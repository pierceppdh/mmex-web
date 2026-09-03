"""INFOTABLE_V1 ledger options and CURRENCYHISTORY_V1 rates.

Rates are “1 unit of this currency in base units” (desktop BASECONVRATE).
When USECURRENCYHISTORY is TRUE, balances use the latest history row.
Posting a rate updates BASECONVRATE and upserts UNIQUE(CURRENCYID, CURRDATE).
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.kv import save_web_prefs, web_prefs
from mmex_domain.money import as_decimal

UPD_MANUAL = 2
DATE_FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "YYYY/MM/DD": "%Y/%m/%d",
    "DD.MM.YYYY": "%d.%m.%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
}
FORMAT_BY_WX = {v: k for k, v in DATE_FORMATS.items()}

EDITABLE = (
    "USERNAME",
    "DATEFORMAT",
    "DELIMITER",
    "USECURRENCYHISTORY",
    "FINANCIAL_YEAR_START_DAY",
    "FINANCIAL_YEAR_START_MONTH",
    "STOCKURL",
    "CATEG_DELIMITER",
    "SHARE_PRECISION",
)


class SettingsError(ValueError):
    """Invalid settings or rate payload."""


def _next_id(conn: Connection, table: str, column: str) -> int:
    now_based = int(time.time() * 1000) * 1000
    max_id = int(conn.execute(text(f"SELECT MAX({column}) FROM {table}")).scalar() or 0)
    return max(now_based, max_id + 1)


def _info_map(conn: Connection) -> dict[str, str]:
    rows = conn.execute(text("SELECT INFONAME, INFOVALUE FROM INFOTABLE_V1"))
    return {str(k): str(v) for k, v in rows}


def _set_info(conn: Connection, name: str, value: str) -> None:
    existing = conn.execute(
        text("SELECT INFOID FROM INFOTABLE_V1 WHERE INFONAME = :n"),
        {"n": name},
    ).fetchone()
    if existing:
        conn.execute(
            text("UPDATE INFOTABLE_V1 SET INFOVALUE = :v WHERE INFONAME = :n"),
            {"v": value, "n": name},
        )
        return
    iid = _next_id(conn, "INFOTABLE_V1", "INFOID")
    conn.execute(
        text("INSERT INTO INFOTABLE_V1 (INFOID, INFONAME, INFOVALUE) VALUES (:id, :n, :v)"),
        {"id": iid, "n": name, "v": value},
    )


def _bool_str(value: object, default: bool = False) -> str:
    if value is None or value == "":
        return "TRUE" if default else "FALSE"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    raw = str(value).strip().upper()
    if raw in ("1", "TRUE", "YES", "Y", "ON"):
        return "TRUE"
    if raw in ("0", "FALSE", "NO", "N", "OFF"):
        return "FALSE"
    raise SettingsError(f"invalid boolean for {value!r}")


def _iso_date(value: object) -> str:
    raw = str(value or "").strip()
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    raw = raw[:10]
    try:
        date.fromisoformat(raw)
    except ValueError as exc:
        raise SettingsError("invalid date") from exc
    return raw


def meta() -> dict[str, Any]:
    return {
        "date_formats": [{"id": k, "wx": v} for k, v in DATE_FORMATS.items()],
        "delimiters": [",", ";", "\\t", "|"],
    }


def get_settings(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        info = _info_map(conn)
        try:
            base_id = int(info.get("BASECURRENCYID") or 0)
        except ValueError:
            base_id = 0
        base = conn.execute(
            text(
                "SELECT CURRENCYID, CURRENCYNAME, CURRENCY_SYMBOL FROM CURRENCYFORMATS_V1 "
                "WHERE CURRENCYID = :id"
            ),
            {"id": base_id},
        ).fetchone()
        currencies = conn.execute(
            text(
                """
                SELECT c.CURRENCYID, c.CURRENCYNAME, c.CURRENCY_SYMBOL, c.BASECONVRATE,
                       (SELECT COUNT(*) FROM ACCOUNTLIST_V1 a WHERE a.CURRENCYID = c.CURRENCYID) AS USED,
                       (SELECT COUNT(*) FROM CURRENCYHISTORY_V1 h WHERE h.CURRENCYID = c.CURRENCYID) AS HIST
                  FROM CURRENCYFORMATS_V1 c
                 ORDER BY c.CURRENCY_SYMBOL
                """
            )
        ).fetchall()
    wx = info.get("DATEFORMAT") or "%Y-%m-%d"
    return {
        "username": info.get("USERNAME") or "",
        "date_format": FORMAT_BY_WX.get(wx, "YYYY-MM-DD"),
        "date_format_wx": wx,
        "delimiter": info.get("DELIMITER") or ",",
        "use_currency_history": info.get("USECURRENCYHISTORY", "FALSE").upper() == "TRUE",
        "financial_year_start_day": int(info.get("FINANCIAL_YEAR_START_DAY") or 1),
        "financial_year_start_month": int(info.get("FINANCIAL_YEAR_START_MONTH") or 1),
        "stock_url": info.get("STOCKURL") or "",
        "categ_delimiter": info.get("CATEG_DELIMITER") or ":",
        "share_precision": int(info.get("SHARE_PRECISION") or 4),
        "base_currency_id": base_id,
        "base_currency_name": (base[1] if base else info.get("BASECURRENCYNAME") or ""),
        "base_currency_symbol": (base[2] if base else ""),
        "currencies": [
            {
                "currency_id": int(r[0]),
                "name": r[1],
                "symbol": r[2],
                "rate": str(as_decimal(r[3])),
                "used_count": int(r[4] or 0),
                "history_count": int(r[5] or 0),
                "is_base": int(r[0]) == base_id,
            }
            for r in currencies
        ],
        "meta": meta(),
        **web_prefs(engine),
    }


def update_settings(engine: Engine, data: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        if "username" in data:
            _set_info(conn, "USERNAME", str(data.get("username") or ""))
        if "date_format" in data:
            key = str(data.get("date_format") or "YYYY-MM-DD")
            if key not in DATE_FORMATS:
                raise SettingsError("invalid date format")
            _set_info(conn, "DATEFORMAT", DATE_FORMATS[key])
        if "delimiter" in data:
            delim = str(data.get("delimiter") or ",")
            if delim in ("\\t", "tab", "TAB"):
                delim = "\t"
            if len(delim) != 1:
                raise SettingsError("delimiter must be one character")
            _set_info(conn, "DELIMITER", delim)
        if "use_currency_history" in data:
            _set_info(conn, "USECURRENCYHISTORY", _bool_str(data.get("use_currency_history")))
        if "financial_year_start_day" in data:
            day = int(data.get("financial_year_start_day") or 1)
            if day < 1 or day > 31:
                raise SettingsError("financial year day must be 1–31")
            _set_info(conn, "FINANCIAL_YEAR_START_DAY", str(day))
        if "financial_year_start_month" in data:
            month = int(data.get("financial_year_start_month") or 1)
            if month < 1 or month > 12:
                raise SettingsError("financial year month must be 1–12")
            _set_info(conn, "FINANCIAL_YEAR_START_MONTH", str(month))
        if "stock_url" in data:
            url = str(data.get("stock_url") or "").strip()
            if url and not (url.startswith("http://") or url.startswith("https://")):
                raise SettingsError("stock_url must be http(s)")
            _set_info(conn, "STOCKURL", url)
        if "categ_delimiter" in data:
            cd = str(data.get("categ_delimiter") or ":")[:8]
            if not cd:
                raise SettingsError("categ_delimiter is required")
            _set_info(conn, "CATEG_DELIMITER", cd)
        if "share_precision" in data:
            prec = int(data.get("share_precision") or 4)
            if prec < 0 or prec > 10:
                raise SettingsError("share precision must be 0–10")
            _set_info(conn, "SHARE_PRECISION", str(prec))
    prefs = {
        k: data[k]
        for k in ("theme", "show_closed_accounts", "default_account_id")
        if k in data
    }
    if prefs:
        try:
            save_web_prefs(engine, prefs)
        except ValueError as exc:
            raise SettingsError(str(exc)) from exc
    return get_settings(engine)


def set_base_currency(engine: Engine, currency_id: int) -> dict[str, Any]:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT CURRENCYID, CURRENCYNAME FROM CURRENCYFORMATS_V1 WHERE CURRENCYID = :id"
            ),
            {"id": currency_id},
        ).fetchone()
        if row is None:
            raise SettingsError("unknown currency")
        _set_info(conn, "BASECURRENCYID", str(int(row[0])))
        _set_info(conn, "BASECURRENCYNAME", str(row[1]))
        conn.execute(
            text("UPDATE CURRENCYFORMATS_V1 SET BASECONVRATE = 1 WHERE CURRENCYID = :id"),
            {"id": currency_id},
        )
    return get_settings(engine)


def list_rate_history(engine: Engine, currency_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        cur = conn.execute(
            text(
                "SELECT CURRENCYID, CURRENCYNAME, CURRENCY_SYMBOL, BASECONVRATE "
                "FROM CURRENCYFORMATS_V1 WHERE CURRENCYID = :id"
            ),
            {"id": currency_id},
        ).fetchone()
        if cur is None:
            raise SettingsError("unknown currency")
        rows = conn.execute(
            text(
                """
                SELECT CURRHISTID, CURRDATE, CURRVALUE, CURRUPDTYPE
                  FROM CURRENCYHISTORY_V1
                 WHERE CURRENCYID = :id
                 ORDER BY CURRDATE DESC
                """
            ),
            {"id": currency_id},
        ).fetchall()
    return {
        "currency_id": int(cur[0]),
        "name": cur[1],
        "symbol": cur[2],
        "rate": str(as_decimal(cur[3])),
        "history": [
            {
                "hist_id": int(r[0]),
                "date": str(r[1])[:10],
                "rate": str(as_decimal(r[2])),
                "upd_type": int(r[3] or 0),
            }
            for r in rows
        ],
    }


def upsert_rate(
    engine: Engine,
    currency_id: int,
    *,
    rate: object,
    rate_date: str,
    update_current: bool = True,
) -> dict[str, Any]:
    try:
        value = as_decimal(rate)
    except (InvalidOperation, ValueError) as exc:
        raise SettingsError("invalid rate") from exc
    if value <= 0:
        raise SettingsError("rate must be > 0")
    day = _iso_date(rate_date)
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT CURRENCYID FROM CURRENCYFORMATS_V1 WHERE CURRENCYID = :id"),
            {"id": currency_id},
        ).fetchone()
        if exists is None:
            raise SettingsError("unknown currency")
        row = conn.execute(
            text(
                "SELECT CURRHISTID FROM CURRENCYHISTORY_V1 "
                "WHERE CURRENCYID = :c AND CURRDATE = :d"
            ),
            {"c": currency_id, "d": day},
        ).fetchone()
        if row:
            conn.execute(
                text(
                    "UPDATE CURRENCYHISTORY_V1 SET CURRVALUE = :v, CURRUPDTYPE = :u "
                    "WHERE CURRHISTID = :id"
                ),
                {"v": str(value), "u": UPD_MANUAL, "id": int(row[0])},
            )
        else:
            hid = _next_id(conn, "CURRENCYHISTORY_V1", "CURRHISTID")
            conn.execute(
                text(
                    """
                    INSERT INTO CURRENCYHISTORY_V1 (
                        CURRHISTID, CURRENCYID, CURRDATE, CURRVALUE, CURRUPDTYPE
                    ) VALUES (:id, :c, :d, :v, :u)
                    """
                ),
                {
                    "id": hid,
                    "c": currency_id,
                    "d": day,
                    "v": str(value),
                    "u": UPD_MANUAL,
                },
            )
        if update_current:
            latest = conn.execute(
                text("SELECT MAX(CURRDATE) FROM CURRENCYHISTORY_V1 WHERE CURRENCYID = :c"),
                {"c": currency_id},
            ).scalar()
            if latest is None or str(latest)[:10] <= day:
                conn.execute(
                    text(
                        "UPDATE CURRENCYFORMATS_V1 SET BASECONVRATE = :v WHERE CURRENCYID = :id"
                    ),
                    {"v": str(value), "id": currency_id},
                )
    return list_rate_history(engine, currency_id)


def delete_rate(engine: Engine, currency_id: int, hist_id: int) -> dict[str, Any]:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT CURRHISTID, CURRDATE FROM CURRENCYHISTORY_V1 "
                "WHERE CURRHISTID = :h AND CURRENCYID = :c"
            ),
            {"h": hist_id, "c": currency_id},
        ).fetchone()
        if row is None:
            raise SettingsError("unknown rate")
        deleted_day = str(row[1])[:10]
        conn.execute(
            text("DELETE FROM CURRENCYHISTORY_V1 WHERE CURRHISTID = :id"),
            {"id": hist_id},
        )
        remaining = conn.execute(
            text(
                "SELECT CURRDATE, CURRVALUE FROM CURRENCYHISTORY_V1 "
                "WHERE CURRENCYID = :c ORDER BY CURRDATE DESC LIMIT 1"
            ),
            {"c": currency_id},
        ).fetchone()
        if remaining is not None and deleted_day >= str(remaining[0])[:10]:
            conn.execute(
                text(
                    "UPDATE CURRENCYFORMATS_V1 SET BASECONVRATE = :v WHERE CURRENCYID = :id"
                ),
                {"v": str(as_decimal(remaining[1])), "id": currency_id},
            )
    return list_rate_history(engine, currency_id)
