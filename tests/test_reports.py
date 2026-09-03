from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def test_income_expense_categories_payees_ignore_void_and_splits(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO CHECKINGACCOUNT_V1 ("
                " TRANSID, ACCOUNTID, TOACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT,"
                " STATUS, CATEGID, TRANSDATE, DELETEDTIME, TOTRANSAMOUNT"
                ") VALUES "
                "(1, 1, -1, 10, 'Withdrawal', '40', '', -1, '2026-03-10T00:00:00', '', '40'),"
                "(2, 1, -1, 10, 'Deposit', '100', '', 1, '2026-03-15T00:00:00', '', '100'),"
                "(3, 1, -1, 10, 'Withdrawal', '7', 'V', 2, '2026-03-16T00:00:00', '', '7'),"
                "(4, 1, -1, 10, 'Transfer', '50', '', 2, '2026-03-17T00:00:00', '', '50')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO SPLITTRANSACTIONS_V1 (SPLITTRANSID, TRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES) "
                "VALUES (1, 1, 2, 25, ''), (2, 1, 3, 15, '')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO STOCK_V1 ("
                " STOCKID, HELDAT, PURCHASEDATE, STOCKNAME, SYMBOL, NUMSHARES,"
                " PURCHASEPRICE, CURRENTPRICE, VALUE, COMMISSION"
                ") VALUES (1, 1, '2020-01-01', 'Acme', 'ACM', 10, 5, 7.5, 75, 0)"
            )
        )
    engine.dispose()

    catalog = authed_client.get("/api/reports")
    assert catalog.status_code == 200
    ids = [r["id"] for r in catalog.json()["reports"]]
    assert ids == [
        "income_expenses",
        "categories",
        "payees",
        "cashflow",
        "accounts",
        "budget",
        "stocks",
        "usage",
    ]

    ie = authed_client.get(
        "/api/reports/income_expenses",
        params={"date_from": "2026-03-01", "date_to": "2026-03-31"},
    )
    assert ie.status_code == 200, ie.text
    totals = ie.json()["totals"]
    assert Decimal(totals["income"]) == Decimal("100")
    assert Decimal(totals["expense"]) == Decimal("40")
    assert Decimal(totals["net"]) == Decimal("60")
    assert ie.json()["series"][0]["month"] == "2026-03"

    cats = authed_client.get(
        "/api/reports/categories",
        params={"date_from": "2026-03-01", "date_to": "2026-03-31"},
    ).json()["rows"]
    by_path = {r["path"]: r for r in cats}
    assert Decimal(by_path["Food : Groceries"]["expense"]) == Decimal("25")
    assert Decimal(by_path["Food : Dining"]["expense"]) == Decimal("15")
    assert Decimal(by_path["Food"]["income"]) == Decimal("100")

    payees = authed_client.get(
        "/api/reports/payees",
        params={"date_from": "2026-03-01", "date_to": "2026-03-31"},
    ).json()["rows"]
    boul = next(r for r in payees if r["name"] == "Boulanger")
    assert Decimal(boul["income"]) == Decimal("100")
    assert Decimal(boul["expense"]) == Decimal("40")

    usage = authed_client.get(
        "/api/reports/usage",
        params={"date_from": "2026-03-01", "date_to": "2026-03-31"},
    ).json()
    assert usage["total"] >= 3

    stocks = authed_client.get("/api/reports/stocks").json()
    assert Decimal(stocks["rows"][0]["market"]) == Decimal("75")

    accounts = authed_client.get("/api/reports/accounts")
    assert accounts.status_code == 200
    assert "net_worth" in accounts.json()

    missing = authed_client.get("/api/reports/nope")
    assert missing.status_code == 404
