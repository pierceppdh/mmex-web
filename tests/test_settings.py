from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def test_settings_and_currency_history(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    got = authed_client.get("/api/settings")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["base_currency_id"] == 1
    assert body["use_currency_history"] is False
    assert body["date_format"] == "YYYY-MM-DD"
    assert any(c["symbol"] == "EUR" and c["is_base"] for c in body["currencies"])

    saved = authed_client.put(
        "/api/settings",
        json={
            "username": "pierre-test",
            "use_currency_history": True,
            "date_format": "DD/MM/YYYY",
            "delimiter": ";",
            "financial_year_start_month": 4,
            "financial_year_start_day": 6,
            "share_precision": 6,
            "stock_url": "https://example.test/quote/%s",
            "categ_delimiter": ":",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["username"] == "pierre-test"
    assert saved.json()["use_currency_history"] is True
    assert saved.json()["date_format"] == "DD/MM/YYYY"
    assert saved.json()["delimiter"] == ";"
    assert saved.json()["financial_year_start_month"] == 4
    assert saved.json()["financial_year_start_day"] == 6
    assert saved.json()["share_precision"] == 6

    bad = authed_client.put("/api/settings", json={"date_format": "nope"})
    assert bad.status_code == 400

    hist = authed_client.post(
        "/api/currencies/2/history",
        json={"date": "2026-08-01", "rate": "0.85"},
    )
    assert hist.status_code == 200, hist.text
    assert Decimal(hist.json()["rate"]) == Decimal("0.85")
    assert hist.json()["history"][0]["date"] == "2026-08-01"
    hid = hist.json()["history"][0]["hist_id"]

    again = authed_client.post(
        "/api/currencies/2/history",
        json={"date": "2026-08-01", "rate": "0.88"},
    )
    assert again.status_code == 200
    assert len(again.json()["history"]) == 1
    assert Decimal(again.json()["rate"]) == Decimal("0.88")

    older = authed_client.post(
        "/api/currencies/2/history",
        json={"date": "2020-01-01", "rate": "0.50"},
    )
    assert older.status_code == 200
    assert len(older.json()["history"]) == 2
    assert Decimal(older.json()["rate"]) == Decimal("0.88")

    zero = authed_client.post(
        "/api/currencies/2/history",
        json={"date": "2021-01-01", "rate": "0"},
    )
    assert zero.status_code == 400

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        rate = conn.execute(
            text("SELECT BASECONVRATE FROM CURRENCYFORMATS_V1 WHERE CURRENCYID = 2")
        ).scalar()
        wx = conn.execute(
            text("SELECT INFOVALUE FROM INFOTABLE_V1 WHERE INFONAME = 'DATEFORMAT'")
        ).scalar()
        use = conn.execute(
            text("SELECT INFOVALUE FROM INFOTABLE_V1 WHERE INFONAME = 'USECURRENCYHISTORY'")
        ).scalar()
    engine.dispose()
    assert Decimal(str(rate)) == Decimal("0.88")
    assert wx == "%d/%m/%Y"
    assert str(use).upper() == "TRUE"

    deleted = authed_client.delete(f"/api/currencies/2/history/{hid}")
    assert deleted.status_code == 200
    assert len(deleted.json()["history"]) == 1
    assert Decimal(deleted.json()["rate"]) == Decimal("0.50")

    leftover = deleted.json()["history"][0]["hist_id"]
    cleared = authed_client.delete(f"/api/currencies/2/history/{leftover}")
    assert cleared.status_code == 200
    assert cleared.json()["history"] == []

    missing = authed_client.get("/api/currencies/999/history")
    assert missing.status_code == 404

    base = authed_client.put("/api/settings/base-currency", json={"currency_id": 2})
    assert base.status_code == 200
    assert base.json()["base_currency_id"] == 2
    usd = next(c for c in base.json()["currencies"] if c["currency_id"] == 2)
    assert usd["is_base"] is True
    assert Decimal(usd["rate"]) == Decimal("1")
