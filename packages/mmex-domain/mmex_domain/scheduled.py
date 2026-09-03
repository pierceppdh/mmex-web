"""Scheduled bills (BILLSDEPOSITS_V1): list, CRUD, enter, skip, silent due job."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.constants import NOT_SET, REF_TRANSACTION
from mmex_domain.lookups import _category_path
from mmex_domain.money import as_decimal
from mmex_domain.repeats import (
    AUTO_SILENT,
    INTERVAL_TYPES,
    ONE_SHOT_TYPES,
    USES_REMAINING,
    auto_meta,
    decode,
    encode,
    next_occurrence,
    type_meta,
)
from mmex_domain.transactions import TransactionError, _next_id, create_transaction

REF_REPEATING = "Repeating Transaction"


class ScheduledError(ValueError):
    """Invalid scheduled payload or missing bill."""


def _parse_day(value: str | None) -> date:
    raw = (value or "").strip()
    if not raw:
        raise ScheduledError("next_occurrence_date is required")
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    return date.fromisoformat(raw[:10])


def _fmt(day: date) -> str:
    return day.isoformat() + "T00:00:00"


def _today() -> date:
    return datetime.now().date()


def _load_cats(conn: Connection) -> dict[int, dict[str, Any]]:
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


def list_scheduled(engine: Engine) -> dict[str, Any]:
    today = _today()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT b.BDID, b.ACCOUNTID, a.ACCOUNTNAME, b.TOACCOUNTID, ta.ACCOUNTNAME,
                       b.PAYEEID, p.PAYEENAME, b.TRANSCODE, b.TRANSAMOUNT, b.STATUS,
                       b.TRANSACTIONNUMBER, b.NOTES, b.CATEGID, b.TRANSDATE,
                       b.NEXTOCCURRENCEDATE, b.REPEATS, b.NUMOCCURRENCES, b.COLOR,
                       b.FOLLOWUPID, b.TOTRANSAMOUNT
                  FROM BILLSDEPOSITS_V1 b
                  LEFT JOIN ACCOUNTLIST_V1 a ON a.ACCOUNTID = b.ACCOUNTID
                  LEFT JOIN ACCOUNTLIST_V1 ta ON ta.ACCOUNTID = b.TOACCOUNTID
                  LEFT JOIN PAYEE_V1 p ON p.PAYEEID = b.PAYEEID
                 ORDER BY b.NEXTOCCURRENCEDATE ASC, b.BDID ASC
                """
            )
        ).fetchall()
        cats = _load_cats(conn)
        ids = [int(r[0]) for r in rows]
        split_counts: dict[int, int] = {}
        if ids:
            from sqlalchemy import bindparam

            stmt = text(
                """
                SELECT TRANSID, COUNT(*) FROM BUDGETSPLITTRANSACTIONS_V1
                 WHERE TRANSID IN :ids GROUP BY TRANSID
                """
            ).bindparams(bindparam("ids", expanding=True))
            for bid, cnt in conn.execute(stmt, {"ids": ids}):
                split_counts[int(bid)] = int(cnt)
    out = []
    overdue = 0
    for r in rows:
        kind, auto = decode(r[15])
        try:
            nxt = _parse_day(r[14])
        except ScheduledError:
            nxt = today
        days = (nxt - today).days
        if days <= 0:
            overdue += 1
        cid = int(r[12]) if r[12] is not None else NOT_SET
        item = {
            "bd_id": int(r[0]),
            "account_id": int(r[1]),
            "account_name": r[2],
            "to_account_id": int(r[3] or NOT_SET),
            "to_account_name": r[4],
            "payee_id": int(r[5] or NOT_SET),
            "payee_name": r[6] if r[5] not in (None, NOT_SET) else None,
            "trans_code": r[7],
            "trans_amount": str(as_decimal(r[8])),
            "status": r[9] or "",
            "transaction_number": r[10] or "",
            "notes": r[11] or "",
            "categ_id": cid,
            "category_path": _category_path(cid, cats) if cid in cats else None,
            "trans_date": r[13],
            "next_occurrence_date": r[14],
            "repeats": int(r[15] or 0),
            "repeat_type": kind,
            "auto_mode": auto,
            "repeat_label_fr": type_meta(kind)["label_fr"],
            "repeat_label_en": type_meta(kind)["label_en"],
            "auto_label_fr": auto_meta(auto)["label_fr"],
            "auto_label_en": auto_meta(auto)["label_en"],
            "num_occurrences": int(r[16] if r[16] is not None else NOT_SET),
            "color": int(r[17] if r[17] is not None else NOT_SET),
            "followup_id": int(r[18] if r[18] is not None else NOT_SET),
            "to_trans_amount": str(as_decimal(r[19] if r[19] is not None else r[8])),
            "days_until": days,
            "overdue": days <= 0,
            "split_count": split_counts.get(int(r[0]), 0),
        }
        out.append(item)
    return {"scheduled": out, "overdue": overdue, "total": len(out)}


