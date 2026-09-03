"""Built-in report endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Engine

from mmex_domain.budgets import BudgetError
from mmex_domain.reports import ReportError, catalog, run_report
from mmex_web_api.deps import get_compatible_engine, get_current_user

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


def _http(exc: ReportError | BudgetError) -> HTTPException:
    msg = str(exc)
    code = 404 if msg.startswith("unknown") else 400
    return HTTPException(status_code=code, detail=msg)


@router.get("/reports")
def reports_catalog() -> dict[str, Any]:
    return catalog()


@router.get("/reports/{report_id}")
def reports_run(
    report_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    year_id: int | None = None,
    engine: Engine = Depends(get_compatible_engine),
) -> dict[str, Any]:
    try:
        return run_report(
            engine, report_id, date_from=date_from, date_to=date_to, year_id=year_id
        )
    except (ReportError, BudgetError) as exc:
        raise _http(exc) from exc
