"""Relevé Banque Cler, compte privé Zak."""

from datetime import date
from decimal import Decimal

from mmex_domain.recon import (
    expected_account_type,
    match_statement_account,
    suggest_account_id,
)
from mmex_recon.balance import check_pdf_balances
from mmex_recon.parsers.banque_cler import BanqueClerParser
from mmex_recon.parsers.postfinance import PostFinanceParser
from mmex_recon.parsers.registry import ParserRegistry
from mmex_recon.schemas import BalanceStatus


def _word(text: str, x: float, y: float) -> dict:
    return {"text": text, "x0": x, "top": y}


def _line(y: float, cells: list[tuple[str, float]]) -> list[dict]:
    return [_word(text, x, y) for text, x in cells]


def _statement_pages() -> tuple[str, list[list[dict]]]:
    """Colonnes calées sur le relevé Zak : débit ~365, crédit ~444, solde ~528."""
    text = "\n".join(
        [
            "Bank Cler AG",
            "www.cler.ch/contact",
            "BIC/Swift BCLRCHBB",
            "Compte privé Zak",
            "IBAN CH12 0000 0000 0000 0000 1",
            "N° 2612.0000.0001 CHF",
            "Relevé de compte en CHF",
            "01.09.2026 - 30.09.2026",
            "Paiement PostFinance plus loin dans le texte",
        ]
    )
    header = [
        ("Date", 73.70),
        ("Texte", 114.80),
        ("Date", 288.70),
        ("de", 309.98),
        ("Débit", 378.11),
        ("Crédit", 454.57),
        ("Solde", 536.77),
    ]
    page1 = [
        *_line(306.18, [("01.09.2026", 70.86), ("-", 126.63), ("30.09.2026", 133.43)]),
        *_line(346.41, header),
        *_line(357.82, [("valeur", 295.47)]),
        *_line(
            378.24,
            [("31.08.26", 73.70), ("Report", 114.80), ("de", 143.33), ("solde", 154.64), ("0.00", 541.35)],
        ),
        *_line(
            398.10,
            [
                ("25.09.26", 73.70),
                ("Client", 114.80),
                ("Exemple", 170.00),
                ("25.09.26", 286.21),
                ("1'686.30", 444.37),
                ("1'686.30", 523.74),
            ],
        ),
        *_line(409.51, [("Ref", 114.80), ("ALPHA", 150.00)]),
        *_line(
            463.59,
            [
                ("30.09.26", 73.70),
                ("Assureur", 114.80),
                ("SA", 160.00),
                ("30.09.26", 286.21),
                ("1'686.30", 365.01),
                ("0.00", 541.35),
            ],
        ),
        *_line(475.00, [("No", 114.80), ("1084890.01.01,", 129.73)]),
        *_line(
            529.08,
            [
                ("30.09.26", 73.70),
                ("Assureur", 114.80),
                ("SA", 160.00),
                ("30.09.26", 286.21),
                ("404.80", 372.69),
                ("-404.80", 528.17),
            ],
        ),
        *_line(540.48, [("No", 114.80), ("1084890.01.02,", 129.73)]),
        *_line(
            594.56,
            [
                ("30.09.26", 73.70),
                ("Client", 114.80),
                ("Exemple", 170.00),
                ("30.09.26", 286.21),
                ("404.80", 452.06),
                ("0.00", 541.35),
            ],
        ),
        *_line(605.97, [("Ref", 114.80), ("BETA", 150.00)]),
        *_line(806.84, [("Page", 514.53), ("1/2", 546.86)]),
    ]
    page2 = [
        *_line(
            128.30,
            [
                ("Relevé", 70.86),
                ("de", 123.37),
                ("compte", 145.95),
                ("en", 207.60),
                ("CHF", 229.82),
            ],
        ),
        *_line(150.28, [("01.09.2026", 70.86), ("-", 126.63), ("30.09.2026", 133.43)]),
        *_line(190.51, header),
        *_line(201.92, [("valeur", 295.47)]),
        *_line(
            222.35,
            [("Solde", 114.80), ("au", 138.28), ("30.09.2026", 149.78), ("0.00", 541.15)],
        ),
        *_line(
            242.20,
            [
                ("Volume", 114.80),
                ("des", 146.08),
                ("transactions", 161.31),
                ("2'091.10", 364.81),
                ("2'091.10", 444.18),
            ],
        ),
        *_line(
            287.64,
            [("En", 70.86), ("cas", 84.43), ("contestation", 113.93), ("tardive", 200.00)],
        ),
    ]
    return text, [page1, page2]


