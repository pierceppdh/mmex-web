"""Modèles Pydantic pour la réconciliation bancaire."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MatchStatus(str, Enum):
    """Statut de correspondance entre relevé et MMEX."""

    AUTO_MATCHED = "AUTO_MATCHED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    FUZZY_MATCHED = "FUZZY_MATCHED"
    LLM_MATCHED = "LLM_MATCHED"
    NO_MATCH = "NO_MATCH"
    MANUAL = "MANUAL"
    SKIP = "SKIP"


class BalanceStatus(str, Enum):
    """Statut de vérification des soldes."""

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class BankTransaction(BaseModel):
    """Transaction extraite d'un relevé PDF."""

    date: date
    description: str
    amount: Decimal  # positif = crédit, négatif = débit
    currency: str = "CHF"
    raw_text: str = ""
    card_holder: Optional[str] = None
    value_date: Optional[date] = None


class ParsedStatement(BaseModel):
    """Relevé bancaire parsé."""

    parser_id: str
    bank_name: str
    account_hint: str
    iban: Optional[str] = None
    account_number: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    opening_balance: Optional[Decimal] = None
    closing_balance: Optional[Decimal] = None
    currency: str = "CHF"
    transactions: list[BankTransaction] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    def card_last4(self) -> Optional[str]:
        """4 derniers chiffres d'une carte masquée (****1234), pas d'un IBAN."""
        import re

        raws: list[str] = []
        meta = self.metadata or {}
        for value in (meta.get("card_number"), meta.get("card_last4"), self.account_number):
            if value:
                raws.append(str(value))
        for raw in raws:
            starred = re.search(r"[*xX]{2,}(\d{4})", raw)
            if starred:
                return starred.group(1)
            if "*" in raw or "x" in raw.lower() or "X" in raw:
                digits = re.sub(r"\D", "", raw)
                if len(digits) >= 4:
                    return digits[-4:]
        return None

    def available_currencies(self) -> list[str]:
        slices = (self.metadata or {}).get("currency_slices") or {}
        if isinstance(slices, dict) and slices:
            preferred = [code for code in ("CHF", "EUR", "USD") if code in slices]
            rest = [code for code in slices if code not in preferred]
            return preferred + rest
        return [self.currency] if self.currency else []

    def with_currency(self, currency: str | None) -> "ParsedStatement":
        """Remplace txs/soldes par la tranche de devise (relevés multi-devises)."""
        if not currency:
            return self
        slices = (self.metadata or {}).get("currency_slices") or {}
        data = slices.get(currency) if isinstance(slices, dict) else None
        if not data:
            return self
        txs: list[BankTransaction] = []
        for item in data.get("transactions") or []:
            raw_date = item.get("date")
            tx_date = (
                date.fromisoformat(raw_date) if isinstance(raw_date, str) else raw_date
            )
            raw_value = item.get("value_date")
            value_date = (
                date.fromisoformat(raw_value)
                if isinstance(raw_value, str)
                else raw_value
            )
            txs.append(
                BankTransaction(
                    date=tx_date,
                    description=item.get("description") or "",
                    amount=Decimal(str(item.get("amount") or "0")),
                    currency=item.get("currency") or currency,
                    raw_text=item.get("raw_text") or "",
                    value_date=value_date,
                )
            )
        opening = data.get("opening_balance")
        closing = data.get("closing_balance")
        return self.model_copy(
            update={
                "currency": currency,
                "opening_balance": (
                    Decimal(str(opening)) if opening not in (None, "") else None
                ),
                "closing_balance": (
                    Decimal(str(closing)) if closing not in (None, "") else None
                ),
                "transactions": txs,
            }
        )


class MmexAccount(BaseModel):
    """Compte MoneyManagerEx."""

    account_id: int
    account_name: str
    account_type: str
    status: str
    account_num: Optional[str] = None
    currency: Optional[str] = None

    def label(self) -> str:
        """Libellé UI : nom · devise · n°/IBAN."""
        parts = [self.account_name]
        if self.currency:
            parts.append(self.currency)
        if self.account_num:
            parts.append(self.account_num)
        return " · ".join(parts)


class MmexTransaction(BaseModel):
    """Transaction MoneyManagerEx."""

    trans_id: int
    account_id: int
    payee_id: Optional[int] = None
    payee_name: Optional[str] = None
    trans_code: str
    amount: Decimal
    status: str
    trans_date: date
    notes: str = ""
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    to_account_id: Optional[int] = None
    counterpart_account_name: Optional[str] = None
    is_inbound_transfer: bool = False


class MatchCandidate(BaseModel):
    """Candidat de correspondance MMEX."""

    mmex_transaction: MmexTransaction
    score: float = 0.0
    amount_match: bool = False
    date_delta_days: int = 0


class TransactionMatch(BaseModel):
    """Résultat de matching pour une transaction du relevé."""

    bank_transaction: BankTransaction
    status: MatchStatus
    candidates: list[MatchCandidate] = Field(default_factory=list)
    selected_trans_id: Optional[int] = None
    selected_payee_name: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    normalized_description: Optional[str] = None
    notes: str = ""
    include: bool = True
    insert_as_transfer: bool = False
    transfer_counterpart_account_id: Optional[int] = None
    transfer_counterpart_account_name: Optional[str] = None
    # Montant dans la devise du compte contrepartie (virements change).
    transfer_counterpart_amount: Optional[Decimal] = None
    force_new_insert: bool = False
    # None = auto (signe du montant) ; "Deposit" / "Withdrawal" pour forcer l'écriture MMEX
    force_trans_code: Optional[str] = None


class BalanceCheckResult(BaseModel):
    """Résultat de vérification des soldes."""

    status: BalanceStatus
    opening_balance_pdf: Optional[Decimal] = None
    closing_balance_pdf: Optional[Decimal] = None
    computed_closing: Optional[Decimal] = None
    mmex_balance: Optional[Decimal] = None
    mmex_balance_date: Optional[date] = None
    difference_pdf: Optional[Decimal] = None
    difference_mmex: Optional[Decimal] = None
    message: str = ""


class ReconciliationSession(BaseModel):
    """Session de réconciliation en cours."""

    source: str  # paperless:<id> ou local:<path>
    statement: ParsedStatement
    account_id: int
    account_name: str
    matches: list[TransactionMatch] = Field(default_factory=list)
    balance_check: Optional[BalanceCheckResult] = None
    paperless_doc_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)


class PaperlessDocument(BaseModel):
    """Document Paperless-ngx."""

    id: int
    title: str
    created: datetime
    tags: list[str] = Field(default_factory=list)
    download_url: Optional[str] = None
    correspondent: Optional[str] = None
    document_type: Optional[str] = None
    original_file_name: Optional[str] = None

    @property
    def created_label(self) -> str:
        return self.created.strftime("%d/%m/%Y")

    def display_tags(self, inbox_tag: str | None = None) -> list[str]:
        """Tags utiles pour identifier le relevé (sans le tag inbox)."""
        if not inbox_tag:
            return list(self.tags)
        key = inbox_tag.casefold()
        return [tag for tag in self.tags if tag.casefold() != key]