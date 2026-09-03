"""Custom field definitions and per-record values."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from mmex_domain.custom_fields import (
    CustomFieldError,
    create_field,
    delete_field,
    get_field,
    list_fields,
    meta,
    save_values,
    update_field,
    values_for,
)
from mmex_web_api.deps import get_compatible_engine, get_current_user, require_write

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


class PropsIn(BaseModel):
    tooltip: str = ""
    regex: str = ""
    autocomplete: bool = False
    default: str = ""
    choices: list[str] = Field(default_factory=list)
    digit_scale: int = 0
    udfc: str = ""


class FieldIn(BaseModel):
    name: str
    ref_type: str
    type: str = "String"
    properties: PropsIn = Field(default_factory=PropsIn)


class FieldPatch(BaseModel):
    name: str | None = None
    ref_type: str | None = None
    type: str | None = None
    properties: PropsIn | None = None


class ValueIn(BaseModel):
    field_id: int
    content: str | None = ""


class ValuesIn(BaseModel):
    ref_type: str
    ref_id: int
    values: list[ValueIn]


def _http(exc: CustomFieldError) -> HTTPException:
    msg = str(exc)
    if msg.startswith("unknown"):
        code = 404
    elif "already assigned" in msg or "still has values" in msg:
        code = 409
    else:
        code = 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/custom-fields/meta")
def fields_meta() -> dict[str, Any]:
    return meta()


@router.get("/custom-fields")
def fields_list(
    ref_type: str | None = None, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    try:
        return list_fields(engine, ref_type)
    except CustomFieldError as exc:
        raise _http(exc) from exc


@router.post("/custom-fields")
def fields_create(body: FieldIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return create_field(
            engine,
            {
                "name": body.name,
                "ref_type": body.ref_type,
                "type": body.type,
                "properties": body.properties.model_dump(),
            },
        )
    except CustomFieldError as exc:
        raise _http(exc) from exc


@router.get("/custom-fields/values")
def fields_values(
    ref_type: str,
    ref_id: int,
    engine: Engine = Depends(get_compatible_engine),
) -> dict[str, Any]:
    try:
        return values_for(engine, ref_type, ref_id)
    except CustomFieldError as exc:
        raise _http(exc) from exc


@router.put("/custom-fields/values")
def fields_save_values(body: ValuesIn, engine: Engine = Depends(require_write)) -> dict[str, Any]:
    try:
        return save_values(
            engine,
            body.ref_type,
            body.ref_id,
            [v.model_dump() for v in body.values],
        )
    except CustomFieldError as exc:
        raise _http(exc) from exc


@router.get("/custom-fields/{field_id}")
def fields_get(field_id: int, engine: Engine = Depends(get_compatible_engine)) -> dict[str, Any]:
    try:
        return get_field(engine, field_id)
    except CustomFieldError as exc:
        raise _http(exc) from exc


@router.put("/custom-fields/{field_id}")
def fields_update(
    field_id: int, body: FieldPatch, engine: Engine = Depends(require_write)
) -> dict[str, Any]:
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if "properties" in payload and payload["properties"] is not None:
        payload["properties"] = body.properties.model_dump() if body.properties else {}
    try:
        return update_field(engine, field_id, payload)
    except CustomFieldError as exc:
        raise _http(exc) from exc


@router.delete("/custom-fields/{field_id}")
def fields_delete(field_id: int, engine: Engine = Depends(require_write)) -> dict[str, str]:
    try:
        delete_field(engine, field_id)
    except CustomFieldError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}
