from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def test_scheduled_enter_skip_once_and_silent_due(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    today = date.today().isoformat()

    weekly = authed_client.post(
        "/api/scheduled",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "9.50",
            "next_occurrence_date": today,
            "payee_id": 10,
            "categ_id": 2,
            "repeat_type": 1,
            "auto_mode": 0,
            "remaining": -1,
        },
    )
    assert weekly.status_code == 200, weekly.text
    bill = weekly.json()
    bid = bill["bd_id"]
    assert bill["repeat_type"] == 1
    assert bill["auto_mode"] == 0
    assert bill["repeats"] == 1

    skipped = authed_client.post(f"/api/scheduled/{bid}/skip")
    assert skipped.status_code == 200, skipped.text
    nxt = skipped.json()["scheduled"]["next_occurrence_date"][:10]
    assert nxt == (date.today() + timedelta(days=7)).isoformat()

    entered = authed_client.post(f"/api/scheduled/{bid}/enter")
    assert entered.status_code == 200, entered.text
    txn = entered.json()["transaction"]
    assert txn["trans_code"] == "Withdrawal"
    assert txn["trans_amount"] in ("9.50", "9.5")
    assert entered.json()["ended"] is False
    nxt2 = entered.json()["scheduled"]["next_occurrence_date"][:10]
    assert nxt2 == (date.today() + timedelta(days=14)).isoformat()

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT ACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT, CATEGID "
                "FROM CHECKINGACCOUNT_V1 WHERE TRANSID = :id"
            ),
            {"id": txn["trans_id"]},
        ).fetchone()
        assert tuple(row)[:3] == (1, 10, "Withdrawal")
        assert int(row[4]) == 2
    engine.dispose()

    once = authed_client.post(
        "/api/scheduled",
        json={
            "account_id": 1,
            "trans_code": "Deposit",
            "trans_amount": "3",
            "next_occurrence_date": today,
            "payee_id": 10,
            "categ_id": 1,
            "repeat_type": 0,
            "auto_mode": 0,
        },
    )
    oid = once.json()["bd_id"]
    done = authed_client.post(f"/api/scheduled/{oid}/enter")
    assert done.json()["ended"] is True
    assert authed_client.get(f"/api/scheduled/{oid}").status_code == 404

    silent = authed_client.post(
        "/api/scheduled",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "1.10",
            "next_occurrence_date": (date.today() - timedelta(days=14)).isoformat(),
            "payee_id": 10,
            "categ_id": 2,
            "repeat_type": 1,
            "auto_mode": 2,
            "remaining": -1,
        },
    )
    assert silent.status_code == 200, silent.text
    processed = authed_client.post("/api/scheduled/process-due")
    assert processed.status_code == 200, processed.text
    body = processed.json()
    assert body["entered"] >= 2
    leftover = authed_client.get(f"/api/scheduled/{silent.json()['bd_id']}").json()
    assert leftover["next_occurrence_date"][:10] > today

    meta = authed_client.get("/api/scheduled/meta").json()
    assert len(meta["repeat_types"]) == 17
    assert meta["auto_modes"][-1]["key"] == "silent"
