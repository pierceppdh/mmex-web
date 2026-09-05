"""Classe de base pour les parseurs de relevés bancaires."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import pdfplumber

from mmex_recon.schemas import BankTransaction, ParsedStatement


class BaseParser(ABC):
    """Parseur abstrait pour relevés PDF."""

    parser_id: str = "base"
    bank_name: str = "Unknown"
    priority: int = 0

    @staticmethod
    def compact_alnum(text: str) -> str:
        """Minuscule, chiffres/lettres uniquement (noms Releve_CB vs Releve-CB)."""
        folded = (
            text.lower()
            .replace("ø", "e")
            .replace("é", "e")
            .replace("è", "e")
            .replace("ê", "e")
        )
        return re.sub(r"[^a-z0-9]+", "", folded)

    @abstractmethod
    def can_parse(self, text: str, filename: str = "") -> bool:
        """Détecte si ce parseur peut traiter le document."""

    @abstractmethod
    def parse(self, pdf_path: Path) -> ParsedStatement:
        """Extrait les transactions du PDF."""

    _IBAN_LENGTHS = {"FR": 27, "CH": 21, "DE": 22, "GB": 22, "BE": 16, "IT": 27}

    @classmethod
    def normalize_iban(cls, raw: str | None) -> str | None:
        if not raw:
            return None
        compact = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
        if len(compact) < 15:
            return None
        length = cls._IBAN_LENGTHS.get(compact[:2], 27)
        return compact[:length]

    def extract_text(self, pdf_path: Path) -> str:
        """Extrait tout le texte du PDF."""
        parts: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def parse_amount(value: str) -> Decimal:
        """Parse un montant (formats CH/EU), y compris signe − / CR trailing."""
        cleaned = value.strip()
        cleaned = (
            cleaned.replace("'", "")
            .replace("\u2019", "")  # apostrophe typographique Yuh
            .replace("\u2018", "")
            .replace(" ", "")
            .replace("\u00a0", "")
        )
        # Tirets typographiques → signe ASCII
        cleaned = (
            cleaned.replace("\u2212", "-")  # minus
            .replace("\u2013", "-")  # en-dash
            .replace("\u2014", "-")  # em-dash
        )
        negative = False
        if cleaned.startswith("(") and cleaned.endswith(")"):
            negative = True
            cleaned = cleaned[1:-1]
        if cleaned.endswith("-"):
            negative = True
            cleaned = cleaned[:-1]
        if cleaned.startswith("+"):
            cleaned = cleaned[1:]
        if cleaned.startswith("-"):
            negative = True
            cleaned = cleaned[1:]
        # Format européen: 1.234,56 ou 1234,56
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            amount = Decimal(cleaned)
        except InvalidOperation:
            return Decimal("0")
        return -amount if negative else amount

    @staticmethod
    def credit_card_app_amount(
        statement_amount: Decimal,
        *,
        is_credit_marker: bool = False,
    ) -> Decimal:
        """Convertit un montant de relevé carte vers la convention app.

        Sur le relevé carte :
        - achat / débit : montant positif (souvent sans signe)
        - crédit / remboursement : montant négatif, ou marqueur CR

        Convention app (comme comptes courants) :
        - positif = crédit (Deposit MMEX)
        - négatif = débit (Withdrawal MMEX)
        """
        if statement_amount == 0:
            return Decimal("0")
        if is_credit_marker or statement_amount < 0:
            return abs(statement_amount)
        return -abs(statement_amount)

    @staticmethod
    def parse_date(value: str, formats: Optional[list[str]] = None) -> Optional[date]:
        """Parse une date avec plusieurs formats."""
        value = value.strip()
        formats = formats or [
            "%d.%m.%Y",
            "%d.%m.%y",
            "%d/%m/%Y",
            "%d/%m/%y",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalise le texte extrait du PDF."""
        # Remplace les caractères CID encodés courants
        text = re.sub(r"\(cid:\d+\)", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()