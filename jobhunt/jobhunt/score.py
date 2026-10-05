"""Screen and score one candidate. Pure functions, no I/O.

The model extracts structured fields from a listing; this module decides what to
do with them. Every rejection records a reason so the digest can say why.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from .dates import age_days, parse_posted
from .normalize import job_id, job_key, norm_company
from .salary import PayRange, parse_pay

FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "live.com"}
BENIGN_PAY_ASSUMPTIONS = {"period_assumed_monthly", "currency_assumed_aed"}
_LANGUAGE_ALIASES = {"mandarin": "chinese", "cantonese": "chinese", "farsi": "persian", "tagalog": "filipino"}

_COMMISSION_ONLY = re.compile(
    r"commission[\s-]*only|100\s*%\s*commission|commission[\s-]*based\s+(?:only|salary)|"
    r"no\s+(?:basic|fixed)\s+salary|without\s+(?:a\s+)?basic\s+salary",
    re.I,
)
_UPFRONT_FEE = re.compile(
    r"\b(?:registration|joining|training|security|processing|application)\s+(?:fee|fees|deposit)\b|"
    r"\b(?:you|candidates?|applicants?)\s+(?:must|will|have\s+to|need\s+to|should)\s+pay\b",
    re.I,
)
_AI_MENTION = re.compile(r"\bai\b|artificial intelligence|generative", re.I)


@dataclass
class Evaluation:
    key: str
    job_id: str
    company: str
    title: str
    location: str
    url: str
    source: str
    all_urls: list = field(default_factory=list)
    posted: str | None = None
    age_days: int | None = None
    pay_display: str = "not listed"
    pay_source: str = "unknown"
    pay_monthly_mid: float | None = None
    tier: str = "U"
    components: dict = field(default_factory=dict)
    score: int = 0
    reject_reasons: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    status: str = "rejected"  # rejected | below_threshold | shortlisted
    strong: bool = False
    apply_method: str = "unknown"
    apply_email: str | None = None
    description: str = ""
    why: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def validate_candidate(c: dict) -> list[str]:
    problems = []
    if not isinstance(c, dict):
        return ["candidate is not an object"]
    for required in ("title", "company"):
        if not str(c.get(required) or "").strip():
            problems.append(f"missing {required}")
    return problems


# ---------------------------------------------------------------- text helpers

def _squash_for_matching(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-_/]+", " ", text.lower())).strip()


def has_phrase(haystack: str, phrase: str) -> bool:
    pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(p) for p in phrase.lower().split()) + r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def _norm_language(name: str) -> str:
    low = str(name).strip().lower()
    return _LANGUAGE_ALIASES.get(low, low)


# ------------------------------------------------------------------- components

def title_points(title: str, description: str, profile: dict) -> tuple[int, str]:
    text = _squash_for_matching(title)
    best, best_phrase = 0, ""
    for group in profile["title_keywords"]:
        for phrase in group["phrases"]:
            if group["points"] > best and has_phrase(text, phrase):
                best, best_phrase = group["points"], phrase
    if best and best < 30 and len(_AI_MENTION.findall(description)) >= 2:
        best = min(30, best + 4)
        best_phrase += " + AI in JD"
    return best, best_phrase


def skill_points(title: str, description: str, profile: dict) -> tuple[int, list[str], bool]:
    """Returns (points, matched terms, jd_missing)."""
    if len((description or "").strip()) < 120:
        return 8, [], True
    text = _squash_for_matching(f"{title}\n{description}")
    hits = [term for term in profile["lexicon"] if has_phrase(text, term)]
    return min(25, 5 * len(hits)), hits, False


def seniority_points(years: int | None, title: str, profile: dict) -> tuple[int, list[str]]:
    flags = []
    have = profile.get("years_experience")
    if years is None:
        points = 10
    elif years <= 1:
        points = 6
    elif have is not None:
        # Marked down by how far the post's minimum is above what the candidate has.
        gap = years - have
        points = 15 if gap <= 0 else {1: 12, 2: 9, 3: 6}.get(gap, 3)
    elif years <= 6:
        points = 15
    elif years <= 9:
        points = 9
    else:
        points = 3
    text = _squash_for_matching(title)
    if any(has_phrase(text, t) for t in profile["soft_junior_title_terms"]):
        points = min(points, 6)
        flags.append("junior_title")
    return points, flags


def tier_for(pay: PayRange | None, profile: dict) -> str:
    """A/B/C by midpoint, U when the pay cannot be judged, X when the top of the range is under the floor."""
    if pay is None:
        return "U"
    if pay.ceiling is not None and pay.ceiling < profile["floor"]:
        return "X"
    if pay.high is None and pay.low is not None and pay.low < profile["floor"]:
        return "U"  # open-ended ("from 3,000"): the ceiling is unknown
    value = pay.midpoint
    if value >= profile["tier_a"]:
        return "A"
    if value >= profile["tier_b"]:
        return "B"
    return "C"  # midpoint >= floor, or a range that straddles the floor


def format_pay(pay: PayRange | None) -> str:
    if pay is None:
        return "not listed"

    def n(v: float) -> str:
        return f"{round(v):,}"

    if pay.low is not None and pay.high is not None:
        body = n(pay.low) if round(pay.low) == round(pay.high) else f"{n(pay.low)}–{n(pay.high)}"
    elif pay.low is not None:
        body = f"{n(pay.low)}+"
    else:
        body = f"up to {n(pay.high)}"
    approx = "≈ " if pay.currency != "AED" or pay.period != "month" else ""
    return f"{approx}AED {body}/mo"


def freshness_points(age: int | None) -> int:
    if age is None:
        return 0
    if age <= 3:
        return 5
    if age <= 7:
        return 3
    if age <= 14:
        return 1
    return 0


# --------------------------------------------------------------------- evaluate

def evaluate(c: dict, profile: dict, today: date) -> Evaluation:
    title = str(c.get("title") or "").strip()
    company = str(c.get("company") or "").strip()
    location = str(c.get("location") or "Dubai").strip()
    description = str(c.get("description") or "")
    key = job_key(company, title, location)

    ev = Evaluation(
        key=key,
        job_id=job_id(key),
        company=company,
        title=title,
        location=location,
        url=str(c.get("url") or ""),
        source=str(c.get("source") or "other"),
        all_urls=[u for u in (c.get("all_urls") or [c.get("url")]) if u],
        apply_method=str(c.get("apply_method") or "unknown"),
        apply_email=(c.get("apply_email") or None),
        description=description,
    )
    reasons: list[str] = []
    flags: list[str] = []

    # --- freshness
    posted = parse_posted(c.get("posted"), today)
    age = age_days(posted, today)
    ev.posted = posted.day.isoformat() if posted else None
    ev.age_days = age
    if age is None:
        flags.append("no_date")
    elif age > profile["stale_days"]:
        reasons.append("stale")

    # --- level / seniority label
    level_text = _squash_for_matching(f"{c.get('level_label') or ''} {title}")
    for term in profile["reject_level_terms"]:
        if has_phrase(level_text, term):
            reasons.append("junior_level")
            break

    # --- pay
    pay = parse_pay(c.get("pay_text"))
    tier = tier_for(pay, profile)
    ev.tier = tier
    ev.pay_display = format_pay(pay)
    ev.pay_source = str(c.get("pay_source") or ("listing" if pay else "unknown"))
    ev.pay_monthly_mid = round(pay.midpoint) if pay else None
    if pay is not None:
        # Monthly AED is the normal case in the UAE; only surface assumptions that could mislead.
        flags.extend(f"pay_assumed:{a}" for a in pay.assumptions if a not in BENIGN_PAY_ASSUMPTIONS)
    if tier == "X":
        reasons.append("pay_below_floor")
    elif pay is None:
        flags.append("pay_unlisted")
    elif pay.low is not None and pay.high is not None and pay.midpoint < profile["floor"]:
        flags.append("pay_straddles_floor")
    elif pay.high is None and pay.low is not None and pay.low < profile["floor"]:
        # "From AED 1,111" is usually a board placeholder, but it is also what a low payer advertises.
        flags.append("pay_min_below_floor")
    if ev.pay_source == "estimate":
        flags.append("pay_estimate")

    # --- languages
    allowed = {_norm_language(x) for x in profile["languages"]}
    flag_only = {_norm_language(x) for x in profile["languages_flag_only"]}
    for lang in c.get("languages_required") or []:
        norm = _norm_language(lang)
        if norm in allowed:
            continue
        if norm in flag_only:
            flags.append(f"language:{norm}")
        else:
            reasons.append(f"language:{norm}")

    # --- job type
    job_type = str(c.get("job_type") or "").strip().lower()
    if job_type and job_type in {t.lower() for t in profile["reject_job_types"]}:
        reasons.append(f"job_type:{job_type}")
    elif job_type == "contract":
        flags.append("contract")
    if not any(r.startswith("job_type:") for r in reasons):
        title_words = _squash_for_matching(title)
        for term in profile["reject_job_types"]:
            if has_phrase(title_words, term):  # e.g. a "Freelance ..." title on a post the board calls permanent
                flags.append("title_says:" + term.replace(" ", "_"))
                break

    # --- scam and quality signals
    haystack = f"{title}\n{description}"
    if _COMMISSION_ONLY.search(haystack):
        reasons.append("commission_only")
    if _UPFRONT_FEE.search(haystack):
        reasons.append("upfront_fee")
    if ev.apply_method == "whatsapp":
        reasons.append("whatsapp_only_apply")

    # --- visa
    visa = str(c.get("visa_info") or "not_stated")
    if visa == "not_sponsored" and profile.get("needs_visa_sponsorship") is True:
        reasons.append("no_visa_sponsorship")
    elif visa in ("not_stated", ""):
        flags.append("visa_not_stated")

    if c.get("gender_restricted"):
        flags.append("gender_restricted")

    # Observations only the model can make (employer_mismatch, prompt_injection_attempt, ...).
    # Strictly validated: these come from the model reading untrusted text, and they end up in a report.
    valid_extras = [
        label for label in (str(x).strip().lower() for x in (c.get("extra_flags") or []))
        if re.fullmatch(r"[a-z0-9_:]{1,40}", label)
    ]
    flags.extend(valid_extras[:5])  # validate first, then cap, so junk cannot crowd out real flags

    # --- components
    t_pts, t_phrase = title_points(title, description, profile)
    s_pts, hits, jd_missing = skill_points(title, description, profile)
    if jd_missing:
        flags.append("no_jd")
    years = c.get("years_required")
    years = int(years) if isinstance(years, (int, float)) else None
    sen_pts, sen_flags = seniority_points(years, title, profile)
    flags.extend(sen_flags)
    pay_pts = {"A": 20, "B": 14, "C": 8, "U": 8}.get(tier, 0)
    fresh_pts = freshness_points(age)

    adjust = 0
    domain = (ev.apply_email or "").rsplit("@", 1)[-1].lower() if ev.apply_email else ""
    if domain in FREE_EMAIL_DOMAINS:
        adjust -= 8
        flags.append("free_email_apply")
    title_for_negatives = _squash_for_matching(title).replace("prompt engineer", " ")
    if any(has_phrase(title_for_negatives, t) for t in profile.get("negative_title_terms", [])):
        adjust -= 8
        flags.append("engineering_role")
    scope = [s for s in (c.get("scope_items") or []) if str(s).strip()]
    if len(scope) >= 4:
        adjust -= 10 if tier in ("C", "U") else 4
        flags.append("scope_bloat")
    if not company or "confidential" in company.lower():
        adjust -= 5
        flags.append("employer_hidden")
    watch = {norm_company(w) for w in profile.get("watchlist_companies", [])}
    if norm_company(company) in watch:
        adjust += 5
        flags.append("watchlist_company")
    adjust = max(-20, min(5, adjust))

    total = t_pts + s_pts + sen_pts + pay_pts + fresh_pts + adjust
    if t_pts == 0:
        total = min(total, 40)  # nothing in the title matches what you are hunting for
        flags.append("off_target_title")
    total = max(0, min(100, total))

    ev.components = {
        "title": t_pts, "skills": s_pts, "seniority": sen_pts,
        "pay": pay_pts, "freshness": fresh_pts, "adjustment": adjust,
    }
    ev.score = total
    ev.reject_reasons = list(dict.fromkeys(reasons))
    ev.flags = list(dict.fromkeys(flags))

    if ev.reject_reasons:
        ev.status = "rejected"
    elif total >= profile["shortlist_threshold"]:
        ev.status = "shortlisted"
        ev.strong = total >= profile["strong_threshold"]
    else:
        ev.status = "below_threshold"

    parts = []
    if t_phrase:
        parts.append(f"title match: {t_phrase}")
    if hits:
        parts.append("skills in JD: " + ", ".join(hits[:6]))
    ev.why = "; ".join(parts) or "weak match"
    return ev


# ------------------------------------------------------------ batch de-duplication

def dedupe_candidates(candidates: list[dict]) -> tuple[list[dict], int]:
    """Collapse the same job seen on several boards. Keeps the richest record."""
    best: dict[str, dict] = {}
    urls: dict[str, list] = {}
    duplicates = 0
    for c in candidates:
        key = job_key(c.get("company"), c.get("title"), c.get("location"))
        if key not in best:
            best[key] = dict(c)
            urls[key] = [c["url"]] if c.get("url") else []
            continue
        duplicates += 1
        if c.get("url") and c["url"] not in urls[key]:
            urls[key].append(c["url"])
        kept = best[key]

        def richness(rec: dict) -> tuple:
            return (bool(rec.get("pay_text")), len(rec.get("description") or ""))

        # "Has a pay figure" ranks first, so the winner always keeps the pay if either record has one.
        base, other = (dict(c), kept) if richness(c) > richness(kept) else (kept, c)
        if len(other.get("description") or "") > len(base.get("description") or ""):
            base["description"] = other["description"]
        best[key] = base
    for key, record in best.items():
        record["all_urls"] = urls[key]
    return list(best.values()), duplicates
