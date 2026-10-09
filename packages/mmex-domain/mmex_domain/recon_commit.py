"""Apply recon operations to CHECKINGACCOUNT_V1 under an existing writer lock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.accounts import AccountError, assert_writable
from mmex_domain.constants import NOT_SET, STATUS_RECONCILED, TRANS_TRANSFER
from mmex_domain.managers import ManagerError, create_payee
from mmex_domain.money import as_decimal, format_cents
from mmex_domain.transactions import TransactionError, create_transaction

_CENT = Decimal("0.01")


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


def _abs_money(value: object) -> Decimal:
    return Decimal(format_cents(abs(as_decimal(value))))


def _same_abs(left: object, right: object) -> bool:
    """True when two magnitudes are equal or one cent apart."""
    return abs(_abs_money(left) - _abs_money(right)) <= _CENT


@dataclass(frozen=True)
class _AmountPlan:
    trans_amount: Decimal | None
    to_trans_amount: Decimal | None
    splits: tuple[tuple[int, Decimal], ...]


def _load_booking(conn: Connection, trans_id: int) -> Any:
    return conn.execute(
        text(
            """
            SELECT ACCOUNTID, TOACCOUNTID, TRANSCODE, TRANSAMOUNT, TOTRANSAMOUNT,
                   TRANSDATE, DELETEDTIME
              FROM CHECKINGACCOUNT_V1
             WHERE TRANSID = :id
            """
        ),
        {"id": trans_id},
    ).fetchone()


def _is_inbound(row: Any, statement_account_id: int) -> bool:
    to_account = int(row[1] or 0)
    return (
        (row[2] or "") == TRANS_TRANSFER
        and to_account == int(statement_account_id)
        and int(row[0]) != int(statement_account_id)
    )


def _visible_amount(row: Any, statement_account_id: int) -> Decimal:
    """Amount the statement account shows: source amount, or destination for an inbound transfer."""
    trans_amount = as_decimal(row[3])
    to_amount = as_decimal(row[4])
    if _is_inbound(row, statement_account_id):
        return to_amount if to_amount != 0 else trans_amount
    return trans_amount


def _load_splits(conn: Connection, trans_id: int) -> list[tuple[int, Decimal]]:
    rows = conn.execute(
        text(
            """
            SELECT SPLITTRANSID, SPLITTRANSAMOUNT
              FROM SPLITTRANSACTIONS_V1
             WHERE TRANSID = :id
             ORDER BY SPLITTRANSID
            """
        ),
        {"id": trans_id},
    ).fetchall()
    return [(int(split_id), as_decimal(amount)) for split_id, amount in rows]


def _rescale_splits(
    splits: list[tuple[int, Decimal]], old_amount: Decimal, new_amount: Decimal
) -> tuple[tuple[int, Decimal], ...]:
    """Keep each split’s share of TRANSAMOUNT. The last line absorbs rounding."""
    if not splits:
        return ()
    old = _abs_money(old_amount)
    new = _abs_money(new_amount)
    if old == 0:
        raise TransactionError("cannot rescale splits from a zero amount")
    if any(amount <= 0 for _, amount in splits):
        raise TransactionError("split amount must stay positive")
    scaled: list[tuple[int, Decimal]] = []
    allocated = Decimal("0.00")
    for split_id, amount in splits[:-1]:
        piece = (abs(amount) * new / old).quantize(_CENT, rounding=ROUND_HALF_UP)
        if piece <= 0:
            raise TransactionError("split amount must stay positive")
        scaled.append((split_id, piece))
        allocated += piece
    last = (new - allocated).quantize(_CENT, rounding=ROUND_HALF_UP)
    if last <= 0:
        raise TransactionError("split amount must stay positive")
    scaled.append((splits[-1][0], last))
    return tuple(scaled)


def _guard_amount_change(conn: Connection, row: Any) -> None:
    to_account = int(row[1] or 0)
    dest = to_account if (row[2] or "") == TRANS_TRANSFER and to_account > 0 else None
    try:
        assert_writable(conn, int(row[0]), row[5], to_account_id=dest)
    except AccountError as exc:
        raise TransactionError(str(exc)) from exc


def adjustment_plan(conn: Connection, op: dict[str, Any]) -> _AmountPlan | None:
    """How to align one linked booking onto the bank amount.

    Returns None when the visible amount already matches, so reconcile only
    sets the status. A locked statement blocks the amount change before any write.
    """
    if op.get("amount") is None or op.get("account_id") is None:
        return None
    row = _load_booking(conn, int(op["trans_id"]))
    if row is None or row[6]:
        return None
    statement_account_id = int(op["account_id"])
    target = _abs_money(op["amount"])
    visible = _visible_amount(row, statement_account_id)
    if not _needs_amount_change(visible, target):
        return None
    _guard_amount_change(conn, row)
    trans_amount = as_decimal(row[3])
    to_amount = as_decimal(row[4])
    new_trans: Decimal | None = None
    new_to: Decimal | None = None
    if _is_inbound(row, statement_account_id):
        # The statement sees the destination amount. Keep a different source amount
        # when the two legs are already in different currencies.
        shown = to_amount if to_amount != 0 else trans_amount
        new_to = target
        if _same_abs(trans_amount, shown):
            new_trans = target
    else:
        new_trans = target
        if (row[2] or "") != TRANS_TRANSFER or _same_abs(to_amount, trans_amount):
            new_to = target
    splits: tuple[tuple[int, Decimal], ...] = ()
    if new_trans is not None and _needs_amount_change(trans_amount, new_trans):
        splits = _rescale_splits(_load_splits(conn, int(op["trans_id"])), trans_amount, new_trans)
    return _AmountPlan(new_trans, new_to, splits)


def _needs_amount_change(current: object, target: object) -> bool:
    """True when the two amounts differ by at least one cent after rounding."""
    return _abs_money(current) != _abs_money(target)


def count_amount_adjustments(engine: Engine, operations: list[dict[str, Any]]) -> int:
    count = 0
    with engine.connect() as conn:
        for op in operations:
            if op.get("type") != "reconcile":
                continue
            if adjustment_plan(conn, op) is not None:
                count += 1
    return count


def _write_reconcile(conn: Connection, trans_id: int, plan: _AmountPlan | None) -> None:
    sets = ["STATUS = :status", "LASTUPDATEDTIME = datetime('now')"]
    params: dict[str, Any] = {"status": STATUS_RECONCILED, "id": trans_id}
    if plan is not None and plan.trans_amount is not None:
        sets.append("TRANSAMOUNT = :amt")
        params["amt"] = format_cents(plan.trans_amount)
    if plan is not None and plan.to_trans_amount is not None:
        sets.append("TOTRANSAMOUNT = :toamt")
        params["toamt"] = format_cents(plan.to_trans_amount)
    conn.execute(
        text(
            f"""
            UPDATE CHECKINGACCOUNT_V1
               SET {", ".join(sets)}
             WHERE TRANSID = :id
               AND (DELETEDTIME IS NULL OR DELETEDTIME = '')
            """
        ),
        params,
    )
    if plan is None:
        return
    for split_id, amount in plan.splits:
        conn.execute(
            text(
                """
                UPDATE SPLITTRANSACTIONS_V1
                   SET SPLITTRANSAMOUNT = :amt
                 WHERE SPLITTRANSID = :sid
                """
            ),
            {"amt": format_cents(amount), "sid": split_id},
        )


def _reconcile(engine: Engine, op: dict[str, Any]) -> bool:
    """Mark one booking reconciled and, when the amounts differ, copy the bank amount."""
    trans_id = int(op["trans_id"])
    with engine.begin() as conn:
        plan = adjustment_plan(conn, op)
        _write_reconcile(conn, trans_id, plan)
    return plan is not None


def apply_operations(engine: Engine, operations: list[dict[str, Any]]) -> dict[str, Any]:
    inserted: list[int] = []
    reconciled: list[int] = []
    adjusted: list[int] = []
    for op in operations:
        kind = op["type"]
        if kind == "reconcile":
            trans_id = int(op["trans_id"])
            if _reconcile(engine, op):
                adjusted.append(trans_id)
            reconciled.append(trans_id)
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
    return {"inserted": inserted, "reconciled": reconciled, "adjusted": adjusted}
