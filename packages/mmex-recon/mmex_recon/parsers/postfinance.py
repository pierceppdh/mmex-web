"""Parseur pour relevés PostFinance."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from mmex_recon.schemas import BankTransaction, ParsedStatement
from mmex_recon.parsers.base import BaseParser

# Montant CH: 10.00, 1'978.85, 7 629.70, 10 000.00
_AMOUNT = r"(?:\d{1,3}(?:[\s']\d{3})*|\d+)(?:\.\d{2})?"
_OPTIONAL_BALANCE = rf"(?:\s+{_AMOUNT})?"


class PostFinanceParser(BaseParser):
    """Parse les extraits de compte PostFinance."""

    parser_id = "postfinance"
    bank_name = "PostFinance"
    priority = 85

    _SKIP_PREFIXES = (
        "Extrait de compte",
        "IBAN",
        "Numéro de compte",
        "BIC",
        "Page",
        "Date:",
        "Date Texte",
        "Total ",
        "Des informations",
        "Veuillez contrôler",
        "Avec nos meilleures",
        "PostFinance SA",
        "Monsieur",
        "Prud'",
        "Chemin de",
        "Compte privé",
        "Régler des achats",
        "www.postfinance",
        "Téléphone",
        "Vous êtes conseillé",
    )
    _SKIP_EXACT = {"00.230000", "RF", "65600", "Post CH AG", "P.P."}

    def can_parse(self, text: str, filename: str = "") -> bool:
        text_lower = text.lower()
        fname = filename.lower()
        return (
            "postfinance" in text_lower
            or "post finance" in text_lower
            or "postfinance" in fname
            or "pofichbexxx" in text_lower
        )

    def parse(self, pdf_path: Path) -> ParsedStatement:
        text = self.extract_text(pdf_path)
        iban = self._extract_iban(text)
        account_number = self._extract_account_number(text)
        period_start, period_end = self._extract_period(text)
        opening = self._extract_opening(text)
        closing = self._extract_closing(text)
        transactions = self._extract_transactions(text)

        return ParsedStatement(
            parser_id=self.parser_id,
            bank_name=self.bank_name,
            account_hint="Postfinance Cécile et Pierre",
            iban=iban,
            account_number=account_number,
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening,
            closing_balance=closing,
            currency="CHF",
            transactions=transactions,
            metadata={"source_file": pdf_path.name},
        )

    def _extract_iban(self, text: str) -> str | None:
        match = re.search(r"IBAN\s+(CH[\d\s]+)", text)
        return match.group(1).replace(" ", "") if match else None

    def _extract_account_number(self, text: str) -> str | None:
        match = re.search(r"Numéro de compte\s+([\d-]+)", text)
        return match.group(1) if match else None

    def _extract_period(self, text: str) -> tuple[date | None, date | None]:
        match = re.search(
            r"Extrait de compte\s+(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})",
            text,
        )
        if match:
            return (
                self.parse_date(match.group(1)),
                self.parse_date(match.group(2)),
            )
        return None, None

    def _extract_opening(self, text: str) -> Decimal | None:
        matches = re.findall(
            rf"\d{{2}}\.\d{{2}}\.\d{{2}}\s+Etat de compte\s+({_AMOUNT})",
            text,
        )
        if matches:
            return self.parse_amount(matches[0])
        return None

    def _extract_closing(self, text: str) -> Decimal | None:
        matches = re.findall(
            rf"\d{{2}}\.\d{{2}}\.\d{{2}}\s+Etat de compte\s+({_AMOUNT})",
            text,
        )
        if len(matches) >= 2:
            return self.parse_amount(matches[-1])
        if matches:
            return self.parse_amount(matches[0])
        return None

    def _is_transaction_start(self, line: str) -> re.Match | None:
        patterns = [
            rf"^(\d{{2}}\.\d{{2}}\.\d{{2}})\s+(DÉBIT|CRÉDIT)\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^(DÉBIT|CRÉDIT)\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^(\d{{2}}\.\d{{2}}\.\d{{2}})\s+CHARGE CPTE CARTE DE\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^CHARGE CPTE CARTE DE\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^(\d{{2}}\.\d{{2}}\.\d{{2}})\s+RÉCEPTION D'ARGENT TWINT DU\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^RÉCEPTION D'ARGENT TWINT DU\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^(\d{{2}}\.\d{{2}}\.\d{{2}})\s+ACHAT/PRESTATION TWINT DU\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^ACHAT/PRESTATION TWINT DU\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^(\d{{2}}\.\d{{2}}\.\d{{2}})\s+RETOUR DE MARCHANDISE TWINT\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^RETOUR DE MARCHANDISE TWINT\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^(\d{{2}}\.\d{{2}}\.\d{{2}})\s+RETOUR DE VOTRE PAIEMENT\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^RETOUR DE VOTRE PAIEMENT\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^(\d{{2}}\.\d{{2}}\.\d{{2}})\s+ACHAT/SERVICE DU\s+(\d{{2}}\.\d{{2}}\.\d{{4}})\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^ACHAT/SERVICE DU\s+(\d{{2}}\.\d{{2}}\.\d{{4}})\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^(\d{{2}}\.\d{{2}}\.\d{{2}})\s+PRIX POUR\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^PRIX POUR\s+({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}}){_OPTIONAL_BALANCE}$",
            rf"^(\d{{2}}\.\d{{2}}\.\d{{2}})\s+BOUCLEMENT DES INTERETS.*?({_AMOUNT})\s+(\d{{2}}\.\d{{2}}\.\d{{2}})$",
        ]
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                return match
        return None

    def _parse_transaction_start(
        self, line: str, match: re.Match
    ) -> tuple[date | None, Decimal | None, bool, date | None, str]:
        if "ACHAT/SERVICE" in line:
            if re.match(r"^\d{2}\.\d{2}\.\d{2}\s+ACHAT/SERVICE", line):
                tx_date = self.parse_date(match.group(1))
                amount = self.parse_amount(match.group(3))
                value_date = self.parse_date(match.group(4))
            else:
                purchase_date = match.group(1)
                amount = self.parse_amount(match.group(2))
                value_date = self.parse_date(match.group(3))
                tx_date = value_date or self.parse_date(purchase_date, ["%d.%m.%Y"])
            return tx_date, amount, False, value_date, "ACHAT/SERVICE"

        if "BOUCLEMENT DES INTERETS" in line:
            tx_date = self.parse_date(match.group(1))
            amount = self.parse_amount(match.group(2))
            value_date = self.parse_date(match.group(3))
            return tx_date, amount, False, value_date, "BOUCLEMENT INTERETS"

        if "CHARGE CPTE CARTE" in line:
            if re.match(r"\d{2}\.\d{2}\.\d{2}", match.group(1)):
                value_date = self.parse_date(match.group(3))
                amount = self.parse_amount(match.group(2))
            else:
                value_date = self.parse_date(match.group(2))
                amount = self.parse_amount(match.group(1))
            return value_date, amount, False, value_date, "CHARGE CPTE CARTE"

        if "RETOUR DE MARCHANDISE TWINT" in line or "RETOUR DE VOTRE PAIEMENT" in line:
            label = (
                "RETOUR DE MARCHANDISE TWINT"
                if "MARCHANDISE" in line
                else "RETOUR DE VOTRE PAIEMENT"
            )
            if re.match(r"\d{2}\.\d{2}\.\d{2}", match.group(1)):
                tx_date = self.parse_date(match.group(1))
                amount = self.parse_amount(match.group(2))
                value_date = self.parse_date(match.group(3))
            else:
                amount = self.parse_amount(match.group(1))
                value_date = self.parse_date(match.group(2))
                tx_date = value_date
            return tx_date, amount, True, value_date, label

        if "PRESTATION TWINT" in line:
            if re.match(r"\d{2}\.\d{2}\.\d{2}", match.group(1)):
                tx_date = self.parse_date(match.group(1))
                amount = self.parse_amount(match.group(2))
                value_date = self.parse_date(match.group(3))
            else:
                amount = self.parse_amount(match.group(1))
                value_date = self.parse_date(match.group(2))
                tx_date = value_date
            return tx_date, amount, False, value_date, "ACHAT/PRESTATION TWINT"

        if "TWINT" in line:
            if re.match(r"\d{2}\.\d{2}\.\d{2}", match.group(1)):
                tx_date = self.parse_date(match.group(1))
                amount = self.parse_amount(match.group(2))
                value_date = self.parse_date(match.group(3))
            else:
                amount = self.parse_amount(match.group(1))
                value_date = self.parse_date(match.group(2))
                tx_date = value_date
            return tx_date, amount, True, value_date, "TWINT"

        if "PRIX POUR" in line:
            if re.match(r"\d{2}\.\d{2}\.\d{2}", match.group(1)):
                tx_date = self.parse_date(match.group(1))
                amount = self.parse_amount(match.group(2))
                value_date = self.parse_date(match.group(3))
            else:
                amount = self.parse_amount(match.group(1))
                value_date = self.parse_date(match.group(2))
                tx_date = value_date
            return tx_date, amount, False, value_date, "PRIX POUR"

        groups = match.groups()
        if groups[0] and re.match(r"\d{2}\.\d{2}\.\d{2}", groups[0]):
            tx_date = self.parse_date(groups[0])
            trans_type = groups[1]
            amount = self.parse_amount(groups[2])
            value_date = self.parse_date(groups[3])
        else:
            trans_type = groups[0]
            amount = self.parse_amount(groups[1])
            value_date = self.parse_date(groups[2])
            tx_date = value_date

        is_credit = trans_type == "CRÉDIT"
        return tx_date, amount, is_credit, value_date, ""

    def _should_skip_line(self, line: str) -> bool:
        if not line or line in self._SKIP_EXACT:
            return True
        if any(line.startswith(prefix) for prefix in self._SKIP_PREFIXES):
            return True
        if re.match(r"^\d{2}\.\d{2}\.\d{2}\s+Etat de compte\s+", line):
            return True
        if re.match(r"^CH[A-Z0-9]{10,}$", line):
            return True
        if re.match(r"^00\.\d{6}$", line):
            return True
        return False

    def _extract_transactions(self, text: str) -> list[BankTransaction]:
        transactions: list[BankTransaction] = []
        lines = text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            i += 1

            if self._should_skip_line(line):
                continue

            start_match = self._is_transaction_start(line)
            if not start_match:
                continue

            tx_date, amount, is_credit, value_date, label = self._parse_transaction_start(
                line, start_match
            )
            description_parts: list[str] = []
            if label:
                description_parts.append(label)

            while i < len(lines):
                next_line = lines[i].strip()
                if self._is_transaction_start(next_line) or self._should_skip_line(next_line):
                    if self._is_transaction_start(next_line):
                        break
                    i += 1
                    continue
                description_parts.append(next_line)
                i += 1

            if tx_date and amount is not None and amount != 0:
                desc = " ".join(description_parts).strip() or "Transaction PostFinance"
                signed = amount if is_credit else -amount
                transactions.append(
                    BankTransaction(
                        date=tx_date,
                        description=desc[:200],
                        amount=signed,
                        currency="CHF",
                        raw_text=line,
                        value_date=value_date,
                    )
                )

        return transactions