"""Yield and take the shared ``data.mmb.lock`` writer lock."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from mmex_web_api.deps import get_current_user

router = APIRouter(prefix="/api/lock", dependencies=[Depends(get_current_user)])


@router.get("")
def lock_get(request: Request) -> dict[str, Any]:
    return request.app.state.mmex.lock.status()


@router.post("/acquire")
def lock_acquire(request: Request) -> dict[str, Any]:
    lock = request.app.state.mmex.lock
    if lock.acquired:
        return lock.status()
    if not lock.acquire():
        status = lock.status()
        who = status.get("holder") or "unknown"
        raise HTTPException(status_code=409, detail=f"write lock held by {who}")
    return lock.status()


@router.post("/release")
def lock_release(request: Request) -> dict[str, Any]:
    lock = request.app.state.mmex.lock
    lock.release()
    return lock.status()
