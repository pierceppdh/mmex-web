"""Built-in reports in base currency (desktop income/expense, categories, payees)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterator

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.balances import account_rows, load_currencies
from mmex_domain.budgets import cashflow, get_year, list_years
from mmex_domain.constants import STATUS_VOID, TRANS_DEPOSIT, TRANS_WITHDRAWAL
from mmex_domain.lookups import _category_path
from mmex_domain.money import as_decimal, to_base

REPORTS: tuple[tuple[str, str, str], ...] = (
    ("income_expenses", "Recettes vs dépenses", "Income vs expenses"),
    ("categories", "Catégories", "Categories"),
    ("payees", "Tiers", "Payees"),
    ("cashflow", "Trésorerie", "Cash flow"),
    ("accounts", "Comptes", "Accounts"),
    ("budget", "Budget", "Budget"),
    ("stocks", "Titres", "Stocks"),
    ("usage", "Activité", "My usage"),
)


class ReportError(ValueError):
    """Unknown report or invalid range."""


def catalog() -> dict[str, Any]:
    return {
        "reports": [
            {"id": rid, "label_fr": fr, "label_en": en} for rid, fr, en in REPORTS
        ]
    }


def _q(value: Any) -> Decimal:
    return as_decimal(value).quantize(Decimal("0.01"))


def _parse_day(value: str | None, fallback: date) -> date:
    raw = (value or "").strip()
    if not raw:
        return fallback
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    return date.fromisoformat(raw[:10])


def _range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    today = date.today()
    start = _parse_day(date_from, date(today.year, 1, 1))
    end = _parse_day(date_to, today)
    if start > end:
        raise ReportError("date_from must be on or before date_to")
    return start, end


def _base(conn: Connection) -> tuple[dict[int, dict[str, Any]], Decimal, dict[str, str]]:
    currencies = load_currencies(conn)
    info = {str(k): str(v) for k, v in conn.execute(text("SELECT INFONAME, INFOVALUE FROM INFOTABLE_V1"))}
    try:
        base_id = int(info.get("BASECURRENCYID") or 0)
    except ValueError:
        base_id = 0
    base = currencies.get(base_id) or next(iter(currencies.values()), None)
    base_rate = as_decimal(base["rate"]) if base else Decimal("1")
    return currencies, base_rate, {
        "name": base["name"] if base else "",
        "symbol": base["symbol"] if base else "",
    }


def _to_base(amount: Any, currency_id: int | None, currencies: dict[int, dict[str, Any]], base_rate: Decimal) -> Decimal:
    cur = currencies.get(int(currency_id or 0))
    rate = as_decimal(cur["rate"]) if cur else Decimal("1")
    return to_base(as_decimal(amount), rate, base_rate)


def _facts(
    conn: Connection,
    start: date,
    end: date,
    currencies: dict[int, dict[str, Any]],
    base_rate: Decimal,
) -> Iterator[dict[str, Any]]:
    params = {
        "a": start.isoformat(),
        "b": end.isoformat(),
        "void": STATUS_VOID,
        "w": TRANS_WITHDRAWAL,
        "d": TRANS_DEPOSIT,
    }
    sql = """
        SELECT date(c.TRANSDATE), c.TRANSCODE, c.TRANSAMOUNT, c.CATEGID, c.PAYEEID,
               p.PAYEENAME, a.CURRENCYID, c.TRANSID
          FROM CHECKINGACCOUNT_V1 c
          JOIN ACCOUNTLIST_V1 a ON a.ACCOUNTID = c.ACCOUNTID
          LEFT JOIN PAYEE_V1 p ON p.PAYEEID = c.PAYEEID
         WHERE (c.DELETEDTIME IS NULL OR c.DELETEDTIME = '')
           AND IFNULL(c.STATUS, '') != :void
           AND c.TRANSCODE IN (:w, :d)
           AND date(c.TRANSDATE) >= :a AND date(c.TRANSDATE) <= :b
           AND NOT EXISTS (
                 SELECT 1 FROM SPLITTRANSACTIONS_V1 s WHERE s.TRANSID = c.TRANSID
           )
        UNION ALL
        SELECT date(c.TRANSDATE), c.TRANSCODE, s.SPLITTRANSAMOUNT, s.CATEGID, c.PAYEEID,
               p.PAYEENAME, a.CURRENCYID, c.TRANSID
          FROM SPLITTRANSACTIONS_V1 s
          JOIN CHECKINGACCOUNT_V1 c ON c.TRANSID = s.TRANSID
          JOIN ACCOUNTLIST_V1 a ON a.ACCOUNTID = c.ACCOUNTID
          LEFT JOIN PAYEE_V1 p ON p.PAYEEID = c.PAYEEID
         WHERE (c.DELETEDTIME IS NULL OR c.DELETEDTIME = '')
           AND IFNULL(c.STATUS, '') != :void
           AND c.TRANSCODE IN (:w, :d)
           AND date(c.TRANSDATE) >= :a AND date(c.TRANSDATE) <= :b
    """
    for day, code, amt, cid, pid, pname, cur, tid in conn.execute(text(sql), params):
        yield {
            "day": str(day or "")[:10],
            "month": str(day or "")[:7],
            "code": code,
            "amount": _to_base(amt, cur, currencies, base_rate),
            "categ_id": int(cid) if cid is not None and int(cid) > 0 else None,
            "payee_id": int(pid) if pid is not None and int(pid) > 0 else None,
            "payee_name": pname,
            "trans_id": int(tid),
        }


def run_report(
    engine: Engine,
    report_id: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    year_id: int | None = None,
) -> dict[str, Any]:
    known = {rid: (fr, en) for rid, fr, en in REPORTS}
    if report_id not in known:
        raise ReportError(f"unknown report {report_id}")
    start, end = _range(date_from, date_to)
    label_fr, label_en = known[report_id]
    with engine.connect() as conn:
        currencies, base_rate, base_meta = _base(conn)
        payload: dict[str, Any] = {
            "id": report_id,
            "label_fr": label_fr,
            "label_en": label_en,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "base_currency": base_meta,
        }
        if report_id == "income_expenses":
            payload.update(_income_expenses(conn, start, end, currencies, base_rate))
        elif report_id == "categories":
            payload.update(_categories(conn, start, end, currencies, base_rate))
        elif report_id == "payees":
            payload.update(_payees(conn, start, end, currencies, base_rate))
        elif report_id == "usage":
            payload.update(_usage(conn, start, end))
        elif report_id == "stocks":
            payload.update(_stocks(conn))
        elif report_id == "accounts":
            pass
        elif report_id == "cashflow":
            pass
        elif report_id == "budget":
            pass
    if report_id == "accounts":
        rows = account_rows(engine)
        payload["groups"] = rows["groups"]
        payload["net_worth"] = rows["net_worth"]
        payload["net_worth_formatted"] = rows["net_worth_formatted"]
        payload["series"] = [
            {"name": a["name"], "value": str(_q(a["display_value_base"]))}
            for a in rows["accounts"]
            if a["status"] == "Open"
        ]
    elif report_id == "cashflow":
        payload.update(cashflow(engine, months=12))
    elif report_id == "budget":
        years = list_years(engine)["years"]
        payload["years"] = years
        chosen = year_id or (years[0]["year_id"] if years else None)
        payload["year"] = get_year(engine, int(chosen)) if chosen else None
    return payload


def _income_expenses(
    conn: Connection, start: date, end: date, currencies: dict, base_rate: Decimal
) -> dict[str, Any]:
    by_month: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"income": Decimal("0"), "expense": Decimal("0")}
    )
    total_in = Decimal("0")
    total_out = Decimal("0")
    for fact in _facts(conn, start, end, currencies, base_rate):
        bucket = by_month[fact["month"] or ""]
        if fact["code"] == TRANS_DEPOSIT:
            bucket["income"] += fact["amount"]
            total_in += fact["amount"]
        else:
            bucket["expense"] += fact["amount"]
            total_out += fact["amount"]
    series = [
        {
            "month": month,
            "income": str(_q(vals["income"])),
            "expense": str(_q(vals["expense"])),
            "net": str(_q(vals["income"] - vals["expense"])),
        }
        for month, vals in sorted(by_month.items())
    ]
    return {
        "series": series,
        "totals": {
            "income": str(_q(total_in)),
            "expense": str(_q(total_out)),
            "net": str(_q(total_in - total_out)),
        },
    }


def _categories(
    conn: Connection, start: date, end: date, currencies: dict, base_rate: Decimal
) -> dict[str, Any]:
    cats = {
        int(r[0]): {
            "categ_id": int(r[0]),
            "name": r[1],
            "parent_id": int(r[2]) if r[2] is not None and int(r[2]) > 0 else None,
        }
        for r in conn.execute(text("SELECT CATEGID, CATEGNAME, PARENTID FROM CATEGORY_V1"))
    }
    income: dict[int | None, Decimal] = defaultdict(lambda: Decimal("0"))
    expense: dict[int | None, Decimal] = defaultdict(lambda: Decimal("0"))
    for fact in _facts(conn, start, end, currencies, base_rate):
        cid = fact["categ_id"]
        if fact["code"] == TRANS_DEPOSIT:
            income[cid] += fact["amount"]
        else:
            expense[cid] += fact["amount"]
    keys = set(income) | set(expense)
    rows = []
    for cid in keys:
        path = _category_path(cid, cats) if cid and cid in cats else "—"
        rows.append(
            {
                "categ_id": cid,
                "path": path,
                "income": str(_q(income[cid])),
                "expense": str(_q(expense[cid])),
            }
        )
    rows.sort(key=lambda r: as_decimal(r["expense"]) + as_decimal(r["income"]), reverse=True)
    return {"rows": rows, "series": rows[:12]}


def _payees(
    conn: Connection, start: date, end: date, currencies: dict, base_rate: Decimal
) -> dict[str, Any]:
    income: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    expense: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for fact in _facts(conn, start, end, currencies, base_rate):
        name = fact["payee_name"] or "—"
        if fact["code"] == TRANS_DEPOSIT:
            income[name] += fact["amount"]
        else:
            expense[name] += fact["amount"]
    names = set(income) | set(expense)
    rows = [
        {
            "name": name,
            "income": str(_q(income[name])),
            "expense": str(_q(expense[name])),
        }
        for name in names
    ]
    rows.sort(key=lambda r: as_decimal(r["expense"]) + as_decimal(r["income"]), reverse=True)
    return {"rows": rows, "series": rows[:12]}


def _usage(conn: Connection, start: date, end: date) -> dict[str, Any]:
    rows = conn.execute(
        text(
            """
            SELECT strftime('%Y-%m', TRANSDATE) AS YM, COUNT(*)
              FROM CHECKINGACCOUNT_V1
             WHERE (DELETEDTIME IS NULL OR DELETEDTIME = '')
               AND date(TRANSDATE) >= :a AND date(TRANSDATE) <= :b
             GROUP BY YM
             ORDER BY YM
            """
        ),
        {"a": start.isoformat(), "b": end.isoformat()},
    ).fetchall()
    series = [{"month": r[0], "count": int(r[1])} for r in rows]
    return {"series": series, "total": sum(s["count"] for s in series)}


def _stocks(conn: Connection) -> dict[str, Any]:
    rows = conn.execute(
        text(
            """
            SELECT s.STOCKID, s.STOCKNAME, s.SYMBOL, s.NUMSHARES, s.CURRENTPRICE,
                   s.PURCHASEPRICE, a.ACCOUNTNAME, a.CURRENCYID
              FROM STOCK_V1 s
              LEFT JOIN ACCOUNTLIST_V1 a ON a.ACCOUNTID = s.HELDAT
             ORDER BY s.STOCKNAME
            """
        )
    ).fetchall()
    currencies, base_rate, _base_meta = _base(conn)
    out = []
    total = Decimal("0")
    for r in rows:
        market = as_decimal(r[3]) * as_decimal(r[4])
        base = _to_base(market, r[7], currencies, base_rate)
        total += base
        out.append(
            {
                "stock_id": int(r[0]),
                "name": r[1],
                "symbol": r[2] or "",
                "shares": str(as_decimal(r[3])),
                "price": str(_q(r[4])),
                "market": str(_q(market)),
                "market_base": str(_q(base)),
                "account_name": r[6],
            }
        )
    return {"rows": out, "series": out, "total_base": str(_q(total))}
