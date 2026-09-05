"""Minimal Paperless-ngx client (inbox list)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mmex_web_api.config import Settings

logger = logging.getLogger(__name__)


class PaperlessError(RuntimeError):
    pass


def _get(url: str, token: str, timeout: int = 15) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Authorization": f"Token {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise PaperlessError(f"Paperless HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise PaperlessError(str(exc.reason or exc)) from exc


def list_inbox_documents(settings: Settings) -> list[dict[str, Any]]:
    base = (settings.paperless_url or "").rstrip("/")
    token = settings.paperless_token or ""
    if not base or not token:
        return []
    tag_name = settings.paperless_inbox_tag or "Nouveau-Relevé"
    tags = _get(
        f"{base}/api/tags/?{urllib.parse.urlencode({'name__iexact': tag_name, 'page_size': 10})}",
        token,
    )
    results = tags.get("results") or []
    if not results:
        return []
    tag_id = int(results[0]["id"])
    docs: list[dict[str, Any]] = []
    params = urllib.parse.urlencode(
        {"ordering": "-created", "tags__id__in": tag_id, "page_size": 100}
    )
    url: str | None = f"{base}/api/documents/?{params}"
    while url:
        payload = _get(url, token)
        for item in payload.get("results") or []:
            created = str(item.get("created") or item.get("created_date") or "")
            tags_raw = item.get("tags") or []
            tag_names: list[str] = []
            for t in tags_raw:
                if isinstance(t, dict) and t.get("name"):
                    tag_names.append(str(t["name"]))
            docs.append(
                {
                    "id": int(item["id"]),
                    "title": item.get("title") or "",
                    "created": created[:10],
                    "original_file_name": item.get("original_file_name") or "",
                    "tags": tag_names,
                }
            )
        url = payload.get("next")
    return docs


def download_document(settings: Settings, doc_id: int) -> tuple[bytes, str]:
    base = (settings.paperless_url or "").rstrip("/")
    token = settings.paperless_token or ""
    if not base or not token:
        raise PaperlessError("Paperless is not configured")
    url = f"{base}/api/documents/{int(doc_id)}/download/"
    req = urllib.request.Request(url, headers={"Authorization": f"Token {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type") or "application/pdf"
            disp = resp.headers.get("Content-Disposition") or ""
    except urllib.error.HTTPError as exc:
        raise PaperlessError(f"Paperless HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise PaperlessError(str(exc.reason or exc)) from exc
    name = f"paperless_{doc_id}.pdf"
    marker = "filename="
    if marker in disp:
        name = disp.split(marker, 1)[1].strip().strip('"')
    return data, name


def _json_request(method: str, url: str, token: str, body: dict | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise PaperlessError(f"Paperless HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise PaperlessError(str(exc.reason or exc)) from exc


def _tag_id(settings: Settings, name: str) -> int | None:
    base = settings.paperless_url.rstrip("/")
    payload = _get(
        f"{base}/api/tags/?{urllib.parse.urlencode({'name__iexact': name, 'page_size': 10})}",
        settings.paperless_token,
    )
    results = payload.get("results") or []
    if not results:
        return None
    return int(results[0]["id"])


def mark_reconciled(settings: Settings, doc_id: int) -> dict[str, Any]:
    if not settings.paperless_url or not settings.paperless_token:
        return {"updated": False, "error": "not_configured"}
    base = settings.paperless_url.rstrip("/")
    token = settings.paperless_token
    inbox_id = _tag_id(settings, settings.paperless_inbox_tag)
    done_id = _tag_id(settings, settings.paperless_done_tag)
    if done_id is None:
        created = _json_request(
            "POST",
            f"{base}/api/tags/",
            token,
            {"name": settings.paperless_done_tag, "color": "#4caf50"},
        )
        done_id = int(created["id"])
    doc = _get(f"{base}/api/documents/{int(doc_id)}/", token)
    tags: set[int] = set()
    for item in doc.get("tags") or []:
        if isinstance(item, int):
            tags.add(item)
        elif isinstance(item, dict) and "id" in item:
            tags.add(int(item["id"]))
    if done_id in tags and (inbox_id is None or inbox_id not in tags):
        return {"updated": False, "already_reconciled": True}
    if inbox_id:
        tags.discard(inbox_id)
    tags.add(done_id)
    _json_request("PATCH", f"{base}/api/documents/{int(doc_id)}/", token, {"tags": sorted(tags)})
    return {"updated": True, "already_reconciled": False}
