from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def test_quickadd_writes_ledger_and_creates_payee(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    meta = authed_client.get("/api/quickadd")
    assert meta.status_code == 200
    assert meta.json()["last_account_id"] is None

    created = authed_client.post(
        "/api/quickadd",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "7.40",
            "trans_date": "2026-08-30",
            "payee_name": "Taxi PR16",
            "category": "Food:Dining",
            "notes": "phone",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["account_id"] == 1
    assert Decimal(body["trans_amount"]) == Decimal("7.40")
    assert body["payee_name"] == "Taxi PR16"
    assert body["created_payee"] is True
    assert body["last_account_id"] == 1

    again = authed_client.get("/api/quickadd")
    assert again.json()["last_account_id"] == 1

    missing = authed_client.post(
        "/api/quickadd",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "1",
            "trans_date": "2026-08-30",
        },
    )
    assert missing.status_code == 400

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        payee = conn.execute(
            text("SELECT PAYEENAME FROM PAYEE_V1 WHERE PAYEENAME = 'Taxi PR16'")
        ).scalar()
        last = conn.execute(
            text("SELECT SETTINGVALUE FROM SETTING_V1 WHERE SETTINGNAME = 'MMEXWEB_LAST_ACCOUNT'")
        ).scalar()
    engine.dispose()
    assert payee == "Taxi PR16"
    assert str(last) == "1"

    trash = authed_client.post(f"/api/transactions/{body['trans_id']}/delete")
    assert trash.status_code == 200
