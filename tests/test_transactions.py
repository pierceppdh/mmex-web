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


def test_transfer_update_can_change_source_account(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        _insert_account(conn, 3, "Zak", "Checking", "0")
    engine.dispose()
    created = authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Transfer",
            "trans_amount": "10.00",
            "to_trans_amount": "10.00",
            "to_account_id": 2,
            "trans_date": "2026-05-01",
            "categ_id": 1,
        },
    )
    assert created.status_code == 200, created.text
    tid = created.json()["trans_id"]
    updated = authed_client.put(
        f"/api/transactions/{tid}",
        json={
            "account_id": 3,
            "trans_code": "Transfer",
            "trans_amount": "10.00",
            "to_trans_amount": "10.00",
            "to_account_id": 2,
            "trans_date": "2026-05-01",
            "categ_id": 1,
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["account_id"] == 3
    assert body["to_account_id"] == 2
    src = authed_client.get("/api/accounts/1/transactions").json()["transactions"]
    assert all(row["trans_id"] != tid for row in src)
    moved = authed_client.get("/api/accounts/3/transactions").json()["transactions"]
    assert moved[0]["trans_id"] == tid
    assert moved[0]["withdrawal"] == "10.00" or Decimal(moved[0]["withdrawal"]) == Decimal("10")
    dest = authed_client.get("/api/accounts/2/transactions").json()["transactions"]
    assert dest[0]["trans_id"] == tid
    assert Decimal(dest[0]["deposit"]) == Decimal("10")


def _post_txn(client: TestClient, **extra: object) -> int:
    payload = {
        "account_id": 1,
        "trans_code": "Withdrawal",
        "trans_amount": "5.00",
        "trans_date": "2026-03-02",
        "payee_id": 10,
        "categ_id": 2,
    }
    payload.update(extra)
    created = client.post("/api/transactions", json=payload)
    assert created.status_code == 200, created.text
    return int(created.json()["trans_id"])


def test_bulk_payee_category_and_delete(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO PAYEE_V1 (PAYEEID, PAYEENAME, CATEGID, ACTIVE) "
                "VALUES (11, 'Pharmacie', 3, 1)"
            )
        )
    engine.dispose()

    first = _post_txn(authed_client, trans_amount="4.00", trans_date="2026-03-02")
    second = _post_txn(authed_client, trans_amount="6.00", trans_date="2026-03-03", categ_id=3)
    transfer = _post_txn(
        authed_client,
        trans_code="Transfer",
        trans_amount="2.00",
        to_trans_amount="2.00",
        to_account_id=2,
        trans_date="2026-03-04",
        payee_id=None,
        categ_id=1,
    )
    split = _post_txn(
        authed_client,
        trans_amount="9.00",
        trans_date="2026-03-05",
        categ_id=-1,
        splits=[
            {"categ_id": 2, "amount": "4.00", "notes": ""},
            {"categ_id": 3, "amount": "5.00", "notes": ""},
        ],
    )

    payees = authed_client.post(
        "/api/transactions/bulk",
        json={"trans_ids": [first, second, transfer, first], "action": "set_payee", "payee_id": 11},
    )
    assert payees.status_code == 200, payees.text
    body = payees.json()
    assert body["updated"] == 2
    assert body["skipped"] == [{"trans_id": transfer, "reason": "transfer"}]

    categories = authed_client.post(
        "/api/transactions/bulk",
        json={
            "trans_ids": [first, transfer, split],
            "action": "set_category",
            "categ_id": 1,
        },
    )
    assert categories.status_code == 200, categories.text
    assert categories.json()["updated"] == 2
    assert categories.json()["skipped"] == [{"trans_id": split, "reason": "split"}]

    cleared = authed_client.post(
        "/api/transactions/bulk",
        json={"trans_ids": [second], "action": "set_category", "categ_id": -1},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["updated"] == 1

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        rows = {
            int(r[0]): (int(r[1]), int(r[2]), r[3] or "")
            for r in conn.execute(
                text("SELECT TRANSID, PAYEEID, CATEGID, DELETEDTIME FROM CHECKINGACCOUNT_V1")
            )
        }
        split_cats = [
            int(r[0])
            for r in conn.execute(
                text("SELECT CATEGID FROM SPLITTRANSACTIONS_V1 WHERE TRANSID = :id ORDER BY SPLITTRANSID"),
                {"id": split},
            )
        ]
    engine.dispose()
    assert rows[first][:2] == (11, 1)
    assert rows[second][:2] == (11, NOT_SET)
    assert rows[transfer][0] == NOT_SET
    assert rows[transfer][1] == 1
    assert rows[split][1] == NOT_SET
    assert split_cats == [2, 3]
    assert all(row[2] == "" for row in rows.values())

    removed = authed_client.post(
        "/api/transactions/bulk",
        json={"trans_ids": [first, second], "action": "delete"},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json() == {"updated": 2, "skipped": []}
    listed = authed_client.get("/api/accounts/1/transactions").json()["transactions"]
    assert {row["trans_id"] for row in listed} == {transfer, split}

    again = authed_client.post(
        "/api/transactions/bulk",
        json={"trans_ids": [first], "action": "set_payee", "payee_id": 10},
    )
    assert again.status_code == 200, again.text
    assert again.json()["updated"] == 0
    assert again.json()["skipped"] == [{"trans_id": first, "reason": "deleted"}]

    missing = authed_client.post(
        "/api/transactions/bulk",
        json={"trans_ids": [999], "action": "delete"},
    )
    assert missing.status_code == 404
    unknown_payee = authed_client.post(
        "/api/transactions/bulk",
        json={"trans_ids": [transfer], "action": "set_payee", "payee_id": 99},
    )
    assert unknown_payee.status_code == 404
    empty = authed_client.post("/api/transactions/bulk", json={"trans_ids": [], "action": "delete"})
    assert empty.status_code == 422


def test_bulk_statement_lock_rolls_back(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)
    early = _post_txn(authed_client, trans_date="2026-03-01", categ_id=2)
    late = _post_txn(authed_client, trans_date="2026-05-01", categ_id=2)
    lock = authed_client.put(
        "/api/accounts/1/statement",
        json={"statement_locked": True, "statement_date": "2026-04-01"},
    )
    assert lock.status_code == 200, lock.text
    blocked = authed_client.post(
        "/api/transactions/bulk",
        json={"trans_ids": [early, late], "action": "set_category", "categ_id": 3},
    )
    assert blocked.status_code == 423, blocked.text
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        cats = {
            int(r[0]): int(r[1])
            for r in conn.execute(text("SELECT TRANSID, CATEGID FROM CHECKINGACCOUNT_V1"))
        }
    engine.dispose()
    assert cats[early] == 2
    assert cats[late] == 2


def test_lookups(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)
    cats = authed_client.get("/api/categories").json()["categories"]
    groceries = next(c for c in cats if c["name"] == "Groceries")
    assert groceries["path"] == "Food : Groceries"
    payees = authed_client.get("/api/payees", params={"q": "boul"}).json()["payees"]
    assert payees[0]["name"] == "Boulanger"
    tags = authed_client.get("/api/tags").json()["tags"]
    assert {t["name"] for t in tags} >= {"kids", "tax"}
