"""Budget years, entries, cash-flow."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from mmex_domain.budgets import (
    BudgetError,
    cashflow,
    create_year,
    delete_entry,
    delete_year,
    get_year,
    list_years,
    period_meta,
    upsert_entry,
)
from mmex_web_api.deps import get_compatible_engine, get_current_user, require_write

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


class YearIn(BaseModel):
    name: str
    copy_from_id: int | None = None


class EntryIn(BaseModel):
    categ_id: int
    period: str = "Monthly"
    amount: Decimal
    notes: str = ""
    active: int = 1


def _http(exc: BudgetError) -> HTTPException:
    msg = str(exc)
    code = 404 if msg.startswith("unknown") else 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/budgets/meta")
def budgets_meta() -> dict[str, Any]:
    return {"periods": period_meta()}


@router.get("/budgets/cashflow")
def budgets_cashflow(
    months: int = 12, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    return cashflow(engine, months=months)


@router.get("/budgets")
def budgets_list(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return list_years(engine)


@router.post("/budgets")
def budgets_create(body: YearIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_year(engine, body.model_dump())
    except BudgetError as exc:
        raise _http(exc) from exc


@router.get("/budgets/{year_id}")
def budgets_get(year_id: int, engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    try:
        return get_year(engine, year_id)
    except BudgetError as exc:
        raise _http(exc) from exc


@router.delete("/budgets/{year_id}")
def budgets_delete(year_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_year(engine, year_id)
    except BudgetError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}


@router.put("/budgets/{year_id}/entries")
def budgets_upsert_entry(
    year_id: int, body: EntryIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return upsert_entry(engine, year_id, body.model_dump())
    except BudgetError as exc:
        raise _http(exc) from exc


@router.delete("/budgets/{year_id}/entries/{categ_id}")
def budgets_delete_entry(
    year_id: int, categ_id: int, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return delete_entry(engine, year_id, categ_id)
    except BudgetError as exc:
        raise _http(exc) from exc
