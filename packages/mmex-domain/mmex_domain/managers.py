"""CRUD for payees, nested categories, tags, and currencies."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.constants import NOT_SET
from mmex_domain.lookups import _category_path
from mmex_domain.money import as_decimal

CURRENCY_TYPES = ("Fiat", "Crypto")


class ManagerError(ValueError):
    """Invalid manager payload or conflict with existing rows."""


def _next_id(conn: Connection, table: str, column: str) -> int:
    now_based = int(time.time() * 1000) * 1000
    max_id = int(conn.execute(text(f"SELECT MAX({column}) FROM {table}")).scalar() or 0)
    return max(now_based, max_id + 1)


def _name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise ManagerError("name is required")
    return name


def _active(value: Any, default: int = 1) -> int:
    if value is None or value == "":
        return default
    return 1 if int(value) else 0


def _categ_id(value: Any) -> int:
    if value in (None, "", 0):
        return NOT_SET
    return int(value)


# --- Payees ---


def list_payees_admin(engine: Engine, include_inactive: bool = True) -> list[dict[str, Any]]:
    where = "" if include_inactive else "WHERE IFNULL(p.ACTIVE, 1) != 0"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT p.PAYEEID, p.PAYEENAME, p.CATEGID, p.NUMBER, p.WEBSITE,
                       p.NOTES, IFNULL(p.ACTIVE, 1), IFNULL(p.PATTERN, ''),
                       (SELECT COUNT(*) FROM CHECKINGACCOUNT_V1 c WHERE c.PAYEEID = p.PAYEEID)
                       + (SELECT COUNT(*) FROM BILLSDEPOSITS_V1 b WHERE b.PAYEEID = p.PAYEEID)
                  FROM PAYEE_V1 p
                  {where}
                 ORDER BY p.PAYEENAME COLLATE NOCASE
                """
            )
        ).fetchall()
        cats = _category_map(conn)
    out = []
    for r in rows:
        cid = int(r[2]) if r[2] is not None else NOT_SET
        out.append(
            {
                "payee_id": int(r[0]),
                "name": r[1],
                "categ_id": cid,
                "category_path": _category_path(cid, cats) if cid in cats else None,
                "number": r[3] or "",
                "website": r[4] or "",
                "notes": r[5] or "",
                "active": int(r[6]),
                "pattern": r[7] or "",
                "used_count": int(r[8] or 0),
            }
        )
    return out


def get_payee(engine: Engine, payee_id: int) -> dict[str, Any]:
    rows = [p for p in list_payees_admin(engine) if p["payee_id"] == payee_id]
    if not rows:
        raise ManagerError(f"unknown payee {payee_id}")
    return rows[0]


def create_payee(engine: Engine, payload: dict[str, Any]) -> dict[str, Any]:
    data = _payee_fields(payload)
    with engine.begin() as conn:
        _assert_unique_payee(conn, data["name"])
        if data["categ_id"] > 0:
            _assert_category(conn, data["categ_id"])
        pid = _next_id(conn, "PAYEE_V1", "PAYEEID")
        conn.execute(
            text(
                """
                INSERT INTO PAYEE_V1 (
                    PAYEEID, PAYEENAME, CATEGID, NUMBER, WEBSITE, NOTES, ACTIVE, PATTERN
                ) VALUES (:id, :name, :cid, :num, :web, :notes, :active, :pat)
                """
            ),
            {
                "id": pid,
                "name": data["name"],
                "cid": data["categ_id"],
                "num": data["number"],
                "web": data["website"],
                "notes": data["notes"],
                "active": data["active"],
                "pat": data["pattern"],
            },
        )
    return get_payee(engine, pid)


