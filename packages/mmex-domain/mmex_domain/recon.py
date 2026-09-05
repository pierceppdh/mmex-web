"""Map Paperless inbox documents to MMEX accounts (read-only)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine


def normalize_account_ref(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[\s\-]", "", value).upper()


def list_account_refs(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ACCOUNTID, ACCOUNTNAME, ACCOUNTNUM, ACCOUNTTYPE, STATUS
                  FROM ACCOUNTLIST_V1
                 ORDER BY ACCOUNTNAME
                """
            )
        ).fetchall()
    return [
        {
            "account_id": int(row[0]),
            "name": row[1] or "",
            "account_num": row[2] or "",
            "account_type": row[3] or "",
            "status": row[4] or "",
        }
        for row in rows
    ]


def suggest_account_id(haystack: str, accounts: list[dict[str, Any]]) -> int | None:
    blob = normalize_account_ref(haystack)
    lower = haystack.lower()
    best: int | None = None
    best_len = 0
    for acc in accounts:
        if acc.get("status") == "Closed":
            continue
        num = normalize_account_ref(str(acc.get("account_num") or ""))
        if len(num) >= 6 and num in blob and len(num) > best_len:
            best = int(acc["account_id"])
            best_len = len(num)
        name = str(acc.get("name") or "").strip()
        if name and name.lower() in lower and best is None:
            best = int(acc["account_id"])
    return best
