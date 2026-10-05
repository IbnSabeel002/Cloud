"""The one line about when the candidate can start, kept true as the days pass.

"My notice period ends this week" is wrong a week later. So the settings hold a date
(`notice_ends_by`) and this works out the sentence for today. The model copies it as printed
and never writes a date of its own.
"""

from __future__ import annotations

from datetime import date


def _day(d: date) -> str:
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')}"  # "Friday 9 October", no zero padding


def availability_line(card: dict, today: date) -> str | None:
    """A sentence for outreach, or None when nothing is known.

    `notice_ends_by` (YYYY-MM-DD) is the latest day the notice period can end. Without it, the free-text
    `availability` is used as written. An unreadable date is ignored rather than guessed at.
    """
    raw = card.get("notice_ends_by")
    if raw:
        try:
            ends = date.fromisoformat(str(raw).strip())
        except ValueError:
            ends = None
        if ends is not None:
            if ends < today:
                return "My notice period has ended, so I am available to join immediately."
            if ends == today:
                return "My notice period ends today."
            return f"My notice period ends by {_day(ends)}."
    text = str(card.get("availability") or "").strip()
    return text or None