def update_payee(engine: Engine, payee_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = _payee_fields(payload)
    with engine.begin() as conn:
        if conn.execute(
            text("SELECT PAYEEID FROM PAYEE_V1 WHERE PAYEEID = :id"), {"id": payee_id}
        ).fetchone() is None:
            raise ManagerError(f"unknown payee {payee_id}")
        _assert_unique_payee(conn, data["name"], exclude=payee_id)
        if data["categ_id"] > 0:
            _assert_category(conn, data["categ_id"])
        conn.execute(
            text(
                """
                UPDATE PAYEE_V1 SET
                    PAYEENAME = :name, CATEGID = :cid, NUMBER = :num,
                    WEBSITE = :web, NOTES = :notes, ACTIVE = :active, PATTERN = :pat
                 WHERE PAYEEID = :id
                """
            ),
            {
                "id": payee_id,
                "name": data["name"],
                "cid": data["categ_id"],
                "num": data["number"],
                "web": data["website"],
                "notes": data["notes"],
                "active": data["active"],
                "pat": data["pattern"],
            },
        )
    return get_payee(engine, payee_id)


def set_payee_active(engine: Engine, payee_id: int, active: bool) -> dict[str, Any]:
    with engine.begin() as conn:
        n = conn.execute(
            text("UPDATE PAYEE_V1 SET ACTIVE = :a WHERE PAYEEID = :id"),
            {"a": 1 if active else 0, "id": payee_id},
        ).rowcount
        if not n:
            raise ManagerError(f"unknown payee {payee_id}")
    return get_payee(engine, payee_id)


def delete_payee(engine: Engine, payee_id: int) -> None:
    with engine.begin() as conn:
        used = conn.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM CHECKINGACCOUNT_V1 WHERE PAYEEID = :id)
                + (SELECT COUNT(*) FROM BILLSDEPOSITS_V1 WHERE PAYEEID = :id)
                """
            ),
            {"id": payee_id},
        ).scalar()
        if int(used or 0):
            raise ManagerError("payee is in use")
        n = conn.execute(
            text("DELETE FROM PAYEE_V1 WHERE PAYEEID = :id"), {"id": payee_id}
        ).rowcount
        if not n:
            raise ManagerError(f"unknown payee {payee_id}")


def merge_payees(engine: Engine, source_id: int, dest_id: int) -> dict[str, Any]:
    if int(source_id) == int(dest_id):
        raise ManagerError("cannot merge a payee into itself")
    with engine.begin() as conn:
        for pid in (source_id, dest_id):
            if conn.execute(
                text("SELECT PAYEEID FROM PAYEE_V1 WHERE PAYEEID = :id"), {"id": pid}
            ).fetchone() is None:
                raise ManagerError(f"unknown payee {pid}")
        checking = conn.execute(
            text("UPDATE CHECKINGACCOUNT_V1 SET PAYEEID = :d WHERE PAYEEID = :s"),
            {"d": dest_id, "s": source_id},
        ).rowcount
        bills = conn.execute(
            text("UPDATE BILLSDEPOSITS_V1 SET PAYEEID = :d WHERE PAYEEID = :s"),
            {"d": dest_id, "s": source_id},
        ).rowcount
        conn.execute(
            text(
                "DELETE FROM CUSTOMFIELDDATA_V1 WHERE REFID = :s AND FIELDID IN "
                "(SELECT FIELDID FROM CUSTOMFIELD_V1 WHERE REFTYPE = 'Payee')"
            ),
            {"s": source_id},
        )
        conn.execute(
            text("DELETE FROM ATTACHMENT_V1 WHERE REFTYPE = 'Payee' AND REFID = :s"),
            {"s": source_id},
        )
        conn.execute(text("DELETE FROM PAYEE_V1 WHERE PAYEEID = :id"), {"id": source_id})
    dest = get_payee(engine, dest_id)
    dest["merged_from"] = int(source_id)
    dest["updated_transactions"] = int(checking or 0)
    dest["updated_scheduled"] = int(bills or 0)
    return dest


def _payee_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _name(payload.get("name")),
        "categ_id": _categ_id(payload.get("categ_id")),
        "number": str(payload.get("number") or ""),
        "website": str(payload.get("website") or ""),
        "notes": str(payload.get("notes") or ""),
        "active": _active(payload.get("active"), 1),
        "pattern": str(payload.get("pattern") or ""),
    }


def _assert_unique_payee(conn: Connection, name: str, exclude: int | None = None) -> None:
    sql = "SELECT PAYEEID FROM PAYEE_V1 WHERE PAYEENAME = :n COLLATE NOCASE"
    params: dict[str, Any] = {"n": name}
    if exclude is not None:
        sql += " AND PAYEEID != :id"
        params["id"] = exclude
    if conn.execute(text(sql), params).fetchone():
        raise ManagerError("payee name already exists")


# --- Categories ---


def _category_map(conn: Connection) -> dict[int, dict[str, Any]]:
    rows = conn.execute(
        text("SELECT CATEGID, CATEGNAME, PARENTID, IFNULL(ACTIVE, 1) FROM CATEGORY_V1")
    ).fetchall()
    return {
        int(r[0]): {
            "categ_id": int(r[0]),
            "name": r[1],
            "parent_id": int(r[2]) if r[2] is not None and int(r[2]) > 0 else None,
            "active": int(r[3]),
        }
        for r in rows
    }


def list_categories_admin(engine: Engine, include_inactive: bool = True) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        by_id = _category_map(conn)
        used = {
            int(r[0]): int(r[1])
            for r in conn.execute(
                text(
                    """
                    SELECT CATEGID, COUNT(*) FROM (
                        SELECT CATEGID FROM CHECKINGACCOUNT_V1
                        UNION ALL SELECT CATEGID FROM SPLITTRANSACTIONS_V1
                        UNION ALL SELECT CATEGID FROM BILLSDEPOSITS_V1
                        UNION ALL SELECT CATEGID FROM BUDGETTABLE_V1
                        UNION ALL SELECT CATEGID FROM BUDGETSPLITTRANSACTIONS_V1
                        UNION ALL SELECT CATEGID FROM PAYEE_V1
                    ) AS u WHERE CATEGID IS NOT NULL AND CATEGID > 0
                    GROUP BY CATEGID
                    """
                )
            )
        }
        children = {}
        for item in by_id.values():
            pid = item["parent_id"]
            if pid:
                children[pid] = children.get(pid, 0) + 1
    out = []
    for item in by_id.values():
        if not include_inactive and item["active"] == 0:
            continue
        row = dict(item)
        row["path"] = _category_path(item["categ_id"], by_id)
        row["used_count"] = used.get(item["categ_id"], 0)
        row["child_count"] = children.get(item["categ_id"], 0)
        out.append(row)
    out.sort(key=lambda c: c["path"].lower())
    return out


def get_category(engine: Engine, categ_id: int) -> dict[str, Any]:
    rows = [c for c in list_categories_admin(engine) if c["categ_id"] == categ_id]
    if not rows:
        raise ManagerError(f"unknown category {categ_id}")
    return rows[0]


def create_category(engine: Engine, payload: dict[str, Any]) -> dict[str, Any]:
    name = _name(payload.get("name"))
    parent_id = _categ_id(payload.get("parent_id"))
    active = _active(payload.get("active"), 1)
    with engine.begin() as conn:
        if parent_id > 0:
            _assert_category(conn, parent_id)
        _assert_unique_category(conn, name, parent_id)
        cid = _next_id(conn, "CATEGORY_V1", "CATEGID")
        conn.execute(
            text(
                """
                INSERT INTO CATEGORY_V1 (CATEGID, CATEGNAME, ACTIVE, PARENTID)
                VALUES (:id, :name, :active, :pid)
                """
            ),
            {"id": cid, "name": name, "active": active, "pid": parent_id},
        )
    return get_category(engine, cid)


def update_category(engine: Engine, categ_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = _name(payload.get("name"))
    parent_id = _categ_id(payload.get("parent_id"))
    active = _active(payload.get("active"), 1)
    with engine.begin() as conn:
        _assert_category(conn, categ_id)
        if parent_id == categ_id:
            raise ManagerError("category cannot be its own parent")
        if parent_id > 0:
            _assert_category(conn, parent_id)
            if _is_descendant(conn, parent_id, categ_id):
                raise ManagerError("category cannot be nested under a descendant")
        _assert_unique_category(conn, name, parent_id, exclude=categ_id)
        conn.execute(
            text(
                """
                UPDATE CATEGORY_V1
                   SET CATEGNAME = :name, ACTIVE = :active, PARENTID = :pid
                 WHERE CATEGID = :id
                """
            ),
            {"id": categ_id, "name": name, "active": active, "pid": parent_id},
        )
    return get_category(engine, categ_id)


def set_category_active(engine: Engine, categ_id: int, active: bool) -> dict[str, Any]:
    with engine.begin() as conn:
        n = conn.execute(
            text("UPDATE CATEGORY_V1 SET ACTIVE = :a WHERE CATEGID = :id"),
            {"a": 1 if active else 0, "id": categ_id},
        ).rowcount
        if not n:
            raise ManagerError(f"unknown category {categ_id}")
    return get_category(engine, categ_id)


def delete_category(engine: Engine, categ_id: int) -> None:
    with engine.begin() as conn:
        _assert_category(conn, categ_id)
        kids = conn.execute(
            text("SELECT COUNT(*) FROM CATEGORY_V1 WHERE PARENTID = :id"),
            {"id": categ_id},
        ).scalar()
        if int(kids or 0):
            raise ManagerError("category has children")
        used = conn.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM CHECKINGACCOUNT_V1 WHERE CATEGID = :id)
                + (SELECT COUNT(*) FROM SPLITTRANSACTIONS_V1 WHERE CATEGID = :id)
                + (SELECT COUNT(*) FROM BILLSDEPOSITS_V1 WHERE CATEGID = :id)
                + (SELECT COUNT(*) FROM BUDGETTABLE_V1 WHERE CATEGID = :id)
                + (SELECT COUNT(*) FROM BUDGETSPLITTRANSACTIONS_V1 WHERE CATEGID = :id)
                + (SELECT COUNT(*) FROM PAYEE_V1 WHERE CATEGID = :id)
                """
            ),
            {"id": categ_id},
        ).scalar()
        if int(used or 0):
            raise ManagerError("category is in use")
        conn.execute(text("DELETE FROM CATEGORY_V1 WHERE CATEGID = :id"), {"id": categ_id})


