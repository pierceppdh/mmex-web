"""Phone-grade capture that writes CHECKINGACCOUNT_V1 (not the PHP sidecar)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine

from mmex_domain.constants import NOT_SET, TRANS_TRANSFER
from mmex_domain.io import _ensure_category, _ensure_payee
from mmex_domain.kv import DEFAULT_ACCOUNT_KEY, kv_get_engine, kv_set
from mmex_domain.transactions import create_transaction

LAST_ACCOUNT_KEY = "MMEXWEB_LAST_ACCOUNT"


class QuickaddError(ValueError):
    """Invalid quick-add payload."""


def _id_setting(engine: Engine, name: str) -> int | None:
    raw = kv_get_engine(engine, name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def last_account_id(engine: Engine) -> int | None:
    return _id_setting(engine, LAST_ACCOUNT_KEY)


def default_account_id(engine: Engine) -> int | None:
    return _id_setting(engine, DEFAULT_ACCOUNT_KEY)


def add_quick(engine: Engine, data: dict[str, Any]) -> dict[str, Any]:
    code = str(data.get("trans_code") or "Withdrawal")
    payee_id = int(data.get("payee_id") or 0)
    payee_name = str(data.get("payee_name") or "").strip()
    categ_id = int(data.get("categ_id") or 0)
    categ_path = str(data.get("category") or "").strip()
    created_payee = False
    created_category = False
    with engine.begin() as conn:
        if code != TRANS_TRANSFER:
            if payee_id <= 0:
                if not payee_name:
                    raise QuickaddError("payee is required")
                payee_id, created_payee = _ensure_payee(conn, payee_name)
            if categ_id <= 0 and categ_path:
                categ_id, created_category = _ensure_category(conn, categ_path)
        account_id = int(data.get("account_id") or 0)
        if account_id <= 0:
            raise QuickaddError("account_id is required")
        kv_set(conn, LAST_ACCOUNT_KEY, str(account_id))
    payload = {
        "account_id": account_id,
        "trans_code": code,
        "trans_amount": data.get("trans_amount"),
        "trans_date": data.get("trans_date"),
        "payee_id": payee_id if code != TRANS_TRANSFER else NOT_SET,
        "to_account_id": data.get("to_account_id"),
        "to_trans_amount": data.get("to_trans_amount"),
        "categ_id": categ_id if categ_id > 0 else NOT_SET,
        "status": data.get("status") or "",
        "notes": data.get("notes") or "",
        "transaction_number": data.get("transaction_number") or "",
    }
    created = create_transaction(engine, payload)
    created["created_payee"] = created_payee
    created["created_category"] = created_category
    created["last_account_id"] = account_id
    return created
