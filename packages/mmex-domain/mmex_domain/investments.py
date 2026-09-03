"""STOCK_V1, STOCKHISTORY_V1, SHAREINFO_V1, ASSETS_V1, TRANSLINK_V1.

Stock market value is NUMSHARES × CURRENTPRICE. When share lots exist,
NUMSHARES / PURCHASEPRICE / VALUE / COMMISSION follow desktop
StockModel::update_data_position (average cost of remaining shares).

Asset current value matches MMEX 1.9 valueAtDate: with no translinks,
compound VALUE from STARTDATE; with translinks, each linked checking
flow (sign-flipped account flow, converted toward base) is compounded
from the transaction date. Void and deleted rows are skipped.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.balances import load_currencies
from mmex_domain.constants import NOT_SET, STATUS_VOID
from mmex_domain.money import as_decimal, to_base

LINK_STOCK = "Stock"
LINK_ASSET = "Asset"
UPD_MANUAL = 2

ASSET_TYPES = (
    "Property",
    "Automobile",
    "Household Object",
    "Art",
    "Jewellery",
    "Cash",
    "Other",
)
ASSET_STATUSES = ("Open", "Closed")
VALUE_CHANGES = ("None", "Appreciates", "Depreciates")
VALUE_MODES = ("Percentage", "Linear")

Q4 = Decimal("0.0001")
Q8 = Decimal("0.00000001")


class InvestError(ValueError):
    """Invalid investment payload or missing row."""


def _next_id(conn: Connection, table: str, column: str) -> int:
    now_based = int(time.time() * 1000) * 1000
    max_id = int(conn.execute(text(f"SELECT MAX({column}) FROM {table}")).scalar() or 0)
    return max(now_based, max_id + 1)


def _q(value: object, quant: Decimal = Q4) -> Decimal:
    return as_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def _s(value: object, quant: Decimal = Q4) -> str:
    q = _q(value, quant)
    if q == 0:
        return "0"
    return format(q, "f")


def _iso_date(value: object, *, required: bool = True) -> str:
    raw = str(value or "").strip()
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    raw = raw[:10]
    if not raw:
        if required:
            raise InvestError("date is required")
        return ""
    try:
        date.fromisoformat(raw)
    except ValueError as exc:
        raise InvestError("invalid date") from exc
    return raw


def _as_date(value: object) -> date | None:
    raw = _iso_date(value, required=False)
    if not raw:
        return None
    return date.fromisoformat(raw)


def _name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise InvestError("name is required")
    return name


def _choice(value: object, allowed: tuple[str, ...], default: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    for item in allowed:
        if item.lower() == raw.lower():
            return item
    raise InvestError(f"invalid value: {raw}")


def meta() -> dict[str, Any]:
    return {
        "asset_types": list(ASSET_TYPES),
        "asset_statuses": list(ASSET_STATUSES),
        "value_changes": list(VALUE_CHANGES),
        "value_modes": list(VALUE_MODES),
    }


def list_holding_accounts(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, CURRENCYID, STATUS
                  FROM ACCOUNTLIST_V1
                 WHERE ACCOUNTTYPE = 'Investment'
                 ORDER BY ACCOUNTNAME COLLATE NOCASE
                """
            )
        ).fetchall()
    return [
        {
            "account_id": int(r[0]),
            "name": r[1],
            "account_type": r[2],
            "currency_id": int(r[3]),
            "status": r[4],
        }
        for r in rows
    ]


