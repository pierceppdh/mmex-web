"""SQLAlchemy engine for the mounted `.mmb` file."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from mmex_web_api.sqliteutil import configure_sqlite_connection


def make_engine(db_path: Path) -> Engine:
    uri = f"sqlite:///{db_path.resolve()}"
    engine = create_engine(
        uri,
        connect_args={"timeout": 30, "check_same_thread": False},
    )
    event.listen(engine, "connect", configure_sqlite_connection)
    return engine
