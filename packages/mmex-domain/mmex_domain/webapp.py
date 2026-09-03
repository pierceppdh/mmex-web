"""Ingest leftover PHP WebApp sidecar rows (`MMEX_New_Transaction.db`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from mmex_domain.constants import NOT_SET, TRANS_CODES, TRANS_TRANSFER
from mmex_domain.io import _account_by_name, _ensure_category, _ensure_payee
from mmex_domain.money import as_decimal
from mmex_domain.transactions import create_transaction

BLANK = {"", "none", "empty", "null"}


class WebappError(ValueError):
    """Invalid or unreadable WebApp sidecar."""


def _blank(value: object) -> bool:
    return str(value or "").strip().lower() in BLANK


def _text(value: object) -> str:
    raw = str(value or "").strip()
    return "" if raw.lower() in BLANK else raw


def sidecar_status(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False, "pending": 0}
    exists = path.is_file()
    pending = 0
    if exists:
        engine = create_engine(f"sqlite:///{path}")
        try:
            with engine.connect() as conn:
                tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
                if "New_Transaction" in tables:
                    pending = int(conn.execute(text("SELECT COUNT(*) FROM New_Transaction")).scalar() or 0)
        finally:
            engine.dispose()
    return {"path": str(path), "exists": exists, "pending": pending}


def list_pending(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise WebappError("webapp sidecar is missing")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT ID, Date, Account, ToAccount, Status, Type, Payee, "
                    "Category, SubCategory, Amount, Notes FROM New_Transaction ORDER BY ID"
                )
            ).fetchall()
    except Exception as exc:
        raise WebappError("sidecar is not a WebApp database") from exc
    finally:
        engine.dispose()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r[0]),
                "date": str(r[1] or "")[:10],
                "account": _text(r[2]),
                "to_account": _text(r[3]),
                "status": "" if _blank(r[4]) else str(r[4]),
                "type": str(r[5] or "Withdrawal"),
                "payee": _text(r[6]),
                "category": _text(r[7]),
                "subcategory": _text(r[8]),
                "amount": str(r[9] if r[9] is not None else "0"),
                "notes": _text(r[10]),
            }
        )
    return out


def import_sidecar(
    engine: Engine,
    path: Path,
    *,
    dry_run: bool = True,
    delete_imported: bool = False,
) -> dict[str, Any]:
    pending = list_pending(path)
    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    created_payees = 0
    created_categories = 0
    ok_ids: list[int] = []
    for row in pending:
        try:
            code = row["type"] if row["type"] in TRANS_CODES else None
            if code is None:
                raise WebappError(f"invalid type {row['type']!r}")
            with engine.begin() as conn:
                account_id = _account_by_name(conn, row["account"])
                if account_id is None:
                    raise WebappError(f"unknown account {row['account']!r}")
                to_id = None
                payee_id = NOT_SET
                if code == TRANS_TRANSFER:
                    to_id = _account_by_name(conn, row["to_account"])
                    if to_id is None:
                        raise WebappError(f"unknown to-account {row['to_account']!r}")
                elif not dry_run:
                    if not row["payee"]:
                        raise WebappError("payee is required")
                    payee_id, new_p = _ensure_payee(conn, row["payee"])
                    created_payees += int(new_p)
                elif not row["payee"]:
                    raise WebappError("payee is required")
                path_bits = [p for p in (row["category"], row["subcategory"]) if p]
                categ_id = NOT_SET
                if path_bits and not dry_run:
                    categ_id, new_c = _ensure_category(conn, ":".join(path_bits))
                    created_categories += int(new_c)
            amount = as_decimal(str(row["amount"]).replace(",", "."))
            if dry_run:
                imported.append({"sidecar_id": row["id"], "trans_id": None, "account_id": account_id})
                ok_ids.append(row["id"])
                continue
            created = create_transaction(
                engine,
                {
                    "account_id": account_id,
                    "trans_code": code,
                    "trans_amount": amount,
                    "trans_date": row["date"],
                    "payee_id": payee_id,
                    "to_account_id": to_id,
                    "categ_id": categ_id,
                    "status": row["status"] if row["status"] in ("", "R", "V", "F", "D") else "",
                    "notes": row["notes"],
                },
            )
            imported.append(
                {
                    "sidecar_id": row["id"],
                    "trans_id": created["trans_id"],
                    "account_id": account_id,
                }
            )
            ok_ids.append(row["id"])
        except Exception as exc:
            errors.append({"sidecar_id": row["id"], "error": str(exc)})
    deleted = 0
    if delete_imported and not dry_run and ok_ids:
        side = create_engine(f"sqlite:///{path}")
        try:
            with side.begin() as conn:
                for sid in ok_ids:
                    conn.execute(text("DELETE FROM New_Transaction WHERE ID = :id"), {"id": sid})
            deleted = len(ok_ids)
        finally:
            side.dispose()
    return {
        "dry_run": dry_run,
        "pending": len(pending),
        "imported": len(imported),
        "errors": errors,
        "created": {"payees": created_payees, "categories": created_categories},
        "deleted_from_sidecar": deleted,
        "rows": imported,
    }