def _account(conn: Connection, account_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, CURRENCYID, STATUS
              FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id
            """
        ),
        {"id": account_id},
    ).fetchone()
    if row is None:
        return None
    return {
        "account_id": int(row[0]),
        "name": row[1],
        "account_type": row[2],
        "currency_id": int(row[3]),
        "status": row[4],
    }


def _require_account(conn: Connection, account_id: int) -> dict[str, Any]:
    acct = _account(conn, account_id)
    if acct is None:
        raise InvestError("unknown account")
    return acct


# --- stocks ---


def _stock_row(conn: Connection, stock_id: int) -> Any:
    row = conn.execute(
        text(
            """
            SELECT s.STOCKID, s.HELDAT, s.PURCHASEDATE, s.STOCKNAME, s.SYMBOL,
                   s.NUMSHARES, s.PURCHASEPRICE, s.NOTES, s.CURRENTPRICE,
                   s.VALUE, s.COMMISSION, a.ACCOUNTNAME, a.CURRENCYID
              FROM STOCK_V1 s
              LEFT JOIN ACCOUNTLIST_V1 a ON a.ACCOUNTID = s.HELDAT
             WHERE s.STOCKID = :id
            """
        ),
        {"id": stock_id},
    ).fetchone()
    if row is None:
        raise InvestError("unknown stock")
    return row


def _lot_count(conn: Connection, stock_id: int) -> int:
    return int(
        conn.execute(
            text(
                """
                SELECT COUNT(*) FROM TRANSLINK_V1
                 WHERE LINKTYPE = :lt AND LINKRECORDID = :id
                """
            ),
            {"lt": LINK_STOCK, "id": stock_id},
        ).scalar()
        or 0
    )


def _serialize_stock(row: Any, *, lot_count: int = 0) -> dict[str, Any]:
    shares = as_decimal(row[5])
    purchase = as_decimal(row[6])
    current = as_decimal(row[8])
    cost = as_decimal(row[9]) if row[9] is not None else shares * purchase
    market = shares * current
    return {
        "stock_id": int(row[0]),
        "held_at": int(row[1]) if row[1] is not None else NOT_SET,
        "account_name": row[11],
        "currency_id": int(row[12]) if row[12] is not None else None,
        "purchase_date": _iso_date(row[2], required=False),
        "name": row[3],
        "symbol": row[4] or "",
        "num_shares": _s(shares, Q8),
        "purchase_price": _s(purchase),
        "notes": row[7] or "",
        "current_price": _s(current),
        "value": _s(cost),
        "commission": _s(row[10]),
        "market": _s(market),
        "gain": _s(market - cost),
        "lot_count": lot_count,
    }


def list_stocks(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT s.STOCKID, s.HELDAT, s.PURCHASEDATE, s.STOCKNAME, s.SYMBOL,
                       s.NUMSHARES, s.PURCHASEPRICE, s.NOTES, s.CURRENTPRICE,
                       s.VALUE, s.COMMISSION, a.ACCOUNTNAME, a.CURRENCYID,
                       (SELECT COUNT(*) FROM TRANSLINK_V1 t
                         WHERE t.LINKTYPE = :lt AND t.LINKRECORDID = s.STOCKID) AS LOTS
                  FROM STOCK_V1 s
                  LEFT JOIN ACCOUNTLIST_V1 a ON a.ACCOUNTID = s.HELDAT
                 ORDER BY a.ACCOUNTNAME COLLATE NOCASE, s.STOCKNAME COLLATE NOCASE
                """
            ),
            {"lt": LINK_STOCK},
        ).fetchall()
        stocks = [_serialize_stock(r, lot_count=int(r[13] or 0)) for r in rows]
        total_market = sum((as_decimal(s["market"]) for s in stocks), Decimal("0"))
        total_gain = sum((as_decimal(s["gain"]) for s in stocks), Decimal("0"))
    return {
        "stocks": stocks,
        "totals": {"market": _s(total_market), "gain": _s(total_gain)},
        "accounts": list_holding_accounts(engine),
    }


