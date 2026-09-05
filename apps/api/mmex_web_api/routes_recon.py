"""Bank statement inbox (Paperless Nouveau-Relevé) mapped to MMEX accounts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.engine import Engine

from mmex_domain.recon import list_account_refs, suggest_account_id
from mmex_web_api.config import Settings
from mmex_web_api.deps import get_compatible_engine, get_current_user, get_settings
from mmex_web_api.paperless import PaperlessError, download_document, list_inbox_documents

router = APIRouter(prefix="/api/recon", dependencies=[Depends(get_current_user)])


@router.get("/inbox")
def inbox(
    engine: Engine = Depends(get_compatible_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    accounts = list_account_refs(engine)
    try:
        raw = list_inbox_documents(settings)
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    documents: list[dict[str, Any]] = []
    by_account: dict[int, list[dict[str, Any]]] = {}
    unmapped: list[dict[str, Any]] = []
    for doc in raw:
        hay = " ".join(
            [
                str(doc.get("title") or ""),
                str(doc.get("original_file_name") or ""),
                " ".join(doc.get("tags") or []),
            ]
        )
        aid = suggest_account_id(hay, accounts)
        item = {**doc, "account_id": aid}
        documents.append(item)
        if aid is None:
            unmapped.append(item)
        else:
            by_account.setdefault(aid, []).append(item)
    return {
        "configured": bool(settings.paperless_url and settings.paperless_token),
        "inbox_tag": settings.paperless_inbox_tag,
        "documents": documents,
        "by_account": {str(k): v for k, v in by_account.items()},
        "unmapped": unmapped,
    }


@router.get("/documents/{doc_id}/file")
def document_file(
    doc_id: int,
    settings: Settings = Depends(get_settings),
) -> Response:
    try:
        data, name = download_document(settings, doc_id)
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    headers = {"Content-Disposition": f'inline; filename="{name}"'}
    media = "application/pdf" if name.lower().endswith(".pdf") else "application/octet-stream"
    return Response(content=data, media_type=media, headers=headers)
