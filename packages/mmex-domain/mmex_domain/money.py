"""Currency formatting and conversion helpers."""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP


def as_decimal(value: object | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def currency_precision(scale: int | None) -> int:
    if not scale or scale <= 1:
        return 0
    return int(round(math.log10(scale)))


def format_amount(
    value: Decimal,
    *,
    scale: int | None = 100,
    pfx: str | None = "",
    sfx: str | None = "",
    decimal_point: str | None = ".",
    group_separator: str | None = ",",
) -> str:
    prec = currency_precision(scale)
    q = Decimal("1") if prec == 0 else Decimal("1").scaleb(-prec)
    quantized = as_decimal(value).quantize(q, rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    abs_q = abs(quantized)
    raw = f"{abs_q:.{prec}f}"
    whole, _, frac = raw.partition(".")
    dp = decimal_point if decimal_point is not None else "."
    gs = group_separator if group_separator is not None else ""
    if gs:
        grouped = _group(whole, gs)
    else:
        grouped = whole
    body = grouped if prec == 0 else f"{grouped}{dp}{frac}"
    return f"{sign}{pfx or ''}{body}{sfx or ''}"


def _group(whole: str, sep: str) -> str:
    if len(whole) <= 3:
        return whole
    parts: list[str] = []
    while whole:
        parts.append(whole[-3:])
        whole = whole[:-3]
    return sep.join(reversed(parts))


def to_base(amount: Decimal, rate: Decimal, base_rate: Decimal) -> Decimal:
    """Convert an amount using MMEX BASECONVRATE / history rates.

    Rates are “1 unit of this currency in base units”. If the base currency
    itself has rate 1, this is amount * rate.
    """
    if base_rate == 0:
        return amount * rate
    return amount * (rate / base_rate)
