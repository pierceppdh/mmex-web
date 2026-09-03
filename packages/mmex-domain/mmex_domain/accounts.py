"""Account statement lock and related ACCOUNTLIST_V1 fields."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.balances import ACCOUNT_TYPE_ORDER
from mmex_domain.money import as_decimal

ACCOUNT_STATUSES = ("Open", "Closed")

LOCKED_MSG = "statement locked"


class AccountError(ValueError):
    """Invalid account payload or missing account."""


def _day(value: str | None) -> str:
    raw = (value or "").strip()
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    return raw[:10]


def is_locked(locked_flag: Any, statement_date: str | None, trans_date: str | None) -> bool:
    flag = locked_flag
    if flag is None or flag == "":
        return False
    if isinstance(flag, str) and flag.upper() in ("FALSE", "N", "NO", "0"):
        return False
    try:
        if int(flag) == 0:
            return False
    except (TypeError, ValueError):
        if not flag:
            return False
    stmt = _day(statement_date)
    day = _day(trans_date)
    if not stmt or not day:
        return False
    return day <= stmt


def load_statement(conn: Connection, account_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT ACCOUNTID, ACCOUNTNAME, STATEMENTLOCKED, STATEMENTDATE,
                   CREDITLIMIT, MINIMUMBALANCE, INTERESTRATE, PAYMENTDUEDATE,
                   MINIMUMPAYMENT
              FROM ACCOUNTLIST_V1
             WHERE ACCOUNTID = :id
            """
        ),
        {"id": account_id},
    ).fetchone()
    if row is None:
        return None
    return {
        "account_id": int(row[0]),
        "name": row[1],
        "statement_locked": int(row[2] or 0),
        "statement_date": _day(row[3]) or None,
        "credit_limit": str(as_decimal(row[4])),
        "minimum_balance": str(as_decimal(row[5])),
        "interest_rate": str(as_decimal(row[6])),
        "payment_due_date": _day(row[7]) or None,
        "minimum_payment": str(as_decimal(row[8])),
    }


def statement_blocks(conn: Connection, account_id: int, trans_date: str | None) -> bool:
    if account_id is None or int(account_id) <= 0:
        return False
    row = conn.execute(
        text(
            "SELECT STATEMENTLOCKED, STATEMENTDATE FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id"
        ),
        {"id": int(account_id)},
    ).fetchone()
    if row is None:
        return False
    return is_locked(row[0], row[1], trans_date)


def assert_writable(
    conn: Connection,
    account_id: int,
    trans_date: str | None,
    *,
    to_account_id: int | None = None,
) -> None:
    if statement_blocks(conn, account_id, trans_date):
        raise AccountError(LOCKED_MSG)
    if to_account_id and int(to_account_id) > 0:
        if statement_blocks(conn, int(to_account_id), trans_date):
            raise AccountError(LOCKED_MSG)


def update_statement(engine: Engine, account_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    locked = 1 if payload.get("statement_locked") else 0
    stmt_date = _day(str(payload.get("statement_date") or "")) or None
    if locked and not stmt_date:
        raise AccountError("statement_date is required when locked")
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT ACCOUNTID FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id"),
            {"id": account_id},
        ).fetchone()
        if exists is None:
            raise AccountError(f"unknown account {account_id}")
        conn.execute(
            text(
                """
                UPDATE ACCOUNTLIST_V1 SET
                    STATEMENTLOCKED = :lock,
                    STATEMENTDATE = :sdate,
                    CREDITLIMIT = :clim,
                    MINIMUMBALANCE = :minbal,
                    INTERESTRATE = :rate,
                    PAYMENTDUEDATE = :pdue,
                    MINIMUMPAYMENT = :mpay
                 WHERE ACCOUNTID = :id
                """
            ),
            {
                "lock": locked,
                "sdate": stmt_date or "",
                "clim": str(as_decimal(payload.get("credit_limit"))),
                "minbal": str(as_decimal(payload.get("minimum_balance"))),
                "rate": str(as_decimal(payload.get("interest_rate"))),
                "pdue": _day(str(payload.get("payment_due_date") or "")) or "",
                "mpay": str(as_decimal(payload.get("minimum_payment"))),
                "id": account_id,
            },
        )
    with engine.connect() as conn:
        item = load_statement(conn, account_id)
    assert item is not None
    return item


