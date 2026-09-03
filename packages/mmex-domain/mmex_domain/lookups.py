"""Payees, nested categories, and tags."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine


def list_payees(engine: Engine, query: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    sql = """
        SELECT PAYEEID, PAYEENAME, CATEGID, IFNULL(ACTIVE, 1), IFNULL(PATTERN, '')
          FROM PAYEE_V1
         WHERE IFNULL(ACTIVE, 1) != 0
    """
    params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
    if query and query.strip():
        sql += " AND PAYEENAME LIKE :q COLLATE NOCASE"
        params["q"] = f"%{query.strip()}%"
    sql += " ORDER BY PAYEENAME LIMIT :limit"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [
        {
            "payee_id": int(r[0]),
            "name": r[1],
            "categ_id": int(r[2]) if r[2] is not None else None,
            "active": int(r[3]),
            "pattern": r[4] or "",
        }
        for r in rows
    ]


def list_categories(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT CATEGID, CATEGNAME, PARENTID, ACTIVE
                  FROM CATEGORY_V1
                 ORDER BY CATEGNAME
                """
            )
        ).fetchall()
    by_id = {
        int(r[0]): {
            "categ_id": int(r[0]),
            "name": r[1],
            "parent_id": int(r[2]) if r[2] is not None and int(r[2]) > 0 else None,
            "active": int(r[3] or 1),
        }
        for r in rows
    }
    out: list[dict[str, Any]] = []
    for item in by_id.values():
        if item["active"] == 0:
            continue
        item = dict(item)
        item["path"] = _category_path(item["categ_id"], by_id)
        out.append(item)
    out.sort(key=lambda c: c["path"].lower())
    return out


def _category_path(categ_id: int, by_id: dict[int, dict[str, Any]]) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    current: int | None = categ_id
    while current and current in by_id and current not in seen:
        seen.add(current)
        node = by_id[current]
        parts.append(node["name"])
        current = node["parent_id"]
    return " : ".join(reversed(parts))


def list_tags(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT TAGID, TAGNAME, ACTIVE
                  FROM TAG_V1
                 WHERE IFNULL(ACTIVE, 1) != 0
                 ORDER BY TAGNAME
                """
            )
        ).fetchall()
    return [{"tag_id": int(r[0]), "name": r[1]} for r in rows]
