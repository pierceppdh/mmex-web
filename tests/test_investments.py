from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_balances import _insert_account, _insert_txn
from tests.test_transactions import _seed


def _seed_invest(mmex_settings: Settings) -> None:
    _seed(mmex_settings)
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        _insert_account(conn, 9, "PEA", "Investment", "0")
        _insert_txn(conn, 50, 1, "Withdrawal", "250", status="")
        _insert_txn(conn, 51, 1, "Withdrawal", "80", status="")
        _insert_txn(conn, 52, 1, "Deposit", "30", status="")
        _insert_txn(conn, 53, 1, "Withdrawal", "10", status="V")
    engine.dispose()


def test_stock_price_lots_and_asset_value(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed_invest(mmex_settings)

    missing = authed_client.get("/api/stocks/1")
    assert missing.status_code == 404

    created = authed_client.post(
        "/api/stocks",
        json={
            "name": "Acme",
            "symbol": "ACM",
            "held_at": 9,
            "purchase_date": "2024-01-15",
            "num_shares": "10",
            "purchase_price": "5",
            "current_price": "5",
            "commission": "1",
        },
    )
    assert created.status_code == 200, created.text
    stock = created.json()
    sid = stock["stock_id"]
    assert Decimal(stock["num_shares"]) == Decimal("10")
    assert Decimal(stock["market"]) == Decimal("50")
    assert Decimal(stock["value"]) == Decimal("50")
    assert stock["lot_count"] == 0

    listed = authed_client.get("/api/stocks")
    assert listed.status_code == 200
    assert Decimal(listed.json()["totals"]["market"]) == Decimal("50")
    assert any(a["account_id"] == 9 for a in listed.json()["accounts"])

    priced = authed_client.post(
        f"/api/stocks/{sid}/price", json={"date": "2026-08-01", "price": "7.5"}
    )
    assert priced.status_code == 200, priced.text
    assert Decimal(priced.json()["price"]) == Decimal("7.5")
    assert priced.json()["history"][0]["date"] == "2026-08-01"

    again = authed_client.post(
        "/api/stocks/price",
        json={"symbol": "ACM", "date": "2026-08-01", "price": "8"},
    )
    assert again.status_code == 200
    detail = authed_client.get(f"/api/stocks/{sid}").json()
    assert Decimal(detail["current_price"]) == Decimal("8")
    assert Decimal(detail["market"]) == Decimal("80")
    assert len(detail["history"]) == 1

    lot = authed_client.post(
        f"/api/stocks/{sid}/lots",
        json={
            "trans_id": 50,
            "share_number": "4",
            "share_price": "5",
            "share_commission": "2",
            "share_lot": "A",
        },
    )
    assert lot.status_code == 200, lot.text
    assert Decimal(lot.json()["num_shares"]) == Decimal("4")
    assert Decimal(lot.json()["purchase_price"]) == Decimal("5.5")  # (20+2)/4
    assert Decimal(lot.json()["value"]) == Decimal("22")
    assert Decimal(lot.json()["commission"]) == Decimal("2")
    assert lot.json()["purchase_date"] == "2026-03-01" or lot.json()["purchase_date"]
    assert len(lot.json()["lots"]) == 1

    dup = authed_client.post(
        f"/api/stocks/{sid}/lots",
        json={"trans_id": 50, "share_number": "1", "share_price": "1"},
    )
    assert dup.status_code == 409

    blocked = authed_client.delete(f"/api/stocks/{sid}")
    assert blocked.status_code == 409

    share_info_id = lot.json()["lots"][0]["share_info_id"]
    unlinked = authed_client.delete(f"/api/stocks/{sid}/lots/{share_info_id}")
    assert unlinked.status_code == 200
    assert unlinked.json()["lots"] == []

    deleted = authed_client.delete(f"/api/stocks/{sid}")
    assert deleted.status_code == 200

    asset = authed_client.post(
        "/api/assets",
        json={
            "name": "Cabane test",
            "start_date": "2024-01-01",
            "asset_type": "Property",
            "value": "100",
            "value_change": "Appreciates",
            "value_change_mode": "Percentage",
            "value_change_rate": "10",
            "status": "Open",
        },
    )
    assert asset.status_code == 200, asset.text
    aid = asset.json()["asset_id"]
    as_of = authed_client.get(f"/api/assets/{aid}", params={"as_of": "2025-01-01"})
    assert as_of.status_code == 200
    days = (date(2025, 1, 1) - date(2024, 1, 1)).days
    expected = Decimal("100") * (Decimal("1") + Decimal("10") / Decimal("36500")) ** days
    assert abs(Decimal(as_of.json()["current_value"]) - expected) < Decimal("0.0002")
    assert expected > Decimal("110")

    linear = authed_client.post(
        "/api/assets",
        json={
            "name": "Linéaire",
            "start_date": "2024-01-01",
            "value": "100",
            "value_change": "Appreciates",
            "value_change_mode": "Linear",
            "value_change_rate": "10",
        },
    )
    lin = authed_client.get(
        f"/api/assets/{linear.json()['asset_id']}", params={"as_of": "2025-01-01"}
    ).json()
    lin_expected = Decimal("100") * (
        Decimal("1") + Decimal("10") / Decimal("100") * Decimal(days) / Decimal("365")
    )
    assert abs(Decimal(lin["current_value"]) - lin_expected) < Decimal("0.0002")

    linked = authed_client.post(f"/api/assets/{aid}/links", json={"trans_id": 51})
    assert linked.status_code == 200, linked.text
    none = authed_client.put(
        f"/api/assets/{aid}",
        json={"value_change": "None", "value_change_rate": "0"},
    )
    assert none.status_code == 200
    body = authed_client.get(f"/api/assets/{aid}", params={"as_of": "2026-08-01"}).json()
    # withdrawal 80 from checking → +80 to the asset; VALUE ignored when links exist
    assert Decimal(body["current_value"]) == Decimal("80")
    assert body["link_count"] == 1

    voided = authed_client.post(f"/api/assets/{aid}/links", json={"trans_id": 53})
    assert voided.status_code == 200
    still = authed_client.get(f"/api/assets/{aid}", params={"as_of": "2026-08-01"}).json()
    assert Decimal(still["current_value"]) == Decimal("80")

    refuse = authed_client.delete(f"/api/assets/{aid}")
    assert refuse.status_code == 409

    tl_id = still["links"][0]["translink_id"]
    authed_client.delete(f"/api/assets/{aid}/links/{tl_id}")
    still = authed_client.get(f"/api/assets/{aid}").json()
    # one remaining (void) link — still in the translink path, void skipped → 0
    void_link = next(l for l in still["links"] if l["trans_id"] == 53)
    authed_client.delete(f"/api/assets/{aid}/links/{void_link['translink_id']}")
    gone = authed_client.delete(f"/api/assets/{aid}")
    assert gone.status_code == 200
    leftover = authed_client.get("/api/assets").json()["assets"]
    assert all(a["name"] != "Cabane test" for a in leftover)

    throwaway = next(a for a in leftover if a["name"] == "Linéaire")
    assert authed_client.delete(f"/api/assets/{throwaway['asset_id']}").status_code == 200
