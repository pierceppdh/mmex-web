"""Parseur pour relevés carte Boursorama."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from mmex_recon.schemas import BankTransaction, ParsedStatement
from mmex_recon.parsers.base import BaseParser


class BoursoramaCbParser(BaseParser):
    """Parse les relevés de carte Boursorama (CB Premier)."""

    parser_id = "boursorama_cb"
    bank_name = "Boursorama CB"
    priority = 90

    def can_parse(self, text: str, filename: str = "") -> bool:
        fname = self.compact_alnum(filename)
        if "relevecompte" in fname:
            return False
        if "relevecb" in fname:
            return True
        compact = self.compact_alnum(text)
        if "mouvementseneur" in compact:
            return False
        has_card_statement = (
            "relevedecarte" in compact or "porteurdelacarte" in compact
        )
        return has_card_statement and (
            "boursorama" in compact or "boursobank" in compact
        )

    def parse(self, pdf_path: Path) -> ParsedStatement:
        text = self.extract_text(pdf_path)
        iban = self._extract_iban(text)
        card_number = self._extract_card(text)
        period_start, period_end = self._extract_period(text)
        holder = self._extract_holder(text)
        transactions = self._extract_transactions(text)
        total_debit = self._extract_total(text, kind="debit")
        total_credit = self._extract_total(text, kind="credit")

        account_hint = "Visa Boursorama Pierre"
        if card_number and "6161" in card_number:
            account_hint = "Visa Boursorama Cecile"
        elif card_number and "7602" in card_number:
            account_hint = "Visa Boursorama Pierre"

        return ParsedStatement(
            parser_id=self.parser_id,
            bank_name=self.bank_name,
            account_hint=account_hint,
            iban=iban,
            account_number=card_number,
            period_start=period_start,
            period_end=period_end,
            opening_balance=None,
            closing_balance=None,
            currency="EUR",
            transactions=transactions,
            metadata={
                "source_file": pdf_path.name,
                "card_holder": holder,
                "card_number": card_number,
                "period_total_debit": str(total_debit) if total_debit else None,
                "period_total_credit": str(total_credit) if total_credit else None,
                "balance_check_skipped": True,
                "balance_check_reason": (
                    "Relevé CB: total période uniquement, pas de solde compte — vérification manuelle"
                ),
            },
        )

    def _extract_iban(self, text: str) -> str | None:
        match = re.search(r"I\.B\.A\.N\.\s*(FR[\dA-Z\s]{10,40})", text)
        return self.normalize_iban(match.group(1)) if match else None

    def _extract_card(self, text: str) -> str | None:
        match = re.search(r"(\d{4}\*+\d{4})", text)
        return match.group(1) if match else None

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

    def _extract_holder(self, text: str) -> str | None:
        match = re.search(r"Porteurdelacarte:\s*(.+)", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"Porteur de la carte:\s*(.+)", text)
        return match.group(1).strip() if match else None

    def _extract_total(self, text: str, *, kind: str = "debit") -> Decimal | None:
        if kind == "credit":
            match = re.search(r"AVOTRECREDIT.*?(\d+[.,]\d{2})", text, re.IGNORECASE)
        else:
            match = re.search(r"AVOTREDEBIT.*?(\d+[.,]\d{2})", text, re.IGNORECASE)
        if match:
            return self.parse_amount(match.group(1))
        return None

    def _extract_transactions(self, text: str) -> list[BankTransaction]:
        transactions: list[BankTransaction] = []
        in_credit_section = False
        # CARTE… achats ; AVOIR… remboursements (parfois le relevé n'a que des avoirs).
        amount = (
            r"([-+−–]?\s*(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d+[.,]\d{2})-?)\s*(CR)?\s*$"
        )
        typed = re.compile(
            rf"^(\d{{2}}/\d{{2}}/\d{{4}})\s+(CARTE|AVOIR)(\d{{2}}/\d{{2}}/\d{{2}})(.+?)\s+{amount}",
            re.IGNORECASE,
        )
        loose = re.compile(
            rf"^(\d{{2}}/\d{{2}}/\d{{4}})\s+(.+?)\s+{amount}",
        )
        credit_header = re.compile(
            r"^(vos\s+)?avoirs?\b|^(vos\s+)?cr[eéèøØ]dits?\b",
            re.IGNORECASE,
        )
        debit_header = re.compile(
            r"^(vos\s+)?d[eéèøØ]bits?\b|^op[eé]rations?\s+d[eé]bit",
            re.IGNORECASE,
        )

        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if re.match(r"^AVOTRE(DEBIT|CREDIT)", line, re.IGNORECASE):
                continue
            if credit_header.match(line) and not typed.match(line) and not loose.match(line):
                in_credit_section = True
                continue
            if debit_header.match(line) and not typed.match(line):
                in_credit_section = False
                continue

            match = typed.match(line)
            kind = None
            if match:
                tx_date = self.parse_date(match.group(1))
                kind = match.group(2).upper()
                description = match.group(4).strip()
                statement_amount = self.parse_amount(match.group(5))
                is_credit_marker = bool(match.group(6))
            else:
                loose_match = loose.match(line)
                if not loose_match:
                    continue
                tx_date = self.parse_date(loose_match.group(1))
                description = loose_match.group(2).strip()
                statement_amount = self.parse_amount(loose_match.group(3))
                is_credit_marker = bool(loose_match.group(4))
                if description.upper().startswith("AVOIR"):
                    kind = "AVOIR"

            is_credit = (
                kind == "AVOIR"
                or is_credit_marker
                or in_credit_section
                or "AVOIR" in description.upper()
            )
            if tx_date and statement_amount != 0:
                app_amount = self.credit_card_app_amount(
                    statement_amount,
                    is_credit_marker=is_credit,
                )
                transactions.append(
                    BankTransaction(
                        date=tx_date,
                        description=description,
                        amount=app_amount,
                        currency="EUR",
                        raw_text=line,
                    )
                )
        return transactions