"""CSV / QIF / XML import and export."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.engine import Engine

from mmex_domain.io import IoError, export_file, import_file, meta
from mmex_web_api.deps import get_compatible_engine, get_current_user, require_write

router = APIRouter(prefix="/api/io", dependencies=[Depends(get_current_user)])


def _http(exc: IoError) -> HTTPException:
    msg = str(exc)
    code = 404 if msg.startswith("unknown") else 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/meta")
def io_meta() -> dict[str, Any]:
    return meta()


def _import_kwargs(
    *,
    fmt: str,
    account_id: int,
    fields: str | None,
    delimiter: str,
    date_format: str,
    decimal: str,
    amount_sign: str,
    skip_first: int,
    skip_last: int,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "fmt": fmt,
        "account_id": account_id,
        "fields": fields,
        "delimiter": delimiter,
        "date_format": date_format,
        "decimal": decimal,
        "amount_sign": amount_sign,
        "skip_first": skip_first,
        "skip_last": skip_last,
        "dry_run": dry_run,
    }


@router.post("/preview")
async def io_preview(
    file: UploadFile = File(...),
    account_id: int = Form(...),
    fmt: str = Form("csv"),
    fields: str | None = Form(None),
    delimiter: str = Form(","),
    date_format: str = Form("YYYY-MM-DD"),
    decimal: str = Form("."),
    amount_sign: str = Form("deposit"),
    skip_first: int = Form(0),
    skip_last: int = Form(0),
    engine: Engine = Depends(get_compatible_engine),
) -> dict[str, Any]:
    data = await file.read()
    try:
        return import_file(
            engine,
            data,
            **_import_kwargs(
                fmt=fmt,
                account_id=account_id,
                fields=fields,
                delimiter=delimiter,
                date_format=date_format,
                decimal=decimal,
                amount_sign=amount_sign,
                skip_first=skip_first,
                skip_last=skip_last,
                dry_run=True,
            ),
        )
    except IoError as exc:
        raise _http(exc) from exc


@router.post("/import")
async def io_import(
    file: UploadFile = File(...),
    account_id: int = Form(...),
    fmt: str = Form("csv"),
    fields: str | None = Form(None),
    delimiter: str = Form(","),
    date_format: str = Form("YYYY-MM-DD"),
    decimal: str = Form("."),
    amount_sign: str = Form("deposit"),
    skip_first: int = Form(0),
    skip_last: int = Form(0),
    engine: Engine = Depends(require_write),
) -> dict[str, Any]:
    data = await file.read()
    try:
        return import_file(
            engine,
            data,
            **_import_kwargs(
                fmt=fmt,
                account_id=account_id,
                fields=fields,
                delimiter=delimiter,
                date_format=date_format,
                decimal=decimal,
                amount_sign=amount_sign,
                skip_first=skip_first,
                skip_last=skip_last,
                dry_run=False,
            ),
        )
    except IoError as exc:
        raise _http(exc) from exc


@router.get("/export")
def io_export(
    account_id: int,
    fmt: str = "csv",
    date_from: str | None = None,
    date_to: str | None = None,
    fields: str | None = None,
    delimiter: str = ",",
    date_format: str = "YYYY-MM-DD",
    titles: bool = True,
    engine: Engine = Depends(get_compatible_engine),
) -> Response:
    try:
        payload, filename, media = export_file(
            engine,
            fmt=fmt,
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            fields=fields,
            delimiter=delimiter,
            titles=titles,
            date_format=date_format,
        )
    except IoError as exc:
        raise _http(exc) from exc
    return Response(
        content=payload,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
