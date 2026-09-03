"""Account balances matching desktop MMEX (checking flow + stock market value).

Checking flow (Model_Checking::account_flow):
- skip STATUS ``V`` (void) and rows with DELETEDTIME
- source: Deposit +, Withdrawal/Transfer −TRANSAMOUNT
- destination of Transfer: +TOTRANSAMOUNT (fallback TRANSAMOUNT)
Then add ACCOUNTLIST.INITIALBAL.

Investment display value is the stock market value (NUMSHARES * CURRENTPRICE).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.money import as_decimal, format_amount, to_base

ACCOUNT_TYPE_ORDER = (
    "Cash",
    "Checking",
    "Credit Card",
    "Term",
    "Loan",
    "Investment",
    "Asset",
    "Shares",
)

ACCOUNT_TYPE_LABEL_FR = {
    "Cash": "Espèces",
    "Checking": "Comptes bancaires",
    "Credit Card": "Cartes de crédit",
    "Term": "Comptes à terme",
    "Loan": "Prêts",
    "Investment": "Portefeuilles de titres",
    "Asset": "Actifs",
    "Shares": "Actions",
}

ACCOUNT_TYPE_LABEL_EN = {
    "Cash": "Cash",
    "Checking": "Bank accounts",
    "Credit Card": "Credit cards",
    "Term": "Term accounts",
    "Loan": "Loans",
    "Investment": "Investment portfolios",
    "Asset": "Assets",
    "Shares": "Shares",
}

def _flow_sql(*, reconciled: bool = False) -> str:
    rec = "AND IFNULL(STATUS, '') = 'R'" if reconciled else ""
    return f"""
SELECT ACCOUNTID AS AID,
       CASE
           WHEN TRANSCODE = 'Deposit' THEN TRANSAMOUNT
           WHEN TRANSCODE IN ('Withdrawal', 'Transfer') THEN -TRANSAMOUNT
           ELSE 0
       END AS FLOW
  FROM CHECKINGACCOUNT_V1
 WHERE (DELETEDTIME IS NULL OR DELETEDTIME = '')
   AND IFNULL(STATUS, '') != 'V'
   {rec}
UNION ALL
SELECT TOACCOUNTID AS AID,
       COALESCE(NULLIF(TOTRANSAMOUNT, 0), TRANSAMOUNT) AS FLOW
  FROM CHECKINGACCOUNT_V1
 WHERE TRANSCODE = 'Transfer'
   AND TOACCOUNTID IS NOT NULL AND TOACCOUNTID > 0
   AND (DELETEDTIME IS NULL OR DELETEDTIME = '')
   AND IFNULL(STATUS, '') != 'V'
   {rec}
"""


FLOW_SQL = _flow_sql()
RECON_FLOW_SQL = _flow_sql(reconciled=True)

STOCK_SQL = """
SELECT HELDAT AS AID,
       COALESCE(SUM(COALESCE(NUMSHARES, 0) * COALESCE(CURRENTPRICE, 0)), 0) AS MARKET
  FROM STOCK_V1
 GROUP BY HELDAT