def merge_categories(engine: Engine, source_id: int, dest_id: int) -> dict[str, Any]:
    if int(source_id) == int(dest_id):
        raise ManagerError("cannot merge a category into itself")
    with engine.begin() as conn:
        _assert_category(conn, source_id)
        _assert_category(conn, dest_id)
        if _is_descendant(conn, dest_id, source_id):
            raise ManagerError("cannot merge a category into one of its descendants")
        checking = conn.execute(
            text("UPDATE CHECKINGACCOUNT_V1 SET CATEGID = :d WHERE CATEGID = :s"),
            {"d": dest_id, "s": source_id},
        ).rowcount
        splits = conn.execute(
            text("UPDATE SPLITTRANSACTIONS_V1 SET CATEGID = :d WHERE CATEGID = :s"),
            {"d": dest_id, "s": source_id},
        ).rowcount
        bills = conn.execute(
            text("UPDATE BILLSDEPOSITS_V1 SET CATEGID = :d WHERE CATEGID = :s"),
            {"d": dest_id, "s": source_id},
        ).rowcount
        conn.execute(
            text("UPDATE BUDGETSPLITTRANSACTIONS_V1 SET CATEGID = :d WHERE CATEGID = :s"),
            {"d": dest_id, "s": source_id},
        )
        conn.execute(
            text("UPDATE BUDGETTABLE_V1 SET CATEGID = :d WHERE CATEGID = :s"),
            {"d": dest_id, "s": source_id},
        )
        conn.execute(
            text("UPDATE PAYEE_V1 SET CATEGID = :d WHERE CATEGID = :s"),
            {"d": dest_id, "s": source_id},
        )
        conn.execute(
            text("UPDATE CATEGORY_V1 SET PARENTID = :d WHERE PARENTID = :s"),
            {"d": dest_id, "s": source_id},
        )
        conn.execute(text("DELETE FROM CATEGORY_V1 WHERE CATEGID = :id"), {"id": source_id})
    dest = get_category(engine, dest_id)
    dest["merged_from"] = int(source_id)
    dest["updated_transactions"] = int(checking or 0) + int(splits or 0)
    dest["updated_scheduled"] = int(bills or 0)
    return dest


