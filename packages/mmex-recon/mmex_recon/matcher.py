"""Fuzzy match bank lines to MMEX checking rows (rapidfuzz)."""

from __future__ import annotations

from datetime import date
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
TOLERANCE_DAYS = 3
THRESHOLD = 70.0


def _amounts_equal(a: Decimal, b: Decimal) -> bool:
    return abs(Decimal(str(a)) - Decimal(str(b))) <= AMOUNT_TOLERANCE


def _signed_amount(code: str, amount: Decimal, inbound: bool) -> Decimal:
    amt = abs(Decimal(str(amount)))
    if inbound:
        return amt
    if code == "Deposit":
        return amt
    return -amt


def load_candidates(
    engine: Engine, account_id: int, start: date, end: date
) -> list[MmexTransaction]:
    params = {
        "account_id": account_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    sql = """
        SELECT ca.TRANSID, ca.ACCOUNTID, ca.PAYEEID, p.PAYEENAME,
               ca.TRANSCODE, ca.TRANSAMOUNT, ca.STATUS, ca.TRANSDATE,
               COALESCE(ca.NOTES, ''), ca.CATEGID, c.CATEGNAME,
               ca.TOACCOUNTID, dest.ACCOUNTNAME
          FROM CHECKINGACCOUNT_V1 ca
          LEFT JOIN PAYEE_V1 p ON ca.PAYEEID = p.PAYEEID
          LEFT JOIN CATEGORY_V1 c ON ca.CATEGID = c.CATEGID
          LEFT JOIN ACCOUNTLIST_V1 dest
            ON ca.TOACCOUNTID = dest.ACCOUNTID AND ca.TOACCOUNTID > 0
         WHERE (ca.DELETEDTIME IS NULL OR ca.DELETEDTIME = '')
           AND date(substr(ca.TRANSDATE, 1, 10)) >= date(:start)
           AND date(substr(ca.TRANSDATE, 1, 10)) <= date(:end)
           AND COALESCE(ca.STATUS, '') != 'R'
           AND (ca.ACCOUNTID = :account_id OR ca.TOACCOUNTID = :account_id)
         ORDER BY ca.TRANSDATE
    """
    out: list[MmexTransaction] = []
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params):
            inbound = int(row[11] or 0) == account_id and row[4] == "Transfer"
            raw_date = str(row[7] or "")[:10]
            out.append(
                MmexTransaction(
                    trans_id=int(row[0]),
                    account_id=int(row[1]),
                    payee_id=int(row[2]) if row[2] else None,
                    payee_name=row[3],
                    trans_code=row[4] or "",
                    amount=_signed_amount(row[4] or "", Decimal(str(row[5] or 0)), inbound),
                    status=row[6] or "",
                    trans_date=date.fromisoformat(raw_date),
                    notes=row[8] or "",
                    category_id=int(row[9]) if row[9] not in (None, -1) else None,
                    category_name=row[10],
                    to_account_id=int(row[11]) if row[11] else None,
                    counterpart_account_name=row[12],
                    is_inbound_transfer=inbound,
                )
            )
    return out


def _desc_score(bank: BankTransaction, mmex: MmexTransaction) -> float:
    blob = " ".join(
        filter(None, [mmex.payee_name or "", mmex.notes, mmex.counterpart_account_name or ""])
    )
    if not blob.strip():
        return 0.0
    return float(fuzz.token_set_ratio(bank.description, blob))


def _amount_match(bank_amt: Decimal, mmex: MmexTransaction, credit_card: bool) -> bool:
    if _amounts_equal(bank_amt, mmex.amount):
        return True
    if credit_card and _amounts_equal(abs(bank_amt), abs(mmex.amount)):
        return True
    return False


def match_all(
    bank_txs: list[BankTransaction],
    mmex_txs: list[MmexTransaction],
    *,
    credit_card: bool = False,
) -> list[TransactionMatch]:
    used: set[int] = set()
    results: list[TransactionMatch] = []
    for bank in bank_txs:
        candidates: list[MatchCandidate] = []
        for mmex in mmex_txs:
            delta = abs((bank.date - mmex.trans_date).days)
            if delta > TOLERANCE_DAYS:
                continue
            amount_ok = _amount_match(bank.amount, mmex, credit_card)
            desc = _desc_score(bank, mmex)
            date_score = max(0, 100 - delta * 15)
            score = desc * 0.7 + date_score * 0.3
            if amount_ok:
                score += 30 if _amounts_equal(bank.amount, mmex.amount) else 20
            if score >= THRESHOLD - 20 or amount_ok:
                candidates.append(
                    MatchCandidate(
                        mmex_transaction=mmex,
                        score=score,
                        amount_match=amount_ok,
                        date_delta_days=delta,
                    )
                )
        candidates.sort(key=lambda c: (c.mmex_transaction.trans_id in used, -c.score))
        status = MatchStatus.NO_MATCH
        selected_id = None
        payee = None
        categ_id = None
        categ_name = None
        auto = None
        for cand in candidates:
            if cand.mmex_transaction.trans_id in used:
                continue
            if cand.amount_match and (cand.score >= THRESHOLD or cand.date_delta_days == 0):
                auto = cand
                break
        if auto:
            status = MatchStatus.AUTO_MATCHED
            selected_id = auto.mmex_transaction.trans_id
            payee = auto.mmex_transaction.payee_name
            categ_id = auto.mmex_transaction.category_id
            categ_name = auto.mmex_transaction.category_name
        elif candidates:
            best = next(
                (c for c in candidates if c.mmex_transaction.trans_id not in used),
                candidates[0],
            )
            if best.amount_match:
                status = MatchStatus.FUZZY_MATCHED
                payee = best.mmex_transaction.payee_name
                categ_id = best.mmex_transaction.category_id
                categ_name = best.mmex_transaction.category_name
            else:
                status = MatchStatus.AMOUNT_MISMATCH
        include = status not in (MatchStatus.FUZZY_MATCHED, MatchStatus.AMOUNT_MISMATCH)
        if selected_id:
            used.add(selected_id)
        results.append(
            TransactionMatch(
                bank_transaction=bank,
                status=status,
                candidates=candidates[:5],
                selected_trans_id=selected_id,
                selected_payee_name=payee or bank.description[:80],
                category_id=categ_id,
                category_name=categ_name,
                normalized_description=bank.description,
                include=include,
            )
        )
    return results


def session_public(payload: dict[str, Any]) -> dict[str, Any]:
    return payload
