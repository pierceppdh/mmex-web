from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_balances import _insert_account, _insert_txn
from tests.test_transactions import _seed


def test_web_prefs_and_account_properties(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        _insert_account(conn, 9, "Ferme", "Checking", "50")
        conn.execute(
            text("UPDATE ACCOUNTLIST_V1 SET STATUS = 'Closed' WHERE ACCOUNTID = 9")
        )
        _insert_txn(conn, 1, 1, "Deposit", "10")
    engine.dispose()

    dash = authed_client.get("/api/dashboard").json()
    assert any(a["name"] == "Ferme" for a in dash["closed_accounts"])
    assert all(a["status"] == "Open" for g in dash["groups"] for a in g["accounts"])

    got = authed_client.get("/api/settings").json()
    assert got["theme"] == "system"
    assert got["show_closed_accounts"] is False
    assert got["default_account_id"] is None

    saved = authed_client.put(
        "/api/settings",
        json={
            "theme": "light",
            "show_closed_accounts": True,
            "default_account_id": 1,
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["theme"] == "light"
    assert body["show_closed_accounts"] is True
    assert body["default_account_id"] == 1

    meta = authed_client.get("/api/quickadd").json()
    assert meta["default_account_id"] == 1
    assert meta["last_account_id"] is None

    bad_theme = authed_client.put("/api/settings", json={"theme": "neon"})
    assert bad_theme.status_code == 400

    detail = authed_client.get("/api/accounts/1")
    assert detail.status_code == 200
    assert detail.json()["name"]
    assert "account_types" in detail.json()

    updated = authed_client.put(
        "/api/accounts/1",
        json={
            **{k: detail.json()[k] for k in (
                "name",
                "account_type",
                "account_num",
                "status",
                "notes",
                "held_at",
                "website",
                "contact_info",
                "access_info",
                "initial_bal",
                "initial_date",
                "favorite",
                "currency_id",
                "statement_locked",
                "statement_date",
                "credit_limit",
                "minimum_balance",
                "interest_rate",
                "payment_due_date",
                "minimum_payment",
            )},
            "name": "Compte test",
            "favorite": True,
            "account_num": "CH00",
            "held_at": "Banque",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Compte test"
    assert updated.json()["favorite"] is True
    assert updated.json()["account_num"] == "CH00"

    missing = authed_client.get("/api/accounts/99999")
    assert missing.status_code == 404

    created = authed_client.post(
        "/api/accounts",
        json={"name": "Livret test", "account_type": "Term", "currency_id": 1, "initial_bal": "10"},
    )
    assert created.status_code == 200, created.text
    new_id = created.json()["account_id"]
    assert created.json()["name"] == "Livret test"
    dup = authed_client.post("/api/accounts", json={"name": "livret test", "currency_id": 1})
    assert dup.status_code == 400
    busy = authed_client.delete("/api/accounts/1")
    assert busy.status_code == 409
    gone = authed_client.delete(f"/api/accounts/{new_id}")
    assert gone.status_code == 200
