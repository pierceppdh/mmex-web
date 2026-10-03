"""PostFinance statement lines that are movements, not detail text."""

from datetime import date
from decimal import Decimal

from mmex_recon.balance import check_pdf_balances
from mmex_recon.parsers.postfinance import PostFinanceParser
from mmex_recon.schemas import BalanceStatus, ParsedStatement


def _parse(text: str):
    return PostFinanceParser()._extract_transactions(text)


def test_transfer_and_twint_send_are_movements() -> None:
    text = "\n".join(
        [
            "01.09.26 DÉBIT 28.30 01.09.26",
            "SUNRISE GMBH",
            "09.09.26 ACHAT/PRESTATION TWINT DU 11.50 09.09.26",
            "09.09.2026",
            "LES PAINS",
            "09.09.26 TRANSFERT DU COMPTE 418.21 09.09.26 71 335.54",
            "CH8809000000145848732",
            "Page 2 / 7",
            "Date 01.10.2026",
            "11.09.26 DÉBIT 29.90 11.09.26 71 305.64",
            "SUNRISE GMBH",
            "ACHAT/PRESTATION TWINT DU 85.00 28.09.26",
            "28.09.2026",
            "OPLABIO SA",
            "ENVOI D'ARGENT TWINT DU 105.70 28.09.26 76 475.74",
            "28.09.2026",
            "POUR NUMÉRO MOBILE.",
            "+41760000000",
            "NOM EXEMPLE",
            "29.09.26 ACHAT/PRESTATION TWINT DU 29.90 28.09.26 76 445.84",
            "QOQA",
        ]
    )
    txs = _parse(text)
    assert len(txs) == 7
    by_amount = {tx.amount: tx for tx in txs}
    transfer = by_amount[Decimal("418.21")]
    assert transfer.date == date(2026, 9, 9)
    assert transfer.value_date == date(2026, 9, 9)
    assert "TRANSFERT DU COMPTE" in transfer.description
    assert "CH8809000000145848732" in transfer.description
    assert "Date 01.10.2026" not in transfer.description

    send = by_amount[Decimal("-105.70")]
    assert send.date == date(2026, 9, 28)
    assert "ENVOI D'ARGENT TWINT" in send.description
    assert "NOM EXEMPLE" in send.description
    # The send must not be swallowed by the previous Twint purchase.
    purchase = by_amount[Decimal("-85.00")]
    assert "105.70" not in purchase.description
    assert "ENVOI" not in purchase.description


def test_page_header_and_footer_stay_out_of_descriptions() -> None:
    text = "\n".join(
        [
            "24.09.26 ACHAT/SERVICE DU 24.09.2026 4.45 24.09.26",
            "CARTE NO XXXX1249",
            "COOP",
            "Page 4 / 7",
            "Date 01.10.2026",
            "IBAN CH5309000000146121835",
            "Date Texte Crédit Débit Valeur Solde",
            "30.09.26 ACHAT/PRESTATION TWINT DU 17.00 30.09.26 69 950.39",
            "30.09.2026",
            "COMMERCE",
            "Total 22 028.61 25 753.88",
            "30.09.26 Etat de compte 69 950.39",
            "Veuillez contrôler l'extrait de compte. Sauf avis contraire de votre part dans les 30 jours, il sera considéré",
            "comme accepté.",
            "Des informations sur la manière dont PostFinance traite vos données personnelles sont disponibles dans",
            "notre déclaration générale de protection des données.",
        ]
    )
    txs = _parse(text)
    assert len(txs) == 2
    assert txs[0].description == "ACHAT/SERVICE CARTE NO XXXX1249 COOP"
    assert txs[1].description == "ACHAT/PRESTATION TWINT 30.09.2026 COMMERCE"
    assert "comme accepté" not in txs[1].description
    assert "déclaration" not in txs[1].description


def test_transfer_and_send_keep_pdf_balance() -> None:
    text = "\n".join(
        [
            "31.08.26 Etat de compte 100.00",
            "01.09.26 DÉBIT 10.00 01.09.26",
            "PAYEE",
            "02.09.26 TRANSFERT DU COMPTE 40.00 02.09.26 130.00",
            "CH1200000000000000000",
            "ENVOI D'ARGENT TWINT DU 5.00 03.09.26 125.00",
            "03.09.2026",
            "POUR NUMÉRO MOBILE.",
            "30.09.26 Etat de compte 125.00",
        ]
    )
    parser = PostFinanceParser()
    txs = parser._extract_transactions(text)
    statement = ParsedStatement(
        parser_id="postfinance",
        bank_name="PostFinance",
        account_hint="test",
        opening_balance=parser._extract_opening(text),
        closing_balance=parser._extract_closing(text),
        transactions=txs,
    )
    check = check_pdf_balances(statement)
    assert len(txs) == 3
    assert check.status == BalanceStatus.GREEN
    assert check.computed_closing == Decimal("125.00")