"""


def _info_map(conn: Connection) -> dict[str, str]:
    rows = conn.execute(text("SELECT INFONAME, INFOVALUE FROM INFOTABLE_V1"))
    return {str(k): str(v) for k, v in rows}


def load_currencies(conn: Connection) -> dict[int, dict[str, Any]]:
    hist_rows = conn.execute(
        text(
            """
            SELECT h.CURRENCYID, h.CURRVALUE
              FROM CURRENCYHISTORY_V1 h
              JOIN (
                    SELECT CURRENCYID, MAX(CURRDATE) AS MAXDATE
                      FROM CURRENCYHISTORY_V1
                     GROUP BY CURRENCYID
                   ) m ON m.CURRENCYID = h.CURRENCYID AND m.MAXDATE = h.CURRDATE
            """
        )
    )
    latest_hist = {int(r[0]): as_decimal(r[1]) for r in hist_rows}

    use_hist = _info_map(conn).get("USECURRENCYHISTORY", "FALSE").upper() == "TRUE"
    out: dict[int, dict[str, Any]] = {}
    for row in conn.execute(
        text(
            """
            SELECT CURRENCYID, CURRENCYNAME, PFX_SYMBOL, SFX_SYMBOL, DECIMAL_POINT,
                   GROUP_SEPARATOR, SCALE, BASECONVRATE, CURRENCY_SYMBOL, CURRENCY_TYPE
              FROM CURRENCYFORMATS_V1
            """
        )
    ):
        cid = int(row[0])
        base_rate = as_decimal(row[7])
        rate = latest_hist.get(cid, base_rate) if use_hist else base_rate
        if rate == 0:
            rate = Decimal("1")
        out[cid] = {
            "currency_id": cid,
            "name": row[1],
            "pfx": row[2] or "",
            "sfx": row[3] or "",
            "decimal_point": row[4] if row[4] is not None else ".",
            "group_separator": row[5] if row[5] is not None else " ",
            "scale": int(row[6] or 100),
            "base_conv_rate": str(base_rate),
            "rate": rate,
            "symbol": row[8],
            "currency_type": row[9],
        }
    return out


def checking_flows(conn: Connection, *, reconciled: bool = False) -> dict[int, Decimal]:
    sql = RECON_FLOW_SQL if reconciled else FLOW_SQL
    flows: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for aid, flow in conn.execute(text(sql)):
        if aid is None:
            continue
        flows[int(aid)] += as_decimal(flow)
    return flows


def _format(currency: dict[str, Any] | None, value: Decimal) -> str:
    return format_amount(
        value,
        scale=currency["scale"] if currency else 100,
        pfx=currency["pfx"] if currency else "",
        sfx=currency["sfx"] if currency else "",
        decimal_point=currency["decimal_point"] if currency else ".",
        group_separator=currency["group_separator"] if currency else " ",
    )


def stock_markets(conn: Connection) -> dict[int, Decimal]:
    markets: dict[int, Decimal] = {}
    for aid, market in conn.execute(text(STOCK_SQL)):
        if aid is None:
            continue
        markets[int(aid)] = as_decimal(market)
    return markets


def _is_favorite(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().upper() in {"TRUE", "1", "YES", "Y"}


def account_rows(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        info = _info_map(conn)
        currencies = load_currencies(conn)
        flows = checking_flows(conn)
        recon_flows = checking_flows(conn, reconciled=True)
        markets = stock_markets(conn)
        try:
            base_id = int(info.get("BASECURRENCYID") or 0)
        except ValueError:
            base_id = 0
        base = currencies.get(base_id) or next(iter(currencies.values()), None)
        base_rate = as_decimal(base["rate"]) if base else Decimal("1")

        accounts: list[dict[str, Any]] = []
        for row in conn.execute(
            text(
                """
                SELECT ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, STATUS, FAVORITEACCT,
                       INITIALBAL, CURRENCYID, STATEMENTLOCKED, STATEMENTDATE,
                       CREDITLIMIT, MINIMUMPAYMENT, PAYMENTDUEDATE
                  FROM ACCOUNTLIST_V1
                 ORDER BY ACCOUNTTYPE, ACCOUNTNAME
                """
            )
        ):
            aid = int(row[0])
            currency = currencies.get(int(row[6]))
            initial = as_decimal(row[5])
            flow = flows.get(aid, Decimal("0"))
            balance = initial + flow
            market = markets.get(aid, Decimal("0"))
            acct_type = row[2]
            display = market if acct_type == "Investment" else balance
            rate = as_decimal(currency["rate"]) if currency else Decimal("1")
            display_base = to_base(display, rate, base_rate)
            formatted = _format(currency, display)
            recon = initial + recon_flows.get(aid, Decimal("0"))
            diff = display - recon
            stmt_date = row[8] or ""
            if "T" in str(stmt_date):
                stmt_date = str(stmt_date).split("T", 1)[0]
            accounts.append(
                {
                    "account_id": aid,
                    "name": row[1],
                    "account_type": acct_type,
                    "status": row[3],
                    "favorite": _is_favorite(row[4]),
                    "currency_id": int(row[6]),
                    "currency_symbol": currency["symbol"] if currency else None,
                    "balance": str(balance),
                    "market_value": str(market),
                    "display_value": str(display),
                    "display_value_base": str(display_base),
                    "display_formatted": formatted,
                    "reconciled_balance": str(recon),
                    "reconciled_formatted": _format(currency, recon),
                    "difference": str(diff),
                    "difference_formatted": _format(currency, diff),
                    "statement_locked": int(row[7] or 0),
                    "statement_date": (str(stmt_date)[:10] or None),
                    "credit_limit": str(as_decimal(row[9])),
                    "minimum_payment": str(as_decimal(row[10])),
                    "payment_due_date": (str(row[11] or "")[:10] or None),
                }
            )

        upcoming = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM BILLSDEPOSITS_V1
                 WHERE NEXTOCCURRENCEDATE IS NOT NULL
                   AND NEXTOCCURRENCEDATE != ''
                   AND date(NEXTOCCURRENCEDATE) <= date('now', '+14 days')
                """
            )
        ).scalar()

    groups = _group_accounts(accounts)
    open_accounts = [a for a in accounts if a["status"] == "Open"]
    net_worth = sum((as_decimal(a["display_value_base"]) for a in open_accounts), Decimal("0"))
    base_formatted = format_amount(
        net_worth,
        scale=base["scale"] if base else 100,
        pfx=base["pfx"] if base else "",
        sfx=base["sfx"] if base else "",
        decimal_point=base["decimal_point"] if base else ".",
        group_separator=base["group_separator"] if base else " ",
    )
    return {
        "base_currency": (
            {
                "currency_id": base["currency_id"],
                "name": base["name"],
                "symbol": base["symbol"],
            }
            if base
            else None
        ),
        "net_worth": str(net_worth),
        "net_worth_formatted": base_formatted,
        "upcoming_bills": int(upcoming or 0),
        "accounts": accounts,
        "groups": groups,
        "closed_accounts": [a for a in accounts if a["status"] != "Open"],
        "favorites": [a for a in open_accounts if a["favorite"]],
    }


