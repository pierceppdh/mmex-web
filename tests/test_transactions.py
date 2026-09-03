from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_domain.constants import NOT_SET, REF_TRANSACTION, REF_TRANSACTION_SPLIT
from mmex_web_api.config import Settings
from tests.test_balances import _insert_account


def _seed(mmex_settings: Settings) -> None:
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Courant", "Checking", "100")
        _insert_account(conn, 2, "Epargne", "Term", "0")
        conn.execute(
            text(
                "INSERT INTO PAYEE_V1 (PAYEEID, PAYEENAME, CATEGID, ACTIVE) "
                "VALUES (10, 'Boulanger', 1, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO CATEGORY_V1 (CATEGID, CATEGNAME, ACTIVE, PARENTID) "
                "VALUES (1, 'Food', 1, -1), (2, 'Groceries', 1, 1), (3, 'Dining', 1, 1)"
            )
        )
        conn.execute(
            text("INSERT INTO TAG_V1 (TAGID, TAGNAME, ACTIVE) VALUES (1, 'kids', 1), (2, 'tax', 1)")
        )
    engine.dispose()


def test_crud_split_transfer_status_delete(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)

    created = authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "40.00",
            "trans_date": "2026-03-01",
            "payee_id": 10,
            "status": "",
            "notes": "courses",
            "tag_ids": [1],
            "splits": [
                {"categ_id": 2, "amount": "25.00", "notes": "super", "tag_ids": [2]},
                {"categ_id": 3, "amount": "15.00", "notes": "", "tag_ids": []},
            ],
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    tid = body["trans_id"]
    assert body["categ_id"] == NOT_SET
    assert body["payee_id"] == 10
    assert body["payee_name"] == "Boulanger"
    assert body["trans_code"] == "Withdrawal"
    assert Decimal(body["trans_amount"]) == Decimal("40.00")
    assert body["trans_date"].startswith("2026-03-01")
    assert body["to_account_id"] == NOT_SET
    assert len(body["splits"]) == 2
    assert body["splits"][0]["categ_id"] == 2
    assert Decimal(body["splits"][0]["amount"]) == Decimal("25")
    assert body["splits"][0]["tags"][0]["name"] == "tax"
    assert body["tags"][0]["name"] == "kids"
    assert body["category_path"] is None

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT ACCOUNTID, TOACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT, "
                "STATUS, NOTES, CATEGID, TOTRANSAMOUNT, COLOR, DELETEDTIME "
                "FROM CHECKINGACCOUNT_V1 WHERE TRANSID = :id"
            ),
            {"id": tid},
        ).fetchone()
        assert tuple(row)[:8] == (1, -1, 10, "Withdrawal", 40, "", "courses", -1)
        assert row[8] == 40
        assert int(row[9]) == -1
        assert (row[10] or "") == ""
        splits = conn.execute(
            text(
                "SELECT CATEGID, SPLITTRANSAMOUNT, NOTES FROM SPLITTRANSACTIONS_V1 "
                "WHERE TRANSID = :id ORDER BY SPLITTRANSID"
            ),
            {"id": tid},
        ).fetchall()
        assert [(int(a), float(b), c or "") for a, b, c in splits] == [
            (2, 25.0, "super"),
            (3, 15.0, ""),
        ]
        refs = {
            r[0]
            for r in conn.execute(
                text("SELECT REFTYPE FROM TAGLINK_V1 WHERE REFID = :id OR REFID IN "
                     "(SELECT SPLITTRANSID FROM SPLITTRANSACTIONS_V1 WHERE TRANSID = :id)"),
                {"id": tid},
            )
        }
        assert REF_TRANSACTION in refs
        assert REF_TRANSACTION_SPLIT in refs
    engine.dispose()

    listed = authed_client.get("/api/accounts/1/transactions")
    assert listed.status_code == 200
    page = listed.json()
    assert page["total"] == 1
    row0 = page["transactions"][0]
    assert Decimal(row0["running_balance"]) == Decimal("60")  # 100-40
    assert row0["withdrawal"] == "40.00" or Decimal(row0["withdrawal"]) == Decimal("40")
    assert row0["is_split"] is True

    cycled = authed_client.post(f"/api/transactions/{tid}/status")
    assert cycled.json()["status"] == "R"

    xfer = authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Transfer",
            "trans_amount": "10",
            "to_trans_amount": "12",
            "to_account_id": 2,
            "trans_date": "2026-03-02",
            "categ_id": 1,
        },
    )
    assert xfer.status_code == 200, xfer.text
    xbody = xfer.json()
    assert xbody["payee_id"] == NOT_SET
    assert Decimal(xbody["trans_amount"]) == Decimal("10")
    assert Decimal(xbody["to_trans_amount"]) == Decimal("12")

    dest = authed_client.get("/api/accounts/2/transactions").json()["transactions"][0]
    assert Decimal(dest["deposit"]) == Decimal("12")
    assert Decimal(dest["running_balance"]) == Decimal("12")

    deleted = authed_client.post(f"/api/transactions/{tid}/delete")
    assert deleted.json()["deleted_time"]
    gone = authed_client.get("/api/accounts/1/transactions").json()
    ids = {t["trans_id"] for t in gone["transactions"]}
    assert tid not in ids
    restored = authed_client.post(f"/api/transactions/{tid}/restore")
    assert restored.json()["deleted_time"] == ""

    bad = authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "5",
            "trans_date": "2026-03-03",
            "payee_id": 10,
            "splits": [{"categ_id": 2, "amount": "1"}],
        },
    )
    assert bad.status_code == 400


def test_ledger_all_accounts(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)
    authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "3.00",
            "trans_date": "2026-04-01",
            "payee_id": 10,
            "status": "",
        },
    )
    authed_client.post(
        "/api/transactions",
        json={
            "account_id": 2,
            "trans_code": "Deposit",
            "trans_amount": "9.00",
            "trans_date": "2026-04-02",
            "payee_id": 10,
            "status": "",
        },
    )
    got = authed_client.get("/api/ledger/transactions")
    assert got.status_code == 200, got.text
    rows = got.json()["transactions"]
    accounts = {r["account_id"] for r in rows}
    assert 1 in accounts and 2 in accounts
    assert got.json()["account_id"] is None


def test_lookups(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)
    cats = authed_client.get("/api/categories").json()["categories"]
    groceries = next(c for c in cats if c["name"] == "Groceries")
    assert groceries["path"] == "Food : Groceries"
    payees = authed_client.get("/api/payees", params={"q": "boul"}).json()["payees"]
    assert payees[0]["name"] == "Boulanger"
    tags = authed_client.get("/api/tags").json()["tags"]
    assert {t["name"] for t in tags} >= {"kids", "tax"}
