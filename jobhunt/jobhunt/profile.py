"""Search profile: salary policy, title weights, skill lexicon, language rules.

The defaults are generic on purpose. The real values (name, pay target, resume
skills) live in the private Routine prompt and are written to profile.json at
run time. Nothing personal belongs in this file or in git.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

DEFAULT_PROFILE: dict = {
    # Salary policy (monthly AED).
    "floor": 4000,
    "tier_a": 8000,
    "tier_b": 5000,
    # Screening.
    "stale_days": 21,
    "shortlist_threshold": 60,
    # A listing with no job description (a job-alert email gives title, company and place only) cannot earn the
    # skills points and has no pay, so it is judged on the title and the rest. Pay and skills are checked by the user.
    "thin_shortlist_threshold": 50,
    "strong_threshold": 75,
    "max_outreach": 5,
    "prune_days": 30,
    # Candidate facts used for scoring.
    "languages": ["english"],
    "languages_flag_only": ["arabic"],
    "needs_visa_sponsorship": None,
    # Places that rule a job out (the candidate lives in Dubai), and other UAE places that only get a flag.
    "reject_locations": [
        "riyadh", "jeddah", "dammam", "khobar", "saudi arabia", "saudi", "ksa", "doha", "qatar", "kuwait",
        "bahrain", "manama", "muscat", "oman", "cairo", "egypt", "amman", "jordan", "beirut", "lebanon",
        "india", "pakistan", "karachi", "lahore", "london", "united kingdom", "singapore", "hong kong",
    ],
    "flag_locations": ["abu dhabi", "al ain", "ras al khaimah", "fujairah", "umm al quwain", "sharjah", "ajman"],
    "watchlist_companies": [],
    "reject_level_terms": [
        "fresher", "entry level", "entry-level", "junior", "intern", "internship",
        "trainee", "graduate", "graduates",
    ],
    "soft_junior_title_terms": ["executive", "assistant", "coordinator", "admin", "associate"],
    "reject_job_types": ["part-time", "part time", "freelance", "internship", "intern"],
    # Years of experience the candidate has. When set, a post asking for more is marked down by the gap.
    "years_experience": None,
    # Engineering titles need a software background; a "Generative AI" in the title does not change that.
    "negative_title_terms": ["engineer", "developer", "architect", "scientist", "devops", "programmer"],
    "title_keywords": [
        {"points": 30, "phrases": [
            "creative ai", "ai creative", "generative ai", "gen ai", "genai", "ai content",
            "ai video", "ai marketing", "ai social", "ai influencer", "ai media", "ai producer",
            "ai specialist", "ai strategist", "creative technologist", "prompt engineer",
            "ai artist", "ai art director",
        ]},
        {"points": 26, "phrases": ["ai designer", "ai visual"]},
        {"points": 24, "phrases": [
            "social media manager", "head of social", "social media lead", "social media and ai",
            "social media and marketing manager", "social media marketing manager",
            "social media and digital marketing",
        ]},
        {"points": 22, "phrases": [
            "marketing operations", "marketing automation", "digital transformation",
            "marketing technologist", "martech", "marketing technology", "growth operations",
            "ai automation", "ai and automation", "agentic ai", "automation specialist",
        ]},
        {"points": 16, "phrases": [
            "social media specialist", "digital marketing manager", "content strategist",
            "creative producer", "creative director", "content manager", "creative lead",
            "content lead", "brand manager",
        ]},
        {"points": 10, "phrases": [
            "digital marketing", "marketing manager", "content creator", "social media",
            "content specialist", "marketing specialist",
        ]},
    ],
    "lexicon": [
        "generative ai", "prompt", "comfyui", "midjourney", "stable diffusion", "kling", "veo",
        "runway", "sora", "higgsfield", "canva", "capcut", "meta ads", "google ads",
        "google analytics", "ga4", "tiktok", "instagram", "linkedin", "n8n", "zapier",
        "langchain", "python", "automation", "crm", "hubspot", "remotion", "after effects",
        "premiere", "figma", "agentic", "ai agents", "seo", "influencer", "content calendar",
        "copywriting", "analytics", "video editing", "chatgpt", "claude",
    ],
}


def load_profile(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    """Defaults, then the JSON file, then explicit overrides. Unknown keys pass through."""
    profile = copy.deepcopy(DEFAULT_PROFILE)
    if path:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("profile.json must contain a JSON object")
        profile.update(data)
    if overrides:
        profile.update(overrides)
    _validate(profile)
    return profile


def _validate(profile: dict) -> None:
    if not (profile["floor"] <= profile["tier_b"] <= profile["tier_a"]):
        raise ValueError("salary policy must satisfy floor <= tier_b <= tier_a")
    if not (0 <= profile["shortlist_threshold"] <= profile["strong_threshold"] <= 100):
        raise ValueError("thresholds must satisfy 0 <= shortlist <= strong <= 100")
    if not (0 <= profile["thin_shortlist_threshold"] <= profile["shortlist_threshold"]):
        raise ValueError("thin_shortlist_threshold must satisfy 0 <= thin <= shortlist")
    if profile["stale_days"] < 1:
        raise ValueError("stale_days must be at least 1")
