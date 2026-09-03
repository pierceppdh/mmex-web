from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def _extra(mmex_settings: Settings) -> None:
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO PAYEE_V1 (PAYEEID, PAYEENAME, CATEGID, ACTIVE) "
                "VALUES (11, 'Netflix', 1, 1), (12, 'HiddenShop', 1, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO CHECKINGACCOUNT_V1 ("
                " TRANSID, ACCOUNTID, TOACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT,"
                " STATUS, NOTES, CATEGID, TRANSDATE, DELETEDTIME, TOTRANSAMOUNT, FOLLOWUPID"
                ") VALUES "
                "(1, 1, -1, 10, 'Withdrawal', '40', '', 'courses', -1, '2026-03-01T00:00:00', '', '40', -1),"
                "(2, 1, -1, 11, 'Withdrawal', '15.25', 'R', 'stream', 1, '2026-04-10T00:00:00', '', '15.25', 1),"
                "(3, 1, -1, 10, 'Deposit', '8', '', 'refund', 3, '2026-05-01T00:00:00', '', '8', -1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO SPLITTRANSACTIONS_V1 (SPLITTRANSID, TRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES) "
                "VALUES (1, 1, 2, 25, 'super'), (2, 1, 3, 15, '')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO TAGLINK_V1 (REFTYPE, REFID, TAGID) VALUES "
                "('Transaction', 1, 1), ('TransactionSplit', 1, 2)"
            )
        )
    engine.dispose()


def test_register_filters_and_running_balance(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    _extra(mmex_settings)

    all_rows = authed_client.get("/api/accounts/1/transactions")
    assert all_rows.status_code == 200, all_rows.text
    body = all_rows.json()
    assert body["account_total"] == 3
    assert body["total"] == 3
    by_id = {t["trans_id"]: t for t in body["transactions"]}
    assert Decimal(by_id[2]["running_balance"]) == Decimal("44.75")

    dated = authed_client.get(
        "/api/accounts/1/transactions", params={"date_from": "2026-04-01", "date_to": "2026-04-30"}
    ).json()
    assert dated["total"] == 1
    assert dated["transactions"][0]["payee_name"] == "Netflix"
    assert dated["transactions"][0]["running_balance"] == by_id[2]["running_balance"]

    payee = authed_client.get("/api/accounts/1/transactions", params={"payee_q": "netfl"}).json()
    assert payee["total"] == 1
    assert payee["transactions"][0]["trans_id"] == 2

    cat = authed_client.get("/api/accounts/1/transactions", params={"categ_id": 1}).json()
    ids = {t["trans_id"] for t in cat["transactions"]}
    assert ids == {1, 2, 3}

    groceries = authed_client.get("/api/accounts/1/transactions", params={"categ_id": 2}).json()
    assert groceries["total"] == 1
    assert groceries["transactions"][0]["trans_id"] == 1

    tagged = authed_client.get("/api/accounts/1/transactions", params={"tag_id": 2}).json()
    assert tagged["total"] == 1
    assert tagged["transactions"][0]["trans_id"] == 1

    recon = authed_client.get("/api/accounts/1/transactions", params={"status": "R"}).json()
    assert recon["total"] == 1
    none = authed_client.get("/api/accounts/1/transactions", params={"status": ""}).json()
    assert none["total"] == 2

    amt = authed_client.get(
        "/api/accounts/1/transactions", params={"amount_min": "15", "amount_max": "20"}
    ).json()
    assert amt["total"] == 1
    assert amt["transactions"][0]["trans_id"] == 2

    follow = authed_client.get("/api/accounts/1/transactions", params={"followup": True}).json()
    assert follow["total"] == 1
    assert follow["transactions"][0]["trans_id"] == 2

    found = authed_client.get("/api/payees", params={"q": "netflix", "limit": 10}).json()
    names = [p["name"] for p in found["payees"]]
    assert "Netflix" in names
    assert "HiddenShop" not in names


def test_saved_views_and_statement_lock(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    _extra(mmex_settings)

    created = authed_client.post(
        "/api/views",
        json={"name": "Courses", "account_id": 1, "filter": {"categ_id": 2, "payee_q": "boul"}},
    )
    assert created.status_code == 200, created.text
    view = created.json()
    assert view["id"] == 1
    assert view["filter"]["categ_id"] == 2
    listed = authed_client.get("/api/views").json()["views"]
    assert len(listed) == 1
    assert listed[0]["name"] == "Courses"

    renamed = authed_client.put(
        "/api/views/1",
        json={"name": "Super", "account_id": 1, "filter": {"categ_id": 2}},
    )
    assert renamed.json()["name"] == "Super"
    assert authed_client.delete("/api/views/1").status_code == 200
    assert authed_client.get("/api/views").json()["views"] == []

    lock = authed_client.put(
        "/api/accounts/1/statement",
        json={
            "statement_locked": True,
            "statement_date": "2026-04-01",
            "credit_limit": "500",
            "minimum_payment": "20",
        },
    )
    assert lock.status_code == 200, lock.text
    assert lock.json()["statement_locked"] == 1
    assert lock.json()["statement_date"] == "2026-04-01"

    blocked = authed_client.put(
        "/api/transactions/1",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "40.00",
            "trans_date": "2026-03-01",
            "payee_id": 10,
            "categ_id": 2,
        },
    )
    assert blocked.status_code == 423, blocked.text

    cycle = authed_client.post("/api/transactions/1/status")
    assert cycle.status_code == 423

    later = authed_client.put(
        "/api/transactions/3",
        json={
            "account_id": 1,
            "trans_code": "Deposit",
            "trans_amount": "8",
            "trans_date": "2026-05-01",
            "payee_id": 10,
            "categ_id": 3,
            "notes": "ok",
        },
    )
    assert later.status_code == 200, later.text
    assert later.json()["notes"] == "ok"

    new_old = authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "1",
            "trans_date": "2026-03-15",
            "payee_id": 10,
            "categ_id": 1,
        },
    )
    assert new_old.status_code == 423

    new_ok = authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "1",
            "trans_date": "2026-06-01",
            "payee_id": 10,
            "categ_id": 1,
        },
    )
    assert new_ok.status_code == 200, new_ok.text
