"""Read-only inspection of an MMEX `.mmb` SQLite file."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from mmex_domain.version import INFO_KEYS, MAX_USER_VERSION, MIN_USER_VERSION


def inspect_mmex_file(db_path: Path) -> dict[str, Any]:
    """Return path metadata and a small INFOTABLE subset when the file exists."""
    resolved = db_path.resolve()
    info: dict[str, Any] = {
        "path": str(resolved),
        "exists": resolved.exists(),
        "size": None,
        "sqlite": False,
        "user_version": None,
        "min_user_version": MIN_USER_VERSION,
        "max_user_version": MAX_USER_VERSION,
        "info_table": {},
        "error": None,
    }
    if not resolved.exists():
        return info
    info["size"] = resolved.stat().st_size
    try:
        uri = f"file:{resolved}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            info["sqlite"] = True
            row = conn.execute("PRAGMA user_version").fetchone()
            info["user_version"] = row[0] if row else None
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "INFOTABLE_V1" in tables:
                placeholders = ",".join("?" * len(INFO_KEYS))
                pairs = conn.execute(
                    f"SELECT INFONAME, INFOVALUE FROM INFOTABLE_V1 "
                    f"WHERE INFONAME IN ({placeholders})",
                    INFO_KEYS,
                ).fetchall()
                info["info_table"] = {str(k): str(v) for k, v in pairs}
        finally:
            conn.close()
    except sqlite3.Error as exc:
        info["error"] = str(exc)
    return info
