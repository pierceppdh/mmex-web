"""BUDGETYEAR_V1 / BUDGETTABLE_V1 and cash-flow (desktop Model_Budget::getEstimate)."""

from __future__ import annotations

import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.constants import STATUS_VOID, TRANS_DEPOSIT, TRANS_TRANSFER, TRANS_WITHDRAWAL
from mmex_domain.lookups import _category_path
from mmex_domain.money import as_decimal
from mmex_domain.repeats import (
    INTERVAL_TYPES,
    ONE_SHOT_TYPES,
    USES_REMAINING,
    decode,
    next_occurrence,
)
from mmex_domain.transactions import _next_id

PERIOD_NONE = "None"
PERIOD_WEEKLY = "Weekly"
PERIOD_BIWEEKLY = "Bi-Weekly"
PERIOD_MONTHLY = "Monthly"
PERIOD_BIMONTHLY = "Bi-Monthly"
PERIOD_QUARTERLY = "Quarterly"
PERIOD_HALFYEARLY = "Half-Yearly"
PERIOD_YEARLY = "Yearly"
PERIOD_DAILY = "Daily"

PERIODS: tuple[tuple[str, int, str, str], ...] = (
    (PERIOD_NONE, 0, "Aucun", "None"),
    (PERIOD_WEEKLY, 52, "Hebdomadaire", "Weekly"),
    (PERIOD_BIWEEKLY, 26, "Toutes les 2 semaines", "Fortnightly"),
    (PERIOD_MONTHLY, 12, "Mensuel", "Monthly"),
    (PERIOD_BIMONTHLY, 6, "Tous les 2 mois", "Every 2 months"),
    (PERIOD_QUARTERLY, 4, "Trimestriel", "Quarterly"),
    (PERIOD_HALFYEARLY, 2, "Semestriel", "Half-yearly"),
    (PERIOD_YEARLY, 1, "Annuel", "Yearly"),
    (PERIOD_DAILY, 365, "Quotidien", "Daily"),
)

PERIOD_MULT = {name: mult for name, mult, _fr, _en in PERIODS}
YEAR_RE = re.compile(r"^(\d{4})$")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


class BudgetError(ValueError):
    """Invalid budget payload or missing year."""


def period_meta() -> list[dict[str, Any]]:
    return [
        {"id": name, "multiplier": mult, "label_fr": fr, "label_en": en}
        for name, mult, fr, en in PERIODS
    ]


def parse_year_name(name: str) -> tuple[bool, date, date]:
    raw = (name or "").strip()
    month_m = MONTH_RE.match(raw)
    if month_m:
        year, month = int(month_m.group(1)), int(month_m.group(2))
        if month < 1 or month > 12:
            raise BudgetError("month must be 01–12")
        last = monthrange(year, month)[1]
        start = date(year, month, 1)
        return True, start, date(year, month, last)
    year_m = YEAR_RE.match(raw)
    if year_m:
        year = int(year_m.group(1))
        return False, date(year, 1, 1), date(year, 12, 31)
    raise BudgetError("name must be YYYY or YYYY-MM")


def _q(value: Any) -> Decimal:
    return as_decimal(value).quantize(Decimal("0.01"))


def get_estimate(is_monthly: bool, period: str, amount: Any) -> Any:
    """Desktop Model_Budget::getEstimate: yearly = amount * multiplier; monthly = yearly / 12."""
    amt = as_decimal(amount)
    mult = PERIOD_MULT.get(period, 0)
    yearly = amt * Decimal(mult)
    if is_monthly:
        return (yearly / Decimal(12)).quantize(Decimal("0.01"))
    return yearly.quantize(Decimal("0.01"))


def _load_cats(conn: Connection) -> dict[int, dict[str, Any]]:
    rows = conn.execute(
        text("SELECT CATEGID, CATEGNAME, PARENTID, IFNULL(ACTIVE, 1) FROM CATEGORY_V1")
    ).fetchall()
    return {
        int(r[0]): {
            "categ_id": int(r[0]),
            "name": r[1],
            "parent_id": int(r[2]) if r[2] is not None and int(r[2]) > 0 else None,
            "active": int(r[3] or 1),
        }
        for r in rows
    }


