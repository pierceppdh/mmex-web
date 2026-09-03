"""SETTING_V1 key/value helpers for web-only options."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


def kv_get(conn: Connection, name: str) -> str | None:
    row = conn.execute(
        text("SELECT SETTINGVALUE FROM SETTING_V1 WHERE SETTINGNAME = :n"),
        {"n": name},
    ).fetchone()
    return str(row[0]) if row else None


def kv_set(conn: Connection, name: str, value: str) -> None:
    existing = conn.execute(
        text("SELECT SETTINGID FROM SETTING_V1 WHERE SETTINGNAME = :n"),
        {"n": name},
    ).fetchone()
    if existing:
        conn.execute(
            text("UPDATE SETTING_V1 SET SETTINGVALUE = :v WHERE SETTINGNAME = :n"),
            {"v": value, "n": name},
        )
        return
    next_id = int(conn.execute(text("SELECT COALESCE(MAX(SETTINGID), 0) FROM SETTING_V1")).scalar() or 0) + 1
    conn.execute(
        text(
            "INSERT INTO SETTING_V1 (SETTINGID, SETTINGNAME, SETTINGVALUE) "
            "VALUES (:id, :n, :v)"
        ),
        {"id": next_id, "n": name, "v": value},
    )


def kv_get_engine(engine: Engine, name: str) -> str | None:
    with engine.connect() as conn:
        return kv_get(conn, name)


THEME_KEY = "MMEXWEB_THEME"
SHOW_CLOSED_KEY = "MMEXWEB_SHOW_CLOSED"
DEFAULT_ACCOUNT_KEY = "MMEXWEB_DEFAULT_ACCOUNT"
THEMES = ("system", "light", "dark")


def web_prefs(engine: Engine) -> dict[str, object]:
    with engine.connect() as conn:
        theme = (kv_get(conn, THEME_KEY) or "system").strip().lower()
        if theme not in THEMES:
            theme = "system"
        closed_raw = (kv_get(conn, SHOW_CLOSED_KEY) or "FALSE").strip().upper()
        default_raw = kv_get(conn, DEFAULT_ACCOUNT_KEY)
    default_id: int | None = None
    if default_raw:
        try:
            value = int(default_raw)
            if value > 0:
                default_id = value
        except ValueError:
            default_id = None
    return {
        "theme": theme,
        "show_closed_accounts": closed_raw in ("TRUE", "1", "YES", "ON"),
        "default_account_id": default_id,
    }


def save_web_prefs(engine: Engine, data: dict[str, object]) -> dict[str, object]:
    with engine.begin() as conn:
        if "theme" in data and data["theme"] is not None:
            theme = str(data["theme"]).strip().lower()
            if theme not in THEMES:
                raise ValueError("invalid theme")
            kv_set(conn, THEME_KEY, theme)
        if "show_closed_accounts" in data and data["show_closed_accounts"] is not None:
            flag = data["show_closed_accounts"]
            truthy = flag is True or str(flag).strip().upper() in ("TRUE", "1", "YES", "ON")
            kv_set(conn, SHOW_CLOSED_KEY, "TRUE" if truthy else "FALSE")
        if "default_account_id" in data:
            raw = data["default_account_id"]
            if raw in (None, "", 0, "0"):
                kv_set(conn, DEFAULT_ACCOUNT_KEY, "")
            else:
                aid = int(raw)  # type: ignore[arg-type]
                if aid < 0:
                    raise ValueError("invalid default_account_id")
                if aid > 0:
                    exists = conn.execute(
                        text("SELECT ACCOUNTID FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id"),
                        {"id": aid},
                    ).fetchone()
                    if exists is None:
                        raise ValueError(f"unknown account {aid}")
                kv_set(conn, DEFAULT_ACCOUNT_KEY, str(aid) if aid > 0 else "")
    return web_prefs(engine)