def _assert_category(conn: Connection, categ_id: int) -> None:
    if conn.execute(
        text("SELECT CATEGID FROM CATEGORY_V1 WHERE CATEGID = :id"), {"id": categ_id}
    ).fetchone() is None:
        raise ManagerError(f"unknown category {categ_id}")


def _assert_unique_category(
    conn: Connection, name: str, parent_id: int, exclude: int | None = None
) -> None:
    sql = """
        SELECT CATEGID FROM CATEGORY_V1
         WHERE CATEGNAME = :n COLLATE NOCASE AND PARENTID = :pid
    """
    params: dict[str, Any] = {"n": name, "pid": parent_id}
    if exclude is not None:
        sql += " AND CATEGID != :id"
        params["id"] = exclude
    if conn.execute(text(sql), params).fetchone():
        raise ManagerError("category name already exists under this parent")


def _is_descendant(conn: Connection, maybe_child: int, ancestor: int) -> bool:
    """True if maybe_child is nested under ancestor."""
    current = maybe_child
    seen: set[int] = set()
    while current and current > 0 and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        row = conn.execute(
            text("SELECT PARENTID FROM CATEGORY_V1 WHERE CATEGID = :id"),
            {"id": current},
        ).fetchone()
        if row is None:
            break
        current = int(row[0] or 0)
    return False


