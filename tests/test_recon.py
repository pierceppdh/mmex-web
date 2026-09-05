from __future__ import annotations

from sqlalchemy import create_engine, text

from mmex_domain.recon import suggest_account_id
from mmex_web_api import routes_recon


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
    resp = authed_client.get("/api/recon/inbox")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["documents"][0]["account_id"] == 1
    assert "1" in body["by_account"]
