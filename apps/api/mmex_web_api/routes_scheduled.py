"""Scheduled bills endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from mmex_domain.repeats import AUTO_MODES, REPEAT_TYPES
from mmex_domain.scheduled import (
    ScheduledError,
    create_scheduled,
    delete_scheduled,
    enter_scheduled,
    get_scheduled,
    list_scheduled,
    process_due_silent,
    skip_scheduled,
    update_scheduled,
)
from mmex_web_api.backup import backup_database
from mmex_web_api.config import Settings
from mmex_web_api.deps import (
    get_compatible_engine,
    get_settings,
    require_write,
)
from mmex_web_api.due_job import record_due_job

router = APIRouter(prefix="/api")


class SplitIn(BaseModel):
    categ_id: int
    amount: Decimal
    notes: str = ""


class ScheduledIn(BaseModel):
    account_id: int
    trans_code: Literal["Withdrawal", "Deposit", "Transfer"]
    trans_amount: Decimal
    next_occurrence_date: str
    payee_id: int | None = None
    to_account_id: int | None = None
    to_trans_amount: Decimal | None = None
    categ_id: int | None = None
    status: str = ""
    transaction_number: str = ""
    notes: str = ""
    color: int = -1
    followup_id: int = -1
    repeat_type: int = 0
    auto_mode: int = 0
    interval: int | None = None
    remaining: int | None = -1
    tag_ids: list[int] = Field(default_factory=list)
    splits: list[SplitIn] = Field(default_factory=list)


def _payload(body: ScheduledIn) -> dict[str, Any]:
    data = body.model_dump()
    data["splits"] = [s.model_dump() for s in body.splits]
    return data


def _http(exc: ScheduledError) -> HTTPException:
    msg = str(exc)
    code = 404 if msg.startswith("unknown") else 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/scheduled/meta")
def scheduled_meta() -> dict[str, Any]:
    return {
        "repeat_types": [
            {"id": i, "key": k, "label_fr": fr, "label_en": en} for i, k, fr, en in REPEAT_TYPES
        ],
        "auto_modes": [
            {"id": i, "key": k, "label_fr": fr, "label_en": en} for i, k, fr, en in AUTO_MODES
        ],
    }


@router.get("/scheduled")
def scheduled_list(
    request: Request,
    engine: Engine = Depends(get_compatible_engine),
) -> dict[str, Any]:
    body = list_scheduled(engine)
    body["due_job"] = request.app.state.mmex.due_job
    return body


@router.post("/scheduled/process-due")
def scheduled_process_due(
    request: Request,
    engine: Engine = Depends(require_write),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    backup_database(settings.db_path, settings.backups_dir, keep=settings.backup_keep)
    try:
        result = process_due_silent(engine)
    except Exception as exc:
        record_due_job(request.app.state.mmex, error=str(exc))
        raise
    record_due_job(request.app.state.mmex, result)
    return result


@router.get("/scheduled/{bd_id}")
def scheduled_get(bd_id: int, engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    try:
        return get_scheduled(engine, bd_id)
    except ScheduledError as exc:
        raise _http(exc) from exc


@router.post("/scheduled")
def scheduled_create(body: ScheduledIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_scheduled(engine, _payload(body))
    except ScheduledError as exc:
        raise _http(exc) from exc


@router.put("/scheduled/{bd_id}")
def scheduled_update(
    bd_id: int, body: ScheduledIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_scheduled(engine, bd_id, _payload(body))
    except ScheduledError as exc:
        raise _http(exc) from exc


@router.delete("/scheduled/{bd_id}")
def scheduled_delete(bd_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_scheduled(engine, bd_id)
    except ScheduledError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}


@router.post("/scheduled/{bd_id}/enter")
def scheduled_enter(bd_id: int, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return enter_scheduled(engine, bd_id)
    except ScheduledError as exc:
        raise _http(exc) from exc


@router.post("/scheduled/{bd_id}/skip")
def scheduled_skip(bd_id: int, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return skip_scheduled(engine, bd_id)
    except ScheduledError as exc:
        raise _http(exc) from exc
