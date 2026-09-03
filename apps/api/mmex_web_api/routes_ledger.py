"""Ledger endpoints (schema, dashboard, accounts, statement, saved views)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from mmex_domain.accounts import (
    AccountError,
    create_account,
    delete_account,
    load_account,
    update_account,
    update_statement,
)
from mmex_domain.balances import account_rows, list_currencies
from mmex_domain.version import read_schema_status
from mmex_domain.views import ViewError, create_view, delete_view, list_views, update_view
from mmex_web_api.deps import (
    get_compatible_engine,
    get_current_user,
    get_engine,
    require_write,
)

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


@router.get("/schema")
def schema(engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    return read_schema_status(engine).to_dict()


@router.get("/dashboard")
def dashboard(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    status = read_schema_status(engine)
    payload = account_rows(engine)
    payload["schema"] = status.to_dict()
    return payload


@router.get("/accounts")
def accounts(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    payload = account_rows(engine)
    return {"accounts": payload["accounts"], "groups": payload["groups"]}


@router.get("/currencies")
def currencies(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return {"currencies": list_currencies(engine)}


class AccountIn(BaseModel):
    name: str
    account_type: str = "Checking"
    account_num: str = ""
    status: str = "Open"
    notes: str = ""
    held_at: str = ""
    website: str = ""
    contact_info: str = ""
    access_info: str = ""
    initial_bal: str | float | int = 0
    initial_date: str | None = None
    favorite: bool = False
    currency_id: int = 0
    statement_locked: bool = False
    statement_date: str | None = None
    credit_limit: str | float | int = 0
    minimum_balance: str | float | int = 0
    interest_rate: str | float | int = 0
    payment_due_date: str | None = None
    minimum_payment: str | float | int = 0


class StatementIn(BaseModel):
    statement_locked: bool = False
    statement_date: str | None = None
    credit_limit: str | float | int = 0
    minimum_balance: str | float | int = 0
    interest_rate: str | float | int = 0
    payment_due_date: str | None = None
    minimum_payment: str | float | int = 0


class ViewIn(BaseModel):
    name: str
    account_id: int | None = None
    filter: dict[str, Any] = Field(default_factory=dict)


def _acct_http(exc: AccountError | ViewError) -> HTTPException:
    msg = str(exc)
    if msg.startswith("unknown"):
        code = 404
    elif "in use" in msg:
        code = 409
    else:
        code = 400
    return HTTPException(status_code=code, detail=msg)


@router.post("/accounts")
def account_create(body: AccountIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_account(engine, body.model_dump())
    except AccountError as exc:
        raise _acct_http(exc) from exc


@router.get("/accounts/{account_id}")
def account_get(account_id: int, engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    item = load_account(engine, account_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown account {account_id}")
    return item


@router.put("/accounts/{account_id}")
def account_put(
    account_id: int, body: AccountIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_account(engine, account_id, body.model_dump())
    except AccountError as exc:
        raise _acct_http(exc) from exc


@router.delete("/accounts/{account_id}")
def account_delete(account_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_account(engine, account_id)
    except AccountError as exc:
        raise _acct_http(exc) from exc
    return {"status": "deleted"}


@router.put("/accounts/{account_id}/statement")
def account_statement(
    account_id: int, body: StatementIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_statement(engine, account_id, body.model_dump())
    except AccountError as exc:
        raise _acct_http(exc) from exc


@router.get("/views")
def views_list(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return {"views": list_views(engine)}


@router.post("/views")
def views_create(body: ViewIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_view(engine, body.model_dump())
    except ViewError as exc:
        raise _acct_http(exc) from exc


@router.put("/views/{view_id}")
def views_update(
    view_id: int, body: ViewIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_view(engine, view_id, body.model_dump())
    except ViewError as exc:
        raise _acct_http(exc) from exc


@router.delete("/views/{view_id}")
def views_delete(view_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_view(engine, view_id)
    except ViewError as exc:
        raise _acct_http(exc) from exc
    return {"status": "deleted"}
