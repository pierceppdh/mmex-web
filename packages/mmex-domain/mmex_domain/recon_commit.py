"""Apply recon operations to CHECKINGACCOUNT_V1 under an existing writer lock."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from mmex_domain.constants import NOT_SET, STATUS_RECONCILED
from mmex_domain.managers import ManagerError, create_payee
from mmex_domain.money import as_decimal
from mmex_domain.transactions import TransactionError, create_transaction


def _payee_id(engine: Engine, name: str) -> int:
    label = (name or "Relevé").strip()[:64] or "Relevé"
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT PAYEEID FROM PAYEE_V1 WHERE PAYEENAME = :n COLLATE NOCASE"),
            {"n": label},
        ).fetchone()
    if row:
        return int(row[0])
    try:
        created = create_payee(engine, {"name": label, "categ_id": NOT_SET})
        return int(created["payee_id"])
    except ManagerError:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT PAYEEID FROM PAYEE_V1 WHERE PAYEENAME = :n COLLATE NOCASE"),
                {"n": label},
            ).fetchone()
        if row:
            return int(row[0])
        raise


def _set_reconciled(engine: Engine, trans_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE CHECKINGACCOUNT_V1
                   SET STATUS = :st, LASTUPDATEDTIME = datetime('now')
                 WHERE TRANSID = :id
                   AND (DELETEDTIME IS NULL OR DELETEDTIME = '')
                """
            ),
            {"st": STATUS_RECONCILED, "id": trans_id},
        )


def apply_operations(engine: Engine, operations: list[dict[str, Any]]) -> dict[str, Any]:
    inserted: list[int] = []
    reconciled: list[int] = []
    for op in operations:
        kind = op["type"]
        if kind == "reconcile":
            _set_reconciled(engine, int(op["trans_id"]))
            reconciled.append(int(op["trans_id"]))
        elif kind == "insert":
            raw = Decimal(str(op["amount"]))
            code = op.get("trans_code") or ("Deposit" if raw > 0 else "Withdrawal")
            payload = {
                "account_id": int(op["account_id"]),
                "trans_code": code,
                "trans_amount": abs(as_decimal(raw)),
                "trans_date": (
                    op["trans_date"].isoformat()
                    if isinstance(op["trans_date"], date)
                    else str(op["trans_date"])[:10]
                ),
                "payee_id": _payee_id(engine, str(op.get("payee_name") or "")),
                "categ_id": int(op["category_id"]) if op.get("category_id") and int(op["category_id"]) > 0 else NOT_SET,
                "status": STATUS_RECONCILED,
                "notes": str(op.get("notes") or ""),
            }
            created = create_transaction(engine, payload)
            inserted.append(int(created["trans_id"]))
            reconciled.append(int(created["trans_id"]))
        elif kind == "transfer":
            payload = {
                "account_id": int(op["from_account_id"]),
                "to_account_id": int(op["to_account_id"]),
                "trans_code": "Transfer",
                "trans_amount": abs(as_decimal(op["amount"])),
                "to_trans_amount": abs(as_decimal(op.get("to_amount") or op["amount"])),
                "trans_date": (
                    op["trans_date"].isoformat()
                    if isinstance(op["trans_date"], date)
                    else str(op["trans_date"])[:10]
                ),
                "categ_id": int(op["category_id"]) if op.get("category_id") and int(op["category_id"]) > 0 else NOT_SET,
                "status": STATUS_RECONCILED,
                "notes": str(op.get("notes") or ""),
                "payee_id": 0,
            }
            created = create_transaction(engine, payload)
            inserted.append(int(created["trans_id"]))
            reconciled.append(int(created["trans_id"]))
        else:
            raise TransactionError(f"unknown recon op {kind}")
    return {"inserted": inserted, "reconciled": reconciled}
