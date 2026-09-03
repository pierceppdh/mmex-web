from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_balances import _insert_account, _insert_txn


def test_dashboard_and_currencies(authed_client: TestClient, mmex_settings: Settings) -> None:
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Courant", "Checking", "200", favorite="TRUE")
        _insert_txn(conn, 1, 1, "Deposit", "10")
    engine.dispose()

    dash = authed_client.get("/api/dashboard")
    assert dash.status_code == 200
    body = dash.json()
    assert body["schema"]["ok"] is True
    assert body["base_currency"]["symbol"] == "EUR"
    assert Decimal(body["net_worth"]) == Decimal("210")
    assert any(a["name"] == "Courant" for a in body["favorites"])
    checking = next(g for g in body["groups"] if g["account_type"] == "Checking")
    assert checking["label_fr"] == "Comptes bancaires"
    assert checking["label_en"] == "Bank accounts"

    cur = authed_client.get("/api/currencies")
    assert cur.status_code == 200
    symbols = {c["symbol"] for c in cur.json()["currencies"]}
    assert {"EUR", "USD"} <= symbols

    acc = authed_client.get("/api/accounts")
    assert acc.status_code == 200
    assert len(acc.json()["accounts"]) == 1
