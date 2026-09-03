"""Payee, category, tag, and currency managers."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from mmex_domain.managers import (
    ManagerError,
    create_category,
    create_currency,
    create_payee,
    create_tag,
    delete_category,
    delete_currency,
    delete_payee,
    delete_tag,
    merge_categories,
    merge_payees,
    get_payee,
    list_categories_admin,
    list_currencies_admin,
    list_payees_admin,
    list_tags_admin,
    set_category_active,
    set_payee_active,
    set_tag_active,
    update_category,
    update_currency,
    update_payee,
    update_tag,
)
from mmex_web_api.deps import get_compatible_engine, get_current_user, require_write

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


class PayeeIn(BaseModel):
    name: str
    categ_id: int | None = None
    number: str = ""
    website: str = ""
    notes: str = ""
    active: int = 1
    pattern: str = ""


class CategoryIn(BaseModel):
    name: str
    parent_id: int | None = None
    active: int = 1


class TagIn(BaseModel):
    name: str
    active: int = 1


class CurrencyIn(BaseModel):
    name: str
    symbol: str
    pfx: str = ""
    sfx: str = ""
    decimal_point: str = "."
    group_separator: str = " "
    unit_name: str = ""
    cent_name: str = ""
    scale: int = 100
    rate: str = "1"
    currency_type: Literal["Fiat", "Crypto"] = "Fiat"


class ActiveIn(BaseModel):
    active: bool = Field(...)


class MergeIn(BaseModel):
    into_id: int


def _http(exc: ManagerError) -> HTTPException:
    msg = str(exc)
    if msg.startswith("unknown"):
        code = 404
    elif "in use" in msg or "has children" in msg or "cannot delete" in msg:
        code = 409
    else:
        code = 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/payees/all")
def payees_all(
    include_inactive: bool = True, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    return {"payees": list_payees_admin(engine, include_inactive=include_inactive)}


@router.get("/payees/{payee_id}")
def payee_get(payee_id: int, engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    try:
        return get_payee(engine, payee_id)
    except ManagerError as exc:
        raise _http(exc) from exc


@router.post("/payees")
def payee_create(body: PayeeIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_payee(engine, body.model_dump())
    except ManagerError as exc:
        raise _http(exc) from exc


@router.put("/payees/{payee_id}")
def payee_update(
    payee_id: int, body: PayeeIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_payee(engine, payee_id, body.model_dump())
    except ManagerError as exc:
        raise _http(exc) from exc


@router.post("/payees/{payee_id}/active")
def payee_active(
    payee_id: int, body: ActiveIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return set_payee_active(engine, payee_id, body.active)
    except ManagerError as exc:
        raise _http(exc) from exc


@router.delete("/payees/{payee_id}")
def payee_delete(payee_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_payee(engine, payee_id)
    except ManagerError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}


@router.post("/payees/{payee_id}/merge")
def payee_merge(
    payee_id: int, body: MergeIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return merge_payees(engine, payee_id, body.into_id)
    except ManagerError as exc:
        raise _http(exc) from exc


@router.get("/categories/all")
def categories_all(
    include_inactive: bool = True, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    return {"categories": list_categories_admin(engine, include_inactive=include_inactive)}


@router.post("/categories")
def category_create(body: CategoryIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_category(engine, body.model_dump())
    except ManagerError as exc:
        raise _http(exc) from exc


@router.put("/categories/{categ_id}")
def category_update(
    categ_id: int, body: CategoryIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_category(engine, categ_id, body.model_dump())
    except ManagerError as exc:
        raise _http(exc) from exc


@router.post("/categories/{categ_id}/active")
def category_active(
    categ_id: int, body: ActiveIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return set_category_active(engine, categ_id, body.active)
    except ManagerError as exc:
        raise _http(exc) from exc


@router.delete("/categories/{categ_id}")
def category_delete(categ_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_category(engine, categ_id)
    except ManagerError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}


@router.post("/categories/{categ_id}/merge")
def category_merge(
    categ_id: int, body: MergeIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return merge_categories(engine, categ_id, body.into_id)
    except ManagerError as exc:
        raise _http(exc) from exc


@router.get("/tags/all")
def tags_all(
    include_inactive: bool = True, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    return {"tags": list_tags_admin(engine, include_inactive=include_inactive)}


@router.post("/tags")
def tag_create(body: TagIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_tag(engine, body.model_dump())
    except ManagerError as exc:
        raise _http(exc) from exc


@router.put("/tags/{tag_id}")
def tag_update(tag_id: int, body: TagIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return update_tag(engine, tag_id, body.model_dump())
    except ManagerError as exc:
        raise _http(exc) from exc


@router.post("/tags/{tag_id}/active")
def tag_active(
    tag_id: int, body: ActiveIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return set_tag_active(engine, tag_id, body.active)
    except ManagerError as exc:
        raise _http(exc) from exc


@router.delete("/tags/{tag_id}")
def tag_delete(tag_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_tag(engine, tag_id)
    except ManagerError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}


@router.get("/currencies/all")
def currencies_all(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return {"currencies": list_currencies_admin(engine)}


@router.post("/currencies")
def currency_create(body: CurrencyIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_currency(engine, body.model_dump())
    except ManagerError as exc:
        raise _http(exc) from exc


@router.put("/currencies/{currency_id}")
def currency_update(
    currency_id: int, body: CurrencyIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_currency(engine, currency_id, body.model_dump())
    except ManagerError as exc:
        raise _http(exc) from exc


@router.delete("/currencies/{currency_id}")
def currency_delete(currency_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_currency(engine, currency_id)
    except ManagerError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}
