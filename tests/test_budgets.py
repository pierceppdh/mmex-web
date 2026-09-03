from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_domain.budgets import get_estimate
from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def test_estimate_yearly_and_monthly() -> None:
    assert get_estimate(False, "Monthly", "10") == Decimal("120.00")
    assert get_estimate(True, "Monthly", "10") == Decimal("10.00")
    assert get_estimate(False, "Yearly", "120") == Decimal("120.00")
    assert get_estimate(True, "Yearly", "120") == Decimal("10.00")
    assert get_estimate(False, "None", "99") == Decimal("0.00")


def test_budget_crud_actuals_copy_and_cashflow(
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
                "(2, 1, -1, 10, 'Withdrawal', '10', 'V', 2, '2026-03-11T00:00:00', '', '10'),"
                "(3, 1, -1, 10, 'Deposit', '8', '', 1, '2026-03-12T00:00:00', '', '8')"
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
                "INSERT INTO BILLSDEPOSITS_V1 ("
                " BDID, ACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT, REPEATS,"
                " NEXTOCCURRENCEDATE, NUMOCCURRENCES"
                ") VALUES (1, 1, 10, 'Withdrawal', '9.50', 1, :d, -1)"
            ),
            {"d": date.today().replace(day=1).isoformat() + "T00:00:00"},
        )
    engine.dispose()

    created = authed_client.post("/api/budgets", json={"name": "2026"})
    assert created.status_code == 200, created.text
    year_id = created.json()["year_id"]
    assert created.json()["is_monthly"] is False

    bad = authed_client.post("/api/budgets", json={"name": "2026"})
    assert bad.status_code == 400

    saved = authed_client.put(
        f"/api/budgets/{year_id}/entries",
        json={"categ_id": 2, "period": "Monthly", "amount": "10"},
    )
    assert saved.status_code == 200, saved.text
    groc = next(r for r in saved.json()["lines"] if r["categ_id"] == 2)
    assert groc["estimated"] == "120.00"
    assert Decimal(groc["actual"]) == Decimal("25")
    assert Decimal(groc["difference"]) == Decimal("95")
    food = next(r for r in saved.json()["lines"] if r["categ_id"] == 1)
    assert Decimal(food["actual_expense"]) == Decimal("40")
    assert Decimal(food["actual_income"]) == Decimal("8")

    month = authed_client.post("/api/budgets", json={"name": "2026-03"})
    assert month.status_code == 200
    mid = month.json()["year_id"]
    msave = authed_client.put(
        f"/api/budgets/{mid}/entries",
        json={"categ_id": 2, "period": "Monthly", "amount": "10"},
    )
    mline = next(r for r in msave.json()["lines"] if r["categ_id"] == 2)
    assert mline["estimated"] == "10.00"
    assert Decimal(mline["actual"]) == Decimal("25")

    copied = authed_client.post("/api/budgets", json={"name": "2027", "copy_from_id": year_id})
    assert copied.status_code == 200
    assert any(
        r["categ_id"] == 2 and Decimal(r["entry"]["amount"]) == Decimal("10")
        for r in copied.json()["lines"]
        if r["entry"]
    )

    flow = authed_client.get("/api/budgets/cashflow", params={"months": 3})
    assert flow.status_code == 200, flow.text
    series = flow.json()["series"]
    assert len(series) == 3
    this_month = date.today().strftime("%Y-%m")
    row = next(s for s in series if s["month"] == this_month)
    assert Decimal(row["scheduled_out"]) >= Decimal("9.50")

    listed = authed_client.get("/api/budgets").json()
    assert {y["name"] for y in listed["years"]} == {"2026", "2026-03", "2027"}
    assert authed_client.delete(f"/api/budgets/{year_id}").status_code == 200
    assert authed_client.get(f"/api/budgets/{year_id}").status_code == 404
