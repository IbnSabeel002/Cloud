"""Stable identity for a job, so the same posting on Indeed and Bayt collapses to one row."""

from __future__ import annotations

import hashlib
import re

_COMPANY_NOISE = {
    "llc", "l.l.c", "lle", "fz", "fzc", "fzco", "fze", "fzllc", "fz-llc", "fz-lle", "fzlle", "ltd",
    "limited", "inc", "co", "company", "dmcc", "pjsc", "pvt", "private", "jsc", "sole",
    "proprietorship", "establishment", "est", "branch", "the",
}

_CITIES = ["dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "fujairah", "umm al quwain", "al ain"]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def norm_company(name: str | None) -> str:
    if not name:
        return ""
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^\w\s\-.]", " ", text)
    tokens = []
    for token in re.split(r"\s+", text):
        bare = token.strip(".-")
        if not bare or bare in _COMPANY_NOISE or bare.replace(".", "") in _COMPANY_NOISE:
            continue
        tokens.append(bare.replace(".", ""))
    return _squash(" ".join(tokens))


def norm_title(title: str | None) -> str:
    if not title:
        return ""
    text = title.lower()
    text = re.sub(r"\([^)]*\)", " ", text)  # "(Onsite - Dubai)", "(Global)"
    text = re.sub(r"\s[-–|,]\s*(?:dubai|abu dhabi|uae|united arab emirates|onsite|hybrid|remote)\b.*$", " ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    return _squash(text)


def norm_city(location: str | None) -> str:
    if not location:
        return "dubai"
    low = location.lower()
    for city in _CITIES:
        if city in low:
            return city
    return _squash(re.sub(r"[^\w\s]", " ", low)) or "dubai"


def job_key(company: str | None, title: str | None, location: str | None) -> str:
    return f"{norm_company(company)}|{norm_title(title)}|{norm_city(location)}"


def job_id(key: str) -> str:
    return "j_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
