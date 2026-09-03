"""Register filter matching (desktop FilterTrans: date, payee, category, status, type, amount, notes, tags)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from mmex_domain.constants import NOT_SET, REF_TRANSACTION, REF_TRANSACTION_SPLIT
from mmex_domain.money import as_decimal


def parse_filter(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw or {}
    out: dict[str, Any] = {}
    if src.get("date_from"):
        out["date_from"] = str(src["date_from"])[:10]
    if src.get("date_to"):
        out["date_to"] = str(src["date_to"])[:10]
    if src.get("payee_id") not in (None, "", 0, -1):
        out["payee_id"] = int(src["payee_id"])
    if src.get("payee_q"):
        out["payee_q"] = str(src["payee_q"]).strip().lower()
    if src.get("categ_id") not in (None, "", 0, -1):
        out["categ_id"] = int(src["categ_id"])
    code = src.get("trans_code")
    if code in ("Withdrawal", "Deposit", "Transfer"):
        out["trans_code"] = code
    if "status" in src and src["status"] is not None:
        status = str(src["status"])
        if status in ("none", "__none__"):
            status = ""
        if status != "*":
            out["status"] = status
    if src.get("amount_min") not in (None, ""):
        out["amount_min"] = str(as_decimal(src["amount_min"]))
    if src.get("amount_max") not in (None, ""):
        out["amount_max"] = str(as_decimal(src["amount_max"]))
    if src.get("notes"):
        out["notes"] = str(src["notes"]).strip().lower()
    if src.get("number"):
        out["number"] = str(src["number"]).strip().lower()
    if src.get("tag_id") not in (None, "", 0, -1):
        out["tag_id"] = int(src["tag_id"])
    if src.get("color") not in (None, ""):
        out["color"] = int(src["color"])
    follow = src.get("followup")
    if follow in (True, "true", "1", 1):
        out["followup"] = True
    elif follow in (False, "false", "0", 0):
        out["followup"] = False
    return out


def is_active(filt: dict[str, Any] | None) -> bool:
    return bool(filt)


def _descendants(cats: dict[int, dict[str, Any]], root: int) -> set[int]:
    children: dict[int, list[int]] = defaultdict(list)
    for cid, info in cats.items():
        pid = info.get("parent_id")
        if pid:
            children[int(pid)].append(int(cid))
    out = {int(root)}
    stack = [int(root)]
    while stack:
        cur = stack.pop()
        for child in children.get(cur, []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def _load_split_categs(conn: Connection, trans_ids: list[int]) -> dict[int, set[int]]:
    result: dict[int, set[int]] = {i: set() for i in trans_ids}
    if not trans_ids:
        return result
    stmt = text(
        "SELECT TRANSID, CATEGID FROM SPLITTRANSACTIONS_V1 WHERE TRANSID IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    for tid, cid in conn.execute(stmt, {"ids": trans_ids}):
        if cid is not None and int(cid) > 0:
            result.setdefault(int(tid), set()).add(int(cid))
    return result


def _load_tag_hits(conn: Connection, trans_ids: list[int], tag_id: int) -> set[int]:
    if not trans_ids:
        return set()
    hits: set[int] = set()
    stmt = text(
        """
        SELECT REFID FROM TAGLINK_V1
         WHERE REFTYPE = :t AND TAGID = :tag AND REFID IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))
    for (ref_id,) in conn.execute(
        stmt, {"t": REF_TRANSACTION, "tag": tag_id, "ids": trans_ids}
    ):
        hits.add(int(ref_id))
    split_stmt = text(
        """
        SELECT s.TRANSID
          FROM SPLITTRANSACTIONS_V1 s
          JOIN TAGLINK_V1 l ON l.REFTYPE = :t AND l.REFID = s.SPLITTRANSID
         WHERE l.TAGID = :tag AND s.TRANSID IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))
    for (tid,) in conn.execute(
        split_stmt, {"t": REF_TRANSACTION_SPLIT, "tag": tag_id, "ids": trans_ids}
    ):
        hits.add(int(tid))
    return hits


def apply_filter(
    conn: Connection,
    rows: list[dict[str, Any]],
    filt: dict[str, Any],
    cats: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not filt:
        return rows
    trans_ids = [r["trans_id"] for r in rows]
    split_categs: dict[int, set[int]] = {}
    tag_hits: set[int] | None = None
    categ_set: set[int] | None = None
    if "categ_id" in filt:
        categ_set = _descendants(cats, filt["categ_id"])
        split_categs = _load_split_categs(conn, trans_ids)
    if "tag_id" in filt:
        tag_hits = _load_tag_hits(conn, trans_ids, filt["tag_id"])

    matched: list[dict[str, Any]] = []
    for item in rows:
        day = (item.get("trans_date") or "")[:10]
        if "date_from" in filt and day < filt["date_from"]:
            continue
        if "date_to" in filt and day > filt["date_to"]:
            continue
        if "payee_id" in filt and int(item.get("payee_id") or NOT_SET) != filt["payee_id"]:
            continue
        if "payee_q" in filt:
            name = (item.get("payee_name") or "").lower()
            if filt["payee_q"] not in name:
                continue
        if "trans_code" in filt and item.get("trans_code") != filt["trans_code"]:
            continue
        if "status" in filt and (item.get("status") or "") != filt["status"]:
            continue
        if "notes" in filt and filt["notes"] not in (item.get("notes") or "").lower():
            continue
        if "number" in filt and filt["number"] not in (
            item.get("transaction_number") or ""
        ).lower():
            continue
        if "color" in filt and int(item.get("color") or NOT_SET) != filt["color"]:
            continue
        if filt.get("followup") is True and int(item.get("followup_id") or NOT_SET) <= 0:
            continue
        if filt.get("followup") is False and int(item.get("followup_id") or NOT_SET) > 0:
            continue
        if categ_set is not None:
            cid = int(item.get("categ_id") or NOT_SET)
            splits = split_categs.get(item["trans_id"], set())
            if cid not in categ_set and splits.isdisjoint(categ_set):
                continue
        if tag_hits is not None and item["trans_id"] not in tag_hits:
            continue
        if "amount_min" in filt or "amount_max" in filt:
            flow = abs(as_decimal(item.get("flow") or 0))
            shown = flow if flow != 0 else as_decimal(item.get("trans_amount") or 0)
            if "amount_min" in filt and shown < as_decimal(filt["amount_min"]):
                continue
            if "amount_max" in filt and shown > as_decimal(filt["amount_max"]):
                continue
        matched.append(item)
    return matched
