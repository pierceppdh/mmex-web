"""Account suggestions for the Paperless inbox, keyed by document checksum."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

_MISS = object()
_lock = Lock()


def inbox_fingerprint(doc: dict) -> str:
    """Identity of a Paperless document for the suggestion cache.

    The list endpoint often returns an empty checksum. Fall back to the
    modified time, then to the document id, so a repeat inbox load does not
    download the PDF again.
    """
    doc_id = int(doc["id"])
    checksum = str(doc.get("checksum") or "").strip()
    if checksum:
        return f"sha:{checksum}"
    modified = str(doc.get("modified") or doc.get("added") or "").strip()
    name = str(doc.get("original_file_name") or "")
    if modified:
        return f"mod:{doc_id}:{modified}:{name}"
    return f"id:{doc_id}:{name}"


def cache_path(data_dir: Path) -> Path:
    return data_dir / "recon-inbox-cache.json"


def lookup(path: Path, doc_id: int, fingerprint: str) -> Any:
    """Return the cached account id, None if cached as unmapped, or ``_MISS``."""
    with _lock:
        row = _load(path).get(str(doc_id))
    if not isinstance(row, dict) or row.get("fingerprint") != fingerprint:
        return _MISS
    account_id = row.get("account_id")
    if account_id is None:
        return None
    try:
        return int(account_id)
    except (TypeError, ValueError):
        return _MISS


def store(path: Path, doc_id: int, fingerprint: str, account_id: int | None) -> None:
    with _lock:
        data = _load(path)
        data[str(doc_id)] = {"fingerprint": fingerprint, "account_id": account_id}
        _write(path, data)


def retain(path: Path, doc_ids: set[int]) -> None:
    """Drop suggestions for documents that left the inbox."""
    keep = {str(doc_id) for doc_id in doc_ids}
    with _lock:
        data = _load(path)
        pruned = {key: value for key, value in data.items() if key in keep}
        if pruned == data:
            return
        _write(path, pruned)


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)
