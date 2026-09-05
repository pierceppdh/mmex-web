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
