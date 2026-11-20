"""Unfinished reconciliation sessions, kept across a process restart."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

_KEEP_COMMITTED = timedelta(days=2)
_KEEP_OPEN = timedelta(days=45)


class SessionStore:
    """JSON file under the data directory. One writer process."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self._items: dict[str, dict[str, Any]] = {}
        self._load()

    def get(self, session_id: str, default: Any = None) -> Any:
        return self._items.get(session_id, default)

    def __setitem__(self, session_id: str, session: dict[str, Any]) -> None:
        with self._lock:
            self._items[str(session_id)] = session
            self._stamp(session)
            self._prune()
            self._write()

    def save(self, session: dict[str, Any]) -> None:
        """Persist an in-place edit. ``__setitem__`` is not called for those."""
        session_id = str(session.get("id") or "")
        if not session_id:
            return
        with self._lock:
            self._items[session_id] = session
            self._stamp(session)
            self._prune()
            self._write()

    def latest_open(self, paperless_id: int) -> dict[str, Any] | None:
        found: dict[str, Any] | None = None
        found_at = ""
        for session in self._items.values():
            if session.get("committed"):
                continue
            if session.get("paperless_doc_id") != paperless_id:
                continue
            updated = str(session.get("updated_at") or "")
            if found is None or updated >= found_at:
                found = session
                found_at = updated
        return found

    def drop_other_open(self, paperless_id: int, keep_id: str) -> None:
        with self._lock:
            remove = [
                sid
                for sid, session in self._items.items()
                if sid != keep_id
                and not session.get("committed")
                and session.get("paperless_doc_id") == paperless_id
            ]
            if not remove:
                return
            for sid in remove:
                del self._items[sid]
            self._write()

    def _stamp(self, session: dict[str, Any]) -> None:
        session["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _prune(self) -> None:
        now = datetime.now(timezone.utc)
        remove: list[str] = []
        for sid, session in self._items.items():
            updated = _parse_time(session.get("updated_at"))
            if updated is None:
                continue
            limit = _KEEP_COMMITTED if session.get("committed") else _KEEP_OPEN
            if now - updated > limit:
                remove.append(sid)
        for sid in remove:
            del self._items[sid]

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self._items = {str(k): v for k, v in data.items() if isinstance(v, dict)}
        self._prune()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._items), encoding="utf-8")
        tmp.replace(self.path)


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
