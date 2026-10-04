"""Match statement lines to ledger rows.

A line is linked when the amount agrees and either the payee or counterpart
is actually named in the bank text, or the amount is unique in the date window.
Partial string scores are not used: they promoted unrelated transfers that
shared a common amount.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
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
# config.py in bank-reconciliation-app
TOLERANCE_DAYS = 4
TEXT_AUTO = 80.0

# Words that appear in account titles but not on the bank line.
_GENERIC = {
    "banque",
    "bank",
    "compte",
    "comptes",
    "account",
    "epargne",
    "zak",
    "carte",
    "card",
    "credit",
    "debit",
    "virement",
    "virements",
    "transfert",
    "transfer",
    "postfinance",
    "finance",
    "post",
    "gmbh",
    "sarl",
    "ltd",
    "chf",
    "eur",
    "usd",
    "inconnu",
    "unknown",
}
_IGNORE_NAMES = {"inconnu", "unknown", "virement entrant"}
_SKIP_STATUS = {"V", "D"}
_ALIASES = (
    ("visa cashback", ("swisscard", "visa cashback", "aecs")),
    ("banque cler", ("bank cler", "cler ag", "cler")),
    ("axa police", ("axa leben", "axa")),
    ("postfinance ludivine", ("ludivine", "27145747")),
    ("postfinance thomas", ("thomas", "27145772")),
    ("mastercard", ("charge cpte carte", "carte credit postfinance", "cpte carte credit")),
    ("yuh", ("swissquote", "yuh")),
)


def _amounts_equal(a: object, b: object) -> bool:
    return abs(Decimal(str(a)) - Decimal(str(b))) <= AMOUNT_TOLERANCE


def _parse_day(raw: object) -> date:
    text = str(raw or "")[:10]
    return date.fromisoformat(text)


def _row_to_local(row: Any, account_name: str | None = None) -> MmexTransaction:
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
        account_name=account_name or None,
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


def supplement_foreign_amounts(
    engine: Engine,
    account_id: int,
    start: date,
    end: date,
    bank_txs: list[BankTransaction],
    mmex: list[MmexTransaction],
    *,
    credit_card: bool = False,
) -> list[MmexTransaction]:
    """Add ledger rows booked on another account when no local amount matches.

    A transfer entered on the savings account still belongs to a payment the
    checking statement shows, as long as the amount and the counterpart agree.
    """
    missing = [
        bank.amount
        for bank in bank_txs
        if not any(_amount_match(bank.amount, tx, credit_card) for tx in mmex)
    ]
    if not missing:
        return mmex
    extra = _load_foreign_amounts(
        engine, account_id, start, end, missing, credit_card=credit_card
    )
    seen = {tx.trans_id for tx in mmex}
    return mmex + [tx for tx in extra if tx.trans_id not in seen]


def _load_foreign_amounts(
    engine: Engine,
    account_id: int,
    start: date,
    end: date,
    amounts: list[Decimal],
    *,
    credit_card: bool,
) -> list[MmexTransaction]:
    targets: list[Decimal] = []
    seen_amounts: set[Decimal] = set()
    for raw in amounts:
        key = abs(Decimal(str(raw))).quantize(Decimal("0.01"))
        if key == 0 or key in seen_amounts:
            continue
        seen_amounts.add(key)
        targets.append(key)
    if not targets:
        return []
    params: dict[str, Any] = {
        "account_id": account_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    pieces: list[str] = []
    for index, key in enumerate(targets):
        params[f"a{index}"] = float(key)
        pieces.append(
            "("
            f"ABS(ABS(CAST(ca.TRANSAMOUNT AS REAL)) - :a{index}) <= 0.02"
            " OR ABS(ABS(CAST(COALESCE(NULLIF(ca.TOTRANSAMOUNT, 0), ca.TRANSAMOUNT) AS REAL))"
            f" - :a{index}) <= 0.02"
            ")"
        )
    sql = f"""
        SELECT ca.TRANSID, ca.ACCOUNTID, ca.PAYEEID, p.PAYEENAME,
               ca.TRANSCODE, ca.TRANSAMOUNT, ca.STATUS, ca.TRANSDATE,
               COALESCE(ca.NOTES, ''), ca.CATEGID, c.CATEGNAME,
               ca.TOACCOUNTID, dest.ACCOUNTNAME, src.ACCOUNTNAME
          FROM CHECKINGACCOUNT_V1 ca
          LEFT JOIN PAYEE_V1 p ON ca.PAYEEID = p.PAYEEID
          LEFT JOIN CATEGORY_V1 c ON ca.CATEGID = c.CATEGID
          LEFT JOIN ACCOUNTLIST_V1 dest
            ON ca.TOACCOUNTID = dest.ACCOUNTID AND ca.TOACCOUNTID > 0
          LEFT JOIN ACCOUNTLIST_V1 src ON ca.ACCOUNTID = src.ACCOUNTID
         WHERE ca.ACCOUNTID != :account_id
           AND NOT (ca.TRANSCODE = 'Transfer' AND ca.TOACCOUNTID = :account_id)
           AND (ca.DELETEDTIME IS NULL OR ca.DELETEDTIME = '')
           AND date(substr(ca.TRANSDATE, 1, 10)) >= date(:start)
           AND date(substr(ca.TRANSDATE, 1, 10)) <= date(:end)
           AND ({" OR ".join(pieces)})
         ORDER BY ca.TRANSDATE
    """
    found: list[MmexTransaction] = []
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params):
            tx = _row_to_local(row, account_name=row[13] or None)
            if _status(tx) in _SKIP_STATUS:
                continue
            if any(_amount_match(amount, tx, credit_card) for amount in amounts):
                found.append(tx)
    return found


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", _fold(value))
        if len(token) >= 4 and not token.isdigit()
    ]


def _status(tx: MmexTransaction) -> str:
    return (tx.status or "").strip().upper()


def _reconciled(tx: MmexTransaction) -> bool:
    return _status(tx) == "R"


def _is_invoice_payment(bank_tx: BankTransaction) -> bool:
    return bank_tx.amount > 0 and "paiement" in bank_tx.description.lower()


def _date_delta(bank_tx: BankTransaction, mmex_tx: MmexTransaction) -> int:
    deltas = [abs((bank_tx.date - mmex_tx.trans_date).days)]
    if bank_tx.value_date is not None:
        deltas.append(abs((bank_tx.value_date - mmex_tx.trans_date).days))
    return min(deltas)


def _token_in(token: str, bank_tokens: set[str]) -> bool:
    if token in bank_tokens:
        return True
    for other in bank_tokens:
        if abs(len(other) - len(token)) > 1:
            continue
        if fuzz.ratio(token, other) >= 90:
            return True
    return False


def _name_score(name: str | None, bank_tokens: set[str]) -> float:
    if not name:
        return 0.0
    if _fold(name).strip() in _IGNORE_NAMES:
        return 0.0
    parts = _tokens(name)
    specific = [token for token in parts if token not in _GENERIC]
    usable = specific or parts
    if not usable:
        return 0.0
    if all(_token_in(token, bank_tokens) for token in usable):
        return 96.0
    return 0.0


def _alias_score(bank_tx: BankTransaction, mmex_tx: MmexTransaction) -> float:
    counterpart = _fold(mmex_tx.counterpart_account_name or "")
    if not counterpart:
        return 0.0
    bank = _fold(bank_tx.description)
    for account_key, keywords in _ALIASES:
        if account_key in counterpart and any(word in bank for word in keywords):
            return 92.0
    return 0.0


def _text_score(bank_tx: BankTransaction, mmex_tx: MmexTransaction) -> float:
    if _is_invoice_payment(bank_tx) and mmex_tx.is_inbound_transfer:
        return 95.0
    bank_tokens = set(_tokens(bank_tx.description))
    return max(
        _alias_score(bank_tx, mmex_tx),
        _name_score(mmex_tx.payee_name, bank_tokens),
        _name_score(mmex_tx.counterpart_account_name, bank_tokens),
        _name_score(mmex_tx.notes, bank_tokens),
    )


def _counterpart_text(bank_tx: BankTransaction, mmex_tx: MmexTransaction) -> float:
    bank_tokens = set(_tokens(bank_tx.description))
    return max(
        _alias_score(bank_tx, mmex_tx),
        _name_score(mmex_tx.counterpart_account_name, bank_tokens),
    )


def _same_bank(left: str | None, right: str | None) -> bool:
    """True when two account titles share a bank or person token."""
    if not left or not right:
        return False
    return bool(set(_tokens(left)) & set(_tokens(right)))


def _foreign_transfer_hit(
    bank_tx: BankTransaction,
    mmex_tx: MmexTransaction,
    statement_account_name: str | None,
) -> bool:
    """A row booked on another account is the same payment only for a transfer.

    Card purchases with the same shop name stay on their own account. A transfer
    entered on another account of the same bank is kept when the statement names
    the counterpart, which is how the PostFinance to Banque Cler payment is booked
    on the savings account.
    """
    if not mmex_tx.account_name:
        return True
    if mmex_tx.trans_code != "Transfer" and not mmex_tx.is_inbound_transfer:
        return False
    if not _same_bank(statement_account_name, mmex_tx.account_name):
        return False
    return _counterpart_text(bank_tx, mmex_tx) >= TEXT_AUTO


def _near_amount(bank_amount: Decimal, mmex_tx: MmexTransaction) -> bool:
    return abs(abs(Decimal(str(bank_amount))) - abs(Decimal(str(mmex_tx.amount)))) <= Decimal("1.00")


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


@dataclass
class _Scored:
    candidate: MatchCandidate
    text: float
    reconciled: bool


def _score_bank(
    bank_tx: BankTransaction,
    mmex_transactions: list[MmexTransaction],
    credit_card: bool,
    statement_account_name: str | None = None,
) -> list[_Scored]:
    raw: list[_Scored] = []
    for mmex_tx in mmex_transactions:
        if _status(mmex_tx) in _SKIP_STATUS:
            continue
        if not _foreign_transfer_hit(bank_tx, mmex_tx, statement_account_name):
            continue
        date_delta = _date_delta(bank_tx, mmex_tx)
        if date_delta > TOLERANCE_DAYS:
            continue
        amount_ok = _amount_match(bank_tx.amount, mmex_tx, credit_card)
        text = _text_score(bank_tx, mmex_tx)
        if not amount_ok and not (text >= TEXT_AUTO and _near_amount(bank_tx.amount, mmex_tx)):
            continue
        same_sign = _amounts_equal(bank_tx.amount, mmex_tx.amount)
        date_score = max(0, 100 - date_delta * 15)
        score = text * 0.7 + date_score * 0.3
        if amount_ok:
            score += 30 if same_sign else 20
        raw.append(
            _Scored(
                candidate=MatchCandidate(
                    mmex_transaction=mmex_tx,
                    score=score,
                    amount_match=amount_ok,
                    date_delta_days=date_delta,
                ),
                text=text,
                reconciled=_reconciled(mmex_tx),
            )
        )
    if any(item.candidate.amount_match for item in raw):
        raw = [item for item in raw if item.candidate.amount_match]
    raw = [
        item
        for item in raw
        if not item.reconciled or item.text >= TEXT_AUTO or item.candidate.date_delta_days <= 1
    ]
    raw.sort(
        key=lambda item: (
            item.reconciled,
            not item.candidate.amount_match,
            -item.text,
            item.candidate.date_delta_days,
            item.candidate.mmex_transaction.trans_id,
        )
    )
    return raw


def _choose(scored: list[_Scored], reserved: set[int], *, unique: bool) -> _Scored | None:
    available = [
        item
        for item in scored
        if item.candidate.mmex_transaction.trans_id not in reserved and item.candidate.amount_match
    ]
    strong = [item for item in available if item.text >= TEXT_AUTO]
    if strong:
        strong.sort(
            key=lambda item: (
                item.reconciled,
                bool(item.candidate.mmex_transaction.account_name),
                -item.text,
                item.candidate.date_delta_days,
                item.candidate.mmex_transaction.trans_id,
            )
        )
        return strong[0]
    if not unique:
        return None
    open_rows = [
        item
        for item in scored
        if item.candidate.amount_match
        and not item.reconciled
        and not item.candidate.mmex_transaction.account_name
    ]
    free_open = [item for item in open_rows if item.candidate.mmex_transaction.trans_id not in reserved]
    if len(open_rows) == 1 and free_open:
        return free_open[0]
    if open_rows:
        return None
    reconciled_rows = [
        item
        for item in scored
        if item.candidate.amount_match and item.reconciled and item.candidate.date_delta_days <= 1
    ]
    free_reconciled = [
        item
        for item in reconciled_rows
        if item.candidate.mmex_transaction.trans_id not in reserved
    ]
    if len(reconciled_rows) == 1 and free_reconciled:
        return free_reconciled[0]
    return None


def _to_match(
    bank_tx: BankTransaction, scored: list[_Scored], chosen: _Scored | None
) -> TransactionMatch:
    status = MatchStatus.NO_MATCH
    selected_id = None
    selected_payee = None
    category_id = None
    category_name = None
    if chosen is not None:
        tx = chosen.candidate.mmex_transaction
        status = MatchStatus.AUTO_MATCHED
        selected_id = tx.trans_id
        selected_payee = tx.payee_name
        category_id = tx.category_id
        category_name = tx.category_name
    elif any(item.candidate.amount_match and not item.reconciled for item in scored):
        status = MatchStatus.FUZZY_MATCHED
        best = next(
            item for item in scored if item.candidate.amount_match and not item.reconciled
        )
        tx = best.candidate.mmex_transaction
        selected_payee = tx.payee_name
        category_id = tx.category_id
        category_name = tx.category_name
    elif scored and not any(item.candidate.amount_match for item in scored):
        status = MatchStatus.AMOUNT_MISMATCH
    include = status not in (MatchStatus.FUZZY_MATCHED, MatchStatus.AMOUNT_MISMATCH)
    return TransactionMatch(
        bank_transaction=bank_tx,
        status=status,
        candidates=[item.candidate for item in scored[:5]],
        selected_trans_id=selected_id,
        selected_payee_name=selected_payee,
        category_id=category_id,
        category_name=category_name,
        normalized_description=bank_tx.description,
        include=include,
    )


def match_transaction(
    bank_tx: BankTransaction,
    mmex_transactions: list[MmexTransaction],
    used_trans_ids: set[int] | None = None,
    *,
    credit_card: bool = False,
    statement_account_name: str | None = None,
) -> TransactionMatch:
    scored = _score_bank(
        bank_tx, mmex_transactions, credit_card, statement_account_name
    )
    chosen = _choose(scored, used_trans_ids or set(), unique=True)
    return _to_match(bank_tx, scored, chosen)


def match_all(
    bank_txs: list[BankTransaction],
    mmex_txs: list[MmexTransaction],
    *,
    credit_card: bool = False,
    statement_account_name: str | None = None,
) -> list[TransactionMatch]:
    rows = [
        _score_bank(bank, mmex_txs, credit_card, statement_account_name) for bank in bank_txs
    ]
    used: set[int] = set()
    chosen: list[_Scored | None] = [None] * len(rows)

    def best_text(index: int) -> float:
        texts = [
            item.text
            for item in rows[index]
            if item.candidate.amount_match and not item.reconciled
        ]
        return max(texts, default=0.0)

    order = sorted(range(len(rows)), key=lambda index: (-best_text(index), index))
    for index in order:
        pick = _choose(rows[index], used, unique=False)
        if pick is not None:
            chosen[index] = pick
            used.add(pick.candidate.mmex_transaction.trans_id)
    for index in order:
        if chosen[index] is not None:
            continue
        pick = _choose(rows[index], used, unique=True)
        if pick is not None:
            chosen[index] = pick
            used.add(pick.candidate.mmex_transaction.trans_id)
    return [_to_match(bank, rows[index], chosen[index]) for index, bank in enumerate(bank_txs)]


def session_public(payload: dict[str, Any]) -> dict[str, Any]:
    return payload