# --- Tags ---


def list_tags_admin(engine: Engine, include_inactive: bool = True) -> list[dict[str, Any]]:
    where = "" if include_inactive else "WHERE IFNULL(ACTIVE, 1) != 0"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT t.TAGID, t.TAGNAME, IFNULL(t.ACTIVE, 1),
                       (SELECT COUNT(*) FROM TAGLINK_V1 l WHERE l.TAGID = t.TAGID)
                  FROM TAG_V1 t
                  {where}
                 ORDER BY t.TAGNAME COLLATE NOCASE
                """
            )
        ).fetchall()
    return [
        {
            "tag_id": int(r[0]),
            "name": r[1],
            "active": int(r[2]),
            "used_count": int(r[3] or 0),
        }
        for r in rows
    ]


def get_tag(engine: Engine, tag_id: int) -> dict[str, Any]:
    rows = [t for t in list_tags_admin(engine) if t["tag_id"] == tag_id]
    if not rows:
        raise ManagerError(f"unknown tag {tag_id}")
    return rows[0]


def create_tag(engine: Engine, payload: dict[str, Any]) -> dict[str, Any]:
    name = _name(payload.get("name"))
    active = _active(payload.get("active"), 1)
    with engine.begin() as conn:
        _assert_unique_tag(conn, name)
        tid = _next_id(conn, "TAG_V1", "TAGID")
        conn.execute(
            text("INSERT INTO TAG_V1 (TAGID, TAGNAME, ACTIVE) VALUES (:id, :name, :a)"),
            {"id": tid, "name": name, "a": active},
        )
    return get_tag(engine, tid)


def update_tag(engine: Engine, tag_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = _name(payload.get("name"))
    active = _active(payload.get("active"), 1)
    with engine.begin() as conn:
        if conn.execute(
            text("SELECT TAGID FROM TAG_V1 WHERE TAGID = :id"), {"id": tag_id}
        ).fetchone() is None:
            raise ManagerError(f"unknown tag {tag_id}")
        _assert_unique_tag(conn, name, exclude=tag_id)
        conn.execute(
            text("UPDATE TAG_V1 SET TAGNAME = :name, ACTIVE = :a WHERE TAGID = :id"),
            {"id": tag_id, "name": name, "a": active},
        )
    return get_tag(engine, tag_id)


def set_tag_active(engine: Engine, tag_id: int, active: bool) -> dict[str, Any]:
    with engine.begin() as conn:
        n = conn.execute(
            text("UPDATE TAG_V1 SET ACTIVE = :a WHERE TAGID = :id"),
            {"a": 1 if active else 0, "id": tag_id},
        ).rowcount
        if not n:
            raise ManagerError(f"unknown tag {tag_id}")
    return get_tag(engine, tag_id)


def delete_tag(engine: Engine, tag_id: int) -> None:
    with engine.begin() as conn:
        used = conn.execute(
            text("SELECT COUNT(*) FROM TAGLINK_V1 WHERE TAGID = :id"), {"id": tag_id}
        ).scalar()
        if int(used or 0):
            raise ManagerError("tag is in use")
        n = conn.execute(text("DELETE FROM TAG_V1 WHERE TAGID = :id"), {"id": tag_id}).rowcount
        if not n:
            raise ManagerError(f"unknown tag {tag_id}")


def _assert_unique_tag(conn: Connection, name: str, exclude: int | None = None) -> None:
    sql = "SELECT TAGID FROM TAG_V1 WHERE TAGNAME = :n COLLATE NOCASE"
    params: dict[str, Any] = {"n": name}
    if exclude is not None:
        sql += " AND TAGID != :id"
        params["id"] = exclude
    if conn.execute(text(sql), params).fetchone():
        raise ManagerError("tag name already exists")


# --- Currencies ---


def list_currencies_admin(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        base = conn.execute(
            text("SELECT INFOVALUE FROM INFOTABLE_V1 WHERE INFONAME = 'BASECURRENCYID'")
        ).scalar()
        base_id = int(base) if base not in (None, "") else None
        rows = conn.execute(
            text(
                """
                SELECT CURRENCYID, CURRENCYNAME, PFX_SYMBOL, SFX_SYMBOL,
                       DECIMAL_POINT, GROUP_SEPARATOR, UNIT_NAME, CENT_NAME,
                       SCALE, BASECONVRATE, CURRENCY_SYMBOL, CURRENCY_TYPE,
                       (SELECT COUNT(*) FROM ACCOUNTLIST_V1 a WHERE a.CURRENCYID = c.CURRENCYID)
                       + (SELECT COUNT(*) FROM ASSETS_V1 s WHERE s.CURRENCYID = c.CURRENCYID)
                  FROM CURRENCYFORMATS_V1 c
                 ORDER BY CURRENCY_SYMBOL
                """
            )
        ).fetchall()
    out = []
    for r in rows:
        cid = int(r[0])
        out.append(
            {
                "currency_id": cid,
                "name": r[1],
                "pfx": r[2] or "",
                "sfx": r[3] or "",
                "decimal_point": r[4] or ".",
                "group_separator": r[5] or "",
                "unit_name": r[6] or "",
                "cent_name": r[7] or "",
                "scale": int(r[8] or 100),
                "rate": str(as_decimal(r[9])),
                "symbol": r[10],
                "currency_type": r[11] or "Fiat",
                "used_count": int(r[12] or 0),
                "is_base": base_id == cid,
            }
        )
    return out


def get_currency(engine: Engine, currency_id: int) -> dict[str, Any]:
    rows = [c for c in list_currencies_admin(engine) if c["currency_id"] == currency_id]
    if not rows:
        raise ManagerError(f"unknown currency {currency_id}")
    return rows[0]


def create_currency(engine: Engine, payload: dict[str, Any]) -> dict[str, Any]:
    data = _currency_fields(payload)
    with engine.begin() as conn:
        _assert_unique_currency(conn, data["name"], data["sym"])
        cid = _next_id(conn, "CURRENCYFORMATS_V1", "CURRENCYID")
        conn.execute(
            text(
                """
                INSERT INTO CURRENCYFORMATS_V1 (
                    CURRENCYID, CURRENCYNAME, PFX_SYMBOL, SFX_SYMBOL,
                    DECIMAL_POINT, GROUP_SEPARATOR, UNIT_NAME, CENT_NAME,
                    SCALE, BASECONVRATE, CURRENCY_SYMBOL, CURRENCY_TYPE
                ) VALUES (
                    :id, :name, :pfx, :sfx, :dec, :grp, :unit, :cent,
                    :scale, :rate, :sym, :typ
                )
                """
            ),
            {"id": cid, **data},
        )
    return get_currency(engine, cid)


def update_currency(engine: Engine, currency_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = _currency_fields(payload)
    with engine.begin() as conn:
        if conn.execute(
            text("SELECT CURRENCYID FROM CURRENCYFORMATS_V1 WHERE CURRENCYID = :id"),
            {"id": currency_id},
        ).fetchone() is None:
            raise ManagerError(f"unknown currency {currency_id}")
        _assert_unique_currency(conn, data["name"], data["sym"], exclude=currency_id)
        conn.execute(
            text(
                """
                UPDATE CURRENCYFORMATS_V1 SET
                    CURRENCYNAME = :name, PFX_SYMBOL = :pfx, SFX_SYMBOL = :sfx,
                    DECIMAL_POINT = :dec, GROUP_SEPARATOR = :grp,
                    UNIT_NAME = :unit, CENT_NAME = :cent, SCALE = :scale,
                    BASECONVRATE = :rate, CURRENCY_SYMBOL = :sym, CURRENCY_TYPE = :typ
                 WHERE CURRENCYID = :id
                """
            ),
            {"id": currency_id, **data},
        )
    return get_currency(engine, currency_id)


def delete_currency(engine: Engine, currency_id: int) -> None:
    with engine.begin() as conn:
        base = conn.execute(
            text("SELECT INFOVALUE FROM INFOTABLE_V1 WHERE INFONAME = 'BASECURRENCYID'")
        ).scalar()
        if base not in (None, "") and int(base) == currency_id:
            raise ManagerError("cannot delete the base currency")
        used = conn.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM ACCOUNTLIST_V1 WHERE CURRENCYID = :id)
                + (SELECT COUNT(*) FROM ASSETS_V1 WHERE CURRENCYID = :id)
                """
            ),
            {"id": currency_id},
        ).scalar()
        if int(used or 0):
            raise ManagerError("currency is in use")
        conn.execute(
            text("DELETE FROM CURRENCYHISTORY_V1 WHERE CURRENCYID = :id"), {"id": currency_id}
        )
        n = conn.execute(
            text("DELETE FROM CURRENCYFORMATS_V1 WHERE CURRENCYID = :id"), {"id": currency_id}
        ).rowcount
        if not n:
            raise ManagerError(f"unknown currency {currency_id}")


