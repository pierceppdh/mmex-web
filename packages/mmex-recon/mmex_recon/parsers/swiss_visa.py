"""Parseur pour relevés Swiss Visa Cashback (Swisscard AECS)."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from mmex_recon.schemas import BankTransaction, ParsedStatement
from mmex_recon.parsers.base import BaseParser


class SwissVisaParser(BaseParser):
    """Parse les factures Cashback Visa/American Express."""

    parser_id = "swiss_visa"
    bank_name = "Swisscard Cashback"
    priority = 100

    def can_parse(self, text: str, filename: str = "") -> bool:
        fname_lower = filename.lower()
        header = text[:1500].lower()
        if "postfinance" in header:
            return False
        if "boursorama" in header:
            return False
        markers = ["swisscard aecs", "cashback-cards", "cashback cards"]
        if any(m in header for m in markers):
            return True
        if "swisscard" in fname_lower or "cashback visa" in fname_lower:
            return True
        return "numéro de compte" in header and "cashback" in header

    def parse(self, pdf_path: Path) -> ParsedStatement:
        text = self.extract_text(pdf_path)
        account_number = self._extract_account_number(text)
        period_start, period_end = self._extract_period(text)
        opening, closing, closing_in_customer_favor = self._extract_balances(text)
        currency = "CHF"

        transactions = self._extract_transactions(text)

        return ParsedStatement(
            parser_id=self.parser_id,
            bank_name=self.bank_name,
            account_hint="Visa Cashback",
            account_number=account_number,
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening,
            closing_balance=closing,
            currency=currency,
            transactions=transactions,
            metadata={
                "source_file": pdf_path.name,
                "balance_formula": "credit_card",
                "closing_in_customer_favor": closing_in_customer_favor,
            },
        )

    def _extract_account_number(self, text: str) -> str | None:
        match = re.search(r"Numéro de compte\s+([\d\s']+)", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"Cashback\s+([\d\s']+)", text)
        return match.group(1).strip() if match else None

    def _extract_period(self, text: str) -> tuple[date | None, date | None]:
        match = re.search(
            r"Période de facturation\s+(\d{2}\.\d{2}\.\d{2})\s*[–-]\s*(\d{2}\.\d{2}\.\d{2})",
            text,
        )
        if match:
            return (
                self.parse_date(match.group(1)),
                self.parse_date(match.group(2)),
            )
        return None, None

    def _closing_in_customer_favor(self, text: str) -> bool:
        """True si le nouveau solde est « en votre faveur » (crédit client)."""
        match = re.search(
            r"Nouveau\s+solde\s+en[\s\S]{0,240}?\b(votre|notre)\s+faveur",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).lower() == "votre"
        return bool(re.search(r"\bvotre\s+faveur\b", text, re.IGNORECASE))

    def _extract_balances(
        self, text: str
    ) -> tuple[Decimal | None, Decimal | None, bool]:
        opening = None
        closing = None
        amount = r"[-+−]?\s*[\d'.,]+-?"
        in_favor = self._closing_in_customer_favor(text)

        match = re.search(
            r"Solde dernière\s+.*?facture\s+.*?"
            rf"CHF\s+({amount})\s+CHF\s+{amount}\s+CHF\s+{amount}\s+CHF\s+({amount})",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            opening = self.parse_amount(match.group(1))
            closing = self.parse_amount(match.group(2))
        else:
            match = re.search(
                rf"Total des nouvelles transactions\s+({amount})",
                text,
                re.IGNORECASE,
            )
            if match:
                closing = self.parse_amount(match.group(1))

        # Crédit client (vous avez trop payé) : montant dû négatif sur le PDF,
        # affiché positif « en votre faveur ». L'arithmétique carte utilise
        # encore la convention « dû » (voir BalanceChecker).
        if closing is not None and (in_favor or closing < 0):
            in_favor = True
            closing = abs(closing)

        return opening, closing, in_favor

    @staticmethod
    def _normalize_line(line: str) -> str:
        return (
            line.replace("\u2013", "-")
            .replace("\u2014", "-")
            .replace("\u00a0", " ")
            .strip()
        )

    def _extract_payments(self, text: str) -> list[BankTransaction]:
        """Extrait les paiements de facture, indépendamment de la section."""
        payment_pattern = re.compile(
            r"(\d{2}\.\d{2}\.\d{4})\s+VOTRE\s+PAIEMENT[^\d\n]*([\d'.,]+)",
            re.IGNORECASE,
        )
        payments: list[BankTransaction] = []
        seen: set[tuple[date, Decimal]] = set()

        for match in payment_pattern.finditer(text):
            tx_date = self.parse_date(match.group(1))
            amount = self.parse_amount(match.group(2))
            if not tx_date or amount <= 0:
                continue
            key = (tx_date, amount)
            if key in seen:
                continue
            seen.add(key)
            payments.append(
                BankTransaction(
                    date=tx_date,
                    description="VOTRE PAIEMENT",
                    amount=amount,
                    currency="CHF",
                    raw_text=match.group(0).strip(),
                )
            )

        return payments

    def _extract_transactions(self, text: str) -> list[BankTransaction]:
        transactions = self._extract_payments(text)
        current_holder: str | None = None
        section: str | None = None

        # Montant signé en fin de ligne (achats positifs, crédits négatifs / CR).
        tx_pattern = re.compile(
            r"^(\d{2}\.\d{2}\.\d{4})\s+(.+?)\s+"
            r"([-+−–]?\s*[\d'.,]+-?)\s*(CR)?\s*$",
            re.IGNORECASE,
        )
        card_header = re.compile(
            r"^\d{4}\s+\d{2}XXXX\s+X\d{4}\s+(.+?)\s+Cashback"
        )
        payments_header = re.compile(r"^Vos\s+paiements(?:\s|$)", re.IGNORECASE)
        transactions_header = re.compile(r"^Nouvelles\s+transactions(?:\s|$)", re.IGNORECASE)
        # Sections de crédits / avoirs éventuelles
        credits_header = re.compile(
            r"^(Vos\s+crédits|Nouveaux\s+crédits|Crédits|Avoirs)\b",
            re.IGNORECASE,
        )

        for raw_line in text.split("\n"):
            line = self._normalize_line(raw_line)
            if not line:
                continue

            if payments_header.match(line):
                section = "payments"
                continue
            if transactions_header.match(line):
                section = "transactions"
                continue
            if credits_header.match(line):
                section = "credits"
                continue
            if line.startswith("Total des nouvelles transactions"):
                break

            card_match = card_header.match(line)
            if card_match:
                current_holder = card_match.group(1).strip()
                section = "transactions"
                continue

            if section not in ("transactions", "credits"):
                continue

            if line.startswith("Report ") or line.startswith("Total "):
                continue
            if "CHF " in line and "supplément" in line:
                continue
            if re.search(r"VOTRE\s+PAIEMENT", line, re.IGNORECASE):
                continue

            tx_match = tx_pattern.match(line)
            if tx_match:
                tx_date = self.parse_date(tx_match.group(1))
                description = tx_match.group(2).strip()
                statement_amount = self.parse_amount(tx_match.group(3))
                is_credit_marker = bool(tx_match.group(4)) or section == "credits"
                if tx_date and statement_amount != 0:
                    app_amount = self.credit_card_app_amount(
                        statement_amount,
                        is_credit_marker=is_credit_marker,
                    )
                    transactions.append(
                        BankTransaction(
                            date=tx_date,
                            description=description,
                            amount=app_amount,
                            currency="CHF",
                            raw_text=line,
                            card_holder=current_holder,
                        )
                    )

        return transactions