"""Checking-account transactions: list, CRUD, splits, tags."""

from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.accounts import AccountError, assert_writable
from mmex_domain.constants import (
    COLOR_IDS,
    NOT_SET,
    REF_TRANSACTION,
    REF_TRANSACTION_SPLIT,
    STATUS_CYCLE,
    STATUS_NONE,
    STATUS_VOID,
    TRANS_CODES,
    TRANS_DEPOSIT,
    TRANS_TRANSFER,
    TRANS_WITHDRAWAL,
)
from mmex_domain.filters import apply_filter, parse_filter
from mmex_domain.lookups import _category_path
from mmex_domain.money import as_decimal

class TransactionError(ValueError):
    """Invalid transaction payload or missing row."""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _next_id(conn: Connection, table: str, column: str) -> int:
    now_based = int(time.time() * 1000) * 1000
    max_id = int(conn.execute(text(f"SELECT MAX({column}) FROM {table}")).scalar() or 0)
    return max(now_based, max_id + 1)


def _normalize_date(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise TransactionError("trans_date is required")
    if "T" in raw:
        date_part, time_part = raw.split("T", 1)
        time_part = time_part[:8] if time_part else "00:00:00"
        if len(time_part) == 5:
            time_part = time_part + ":00"
        return f"{date_part}T{time_part}"
    return f"{raw}T00:00:00"


def _status(value: str | None) -> str:
    status = "" if value is None else str(value)
    if status not in STATUS_CYCLE:
        raise TransactionError(f"invalid status {status!r}")
    return status


def account_flow(row: dict[str, Any], account_id: int) -> Decimal:
    if row.get("status") == STATUS_VOID:
        return Decimal("0")
    if row.get("deleted_time"):
        return Decimal("0")
    code = row["trans_code"]
    amount = as_decimal(row["trans_amount"])
    to_amount = as_decimal(row.get("to_trans_amount") or row["trans_amount"])
    if int(row["account_id"]) == account_id:
        if code == TRANS_DEPOSIT:
            return amount
        return -amount
    if int(row.get("to_account_id") or 0) == account_id and code == TRANS_TRANSFER:
        return to_amount if to_amount != 0 else amount
    return Decimal("0")


def _load_category_map(conn: Connection) -> dict[int, dict[str, Any]]:
    rows = conn.execute(
        text("SELECT CATEGID, CATEGNAME, PARENTID FROM CATEGORY_V1")
    ).fetchall()
    return {
        int(r[0]): {
            "categ_id": int(r[0]),
            "name": r[1],
            "parent_id": int(r[2]) if r[2] is not None and int(r[2]) > 0 else None,
        }
        for r in rows
    }


def _tags_for(conn: Connection, ref_type: str, ref_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not ref_ids:
        return {}
    from sqlalchemy import bindparam

    result: dict[int, list[dict[str, Any]]] = {i: [] for i in ref_ids}
    stmt = text(
        """
        SELECT l.REFID, t.TAGID, t.TAGNAME
          FROM TAGLINK_V1 l
          JOIN TAG_V1 t ON t.TAGID = l.TAGID
         WHERE l.REFTYPE = :ref_type
           AND l.REFID IN :ids
         ORDER BY t.TAGNAME
        """
    ).bindparams(bindparam("ids", expanding=True))
    rows = conn.execute(stmt, {"ref_type": ref_type, "ids": list(ref_ids)})
    for ref_id, tag_id, name in rows:
        result.setdefault(int(ref_id), []).append({"tag_id": int(tag_id), "name": name})
    return result


def _guard_statement(
    conn: Connection,
    account_id: int,
    trans_date: str | None,
    to_account_id: int | None = None,
) -> None:
    try:
        assert_writable(conn, account_id, trans_date, to_account_id=to_account_id)
    except AccountError as exc:
        raise TransactionError(str(exc)) from exc


def list_transactions(
    engine: Engine,
    account_id: int,
    *,
    limit: int = 100,
    offset: int = 0,
    include_deleted: bool = False,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with engine.connect() as conn:
        initial = as_decimal(
            conn.execute(
                text("SELECT INITIALBAL FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id"),
                {"id": account_id},
            ).scalar()
        )
        name = conn.execute(
            text("SELECT ACCOUNTNAME FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id"),
            {"id": account_id},
        ).scalar()
        if name is None:
            raise TransactionError(f"unknown account {account_id}")
        deleted_sql = "" if include_deleted else "AND (c.DELETEDTIME IS NULL OR c.DELETEDTIME = '')"
        rows = conn.execute(
            text(
                f"""
                SELECT c.TRANSID, c.ACCOUNTID, c.TOACCOUNTID, c.PAYEEID, p.PAYEENAME,
                       c.TRANSCODE, c.TRANSAMOUNT, c.STATUS, c.TRANSACTIONNUMBER,
                       c.NOTES, c.CATEGID, c.TRANSDATE, c.LASTUPDATEDTIME,
                       c.DELETEDTIME, c.TOTRANSAMOUNT, c.COLOR, c.FOLLOWUPID,
                       fa.ACCOUNTNAME, ta.ACCOUNTNAME
                  FROM CHECKINGACCOUNT_V1 c
                  LEFT JOIN PAYEE_V1 p ON p.PAYEEID = c.PAYEEID
                  LEFT JOIN ACCOUNTLIST_V1 fa ON fa.ACCOUNTID = c.ACCOUNTID
                  LEFT JOIN ACCOUNTLIST_V1 ta ON ta.ACCOUNTID = c.TOACCOUNTID
                 WHERE (c.ACCOUNTID = :aid OR (c.TRANSCODE = 'Transfer' AND c.TOACCOUNTID = :aid))
                   {deleted_sql}
                 ORDER BY c.TRANSDATE ASC, c.TRANSID ASC
                """
            ),
            {"aid": account_id},
        ).fetchall()

        parsed: list[dict[str, Any]] = []
        running = initial
        for r in rows:
            item = {
                "trans_id": int(r[0]),
                "account_id": int(r[1]),
                "to_account_id": int(r[2] or NOT_SET),
                "payee_id": int(r[3] or NOT_SET),
                "payee_name": r[4] if r[3] not in (None, NOT_SET) else None,
                "trans_code": r[5],
                "trans_amount": str(as_decimal(r[6])),
                "status": r[7] or "",
                "transaction_number": r[8] or "",
                "notes": r[9] or "",
                "categ_id": int(r[10]) if r[10] is not None else NOT_SET,
                "trans_date": r[11],
                "last_updated_time": r[12],
                "deleted_time": r[13] or "",
                "to_trans_amount": str(as_decimal(r[14] if r[14] is not None else r[6])),
                "color": int(r[15] if r[15] is not None else NOT_SET),
                "followup_id": int(r[16] if r[16] is not None else NOT_SET),
                "from_account_name": r[17],
                "to_account_name": r[18],
            }
            flow = account_flow(item, account_id)
            running += flow
            item["flow"] = str(flow)
            item["running_balance"] = str(running)
            parsed.append(item)

        account_total = len(parsed)
        cats = _load_category_map(conn)
        filt = parse_filter(filters)
        if filt:
            parsed = apply_filter(conn, parsed, filt, cats)
        total = len(parsed)
        window = list(reversed(parsed))[offset : offset + limit]
        trans_ids = [t["trans_id"] for t in window]
        split_counts: dict[int, int] = {}
        if trans_ids:
            from sqlalchemy import bindparam

            stmt = text(
                """
                SELECT TRANSID, COUNT(*)
                  FROM SPLITTRANSACTIONS_V1
                 WHERE TRANSID IN :ids
                 GROUP BY TRANSID
                """
            ).bindparams(bindparam("ids", expanding=True))
            for tid, cnt in conn.execute(stmt, {"ids": trans_ids}):
                split_counts[int(tid)] = int(cnt)
        txn_tags = _tags_for(conn, REF_TRANSACTION, trans_ids) if trans_ids else {}
        from mmex_domain.attachments import counts_for

        att_counts = counts_for(engine, REF_TRANSACTION, trans_ids) if trans_ids else {}
        for item in window:
            cid = item["categ_id"]
            item["category_path"] = (
                _category_path(cid, cats) if cid and cid > 0 and cid in cats else None
            )
            item["split_count"] = split_counts.get(item["trans_id"], 0)
            item["tags"] = txn_tags.get(item["trans_id"], [])
            item["is_split"] = item["split_count"] > 0
            item["attachment_count"] = att_counts.get(item["trans_id"], 0)
            withdrawal, deposit = _wd_columns(item, account_id)
            item["withdrawal"] = withdrawal
            item["deposit"] = deposit

    return {
        "account_id": account_id,
        "account_name": name,
        "initial_bal": str(initial),
        "total": total,
        "account_total": account_total,
        "limit": limit,
        "offset": offset,
        "filter": filt,
        "transactions": window,
    }


def list_ledger_transactions(
    engine: Engine,
    *,
    limit: int = 100,
    offset: int = 0,
    include_deleted: bool = False,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """All checking rows (one row per TRANSID), newest first."""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with engine.connect() as conn:
        deleted_sql = "" if include_deleted else "WHERE (c.DELETEDTIME IS NULL OR c.DELETEDTIME = '')"
        rows = conn.execute(
            text(
                f"""
                SELECT c.TRANSID, c.ACCOUNTID, c.TOACCOUNTID, c.PAYEEID, p.PAYEENAME,
                       c.TRANSCODE, c.TRANSAMOUNT, c.STATUS, c.TRANSACTIONNUMBER,
                       c.NOTES, c.CATEGID, c.TRANSDATE, c.LASTUPDATEDTIME,
                       c.DELETEDTIME, c.TOTRANSAMOUNT, c.COLOR, c.FOLLOWUPID,
                       fa.ACCOUNTNAME, ta.ACCOUNTNAME
                  FROM CHECKINGACCOUNT_V1 c
                  LEFT JOIN PAYEE_V1 p ON p.PAYEEID = c.PAYEEID
                  LEFT JOIN ACCOUNTLIST_V1 fa ON fa.ACCOUNTID = c.ACCOUNTID
                  LEFT JOIN ACCOUNTLIST_V1 ta ON ta.ACCOUNTID = c.TOACCOUNTID
                 {deleted_sql}
                 ORDER BY c.TRANSDATE ASC, c.TRANSID ASC
                """
            )
        ).fetchall()
        parsed: list[dict[str, Any]] = []
        for r in rows:
            item = {
                "trans_id": int(r[0]),
                "account_id": int(r[1]),
                "to_account_id": int(r[2] or NOT_SET),
                "payee_id": int(r[3] or NOT_SET),
                "payee_name": r[4] if r[3] not in (None, NOT_SET) else None,
                "trans_code": r[5],
                "trans_amount": str(as_decimal(r[6])),
                "status": r[7] or "",
                "transaction_number": r[8] or "",
                "notes": r[9] or "",
                "categ_id": int(r[10]) if r[10] is not None else NOT_SET,
                "trans_date": r[11],
                "last_updated_time": r[12],
                "deleted_time": r[13] or "",
                "to_trans_amount": str(as_decimal(r[14] if r[14] is not None else r[6])),
                "color": int(r[15] if r[15] is not None else NOT_SET),
                "followup_id": int(r[16] if r[16] is not None else NOT_SET),
                "from_account_name": r[17],
                "to_account_name": r[18],
                "account_name": r[17],
                "flow": "0",
                "running_balance": "",
            }
            code = item["trans_code"]
            amt = str(as_decimal(r[6]))
            if code == TRANS_DEPOSIT:
                item["withdrawal"] = None
                item["deposit"] = amt
            else:
                item["withdrawal"] = amt
                item["deposit"] = None
            parsed.append(item)
        account_total = len(parsed)
        cats = _load_category_map(conn)
        filt = parse_filter(filters)
        if filt:
            parsed = apply_filter(conn, parsed, filt, cats)
        total = len(parsed)
        window = list(reversed(parsed))[offset : offset + limit]
        trans_ids = [t["trans_id"] for t in window]
        split_counts: dict[int, int] = {}
        if trans_ids:
            from sqlalchemy import bindparam

            stmt = text(
                """
                SELECT TRANSID, COUNT(*)
                  FROM SPLITTRANSACTIONS_V1
                 WHERE TRANSID IN :ids
                 GROUP BY TRANSID
                """
            ).bindparams(bindparam("ids", expanding=True))
            for tid, cnt in conn.execute(stmt, {"ids": trans_ids}):
                split_counts[int(tid)] = int(cnt)
        txn_tags = _tags_for(conn, REF_TRANSACTION, trans_ids) if trans_ids else {}
        from mmex_domain.attachments import counts_for

        att_counts = counts_for(engine, REF_TRANSACTION, trans_ids) if trans_ids else {}
        for item in window:
            cid = item["categ_id"]
            item["category_path"] = (
                _category_path(cid, cats) if cid and cid > 0 and cid in cats else None
            )
            item["split_count"] = split_counts.get(item["trans_id"], 0)
            item["tags"] = txn_tags.get(item["trans_id"], [])
            item["is_split"] = item["split_count"] > 0
            item["attachment_count"] = att_counts.get(item["trans_id"], 0)
    return {
        "account_id": None,
        "account_name": None,
        "initial_bal": "0",
        "total": total,
        "account_total": account_total,
        "limit": limit,
        "offset": offset,
        "filter": filt,
        "transactions": window,
    }


def _wd_columns(item: dict[str, Any], account_id: int) -> tuple[str | None, str | None]:
    flow = as_decimal(item["flow"])
    if flow < 0:
        return str(-flow), None
    if flow > 0:
        return None, str(flow)
    return None, None


def get_transaction(engine: Engine, trans_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT c.TRANSID, c.ACCOUNTID, c.TOACCOUNTID, c.PAYEEID, p.PAYEENAME,
                       c.TRANSCODE, c.TRANSAMOUNT, c.STATUS, c.TRANSACTIONNUMBER,
                       c.NOTES, c.CATEGID, c.TRANSDATE, c.LASTUPDATEDTIME,
                       c.DELETEDTIME, c.TOTRANSAMOUNT, c.COLOR, c.FOLLOWUPID
                  FROM CHECKINGACCOUNT_V1 c
                  LEFT JOIN PAYEE_V1 p ON p.PAYEEID = c.PAYEEID
                 WHERE c.TRANSID = :id
                """
            ),
            {"id": trans_id},
        ).fetchone()
        if row is None:
            raise TransactionError(f"unknown transaction {trans_id}")
        cats = _load_category_map(conn)
        item = {
            "trans_id": int(row[0]),
            "account_id": int(row[1]),
            "to_account_id": int(row[2] or NOT_SET),
            "payee_id": int(row[3] or NOT_SET),
            "payee_name": row[4] if row[3] not in (None, NOT_SET) else None,
            "trans_code": row[5],
            "trans_amount": str(as_decimal(row[6])),
            "status": row[7] or "",
            "transaction_number": row[8] or "",
            "notes": row[9] or "",
            "categ_id": int(row[10]) if row[10] is not None else NOT_SET,
            "category_path": (
                _category_path(int(row[10]), cats)
                if row[10] is not None and int(row[10]) > 0
                else None
            ),
            "trans_date": row[11],
            "last_updated_time": row[12],
            "deleted_time": row[13] or "",
            "to_trans_amount": str(as_decimal(row[14] if row[14] is not None else row[6])),
            "color": int(row[15] if row[15] is not None else NOT_SET),
            "followup_id": int(row[16] if row[16] is not None else NOT_SET),
            "tags": _tags_for(conn, REF_TRANSACTION, [int(row[0])]).get(int(row[0]), []),
            "splits": _load_splits(conn, int(row[0]), cats),
        }
        from mmex_domain.attachments import list_attachments

        item["attachments"] = list_attachments(engine, REF_TRANSACTION, int(row[0]))
        item["attachment_count"] = len(item["attachments"])
        return item


def _load_splits(
    conn: Connection, trans_id: int, cats: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT SPLITTRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES
              FROM SPLITTRANSACTIONS_V1
             WHERE TRANSID = :id
             ORDER BY SPLITTRANSID
            """
        ),
        {"id": trans_id},
    ).fetchall()
    split_ids = [int(r[0]) for r in rows]
    tags = _tags_for(conn, REF_TRANSACTION_SPLIT, split_ids) if split_ids else {}
    out = []
    for r in rows:
        cid = int(r[1]) if r[1] is not None else NOT_SET
        out.append(
            {
                "split_id": int(r[0]),
                "categ_id": cid,
                "category_path": _category_path(cid, cats) if cid in cats else None,
                "amount": str(as_decimal(r[2])),
                "notes": r[3] or "",
                "tags": tags.get(int(r[0]), []),
            }
        )
    return out


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("trans_code")
    if code not in TRANS_CODES:
        raise TransactionError("trans_code must be Withdrawal, Deposit, or Transfer")
    amount = as_decimal(payload.get("trans_amount"))
    if amount <= 0:
        raise TransactionError("trans_amount must be positive")
    status = _status(payload.get("status", STATUS_NONE))
    trans_date = _normalize_date(str(payload.get("trans_date") or ""))
    account_id = int(payload["account_id"])
    splits = payload.get("splits") or []
    tag_ids = [int(t) for t in (payload.get("tag_ids") or [])]
    color = int(payload.get("color", NOT_SET))
    if color not in COLOR_IDS:
        raise TransactionError("invalid color")
    followup_id = int(payload.get("followup_id", NOT_SET))
    notes = str(payload.get("notes") or "")
    number = str(payload.get("transaction_number") or "")

    if code == TRANS_TRANSFER:
        to_account = int(payload.get("to_account_id") or NOT_SET)
        if to_account <= 0 or to_account == account_id:
            raise TransactionError("transfer requires a different to_account_id")
        payee_id = NOT_SET
        to_amount = as_decimal(payload.get("to_trans_amount") or amount)
        if to_amount <= 0:
            raise TransactionError("to_trans_amount must be positive")
    else:
        to_account = NOT_SET
        payee_id = int(payload.get("payee_id") or NOT_SET)
        if payee_id <= 0:
            raise TransactionError("payee_id is required")
        to_amount = amount

    if splits:
        split_sum = sum((as_decimal(s["amount"]) for s in splits), Decimal("0"))
        if split_sum != amount:
            raise TransactionError("split amounts must sum to trans_amount")
        for split in splits:
            if int(split.get("categ_id") or NOT_SET) <= 0:
                raise TransactionError("each split needs a categ_id")
            if as_decimal(split["amount"]) <= 0:
                raise TransactionError("split amount must be positive")
        categ_id = NOT_SET
    else:
        categ_id = int(payload.get("categ_id") or NOT_SET)

    return {
        "account_id": account_id,
        "to_account_id": to_account,
        "payee_id": payee_id,
        "trans_code": code,
        "trans_amount": amount,
        "to_trans_amount": to_amount,
        "status": status,
        "transaction_number": number,
        "notes": notes,
        "categ_id": categ_id,
        "trans_date": trans_date,
        "color": color,
        "followup_id": followup_id,
        "tag_ids": tag_ids,
        "splits": splits,
    }


def _replace_tags(conn: Connection, ref_type: str, ref_id: int, tag_ids: list[int]) -> None:
    conn.execute(
        text("DELETE FROM TAGLINK_V1 WHERE REFTYPE = :t AND REFID = :id"),
        {"t": ref_type, "id": ref_id},
    )
    seen: set[int] = set()
    for tag_id in tag_ids:
        tid = int(tag_id)
        if tid <= 0 or tid in seen:
            continue
        seen.add(tid)
        conn.execute(
            text(
                """
                INSERT INTO TAGLINK_V1 (REFTYPE, REFID, TAGID)
                VALUES (:t, :rid, :tag)
                """
            ),
            {"t": ref_type, "rid": ref_id, "tag": tid},
        )


def _replace_splits(conn: Connection, trans_id: int, splits: list[dict[str, Any]]) -> None:
    old_ids = [
        int(r[0])
        for r in conn.execute(
            text("SELECT SPLITTRANSID FROM SPLITTRANSACTIONS_V1 WHERE TRANSID = :id"),
            {"id": trans_id},
        )
    ]
    if old_ids:
        from sqlalchemy import bindparam

        stmt = text(
            "DELETE FROM TAGLINK_V1 WHERE REFTYPE = :t AND REFID IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        conn.execute(stmt, {"t": REF_TRANSACTION_SPLIT, "ids": old_ids})
        conn.execute(
            text("DELETE FROM SPLITTRANSACTIONS_V1 WHERE TRANSID = :id"),
            {"id": trans_id},
        )
    for split in splits:
        sid = _next_id(conn, "SPLITTRANSACTIONS_V1", "SPLITTRANSID")
        conn.execute(
            text(
                """
                INSERT INTO SPLITTRANSACTIONS_V1 (
                    SPLITTRANSID, TRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES
                ) VALUES (:sid, :tid, :cid, :amt, :notes)
                """
            ),
            {
                "sid": sid,
                "tid": trans_id,
                "cid": int(split["categ_id"]),
                "amt": str(as_decimal(split["amount"])),
                "notes": str(split.get("notes") or ""),
            },
        )
        _replace_tags(
            conn,
            REF_TRANSACTION_SPLIT,
            sid,
            [int(t) for t in (split.get("tag_ids") or [])],
        )


def create_transaction(engine: Engine, payload: dict[str, Any]) -> dict[str, Any]:
    data = _validate(payload)
    with engine.begin() as conn:
        trans_id = _next_id(conn, "CHECKINGACCOUNT_V1", "TRANSID")
        _assert_account(conn, data["account_id"])
        if data["trans_code"] == TRANS_TRANSFER:
            _assert_account(conn, data["to_account_id"])
        else:
            _assert_payee(conn, data["payee_id"])
        _guard_statement(
            conn,
            data["account_id"],
            data["trans_date"],
            data["to_account_id"] if data["trans_code"] == TRANS_TRANSFER else None,
        )
        now = _now()
        conn.execute(
            text(
                """
                INSERT INTO CHECKINGACCOUNT_V1 (
                    TRANSID, ACCOUNTID, TOACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT,
                    STATUS, TRANSACTIONNUMBER, NOTES, CATEGID, TRANSDATE,
                    LASTUPDATEDTIME, DELETEDTIME, FOLLOWUPID, TOTRANSAMOUNT, COLOR
                ) VALUES (
                    :tid, :aid, :toid, :pid, :code, :amt, :status, :num, :notes,
                    :cid, :tdate, :upd, '', :follow, :toamt, :color
                )
                """
            ),
            {
                "tid": trans_id,
                "aid": data["account_id"],
                "toid": data["to_account_id"],
                "pid": data["payee_id"],
                "code": data["trans_code"],
                "amt": str(data["trans_amount"]),
                "status": data["status"],
                "num": data["transaction_number"],
                "notes": data["notes"],
                "cid": data["categ_id"],
                "tdate": data["trans_date"],
                "upd": now,
                "follow": data["followup_id"],
                "toamt": str(data["to_trans_amount"]),
                "color": data["color"],
            },
        )
        _replace_tags(conn, REF_TRANSACTION, trans_id, data["tag_ids"])
        _replace_splits(conn, trans_id, data["splits"])
    return get_transaction(engine, trans_id)


def update_transaction(engine: Engine, trans_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = _validate(payload)
    with engine.begin() as conn:
        existing = conn.execute(
            text(
                "SELECT TRANSID, ACCOUNTID, TOACCOUNTID, TRANSDATE FROM CHECKINGACCOUNT_V1 "
                "WHERE TRANSID = :id"
            ),
            {"id": trans_id},
        ).fetchone()
        if existing is None:
            raise TransactionError(f"unknown transaction {trans_id}")
        _assert_account(conn, data["account_id"])
        if data["trans_code"] == TRANS_TRANSFER:
            _assert_account(conn, data["to_account_id"])
        else:
            _assert_payee(conn, data["payee_id"])
        _guard_statement(conn, int(existing[1]), existing[3], int(existing[2] or 0))
        _guard_statement(
            conn,
            data["account_id"],
            data["trans_date"],
            data["to_account_id"] if data["trans_code"] == TRANS_TRANSFER else None,
        )
        conn.execute(
            text(
                """
                UPDATE CHECKINGACCOUNT_V1 SET
                    ACCOUNTID = :aid,
                    TOACCOUNTID = :toid,
                    PAYEEID = :pid,
                    TRANSCODE = :code,
                    TRANSAMOUNT = :amt,
                    STATUS = :status,
                    TRANSACTIONNUMBER = :num,
                    NOTES = :notes,
                    CATEGID = :cid,
                    TRANSDATE = :tdate,
                    LASTUPDATEDTIME = :upd,
                    TOTRANSAMOUNT = :toamt,
                    COLOR = :color,
                    FOLLOWUPID = :follow
                 WHERE TRANSID = :tid
                """
            ),
            {
                "tid": trans_id,
                "aid": data["account_id"],
                "toid": data["to_account_id"],
                "pid": data["payee_id"],
                "code": data["trans_code"],
                "amt": str(data["trans_amount"]),
                "status": data["status"],
                "num": data["transaction_number"],
                "notes": data["notes"],
                "cid": data["categ_id"],
                "tdate": data["trans_date"],
                "upd": _now(),
                "toamt": str(data["to_trans_amount"]),
                "color": data["color"],
                "follow": data["followup_id"],
            },
        )
        _replace_tags(conn, REF_TRANSACTION, trans_id, data["tag_ids"])
        _replace_splits(conn, trans_id, data["splits"])
    return get_transaction(engine, trans_id)


def cycle_status(engine: Engine, trans_id: int) -> dict[str, Any]:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT STATUS, ACCOUNTID, TOACCOUNTID, TRANSDATE FROM CHECKINGACCOUNT_V1 "
                "WHERE TRANSID = :id"
            ),
            {"id": trans_id},
        ).fetchone()
        if row is None:
            raise TransactionError(f"unknown transaction {trans_id}")
        _guard_statement(conn, int(row[1]), row[3], int(row[2] or 0))
        current = row[0] or ""
        try:
            idx = STATUS_CYCLE.index(current)
        except ValueError:
            idx = 0
        nxt = STATUS_CYCLE[(idx + 1) % len(STATUS_CYCLE)]
        conn.execute(
            text(
                """
                UPDATE CHECKINGACCOUNT_V1
                   SET STATUS = :st, LASTUPDATEDTIME = :upd
                 WHERE TRANSID = :id
                """
            ),
            {"st": nxt, "upd": _now(), "id": trans_id},
        )
    return get_transaction(engine, trans_id)


def soft_delete(engine: Engine, trans_id: int) -> dict[str, Any]:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT ACCOUNTID, TOACCOUNTID, TRANSDATE FROM CHECKINGACCOUNT_V1 "
                "WHERE TRANSID = :id"
            ),
            {"id": trans_id},
        ).fetchone()
        if row is None:
            raise TransactionError(f"unknown transaction {trans_id}")
        _guard_statement(conn, int(row[0]), row[2], int(row[1] or 0))
        n = conn.execute(
            text(
                """
                UPDATE CHECKINGACCOUNT_V1
                   SET DELETEDTIME = :ts, LASTUPDATEDTIME = :ts
                 WHERE TRANSID = :id
                """
            ),
            {"ts": _now(), "id": trans_id},
        ).rowcount
        if not n:
            raise TransactionError(f"unknown transaction {trans_id}")
    return get_transaction(engine, trans_id)


def restore(engine: Engine, trans_id: int) -> dict[str, Any]:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT ACCOUNTID, TOACCOUNTID, TRANSDATE FROM CHECKINGACCOUNT_V1 "
                "WHERE TRANSID = :id"
            ),
            {"id": trans_id},
        ).fetchone()
        if row is None:
            raise TransactionError(f"unknown transaction {trans_id}")
        _guard_statement(conn, int(row[0]), row[2], int(row[1] or 0))
        n = conn.execute(
            text(
                """
                UPDATE CHECKINGACCOUNT_V1
                   SET DELETEDTIME = '', LASTUPDATEDTIME = :ts
                 WHERE TRANSID = :id
                """
            ),
            {"ts": _now(), "id": trans_id},
        ).rowcount
        if not n:
            raise TransactionError(f"unknown transaction {trans_id}")
    return get_transaction(engine, trans_id)


def _assert_account(conn: Connection, account_id: int) -> None:
    row = conn.execute(
        text("SELECT ACCOUNTID FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id"),
        {"id": account_id},
    ).fetchone()
    if row is None:
        raise TransactionError(f"unknown account {account_id}")


def _assert_payee(conn: Connection, payee_id: int) -> None:
    row = conn.execute(
        text("SELECT PAYEEID FROM PAYEE_V1 WHERE PAYEEID = :id"),
        {"id": payee_id},
    ).fetchone()
    if row is None:
        raise TransactionError(f"unknown payee {payee_id}")