def get_stock(engine: Engine, stock_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        row = _stock_row(conn, stock_id)
        payload = _serialize_stock(row, lot_count=_lot_count(conn, stock_id))
        payload["lots"] = _list_stock_lots(conn, stock_id)
        payload["history"] = _list_history(conn, payload["symbol"])
    return payload


def create_stock(engine: Engine, data: dict[str, Any]) -> dict[str, Any]:
    name = _name(data.get("name"))
    held_at = int(data.get("held_at") or 0)
    if held_at <= 0:
        raise InvestError("held_at is required")
    shares = as_decimal(data.get("num_shares") or 0)
    purchase = as_decimal(data.get("purchase_price") or 0)
    current = as_decimal(data.get("current_price") or 0)
    if current == 0:
        current = purchase
    commission = as_decimal(data.get("commission") or 0)
    purchase_date = _iso_date(data.get("purchase_date"))
    symbol = str(data.get("symbol") or "").strip()
    notes = str(data.get("notes") or "")
    value = shares * purchase
    with engine.begin() as conn:
        _require_account(conn, held_at)
        stock_id = _next_id(conn, "STOCK_V1", "STOCKID")
        conn.execute(
            text(
                """
                INSERT INTO STOCK_V1 (
                    STOCKID, HELDAT, PURCHASEDATE, STOCKNAME, SYMBOL,
                    NUMSHARES, PURCHASEPRICE, NOTES, CURRENTPRICE, VALUE, COMMISSION
                ) VALUES (
                    :id, :held, :pdate, :name, :sym,
                    :shares, :pp, :notes, :cp, :val, :comm
                )
                """
            ),
            {
                "id": stock_id,
                "held": held_at,
                "pdate": purchase_date,
                "name": name,
                "sym": symbol,
                "shares": str(shares),
                "pp": str(purchase),
                "notes": notes,
                "cp": str(current),
                "val": str(value),
                "comm": str(commission),
            },
        )
    return get_stock(engine, stock_id)


def update_stock(engine: Engine, stock_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        row = _stock_row(conn, stock_id)
        lots = _lot_count(conn, stock_id)
        held_at = int(data.get("held_at") if data.get("held_at") is not None else row[1] or 0)
        if held_at <= 0:
            raise InvestError("held_at is required")
        _require_account(conn, held_at)
        name = _name(data.get("name") if data.get("name") is not None else row[3])
        symbol = str(data["symbol"] if "symbol" in data else (row[4] or "")).strip()
        notes = str(data["notes"] if "notes" in data else (row[7] or ""))
        current = as_decimal(data["current_price"] if "current_price" in data else row[8])
        purchase_date = _iso_date(
            data["purchase_date"] if "purchase_date" in data else row[2]
        )
        if lots:
            conn.execute(
                text(
                    """
                    UPDATE STOCK_V1 SET HELDAT=:held, STOCKNAME=:name, SYMBOL=:sym,
                           NOTES=:notes, CURRENTPRICE=:cp
                     WHERE STOCKID=:id
                    """
                ),
                {
                    "held": held_at,
                    "name": name,
                    "sym": symbol,
                    "notes": notes,
                    "cp": str(current),
                    "id": stock_id,
                },
            )
        else:
            shares = as_decimal(data["num_shares"] if "num_shares" in data else row[5])
            purchase = as_decimal(
                data["purchase_price"] if "purchase_price" in data else row[6]
            )
            commission = as_decimal(
                data["commission"] if "commission" in data else row[10]
            )
            conn.execute(
                text(
                    """
                    UPDATE STOCK_V1 SET HELDAT=:held, PURCHASEDATE=:pdate, STOCKNAME=:name,
                           SYMBOL=:sym, NUMSHARES=:shares, PURCHASEPRICE=:pp, NOTES=:notes,
                           CURRENTPRICE=:cp, VALUE=:val, COMMISSION=:comm
                     WHERE STOCKID=:id
                    """
                ),
                {
                    "held": held_at,
                    "pdate": purchase_date,
                    "name": name,
                    "sym": symbol,
                    "shares": str(shares),
                    "pp": str(purchase),
                    "notes": notes,
                    "cp": str(current),
                    "val": str(shares * purchase),
                    "comm": str(commission),
                    "id": stock_id,
                },
            )
    return get_stock(engine, stock_id)


def delete_stock(engine: Engine, stock_id: int) -> None:
    with engine.begin() as conn:
        _stock_row(conn, stock_id)
        if _lot_count(conn, stock_id):
            raise InvestError("stock still has linked transactions")
        conn.execute(text("DELETE FROM STOCK_V1 WHERE STOCKID = :id"), {"id": stock_id})


def _list_history(conn: Connection, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
    if not symbol:
        return []
    rows = conn.execute(
        text(
            """
            SELECT HISTID, SYMBOL, DATE, VALUE, UPDTYPE
              FROM STOCKHISTORY_V1
             WHERE SYMBOL = :sym
             ORDER BY DATE DESC
             LIMIT :lim
            """
        ),
        {"sym": symbol, "lim": limit},
    ).fetchall()
    return [
        {
            "hist_id": int(r[0]),
            "symbol": r[1],
            "date": _iso_date(r[2], required=False),
            "price": _s(r[3]),
            "upd_type": int(r[4] or 0),
        }
        for r in rows
    ]


def update_price(
    engine: Engine,
    *,
    symbol: str | None = None,
    stock_id: int | None = None,
    price_date: str,
    price: object,
) -> dict[str, Any]:
    px = as_decimal(price)
    if px < 0:
        raise InvestError("price must be ≥ 0")
    day = _iso_date(price_date)
    with engine.begin() as conn:
        if stock_id is not None:
            row = _stock_row(conn, stock_id)
            symbol = (row[4] or "").strip()
        symbol = (symbol or "").strip()
        if not symbol:
            raise InvestError("symbol is required")
        existing = conn.execute(
            text(
                "SELECT HISTID FROM STOCKHISTORY_V1 WHERE SYMBOL = :s AND DATE = :d"
            ),
            {"s": symbol, "d": day},
        ).fetchone()
        if existing:
            conn.execute(
                text(
                    "UPDATE STOCKHISTORY_V1 SET VALUE = :v, UPDTYPE = :u WHERE HISTID = :id"
                ),
                {"v": str(px), "u": UPD_MANUAL, "id": int(existing[0])},
            )
        else:
            hist_id = _next_id(conn, "STOCKHISTORY_V1", "HISTID")
            conn.execute(
                text(
                    """
                    INSERT INTO STOCKHISTORY_V1 (HISTID, SYMBOL, DATE, VALUE, UPDTYPE)
                    VALUES (:id, :s, :d, :v, :u)
                    """
                ),
                {"id": hist_id, "s": symbol, "d": day, "v": str(px), "u": UPD_MANUAL},
            )
        conn.execute(
            text("UPDATE STOCK_V1 SET CURRENTPRICE = :v WHERE SYMBOL = :s"),
            {"v": str(px), "s": symbol},
        )
    with engine.connect() as conn:
        history = _list_history(conn, symbol)
    return {"symbol": symbol, "date": day, "price": _s(px), "history": history}


def _checking(conn: Connection, trans_id: int) -> Any:
    row = conn.execute(
        text(
            """
            SELECT TRANSID, ACCOUNTID, TRANSCODE, TRANSAMOUNT, STATUS, TRANSDATE,
                   DELETEDTIME, TOTRANSAMOUNT
              FROM CHECKINGACCOUNT_V1 WHERE TRANSID = :id
            """
        ),
        {"id": trans_id},
    ).fetchone()
    if row is None:
        raise InvestError("unknown transaction")
    return row


def _list_stock_lots(conn: Connection, stock_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT t.TRANSLINKID, t.CHECKINGACCOUNTID, s.SHAREINFOID,
                   s.SHARENUMBER, s.SHAREPRICE, s.SHARECOMMISSION, s.SHARELOT,
                   c.TRANSDATE, c.TRANSCODE, c.TRANSAMOUNT, c.STATUS, c.NOTES
              FROM TRANSLINK_V1 t
              JOIN SHAREINFO_V1 s ON s.CHECKINGACCOUNTID = t.CHECKINGACCOUNTID
              LEFT JOIN CHECKINGACCOUNT_V1 c ON c.TRANSID = t.CHECKINGACCOUNTID
             WHERE t.LINKTYPE = :lt AND t.LINKRECORDID = :id
             ORDER BY c.TRANSDATE, t.TRANSLINKID
            """
        ),
        {"lt": LINK_STOCK, "id": stock_id},
    ).fetchall()
    return [
        {
            "translink_id": int(r[0]),
            "trans_id": int(r[1]),
            "share_info_id": int(r[2]),
            "share_number": _s(r[3], Q8),
            "share_price": _s(r[4]),
            "share_commission": _s(r[5]),
            "share_lot": r[6] or "",
            "trans_date": _iso_date(r[7], required=False),
            "trans_code": r[8] or "",
            "trans_amount": _s(r[9]) if r[9] is not None else "0",
            "status": r[10] or "",
            "notes": r[11] or "",
        }
        for r in rows
    ]


def _recompute_position(conn: Connection, stock_id: int) -> None:
    lots = _list_stock_lots(conn, stock_id)
    if not lots:
        return
    total_shares = Decimal("0")
    total_initial = Decimal("0")
    total_commission = Decimal("0")
    avg = Decimal("0")
    min_date = None
    for lot in lots:
        status = lot["status"]
        # skip void; keep deleted lots out via JOIN still showing them — filter here
        if status == STATUS_VOID:
            continue
        n = as_decimal(lot["share_number"])
        price = as_decimal(lot["share_price"])
        comm = as_decimal(lot["share_commission"])
        total_shares += n
        if total_shares < 0:
            total_shares = Decimal("0")
        if n > 0:
            total_initial += n * price + comm
        else:
            total_initial += n * avg
        if total_initial < 0:
            total_initial = Decimal("0")
        if total_shares > 0:
            avg = total_initial / total_shares
        total_commission += comm
        d = lot["trans_date"]
        if d and (min_date is None or d < min_date):
            min_date = d
    conn.execute(
        text(
            """
            UPDATE STOCK_V1 SET NUMSHARES = :n, PURCHASEPRICE = :p, VALUE = :v,
                   COMMISSION = :c, PURCHASEDATE = COALESCE(:d, PURCHASEDATE)
             WHERE STOCKID = :id
            """
        ),
        {
            "n": str(total_shares),
            "p": str(avg),
            "v": str(total_initial),
            "c": str(total_commission),
            "d": min_date,
            "id": stock_id,
        },
    )


def add_stock_lot(engine: Engine, stock_id: int, data: dict[str, Any]) -> dict[str, Any]:
    trans_id = int(data.get("trans_id") or 0)
    if trans_id <= 0:
        raise InvestError("trans_id is required")
    number = as_decimal(data.get("share_number") or 0)
    price = as_decimal(data.get("share_price") or 0)
    commission = as_decimal(data.get("share_commission") or 0)
    lot = str(data.get("share_lot") or "").strip()
    with engine.begin() as conn:
        _stock_row(conn, stock_id)
        _checking(conn, trans_id)
        exists = conn.execute(
            text("SELECT TRANSLINKID FROM TRANSLINK_V1 WHERE CHECKINGACCOUNTID = :id"),
            {"id": trans_id},
        ).fetchone()
        if exists:
            raise InvestError("transaction already linked")
        tl_id = _next_id(conn, "TRANSLINK_V1", "TRANSLINKID")
        si_id = _next_id(conn, "SHAREINFO_V1", "SHAREINFOID")
        conn.execute(
            text(
                """
                INSERT INTO TRANSLINK_V1 (TRANSLINKID, CHECKINGACCOUNTID, LINKTYPE, LINKRECORDID)
                VALUES (:id, :tid, :lt, :rid)
                """
            ),
            {"id": tl_id, "tid": trans_id, "lt": LINK_STOCK, "rid": stock_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO SHAREINFO_V1 (
                    SHAREINFOID, CHECKINGACCOUNTID, SHARENUMBER, SHAREPRICE,
                    SHARECOMMISSION, SHARELOT
                ) VALUES (:id, :tid, :n, :p, :c, :lot)
                """
            ),
            {
                "id": si_id,
                "tid": trans_id,
                "n": str(number),
                "p": str(price),
                "c": str(commission),
                "lot": lot,
            },
        )
        _recompute_position(conn, stock_id)
    return get_stock(engine, stock_id)


def delete_stock_lot(engine: Engine, stock_id: int, share_info_id: int) -> dict[str, Any]:
    with engine.begin() as conn:
        _stock_row(conn, stock_id)
        row = conn.execute(
            text(
                """
                SELECT s.SHAREINFOID, s.CHECKINGACCOUNTID, t.TRANSLINKID
                  FROM SHAREINFO_V1 s
                  JOIN TRANSLINK_V1 t ON t.CHECKINGACCOUNTID = s.CHECKINGACCOUNTID
                 WHERE s.SHAREINFOID = :sid AND t.LINKTYPE = :lt AND t.LINKRECORDID = :id
                """
            ),
            {"sid": share_info_id, "lt": LINK_STOCK, "id": stock_id},
        ).fetchone()
        if row is None:
            raise InvestError("unknown share lot")
        conn.execute(
            text("DELETE FROM SHAREINFO_V1 WHERE SHAREINFOID = :id"),
            {"id": int(row[0])},
        )
        conn.execute(
            text("DELETE FROM TRANSLINK_V1 WHERE TRANSLINKID = :id"),
            {"id": int(row[2])},
        )
        _recompute_position(conn, stock_id)
    return get_stock(engine, stock_id)


# --- assets ---


def _apply_change(
    amount: Decimal,
    *,
    change: str,
    mode: str,
    rate: Decimal,
    days: int,
) -> Decimal:
    if days <= 0 or change == "None" or rate == 0:
        return amount
    if mode == "Linear":
        years = Decimal(days) / Decimal("365")
        factor = Decimal("1") + (rate / Decimal("100")) * years
        if change == "Depreciates":
            factor = Decimal("1") - (rate / Decimal("100")) * years
        if factor < 0:
            factor = Decimal("0")
        return amount * factor
    daily = rate / Decimal("36500")
    if change == "Appreciates":
        base = Decimal("1") + daily
    else:
        base = Decimal("1") - daily
        if base < 0:
            base = Decimal("0")
    return amount * (base ** days)


def _account_flow(trans_code: str, trans_amount: Decimal) -> Decimal:
    if trans_code == "Deposit":
        return trans_amount
    if trans_code in ("Withdrawal", "Transfer"):
        return -trans_amount
    return Decimal("0")


def current_asset_value(
    conn: Connection,
    *,
    asset_id: int,
    start: date,
    stored: Decimal,
    change: str,
    mode: str,
    rate: Decimal,
    as_of: date,
) -> Decimal:
    if as_of < start:
        return Decimal("0")
    currencies = load_currencies(conn)
    info = {
        str(k): str(v)
        for k, v in conn.execute(text("SELECT INFONAME, INFOVALUE FROM INFOTABLE_V1"))
    }
    try:
        base_id = int(info.get("BASECURRENCYID") or 0)
    except ValueError:
        base_id = 0
    base = currencies.get(base_id)
    base_rate = as_decimal(base["rate"]) if base else Decimal("1")

    links = conn.execute(
        text(
            """
            SELECT t.CHECKINGACCOUNTID, c.ACCOUNTID, c.TRANSCODE, c.TRANSAMOUNT,
                   c.STATUS, c.TRANSDATE, c.DELETEDTIME, a.CURRENCYID
              FROM TRANSLINK_V1 t
              JOIN CHECKINGACCOUNT_V1 c ON c.TRANSID = t.CHECKINGACCOUNTID
              LEFT JOIN ACCOUNTLIST_V1 a ON a.ACCOUNTID = c.ACCOUNTID
             WHERE t.LINKTYPE = :lt AND t.LINKRECORDID = :id
            """
        ),
        {"lt": LINK_ASSET, "id": asset_id},
    ).fetchall()
    if not links:
        return _apply_change(
            stored, change=change, mode=mode, rate=rate, days=(as_of - start).days
        )

    total = Decimal("0")
    for link in links:
        deleted = str(link[6] or "")
        status = str(link[4] or "")
        if deleted or status == STATUS_VOID:
            continue
        txn_date = _as_date(link[5])
        if txn_date is None or txn_date > as_of:
            continue
        flow = _account_flow(str(link[2] or ""), as_decimal(link[3]))
        amount = -flow
        cid = int(link[7]) if link[7] is not None else None
        cur = currencies.get(cid) if cid is not None else None
        if cur is not None:
            amount = to_base(amount, as_decimal(cur["rate"]), base_rate)
        days = (as_of - txn_date).days
        total += _apply_change(amount, change=change, mode=mode, rate=rate, days=days)
    return total


def _asset_links(conn: Connection, asset_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT t.TRANSLINKID, t.CHECKINGACCOUNTID, c.TRANSDATE, c.TRANSCODE,
                   c.TRANSAMOUNT, c.STATUS, c.NOTES, a.ACCOUNTNAME
              FROM TRANSLINK_V1 t
              LEFT JOIN CHECKINGACCOUNT_V1 c ON c.TRANSID = t.CHECKINGACCOUNTID
              LEFT JOIN ACCOUNTLIST_V1 a ON a.ACCOUNTID = c.ACCOUNTID
             WHERE t.LINKTYPE = :lt AND t.LINKRECORDID = :id
             ORDER BY c.TRANSDATE, t.TRANSLINKID
            """
        ),
        {"lt": LINK_ASSET, "id": asset_id},
    ).fetchall()
    return [
        {
            "translink_id": int(r[0]),
            "trans_id": int(r[1]),
            "trans_date": _iso_date(r[2], required=False),
            "trans_code": r[3] or "",
            "trans_amount": _s(r[4]) if r[4] is not None else "0",
            "status": r[5] or "",
            "notes": r[6] or "",
            "account_name": r[7],
        }
        for r in rows
    ]


def _serialize_asset(
    conn: Connection, row: Any, *, as_of: date, include_links: bool = False
) -> dict[str, Any]:
    asset_id = int(row[0])
    start = _as_date(row[1]) or as_of
    stored = as_decimal(row[5])
    change = row[6] or "None"
    mode = row[4] or "Percentage"
    rate = as_decimal(row[8])
    current = current_asset_value(
        conn,
        asset_id=asset_id,
        start=start,
        stored=stored,
        change=change,
        mode=mode,
        rate=rate,
        as_of=as_of,
    )
    cid = int(row[3]) if row[3] is not None else NOT_SET
    payload = {
        "asset_id": asset_id,
        "start_date": _iso_date(row[1], required=False),
        "name": row[2],
        "status": row[7] or "Open",
        "currency_id": cid,
        "value_change_mode": mode,
        "value": _s(stored),
        "value_change": change,
        "notes": row[9] or "",
        "value_change_rate": _s(rate),
        "asset_type": row[10] or "Other",
        "current_value": _s(current),
        "link_count": int(row[11] or 0) if len(row) > 11 else 0,
    }
    if include_links:
        payload["links"] = _asset_links(conn, asset_id)
        payload["link_count"] = len(payload["links"])
    return payload


def list_assets(engine: Engine, *, as_of: date | None = None) -> dict[str, Any]:
    day = as_of or date.today()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT a.ASSETID, a.STARTDATE, a.ASSETNAME, a.CURRENCYID,
                       a.VALUECHANGEMODE, a.VALUE, a.VALUECHANGE, a.ASSETSTATUS,
                       a.VALUECHANGERATE, a.NOTES, a.ASSETTYPE,
                       (SELECT COUNT(*) FROM TRANSLINK_V1 t
                         WHERE t.LINKTYPE = :lt AND t.LINKRECORDID = a.ASSETID)
                  FROM ASSETS_V1 a
                 ORDER BY a.ASSETNAME COLLATE NOCASE
                """
            ),
            {"lt": LINK_ASSET},
        ).fetchall()
        assets = [_serialize_asset(conn, r, as_of=day) for r in rows]
        total = sum((as_decimal(a["current_value"]) for a in assets), Decimal("0"))
        open_total = sum(
            (as_decimal(a["current_value"]) for a in assets if a["status"] != "Closed"),
            Decimal("0"),
        )
    return {
        "as_of": day.isoformat(),
        "assets": assets,
        "totals": {"current": _s(total), "open": _s(open_total)},
        "meta": meta(),
    }


def get_asset(engine: Engine, asset_id: int, *, as_of: date | None = None) -> dict[str, Any]:
    day = as_of or date.today()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT ASSETID, STARTDATE, ASSETNAME, CURRENCYID, VALUECHANGEMODE,
                       VALUE, VALUECHANGE, ASSETSTATUS, VALUECHANGERATE, NOTES, ASSETTYPE
                  FROM ASSETS_V1 WHERE ASSETID = :id
                """
            ),
            {"id": asset_id},
        ).fetchone()
        if row is None:
            raise InvestError("unknown asset")
        return _serialize_asset(conn, row, as_of=day, include_links=True)


def create_asset(engine: Engine, data: dict[str, Any]) -> dict[str, Any]:
    name = _name(data.get("name"))
    start = _iso_date(data.get("start_date"))
    status = _choice(data.get("status"), ASSET_STATUSES, "Open")
    asset_type = _choice(data.get("asset_type"), ASSET_TYPES, "Other")
    change = _choice(data.get("value_change"), VALUE_CHANGES, "None")
    mode = _choice(data.get("value_change_mode"), VALUE_MODES, "Percentage")
    value = as_decimal(data.get("value") or 0)
    rate = as_decimal(data.get("value_change_rate") or 0)
    notes = str(data.get("notes") or "")
    currency_id = int(data.get("currency_id") if data.get("currency_id") not in (None, "") else NOT_SET)
    with engine.begin() as conn:
        asset_id = _next_id(conn, "ASSETS_V1", "ASSETID")
        conn.execute(
            text(
                """
                INSERT INTO ASSETS_V1 (
                    ASSETID, STARTDATE, ASSETNAME, ASSETSTATUS, CURRENCYID,
                    VALUECHANGEMODE, VALUE, VALUECHANGE, NOTES, VALUECHANGERATE, ASSETTYPE
                ) VALUES (
                    :id, :start, :name, :st, :cur, :mode, :val, :chg, :notes, :rate, :typ
                )
                """
            ),
            {
                "id": asset_id,
                "start": start,
                "name": name,
                "st": status,
                "cur": currency_id,
                "mode": mode,
                "val": str(value),
                "chg": change,
                "notes": notes,
                "rate": str(rate),
                "typ": asset_type,
            },
        )
    return get_asset(engine, asset_id)


def update_asset(engine: Engine, asset_id: int, data: dict[str, Any]) -> dict[str, Any]:
    current = get_asset(engine, asset_id)
    name = _name(data.get("name") if data.get("name") is not None else current["name"])
    start = _iso_date(data["start_date"] if "start_date" in data else current["start_date"])
    status = _choice(
        data.get("status") if "status" in data else current["status"],
        ASSET_STATUSES,
        "Open",
    )
    asset_type = _choice(
        data.get("asset_type") if "asset_type" in data else current["asset_type"],
        ASSET_TYPES,
        "Other",
    )
    change = _choice(
        data.get("value_change") if "value_change" in data else current["value_change"],
        VALUE_CHANGES,
        "None",
    )
    mode = _choice(
        data.get("value_change_mode") if "value_change_mode" in data else current["value_change_mode"],
        VALUE_MODES,
        "Percentage",
    )
    value = as_decimal(data["value"] if "value" in data else current["value"])
    rate = as_decimal(
        data["value_change_rate"] if "value_change_rate" in data else current["value_change_rate"]
    )
    notes = str(data["notes"] if "notes" in data else current["notes"])
    currency_id = int(
        data["currency_id"] if "currency_id" in data else current["currency_id"]
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE ASSETS_V1 SET STARTDATE=:start, ASSETNAME=:name, ASSETSTATUS=:st,
                       CURRENCYID=:cur, VALUECHANGEMODE=:mode, VALUE=:val,
                       VALUECHANGE=:chg, NOTES=:notes, VALUECHANGERATE=:rate,
                       ASSETTYPE=:typ
                 WHERE ASSETID=:id
                """
            ),
            {
                "start": start,
                "name": name,
                "st": status,
                "cur": currency_id,
                "mode": mode,
                "val": str(value),
                "chg": change,
                "notes": notes,
                "rate": str(rate),
                "typ": asset_type,
                "id": asset_id,
            },
        )
    return get_asset(engine, asset_id)


