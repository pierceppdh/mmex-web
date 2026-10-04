"""Parseur pour les relevés Banque Cler, compte privé Zak."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber

from mmex_recon.schemas import BankTransaction, ParsedStatement
from mmex_recon.parsers.base import BaseParser

# Milliers : apostrophe ASCII ou typographique, espace insécable, espace fine.
_AMOUNT_RE = re.compile(
    r"^-?\d{1,3}(?:[ '\u00a0\u2018\u2019\u202f\u2009]\d{3})*\.\d{2}$"
)
_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2}(?:\d{2})?$")
_ROW_Y_TOL = 2.0
_MARGIN_X = 60.0
_HEADER_CHARS = 2000

# Repères du relevé Zak A4 (secours si l'en-tête de colonnes manque).
_DEFAULT_DEBIT_X = 378.0
_DEFAULT_CREDIT_X = 455.0
_DEFAULT_SOLDE_X = 537.0
_DEFAULT_VALUE_X = 289.0

_CLER_MARKERS = ("bank cler", "bclrchbb", "compte prive zak", "cler.ch")
_OTHER_BANK_MARKERS = ("postfinance", "post finance", "yuh", "boursorama", "swisscard")
_STOP_MARKERS = (
    "volume des transactions",
    "contestation",
    "meilleures salutations",
    "avis sans signature",
)


def _fold(text: str) -> str:
    return (
        text.lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("à", "a")
        .replace("â", "a")
        .replace("ô", "o")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ù", "u")
        .replace("û", "u")
        .replace("ç", "c")
        .replace("°", "")
    )


@dataclass
class _Zones:
    desc_min: float = 110.0
    desc_max: float = 273.0
    value_min: float = 273.0
    debit_left: float = 333.0
    credit_left: float = 416.0
    solde_left: float = 496.0
    booking_max: float = 112.0


def _zones_from_header(row: list[dict]) -> _Zones:
    debit = credit = solde = value = None
    for word in row:
        token = _fold(word["text"])
        x = float(word["x0"])
        if token.startswith("debit"):
            debit = x
        elif token.startswith("credit"):
            credit = x
        elif token == "solde":
            solde = x
        elif token == "date" and x > 180:
            value = x
    debit = _DEFAULT_DEBIT_X if debit is None else debit
    credit = _DEFAULT_CREDIT_X if credit is None else credit
    solde = _DEFAULT_SOLDE_X if solde is None else solde
    value = _DEFAULT_VALUE_X if value is None else value
    # La date de valeur est alignée à gauche de son libellé : on laisse une marge.
    value_min = value - 16.0
    return _Zones(
        desc_max=value_min,
        value_min=value_min,
        debit_left=(value + debit) / 2,
        credit_left=(debit + credit) / 2,
        solde_left=(credit + solde) / 2,
    )


class BanqueClerParser(BaseParser):
    """Parse les relevés « Compte privé Zak » de la Banque Cler."""

    parser_id = "banque_cler"
    bank_name = "Banque Cler"
    # Sous les parseurs carte, Yuh et Boursorama, au-dessus de PostFinance.
    # L'identité est lue dans l'en-tête : un paiement PostFinance vers
    # « BANK CLER AG » ne doit pas être classé comme un relevé Cler.
    priority = 88

    def can_parse(self, text: str, filename: str = "") -> bool:
        folded = _fold(text[:_HEADER_CHARS])
        cler_at = _earliest(folded, _CLER_MARKERS)
        if cler_at is None:
            return False
        other_at = _earliest(folded, _OTHER_BANK_MARKERS)
        if other_at is not None and other_at < cler_at:
            return False
        return True

    def parse(self, pdf_path: Path) -> ParsedStatement:
        text_parts: list[str] = []
        pages_words: list[list[dict]] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text_parts.append(extracted)
                pages_words.append(page.extract_words(use_text_flow=True) or [])
        return self._build("\n".join(text_parts), pages_words, pdf_path.name)

    def _build(
        self,
        text: str,
        pages_words: list[list[dict]],
        filename: str,
    ) -> ParsedStatement:
        iban = self._extract_iban(text)
        account_number = self._extract_account_number(text)
        period_start, period_end = self._extract_period(text)
        currency = self._extract_currency(text)
        opening, closing, transactions = self._extract_entries(pages_words, currency)
        if not transactions and opening is None and closing is None:
            raise ValueError(f"Aucune écriture Banque Cler dans {filename}")
        return ParsedStatement(
            parser_id=self.parser_id,
            bank_name=self.bank_name,
            account_hint="Banque Cler - Zak",
            iban=iban,
            account_number=account_number,
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening,
            closing_balance=closing,
            currency=currency,
            transactions=transactions,
            metadata={"source_file": filename},
        )

    def _extract_iban(self, text: str) -> str | None:
        match = re.search(r"IBAN\s+((?:CH|LI)[0-9A-Z\s]{10,40})", text, re.IGNORECASE)
        if not match:
            return None
        return self.normalize_iban(match.group(1))

    def _extract_account_number(self, text: str) -> str | None:
        match = re.search(r"N[°ºo]\s*(\d{4}\.\d{4}\.\d{4})", text)
        return match.group(1) if match else None

    def _extract_period(self, text: str) -> tuple[date | None, date | None]:
        match = re.search(
            r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})",
            text,
        )
        if not match:
            return None, None
        return self.parse_date(match.group(1)), self.parse_date(match.group(2))

    def _extract_currency(self, text: str) -> str:
        match = re.search(r"compte en\s+(CHF|EUR|USD)", text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        match = re.search(r"\b(CHF|EUR|USD)\b", text)
        return match.group(1).upper() if match else "CHF"

    def _extract_entries(
        self,
        pages_words: list[list[dict]],
        currency: str,
    ) -> tuple[Decimal | None, Decimal | None, list[BankTransaction]]:
        opening: Decimal | None = None
        closing: Decimal | None = None
        transactions: list[BankTransaction] = []
        current: BankTransaction | None = None
        zones = _Zones()
        done = False

        for words in pages_words:
            seen_header = False
            for row in _cluster_rows(words):
                if _is_table_header(row):
                    zones = _zones_from_header(row)
                    seen_header = True
                    continue
                # L'en-tête de page (titulaire, période) est répété avant le tableau.
                if not seen_header:
                    continue
                joined = _row_text(row)
                if _is_stop(joined):
                    done = True
                    break

                booking = _booking_date(row, zones)
                value_date = _value_date(row, zones)
                desc = _description(row, zones)
                debit, credit, balance = _split_amounts(row, zones)
                folded = _fold(desc)

                if booking and "report" in folded and "solde" in folded:
                    if balance is not None and opening is None:
                        opening = balance
                    current = None
                    continue
                if "solde au" in folded:
                    if balance is not None:
                        closing = balance
                    current = None
                    continue
                if booking and (debit is not None or credit is not None):
                    if debit is not None and credit is not None:
                        continue
                    amount = credit if credit is not None else -debit
                    current = BankTransaction(
                        date=booking,
                        description=desc,
                        amount=amount if amount is not None else Decimal("0"),
                        currency=currency,
                        raw_text=joined,
                        value_date=value_date,
                    )
                    transactions.append(current)
                    continue
                if current is not None and desc:
                    current.description = f"{current.description} {desc}".strip()
                    current.raw_text = f"{current.raw_text} {joined}".strip()
            if done:
                break
        return opening, closing, transactions


def _earliest(haystack: str, needles: tuple[str, ...]) -> int | None:
    positions = [haystack.find(needle) for needle in needles]
    found = [pos for pos in positions if pos >= 0]
    return min(found) if found else None


def _cluster_rows(words: list[dict]) -> list[list[dict]]:
    kept = [word for word in words if float(word["x0"]) >= _MARGIN_X]
    ordered = sorted(kept, key=lambda word: (float(word["top"]), float(word["x0"])))
    rows: list[list[dict]] = []
    for word in ordered:
        if rows and abs(float(word["top"]) - float(rows[-1][0]["top"])) <= _ROW_Y_TOL:
            rows[-1].append(word)
        else:
            rows.append([word])
    return rows


def _row_text(row: list[dict]) -> str:
    return " ".join(
        word["text"] for word in sorted(row, key=lambda word: float(word["x0"]))
    )


def _is_table_header(row: list[dict]) -> bool:
    blob = "".join(_fold(word["text"]) for word in row)
    return (
        "date" in blob
        and "texte" in blob
        and "debit" in blob
        and "credit" in blob
        and "solde" in blob
    )


def _is_stop(joined: str) -> bool:
    folded = _fold(joined)
    return any(marker in folded for marker in _STOP_MARKERS)


def _booking_date(row: list[dict], zones: _Zones) -> date | None:
    for word in row:
        x = float(word["x0"])
        if _MARGIN_X <= x < zones.booking_max and _DATE_RE.match(word["text"]):
            return BaseParser.parse_date(word["text"])
    return None


def _value_date(row: list[dict], zones: _Zones) -> date | None:
    for word in row:
        x = float(word["x0"])
        if zones.value_min <= x < zones.debit_left and _DATE_RE.match(word["text"]):
            return BaseParser.parse_date(word["text"])
    return None


def _description(row: list[dict], zones: _Zones) -> str:
    parts = [
        word["text"]
        for word in sorted(row, key=lambda word: float(word["x0"]))
        if zones.desc_min <= float(word["x0"]) < zones.desc_max
        and not _AMOUNT_RE.match(word["text"])
    ]
    return " ".join(parts).strip()


def _split_amounts(
    row: list[dict], zones: _Zones
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    debit: Decimal | None = None
    credit: Decimal | None = None
    balance: Decimal | None = None
    for word in row:
        if not _AMOUNT_RE.match(word["text"]):
            continue
        x = float(word["x0"])
        amount = BaseParser.parse_amount(word["text"])
        if x >= zones.solde_left:
            balance = amount
        elif x >= zones.credit_left:
            credit = abs(amount)
        elif x >= zones.debit_left:
            debit = abs(amount)
    return debit, credit, balance