def get_scheduled(engine: Engine, bd_id: int) -> dict[str, Any]:
    rows = [s for s in list_scheduled(engine)["scheduled"] if s["bd_id"] == bd_id]
    if not rows:
        raise ScheduledError(f"unknown scheduled {bd_id}")
    item = dict(rows[0])
    with engine.connect() as conn:
        item["splits"] = _load_splits(conn, bd_id)
        item["tag_ids"] = [
            int(r[0])
            for r in conn.execute(
                text(
                    "SELECT TAGID FROM TAGLINK_V1 WHERE REFTYPE = :t AND REFID = :id"
                ),
                {"t": REF_REPEATING, "id": bd_id},
            )
        ]
    return item


def _load_splits(conn: Connection, bd_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT SPLITTRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES
              FROM BUDGETSPLITTRANSACTIONS_V1
             WHERE TRANSID = :id
             ORDER BY SPLITTRANSID
            """
        ),
        {"id": bd_id},
    ).fetchall()
    return [
        {
            "split_id": int(r[0]),
            "categ_id": int(r[1]),
            "amount": str(as_decimal(r[2])),
            "notes": r[3] or "",
        }
        for r in rows
    ]


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    from mmex_domain.constants import TRANS_CODES, TRANS_TRANSFER

    code = payload.get("trans_code")
    if code not in TRANS_CODES:
        raise ScheduledError("trans_code must be Withdrawal, Deposit, or Transfer")
    amount = as_decimal(payload.get("trans_amount"))
    if amount <= 0:
        raise ScheduledError("trans_amount must be positive")
    account_id = int(payload["account_id"])
    nxt = _parse_day(str(payload.get("next_occurrence_date") or payload.get("trans_date") or ""))
    kind = int(payload.get("repeat_type") or 0)
    auto = int(payload.get("auto_mode") or 0)
    try:
        repeats = encode(kind, auto)
    except ValueError as exc:
        raise ScheduledError(str(exc)) from exc
    interval = int(payload.get("interval") or payload.get("num_occurrences") or 1)
    remaining = int(payload["remaining"]) if payload.get("remaining") not in (None, "") else NOT_SET
    if remaining == 0:
        remaining = NOT_SET
    if kind in INTERVAL_TYPES:
        if interval <= 0:
            raise ScheduledError("interval must be positive")
        num = interval
    else:
        num = remaining
    if code == TRANS_TRANSFER:
        to_account = int(payload.get("to_account_id") or NOT_SET)
        if to_account <= 0 or to_account == account_id:
            raise ScheduledError("transfer requires a different to_account_id")
        payee_id = NOT_SET
        to_amount = as_decimal(payload.get("to_trans_amount") or amount)
    else:
        to_account = NOT_SET
        payee_id = int(payload.get("payee_id") or NOT_SET)
        if payee_id <= 0:
            raise ScheduledError("payee_id is required")
        to_amount = amount
    splits = payload.get("splits") or []
    categ_id = NOT_SET if splits else int(payload.get("categ_id") or NOT_SET)
    return {
        "account_id": account_id,
        "to_account_id": to_account,
        "payee_id": payee_id,
        "trans_code": code,
        "trans_amount": amount,
        "to_trans_amount": to_amount,
        "status": str(payload.get("status") or ""),
        "transaction_number": str(payload.get("transaction_number") or ""),
        "notes": str(payload.get("notes") or ""),
        "categ_id": categ_id,
        "trans_date": _fmt(nxt),
        "next_occurrence_date": _fmt(nxt),
        "repeats": repeats,
        "num_occurrences": num,
        "color": int(payload.get("color", NOT_SET)),
        "followup_id": int(payload.get("followup_id", NOT_SET)),
        "tag_ids": [int(t) for t in (payload.get("tag_ids") or [])],
        "splits": splits,
    }


def create_scheduled(engine: Engine, payload: dict[str, Any]) -> dict[str, Any]:
    data = _validate(payload)
    with engine.begin() as conn:
        bd_id = _next_id(conn, "BILLSDEPOSITS_V1", "BDID")
        _insert_bill(conn, bd_id, data)
        _replace_bill_splits(conn, bd_id, data["splits"])
        _replace_bill_tags(conn, bd_id, data["tag_ids"])
    return get_scheduled(engine, bd_id)


def update_scheduled(engine: Engine, bd_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = _validate(payload)
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT BDID FROM BILLSDEPOSITS_V1 WHERE BDID = :id"), {"id": bd_id}
        ).fetchone()
        if exists is None:
            raise ScheduledError(f"unknown scheduled {bd_id}")
        conn.execute(text("DELETE FROM BILLSDEPOSITS_V1 WHERE BDID = :id"), {"id": bd_id})
        _insert_bill(conn, bd_id, data)
        _replace_bill_splits(conn, bd_id, data["splits"])
        _replace_bill_tags(conn, bd_id, data["tag_ids"])
    return get_scheduled(engine, bd_id)


def _insert_bill(conn: Connection, bd_id: int, data: dict[str, Any]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO BILLSDEPOSITS_V1 (
                BDID, ACCOUNTID, TOACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT,
                STATUS, TRANSACTIONNUMBER, NOTES, CATEGID, TRANSDATE, FOLLOWUPID,
                TOTRANSAMOUNT, REPEATS, NEXTOCCURRENCEDATE, NUMOCCURRENCES, COLOR
            ) VALUES (
                :id, :aid, :toid, :pid, :code, :amt, :status, :num, :notes, :cid,
                :tdate, :follow, :toamt, :rep, :nxt, :occ, :color
            )
            """
        ),
        {
            "id": bd_id,
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
            "follow": data["followup_id"],
            "toamt": str(data["to_trans_amount"]),
            "rep": data["repeats"],
            "nxt": data["next_occurrence_date"],
            "occ": data["num_occurrences"],
            "color": data["color"],
        },
    )