def _children_map(cats: dict[int, dict[str, Any]]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = defaultdict(list)
    for cid, info in cats.items():
        pid = info.get("parent_id")
        if pid:
            out[int(pid)].append(cid)
    return out


def _subtree(root: int, children: dict[int, list[int]]) -> set[int]:
    out = {root}
    stack = [root]
    while stack:
        cur = stack.pop()
        for child in children.get(cur, []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def list_years(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT y.BUDGETYEARID, y.BUDGETYEARNAME,
                       (SELECT COUNT(*) FROM BUDGETTABLE_V1 e WHERE e.BUDGETYEARID = y.BUDGETYEARID)
                  FROM BUDGETYEAR_V1 y
                 ORDER BY y.BUDGETYEARNAME DESC
                """
            )
        ).fetchall()
    years = []
    for r in rows:
        name = r[1]
        try:
            is_month, start, end = parse_year_name(name)
        except BudgetError:
            is_month, start, end = False, None, None
        years.append(
            {
                "year_id": int(r[0]),
                "name": name,
                "is_monthly": is_month,
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "entry_count": int(r[2] or 0),
            }
        )
    return {"years": years, "periods": period_meta()}


def create_year(engine: Engine, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    parse_year_name(name)
    copy_from = payload.get("copy_from_id")
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT BUDGETYEARID FROM BUDGETYEAR_V1 WHERE BUDGETYEARNAME = :n"),
            {"n": name},
        ).fetchone()
        if exists is not None:
            raise BudgetError("budget year name already exists")
        year_id = _next_id(conn, "BUDGETYEAR_V1", "BUDGETYEARID")
        conn.execute(
            text("INSERT INTO BUDGETYEAR_V1 (BUDGETYEARID, BUDGETYEARNAME) VALUES (:id, :n)"),
            {"id": year_id, "n": name},
        )
        if copy_from:
            src = conn.execute(
                text("SELECT BUDGETYEARID FROM BUDGETYEAR_V1 WHERE BUDGETYEARID = :id"),
                {"id": int(copy_from)},
            ).fetchone()
            if src is None:
                raise BudgetError(f"unknown budget year {copy_from}")
            for row in conn.execute(
                text(
                    """
                    SELECT CATEGID, PERIOD, AMOUNT, NOTES, ACTIVE
                      FROM BUDGETTABLE_V1 WHERE BUDGETYEARID = :id
                    """
                ),
                {"id": int(copy_from)},
            ):
                eid = _next_id(conn, "BUDGETTABLE_V1", "BUDGETENTRYID")
                conn.execute(
                    text(
                        """
                        INSERT INTO BUDGETTABLE_V1 (
                            BUDGETENTRYID, BUDGETYEARID, CATEGID, PERIOD, AMOUNT, NOTES, ACTIVE
                        ) VALUES (:eid, :yid, :cid, :per, :amt, :notes, :act)
                        """
                    ),
                    {
                        "eid": eid,
                        "yid": year_id,
                        "cid": row[0],
                        "per": row[1],
                        "amt": row[2],
                        "notes": row[3] or "",
                        "act": int(row[4] if row[4] is not None else 1),
                    },
                )
    return get_year(engine, year_id)


def delete_year(engine: Engine, year_id: int) -> None:
    with engine.begin() as conn:
        n = conn.execute(
            text("DELETE FROM BUDGETYEAR_V1 WHERE BUDGETYEARID = :id"), {"id": year_id}
        ).rowcount
        if not n:
            raise BudgetError(f"unknown budget year {year_id}")
        conn.execute(text("DELETE FROM BUDGETTABLE_V1 WHERE BUDGETYEARID = :id"), {"id": year_id})


def _actuals(conn: Connection, start: date, end: date) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"income": as_decimal(0), "expense": as_decimal(0)}
    )
    sql = """
        SELECT CATEGID, TRANSCODE, TRANSAMOUNT FROM CHECKINGACCOUNT_V1
         WHERE (DELETEDTIME IS NULL OR DELETEDTIME = '')
           AND IFNULL(STATUS, '') != :void
           AND TRANSCODE IN (:w, :d)
           AND CATEGID IS NOT NULL AND CATEGID > 0
           AND date(TRANSDATE) >= :a AND date(TRANSDATE) <= :b
        UNION ALL
        SELECT s.CATEGID, c.TRANSCODE, s.SPLITTRANSAMOUNT
          FROM SPLITTRANSACTIONS_V1 s
          JOIN CHECKINGACCOUNT_V1 c ON c.TRANSID = s.TRANSID
         WHERE (c.DELETEDTIME IS NULL OR c.DELETEDTIME = '')
           AND IFNULL(c.STATUS, '') != :void
           AND c.TRANSCODE IN (:w, :d)
           AND s.CATEGID IS NOT NULL AND s.CATEGID > 0
           AND date(c.TRANSDATE) >= :a AND date(c.TRANSDATE) <= :b
    """
    params = {
        "void": STATUS_VOID,
        "w": TRANS_WITHDRAWAL,
        "d": TRANS_DEPOSIT,
        "a": start.isoformat(),
        "b": end.isoformat(),
    }
    for cid, code, amt in conn.execute(text(sql), params):
        amount = as_decimal(amt)
        bucket = out[int(cid)]
        if code == TRANS_DEPOSIT:
            bucket["income"] += amount
        else:
            bucket["expense"] += amount
    return out


def get_year(engine: Engine, year_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT BUDGETYEARID, BUDGETYEARNAME FROM BUDGETYEAR_V1 WHERE BUDGETYEARID = :id"),
            {"id": year_id},
        ).fetchone()
        if row is None:
            raise BudgetError(f"unknown budget year {year_id}")
        name = row[1]
        is_monthly, start, end = parse_year_name(name)
        cats = _load_cats(conn)
        children = _children_map(cats)
        entries = conn.execute(
            text(
                """
                SELECT BUDGETENTRYID, CATEGID, PERIOD, AMOUNT, NOTES, IFNULL(ACTIVE, 1)
                  FROM BUDGETTABLE_V1
                 WHERE BUDGETYEARID = :id
                 ORDER BY BUDGETENTRYID
                """
            ),
            {"id": year_id},
        ).fetchall()
        by_categ = {
            int(e[1]): {
                "entry_id": int(e[0]),
                "categ_id": int(e[1]),
                "period": e[2] or PERIOD_NONE,
                "amount": str(as_decimal(e[3])),
                "notes": e[4] or "",
                "active": int(e[5] or 1),
            }
            for e in entries
            if e[1] is not None
        }
        leaf_actuals = _actuals(conn, start, end)

    def rolled(cid: int) -> dict[str, Any]:
        income = as_decimal(0)
        expense = as_decimal(0)
        for node in _subtree(cid, children):
            leaf = leaf_actuals.get(node)
            if not leaf:
                continue
            income += leaf["income"]
            expense += leaf["expense"]
        return {"income": income, "expense": expense}

    lines = []
    total_est = as_decimal(0)
    total_act = as_decimal(0)
    for cid, info in cats.items():
        entry = by_categ.get(cid)
        act = rolled(cid)
        estimated = as_decimal(0)
        if entry and entry["active"]:
            estimated = get_estimate(is_monthly, entry["period"], entry["amount"])
        income, expense = act["income"], act["expense"]
        kind = "income" if income > expense else "expense"
        actual = income if kind == "income" else expense
        if estimated == 0 and actual == 0 and entry is None:
            continue
        total_est += estimated
        total_act += actual
        line = {
            "categ_id": cid,
            "name": info["name"],
            "parent_id": info["parent_id"],
            "path": _category_path(cid, cats),
            "kind": kind,
            "estimated": str(estimated),
            "actual": str(actual),
            "actual_income": str(income),
            "actual_expense": str(expense),
            "difference": str(estimated - actual),
            "entry": entry,
        }
        lines.append(line)
    lines.sort(key=lambda r: r["path"].lower())
    return {
        "year_id": year_id,
        "name": name,
        "is_monthly": is_monthly,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "lines": lines,
        "totals": {
            "estimated": str(total_est),
            "actual": str(total_act),
            "difference": str(total_est - total_act),
        },
        "periods": period_meta(),
    }


def upsert_entry(engine: Engine, year_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    categ_id = int(payload.get("categ_id") or 0)
    if categ_id <= 0:
        raise BudgetError("categ_id is required")
    period = str(payload.get("period") or PERIOD_MONTHLY)
    if period not in PERIOD_MULT:
        raise BudgetError("invalid period")
    amount = as_decimal(payload.get("amount"))
    if amount < 0:
        raise BudgetError("amount must be >= 0")
    notes = str(payload.get("notes") or "")
    active = 1 if payload.get("active", 1) else 0
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT BUDGETYEARID FROM BUDGETYEAR_V1 WHERE BUDGETYEARID = :id"),
            {"id": year_id},
        ).fetchone()
        if exists is None:
            raise BudgetError(f"unknown budget year {year_id}")
        cat = conn.execute(
            text("SELECT CATEGID FROM CATEGORY_V1 WHERE CATEGID = :id"), {"id": categ_id}
        ).fetchone()
        if cat is None:
            raise BudgetError(f"unknown category {categ_id}")
        current = conn.execute(
            text(
                "SELECT BUDGETENTRYID FROM BUDGETTABLE_V1 "
                "WHERE BUDGETYEARID = :y AND CATEGID = :c"
            ),
            {"y": year_id, "c": categ_id},
        ).fetchone()
        if current is None:
            eid = _next_id(conn, "BUDGETTABLE_V1", "BUDGETENTRYID")
            conn.execute(
                text(
                    """
                    INSERT INTO BUDGETTABLE_V1 (
                        BUDGETENTRYID, BUDGETYEARID, CATEGID, PERIOD, AMOUNT, NOTES, ACTIVE
                    ) VALUES (:eid, :yid, :cid, :per, :amt, :notes, :act)
                    """
                ),
                {
                    "eid": eid,
                    "yid": year_id,
                    "cid": categ_id,
                    "per": period,
                    "amt": str(amount),
                    "notes": notes,
                    "act": active,
                },
            )
        else:
            conn.execute(
                text(
                    """
                    UPDATE BUDGETTABLE_V1
                       SET PERIOD = :per, AMOUNT = :amt, NOTES = :notes, ACTIVE = :act
                     WHERE BUDGETENTRYID = :eid
                    """
                ),
                {
                    "per": period,
                    "amt": str(amount),
                    "notes": notes,
                    "act": active,
                    "eid": int(current[0]),
                },
            )
    return get_year(engine, year_id)


def delete_entry(engine: Engine, year_id: int, categ_id: int) -> dict[str, Any]:
    with engine.begin() as conn:
        n = conn.execute(
            text(
                "DELETE FROM BUDGETTABLE_V1 WHERE BUDGETYEARID = :y AND CATEGID = :c"
            ),
            {"y": year_id, "c": categ_id},
        ).rowcount
        if not n:
            raise BudgetError("unknown budget entry")
    return get_year(engine, year_id)


def _month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _add_months(day: date, months: int) -> date:
    year = day.year + (day.month - 1 + months) // 12
    month = (day.month - 1 + months) % 12 + 1
    last = monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def cashflow(engine: Engine, months: int = 12) -> dict[str, Any]:
    """Project scheduled in/out and overlay monthly budget estimates. Transfers net to 0."""
    months = max(1, min(int(months), 24))
    today = date.today()
    start = date(today.year, today.month, 1)
    end = _add_months(start, months) - timedelta(days=1)
    from mmex_domain.balances import account_rows

    payload = account_rows(engine)
    opening = as_decimal(0)
    for acc in payload["accounts"]:
        if acc["status"] != "Open":
            continue
        if acc["account_type"] not in ("Cash", "Checking", "Credit Card"):
            continue
        opening += as_decimal(acc["display_value_base"])

    inflow: dict[str, Any] = defaultdict(lambda: as_decimal(0))
    outflow: dict[str, Any] = defaultdict(lambda: as_decimal(0))
    with engine.connect() as conn:
        bills = conn.execute(
            text(
                """
                SELECT TRANSCODE, TRANSAMOUNT, REPEATS, NEXTOCCURRENCEDATE, NUMOCCURRENCES
                  FROM BILLSDEPOSITS_V1
                """
            )
        ).fetchall()
        years = conn.execute(
            text("SELECT BUDGETYEARID, BUDGETYEARNAME FROM BUDGETYEAR_V1")
        ).fetchall()
        entries_by_year: dict[int, list[Any]] = defaultdict(list)
        for e in conn.execute(
            text("SELECT BUDGETYEARID, PERIOD, AMOUNT, IFNULL(ACTIVE,1) FROM BUDGETTABLE_V1")
        ):
            entries_by_year[int(e[0])].append(e)

    for code, amt, repeats, nxt, num in bills:
        if not nxt:
            continue
        kind, _auto = decode(repeats)
        remaining = int(num if num is not None else -1)
        try:
            day = date.fromisoformat(str(nxt)[:10])
        except ValueError:
            continue
        for _ in range(48):
            if day > end:
                break
            if day >= start and code != TRANS_TRANSFER:
                key = _month_key(day)
                amount = as_decimal(amt)
                if code == TRANS_DEPOSIT:
                    inflow[key] += amount
                else:
                    outflow[key] += amount
            if kind in ONE_SHOT_TYPES or (kind in USES_REMAINING and remaining == 1):
                break
            interval = remaining if kind in INTERVAL_TYPES else 1
            nxt_day = next_occurrence(day, kind, interval)
            if nxt_day <= day:
                break
            if kind in USES_REMAINING and remaining > 1:
                remaining -= 1
            day = nxt_day

    budget_out: dict[str, Any] = defaultdict(lambda: as_decimal(0))
    year_rows = []
    for yid, yname in years:
        try:
            is_monthly, ystart, yend = parse_year_name(yname)
        except BudgetError:
            continue
        year_rows.append((int(yid), yname, is_monthly, ystart, yend))

    cursor = start
    for _ in range(months):
        key = _month_key(cursor)
        chosen = None
        yearly = None
        for yid, yname, is_monthly, ystart, yend in year_rows:
            if is_monthly and ystart <= cursor <= yend:
                chosen = (yid, True)
                break
            if not is_monthly and ystart <= cursor <= yend:
                yearly = (yid, False)
        use = chosen or yearly
        if use:
            yid, _is_month_year = use
            est = as_decimal(0)
            for _y, period, amount, active in entries_by_year.get(yid, []):
                if int(active or 1):
                    est += get_estimate(True, period, amount)
            budget_out[key] = est
        cursor = _add_months(cursor, 1)

    series = []
    running = _q(opening)
    cursor = start
    for _ in range(months):
        key = _month_key(cursor)
        inn = _q(inflow[key])
        outv = _q(outflow[key])
        net = inn - outv
        running += net
        series.append(
            {
                "month": key,
                "scheduled_in": str(inn),
                "scheduled_out": str(outv),
                "scheduled_net": str(net),
                "budget_monthly": str(_q(budget_out[key])),
                "projected": str(running),
            }
        )
        cursor = _add_months(cursor, 1)
    return {
        "opening": str(_q(opening)),
        "months": months,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "series": series,
    }
