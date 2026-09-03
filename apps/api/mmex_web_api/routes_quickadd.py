"""Phone capture and PHP WebApp sidecar ingest."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from mmex_domain.quickadd import QuickaddError, add_quick, default_account_id, last_account_id
from mmex_domain.transactions import TransactionError
from mmex_domain.webapp import WebappError, import_sidecar, list_pending, sidecar_status
from mmex_web_api.backup import backup_database
from mmex_web_api.config import Settings
from mmex_web_api.deps import get_compatible_engine, get_current_user, get_settings, require_write

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


class QuickIn(BaseModel):
    account_id: int
    trans_code: Literal["Withdrawal", "Deposit", "Transfer"] = "Withdrawal"
    trans_amount: str
    trans_date: str
    payee_id: int | None = None
    payee_name: str = ""
    categ_id: int | None = None
    category: str = ""
    to_account_id: int | None = None
    to_trans_amount: str | None = None
    status: str = ""
    notes: str = ""


def _http(exc: Exception) -> HTTPException:
    msg = str(exc)
    if msg.startswith("unknown"):
        return HTTPException(status_code=404, detail=msg)
    if "locked" in msg:
        return HTTPException(status_code=423, detail=msg)
    return HTTPException(status_code=400, detail=msg)


@router.get("/quickadd")
def quickadd_meta(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return {
        "last_account_id": last_account_id(engine),
        "default_account_id": default_account_id(engine),
    }


@router.post("/quickadd")
def quickadd_post(body: QuickIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return add_quick(engine, body.model_dump())
    except (QuickaddError, TransactionError) as exc:
        raise _http(exc) from exc


@router.get("/webapp")
def webapp_get(
    engine: Engine = Depends(get_compatible_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    path = settings.resolved_webapp_db()
    status = sidecar_status(path)
    pending: list[dict[str, Any]] = []
    if status["exists"]:
        try:
            pending = list_pending(path)  # type: ignore[arg-type]
        except WebappError:
            pending = []
    status["rows"] = pending[:50]
    status["last_account_id"] = last_account_id(engine)
    return status


class WebappIn(BaseModel):
    dry_run: bool = True
    delete_imported: bool = False


def _run_import(engine: Engine, settings: Settings, path: Path, dry_run: bool, delete_imported: bool) -> dict[str, Any]:
    if not dry_run:
        backup_database(settings.db_path, settings.backups_dir, keep=settings.backup_keep)
    return import_sidecar(engine, path, dry_run=dry_run, delete_imported=delete_imported)


@router.post("/webapp/import")
def webapp_import(
    body: WebappIn | None = None,
    engine: Engine = Depends(require_write),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    opts = body or WebappIn()
    path = settings.resolved_webapp_db()
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="webapp sidecar is missing")
    try:
        return _run_import(engine, settings, path, opts.dry_run, opts.delete_imported)
    except WebappError as exc:
        raise _http(exc) from exc


@router.post("/webapp/upload")
def webapp_upload(
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    delete_imported: bool = Form(False),
    engine: Engine = Depends(require_write),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    tmp = settings.mmex_data_dir / "_webapp_upload.db"
    tmp.write_bytes(file.file.read())
    try:
        return _run_import(engine, settings, tmp, dry_run, delete_imported)
    except WebappError as exc:
        raise _http(exc) from exc
    finally:
        tmp.unlink(missing_ok=True)
