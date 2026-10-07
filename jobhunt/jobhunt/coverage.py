"""What a run covered, judged by the script and not by the model's own summary.

The model writes one health row per source and says how it went. This module reads those rows next to facts the script
owns: the entries that really reached raw.json (counted by their `source` label), the jobs the prefilter picked, and the
run clock. That turns four quiet failures into plain warnings:

  * a source that was never mentioned (a skipped Bayt, GulfTalent, Naukrigulf or other-board alert step),
  * a source marked failed with no allowed reason, or with the time limit cited before 40 minutes had passed,
  * Indeed results that came back but were never written down (94 returned, 27 typed, on 2026-10-07),
  * jobs the prefilter picked to be opened that were never finished.

It cannot prove that a typed reason, count or detail is true. It makes the claim visible and checkable, and where the
script has its own number (entries counted, the run clock) it lets the code contradict the claim.
"""

from __future__ import annotations

import re

# Every row the digest expects. The first five keep the names the watchdog already matches.
REQUIRED = ("Settings", "Indeed connector", "Tiny Fish pages", "Gmail alerts", "Tracker write",
            "Bayt pages", "GulfTalent", "Naukrigulf", "Other alerts")
# The rows the watchdog checks by name. The others are left to the digest, so a forgotten low-yield row is not a phone alert.
WATCHDOG_NAMES = REQUIRED[:5]
# Tracker write happens in section 8, after the prefilter, so every other row must exist before the prefilter runs.
BEFORE_PREFILTER = tuple(name for name in REQUIRED if name != "Tracker write")

# Which entries in raw.json (by `source`) each source row stands for. The script counts them itself.
ROW_SOURCES = {
    "Indeed connector": ("indeed",),
    "Tiny Fish pages": ("indeed_page", "careers"),
    "Bayt pages": ("bayt",),
    "GulfTalent": ("gulftalent",),
    "Naukrigulf": ("naukrigulf",),
    "Gmail alerts": ("linkedin_alert",),
    "Other alerts": ("indeed_alert", "bayt_alert", "other"),
}
KNOWN_SOURCES = {label for labels in ROW_SOURCES.values() for label in labels}
# What a missing or broken row means for the owner, in words that do not need the row name explained.
COVERS = {
    "Indeed connector": "Indeed search results",
    "Tiny Fish pages": "the Indeed UAE last-3-days pages and any watchlist pages",
    "Bayt pages": "Bayt listings",
    "GulfTalent": "GulfTalent listings",
    "Naukrigulf": "Naukrigulf listings",
    "Gmail alerts": "LinkedIn alert emails",
    "Other alerts": "Indeed, Bayt and GulfTalent alert emails",
    "Settings": "your saved settings",
    "Tracker write": "saving today's jobs",
}

REASONS = {
    "tool_error": "the tool gave an error",
    "tool_missing": "the tool was not available in this session",
    "time_limit": "the 40-minute limit ran out",
    "refused": "a call was refused or waited for approval",
}
TIME_LIMIT_MINUTES = 40
MIN_RATIO = 0.8   # Indeed results written down, as a share of the results that came back
MIN_HITS = 10     # below this many results the share is too coarse to judge

# What an excuse sounds like. A detail that says this is not the evidence an allowed reason needs.
_EXCUSE = re.compile(
    r"\bto\s+stay\s+lean\b|\bto\s+keep\s+the\s+run\s+short\b|\bto\s+save\s+(?:time|tokens|effort)\b|"
    r"\bnot\s+needed(?:\s+today)?\b|\bskip(?:ped|ping)?\s+(?:it|to|for)\b|\b(?:keep|kept|keeping)\s+it\s+(?:short|lean|brief)\b",
    re.I,
)


def _squash(text) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower().replace("&", "and"))


_NAMES = {_squash(name): name for name in REQUIRED}
_NAMES.update({"gulftalentpages": "GulfTalent", "naukrigulfpages": "Naukrigulf", "otheralert": "Other alerts",
               "baytpage": "Bayt pages", "bayt": "Bayt pages"})


def canonical(name) -> str:
    """The required name this row stands for ('' if it is none of them). Case, spacing, '&' and punctuation do not matter."""
    return _NAMES.get(_squash(name), "")


def normalise_reason(value) -> str:
    return re.sub(r"[\s-]+", "_", str(value or "").strip().lower())