def load_account(engine: Engine, account_id: int) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, ACCOUNTNUM, STATUS, NOTES,
                       HELDAT, WEBSITE, CONTACTINFO, ACCESSINFO, INITIALBAL, INITIALDATE,
                       FAVORITEACCT, CURRENCYID, STATEMENTLOCKED, STATEMENTDATE,
                       MINIMUMBALANCE, CREDITLIMIT, INTERESTRATE, PAYMENTDUEDATE,
                       MINIMUMPAYMENT
                  FROM ACCOUNTLIST_V1
                 WHERE ACCOUNTID = :id
                """
            ),
            {"id": account_id},
        ).fetchone()
    if row is None:
        return None
    fav = str(row[12] or "").upper() in ("TRUE", "1", "YES")
    return {
        "account_id": int(row[0]),
        "name": row[1] or "",
        "account_type": row[2] or "Checking",
        "account_num": row[3] or "",
        "status": row[4] or "Open",
        "notes": row[5] or "",
        "held_at": row[6] or "",
        "website": row[7] or "",
        "contact_info": row[8] or "",
        "access_info": row[9] or "",
        "initial_bal": str(as_decimal(row[10])),
        "initial_date": _day(row[11]) or "",
        "favorite": fav,
        "currency_id": int(row[13] or 0),
        "statement_locked": int(row[14] or 0),
        "statement_date": _day(row[15]) or "",
        "minimum_balance": str(as_decimal(row[16])),
        "credit_limit": str(as_decimal(row[17])),
        "interest_rate": str(as_decimal(row[18])),
        "payment_due_date": _day(row[19]) or "",
        "minimum_payment": str(as_decimal(row[20])),
        "account_types": list(ACCOUNT_TYPE_ORDER),
        "account_statuses": list(ACCOUNT_STATUSES),
    }


def update_account(engine: Engine, account_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise AccountError("name is required")
    acct_type = str(payload.get("account_type") or "Checking")
    current = load_account(engine, account_id)
    if current is None:
        raise AccountError(f"unknown account {account_id}")
    allowed_types = set(ACCOUNT_TYPE_ORDER) | {current["account_type"]}
    if acct_type not in allowed_types:
        raise AccountError("invalid account type")
    status = str(payload.get("status") or "Open")
    if status not in ACCOUNT_STATUSES:
        raise AccountError("invalid status")
    locked = 1 if payload.get("statement_locked") else 0
    stmt_date = _day(str(payload.get("statement_date") or "")) or None
    if locked and not stmt_date:
        raise AccountError("statement_date is required when locked")
    with engine.begin() as conn:
        _assert_unique_name(conn, name, exclude=account_id)
        cur_id = int(payload.get("currency_id") or current["currency_id"] or 0)
        if cur_id > 0:
            exists = conn.execute(
                text("SELECT CURRENCYID FROM CURRENCYFORMATS_V1 WHERE CURRENCYID = :id"),
                {"id": cur_id},
            ).fetchone()
            if exists is None:
                raise AccountError(f"unknown currency {cur_id}")
        conn.execute(
            text(
                """
                UPDATE ACCOUNTLIST_V1 SET
                    ACCOUNTNAME = :name,
                    ACCOUNTTYPE = :atype,
                    ACCOUNTNUM = :anum,
                    STATUS = :status,
                    NOTES = :notes,
                    HELDAT = :held,
                    WEBSITE = :web,
                    CONTACTINFO = :contact,
                    ACCESSINFO = :access,
                    INITIALBAL = :ibal,
                    INITIALDATE = :idate,
                    FAVORITEACCT = :fav,
                    CURRENCYID = :cur,
                    STATEMENTLOCKED = :lock,
                    STATEMENTDATE = :sdate,
                    CREDITLIMIT = :clim,
                    MINIMUMBALANCE = :minbal,
                    INTERESTRATE = :rate,
                    PAYMENTDUEDATE = :pdue,
                    MINIMUMPAYMENT = :mpay
                 WHERE ACCOUNTID = :id
                """
            ),
            {
                "name": name,
                "atype": acct_type,
                "anum": str(payload.get("account_num") or ""),
                "status": status,
                "notes": str(payload.get("notes") or ""),
                "held": str(payload.get("held_at") or ""),
                "web": str(payload.get("website") or ""),
                "contact": str(payload.get("contact_info") or ""),
                "access": str(payload.get("access_info") or ""),
                "ibal": str(as_decimal(payload.get("initial_bal"))),
                "idate": _day(str(payload.get("initial_date") or "")) or "",
                "fav": "TRUE" if payload.get("favorite") else "FALSE",
                "cur": cur_id if cur_id > 0 else current["currency_id"],
                "lock": locked,
                "sdate": stmt_date or "",
                "clim": str(as_decimal(payload.get("credit_limit"))),
                "minbal": str(as_decimal(payload.get("minimum_balance"))),
                "rate": str(as_decimal(payload.get("interest_rate"))),
                "pdue": _day(str(payload.get("payment_due_date") or "")) or "",
                "mpay": str(as_decimal(payload.get("minimum_payment"))),
                "id": account_id,
            },
        )
    item = load_account(engine, account_id)
    assert item is not None
    return item


def _next_id(conn: Connection, table: str, column: str) -> int:
    now_based = int(time.time() * 1000) * 1000
    max_id = int(conn.execute(text(f"SELECT MAX({column}) FROM {table}")).scalar() or 0)
    return max(now_based, max_id + 1)


def _assert_unique_name(conn: Connection, name: str, exclude: int | None = None) -> None:
    sql = "SELECT ACCOUNTID FROM ACCOUNTLIST_V1 WHERE ACCOUNTNAME = :n COLLATE NOCASE"
    params: dict[str, Any] = {"n": name}
    if exclude is not None:
        sql += " AND ACCOUNTID != :id"
        params["id"] = exclude
    if conn.execute(text(sql), params).fetchone():
        raise AccountError("account name already exists")


def create_account(engine: Engine, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise AccountError("name is required")
    acct_type = str(payload.get("account_type") or "Checking")
    if acct_type not in ACCOUNT_TYPE_ORDER:
        raise AccountError("invalid account type")
    status = str(payload.get("status") or "Open")
    if status not in ACCOUNT_STATUSES:
        raise AccountError("invalid status")
    with engine.begin() as conn:
        _assert_unique_name(conn, name)
        cur_id = int(payload.get("currency_id") or 0)
        if cur_id <= 0:
            cur_id = int(
                conn.execute(text("SELECT CURRENCYID FROM CURRENCYFORMATS_V1 ORDER BY CURRENCYID LIMIT 1")).scalar()
                or 0
            )
        if cur_id <= 0:
            raise AccountError("currency_id is required")
        exists = conn.execute(
            text("SELECT CURRENCYID FROM CURRENCYFORMATS_V1 WHERE CURRENCYID = :id"),
            {"id": cur_id},
        ).fetchone()
        if exists is None:
            raise AccountError(f"unknown currency {cur_id}")
        aid = _next_id(conn, "ACCOUNTLIST_V1", "ACCOUNTID")
        conn.execute(
            text(
                """
                INSERT INTO ACCOUNTLIST_V1 (
                    ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, ACCOUNTNUM, STATUS, NOTES,
                    HELDAT, WEBSITE, CONTACTINFO, ACCESSINFO, INITIALBAL, INITIALDATE,
                    FAVORITEACCT, CURRENCYID, STATEMENTLOCKED, STATEMENTDATE,
                    MINIMUMBALANCE, CREDITLIMIT, INTERESTRATE, PAYMENTDUEDATE, MINIMUMPAYMENT
                ) VALUES (
                    :id, :name, :atype, :anum, :status, :notes, :held, :web, :contact,
                    :access, :ibal, :idate, :fav, :cur, :lock, :sdate, :minbal, :clim,
                    :rate, :pdue, :mpay
                )
                """
            ),
            {
                "id": aid,
                "name": name,
                "atype": acct_type,
                "anum": str(payload.get("account_num") or ""),
                "status": status,
                "notes": str(payload.get("notes") or ""),
                "held": str(payload.get("held_at") or ""),
                "web": str(payload.get("website") or ""),
                "contact": str(payload.get("contact_info") or ""),
                "access": str(payload.get("access_info") or ""),
                "ibal": str(as_decimal(payload.get("initial_bal"))),
                "idate": _day(str(payload.get("initial_date") or "")) or "",
                "fav": "TRUE" if payload.get("favorite") else "FALSE",
                "cur": cur_id,
                "lock": 1 if payload.get("statement_locked") else 0,
                "sdate": _day(str(payload.get("statement_date") or "")) or "",
                "clim": str(as_decimal(payload.get("credit_limit"))),
                "minbal": str(as_decimal(payload.get("minimum_balance"))),
                "rate": str(as_decimal(payload.get("interest_rate"))),
                "pdue": _day(str(payload.get("payment_due_date") or "")) or "",
                "mpay": str(as_decimal(payload.get("minimum_payment"))),
            },
        )
    item = load_account(engine, aid)
    assert item is not None
    return item


def delete_account(engine: Engine, account_id: int) -> None:
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT ACCOUNTID FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id"),
            {"id": account_id},
        ).fetchone()
        if exists is None:
            raise AccountError(f"unknown account {account_id}")
        used = conn.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM CHECKINGACCOUNT_V1
                    WHERE ACCOUNTID = :id OR TOACCOUNTID = :id)
                + (SELECT COUNT(*) FROM BILLSDEPOSITS_V1
                    WHERE ACCOUNTID = :id OR TOACCOUNTID = :id)
                + (SELECT COUNT(*) FROM STOCK_V1 WHERE HELDAT = :id)
                """
            ),
            {"id": account_id},
        ).scalar()
        if int(used or 0):
            raise AccountError("account is in use")
        conn.execute(text("DELETE FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id"), {"id": account_id})
