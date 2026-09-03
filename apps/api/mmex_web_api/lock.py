"""Exclusive writer lock next to the `.mmb` file.

Protocol ``mmex-lock-v1`` (shared with bank-reconciliation-app):
POSIX ``flock`` on ``data.mmb.lock`` plus a JSON sidecar so siblings can
show who holds the write lock. One writer at a time. Yielding unlocks
the flock and clears ``holder`` so recon (or desktop) can take it.
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, TextIO

PROTOCOL = "mmex-lock-v1"


class WriterLock:
    def __init__(self, lock_path: Path, holder: str) -> None:
        self.lock_path = lock_path
        self.holder = holder
        self._fp: TextIO | None = None
        self.acquired = False
        self.read_only = True
        self.error: str | None = None

    def acquire(self) -> bool:
        if self.acquired:
            return True
        self._close_fp()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self.lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.error = str(exc)
            self.acquired = False
            self.read_only = True
            self._close_fp()
            return False
        payload = {
            "protocol": PROTOCOL,
            "holder": self.holder,
            "pid": os.getpid(),
            "acquired_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._fp.seek(0)
        self._fp.truncate()
        self._fp.write(json.dumps(payload, indent=2))
        self._fp.write("\n")
        self._fp.flush()
        self.acquired = True
        self.read_only = False
        self.error = None
        return True

    def release(self) -> None:
        if self._fp is None:
            self.acquired = False
            self.read_only = True
            return
        try:
            if self.acquired:
                payload = {
                    "protocol": PROTOCOL,
                    "holder": None,
                    "released_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                self._fp.seek(0)
                self._fp.truncate()
                self._fp.write(json.dumps(payload, indent=2))
                self._fp.write("\n")
                self._fp.flush()
                fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
        finally:
            self._close_fp()
            self.acquired = False
            self.read_only = True

    def status(self) -> dict[str, Any]:
        meta = peek_lock(self.lock_path)
        holder = self.holder if self.acquired else meta.get("holder")
        return {
            "path": str(self.lock_path),
            "protocol": PROTOCOL,
            "acquired": self.acquired,
            "read_only": self.read_only,
            "holder": holder,
            "pid": os.getpid() if self.acquired else meta.get("pid"),
            "acquired_at": meta.get("acquired_at"),
            "released_at": meta.get("released_at"),
            "error": self.error,
        }

    def _close_fp(self) -> None:
        if self._fp is None:
            return
        try:
            self._fp.close()
        except OSError:
            pass
        self._fp = None


def peek_lock(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


@contextmanager
def exclusive_write(lock_path: Path, holder: str) -> Iterator[WriterLock]:
    lock = WriterLock(lock_path, holder)
    if not lock.acquire():
        meta = peek_lock(lock_path)
        who = meta.get("holder") or "unknown"
        raise LockBusyError(f"write lock held by {who}")
    try:
        yield lock
    finally:
        lock.release()


class LockBusyError(RuntimeError):
    """Another process holds ``data.mmb.lock``."""