def _replace_bill_splits(conn: Connection, bd_id: int, splits: list[dict[str, Any]]) -> None:
    conn.execute(
        text("DELETE FROM BUDGETSPLITTRANSACTIONS_V1 WHERE TRANSID = :id"), {"id": bd_id}
    )
    for split in splits:
        sid = _next_id(conn, "BUDGETSPLITTRANSACTIONS_V1", "SPLITTRANSID")
        conn.execute(
            text(
                """
                INSERT INTO BUDGETSPLITTRANSACTIONS_V1 (
                    SPLITTRANSID, TRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES
                ) VALUES (:sid, :tid, :cid, :amt, :notes)
                """
            ),
            {
                "sid": sid,
                "tid": bd_id,
                "cid": int(split["categ_id"]),
                "amt": str(as_decimal(split["amount"])),
                "notes": str(split.get("notes") or ""),
            },
        )


def _replace_bill_tags(conn: Connection, bd_id: int, tag_ids: list[int]) -> None:
    conn.execute(
        text("DELETE FROM TAGLINK_V1 WHERE REFTYPE = :t AND REFID = :id"),
        {"t": REF_REPEATING, "id": bd_id},
    )
    seen: set[int] = set()
    for tag_id in tag_ids:
        tid = int(tag_id)
        if tid <= 0 or tid in seen:
            continue
        seen.add(tid)
        conn.execute(
            text("INSERT INTO TAGLINK_V1 (REFTYPE, REFID, TAGID) VALUES (:t, :rid, :tag)"),
            {"t": REF_REPEATING, "rid": bd_id, "tag": tid},
        )


