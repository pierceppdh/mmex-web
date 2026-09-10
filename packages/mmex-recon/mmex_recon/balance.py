"""PDF opening + movements vs closing (ported from bank-reconciliation-app)."""

from __future__ import annotations

from decimal import Decimal

from mmex_recon.schemas import BalanceCheckResult, BalanceStatus, ParsedStatement

TOLERANCE = Decimal("0.05")


def check_pdf_balances(statement: ParsedStatement) -> BalanceCheckResult:
    meta = statement.metadata or {}
    if meta.get("balance_check_skipped"):
        return BalanceCheckResult(
            status=BalanceStatus.GREEN,
            message=str(
                meta.get(
                    "balance_check_reason",
                    "Vérification des soldes non applicable pour ce relevé",
                )
            ),
        )

    opening = statement.opening_balance
    closing_pdf = statement.closing_balance
    credit_card = meta.get("balance_formula") == "credit_card"
    closing_credit = bool(meta.get("closing_in_customer_favor"))
    total_movement = sum((tx.amount for tx in statement.transactions), Decimal("0"))

    computed = None
    if opening is not None:
        if credit_card:
            computed = opening - total_movement
        else:
            computed = opening + total_movement
        if closing_credit and computed is not None:
            computed = -computed

    diff_pdf = None
    if computed is not None and closing_pdf is not None:
        diff_pdf = computed - closing_pdf

    if opening is not None and closing_pdf is not None:
        if diff_pdf is not None and abs(diff_pdf) > TOLERANCE:
            status = BalanceStatus.RED
            message = f"Arithmétique PDF incorrecte : écart de {diff_pdf:+.2f}"
        else:
            status = BalanceStatus.GREEN
            message = "Soldes PDF cohérents (ouverture + mouvements = clôture)"
    else:
        missing = []
        if opening is None:
            missing.append("ouverture")
        if closing_pdf is None:
            missing.append("clôture")
        status = BalanceStatus.YELLOW
        message = (
            f"Soldes PDF partiels (manquant: {', '.join(missing)}) — "
            "vérification arithmétique impossible"
        )

    return BalanceCheckResult(
        status=status,
        opening_balance_pdf=opening,
        closing_balance_pdf=closing_pdf,
        computed_closing=computed,
        difference_pdf=diff_pdf,
        message=message,
    )
