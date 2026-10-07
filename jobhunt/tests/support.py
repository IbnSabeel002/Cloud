"""Shared helpers for tests that run the prefilter command, which refuses to start without a complete health file."""

import json
from pathlib import Path


def complete_health() -> list:
    """One honest row for every source the prefilter needs. Indeed is marked as not available so no count is demanded."""
    rows = [{"source": name, "ok": True, "detail": "test"} for name in
            ("Settings", "Tiny Fish pages", "Bayt pages", "GulfTalent", "Naukrigulf", "Gmail alerts", "Other alerts")]
    rows.insert(1, {"source": "Indeed connector", "ok": False, "reason": "tool_missing",
                    "detail": "search_jobs does not exist in this session"})
    return rows


def write_health(path, rows=None) -> Path:
    path = Path(path)
    path.write_text(json.dumps(complete_health() if rows is None else rows), encoding="utf-8")
    return path
