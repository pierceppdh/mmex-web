"""Parse Paperless PDFs, match against the ledger, commit under WriterLock."""

from __future__ import annotations

import logging
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Engine

from mmex_domain.recon import list_account_refs, match_statement_account
from mmex_domain.recon_commit import apply_operations
from mmex_recon.matcher import TOLERANCE_DAYS, load_candidates, match_all
from mmex_recon.parsers.registry import registry
from mmex_recon.schemas import MatchStatus, ParsedStatement, ReconciliationSession, TransactionMatch
from mmex_web_api.config import Settings
from mmex_web_api.paperless import download_document

logger = logging.getLogger(__name__)


def parse_pdf_bytes(data: bytes, filename: str) -> ParsedStatement:
    suffix = Path(filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return registry.parse(Path(tmp.name))


def _credit_card(engine: Engine, account_id: int) -> bool:
    for acc in list_account_refs(engine):
        if int(acc["account_id"]) == account_id:
            return acc.get("account_type") == "Credit Card"
    return False


def _account_name(engine: Engine, account_id: int) -> str:
    for acc in list_account_refs(engine):
        if int(acc["account_id"]) == account_id:
            return str(acc["name"])
    return f"Compte {account_id}"


def build_session(
    engine: Engine,
    settings: Settings,
    *,
    paperless_id: int,
    account_id: int,
    currency: str | None = None,
) -> dict[str, Any]:
    data, filename = download_document(settings, paperless_id)
    statement = parse_pdf_bytes(data, filename)
    if currency:
        statement = statement.with_currency(currency)
    detected = match_statement_account(statement, list_account_refs(engine))
    if detected:
        account_id = int(detected["account_id"])
    txs = statement.transactions
    if not txs:
        session = ReconciliationSession(
            source=f"paperless:{paperless_id}",
            statement=statement,
            account_id=account_id,
            account_name=_account_name(engine, account_id),
            paperless_doc_id=paperless_id,
        )
        payload = {"id": uuid4().hex, **session.model_dump(mode="json")}
        payload["suggested_account_id"] = int(detected["account_id"]) if detected else None
        return payload
    start = min(t.date for t in txs) - timedelta(days=TOLERANCE_DAYS)
    end = max(t.date for t in txs) + timedelta(days=TOLERANCE_DAYS)
    mmex = load_candidates(engine, account_id, start, end)
    matches = match_all(txs, mmex, credit_card=_credit_card(engine, account_id))
    session = ReconciliationSession(
        source=f"paperless:{paperless_id}",
        statement=statement,
        account_id=account_id,
        account_name=_account_name(engine, account_id),
        matches=matches,
        paperless_doc_id=paperless_id,
    )
    payload = {"id": uuid4().hex, **session.model_dump(mode="json")}
    payload["suggested_account_id"] = int(detected["account_id"]) if detected else None
    return payload


def preview_document(
    engine: Engine, settings: Settings, paperless_id: int
) -> dict[str, Any]:
    data, filename = download_document(settings, paperless_id)
    statement = parse_pdf_bytes(data, filename)
    detected = match_statement_account(statement, list_account_refs(engine))
    last4 = statement.card_last4()
    return {
        "paperless_id": paperless_id,
        "filename": filename,
        "parser_id": statement.parser_id,
        "bank_name": statement.bank_name,
        "iban": statement.iban,
        "account_number": statement.account_number,
        "currency": statement.currency,
        "card_last4": last4,
        "suggested_account_id": int(detected["account_id"]) if detected else None,
        "suggested_account_name": detected["name"] if detected else None,
        "transaction_count": len(statement.transactions),
    }


def _match_from_dict(item: dict[str, Any]) -> TransactionMatch:
    return TransactionMatch.model_validate(item)


def build_operations(session: dict[str, Any]) -> list[dict[str, Any]]:
    account_id = int(session["account_id"])
    ops: list[dict[str, Any]] = []
    for raw in session.get("matches") or []:
        match = _match_from_dict(raw)
        if not match.include or match.status == MatchStatus.SKIP:
            continue
        bank = match.bank_transaction
        if match.selected_trans_id:
            ops.append({"type": "reconcile", "trans_id": match.selected_trans_id})
        elif match.insert_as_transfer and match.transfer_counterpart_account_id:
            amount = bank.amount
            bank_abs = abs(amount)
            other = match.transfer_counterpart_amount
            other_abs = abs(Decimal(str(other))) if other is not None else bank_abs
            if amount > 0:
                ops.append(
                    {
                        "type": "transfer",
                        "from_account_id": match.transfer_counterpart_account_id,
                        "to_account_id": account_id,
                        "amount": other_abs,
                        "to_amount": bank_abs,
                        "trans_date": bank.date,
                        "category_id": match.category_id,
                        "notes": bank.description,
                    }
                )
            else:
                ops.append(
                    {
                        "type": "transfer",
                        "from_account_id": account_id,
                        "to_account_id": match.transfer_counterpart_account_id,
                        "amount": bank_abs,
                        "to_amount": other_abs,
                        "trans_date": bank.date,
                        "category_id": match.category_id,
                        "notes": bank.description,
                    }
                )
        else:
            raw_amt = Decimal(str(bank.amount))
            forced = (match.force_trans_code or "").strip()
            if forced == "Deposit":
                signed, code = abs(raw_amt), "Deposit"
            elif forced == "Withdrawal":
                signed, code = -abs(raw_amt), "Withdrawal"
            elif raw_amt > 0:
                signed, code = raw_amt, "Deposit"
            else:
                signed, code = raw_amt, "Withdrawal"
            ops.append(
                {
                    "type": "insert",
                    "account_id": account_id,
                    "payee_name": match.selected_payee_name or bank.description[:80],
                    "amount": signed,
                    "trans_code": code,
                    "trans_date": bank.date,
                    "category_id": match.category_id or -1,
                    "notes": bank.description,
                }
            )
    return ops


def duplicate_trans_ids(session: dict[str, Any]) -> list[int]:
    seen: dict[int, int] = {}
    dup: list[int] = []
    for i, raw in enumerate(session.get("matches") or []):
        if not raw.get("include") or not raw.get("selected_trans_id"):
            continue
        tid = int(raw["selected_trans_id"])
        if tid in seen:
            dup.extend([seen[tid], i])
        else:
            seen[tid] = i
    return sorted(set(dup))


def commit_session(engine: Engine, session: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    dups = duplicate_trans_ids(session)
    if dups:
        return {
            "success": False,
            "message": f"Plusieurs lignes pointent le même TRANSID (lignes {dups})",
            "inserted": 0,
        }
    ops = build_operations(session)
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "to_insert_count": sum(1 for o in ops if o["type"] == "insert"),
            "to_transfer_count": sum(1 for o in ops if o["type"] == "transfer"),
            "to_reconcile_count": sum(1 for o in ops if o["type"] == "reconcile"),
            "message": f"Dry-run: {len(ops)} opération(s)",
        }
    if not ops:
        return {"success": False, "message": "Aucune ligne incluse", "inserted": 0}
    result = apply_operations(engine, ops)
    return {
        "success": True,
        "dry_run": False,
        "inserted": len(result["inserted"]),
        "reconciled": len(result["reconciled"]),
        "inserted_ids": result["inserted"],
        "reconciled_ids": result["reconciled"],
        "message": (
            f"{len(result['inserted'])} insérées, {len(result['reconciled'])} pointées"
        ),
    }
