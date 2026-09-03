"""Stocks, share lots, assets, translinks."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from mmex_domain.investments import (
    InvestError,
    add_asset_link,
    add_stock_lot,
    create_asset,
    create_stock,
    delete_asset,
    delete_asset_link,
    delete_stock,
    delete_stock_lot,
    get_asset,
    get_stock,
    list_assets,
    list_holding_accounts,
    list_stocks,
    meta,
    update_asset,
    update_price,
    update_stock,
)
from mmex_web_api.deps import get_compatible_engine, get_current_user, require_write

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


class StockIn(BaseModel):
    name: str
    held_at: int
    purchase_date: str
    symbol: str = ""
    num_shares: str = "0"
    purchase_price: str = "0"
    current_price: str = "0"
    commission: str = "0"
    notes: str = ""


class StockPatch(BaseModel):
    name: str | None = None
    held_at: int | None = None
    purchase_date: str | None = None
    symbol: str | None = None
    num_shares: str | None = None
    purchase_price: str | None = None
    current_price: str | None = None
    commission: str | None = None
    notes: str | None = None


class PriceIn(BaseModel):
    date: str
    price: str
    symbol: str | None = None


class LotIn(BaseModel):
    trans_id: int
    share_number: str = "0"
    share_price: str = "0"
    share_commission: str = "0"
    share_lot: str = ""


class AssetIn(BaseModel):
    name: str
    start_date: str
    status: str = "Open"
    asset_type: str = "Other"
    value: str = "0"
    value_change: str = "None"
    value_change_mode: str = "Percentage"
    value_change_rate: str = "0"
    currency_id: int | None = None
    notes: str = ""


class AssetPatch(BaseModel):
    name: str | None = None
    start_date: str | None = None
    status: str | None = None
    asset_type: str | None = None
    value: str | None = None
    value_change: str | None = None
    value_change_mode: str | None = None
    value_change_rate: str | None = None
    currency_id: int | None = None
    notes: str | None = None


class LinkIn(BaseModel):
    trans_id: int


def _http(exc: InvestError) -> HTTPException:
    msg = str(exc)
    if msg.startswith("unknown"):
        code = 404
    elif "already linked" in msg or "still has linked" in msg:
        code = 409
    else:
        code = 400
    return HTTPException(status_code=code, detail=msg)


def _dump(body: BaseModel) -> dict[str, Any]:
    return {k: v for k, v in body.model_dump().items() if v is not None}


@router.get("/investments/meta")
def investments_meta(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return {**meta(), "accounts": list_holding_accounts(engine)}


@router.get("/stocks")
def stocks_list(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return list_stocks(engine)


@router.post("/stocks")
def stocks_create(body: StockIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_stock(engine, body.model_dump())
    except InvestError as exc:
        raise _http(exc) from exc


@router.get("/stocks/{stock_id}")
def stocks_get(stock_id: int, engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    try:
        return get_stock(engine, stock_id)
    except InvestError as exc:
        raise _http(exc) from exc


@router.put("/stocks/{stock_id}")
def stocks_update(
    stock_id: int, body: StockPatch, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_stock(engine, stock_id, _dump(body))
    except InvestError as exc:
        raise _http(exc) from exc


@router.delete("/stocks/{stock_id}")
def stocks_delete(stock_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_stock(engine, stock_id)
    except InvestError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}


@router.post("/stocks/price")
def stocks_price(body: PriceIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return update_price(
            engine, symbol=body.symbol, price_date=body.date, price=body.price
        )
    except InvestError as exc:
        raise _http(exc) from exc


@router.post("/stocks/{stock_id}/price")
def stocks_price_one(
    stock_id: int, body: PriceIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_price(
            engine, stock_id=stock_id, price_date=body.date, price=body.price
        )
    except InvestError as exc:
        raise _http(exc) from exc


@router.post("/stocks/{stock_id}/lots")
def stocks_add_lot(
    stock_id: int, body: LotIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return add_stock_lot(engine, stock_id, body.model_dump())
    except InvestError as exc:
        raise _http(exc) from exc


@router.delete("/stocks/{stock_id}/lots/{share_info_id}")
def stocks_delete_lot(
    stock_id: int, share_info_id: int, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return delete_stock_lot(engine, stock_id, share_info_id)
    except InvestError as exc:
        raise _http(exc) from exc


@router.get("/assets")
def assets_list(
    as_of: str | None = None, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    day = None
    if as_of:
        try:
            day = date.fromisoformat(as_of[:10])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid date") from exc
    return list_assets(engine, as_of=day)


@router.post("/assets")
def assets_create(body: AssetIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_asset(engine, body.model_dump())
    except InvestError as exc:
        raise _http(exc) from exc


@router.get("/assets/{asset_id}")
def assets_get(
    asset_id: int,
    as_of: str | None = None,
    engine: Engine = Depends(get_compatible_engine),
) -> dict[str, Any]:
    day = None
    if as_of:
        try:
            day = date.fromisoformat(as_of[:10])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid date") from exc
    try:
        return get_asset(engine, asset_id, as_of=day)
    except InvestError as exc:
        raise _http(exc) from exc


@router.put("/assets/{asset_id}")
def assets_update(
    asset_id: int, body: AssetPatch, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_asset(engine, asset_id, _dump(body))
    except InvestError as exc:
        raise _http(exc) from exc


@router.delete("/assets/{asset_id}")
def assets_delete(asset_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_asset(engine, asset_id)
    except InvestError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}


@router.post("/assets/{asset_id}/links")
def assets_add_link(
    asset_id: int, body: LinkIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return add_asset_link(engine, asset_id, body.trans_id)
    except InvestError as exc:
        raise _http(exc) from exc


@router.delete("/assets/{asset_id}/links/{translink_id}")
def assets_delete_link(
    asset_id: int, translink_id: int, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return delete_asset_link(engine, asset_id, translink_id)
    except InvestError as exc:
        raise _http(exc) from exc
