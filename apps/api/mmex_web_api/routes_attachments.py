"""Transaction attachments (files on the data volume)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.engine import Engine

from mmex_domain.attachments import (
    AttachmentError,
    add_attachment,
    delete_attachment,
    file_path,
    get_attachment,
    list_attachments,
)
from mmex_domain.constants import REF_TRANSACTION
from mmex_web_api.config import Settings
from mmex_web_api.deps import get_compatible_engine, get_current_user, get_settings, require_write

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


def _http(exc: AttachmentError) -> HTTPException:
    msg = str(exc)
    code = 404 if msg.startswith("unknown") else 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/transactions/{trans_id}/attachments")
def attachments_list(
    trans_id: int, engine: Engine = Depends(get_compatible_engine)
) -> dict[str, Any]:
    return {"attachments": list_attachments(engine, REF_TRANSACTION, trans_id)}


@router.post("/transactions/{trans_id}/attachments")
async def attachments_add(
    trans_id: int,
    file: UploadFile = File(...),
    description: str = Form(""),
    engine: Engine = Depends(require_write),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    data = await file.read()
    try:
        return add_attachment(
            engine,
            settings.attachments_dir,
            ref_type=REF_TRANSACTION,
            ref_id=trans_id,
            original_name=file.filename or "file",
            data=data,
            description=description,
        )
    except AttachmentError as exc:
        raise _http(exc) from exc


@router.get("/attachments/{attachment_id}/file")
def attachments_download(
    attachment_id: int,
    engine: Engine = Depends(get_compatible_engine),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    try:
        item = get_attachment(engine, attachment_id)
        path = file_path(settings.attachments_dir, item["filename"])
    except AttachmentError as exc:
        raise _http(exc) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file missing on volume")
    download_name = item["description"] or item["filename"]
    return FileResponse(path, filename=download_name)


@router.delete("/attachments/{attachment_id}")
def attachments_delete(
    attachment_id: int,
    engine: Engine = Depends(require_write),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    try:
        delete_attachment(engine, settings.attachments_dir, attachment_id)
    except AttachmentError as exc:
        raise _http(exc) from exc
    return {"status": "deleted"}
