"""Map bank statements to MMEX accounts (ported from bank-reconciliation-app)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

KEYWORDS_MAP = {
    "7602": "visa boursorama pierre",
    "6161": "visa boursorama cecile",
    "4810": "visa boursorama",
    "cashback": "visa cashback",
    "swisscard": "visa cashback",
    "boursorama cb": "visa boursorama",
    "relevé de carte": "visa boursorama",
    "releve de carte": "visa boursorama",
    "releve-cb": "visa boursorama",
    "relevé-cb": "visa boursorama",
    "yuh": "yuh",
    "boursorama": "boursorama",
    "boursobank": "boursorama",
    "postfinance": "postfinance",
    "post finance": "postfinance",
}

CARD_HINTS = (
    "visa",
    "cashback",
    "swisscard",
    "releve-cb",
    "relevé-cb",
    "releve de carte",
    "relevé de carte",
    "boursorama cb",
)


def normalize_account_ref(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[\s\-]", "", value).upper()


def list_account_refs(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT a.ACCOUNTID, a.ACCOUNTNAME, a.ACCOUNTNUM, a.ACCOUNTTYPE,
                       a.STATUS, c.CURRENCY_SYMBOL
                  FROM ACCOUNTLIST_V1 a
                  LEFT JOIN CURRENCYFORMATS_V1 c ON a.CURRENCYID = c.CURRENCYID
                 ORDER BY a.ACCOUNTNAME
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
            "currency": (row[5] or "") or None,
        }
        for row in rows
    ]


def expected_account_type(statement: Any) -> str | None:
    meta = getattr(statement, "metadata", None) or {}
    if meta.get("balance_formula") == "credit_card":
        return "Credit Card"
    parser_id = (getattr(statement, "parser_id", None) or "").lower()
    if parser_id in {"boursorama_cb", "swiss_visa"}:
        return "Credit Card"
    bank = (getattr(statement, "bank_name", None) or "").lower()
    if "visa" in bank or "cashback" in bank or bank.endswith(" cb"):
        return "Credit Card"
    if getattr(statement, "iban", None) or parser_id in {
        "boursorama_compte",
        "postfinance",
        "yuh",
    }:
        return "Checking"
    return None


def _card_last4(statement: Any) -> str | None:
    fn = getattr(statement, "card_last4", None)
    if callable(fn):
        return fn()
    return None


def score_statement_account(statement: Any, acc: dict[str, Any]) -> float:
    stmt_iban = normalize_account_ref(getattr(statement, "iban", None))
    stmt_num = normalize_account_ref(getattr(statement, "account_number", None))
    last4 = _card_last4(statement)
    stmt_ccy = (getattr(statement, "currency", None) or "").upper()
    acc_num = normalize_account_ref(str(acc.get("account_num") or ""))
    acc_ccy = (str(acc.get("currency") or "")).upper()
    expected_type = expected_account_type(statement)
    score = 0.0
    card_statement = expected_type == "Credit Card"
    name_lower = str(acc.get("name") or "").lower()

    if card_statement:
        if stmt_num and acc_num == stmt_num:
            score += 100
        elif stmt_num and acc_num and len(acc_num) >= 4 and (
            stmt_num.endswith(acc_num) or acc_num.endswith(stmt_num)
        ):
            score += 60
    elif stmt_iban and acc_num == stmt_iban:
        score += 100
    elif stmt_num and acc_num == stmt_num:
        score += 100
    elif stmt_iban and acc_num and (
        stmt_iban.endswith(acc_num) or acc_num.endswith(stmt_iban)
    ):
        score += 60

    if last4:
        if acc_num.endswith(last4) and len(acc_num) >= 4:
            score += 70
        if last4 in str(acc.get("name") or ""):
            score += 55

    account_hint = (getattr(statement, "account_hint", None) or "").strip().lower()
    if account_hint and account_hint == name_lower:
        score += 50
    elif account_hint and len(account_hint) >= 8 and account_hint in name_lower:
        score += 30

    hint = " ".join(
        part
        for part in (
            getattr(statement, "account_hint", None),
            getattr(statement, "bank_name", None),
            last4,
            (getattr(statement, "metadata", None) or {}).get("card_holder"),
            (getattr(statement, "metadata", None) or {}).get("source_file"),
        )
        if part
    ).lower()
    for keyword, target in KEYWORDS_MAP.items():
        if keyword in hint and target in name_lower:
            score += 40
            break
    else:
        if name_lower in hint or (hint and hint in name_lower):
            score += 25

    ccy_mismatch = bool(stmt_ccy and acc_ccy and stmt_ccy != acc_ccy)
    if stmt_ccy and acc_ccy and stmt_ccy == acc_ccy:
        score += 20
    if ccy_mismatch:
        if score >= 100:
            score = 8
        else:
            score -= 45

    if expected_type:
        if acc.get("account_type") == expected_type:
            score += 12
        elif acc.get("account_type") != expected_type:
            score -= 18

    if str(acc.get("status") or "").lower() != "open":
        score -= 25
    return score


def match_statement_account(
    statement: Any, accounts: list[dict[str, Any]]
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for acc in accounts:
        score = score_statement_account(statement, acc)
        if score > best_score:
            best_score = score
            best = acc
    return best if best_score > 0 else None


def suggest_account_id(haystack: str, accounts: list[dict[str, Any]]) -> int | None:
    """Inbox heuristic when the PDF is not parsed yet (filename / tags)."""
    lower = haystack.lower()
    blob = normalize_account_ref(haystack)
    looks_card = any(h in lower for h in CARD_HINTS)
    best_id: int | None = None
    best_score = 0.0
    for acc in accounts:
        if str(acc.get("status") or "") == "Closed":
            continue
        name_lower = str(acc.get("name") or "").lower()
        num = normalize_account_ref(str(acc.get("account_num") or ""))
        score = 0.0
        if looks_card:
            if acc.get("account_type") == "Credit Card":
                score += 12
            else:
                score -= 18
            for keyword, target in KEYWORDS_MAP.items():
                if keyword in lower and target in name_lower:
                    score += 40
                    break
            digits = re.findall(r"\d{4}", haystack)
            for last4 in digits:
                if last4 in str(acc.get("name") or "") or (num.endswith(last4) and len(num) >= 4):
                    score += 55
                    break
        else:
            if len(num) >= 6 and num in blob:
                score += 100 + len(num) / 100
            for keyword, target in KEYWORDS_MAP.items():
                if keyword in lower and target in name_lower:
                    score += 40
                    break
            else:
                if name_lower and name_lower in lower:
                    score += 25
        if score > best_score:
            best_score = score
            best_id = int(acc["account_id"])
    return best_id if best_score > 0 else None
