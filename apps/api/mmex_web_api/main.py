"""FastAPI entry: health, lock, backup, SPA."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Thread
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from starlette.middleware.sessions import SessionMiddleware

from mmex_domain.schema_info import inspect_mmex_file
from mmex_domain.version import read_schema_status
from mmex_web_api.auth import AuthStore, resolve_secret_key
from mmex_web_api.backup import backup_database, latest_backup
from mmex_web_api.config import Settings, load_settings
from mmex_web_api.db import make_engine
from mmex_web_api.lock import WriterLock
from mmex_web_api.routes_auth import router as auth_router
from mmex_web_api.routes_ledger import router as ledger_router
from mmex_web_api.routes_managers import router as managers_router
from mmex_web_api.routes_attachments import router as attachments_router
from mmex_web_api.routes_scheduled import router as scheduled_router
from mmex_web_api.routes_budgets import router as budgets_router
from mmex_web_api.routes_reports import router as reports_router
from mmex_web_api.routes_grm import router as grm_router
from mmex_web_api.routes_investments import router as investments_router
from mmex_web_api.routes_custom_fields import router as custom_fields_router
from mmex_web_api.routes_io import router as io_router
from mmex_web_api.routes_settings import router as settings_router
from mmex_web_api.routes_lock import router as lock_router
from mmex_web_api.routes_quickadd import router as quickadd_router
from mmex_web_api.routes_transactions import router as transactions_router
from mmex_web_api.routes_recon import router as recon_router

APP_VERSION = "1.14.3"


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = WriterLock(settings.lock_path, settings.mmex_lock_holder)
        self.last_backup: Path | None = None
        self.engine: Engine | None = None
        self.auth = AuthStore(settings)
        self.recon_sessions: dict[str, dict[str, Any]] = {}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for path in (
            settings.mmex_data_dir,
            settings.attachments_dir,
            settings.backups_dir,
        ):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        state.last_backup = backup_database(
            settings.db_path, settings.backups_dir, keep=settings.backup_keep
        )
        state.lock.acquire()
        if settings.db_path.is_file():
            state.engine = make_engine(settings.db_path)
        app.state.mmex = state
        stop = Event()

        def _due_loop() -> None:
            from mmex_domain.scheduled import process_due_silent

            if state.engine is not None and not state.lock.read_only:
                try:
                    backup_database(settings.db_path, settings.backups_dir, keep=settings.backup_keep)
                    process_due_silent(state.engine)
                except Exception:
                    pass
            while not stop.wait(3600):
                if state.engine is None or state.lock.read_only:
                    continue
                try:
                    backup_database(settings.db_path, settings.backups_dir, keep=settings.backup_keep)
                    process_due_silent(state.engine)
                except Exception:
                    pass

        worker = Thread(target=_due_loop, name="mmex-due-job", daemon=True)
        worker.start()
        try:
            yield
        finally:
            stop.set()
            if state.engine is not None:
                state.engine.dispose()
                state.engine = None
            state.lock.release()

    docs_url = "/docs" if settings.enable_openapi else None
    app = FastAPI(
        title="MMEX Web",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url="/redoc" if settings.enable_openapi else None,
        openapi_url="/openapi.json" if settings.enable_openapi else None,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolve_secret_key(settings),
        session_cookie="mmex_session",
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    app.include_router(auth_router)
    app.include_router(ledger_router)
    app.include_router(transactions_router)
    app.include_router(managers_router)
    app.include_router(attachments_router)
    app.include_router(scheduled_router)
    app.include_router(budgets_router)
    app.include_router(reports_router)
    app.include_router(grm_router)
    app.include_router(investments_router)
    app.include_router(custom_fields_router)
    app.include_router(io_router)
    app.include_router(settings_router)
    app.include_router(lock_router)
    app.include_router(quickadd_router)
    app.include_router(recon_router)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        db = inspect_mmex_file(settings.db_path)
        lock = state.lock.status()
        status = "ok"
        if not db["exists"]:
            status = "degraded"
        if db.get("error"):
            status = "error"
        schema = None
        if state.engine is not None:
            schema = read_schema_status(state.engine).to_dict()
            if not schema["ok"] and status == "ok":
                status = "degraded"
        return {
            "status": status,
            "version": APP_VERSION,
            "db": db,
            "schema": schema,
            "lock": lock,
            "last_backup": latest_backup(settings.backups_dir),
            "paperless": {
                "configured": bool(settings.paperless_url and settings.paperless_token),
                "url": settings.paperless_url or None,
                "inbox_tag": settings.paperless_inbox_tag,
            },
        }

    @app.get("/api/info")
    def info() -> dict[str, Any]:
        return {
            "name": "MMEX Web",
            "version": APP_VERSION,
            "locale_default": settings.locale_default,
        }

    static_dir = settings.resolved_static_dir()
    if static_dir is not None:
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str) -> FileResponse:
            candidate = (static_dir / full_path).resolve()
            if (
                full_path
                and candidate.is_file()
                and str(candidate).startswith(str(static_dir.resolve()))
            ):
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
