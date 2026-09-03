from datetime import date

from mmex_domain.repeats import (
    AUTO_SILENT,
    REPEAT_MONTHLY,
    REPEAT_MONTHLY_LAST_BUSINESS_DAY,
    REPEAT_MONTHLY_LAST_DAY,
    REPEAT_WEEKLY,
    decode,
    encode,
    next_occurrence,
)


def test_encode_decode_silent_monthly() -> None:
    value = encode(REPEAT_MONTHLY, AUTO_SILENT)
    assert value == 203
    assert decode(201) == (REPEAT_WEEKLY, AUTO_SILENT)
    assert decode(3) == (REPEAT_MONTHLY, 0)


def test_next_weekly_and_month_end() -> None:
    assert next_occurrence(date(2026, 8, 31), REPEAT_WEEKLY) == date(2026, 9, 7)
    assert next_occurrence(date(2026, 1, 31), REPEAT_MONTHLY) == date(2026, 2, 28)
    assert next_occurrence(date(2026, 1, 15), REPEAT_MONTHLY_LAST_DAY) == date(2026, 1, 31)
    assert next_occurrence(date(2026, 1, 31), REPEAT_MONTHLY_LAST_DAY) == date(2026, 2, 28)
    # 2026-02-28 is Saturday → last business day 27
    assert next_occurrence(date(2026, 2, 10), REPEAT_MONTHLY_LAST_BUSINESS_DAY) == date(
        2026, 2, 27
    )
    assert next_occurrence(date(2026, 3, 1), 13, 10) == date(2026, 3, 11)
