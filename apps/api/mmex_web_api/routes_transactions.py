"""Transaction register and lookup endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from mmex_domain.lookups import list_categories, list_payees, list_tags
from mmex_domain.transactions import (
    TransactionError,
    create_transaction,
    cycle_status,
    get_transaction,
    list_ledger_transactions,
    list_transactions,
    restore,
    soft_delete,
    update_transaction,
)
from mmex_web_api.deps import get_compatible_engine, get_current_user, require_write

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


class SplitIn(BaseModel):
    categ_id: int
    amount: Decimal
    notes: str = ""
    tag_ids: list[int] = Field(default_factory=list)


class TransactionIn(BaseModel):
    account_id: int
    trans_code: Literal["Withdrawal", "Deposit", "Transfer"]
    trans_amount: Decimal
    trans_date: str
    payee_id: int | None = None
    to_account_id: int | None = None
    to_trans_amount: Decimal | None = None
    categ_id: int | None = None
    status: str = ""
    transaction_number: str = ""
    notes: str = ""
    color: int = -1
    followup_id: int = -1
    tag_ids: list[int] = Field(default_factory=list)
    splits: list[SplitIn] = Field(default_factory=list)


def _payload(body: TransactionIn) -> dict[str, Any]:
    data = body.model_dump()
    data["splits"] = [s.model_dump() for s in body.splits]
    return data


def _http(exc: TransactionError) -> HTTPException:
    msg = str(exc)
    if msg.startswith("unknown"):
        code = 404
    elif "locked" in msg:
        code = 423
    else:
        code = 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/payees")
def payees(
    q: str | None = None,
    limit: int = 40,
    engine: Engine = Depends(get_compatible_engine),
) -> dict[str, Any]:
    return {"payees": list_payees(engine, q, limit)}


@router.get("/categories")
def categories(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return {"categories": list_categories(engine)}


@router.get("/tags")
def tags(engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    return {"tags": list_tags(engine)}


@router.get("/ledger/transactions")
def ledger_transactions(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_deleted: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    payee_id: int | None = None,
    payee_q: str | None = None,
    categ_id: int | None = None,
    trans_code: Literal["Withdrawal", "Deposit", "Transfer"] | None = None,
    status: str | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    notes: str | None = None,
    number: str | None = None,
    tag_id: int | None = None,
    color: int | None = None,
    followup: bool | None = None,
    engine: Engine = Depends(get_compatible_engine),
) -> dict[str, Any]:
    try:
        return list_ledger_transactions(
            engine,
            limit=limit,
            offset=offset,
            include_deleted=include_deleted,
            filters={
                "date_from": date_from,
                "date_to": date_to,
                "payee_id": payee_id,
                "payee_q": payee_q,
                "categ_id": categ_id,
                "trans_code": trans_code,
                "status": status,
                "amount_min": amount_min,
                "amount_max": amount_max,
                "notes": notes,
                "number": number,
                "tag_id": tag_id,
                "color": color,
                "followup": followup,
            },
        )
    except TransactionError as exc:
        raise _http(exc) from exc


@router.get("/accounts/{account_id}/transactions")
def account_transactions(
    account_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_deleted: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    payee_id: int | None = None,
    payee_q: str | None = None,
    categ_id: int | None = None,
    trans_code: Literal["Withdrawal", "Deposit", "Transfer"] | None = None,
    status: str | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    notes: str | None = None,
    number: str | None = None,
    tag_id: int | None = None,
    color: int | None = None,
    followup: bool | None = None,
    engine: Engine = Depends(get_compatible_engine),
) -> dict[str, Any]:
    try:
        return list_transactions(
            engine,
            account_id,
            limit=limit,
            offset=offset,
            include_deleted=include_deleted,
            filters={
                "date_from": date_from,
                "date_to": date_to,
                "payee_id": payee_id,
                "payee_q": payee_q,
                "categ_id": categ_id,
                "trans_code": trans_code,
                "status": status,
                "amount_min": amount_min,
                "amount_max": amount_max,
                "notes": notes,
                "number": number,
                "tag_id": tag_id,
                "color": color,
                "followup": followup,
            },
        )
    except TransactionError as exc:
        raise _http(exc) from exc


@router.get("/transactions/{trans_id}")
def transaction_get(
    trans_id: int, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    try:
        return get_transaction(engine, trans_id)
    except TransactionError as exc:
        raise _http(exc) from exc


@router.post("/transactions")
def transaction_create(
    body: TransactionIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return create_transaction(engine, _payload(body))
    except TransactionError as exc:
        raise _http(exc) from exc


@router.put("/transactions/{trans_id}")
def transaction_update(
    trans_id: int, body: TransactionIn, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return update_transaction(engine, trans_id, _payload(body))
    except TransactionError as exc:
        raise _http(exc) from exc


@router.post("/transactions/{trans_id}/status")
def transaction_cycle_status(
    trans_id: int, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return cycle_status(engine, trans_id)
    except TransactionError as exc:
        raise _http(exc) from exc


@router.post("/transactions/{trans_id}/delete")
def transaction_delete(
    trans_id: int, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return soft_delete(engine, trans_id)
    except TransactionError as exc:
        raise _http(exc) from exc


@router.post("/transactions/{trans_id}/restore")
def transaction_restore(
    trans_id: int, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    try:
        return restore(engine, trans_id)
    except TransactionError as exc:
        raise _http(exc) from exc
