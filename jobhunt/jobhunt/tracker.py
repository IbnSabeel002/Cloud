"""The tracker: one row per shortlisted job, carried from day to day.

Google Drive cannot overwrite a file's content through the connector, so the agent
writes a fresh dated snapshot every run and reads back the newest one. That makes
this module the only memory the agent has. It must:

  * round-trip exactly (the content hash proves it),
  * keep what you typed in Status and Notes,
  * never resurrect a job you rejected or applied to,
  * tolerate whatever text rendering Drive hands back (CSV, TSV, markdown table).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from datetime import date, timedelta

COLUMNS = [
    "Key", "FirstSeen", "LastSeen", "Status", "Score", "Tier", "Pay", "PaySource",
    "Company", "Title", "Source", "URL", "Flags", "Notes",
]

STATUSES = ["Shortlisted", "Applied", "Interview", "Offer", "Accepted", "Rejected", "Dead"]
# Rows in these states are never pruned and never touched automatically.
PROTECTED = {"Applied", "Interview", "Offer", "Accepted"}
_STATUS_ORDER = {s: i for i, s in enumerate(["Interview", "Offer", "Applied", "Shortlisted", "Accepted", "Rejected", "Dead"])}

_SYNONYMS = {
    "": "Shortlisted", "new": "Shortlisted", "shortlisted": "Shortlisted", "shortlist": "Shortlisted",
    "applied": "Applied", "apply": "Applied", "interview": "Interview", "interviewing": "Interview",
    "interviews": "Interview", "offer": "Offer", "offered": "Offer", "accepted": "Accepted",
    "hired": "Accepted", "joined": "Accepted", "rejected": "Rejected", "reject": "Rejected",
    "skip": "Rejected", "skipped": "Rejected", "pass": "Rejected", "declined": "Rejected",
    "not interested": "Rejected", "withdrawn": "Rejected", "dead": "Dead", "closed": "Dead",
    "expired": "Dead", "filled": "Dead",
}


def canonical_status(value: str | None) -> str:
    """Map whatever the user typed to a known status; unknown text is kept as typed."""
    text = (value or "").strip()
    return _SYNONYMS.get(text.lower(), text)


# ----------------------------------------------------------------------- parsing

_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_TABLE_RANGE = re.compile(r"Table Range:\s*[A-Z]+1:[A-Z]+(\d+)", re.I)


def _md_unescape(cell: str) -> str:
    """Drive's text rendering is markdown: it writes j\\_9c79 for j_9c79 and \\| for a literal pipe."""
    return re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", cell)


