"""Each job card on an Indeed results page has its own link. Find them, in page order.

The page text and the page's link list come back separately. The `rc/clk?jk=<id>` links appear in the
same order as the result cards, so the k-th link belongs to the k-th card. The model must never use the
search page's own address as a job's link: tomorrow it shows different jobs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Only the click-through and view links carry the job's own id. "fromjk=" (salary pages) and
# the encoded copies inside apply links are not matched on purpose.
_JOB_LINK = re.compile(
    r"https?://(?P<host>[a-z0-9-]+\.indeed\.com)/(?:rc/clk|viewjob)\?(?:[^#\s]*?&)?jk=(?P<jk>[0-9a-f]{16})(?![0-9a-f])",
    re.I,
)
_PLACEHOLDER_IDS = {"abcdef0123456789"}  # a template link Indeed leaves in the page, not a real job


def job_links(links: list[str]) -> list[str]:
    """Clean `viewjob?jk=<id>` links, one per distinct job, in the order the page lists them."""
    seen: set[str] = set()
    out: list[str] = []
    for link in links or []:
        m = _JOB_LINK.match(str(link).strip())
        if not m:
            continue
        jk = m.group("jk").lower()
        if jk in _PLACEHOLDER_IDS or jk in seen:
            continue
        seen.add(jk)
        out.append(f"https://{m.group('host').lower()}/viewjob?jk={jk}")
    return out


def pages_in(path: Path) -> list[dict]:
    """Results from a file written by Tiny Fish `fetch_content` (or a bare list of links)."""
    text = Path(path).read_text(encoding="utf-8")
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError(f"{path}: no JSON found")
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return [r for r in data["results"] if isinstance(r, dict)]
    if isinstance(data, list) and all(isinstance(x, str) for x in data):
        return [{"url": None, "links": data}]
    raise ValueError(f"{path}: not a fetch_content result")


def links_by_page(path: Path) -> list[dict]:
    return [{"page": p.get("url"), "job_links": job_links(p.get("links") or [])} for p in pages_in(path)]
