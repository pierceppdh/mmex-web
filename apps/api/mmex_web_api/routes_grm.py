"""General Report Manager endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from mmex_domain.grm import (
    GrmError,
    delete_report,
    get_report,
    import_grm,
    list_reports,
    run_report,
)
from mmex_web_api.deps import get_compatible_engine, get_current_user, require_write

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


class RunIn(BaseModel):
    begin_date: str | None = None
    end_date: str | None = None
    single_date: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


def _http(exc: GrmError) -> HTTPException:
    msg = str(exc)
    code = 404 if msg.startswith("unknown") else 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/grm")
def grm_list(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return list_reports(engine)


@router.post("/grm/import")
async def grm_import(
    file: UploadFile = File(...),
    engine: Engine = Depends(require_write),
) -> dict[str, Any]:
    data = await file.read()
    try:
        return import_grm(engine, data, file.filename or "")
    except GrmError as exc:
        raise _http(exc) from exc


@router.get("/grm/{report_id}")
def grm_get(report_id: int, engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    try:
        return get_report(engine, report_id)
    except GrmError as exc:
        raise _http(exc) from exc


@router.post("/grm/{report_id}/run")
def grm_run(
    report_id: int, body: RunIn | None = None, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    payload = (body.model_dump() if body else {}) | ((body.extra if body else {}) or {})
    payload.pop("extra", None)
    try:
        return run_report(engine, report_id, payload)
    except GrmError as exc:
        raise _http(exc) from exc


@router.delete("/grm/{report_id}")
def grm_delete(report_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_report(engine, report_id)
    except GrmError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}
