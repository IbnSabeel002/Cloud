"""Turn the pay text on a listing into a monthly AED range.

Faithful to the text. If the text is wrong (job boards sometimes mislabel
currency or period), the parser is wrong in the same way, and says what it
assumed in `assumptions` so the digest can show it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Approximate rates. Only used to rank, never to quote an exact figure back.
TO_AED = {"AED": 1.0, "USD": 3.6725, "EUR": 4.0, "GBP": 4.7, "INR": 0.044, "SAR": 0.98}

_CURRENCIES = [
    ("AED", re.compile(r"(?<![a-z])(?:aed|dhs?|dirhams?)(?![a-z])|د\.إ", re.I)),
    ("USD", re.compile(r"(?<![a-z])usd(?![a-z])|\$", re.I)),
    ("EUR", re.compile(r"(?<![a-z])eur(?![a-z])|€", re.I)),
    ("GBP", re.compile(r"(?<![a-z])gbp(?![a-z])|£", re.I)),
    ("INR", re.compile(r"(?<![a-z])inr(?![a-z])|₹|(?<![a-z])rs\.?(?![a-z])", re.I)),
    ("SAR", re.compile(r"(?<![a-z])sar(?![a-z])", re.I)),
]

_NUMBER = re.compile(
    r"(?<![\d,.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*([kK])(?![a-zA-Z]))?"
)
# "3-5 years" is experience, not pay.
_EXPERIENCE = re.compile(r"\b\d+(?:\s*[-–to]+\s*\d+)?\s*\+?\s*(?:years?|yrs?)\b", re.I)

_YEARLY = re.compile(r"per\s*(?:year|annum|yr)|a\s*year|/\s*(?:yr|year)|yearly|annual|\bp\.?a\.?\b", re.I)
_DAILY = re.compile(r"per\s*day|a\s*day|/\s*day|daily", re.I)
_HOURLY = re.compile(r"per\s*hour|per\s*hr|an\s*hour|/\s*(?:hr|hour)|hourly", re.I)
_WEEKLY = re.compile(r"per\s*week|a\s*week|/\s*week|weekly", re.I)
_MONTHLY = re.compile(r"per\s*month|a\s*month|/\s*(?:mo|month)\b|monthly|\bp\.?m\.?\b", re.I)
_UP_TO = re.compile(r"\bup\s*-?\s*to\b|\bupto\b|\bmax(?:imum)?\b|\bnot\s+more\s+than\b", re.I)
_FROM = re.compile(r"\bfrom\b|\bstarting\b|\bminimum\b|\bmin\b|\d\s*\+(?!\s*(?:years?|yrs?))", re.I)

_WORKING_DAYS = 22
_HOURS_PER_DAY = 8
_WEEKS_PER_MONTH = 4.33


@dataclass(frozen=True)
class PayRange:
    low: float | None  # monthly AED, None when only an upper bound was given
    high: float | None  # monthly AED, None when only a lower bound was given
    currency: str
    period: str
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    raw: str = ""

    @property
    def midpoint(self) -> float:
        if self.low is not None and self.high is not None:
            return (self.low + self.high) / 2
        return self.high if self.high is not None else self.low  # type: ignore[return-value]

    @property
    def ceiling(self) -> float | None:
        """Best known upper figure. None when the text gave only a lower bound."""
        return self.high


def _detect_currency(text: str) -> tuple[str, bool]:
    for code, pattern in _CURRENCIES:
        if pattern.search(text):
            return code, False
    return "AED", True


def _detect_period(text: str) -> str | None:
    for name, pattern in (
        ("year", _YEARLY), ("day", _DAILY), ("hour", _HOURLY), ("week", _WEEKLY), ("month", _MONTHLY),
    ):
        if pattern.search(text):
            return name
    return None


def _to_monthly(value: float, period: str) -> float:
    if period == "year":
        return value / 12
    if period == "week":
        return value * _WEEKS_PER_MONTH
    if period == "day":
        return value * _WORKING_DAYS
    if period == "hour":
        return value * _HOURS_PER_DAY * _WORKING_DAYS
    return value


def parse_pay(text: str | None) -> PayRange | None:
    if not text:
        return None
    raw = str(text).strip()
    cleaned = _EXPERIENCE.sub(" ", raw)

    numbers: list[float] = []
    for m in _NUMBER.finditer(cleaned):
        value = float(m.group(1).replace(",", ""))
        if m.group(2):
            value *= 1000
        numbers.append(value)
    if not numbers:
        return None

    assumptions: list[str] = []
    currency, assumed_currency = _detect_currency(cleaned)
    if assumed_currency:
        assumptions.append("currency_assumed_aed")

    period = _detect_period(cleaned)
    if period is None:
        # Nobody in the UAE advertises 60k+ a month for these roles; treat as a yearly figure.
        if max(numbers) * TO_AED[currency] >= 60000:
            period = "year"
            assumptions.append("period_assumed_yearly")
        else:
            period = "month"
            assumptions.append("period_assumed_monthly")

    if len(numbers) > 2:
        # "Basic 4000 + housing 1000 + transport 500": the first figure is the basic salary.
        # Guessing a range out of the others would invent a number nobody advertised.
        assumptions.append("multiple_numbers_used_first")
        numbers = numbers[:1]
    first_two = numbers[:2]

    factor = TO_AED[currency]
    monthly = [_to_monthly(v, period) * factor for v in first_two]

    if len(monthly) == 1:
        if _UP_TO.search(cleaned):
            low, high = None, monthly[0]
        elif _FROM.search(cleaned):
            low, high = monthly[0], None
        else:
            low = high = monthly[0]
    else:
        low, high = min(monthly), max(monthly)

    return PayRange(low, high, currency, period, tuple(assumptions), raw)
