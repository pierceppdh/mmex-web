"""Swisscard Cashback statements, including the World Mastercard layout."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from mmex_domain.recon import match_statement_account
from mmex_recon.parsers.swiss_visa import SwissVisaParser


GLUED = """
Numérodecompte 40008761658
Périodedefacturation 12.10.26–05.11.26
Soldedernière facture
CHF0.00 CHF0.00 CHF751.50 CHF751.50 CHF50.00
Nouvellestransactions
377660XXXXX7101LUDIVINEPRUD'HOMMECashbackAmericanExpress
15.10.2026 GOOGLE*PLAYBOOKS 7.40
16.10.2026 MEMBERGETMEMBER -40.00
510021XXXXXX7377LUDIVINEPRUD'HOMMECashbackWorldMastercard
14.10.2026 GOOGLE*RECIPEKEEPER 15.25
26.10.2026 ELAIASTUDIO 359.00
Totaldesnouvellestransactions 751.50
"""

SPACED = """
Numéro de compte 4000 8761 658
Période de facturation 12.10.26 – 05.11.26
Solde dernière facture
CHF 0.00 CHF 0.00 CHF 751.50 CHF 751.50 CHF 50.00
Nouvelles transactions
3776 60XXXX X7101 LUDIVINE PRUD'HOMME Cashback American Express
15.10.2026 GOOGLE *PLAY BOOKS 7.40
5100 21XX XXXX 7377 LUDIVINE PRUD'HOMME Cashback World Mastercard
14.10.2026 GOOGLE *RECIPE KEEPER 15.25
26.10.2026 ELAIA STUDIO 359.00
Total des nouvelles transactions 751.50
"""


def test_glued_cashback_keeps_both_card_sections() -> None:
    parser = SwissVisaParser()
    txs = parser._extract_transactions(GLUED)
    assert [(t.date, t.amount, t.description) for t in txs] == [
        (date(2026, 10, 15), Decimal("-7.40"), "GOOGLE*PLAYBOOKS"),
        (date(2026, 10, 16), Decimal("40.00"), "MEMBERGETMEMBER"),
        (date(2026, 10, 14), Decimal("-15.25"), "GOOGLE*RECIPEKEEPER"),
        (date(2026, 10, 26), Decimal("-359.00"), "ELAIASTUDIO"),
    ]
    assert parser._extract_period(GLUED) == (date(2026, 10, 12), date(2026, 11, 5))
    opening, closing, _ = parser._extract_balances(GLUED)
    assert opening == Decimal("0.00")
    assert closing == Decimal("751.50")


def test_spaced_mastercard_header_names_the_holder() -> None:
    txs = SwissVisaParser()._extract_transactions(SPACED)
    mastercard = [t for t in txs if t.date == date(2026, 10, 26)]
    assert mastercard[0].card_holder == "LUDIVINE PRUD'HOMME"
    assert mastercard[0].amount == Decimal("-359.00")


def test_statement_number_prefers_ludivine_over_visa_cashback() -> None:
    parser = SwissVisaParser()
    number = parser._extract_account_number(SPACED)
    assert number.replace(" ", "") == "40008761658"

    class Statement:
        parser_id = "swiss_visa"
        bank_name = "Swisscard Cashback"
        account_hint = "Mastercard cashback"
        account_number = number
        iban = None
        currency = "CHF"
        metadata = {"balance_formula": "credit_card"}

        def card_last4(self):
            return None

    accounts = [
        {
            "account_id": 3,
            "name": "Visa Cashback",
            "account_num": "1001 6369 059",
            "account_type": "Credit Card",
            "status": "Open",
            "currency": "CHF",
        },
        {
            "account_id": 1794058294602000,
            "name": "Mastercard cashback Ludivine",
            "account_num": "4000 8761 658",
            "account_type": "Credit Card",
            "status": "Open",
            "currency": "CHF",
        },
    ]
    matched = match_statement_account(Statement(), accounts)
    assert matched is not None
    assert matched["account_id"] == 1794058294602000


def test_live_ludivine_pdf_if_present() -> None:
    pdf = Path("/tmp/mmex-stmt/ludivine-mc.pdf")
    if not pdf.is_file():
        return
    statement = SwissVisaParser().parse(pdf)
    assert statement.account_hint == "Mastercard cashback"
    assert statement.account_number is not None
    assert statement.account_number.replace(" ", "") == "40008761658"
    assert statement.opening_balance == Decimal("0.00")
    assert statement.closing_balance == Decimal("751.50")
    assert len(statement.transactions) == 20
    assert sum(t.amount for t in statement.transactions) == Decimal("-751.50")