def _group_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for acc in accounts:
        if acc["status"] != "Open":
            continue
        by_type[acc["account_type"]].append(acc)
    groups = []
    seen: set[str] = set()
    for type_name in ACCOUNT_TYPE_ORDER:
        rows = by_type.get(type_name)
        if not rows:
            continue
        seen.add(type_name)
        groups.append(_make_group(type_name, rows))
    for type_name, rows in by_type.items():
        if type_name in seen:
            continue
        groups.append(_make_group(type_name, rows))
    return groups


def _make_group(type_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_base = sum((as_decimal(a["display_value_base"]) for a in rows), Decimal("0"))
    return {
        "account_type": type_name,
        "label_fr": ACCOUNT_TYPE_LABEL_FR.get(type_name, type_name),
        "label_en": ACCOUNT_TYPE_LABEL_EN.get(type_name, type_name),
        "count": len(rows),
        "total_base": str(total_base),
        "accounts": rows,
    }


def list_currencies(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        currencies = load_currencies(conn)
    return [
        {
            "currency_id": c["currency_id"],
            "name": c["name"],
            "symbol": c["symbol"],
            "currency_type": c["currency_type"],
            "pfx": c["pfx"],
            "sfx": c["sfx"],
            "scale": c["scale"],
            "rate": str(c["rate"]),
        }
        for c in sorted(currencies.values(), key=lambda x: x["symbol"])
    ]
