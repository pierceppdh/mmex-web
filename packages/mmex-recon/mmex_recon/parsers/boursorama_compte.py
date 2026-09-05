"""Parseur pour relevés compte courant Boursorama."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber

from mmex_recon.schemas import BankTransaction, ParsedStatement
from mmex_recon.parsers.base import BaseParser

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_AMOUNT_RE = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")

# Colonne Date à gauche, Libellé ~95, Valeur ~381, Débit ~442, Crédit ~506.
_DATE_X_MAX = 80.0
_DESC_X_MIN = 80.0
_DESC_X_MAX = 360.0
_AMOUNT_X_MIN = 430.0
_DEFAULT_SPLIT_X = 474.0
_FOOTER_Y = 740.0
_ROW_Y_TOL = 3.0

_FOOTER_MARKERS = (
    "autorisationded",
    "boursorama-sa",
    "www.boursobank",
    "serviceclient",
    "adressedum",
    "garantiedesdepots",
    "n(cid:176)orias",
)


class BoursoramaCompteParser(BaseParser):
    """Parse les extraits de compte Boursorama."""

    parser_id = "boursorama_compte"
    bank_name = "Boursorama"
    priority = 95

    def can_parse(self, text: str, filename: str = "") -> bool:
        fname = self.compact_alnum(filename)
        if "relevecb" in fname:
            return False
        if "relevecompte" in fname:
            return True
        text_lower = text.lower()
        if "postfinance" in text_lower:
            return False
        compact = self.compact_alnum(text)
        # Un virement Yuh vers Boursorama contient le mot BOURSORAMA et « extrait ».
        if "yuh" in fname or "yuh" in compact or "swqbchzz" in compact:
            return False
        if "relevedecarte" in compact or "porteurdelacarte" in compact:
            return False
        return "boursorama" in compact and (
            "extrait" in compact or "mouvementseneur" in compact
        )

    def parse(self, pdf_path: Path) -> ParsedStatement:
        text_parts: list[str] = []
        pages_words: list[list[dict]] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text_parts.append(extracted)
                pages_words.append(page.extract_words(use_text_flow=True) or [])

        text = "\n".join(text_parts)
        iban = self._extract_iban(text)
        period_start, period_end = self._extract_period(text)
        opening = self._extract_opening(text)
        closing = self._extract_closing(text)
        transactions = self._extract_transactions_from_words(pages_words)
        if not transactions:
            transactions = self._extract_transactions(text)

        return ParsedStatement(
            parser_id=self.parser_id,
            bank_name=self.bank_name,
            account_hint="Boursorama",
            iban=iban,
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening,
            closing_balance=closing,
            currency="EUR",
            transactions=transactions,
            metadata={"source_file": pdf_path.name},
        )

    def _extract_iban(self, text: str) -> str | None:
        match = re.search(r"I\.B\.A\.N\.\s*(FR[\dA-Z\s]{10,40})", text)
        return self.normalize_iban(match.group(1)) if match else None

    def _extract_period(self, text: str) -> tuple[date | None, date | None]:
        match = re.search(
            r"du\s+(\d{2}/\d{2}/\d{4})\s*au\s+(\d{2}/\d{2}/\d{4})",
            text,
        )
        if match:
            return (
                self.parse_date(match.group(1)),
                self.parse_date(match.group(2)),
            )
        return None, None

    def _extract_opening(self, text: str) -> Decimal | None:
        match = re.search(r"SOLDEAU:\s*(\d{2}/\d{2}/\d{4})\s+([\d.,]+)", text, re.IGNORECASE)
        if match:
            return self.parse_amount(match.group(2))
        return None

    def _extract_closing(self, text: str) -> Decimal | None:
        match = re.search(r"NouveausoldeenEUR:\s*([\d.,]+)", text, re.IGNORECASE)
        if match:
            return self.parse_amount(match.group(1))
        return None

    def _extract_transactions_from_words(
        self, pages_words: list[list[dict]]
    ) -> list[BankTransaction]:
        """Signe les montants selon la colonne Débit / Crédit (position x)."""
        transactions: list[BankTransaction] = []
        in_table = False
        split_x = _DEFAULT_SPLIT_X
        current: BankTransaction | None = None

        for words in pages_words:
            rows = self._cluster_rows(words)
            page_split = next(
                (s for row in rows if (s := self._split_x_from_headers(row)) is not None),
                None,
            )
            if page_split is not None:
                # En-tête de tableau répété : ignorer le bandeau RIB au-dessus.
                in_table = False
                split_x = page_split

            for row in rows:
                if not row:
                    continue
                top = row[0]["top"]
                if top >= _FOOTER_Y:
                    continue
                joined = "".join(w["text"] for w in row)
                joined_compact = re.sub(r"\s+", "", joined).lower()
                if any(marker in joined_compact for marker in _FOOTER_MARKERS):
                    continue

                row_split = self._split_x_from_headers(row)
                if row_split is not None:
                    split_x = row_split
                    in_table = True
                    continue

                if not in_table:
                    continue

                if "soldeau" in joined_compact:
                    continue
                if "nouveausolde" in joined_compact:
                    in_table = False
                    current = None
                    continue

                left_date = self._left_date(row)
                amount, is_credit = self._amount_in_columns(row, split_x)
                description = self._description_from_row(row)
                value_date = self._value_date(row)
                raw = " ".join(w["text"] for w in sorted(row, key=lambda w: w["x0"]))

                if left_date and amount is not None:
                    signed = amount if is_credit else -amount
                    current = BankTransaction(
                        date=left_date,
                        description=description,
                        amount=signed,
                        currency="EUR",
                        raw_text=raw,
                        value_date=value_date,
                    )
                    transactions.append(current)
                    continue

                if current is not None and description:
                    current.description = f"{current.description} {description}".strip()
                    if raw:
                        current.raw_text = f"{current.raw_text} {raw}".strip()

        return transactions

    @staticmethod
    def _cluster_rows(words: list[dict]) -> list[list[dict]]:
        ordered = sorted(words, key=lambda w: (w["top"], w["x0"]))
        rows: list[list[dict]] = []
        for word in ordered:
            if rows and abs(word["top"] - rows[-1][0]["top"]) <= _ROW_Y_TOL:
                rows[-1].append(word)
            else:
                rows.append([word])
        return rows

    @staticmethod
    def _normalize_header(text: str) -> str:
        return (
            text.lower()
            .replace("ø", "e")
            .replace("é", "e")
            .replace("è", "e")
            .replace("Ø", "e")
        )

    def _split_x_from_headers(self, row: list[dict]) -> float | None:
        debit_x: float | None = None
        credit_x: float | None = None
        for word in row:
            header = self._normalize_header(word["text"])
            if header == "debit":
                debit_x = word["x0"]
            elif header == "credit":
                credit_x = word["x0"]
        if debit_x is not None and credit_x is not None:
            return (debit_x + credit_x) / 2.0
        return None

    def _left_date(self, row: list[dict]) -> date | None:
        for word in row:
            if word["x0"] < _DATE_X_MAX and _DATE_RE.match(word["text"]):
                return self.parse_date(word["text"])
        return None

    def _value_date(self, row: list[dict]) -> date | None:
        for word in row:
            if _DESC_X_MAX <= word["x0"] < _AMOUNT_X_MIN and _DATE_RE.match(word["text"]):
                return self.parse_date(word["text"])
        return None

    def _description_from_row(self, row: list[dict]) -> str:
        parts = [
            word["text"]
            for word in sorted(row, key=lambda w: w["x0"])
            if _DESC_X_MIN <= word["x0"] < _DESC_X_MAX
        ]
        return " ".join(parts).strip()

    def _amount_in_columns(
        self, row: list[dict], split_x: float
    ) -> tuple[Decimal | None, bool]:
        for word in row:
            if word["x0"] < _AMOUNT_X_MIN:
                continue
            if not _AMOUNT_RE.match(word["text"]):
                continue
            amount = self.parse_amount(word["text"])
            return amount, word["x0"] >= split_x
        return None, False

    def _extract_transactions(self, text: str) -> list[BankTransaction]:
        """Repli texte : sans colonnes PDF, le signe Débit/Crédit est perdu."""
        transactions: list[BankTransaction] = []
        lines = text.split("\n")
        i = 0

        tx_start = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.+)$")
        amount_line = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+([\d.,]+)\s*$")
        debit_credit = re.compile(
            r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(\d{2}/\d{2}/\d{4})\s+([\d.,]+)\s*$"
        )

        while i < len(lines):
            line = lines[i].strip()
            i += 1

            if not line or line.startswith("SOLDE"):
                continue
            if "Nouveausolde" in line:
                break

            dcr_match = debit_credit.match(line)
            if dcr_match:
                tx_date = self.parse_date(dcr_match.group(1))
                description = dcr_match.group(2).strip()
                value_date = self.parse_date(dcr_match.group(3))
                amount = self.parse_amount(dcr_match.group(4))
                if tx_date:
                    transactions.append(
                        BankTransaction(
                            date=tx_date,
                            description=description,
                            amount=-amount,
                            currency="EUR",
                            raw_text=line,
                            value_date=value_date,
                        )
                    )
                continue

            start_match = tx_start.match(line)
            if start_match and "SOLDE" not in line:
                tx_date = self.parse_date(start_match.group(1))
                rest = start_match.group(2)

                value_date = None
                amount = None
                description_parts = [rest]

                inline = re.match(
                    r"^(.+?)\s+(\d{2}/\d{2}/\d{4})\s+([\d.,]+)\s*$", rest
                )
                if inline:
                    description_parts = [inline.group(1)]
                    value_date = self.parse_date(inline.group(2))
                    amount = self.parse_amount(inline.group(3))
                else:
                    while i < len(lines):
                        next_line = lines[i].strip()
                        if tx_start.match(next_line) or "Nouveausolde" in next_line:
                            break
                        amt_match = amount_line.match(next_line)
                        if amt_match and amount is None:
                            value_date = self.parse_date(amt_match.group(1))
                            amount = self.parse_amount(amt_match.group(2))
                            i += 1
                            break
                        if re.match(r"^[\d.,]+$", next_line) and amount is None:
                            amount = self.parse_amount(next_line)
                            i += 1
                            break
                        description_parts.append(next_line)
                        i += 1

                if tx_date and amount is not None:
                    transactions.append(
                        BankTransaction(
                            date=tx_date,
                            description=" ".join(description_parts).strip(),
                            amount=-amount,
                            currency="EUR",
                            raw_text=line,
                            value_date=value_date,
                        )
                    )

        return transactions
