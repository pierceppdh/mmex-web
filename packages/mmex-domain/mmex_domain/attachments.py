"""ATTACHMENT_V1 rows and files beside the ledger."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.constants import REF_TRANSACTION

REF_TYPES = (
    "Transaction",
    "Stock",
    "Asset",
    "Bank Account",
    "Repeating Transaction",
    "Payee",
)

MAX_BYTES = 15 * 1024 * 1024


class AttachmentError(ValueError):
    """Invalid attachment payload or missing file."""


def _next_id(conn: Connection, table: str, column: str) -> int:
    now_based = int(time.time() * 1000) * 1000
    max_id = int(conn.execute(text(f"SELECT MAX({column}) FROM {table}")).scalar() or 0)
    return max(now_based, max_id + 1)


def _safe_name(name: str) -> str:
    base = Path(name or "").name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    if not base:
        base = "file"
    return base[:120]


def _row(r: Any) -> dict[str, Any]:
    return {
        "attachment_id": int(r[0]),
        "ref_type": r[1],
        "ref_id": int(r[2]),
        "description": r[3] or "",
        "filename": r[4],
    }


def list_attachments(
    engine: Engine, ref_type: str, ref_id: int
) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ATTACHMENTID, REFTYPE, REFID, DESCRIPTION, FILENAME
                  FROM ATTACHMENT_V1
                 WHERE REFTYPE = :t AND REFID = :id
                 ORDER BY ATTACHMENTID
                """
            ),
            {"t": ref_type, "id": ref_id},
        ).fetchall()
    return [_row(r) for r in rows]


def counts_for(engine: Engine, ref_type: str, ref_ids: list[int]) -> dict[int, int]:
    if not ref_ids:
        return {}
    from sqlalchemy import bindparam

    result = {i: 0 for i in ref_ids}
    stmt = text(
        """
        SELECT REFID, COUNT(*)
          FROM ATTACHMENT_V1
         WHERE REFTYPE = :t AND REFID IN :ids
         GROUP BY REFID
        """
    ).bindparams(bindparam("ids", expanding=True))
    with engine.connect() as conn:
        for ref_id, cnt in conn.execute(stmt, {"t": ref_type, "ids": list(ref_ids)}):
            result[int(ref_id)] = int(cnt)
    return result


def get_attachment(engine: Engine, attachment_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT ATTACHMENTID, REFTYPE, REFID, DESCRIPTION, FILENAME
                  FROM ATTACHMENT_V1 WHERE ATTACHMENTID = :id
                """
            ),
            {"id": attachment_id},
        ).fetchone()
    if row is None:
        raise AttachmentError(f"unknown attachment {attachment_id}")
    return _row(row)


def file_path(attachments_dir: Path, stored_name: str) -> Path:
    path = (attachments_dir / stored_name).resolve()
    root = attachments_dir.resolve()
    if not str(path).startswith(str(root)):
        raise AttachmentError("invalid filename")
    return path


def add_attachment(
    engine: Engine,
    attachments_dir: Path,
    *,
    ref_type: str,
    ref_id: int,
    original_name: str,
    data: bytes,
    description: str = "",
) -> dict[str, Any]:
    if ref_type not in REF_TYPES:
        raise AttachmentError("invalid ref_type")
    if not data:
        raise AttachmentError("empty file")
    if len(data) > MAX_BYTES:
        raise AttachmentError("file too large")
    if ref_type == REF_TRANSACTION:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT TRANSID FROM CHECKINGACCOUNT_V1 WHERE TRANSID = :id"),
                {"id": ref_id},
            ).fetchone()
        if exists is None:
            raise AttachmentError(f"unknown transaction {ref_id}")
    attachments_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(original_name)
    desc = (description or original_name or safe).strip()
    with engine.begin() as conn:
        aid = _next_id(conn, "ATTACHMENT_V1", "ATTACHMENTID")
        stored = f"{ref_type}_{ref_id}_{aid}_{safe}"
        conn.execute(
            text(
                """
                INSERT INTO ATTACHMENT_V1 (
                    ATTACHMENTID, REFTYPE, REFID, DESCRIPTION, FILENAME
                ) VALUES (:id, :t, :rid, :d, :f)
                """
            ),
            {"id": aid, "t": ref_type, "rid": ref_id, "d": desc, "f": stored},
        )
    path = file_path(attachments_dir, stored)
    path.write_bytes(data)
    return get_attachment(engine, aid)


def delete_attachment(engine: Engine, attachments_dir: Path, attachment_id: int) -> None:
    item = get_attachment(engine, attachment_id)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM ATTACHMENT_V1 WHERE ATTACHMENTID = :id"),
            {"id": attachment_id},
        )
    path = file_path(attachments_dir, item["filename"])
    if path.is_file():
        path.unlink()
