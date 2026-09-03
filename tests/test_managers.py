from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_balances import _insert_account, _insert_txn


def _seed(mmex_settings: Settings) -> None:
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Courant", "Checking", "100")
        conn.execute(
            text(
                "INSERT INTO CATEGORY_V1 (CATEGID, CATEGNAME, ACTIVE, PARENTID) "
                "VALUES (1, 'Food', 1, -1), (2, 'Groceries', 1, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO PAYEE_V1 (PAYEEID, PAYEENAME, CATEGID, ACTIVE, PATTERN) "
                "VALUES (10, 'Boulanger', 1, 1, 'BOUL*')"
            )
        )
        conn.execute(
            text("INSERT INTO TAG_V1 (TAGID, TAGNAME, ACTIVE) VALUES (1, 'kids', 1)")
        )
        _insert_txn(conn, 1, 1, "Withdrawal", "5", payee_id=10, categ_id=2)
    engine.dispose()


def test_payee_category_tag_currency_crud(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)

    created = authed_client.post(
        "/api/payees",
        json={
            "name": "Pharmacie",
            "categ_id": 1,
            "pattern": "PHARM*",
            "notes": "santé",
        },
    )
    assert created.status_code == 200, created.text
    payee = created.json()
    assert payee["name"] == "Pharmacie"
    assert payee["pattern"] == "PHARM*"
    assert payee["category_path"] == "Food"
    pid = payee["payee_id"]

    dup = authed_client.post("/api/payees", json={"name": "pharmacie"})
    assert dup.status_code == 400

    listed = authed_client.get("/api/payees/all").json()["payees"]
    names = {p["name"] for p in listed}
    assert {"Boulanger", "Pharmacie"} <= names
    baker = next(p for p in listed if p["name"] == "Boulanger")
    assert baker["pattern"] == "BOUL*"
    assert baker["used_count"] >= 1

    hidden = authed_client.post(f"/api/payees/{pid}/active", json={"active": False})
    assert hidden.json()["active"] == 0
    typeahead = authed_client.get("/api/payees").json()["payees"]
    assert all(p["name"] != "Pharmacie" for p in typeahead)

    authed_client.post(f"/api/payees/{pid}/active", json={"active": True})
    gone = authed_client.delete(f"/api/payees/{pid}")
    assert gone.status_code == 200
    used = authed_client.delete("/api/payees/10")
    assert used.status_code == 409

    extra = authed_client.post("/api/payees", json={"name": "MergeMe"}).json()
    merged = authed_client.post(
        "/api/payees/10/merge", json={"into_id": extra["payee_id"]}
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["name"] == "MergeMe"
    assert merged.json()["updated_transactions"] >= 1
    gone_src = authed_client.get("/api/payees/10")
    assert gone_src.status_code == 404
    txn = authed_client.get("/api/accounts/1/transactions").json()["transactions"]
    assert all(row["payee_id"] != 10 for row in txn)
    assert any(row["payee_name"] == "MergeMe" for row in txn)

    nested = authed_client.post("/api/categories", json={"name": "Organic", "parent_id": 2})
    assert nested.status_code == 200, nested.text
    assert nested.json()["path"] == "Food : Groceries : Organic"
    oid = nested.json()["categ_id"]

    cycle = authed_client.put(
        "/api/categories/1", json={"name": "Food", "parent_id": oid}
    )
    assert cycle.status_code == 400

    same = authed_client.post("/api/categories", json={"name": "Groceries", "parent_id": 1})
    assert same.status_code == 400

    sibling = authed_client.post("/api/categories", json={"name": "Groceries", "parent_id": -1})
    assert sibling.status_code == 200

    kids = authed_client.delete("/api/categories/1")
    assert kids.status_code == 409

    authed_client.delete(f"/api/categories/{oid}")
    unused_root = authed_client.post("/api/categories", json={"name": "Temp"})
    tid_cat = unused_root.json()["categ_id"]
    assert authed_client.delete(f"/api/categories/{tid_cat}").status_code == 200

    old = authed_client.post("/api/categories", json={"name": "OldCat"}).json()
    new = authed_client.post("/api/categories", json={"name": "NewCat"}).json()
    cat_merge = authed_client.post(
        f"/api/categories/{old['categ_id']}/merge", json={"into_id": new["categ_id"]}
    )
    assert cat_merge.status_code == 200, cat_merge.text
    leftover = {c["categ_id"] for c in authed_client.get("/api/categories/all").json()["categories"]}
    assert old["categ_id"] not in leftover
    assert new["categ_id"] in leftover
    bad = authed_client.post(
        f"/api/categories/{new['categ_id']}/merge", json={"into_id": new["categ_id"]}
    )
    assert bad.status_code == 400

    tag = authed_client.post("/api/tags", json={"name": "tax"})
    assert tag.status_code == 200
    tag_id = tag.json()["tag_id"]
    assert authed_client.post("/api/tags", json={"name": "TAX"}).status_code == 400
    assert authed_client.delete(f"/api/tags/{tag_id}").status_code == 200

    chf = authed_client.post(
        "/api/currencies",
        json={
            "name": "Swiss franc",
            "symbol": "CHF",
            "pfx": "Fr.",
            "scale": 100,
            "rate": "0.95",
            "currency_type": "Fiat",
        },
    )
    assert chf.status_code == 200, chf.text
    cid = chf.json()["currency_id"]
    assert chf.json()["symbol"] == "CHF"
    assert authed_client.post(
        "/api/currencies", json={"name": "Other", "symbol": "chf"}
    ).status_code == 400

    assert authed_client.delete("/api/currencies/1").status_code == 409
    assert authed_client.delete(f"/api/currencies/{cid}").status_code == 200

    admin = authed_client.get("/api/currencies/all").json()["currencies"]
    euro = next(c for c in admin if c["symbol"] == "EUR")
    assert euro["is_base"] is True