def _currency_fields(payload: dict[str, Any]) -> dict[str, Any]:
    name = _name(payload.get("name"))
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise ManagerError("symbol is required")
    ctype = str(payload.get("currency_type") or "Fiat")
    if ctype not in CURRENCY_TYPES:
        raise ManagerError("currency_type must be Fiat or Crypto")
    scale = int(payload.get("scale") or 100)
    if scale < 1:
        raise ManagerError("scale must be positive")
    rate = as_decimal(payload.get("rate") or 1)
    if rate <= 0:
        raise ManagerError("rate must be positive")
    decimal_point = str(payload.get("decimal_point") or ".")
    group_separator = str(payload.get("group_separator") or "")
    if decimal_point and group_separator and decimal_point == group_separator:
        raise ManagerError("decimal_point and group_separator must differ")
    return {
        "name": name,
        "pfx": str(payload.get("pfx") or ""),
        "sfx": str(payload.get("sfx") or ""),
        "dec": decimal_point,
        "grp": group_separator,
        "unit": str(payload.get("unit_name") or ""),
        "cent": str(payload.get("cent_name") or ""),
        "scale": scale,
        "rate": str(rate),
        "sym": symbol,
        "typ": ctype,
    }


def _assert_unique_currency(
    conn: Connection, name: str, symbol: str, exclude: int | None = None
) -> None:
    extra = " AND CURRENCYID != :id" if exclude is not None else ""
    params: dict[str, Any] = {"n": name, "s": symbol}
    if exclude is not None:
        params["id"] = exclude
    if conn.execute(
        text(f"SELECT CURRENCYID FROM CURRENCYFORMATS_V1 WHERE CURRENCYNAME = :n COLLATE NOCASE{extra}"),
        params,
    ).fetchone():
        raise ManagerError("currency name already exists")
    if conn.execute(
        text(
            f"SELECT CURRENCYID FROM CURRENCYFORMATS_V1 WHERE CURRENCY_SYMBOL = :s COLLATE NOCASE{extra}"
        ),
        params,
    ).fetchone():
        raise ManagerError("currency symbol already exists")
