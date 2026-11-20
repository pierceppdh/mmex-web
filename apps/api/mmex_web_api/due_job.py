"""Last silent scheduled-entry run, for health and the scheduled screen."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def record_due_job(
    state: Any,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    errors = [str(item) for item in ((result or {}).get("errors") or [])]
    if error:
        errors = [error, *errors]
    payload = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entered": int((result or {}).get("entered") or 0),
        "ended": int((result or {}).get("ended") or 0),
        "errors": errors,
        "failed": error is not None,
    }
    state.due_job = payload
    if payload["failed"] or payload["errors"]:
        logger.warning("scheduled due job: %s", payload)
    return payload