def delete_asset(engine: Engine, asset_id: int) -> None:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT ASSETID FROM ASSETS_V1 WHERE ASSETID = :id"),
            {"id": asset_id},
        ).fetchone()
        if row is None:
            raise InvestError("unknown asset")
        n = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM TRANSLINK_V1 WHERE LINKTYPE = :lt AND LINKRECORDID = :id"
                ),
                {"lt": LINK_ASSET, "id": asset_id},
            ).scalar()
            or 0
        )
        if n:
            raise InvestError("asset still has linked transactions")
        conn.execute(text("DELETE FROM ASSETS_V1 WHERE ASSETID = :id"), {"id": asset_id})


def add_asset_link(engine: Engine, asset_id: int, trans_id: int) -> dict[str, Any]:
    if trans_id <= 0:
        raise InvestError("trans_id is required")
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT ASSETID FROM ASSETS_V1 WHERE ASSETID = :id"),
            {"id": asset_id},
        ).fetchone()
        if exists is None:
            raise InvestError("unknown asset")
        _checking(conn, trans_id)
        linked = conn.execute(
            text("SELECT TRANSLINKID FROM TRANSLINK_V1 WHERE CHECKINGACCOUNTID = :id"),
            {"id": trans_id},
        ).fetchone()
        if linked:
            raise InvestError("transaction already linked")
        tl_id = _next_id(conn, "TRANSLINK_V1", "TRANSLINKID")
        conn.execute(
            text(
                """
                INSERT INTO TRANSLINK_V1 (TRANSLINKID, CHECKINGACCOUNTID, LINKTYPE, LINKRECORDID)
                VALUES (:id, :tid, :lt, :rid)
                """
            ),
            {"id": tl_id, "tid": trans_id, "lt": LINK_ASSET, "rid": asset_id},
        )
    return get_asset(engine, asset_id)


def delete_asset_link(engine: Engine, asset_id: int, translink_id: int) -> dict[str, Any]:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT TRANSLINKID FROM TRANSLINK_V1
                 WHERE TRANSLINKID = :id AND LINKTYPE = :lt AND LINKRECORDID = :rid
                """
            ),
            {"id": translink_id, "lt": LINK_ASSET, "rid": asset_id},
        ).fetchone()
        if row is None:
            raise InvestError("unknown link")
        conn.execute(
            text("DELETE FROM TRANSLINK_V1 WHERE TRANSLINKID = :id"),
            {"id": translink_id},
        )
    return get_asset(engine, asset_id)