def test_can_parse_cler_header_even_if_postfinance_is_named_later() -> None:
    text, _pages = _statement_pages()
    filename = "Releve-sept.-2026.pdf"
    assert BanqueClerParser().can_parse(text, filename) is True
    # Le mot PostFinance dans un paiement ne doit pas faire gagner l'autre parseur.
    parsers = ParserRegistry()._parsers
    chosen = next(parser for parser in parsers if parser.can_parse(text, filename))
    assert chosen.parser_id == "banque_cler"


def test_can_parse_rejects_postfinance_that_only_mentions_bank_cler() -> None:
    text = "\n".join(
        [
            "PostFinance SA",
            "Extrait de compte 01.09.2026 - 30.09.2026",
            "IBAN CH5309000000146121835",
            *["ACHAT COMMERCE"] * 40,
            "Virement BANK CLER AG 404.80",
            "Compte privé Zak",
        ]
    )
    assert BanqueClerParser().can_parse(text, "Releve-sept.-2026.pdf") is False
    assert PostFinanceParser().can_parse(text, "Releve-sept.-2026.pdf") is True


def test_can_parse_rejects_yuh_before_a_cler_mention() -> None:
    text = "Yuh Swissquote Bank\n" + ("ligne\n" * 20) + "BANK CLER AG\n"
    assert BanqueClerParser().can_parse(text) is False


def test_registry_checks_cler_before_postfinance() -> None:
    ids = ParserRegistry().list_parsers()
    assert ids.index("banque_cler") < ids.index("postfinance")


def test_zak_columns_signs_balances_and_page_two_footer() -> None:
    text, pages = _statement_pages()
    statement = BanqueClerParser()._build(text, pages, "Releve-sept.-2026.pdf")
    assert statement.parser_id == "banque_cler"
    assert statement.bank_name == "Banque Cler"
    assert statement.account_hint == "Banque Cler - Zak"
    assert statement.iban == "CH1200000000000000001"
    assert statement.account_number == "2612.0000.0001"
    assert statement.currency == "CHF"
    assert statement.period_start == date(2026, 9, 1)
    assert statement.period_end == date(2026, 9, 30)
    assert statement.opening_balance == Decimal("0.00")
    assert statement.closing_balance == Decimal("0.00")
    assert [tx.amount for tx in statement.transactions] == [
        Decimal("1686.30"),
        Decimal("-1686.30"),
        Decimal("-404.80"),
        Decimal("404.80"),
    ]
    assert [tx.date for tx in statement.transactions] == [
        date(2026, 9, 25),
        date(2026, 9, 30),
        date(2026, 9, 30),
        date(2026, 9, 30),
    ]
    assert all(tx.value_date == tx.date for tx in statement.transactions)
    descriptions = [tx.description for tx in statement.transactions]
    assert descriptions[0] == "Client Exemple Ref ALPHA"
    assert descriptions[1] == "Assureur SA No 1084890.01.01,"
    assert descriptions[2] == "Assureur SA No 1084890.01.02,"
    assert descriptions[3] == "Client Exemple Ref BETA"
    blob = " ".join(descriptions)
    assert "Volume" not in blob
    assert "contestation" not in blob
    assert "Relevé" not in blob
    assert "01.09.2026" not in blob
    check = check_pdf_balances(statement)
    assert check.status == BalanceStatus.GREEN
    assert check.computed_closing == Decimal("0.00")


def test_statement_suggests_banque_cler_zak() -> None:
    text, pages = _statement_pages()
    statement = BanqueClerParser()._build(text, pages, "Releve-sept.-2026.pdf")
    assert expected_account_type(statement) == "Checking"
    accounts = [
        {
            "account_id": 32,
            "name": "Postfinance Cécile et Pierre",
            "account_num": "",
            "account_type": "Checking",
            "status": "Open",
            "currency": "CHF",
        },
        {
            "account_id": 33,
            "name": "Postfinance Épargne Cécile et Pierre",
            "account_num": "",
            "account_type": "Checking",
            "status": "Open",
            "currency": "CHF",
        },
        {
            "account_id": 174,
            "name": "Banque Cler - Zak",
            "account_num": "",
            "account_type": "Checking",
            "status": "Open",
            "currency": "CHF",
        },
    ]
    match = match_statement_account(statement, accounts)
    assert match is not None
    assert match["account_id"] == 174
    assert suggest_account_id("Releve Zak septembre CHF", accounts) == 174