def is_ok(row: dict) -> bool:
    """Only a real true counts. The string "false" is a failure, and so is a missing value."""
    return row.get("ok") is True


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def failure_problem(row: dict, limit_seen=None, reason_required: bool = True) -> str | None:
    """Why a failed row's stated reason does not count, or None if it does.

    `limit_seen` is the largest number of minutes the `elapsed` command printed in this run (its own clock, not the model's).
    A row that is not a search source (Settings, Tracker write) may leave the reason out.
    """
    reason = normalise_reason(row.get("reason"))
    detail = str(row.get("detail") or "").strip()
    if not reason:
        return "no reason was given" if reason_required else None
    if reason not in REASONS:
        return "that is not an allowed reason"
    if not detail:
        return "no evidence was given"
    if _EXCUSE.search(detail):
        return "the note reads like an excuse, not like evidence"
    if reason == "time_limit":
        if not is_number(limit_seen):
            return "the time limit was cited but the `elapsed` command was never run to check it"
        if limit_seen < TIME_LIMIT_MINUTES:
            return f"the time limit was cited but only {int(limit_seen)} of {TIME_LIMIT_MINUTES} minutes had passed"
    return None


def missing_rows(health, required=REQUIRED) -> list[str]:
    seen = {canonical(h.get("source")) for h in (health or []) if isinstance(h, dict)}
    return [name for name in required if name not in seen]


def duplicate_rows(health) -> list[str]:
    counts: dict[str, int] = {}
    for h in health or []:
        if isinstance(h, dict) and canonical(h.get("source")):
            name = canonical(h.get("source"))
            counts[name] = counts.get(name, 0) + 1
    return [name for name, n in counts.items() if n > 1]


def typed_count(raw_by_source, row_name: str):
    """How many entries for this row reached raw.json, or None when the script has no count to give."""
    if not isinstance(raw_by_source, dict) or row_name not in ROW_SOURCES:
        return None
    return sum(int(raw_by_source.get(label, 0) or 0) for label in ROW_SOURCES[row_name])


def unknown_sources(raw_by_source) -> dict:
    """Source labels in raw.json that no row stands for (a typo such as 'indeed_ae' would otherwise be counted nowhere)."""
    if not isinstance(raw_by_source, dict):
        return {}
    return {label: n for label, n in raw_by_source.items() if label not in KNOWN_SOURCES and n}


def hits_seen(row: dict):
    """The number of results the Indeed searches returned, or None if it is missing or not a plain whole number."""
    value = row.get("hits_seen")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def indeed_problem(row: dict, typed) -> str | None:
    """A problem with how many Indeed results were written down, or None. `typed` is the script's own count."""
    if typed is None:
        return None
    seen = hits_seen(row)
    if seen is None:
        return None if not is_ok(row) else "the number of results that came back (hits_seen) was not reported"
    if seen == 0:
        return "the searches returned nothing, which is unusual" if is_ok(row) else None
    if typed > seen:
        return f"{typed} Indeed entries were written down but only {seen} results were reported"
    if seen >= MIN_HITS and typed < MIN_RATIO * seen:
        return f"only {typed} of the {seen} results that came back were written down"
    return None


_COUNTS = re.compile(r"(\d+)\s+threads?\b.*?(\d+)\s+jobs?\b", re.I | re.S)


def alert_problem(row: dict) -> str | None:
    """An alert row says how many mails it found and how many jobs it took from them; mails with no jobs is a gap."""
    match = _COUNTS.search(str(row.get("detail") or ""))
    if match and int(match.group(1)) > 0 and int(match.group(2)) == 0:
        return f"{match.group(1)} alert mail(s) were found but no jobs were taken from them"
    return None


def gate_problems(health, limit_seen=None) -> list[str]:
    """What must be fixed in health.json before the prefilter may run (an empty list means it may)."""
    problems = []
    if not isinstance(health, list):
        return ["health.json must be a list of rows like {\"source\": ..., \"ok\": true, \"detail\": ...}"]
    absent = missing_rows(health, BEFORE_PREFILTER)
    if absent:
        problems.append("write a row for each of these sources first (do the work, or say why it could not be done): "
                        + ", ".join(f"{name} ({COVERS[name]})" for name in absent))
    for h in health:
        if not isinstance(h, dict):
            problems.append("every row in health.json must be an object")
            continue
        name = canonical(h.get("source"))
        if not name:
            continue
        if not isinstance(h.get("ok"), bool):
            problems.append(f"{name}: ok must be true or false")
        elif not h["ok"]:
            why = failure_problem(h, limit_seen, reason_required=name in ROW_SOURCES)
            if why:
                problems.append(f"{name} is marked failed but {why}")
        elif name == "Indeed connector" and hits_seen(h) is None:
            problems.append("Indeed connector: add hits_seen, the total number of results all the searches returned, as a whole number")
    for name in duplicate_rows(health):
        problems.append(f"{name} has more than one row; keep one")
    return problems