def delete_scheduled(engine: Engine, bd_id: int) -> None:
    with engine.begin() as conn:
        n = conn.execute(
            text("DELETE FROM BILLSDEPOSITS_V1 WHERE BDID = :id"), {"id": bd_id}
        ).rowcount
        if not n:
            raise ScheduledError(f"unknown scheduled {bd_id}")
        conn.execute(
            text("DELETE FROM BUDGETSPLITTRANSACTIONS_V1 WHERE TRANSID = :id"), {"id": bd_id}
        )
        conn.execute(
            text("DELETE FROM TAGLINK_V1 WHERE REFTYPE = :t AND REFID = :id"),
            {"t": REF_REPEATING, "id": bd_id},
        )


def enter_scheduled(engine: Engine, bd_id: int) -> dict[str, Any]:
    """Write one checking row from the bill, then advance or delete the schedule."""
    bill = get_scheduled(engine, bd_id)
    payload = {
        "account_id": bill["account_id"],
        "to_account_id": bill["to_account_id"] if bill["to_account_id"] > 0 else None,
        "payee_id": bill["payee_id"] if bill["payee_id"] > 0 else None,
        "trans_code": bill["trans_code"],
        "trans_amount": bill["trans_amount"],
        "to_trans_amount": bill["to_trans_amount"],
        "trans_date": bill["next_occurrence_date"],
        "status": bill["status"],
        "transaction_number": bill["transaction_number"],
        "notes": bill["notes"],
        "categ_id": bill["categ_id"],
        "color": bill["color"],
        "followup_id": bill["followup_id"],
        "tag_ids": bill.get("tag_ids") or [],
        "splits": [
            {
                "categ_id": s["categ_id"],
                "amount": s["amount"],
                "notes": s["notes"],
                "tag_ids": [],
            }
            for s in bill.get("splits") or []
        ],
    }
    try:
        txn = create_transaction(engine, payload)
    except TransactionError as exc:
        raise ScheduledError(str(exc)) from exc
    ended = _advance_or_delete(engine, bill)
    return {"transaction": txn, "ended": ended, "scheduled": None if ended else get_scheduled(engine, bd_id)}


def skip_scheduled(engine: Engine, bd_id: int) -> dict[str, Any]:
    bill = get_scheduled(engine, bd_id)
    ended = _advance_or_delete(engine, bill)
    return {"ended": ended, "scheduled": None if ended else get_scheduled(engine, bd_id)}


def _advance_or_delete(engine: Engine, bill: dict[str, Any]) -> bool:
    kind = bill["repeat_type"]
    remaining = int(bill["num_occurrences"])
    if kind in ONE_SHOT_TYPES or (kind in USES_REMAINING and remaining == 1):
        delete_scheduled(engine, bill["bd_id"])
        return True
    nxt = next_occurrence(
        _parse_day(bill["next_occurrence_date"]),
        kind,
        remaining if kind in INTERVAL_TYPES else 1,
    )
    due = next_occurrence(
        _parse_day(bill["trans_date"] or bill["next_occurrence_date"]),
        kind,
        remaining if kind in INTERVAL_TYPES else 1,
    )
    new_remaining = remaining
    if kind in USES_REMAINING and remaining > 1:
        new_remaining = remaining - 1
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE BILLSDEPOSITS_V1
                   SET NEXTOCCURRENCEDATE = :nxt,
                       TRANSDATE = :due,
                       NUMOCCURRENCES = :occ
                 WHERE BDID = :id
                """
            ),
            {
                "nxt": _fmt(nxt),
                "due": _fmt(due),
                "occ": new_remaining,
                "id": bill["bd_id"],
            },
        )
    return False


def process_due_silent(engine: Engine, today: date | None = None) -> dict[str, Any]:
    """Enter silent (auto=2) bills whose next date is on or before today. Catch up."""
    today = today or _today()
    entered = 0
    ended = 0
    errors: list[str] = []
    for _ in range(48):
        due_ids: list[int] = []
        for item in list_scheduled(engine)["scheduled"]:
            if item["auto_mode"] != AUTO_SILENT:
                continue
            if _parse_day(item["next_occurrence_date"]) <= today:
                due_ids.append(item["bd_id"])
        if not due_ids:
            break
        progressed = False
        for bd_id in due_ids:
            try:
                result = enter_scheduled(engine, bd_id)
                entered += 1
                progressed = True
                if result["ended"]:
                    ended += 1
            except (ScheduledError, TransactionError) as exc:
                errors.append(f"{bd_id}: {exc}")
        if not progressed:
            break
    return {"entered": entered, "ended": ended, "errors": errors}
