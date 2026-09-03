"""Ledger options and currency history."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from mmex_domain.settings import (
    SettingsError,
    delete_rate,
    get_settings,
    list_rate_history,
    set_base_currency,
    update_settings,
    upsert_rate,
)
from mmex_web_api.deps import get_compatible_engine, get_current_user, require_write

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


class SettingsIn(BaseModel):
    username: str | None = None
    date_format: str | None = None
    delimiter: str | None = None
    use_currency_history: bool | None = None
    financial_year_start_day: int | None = None
    financial_year_start_month: int | None = None
    stock_url: str | None = None
    categ_delimiter: str | None = None
    share_precision: int | None = None
    theme: str | None = None
    show_closed_accounts: bool | None = None
    default_account_id: int | None = None


class BaseCurrencyIn(BaseModel):
    currency_id: int


class RateIn(BaseModel):
    date: str
    rate: str
    update_current: bool = True


def _http(exc: SettingsError) -> HTTPException:
    msg = str(exc)
    if msg.startswith("unknown"):
        code = 404
    else:
        code = 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/settings")
def settings_get(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return get_settings(engine)


@router.put("/settings")
def settings_put(body: SettingsIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    payload = body.model_dump(exclude_unset=True)
    try:
        return update_settings(engine, payload)
    except SettingsError as exc:
        raise _http(exc) from exc


@router.put("/settings/base-currency")
def settings_base(body: BaseCurrencyIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return set_base_currency(engine, body.currency_id)
    except SettingsError as exc:
        raise _http(exc) from exc


@router.get("/currencies/{currency_id}/history")
def currency_history(
    currency_id: int, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    try:
        return list_rate_history(engine, currency_id)
    except SettingsError as exc:
        raise _http(exc) from exc


@router.post("/currencies/{currency_id}/history")
def currency_history_add(
    currency_id: int, body: RateIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return upsert_rate(
            engine,
            currency_id,
            rate=body.rate,
            rate_date=body.date,
            update_current=body.update_current,
        )
    except SettingsError as exc:
        raise _http(exc) from exc


@router.delete("/currencies/{currency_id}/history/{hist_id}")
def currency_history_delete(
    currency_id: int, hist_id: int, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return delete_rate(engine, currency_id, hist_id)
    except SettingsError as exc:
        raise _http(exc) from exc
