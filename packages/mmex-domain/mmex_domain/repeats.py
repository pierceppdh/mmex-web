"""BILLSDEPOSITS_V1.REPEATS bitfield (desktop Model_Billsdeposits / Android Recurrence)."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

MULTIPLEX = 100

REPEAT_ONCE = 0
REPEAT_WEEKLY = 1
REPEAT_BIWEEKLY = 2
REPEAT_MONTHLY = 3
REPEAT_BIMONTHLY = 4
REPEAT_QUARTERLY = 5
REPEAT_SEMIANNUALLY = 6
REPEAT_ANNUALLY = 7
REPEAT_FOUR_MONTHS = 8
REPEAT_FOUR_WEEKS = 9
REPEAT_DAILY = 10
REPEAT_IN_X_DAYS = 11
REPEAT_IN_X_MONTHS = 12
REPEAT_EVERY_X_DAYS = 13
REPEAT_EVERY_X_MONTHS = 14
REPEAT_MONTHLY_LAST_DAY = 15
REPEAT_MONTHLY_LAST_BUSINESS_DAY = 16

AUTO_MANUAL = 0
AUTO_PROMPT = 1
AUTO_SILENT = 2

REPEAT_TYPES: tuple[tuple[int, str, str, str], ...] = (
    (REPEAT_ONCE, "once", "Une fois", "Once"),
    (REPEAT_WEEKLY, "weekly", "Hebdomadaire", "Weekly"),
    (REPEAT_BIWEEKLY, "biweekly", "Toutes les 2 semaines", "Fortnightly"),
    (REPEAT_MONTHLY, "monthly", "Mensuel", "Monthly"),
    (REPEAT_BIMONTHLY, "bimonthly", "Tous les 2 mois", "Every 2 months"),
    (REPEAT_QUARTERLY, "quarterly", "Trimestriel", "Quarterly"),
    (REPEAT_SEMIANNUALLY, "semiannually", "Semestriel", "Half-yearly"),
    (REPEAT_ANNUALLY, "annually", "Annuel", "Yearly"),
    (REPEAT_FOUR_MONTHS, "four_months", "Tous les 4 mois", "Every 4 months"),
    (REPEAT_FOUR_WEEKS, "four_weeks", "Toutes les 4 semaines", "Every 4 weeks"),
    (REPEAT_DAILY, "daily", "Quotidien", "Daily"),
    (REPEAT_IN_X_DAYS, "in_x_days", "Dans X jours", "In X days"),
    (REPEAT_IN_X_MONTHS, "in_x_months", "Dans X mois", "In X months"),
    (REPEAT_EVERY_X_DAYS, "every_x_days", "Tous les X jours", "Every X days"),
    (REPEAT_EVERY_X_MONTHS, "every_x_months", "Tous les X mois", "Every X months"),
    (REPEAT_MONTHLY_LAST_DAY, "last_day", "Dernier jour du mois", "Monthly (last day)"),
    (REPEAT_MONTHLY_LAST_BUSINESS_DAY, "last_business", "Dernier jour ouvré", "Monthly (last business day)"),
)

AUTO_MODES: tuple[tuple[int, str, str, str], ...] = (
    (AUTO_MANUAL, "manual", "Manuel", "Manual"),
    (AUTO_PROMPT, "prompt", "Demander", "Prompt"),
    (AUTO_SILENT, "silent", "Automatique", "Silent"),
)

INTERVAL_TYPES = {REPEAT_IN_X_DAYS, REPEAT_IN_X_MONTHS, REPEAT_EVERY_X_DAYS, REPEAT_EVERY_X_MONTHS}
ONE_SHOT_TYPES = {REPEAT_ONCE, REPEAT_IN_X_DAYS, REPEAT_IN_X_MONTHS}
USES_REMAINING = set(range(0, 17)) - INTERVAL_TYPES


def decode(repeats: int | None) -> tuple[int, int]:
    value = int(repeats or 0)
    auto = value // MULTIPLEX
    kind = value % MULTIPLEX
    if auto not in (AUTO_MANUAL, AUTO_PROMPT, AUTO_SILENT):
        auto = AUTO_MANUAL
    if kind < 0 or kind > REPEAT_MONTHLY_LAST_BUSINESS_DAY:
        kind = REPEAT_ONCE
    return kind, auto


def encode(kind: int, auto: int = AUTO_MANUAL) -> int:
    kind = int(kind)
    auto = int(auto)
    if kind < 0 or kind > REPEAT_MONTHLY_LAST_BUSINESS_DAY:
        raise ValueError("invalid repeat type")
    if auto not in (AUTO_MANUAL, AUTO_PROMPT, AUTO_SILENT):
        raise ValueError("invalid auto mode")
    return kind + auto * MULTIPLEX


def type_meta(kind: int) -> dict[str, str | int]:
    for tid, key, fr, en in REPEAT_TYPES:
        if tid == kind:
            return {"id": tid, "key": key, "label_fr": fr, "label_en": en}
    return {"id": kind, "key": "once", "label_fr": "Une fois", "label_en": "Once"}


def auto_meta(auto: int) -> dict[str, str | int]:
    for aid, key, fr, en in AUTO_MODES:
        if aid == auto:
            return {"id": aid, "key": key, "label_fr": fr, "label_en": en}
    return {"id": AUTO_MANUAL, "key": "manual", "label_fr": "Manuel", "label_en": "Manual"}


def add_months(day: date, months: int) -> date:
    year = day.year + (day.month - 1 + months) // 12
    month = (day.month - 1 + months) % 12 + 1
    last = monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def last_day_of_month(day: date) -> date:
    return date(day.year, day.month, monthrange(day.year, day.month)[1])


def last_business_day(day: date) -> date:
    current = last_day_of_month(day)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def next_occurrence(day: date, kind: int, interval: int = 1) -> date:
    """Advance one occurrence from ``day`` (Android RecurringTransactionService)."""
    kind, _auto = decode(kind) if kind >= MULTIPLEX else (kind, 0)
    x = interval if interval and interval > 0 else 1
    if kind == REPEAT_ONCE:
        return day
    if kind == REPEAT_WEEKLY:
        return day + timedelta(weeks=1)
    if kind == REPEAT_BIWEEKLY:
        return day + timedelta(weeks=2)
    if kind == REPEAT_MONTHLY:
        return add_months(day, 1)
    if kind == REPEAT_BIMONTHLY:
        return add_months(day, 2)
    if kind == REPEAT_QUARTERLY:
        return add_months(day, 3)
    if kind == REPEAT_SEMIANNUALLY:
        return add_months(day, 6)
    if kind == REPEAT_ANNUALLY:
        return add_months(day, 12)
    if kind == REPEAT_FOUR_MONTHS:
        return add_months(day, 4)
    if kind == REPEAT_FOUR_WEEKS:
        return day + timedelta(weeks=4)
    if kind == REPEAT_DAILY:
        return day + timedelta(days=1)
    if kind in (REPEAT_IN_X_DAYS, REPEAT_EVERY_X_DAYS):
        return day + timedelta(days=x)
    if kind in (REPEAT_IN_X_MONTHS, REPEAT_EVERY_X_MONTHS):
        return add_months(day, x)
    if kind == REPEAT_MONTHLY_LAST_DAY:
        last = last_day_of_month(day)
        if day != last:
            return last
        return last_day_of_month(add_months(date(day.year, day.month, 1), 1))
    if kind == REPEAT_MONTHLY_LAST_BUSINESS_DAY:
        last_biz = last_business_day(day)
        if day != last_biz and day < last_biz:
            return last_biz
        nxt = add_months(date(day.year, day.month, 1), 1)
        return last_business_day(nxt)
    return day
