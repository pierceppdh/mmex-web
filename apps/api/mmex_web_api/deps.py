"""Request dependencies."""

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.engine import Engine

from mmex_domain.version import SchemaError, require_schema
from mmex_web_api.auth import SESSION_USER_KEY
from mmex_web_api.backup import backup_database
from mmex_web_api.config import Settings


def get_current_user(request: Request) -> str:
    user = request.session.get(SESSION_USER_KEY)
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def get_engine(request: Request) -> Engine:
    engine: Engine | None = getattr(request.app.state.mmex, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Aucune base MMEX n’est ouverte")
    return engine


def get_compatible_engine(request: Request) -> Engine:
    engine = get_engine(request)
    try:
        require_schema(engine)
    except SchemaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return engine


def require_write(request: Request) -> Engine:
    engine = get_compatible_engine(request)
    state = request.app.state.mmex
    if state.lock.read_only:
        raise HTTPException(status_code=423, detail="database is read-only")
    dest = backup_database(
        state.settings.db_path,
        state.settings.backups_dir,
        keep=state.settings.backup_keep,
    )
    if dest is not None:
        state.last_backup = dest
    return engine


def get_settings(request: Request) -> Settings:
    return request.app.state.mmex.settings
