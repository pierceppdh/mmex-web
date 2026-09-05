"""Bank statement inbox (Paperless Nouveau-Relevé) mapped to MMEX accounts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from mmex_domain.recon import list_account_refs, suggest_account_id
from mmex_domain.transactions import TransactionError
from mmex_web_api.config import Settings
from mmex_web_api.deps import (
    get_compatible_engine,
    get_current_user,
    get_settings,
    require_write,
)
from mmex_web_api.paperless import (
    PaperlessError,
    download_document,
    list_inbox_documents,
    mark_reconciled,
)
from mmex_web_api.recon_pipeline import build_session, commit_session, preview_document

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


@router.get("/documents/{doc_id}/preview")
def document_preview(
    doc_id: int,
    engine: Engine = Depends(get_compatible_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        return preview_document(engine, settings, doc_id)
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


class SessionIn(BaseModel):
    paperless_id: int
    account_id: int
    currency: str | None = None


class MatchPatch(BaseModel):
    include: bool | None = None
    selected_trans_id: int | None = None
    selected_payee_name: str | None = None
    force_new_insert: bool | None = None
    insert_as_transfer: bool | None = None
    transfer_counterpart_account_id: int | None = None
    transfer_counterpart_account_name: str | None = None
    transfer_counterpart_amount: str | None = None
    force_trans_code: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    status: str | None = None


class CommitIn(BaseModel):
    dry_run: bool = True


def _sessions(request: Request) -> dict[str, dict[str, Any]]:
    return request.app.state.mmex.recon_sessions


@router.post("/sessions")
def create_session(
    body: SessionIn,
    request: Request,
    engine: Engine = Depends(get_compatible_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        session = build_session(
            engine,
            settings,
            paperless_id=body.paperless_id,
            account_id=body.account_id,
            currency=body.currency,
        )
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _sessions(request)[session["id"]] = session
    return session


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict[str, Any]:
    session = _sessions(request).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.patch("/sessions/{session_id}/matches/{index}")
def patch_match(
    session_id: str,
    index: int,
    body: MatchPatch,
    request: Request,
) -> dict[str, Any]:
    session = _sessions(request).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    matches = session.get("matches") or []
    if index < 0 or index >= len(matches):
        raise HTTPException(status_code=404, detail="match not found")
    row = dict(matches[index])
    data = body.model_dump(exclude_unset=True)
    nullable = {
        "selected_trans_id",
        "transfer_counterpart_account_id",
        "transfer_counterpart_amount",
        "force_trans_code",
        "category_id",
        "category_name",
    }
    if "selected_trans_id" in data and data["selected_trans_id"] is None:
        row["selected_trans_id"] = None
        row["force_new_insert"] = True
        row["status"] = "MANUAL"
    row.update({k: v for k, v in data.items() if v is not None or k in nullable})
    matches[index] = row
    session["matches"] = matches
    return session


@router.post("/sessions/{session_id}/commit")
def commit(
    session_id: str,
    body: CommitIn,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    session = _sessions(request).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    if body.dry_run:
        engine = get_compatible_engine(request)
    else:
        engine = require_write(request)
    try:
        result = commit_session(engine, session, dry_run=body.dry_run)
    except TransactionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("success") and not body.dry_run:
        doc_id = session.get("paperless_doc_id")
        if doc_id:
            try:
                result["paperless"] = mark_reconciled(settings, int(doc_id))
            except PaperlessError as exc:
                result["paperless"] = {"updated": False, "error": str(exc)}
        session["committed"] = True
    return result
