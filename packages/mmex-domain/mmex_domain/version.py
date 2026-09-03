"""MMEX database version gate.

`PRAGMA user_version` is the upgrade number (v19 tags, v20 TRANSDATE, v21 currencies).
`INFOTABLE.DATAVERSION` is a separate legacy key (often still `3`) and is not the gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, inspect, text
from sqlalchemy.engine import Engine

from mmex_domain.models import MAPPED_TABLES

# Documented public schema is v19; live MMEX 1.9.2/1.9.3 files are v21.
MIN_USER_VERSION = 19
MAX_USER_VERSION = 21

REQUIRED_TABLES = frozenset(cls.__tablename__ for cls in MAPPED_TABLES)

INFO_KEYS = ("DATAVERSION", "MMEXVERSION", "BASECURRENCYID", "BASECURRENCYNAME", "USERNAME")


class SchemaError(Exception):
    """Incompatible or unreadable MMEX database."""


@dataclass(frozen=True)
class SchemaStatus:
    ok: bool
    user_version: int | None
    info: dict[str, str]
    missing_tables: tuple[str, ...]
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "user_version": self.user_version,
            "min_user_version": MIN_USER_VERSION,
            "max_user_version": MAX_USER_VERSION,
            "info": dict(self.info),
            "missing_tables": list(self.missing_tables),
            "error": self.error,
        }


def read_schema_status(engine: Engine) -> SchemaStatus:
    with engine.connect() as conn:
        user_version = conn.execute(text("PRAGMA user_version")).scalar()
        present = set(inspect(engine).get_table_names())
        missing = tuple(sorted(REQUIRED_TABLES - present))
        info: dict[str, str] = {}
        if "INFOTABLE_V1" in present:
            stmt = text(
                "SELECT INFONAME, INFOVALUE FROM INFOTABLE_V1 "
                "WHERE INFONAME IN :names"
            ).bindparams(bindparam("names", expanding=True))
            rows = conn.execute(stmt, {"names": list(INFO_KEYS)})
            info = {str(k): str(v) for k, v in rows}

    error: str | None = None
    if user_version is None:
        error = "PRAGMA user_version is missing"
    elif int(user_version) < MIN_USER_VERSION:
        error = (
            f"MMEX database version {user_version} is older than "
            f"{MIN_USER_VERSION}; upgrade it in desktop MMEX first"
        )
    elif int(user_version) > MAX_USER_VERSION:
        error = (
            f"MMEX database version {user_version} is newer than "
            f"{MAX_USER_VERSION}; this build of MMEX Web cannot open it"
        )
    elif missing:
        error = "missing tables: " + ", ".join(missing)

    return SchemaStatus(
        ok=error is None,
        user_version=int(user_version) if user_version is not None else None,
        info=info,
        missing_tables=missing,
        error=error,
    )


def require_schema(engine: Engine) -> SchemaStatus:
    status = read_schema_status(engine)
    if not status.ok:
        raise SchemaError(status.error or "incompatible schema")
    return status