def _split_rows(text: str) -> list[list[str]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    header_idx = next(
        (i for i, ln in enumerate(lines) if re.search(r"\bkey\b", ln, re.I) and re.search(r"\bstatus\b", ln, re.I)),
        None,
    )
    if header_idx is None:
        return []
    body = lines[header_idx:]
    head = body[0]
    if head.lstrip().startswith("|"):
        rows = []
        for ln in body:
            stripped = ln.strip()
            if not stripped.startswith("|"):
                break  # the table ended; Drive appends a "Table Columns" summary after it
            cells = [c.strip() for c in _UNESCAPED_PIPE.split(stripped.strip("|"))]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # markdown separator row
            rows.append([_md_unescape(c) for c in cells])
        return rows
    delimiter = "\t" if head.count("\t") >= head.count(",") and "\t" in head else ","
    return [row for row in csv.reader(io.StringIO("\n".join(body)), delimiter=delimiter)]


def parse_table(text: str) -> tuple[list[dict], list[str]]:
    """Returns (rows, warnings). Never raises on malformed input: a bad row is skipped and reported."""
    warnings: list[str] = []
    text = (text or "").lstrip("﻿")
    raw = _split_rows(text)
    if not raw:
        if text.strip():
            warnings.append("no header row with Key and Status columns found")
        return [], warnings
    header = [h.strip().lower() for h in raw[0]]
    index = {col: header.index(col.lower()) for col in COLUMNS if col.lower() in header}
    for col in ("Key", "Status"):
        if col not in index:
            return [], [f"missing required column {col}"]
    extra = [h for h in raw[0] if h.strip().lower() not in {c.lower() for c in COLUMNS} and h.strip()]
    if extra:
        warnings.append("ignored unknown columns: " + ", ".join(extra))
    rows = []
    for n, cells in enumerate(raw[1:], start=2):
        row = {col: (cells[index[col]].strip() if col in index and index[col] < len(cells) else "") for col in COLUMNS}
        if not row["Key"]:
            warnings.append(f"row {n}: no Key, skipped")
            continue
        row["Status"] = canonical_status(row["Status"])
        rows.append(row)
    declared = _TABLE_RANGE.search(text)
    if declared and len(rows) != int(declared.group(1)) - 1:
        # Drive states the table's size. A different count means the read-back was cut short or mangled.
        warnings.append(f"readback incomplete: Drive reports {int(declared.group(1)) - 1} data rows, parsed {len(rows)}")
    return rows, warnings


# ------------------------------------------------------------------------- output

def _sort_key(row: dict):
    try:
        score = -int(float(row["Score"]))
    except (TypeError, ValueError):
        score = 0
    return (_STATUS_ORDER.get(row["Status"], 99), score, row["FirstSeen"], row["Key"])


def dump_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in sorted(rows, key=_sort_key):
        writer.writerow({col: row.get(col, "") for col in COLUMNS})
    return buf.getvalue()


def _norm_cell(col: str, value) -> str:
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    if col == "Score" and text:
        try:
            return str(int(float(text)))
        except ValueError:
            return text
    return text


def content_hash(rows: list[dict]) -> str:
    """Hash of the canonical content. Independent of row order, quoting and whitespace."""
    lines = []
    for row in sorted(rows, key=lambda r: r["Key"]):
        lines.append("\x1f".join(_norm_cell(col, row.get(col, "")) for col in COLUMNS))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# -------------------------------------------------------------------------- merge

def _clean(value) -> str:
    """Scraped text may carry newlines or tabs; one stray one breaks a table rendered back as text."""
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def _row_from_eval(ev, today: date) -> dict:
    return {
        "Key": ev.job_id, "FirstSeen": today.isoformat(), "LastSeen": today.isoformat(),
        "Status": "Shortlisted", "Score": str(ev.score), "Tier": ev.tier, "Pay": _clean(ev.pay_display),
        "PaySource": _clean(ev.pay_source), "Company": _clean(ev.company), "Title": _clean(ev.title),
        "Source": _clean(ev.source), "URL": _clean(ev.url), "Flags": ";".join(ev.flags), "Notes": "",
    }


def merge(existing: list[dict], evaluations: list, today: date, profile: dict) -> tuple[list[dict], dict]:
    """Fold today's evaluations into yesterday's rows.

    Returns (rows, stats). `stats["added_ids"]` are the jobs that are new today.
    """
    rows = {r["Key"]: dict(r) for r in existing}
    stats = {
        "added_ids": [], "already_seen": 0, "below_threshold": 0, "rejected_jobs": 0,
        "reject_reasons": Counter(), "auto_dead": 0, "pruned": 0,
    }
    for ev in evaluations:
        row = rows.get(ev.job_id)
        if row is not None:
            stats["already_seen"] += 1
            if ev.status == "shortlisted" and row["Status"] == "Shortlisted":  # the user has not acted
                fresh = {
                    "Score": str(ev.score), "Tier": ev.tier, "Pay": _clean(ev.pay_display),
                    "PaySource": _clean(ev.pay_source), "URL": _clean(ev.url) or row["URL"], "Flags": ";".join(ev.flags),
                }
                if any(_norm_cell(k, row[k]) != _norm_cell(k, v) for k, v in fresh.items()):
                    row.update(fresh)
                    row["LastSeen"] = today.isoformat()  # LastSeen means: last time the agent wrote this row
            elif (ev.status != "shortlisted" and row["Status"] == "Shortlisted"
                  and ("stale" in ev.reject_reasons or "expired" in ev.reject_reasons)):
                row["Status"] = "Dead"
                row["LastSeen"] = today.isoformat()
                why = "went stale" if "stale" in ev.reject_reasons else "expired"
                row["Notes"] = (row["Notes"] + " " if row["Notes"] else "") + f"auto: posting {why}"
                stats["auto_dead"] += 1
            continue
        if ev.status == "shortlisted":
            rows[ev.job_id] = _row_from_eval(ev, today)
            stats["added_ids"].append(ev.job_id)
        elif ev.status == "below_threshold":
            stats["below_threshold"] += 1
        else:
            stats["rejected_jobs"] += 1
            stats["reject_reasons"].update(ev.reject_reasons)

    # Pruned by FirstSeen, not LastSeen: a job first seen more than `prune_days` ago would be screened out as
    # stale if it came back, so its row no longer protects against anything.
    cutoff = today - timedelta(days=profile["prune_days"])
    for key in list(rows):
        row = rows[key]
        if row["Status"] in PROTECTED:
            continue
        try:
            first = date.fromisoformat(row["FirstSeen"])
        except ValueError:
            continue  # unparseable date: keep the row rather than silently drop the user's data
        if first < cutoff:
            del rows[key]
            stats["pruned"] += 1
    return list(rows.values()), stats


def stop_reasons(rows: list[dict]) -> list[str]:
    return [f"Accepted: {r['Company']} - {r['Title']}" for r in rows if r["Status"] == "Accepted"]


def hunt_day(rows: list[dict], today: date, hunt_start: str | None = None) -> int | None:
    start = None
    if hunt_start:
        try:
            start = date.fromisoformat(hunt_start)
        except ValueError:
            start = None
    if start is None:
        firsts = []
        for r in rows:
            try:
                firsts.append(date.fromisoformat(r["FirstSeen"]))
            except ValueError:
                pass
        start = min(firsts) if firsts else None
    return None if start is None else (today - start).days + 1
