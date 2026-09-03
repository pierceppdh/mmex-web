"""Login, logout, bootstrap, and session status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from mmex_web_api.auth import SESSION_USER_KEY, AuthStore

router = APIRouter(prefix="/api/auth")


class LoginBody(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class BootstrapBody(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


def _store(request: Request) -> AuthStore:
    return request.app.state.mmex.auth


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    store = _store(request)
    user = request.session.get(SESSION_USER_KEY)
    return {
        "authenticated": bool(user),
        "username": user,
        "bootstrap": store.needs_bootstrap(),
        "locale_default": request.app.state.mmex.settings.locale_default,
    }


@router.post("/login")
def login(body: LoginBody, request: Request) -> dict[str, Any]:
    store = _store(request)
    if not store.verify(body.username.strip(), body.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    request.session[SESSION_USER_KEY] = body.username.strip()
    return {"ok": True, "username": body.username.strip()}


@router.post("/logout")
def logout(request: Request) -> dict[str, Any]:
    request.session.clear()
    return {"ok": True}


@router.post("/bootstrap")
def bootstrap(body: BootstrapBody, request: Request) -> dict[str, Any]:
    store = _store(request)
    if not store.needs_bootstrap():
        raise HTTPException(status_code=409, detail="credentials already exist")
    try:
        store.bootstrap(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.session[SESSION_USER_KEY] = body.username.strip()
    return {"ok": True, "username": body.username.strip()}
