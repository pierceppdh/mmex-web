from __future__ import annotations

from sqlalchemy import create_engine, text

from mmex_domain.recon import match_statement_account, suggest_account_id
from mmex_recon.schemas import ParsedStatement
from mmex_web_api.config import Settings
from mmex_web_api import recon_pipeline, routes_recon


def test_paperless_env_strips_dockhand_space(monkeypatch) -> None:
    monkeypatch.setenv("PAPERLESS_URL", " http://paperless.home:8000 ")
    monkeypatch.setenv("PAPERLESS_TOKEN", " secret ")
    s = Settings(_env_file=None)
    assert s.paperless_url == "http://paperless.home:8000"
    assert s.paperless_token == "secret"


def test_suggest_account_iban() -> None:
    accounts = [
        {
            "account_id": 1,
            "name": "Boursorama",
            "account_num": "FR76 1234 5678 9012",
            "status": "Open",
        },
        {"account_id": 2, "name": "Cash", "account_num": "", "status": "Open"},
    ]
    hay = "Releve-compte FR76123456789012 Boursorama.pdf"
    assert suggest_account_id(hay, accounts) == 1
    assert suggest_account_id("unknown.pdf", accounts) is None


def _inbox_accounts() -> list[dict]:
    return [
        {
            "account_id": 1,
            "name": "Boursorama",
            "account_num": "FR7640618802700004009647489",
            "account_type": "Checking",
            "status": "Open",
            "currency": "EUR",
        },
        {
            "account_id": 2,
            "name": "Visa Boursorama Pierre",
            "account_num": "",
            "account_type": "Credit Card",
            "status": "Open",
            "currency": "EUR",
        },
        {
            "account_id": 3,
            "name": "Visa Boursorama Cecile",
            "account_num": "",
            "account_type": "Credit Card",
            "status": "Open",
            "currency": "EUR",
        },
        {
            "account_id": 4,
            "name": "Yuh CHF",
            "account_num": "",
            "account_type": "Checking",
            "status": "Open",
            "currency": "CHF",
        },
        {
            "account_id": 5,
            "name": "Yuh EUR",
            "account_num": "",
            "account_type": "Checking",
            "status": "Open",
            "currency": "EUR",
        },
    ]


def test_inbox_suggests_checking_cards_and_yuh() -> None:
    accounts = _inbox_accounts()
    assert suggest_account_id("2026-04 Releve Boursorama.pdf", accounts) == 1
    assert suggest_account_id("Boursorama Releve-CB Pierre 7602.pdf", accounts) == 2
    assert suggest_account_id("Releve-CB Cecile 6161.pdf", accounts) == 3
    assert suggest_account_id("Yuh CHF relevé 2026.pdf", accounts) == 4
    assert suggest_account_id("Yuh EUR statement.pdf", accounts) == 5


def test_card_statement_not_mapped_to_checking_iban() -> None:
    accounts = [
        {
            "account_id": 10,
            "name": "Boursorama",
            "account_num": "FR7640618802700004009647489",
            "account_type": "Checking",
            "status": "Open",
            "currency": "EUR",
        },
        {
            "account_id": 6,
            "name": "Visa Boursorama Cecile",
            "account_num": "",
            "account_type": "Credit Card",
            "status": "Open",
            "currency": "EUR",
        },
    ]
    hay = "2026-05-28 Boursorama Releve-CB-28-05-2026 FR7640618802700004009647489.pdf"
    assert suggest_account_id(hay, accounts) == 6
    stmt = ParsedStatement(
        parser_id="boursorama_cb",
        bank_name="Boursorama CB",
        account_hint="Visa Boursorama Cecile",
        currency="EUR",
        iban="FR7640618802700004009647489",
        account_number="4810********6161",
        metadata={"card_number": "4810********6161"},
    )
    acc = match_statement_account(stmt, accounts)
    assert acc is not None
    assert acc["account_id"] == 6


def test_recon_inbox_unconfigured(authed_client) -> None:
    resp = authed_client.get("/api/recon/inbox")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["documents"] == []


def test_recon_inbox_maps_docs(authed_client, mmex_settings, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ACCOUNTLIST_V1 (
                    ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, ACCOUNTNUM, STATUS,
                    NOTES, HELDAT, WEBSITE, CONTACTINFO, ACCESSINFO,
                    INITIALBAL, FAVORITEACCT, CURRENCYID
                ) VALUES (
                    1, 'Boursorama', 'Checking', 'FR76123456789012', 'Open',
                    '', '', '', '', '', 0, 'TRUE', 1
                )
                """
            )
        )
    engine.dispose()

    monkeypatch.setattr(mmex_settings, "paperless_url", "http://paperless.test")
    monkeypatch.setattr(mmex_settings, "paperless_token", "tok")

    def fake_list(_settings):
        return [
            {
                "id": 9,
                "title": "Releve FR76123456789012",
                "created": "2026-04-01",
                "original_file_name": "releve.pdf",
                "tags": ["Nouveau-Relevé"],
            }
        ]

    monkeypatch.setattr(routes_recon, "list_inbox_documents", fake_list)

    def fail_download(*_a, **_k):
        raise RuntimeError("no pdf")

    monkeypatch.setattr(recon_pipeline, "download_document", fail_download)
    resp = authed_client.get("/api/recon/inbox")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["documents"][0]["account_id"] == 1
    assert "1" in body["by_account"]


def test_recon_inbox_prefers_parsed_statement(authed_client, mmex_settings, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ACCOUNTLIST_V1 (
                    ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, ACCOUNTNUM, STATUS,
                    NOTES, HELDAT, WEBSITE, CONTACTINFO, ACCESSINFO,
                    INITIALBAL, FAVORITEACCT, CURRENCYID
                ) VALUES
                (1, 'Boursorama', 'Checking', 'FR7640618802700004009647489', 'Open',
                 '', '', '', '', '', 0, 'TRUE', 1),
                (6, 'Visa Boursorama Cecile', 'Credit Card', '', 'Open',
                 '', '', '', '', '', 0, 'TRUE', 1)
                """
            )
        )
    engine.dispose()
    monkeypatch.setattr(mmex_settings, "paperless_url", "http://paperless.test")
    monkeypatch.setattr(mmex_settings, "paperless_token", "tok")

    def fake_list(_settings):
        return [
            {
                "id": 11,
                "title": "Boursorama FR7640618802700004009647489",
                "created": "2026-05-28",
                "original_file_name": "Boursorama-releve.pdf",
                "tags": ["Nouveau-Relevé"],
            }
        ]

    monkeypatch.setattr(routes_recon, "list_inbox_documents", fake_list)
    monkeypatch.setattr(recon_pipeline, "download_document", lambda *_a, **_k: (b"%PDF", "cb.pdf"))
    monkeypatch.setattr(
        recon_pipeline,
        "parse_pdf_bytes",
        lambda *_a, **_k: ParsedStatement(
            parser_id="boursorama_cb",
            bank_name="Boursorama CB",
            account_hint="Visa Boursorama Cecile",
            currency="EUR",
            iban="FR7640618802700004009647489",
            account_number="4810********6161",
            metadata={"card_number": "4810********6161"},
        ),
    )
    resp = authed_client.get("/api/recon/inbox")
    assert resp.status_code == 200, resp.text
    assert resp.json()["documents"][0]["account_id"] == 6


def test_recon_pdf_unconfigured(authed_client) -> None:
    resp = authed_client.get("/api/recon/documents/1/file")
    assert resp.status_code == 502
