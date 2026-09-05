"""Fuzzy matcher ported from bank-reconciliation-app (FuzzyMatcher + MmexDatabase)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.engine import Engine

from mmex_recon.schemas import (
    BankTransaction,
    MatchCandidate,
    MatchStatus,
    MmexTransaction,
    TransactionMatch,
)

AMOUNT_TOLERANCE = Decimal("0.01")
# config.py in bank-reconciliation-app
TOLERANCE_DAYS = 4
THRESHOLD = 75.0


def _amounts_equal(a: object, b: object) -> bool:
    return abs(Decimal(str(a)) - Decimal(str(b))) <= AMOUNT_TOLERANCE


def _parse_day(raw: object) -> date:
    text = str(raw or "")[:10]
    return date.fromisoformat(text)


def _row_to_local(row: Any) -> MmexTransaction:
    amount = Decimal(str(row[5] or 0))
    trans_code = row[4] or ""
    if trans_code in ("Withdrawal", "Transfer"):
        amount = -amount
    to_account_id = int(row[11]) if row[11] and int(row[11]) > 0 else None
    return MmexTransaction(
        trans_id=int(row[0]),
        account_id=int(row[1]),
        payee_id=int(row[2]) if row[2] else None,
        payee_name=row[3],
        trans_code=trans_code,
        amount=amount,
        status=row[6] or "",
        trans_date=_parse_day(row[7]),
        notes=row[8] or "",
        category_id=int(row[9]) if row[9] and int(row[9]) > 0 else None,
        category_name=row[10],
        to_account_id=to_account_id,
        counterpart_account_name=row[12] or None,
        is_inbound_transfer=False,
    )


def _row_to_inbound(row: Any) -> MmexTransaction:
    source_name = row[2] or ""
    amount = Decimal(str(row[7] or 0))
    return MmexTransaction(
        trans_id=int(row[0]),
        account_id=int(row[1]),
        payee_id=int(row[4]) if row[4] else None,
        payee_name=source_name or row[5] or "Virement entrant",
        trans_code=row[6] or "Transfer",
        amount=amount,
        status=row[8] or "",
        trans_date=_parse_day(row[9]),
        notes=row[10] or "",
        category_id=int(row[11]) if row[11] and int(row[11]) > 0 else None,
        category_name=row[12],
        to_account_id=int(row[3]) if row[3] else None,
        counterpart_account_name=source_name or None,
        is_inbound_transfer=True,
    )


def load_candidates(
    engine: Engine, account_id: int, start: date, end: date
) -> list[MmexTransaction]:
    """Local rows on the account plus inbound transfers (source-account counterpart)."""
    params = {
        "account_id": account_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    local_sql = """
        SELECT ca.TRANSID, ca.ACCOUNTID, ca.PAYEEID, p.PAYEENAME,
               ca.TRANSCODE, ca.TRANSAMOUNT, ca.STATUS, ca.TRANSDATE,
               COALESCE(ca.NOTES, ''), ca.CATEGID, c.CATEGNAME,
               ca.TOACCOUNTID, dest.ACCOUNTNAME
          FROM CHECKINGACCOUNT_V1 ca
          LEFT JOIN PAYEE_V1 p ON ca.PAYEEID = p.PAYEEID
          LEFT JOIN CATEGORY_V1 c ON ca.CATEGID = c.CATEGID
          LEFT JOIN ACCOUNTLIST_V1 dest
            ON ca.TOACCOUNTID = dest.ACCOUNTID AND ca.TOACCOUNTID > 0
         WHERE ca.ACCOUNTID = :account_id
           AND (ca.DELETEDTIME IS NULL OR ca.DELETEDTIME = '')
           AND date(substr(ca.TRANSDATE, 1, 10)) >= date(:start)
           AND date(substr(ca.TRANSDATE, 1, 10)) <= date(:end)
         ORDER BY ca.TRANSDATE
    """
    inbound_sql = """
        SELECT ca.TRANSID, ca.ACCOUNTID, src.ACCOUNTNAME, ca.TOACCOUNTID,
               ca.PAYEEID, p.PAYEENAME, ca.TRANSCODE,
               COALESCE(NULLIF(ca.TOTRANSAMOUNT, 0), ca.TRANSAMOUNT), ca.STATUS,
               ca.TRANSDATE, COALESCE(ca.NOTES, ''), ca.CATEGID, c.CATEGNAME
          FROM CHECKINGACCOUNT_V1 ca
          LEFT JOIN ACCOUNTLIST_V1 src ON ca.ACCOUNTID = src.ACCOUNTID
          LEFT JOIN PAYEE_V1 p ON ca.PAYEEID = p.PAYEEID
          LEFT JOIN CATEGORY_V1 c ON ca.CATEGID = c.CATEGID
         WHERE ca.TOACCOUNTID = :account_id
           AND ca.TRANSCODE = 'Transfer'
           AND (ca.DELETEDTIME IS NULL OR ca.DELETEDTIME = '')
           AND date(substr(ca.TRANSDATE, 1, 10)) >= date(:start)
           AND date(substr(ca.TRANSDATE, 1, 10)) <= date(:end)
         ORDER BY ca.TRANSDATE
    """
    out: list[MmexTransaction] = []
    seen: set[int] = set()
    with engine.connect() as conn:
        for row in conn.execute(text(local_sql), params):
            tx = _row_to_local(row)
            out.append(tx)
            seen.add(tx.trans_id)
        for row in conn.execute(text(inbound_sql), params):
            tx = _row_to_inbound(row)
            if tx.trans_id not in seen:
                out.append(tx)
                seen.add(tx.trans_id)
    return out


def _is_invoice_payment(bank_tx: BankTransaction) -> bool:
    return bank_tx.amount > 0 and "paiement" in bank_tx.description.lower()


def _transfer_description_score(bank_tx: BankTransaction, mmex_tx: MmexTransaction) -> float:
    bank_desc = bank_tx.description.lower()
    scores: list[float] = []
    counterpart = (mmex_tx.counterpart_account_name or "").strip()
    if counterpart:
        counterpart_lower = counterpart.lower()
        scores.extend(
            [
                float(fuzz.partial_ratio(counterpart_lower, bank_desc)),
                float(fuzz.token_set_ratio(counterpart_lower, bank_desc)),
            ]
        )
    alias_checks = (
        ("visa cashback", ("swisscard", "visa cashback", "aecs")),
        ("banque cler", ("bank cler", "cler ag", "cler")),
        ("axa police", ("axa leben", "axa")),
        ("postfinance ludivine", ("ludivine", "27145747")),
        ("postfinance thomas", ("thomas", "27145772")),
    )
    for account_key, keywords in alias_checks:
        if account_key in counterpart.lower() and any(kw in bank_desc for kw in keywords):
            scores.append(92.0)
    payee = (mmex_tx.payee_name or "").strip()
    if payee and payee.lower() not in {"inconnu", "unknown"}:
        scores.append(float(fuzz.token_set_ratio(payee.lower(), bank_desc)))
    if mmex_tx.notes:
        scores.append(float(fuzz.token_set_ratio(mmex_tx.notes.lower(), bank_desc)))
    return max(scores) if scores else 0.0


def _description_score(bank_tx: BankTransaction, mmex_tx: MmexTransaction) -> float:
    if _is_invoice_payment(bank_tx) and mmex_tx.is_inbound_transfer:
        return 95.0
    if mmex_tx.trans_code == "Transfer" or mmex_tx.is_inbound_transfer:
        transfer_score = _transfer_description_score(bank_tx, mmex_tx)
        if transfer_score > 0:
            return transfer_score
    bank_desc = bank_tx.description
    mmex_desc = mmex_tx.payee_name or ""
    if mmex_tx.counterpart_account_name:
        mmex_desc = f"{mmex_tx.counterpart_account_name} {mmex_desc}"
    if mmex_tx.notes:
        mmex_desc += " " + mmex_tx.notes
    if not mmex_desc:
        return 0.0
    return float(fuzz.token_set_ratio(bank_desc.lower(), mmex_desc.lower()))


def _amount_match(bank_amount: Decimal, mmex_tx: MmexTransaction, credit_card: bool) -> bool:
    if _amounts_equal(bank_amount, mmex_tx.amount):
        return True
    if not credit_card:
        return False
    if not _amounts_equal(abs(Decimal(str(bank_amount))), abs(Decimal(str(mmex_tx.amount)))):
        return False
    bank_amt = Decimal(str(bank_amount))
    mmex_amt = Decimal(str(mmex_tx.amount))
    if bank_amt < 0 and mmex_amt > 0:
        return True
    if bank_amt > 0 and mmex_amt < 0:
        return True
    return False


def _pick_auto_candidate(
    candidates: list[MatchCandidate], reserved_ids: set[int]
) -> MatchCandidate | None:
    for cand in candidates:
        if cand.mmex_transaction.trans_id in reserved_ids:
            continue
        if cand.amount_match and cand.score >= THRESHOLD:
            return cand
    return None


def _pick_review_candidate(
    candidates: list[MatchCandidate], reserved_ids: set[int]
) -> MatchCandidate:
    for cand in candidates:
        if cand.mmex_transaction.trans_id not in reserved_ids:
            return cand
    return candidates[0]


def match_transaction(
    bank_tx: BankTransaction,
    mmex_transactions: list[MmexTransaction],
    used_trans_ids: set[int] | None = None,
    *,
    credit_card: bool = False,
) -> TransactionMatch:
    reserved_ids = used_trans_ids or set()
    candidates: list[MatchCandidate] = []
    bank_amount = bank_tx.amount
    for mmex_tx in mmex_transactions:
        date_delta = abs((bank_tx.date - mmex_tx.trans_date).days)
        if date_delta > TOLERANCE_DAYS:
            continue
        amount_ok = _amount_match(bank_amount, mmex_tx, credit_card)
        same_sign = _amounts_equal(bank_amount, mmex_tx.amount)
        desc_score = _description_score(bank_tx, mmex_tx)
        date_score = max(0, 100 - date_delta * 15)
        score = desc_score * 0.7 + date_score * 0.3
        if amount_ok:
            score += 30 if same_sign else 20
        if amount_ok and _is_invoice_payment(bank_tx) and mmex_tx.is_inbound_transfer:
            score = max(score, THRESHOLD + 10)
        if score >= THRESHOLD - 20 or amount_ok:
            candidates.append(
                MatchCandidate(
                    mmex_transaction=mmex_tx,
                    score=score,
                    amount_match=amount_ok,
                    date_delta_days=date_delta,
                )
            )
    candidates.sort(
        key=lambda c: (c.mmex_transaction.trans_id in reserved_ids, -c.score)
    )
    status = MatchStatus.NO_MATCH
    selected_id = None
    selected_payee = None
    category_id = None
    category_name = None
    if candidates:
        auto = _pick_auto_candidate(candidates, reserved_ids)
        if auto:
            status = MatchStatus.AUTO_MATCHED
            selected_id = auto.mmex_transaction.trans_id
            selected_payee = auto.mmex_transaction.payee_name
            category_id = auto.mmex_transaction.category_id
            category_name = auto.mmex_transaction.category_name
        else:
            best = _pick_review_candidate(candidates, reserved_ids)
            if best.amount_match:
                status = MatchStatus.FUZZY_MATCHED
                selected_payee = best.mmex_transaction.payee_name
                category_id = best.mmex_transaction.category_id
                category_name = best.mmex_transaction.category_name
            else:
                status = MatchStatus.AMOUNT_MISMATCH
    include = status not in (MatchStatus.FUZZY_MATCHED, MatchStatus.AMOUNT_MISMATCH)
    return TransactionMatch(
        bank_transaction=bank_tx,
        status=status,
        candidates=candidates[:5],
        selected_trans_id=selected_id,
        selected_payee_name=selected_payee,
        category_id=category_id,
        category_name=category_name,
        normalized_description=bank_tx.description,
        include=include,
    )


def match_all(
    bank_txs: list[BankTransaction],
    mmex_txs: list[MmexTransaction],
    *,
    credit_card: bool = False,
) -> list[TransactionMatch]:
    used: set[int] = set()
    results: list[TransactionMatch] = []
    for bank in bank_txs:
        result = match_transaction(bank, mmex_txs, used, credit_card=credit_card)
        if result.selected_trans_id is not None:
            used.add(result.selected_trans_id)
        results.append(result)
    return results


def session_public(payload: dict[str, Any]) -> dict[str, Any]:
    return payload
