"""Saved register views in SETTING_V1 (JSON blob, French-first names in the UI)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.filters import parse_filter

SETTING_NAME = "MMEXWEB_SAVED_VIEWS"


class ViewError(ValueError):
    """Invalid saved view."""


def _load_raw(conn: Connection) -> list[dict[str, Any]]:
    row = conn.execute(
        text("SELECT SETTINGVALUE FROM SETTING_V1 WHERE SETTINGNAME = :n"),
        {"n": SETTING_NAME},
    ).fetchone()
    if row is None or not row[0]:
        return []
    try:
        data = json.loads(row[0])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _write(conn: Connection, views: list[dict[str, Any]]) -> None:
    payload = json.dumps(views, ensure_ascii=False)
    exists = conn.execute(
        text("SELECT SETTINGID FROM SETTING_V1 WHERE SETTINGNAME = :n"),
        {"n": SETTING_NAME},
    ).fetchone()
    if exists is None:
        next_id = int(conn.execute(text("SELECT COALESCE(MAX(SETTINGID), 0) FROM SETTING_V1")).scalar() or 0) + 1
        conn.execute(
            text(
                "INSERT INTO SETTING_V1 (SETTINGID, SETTINGNAME, SETTINGVALUE) "
                "VALUES (:id, :n, :v)"
            ),
            {"id": next_id, "n": SETTING_NAME, "v": payload},
        )
    else:
        conn.execute(
            text("UPDATE SETTING_V1 SET SETTINGVALUE = :v WHERE SETTINGNAME = :n"),
            {"v": payload, "n": SETTING_NAME},
        )


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or "").strip()
    if not name:
        raise ViewError("name is required")
    account_id = item.get("account_id")
    if account_id in (None, "", 0, -1):
        account_id = None
    else:
        account_id = int(account_id)
    return {
        "id": int(item["id"]),
        "name": name,
        "account_id": account_id,
        "filter": parse_filter(item.get("filter") or {}),
    }


def list_views(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [_normalize(v) for v in _load_raw(conn) if v.get("id") and v.get("name")]


def create_view(engine: Engine, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        views = _load_raw(conn)
        next_id = max((int(v.get("id") or 0) for v in views), default=0) + 1
        item = _normalize({**payload, "id": next_id})
        views.append(item)
        _write(conn, views)
    return item


def update_view(engine: Engine, view_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        views = _load_raw(conn)
        found = None
        out: list[dict[str, Any]] = []
        for v in views:
            if int(v.get("id") or 0) == view_id:
                found = _normalize({**payload, "id": view_id})
                out.append(found)
            else:
                out.append(v)
        if found is None:
            raise ViewError(f"unknown view {view_id}")
        _write(conn, out)
    return found


def delete_view(engine: Engine, view_id: int) -> None:
    with engine.begin() as conn:
        views = _load_raw(conn)
        kept = [v for v in views if int(v.get("id") or 0) != view_id]
        if len(kept) == len(views):
            raise ViewError(f"unknown view {view_id}")
        _write(conn, kept)
