"""Parse the many ways job boards say "when was this posted".

`today` is always passed in. Nothing here reads the clock, so results are
reproducible and testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass(frozen=True)
class Posted:
    day: date
    # False when the source gave only a lower bound ("30+ days ago") or no year.
    exact: bool


def _month(token: str) -> int | None:
    return _MONTHS.get(token[:3].lower()) if token.isalpha() else None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _without_year(month: int, day: int, today: date) -> date | None:
    """A date with no year means the most recent such date that is not in the future."""
    candidate = _safe_date(today.year, month, day)
    if candidate is None:
        return None
    if candidate > today:
        candidate = _safe_date(today.year - 1, month, day)
    return candidate


_PREFIX = re.compile(r"^\s*(?:(?:posted|active|updated)\s*)?(?:on\s*)?:?\s*", re.I)
_RELATIVE = re.compile(
    r"(\d+)\s*(\+)?\s*(minute|min|hour|hr|day|week|wk|month|mo)s?\b\s*(?:ago)?", re.I
)


def parse_posted(raw: str | None, today: date) -> Posted | None:
    if not raw:
        return None
    text = _PREFIX.sub("", str(raw).strip()).strip().rstrip(".").lower()
    if not text:
        return None

    if text in {"today", "just posted", "just now", "new", "posted today"}:
        return Posted(today, True)
    if text in {"yesterday", "posted yesterday"}:
        return Posted(today - timedelta(days=1), True)

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        d = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        return Posted(d, True) if d else None

    m = re.match(r"^([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$", text)
    if m and _month(m[1]):
        d = _safe_date(int(m[3]), _month(m[1]), int(m[2]))
        return Posted(d, True) if d else None

    m = re.match(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s+(\d{4})$", text)
    if m and _month(m[2]):
        d = _safe_date(int(m[3]), _month(m[2]), int(m[1]))
        return Posted(d, True) if d else None

    m = re.match(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?$", text)
    if m and _month(m[2]):
        d = _without_year(_month(m[2]), int(m[1]), today)
        return Posted(d, False) if d else None

    m = re.match(r"^([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?$", text)
    if m and _month(m[1]):
        d = _without_year(_month(m[1]), int(m[2]), today)
        return Posted(d, False) if d else None

    m = _RELATIVE.search(text)
    if m:
        n = int(m[1])
        unit = m[3].lower()
        lower_bound = bool(m[2])
        if unit in ("minute", "min", "hour", "hr"):
            days = 0
        elif unit == "day":
            days = n
        elif unit in ("week", "wk"):
            days = 7 * n
        else:  # month, mo
            days = 30 * n
        return Posted(today - timedelta(days=days), not lower_bound)

    return None


def age_days(posted: Posted | None, today: date) -> int | None:
    if posted is None:
        return None
    return max(0, (today - posted.day).days)
