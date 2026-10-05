"""Turn job-alert emails into candidate jobs.

The model reads a mailbox badly: one LinkedIn alert is 130,000 characters of HTML, and
the same job appears two or three times in it. The plain-text part is small and regular,
so a script reads that and the model never has to.

Only LinkedIn job-alert mail is understood. Anything else (application receipts, invitations,
marketing, other boards) is skipped and counted, never guessed at.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .score import ALERT_MARK, ALERT_SOURCE

# LinkedIn sends alerts from jobalerts-noreply@linkedin.com. jobs-noreply@ is application
# receipts and "similar jobs", which are not alerts.
# The address must end the sender field (or its angle brackets), so "...linkedin.com.evil.example" is not accepted.
_ALERT_SENDER = re.compile(r"(?:^|<)\s*jobalerts-noreply@linkedin\.com\s*(?:>|$)", re.I)
_JOB_URL = re.compile(r"https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/(\d+)", re.I)
_ALERT_HEADER = re.compile(r"^Your job alert for (.+?) in (.+)$", re.I)

# Lines that follow a job's location, or that are page furniture.
_NOISE = [
    re.compile(p, re.I) for p in (
        r"^this company is actively hiring$", r"^actively recruiting$", r"^apply with resume\b",
        r"^easy apply$", r"^be an early applicant$", r"^promoted$", r"^viewed$",
        r"^\d+ (?:school |company )?alum\w*\b", r"^\d+ (?:connections?|applicants?)\b",
    )
]
_FURNITURE = re.compile(
    r"^(?:https?://|see all jobs|edit alert|manage (?:your )?alerts?|your job alert|a new job matches|"
    r"new jobs? match|new jobs from your other alerts|stand out and let|learn why we included|"
    r"this email was intended|you are receiving|unsubscribe|help:|©)", re.I)
_SEPARATOR = re.compile(r"^-{5,}\s*$")


def canonical_url(url: str) -> str | None:
    """`.../comm/jobs/view/123/?trackingId=...` becomes `https://www.linkedin.com/jobs/view/123/`.

    The tracking parameters identify the reader, so they are never kept, and the link that is
    kept is never opened by the agent (LinkedIn is not scraped).
    """
    m = _JOB_URL.search(url or "")
    return f"https://www.linkedin.com/jobs/view/{m.group(1)}/" if m else None


def _is_noise(line: str) -> bool:
    return any(p.match(line) for p in _NOISE)


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(line)).strip()


def parse_linkedin_alert(plaintext: str) -> tuple[list[dict], dict]:
    """Jobs in one alert's plain text, plus facts about the alert. Duplicates inside it are merged."""
    meta: dict = {"keyword": None, "place": None}
    jobs: dict[str, dict] = {}
    block: list[str] = []
    for raw in (plaintext or "").splitlines():
        line = _clean(raw)
        if not line:
            continue
        head = _ALERT_HEADER.match(line)
        if head and meta["keyword"] is None:
            meta["keyword"], meta["place"] = head.group(1).strip(), head.group(2).strip()
            continue
        if _SEPARATOR.match(line):
            block = []
            continue
        if line.lower().startswith("view job:"):
            url = canonical_url(line)
            content = [b for b in block if not _is_noise(b)]
            block = []
            if not url or len(content) < 2:
                continue
            job_id = url.rstrip("/").rsplit("/", 1)[-1]
            title, company = content[-3:][0:2] if len(content) >= 3 else content[:2]
            location = content[-1] if len(content) >= 3 else None
            jobs.setdefault(job_id, {
                "source": ALERT_SOURCE, "parsed_by": ALERT_MARK, "source_id": job_id, "title": title,
                "company": company, "location": location, "url": url, "posted": None,
            })
            continue
        if line.startswith("<") or "<strong" in line or _FURNITURE.match(line):
            continue
        block.append(line)
    return list(jobs.values()), meta


def _messages_in(path: Path) -> list[dict]:
    """Messages from a file written by Gmail `get_thread` (or a list of such messages)."""
    text = path.read_text(encoding="utf-8")
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError(f"{path}: no JSON found")
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    if isinstance(data, dict) and "messages" in data:
        return list(data["messages"])
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    if isinstance(data, dict):
        return [data]
    raise ValueError(f"{path}: not a Gmail thread")


def parse_threads(paths: list[Path]) -> tuple[list[dict], dict]:
    """Candidates from saved Gmail threads, one per distinct job, and what was skipped and why."""
    jobs: dict[str, dict] = {}
    stats = {"emails": 0, "alerts": 0, "jobs_in_alerts": 0, "skipped": {}}

    def skip(reason: str) -> None:
        stats["skipped"][reason] = stats["skipped"].get(reason, 0) + 1

    for path in paths:
        for msg in _messages_in(Path(path)):
            stats["emails"] += 1
            if not _ALERT_SENDER.search(str(msg.get("sender") or "")):
                skip("not_a_linkedin_job_alert")
                continue
            found, meta = parse_linkedin_alert(str(msg.get("plaintextBody") or ""))
            if not found:
                skip("alert_without_jobs")
                continue
            stats["alerts"] += 1
            stats["jobs_in_alerts"] += len(found)
            for job in found:
                if job["source_id"] not in jobs:
                    jobs[job["source_id"]] = job
    return list(jobs.values()), stats
