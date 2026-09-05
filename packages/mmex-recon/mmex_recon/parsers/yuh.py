"""Parseur pour relevés Yuh (Swissquote) multi-devises."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber

from mmex_recon.schemas import BankTransaction, ParsedStatement
from mmex_recon.parsers.base import BaseParser

_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
# Milliers : apostrophe ASCII, typographique (U+2018/U+2019) ou espace insécable.
_AMOUNT_RE = re.compile(r"^\d{1,3}(?:[ '\u00a0\u2018\u2019]\d{3})*\.\d{2}$")
_DATE_X_MAX = 70.0
_DESC_X_MIN = 70.0
_DESC_X_MAX = 270.0
_DEBIT_X_MIN = 260.0
_CREDIT_X_MIN = 320.0
_SOLDE_X_MIN = 480.0
_VALUE_DATE_X_MIN = 400.0
_FOOTER_Y = 740.0
_ROW_Y_TOL = 3.0


class YuhParser(BaseParser):
    """Parse les extraits Yuh (une tranche par devise)."""

    parser_id = "yuh"
    bank_name = "Yuh"
    # Au-dessus de Boursorama : un virement vers « BOURSORAMA » ne doit pas
    # faire classer le PDF Yuh comme un extrait Boursorama.
    priority = 96

    def can_parse(self, text: str, filename: str = "") -> bool:
        fname = filename.lower()
        if "yuh" in fname:
            return True
        compact = re.sub(r"\s+", "", text.lower())
        if "postfinance" in compact and "yuh" not in compact:
            return False
        return "yuh" in compact or "swqbchzz" in compact or "yuhaccount" in compact

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
        slices = self._extract_currency_slices(pages_words)
        if not slices:
            raise ValueError(f"Aucune tranche de devise Yuh dans {pdf_path.name}")

        order = [code for code in ("CHF", "EUR", "USD") if code in slices] + [
            code for code in slices if code not in {"CHF", "EUR", "USD"}
        ]
        primary_ccy = order[0]
        primary = slices[primary_ccy]
        metadata_slices = {
            code: {
                "opening_balance": (
                    str(data["opening"]) if data["opening"] is not None else None
                ),
                "closing_balance": (
                    str(data["closing"]) if data["closing"] is not None else None
                ),
                "transactions": [
                    {
                        "date": tx.date.isoformat(),
                        "description": tx.description,
                        "amount": str(tx.amount),
                        "currency": tx.currency,
                        "raw_text": tx.raw_text,
                        "value_date": (
                            tx.value_date.isoformat() if tx.value_date else None
                        ),
                    }
                    for tx in data["transactions"]
                ],
            }
            for code, data in slices.items()
        }
        return ParsedStatement(
            parser_id=self.parser_id,
            bank_name=self.bank_name,
            account_hint="Yuh",
            iban=iban,
            period_start=period_start,
            period_end=period_end,
            opening_balance=primary["opening"],
            closing_balance=primary["closing"],
            currency=primary_ccy,
            transactions=primary["transactions"],
            metadata={
                "source_file": pdf_path.name,
                "currency_slices": metadata_slices,
                "available_currencies": order,
            },
        )

    def _extract_iban(self, text: str) -> str | None:
        match = re.search(r"IBAN[:\s]+((?:CH|FR)[\d\s]+)", text, re.IGNORECASE)
        if not match:
            return None
        return self.normalize_iban(match.group(1))

    def _extract_period(self, text: str) -> tuple[date | None, date | None]:
        match = re.search(
            r"[Dd]u\s+(\d{2}\.\d{2}\.\d{4})\s+au\s+(\d{2}\.\d{2}\.\d{4})",
            text,
        )
        if match:
            return self.parse_date(match.group(1)), self.parse_date(match.group(2))
        return None, None

    def _extract_currency_slices(
        self, pages_words: list[list[dict]]
    ) -> dict[str, dict]:
        slices: dict[str, dict] = {}
        current_ccy: str | None = None
        in_table = False
        opening: Decimal | None = None
        closing: Decimal | None = None
        transactions: list[BankTransaction] = []
        current_tx: BankTransaction | None = None

        def flush() -> None:
            nonlocal current_ccy, opening, closing, transactions, current_tx, in_table
            if current_ccy:
                slices[current_ccy] = {
                    "opening": opening,
                    "closing": closing,
                    "transactions": list(transactions),
                }
            current_ccy = None
            in_table = False
            opening = None
            closing = None
            transactions = []
            current_tx = None

        for words in pages_words:
            for row in self._cluster_rows(words):
                if not row or row[0]["top"] >= _FOOTER_Y:
                    continue
                joined = " ".join(w["text"] for w in sorted(row, key=lambda w: w["x0"]))
                compact = re.sub(r"\s+", "", joined).lower()
                if "avis" in compact and "signature" in compact:
                    continue
                if "swissquote" in compact and "finma" in compact:
                    continue

                section = re.search(
                    r"extrait\s+de\s+compte\s+en\s+(CHF|EUR|USD)",
                    joined,
                    re.IGNORECASE,
                )
                if section:
                    flush()
                    current_ccy = section.group(1).upper()
                    continue
                if current_ccy is None:
                    continue

                if self._is_table_header(row):
                    in_table = True
                    continue

                report = re.search(
                    r"soldereport",
                    compact.replace("ø", "e").replace("Ø", "e"),
                )
                if report and not in_table:
                    amount = self._first_amount(row, min_x=150, max_x=_SOLDE_X_MIN)
                    if amount is not None:
                        if opening is None:
                            opening = amount
                        else:
                            closing = amount
                    continue

                if not in_table:
                    continue

                left_date = self._left_date(row)
                desc = self._description(row)
                norm_desc = self._norm_token(desc)
                if left_date and (
                    "ouverture" in norm_desc
                    or "cloture" in norm_desc
                    or "clture" in norm_desc
                ):
                    current_tx = None
                    continue

                debit, credit = self._debit_credit(row)
                value_date = self._value_date(row)
                raw = joined
                if left_date and (debit is not None or credit is not None):
                    amount = credit if credit is not None else -debit
                    current_tx = BankTransaction(
                        date=left_date,
                        description=desc,
                        amount=amount,
                        currency=current_ccy,
                        raw_text=raw,
                        value_date=value_date,
                    )
                    transactions.append(current_tx)
                    continue
                if current_tx is not None and desc:
                    current_tx.description = f"{current_tx.description} {desc}".strip()
                    current_tx.raw_text = f"{current_tx.raw_text} {raw}".strip()

        flush()
        return slices

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
    def _norm_token(text: str) -> str:
        cleaned = re.sub(r"\(cid:\d+\)", "", text)
        return (
            cleaned.lower()
            .replace("ø", "e")
            .replace("é", "e")
            .replace("è", "e")
            .replace("Ø", "e")
        )

    def _is_table_header(self, row: list[dict]) -> bool:
        tokens = [self._norm_token(w["text"]) for w in row]
        blob = "".join(tokens)
        return "date" in blob and "information" in blob and ("bit" in blob or "debit" in blob)

    def _left_date(self, row: list[dict]) -> date | None:
        for word in row:
            if word["x0"] < _DATE_X_MAX and _DATE_RE.match(word["text"]):
                return self.parse_date(word["text"])
        return None

    def _value_date(self, row: list[dict]) -> date | None:
        for word in row:
            if _VALUE_DATE_X_MIN <= word["x0"] < _SOLDE_X_MIN and _DATE_RE.match(word["text"]):
                return self.parse_date(word["text"])
        return None

    def _description(self, row: list[dict]) -> str:
        parts = [
            w["text"]
            for w in sorted(row, key=lambda w: w["x0"])
            if _DESC_X_MIN <= w["x0"] < _DESC_X_MAX
        ]
        return " ".join(parts).strip()

    def _first_amount(
        self, row: list[dict], *, min_x: float, max_x: float
    ) -> Decimal | None:
        for word in sorted(row, key=lambda w: w["x0"]):
            if min_x <= word["x0"] < max_x and _AMOUNT_RE.match(word["text"]):
                return self.parse_amount(word["text"])
        return None

    def _debit_credit(self, row: list[dict]) -> tuple[Decimal | None, Decimal | None]:
        debit = None
        credit = None
        for word in row:
            if not _AMOUNT_RE.match(word["text"]):
                continue
            x = word["x0"]
            if x >= _SOLDE_X_MIN:
                continue
            amount = self.parse_amount(word["text"])
            if _CREDIT_X_MIN <= x < _VALUE_DATE_X_MIN:
                credit = amount
            elif _DEBIT_X_MIN <= x < _CREDIT_X_MIN:
                debit = amount
        return debit, credit
