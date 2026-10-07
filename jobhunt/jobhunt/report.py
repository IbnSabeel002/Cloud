"""Turn a run's decisions into a Slack digest and a full report.

Text written by the model (analysis, outreach notes) and text scraped from job
posts is untrusted. Everything that reaches HTML is escaped.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date

from . import coverage

SLACK_LIMIT = 4500  # Slack allows 5,000 per text element; leave headroom.

REASON_LABELS = {
    "stale": "posting too old",
    "expired": "posting expired",
    "junior_level": "fresher/entry/junior",
    "pay_below_floor": "pay under your floor",
    "commission_only": "commission-only",
    "upfront_fee": "asks candidate to pay",
    "whatsapp_only_apply": "WhatsApp-only apply",
    "no_visa_sponsorship": "no visa sponsorship",
    "off_target_title": "title does not match what you hunt",
}
FLAG_LABELS = {
    "no_date": "no posting date", "pay_unlisted": "pay not listed", "pay_estimate": "pay is an estimate",
    "pay_straddles_floor": "range dips below floor", "visa_not_stated": "visa not stated",
    "gender_restricted": "gender-restricted post", "contract": "contract", "no_jd": "no job description captured",
    "junior_title": "junior-sounding title", "free_email_apply": "applies via free email",
    "scope_bloat": "3-jobs-in-1 scope", "employer_hidden": "employer hidden", "off_target_title": "off-target title",
    "watchlist_company": "on your watchlist", "language:arabic": "Arabic required",
    "pay_min_below_floor": "advertised minimum is under your floor",
    "engineering_role": "engineering title, needs a software background",
    "employer_mismatch": "employer name differs from the job text",
    "prompt_injection_attempt": "post tried to give the agent instructions",
    "heavy_overtime": "heavy overtime",
    "asks_current_salary": "asks your current salary",
    "arabic_required": "Arabic required",
    "arabic_native_required": "native Arabic required",
    "emirati_preferred": "Emirati preferred",
    "immediate_joiner": "wants an immediate joiner (check your notice end date)",
    "needs_own_labour_card": "wants you to bring your own labour card (yours must come from the new employer)",
    "no_job_link": "no direct link to the job (search its title and company)",
}


# Text from job posts, emails and tool errors ends up in a message pushed to Slack and a phone. It is untrusted:
# a title like "Role](https://evil.example/login) [Reply now" must not turn into a live link or an injected line.
_URL_OR_EMAIL = re.compile(r"https?://\S+|www\.\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)
_MARKUP = re.compile(r"[\[\]<>`|\\]")
_SAFE_URL = re.compile(r"^https://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::\d+)?(?:[/?#][^\s()<>\[\]`\"'\\|]*)?$")

# Steps whose absence from the health list means the run skipped them (a run that never read the settings looked
# healthy; a run that skipped Gmail "to keep it short" would have looked like a quick one). A name must appear in the
# health file, ok or not. The playbook pins these exact names in section 4. The rules live in coverage.py.
REQUIRED_SOURCES = coverage.REQUIRED


def _plain(text, limit: int = 120) -> str:
    """One line of harmless text: no links, addresses, markup or line breaks, at most `limit` characters."""
    out = _URL_OR_EMAIL.sub("", str(text if text is not None else ""))
    out = re.sub(r"\s+", " ", _MARKUP.sub("", out)).strip()
    return out[:limit].rstrip()


def _safe_url(url) -> str:
    """The link if it is a plain https address that cannot break out of a markdown link, else an empty string."""
    text = str(url or "").strip()
    return text if len(text) <= 300 and _SAFE_URL.match(text) else ""


def reason_label(reason: str) -> str:
    if reason in REASON_LABELS:
        return REASON_LABELS[reason]
    if reason.startswith("language:"):
        return "needs " + reason.split(":", 1)[1].title()
    if reason.startswith("location:"):
        return "based in " + reason.split(":", 1)[1].replace("_", " ").title()
    if reason.startswith("job_type:"):
        return reason.split(":", 1)[1] + " role"
    return reason


def flag_label(flag: str) -> str:
    if flag in FLAG_LABELS:
        return FLAG_LABELS[flag]
    if flag.startswith("pay_assumed:"):
        return "pay " + flag.split(":", 1)[1].replace("_", " ")
    if flag.startswith("title_says:"):
        return "title says " + flag.split(":", 1)[1].replace("_", " ")
    if flag.startswith("outside_dubai:"):
        return "based in " + flag.split(":", 1)[1].replace("_", " ").title() + ", not Dubai"
    if flag.startswith("language:"):
        return flag.split(":", 1)[1].title() + " required"
    return flag


def _age(entry: dict) -> str:
    age = entry.get("age_days")
    return "date unknown" if age is None else ("today" if age == 0 else f"{age}d ago")


def _pay(entry: dict) -> str:
    if entry.get("pay_display") in (None, "", "not listed"):
        # With no description captured the pay was never looked for, which is not the same as "not listed".
        return "pay not checked" if "no_jd" in (entry.get("flags") or []) else "pay not listed"
    return f"{_plain(entry['pay_display'], 60)} ({_plain(entry.get('pay_source', 'unknown'), 20)})"


@dataclass
class HealthView:
    """The health line, the warnings that go under it, and whether the run counts as degraded."""
    line: str
    notes: list = field(default_factory=list)   # each is one line: a warning (starts with ⚠️) or a plain note
    degraded: bool = False


def _alert_warning(summary: dict) -> str:
    """Said out loud when alert entries were typed by hand: the script refuses them (see score.UNPARSED_ALERT)."""
    n = int(summary.get("unparsed_alert_entries") or 0)
    if not n:
        return ""
    return (f"⚠️ {n} LinkedIn alert {'entry' if n == 1 else 'entries'} typed by hand "
            f"{'was' if n == 1 else 'were'} dropped: the parse-alert command was not used.")


def _count_text(canon: str, row: dict, raw_by_source) -> str:
    """What the script itself counted for a green row, such as '27 of 94 results'. Empty when it has no count."""
    typed = coverage.typed_count(raw_by_source, canon)
    if typed is None:
        return ""
    seen = coverage.hits_seen(row)
    if canon == "Indeed connector" and seen:
        return f" ({typed} of {seen} results)"
    return f" ({typed} {'entry' if typed == 1 else 'entries'})"


def _health_view(health: list[dict] | None, summary: dict | None = None, limit_seen=None) -> HealthView:
    """Judge the model's health rows next to what the script counted. `summary` carries the script's own numbers."""
    summary = summary or {}
    raw_by_source = summary.get("raw_by_source")
    notes: list[str] = []
    if not health:
        line, degraded = "Run health: no source report supplied", True
    else:
        parts, degraded, rows = [], False, {}
        for h in health:
            if not isinstance(h, dict):
                continue
            name = _plain(h.get("source"), 60) or "unnamed source"
            canon = coverage.canonical(h.get("source"))
            if canon:
                rows.setdefault(canon, []).append(h)
            if coverage.is_ok(h):
                parts.append(f"✅ {name}" + _count_text(canon, h, raw_by_source))
                if canon in ("Gmail alerts", "Other alerts") and coverage.alert_problem(h):
                    notes.append(f"⚠️ {canon}: {coverage.alert_problem(h)}.")
                continue
            degraded = True
            detail = _plain(h.get("detail"), 120)
            reason = coverage.normalise_reason(h.get("reason"))
            if reason in coverage.REASONS:
                parts.append(f"⚠️ {name} not run: {coverage.REASONS[reason]}" + (f" ({detail})" if detail else ""))
            else:
                parts.append(f"⚠️ {name} failed" + (f" ({detail})" if detail else ""))
            why = coverage.failure_problem(h, limit_seen, reason_required=canon in coverage.ROW_SOURCES)
            if why:
                notes.append(f"⚠️ {canon or name} is marked failed but {why}.")
        for required in coverage.REQUIRED:
            if required not in rows:
                degraded = True
                parts.append(f"⚠️ {required} never reported")
        for dup in coverage.duplicate_rows(health):
            notes.append(f"⚠️ {dup} has more than one row in the health report.")
        indeed = rows.get("Indeed connector")
        if indeed and len(indeed) == 1:
            why = coverage.indeed_problem(indeed[0], coverage.typed_count(raw_by_source, "Indeed connector"))
            if why:
                notes.append(f"⚠️ Indeed connector: {why}.")
        line = "Run health: " + " · ".join(parts)
    unknown = coverage.unknown_sources(raw_by_source)
    if unknown:
        listed = ", ".join(f"{_plain(label, 30) or '(none)'} ×{n}" for label, n in sorted(unknown.items()))
        notes.append(f"⚠️ Some entries had a source label that no health row covers, so they were counted nowhere: {listed}.")
    if summary.get("coverage_unknown"):
        notes.append("⚠️ Coverage unknown: the prefilter result was not used, so the script could not count what was found.")
    picked, finished = summary.get("picked"), summary.get("finished")
    if isinstance(picked, int) and isinstance(finished, int) and finished < picked:
        n = picked - finished
        notes.append(f"⚠️ {n} of {picked} jobs picked for a closer look did not come back finished.")
    if isinstance(summary.get("overflow"), int) and summary["overflow"] > 0:
        notes.append(f"Not opened: {summary['overflow']} more matching jobs were over the daily limit.")
    alert = _alert_warning(summary)
    if alert:
        notes.append(alert)
    degraded = degraded or any(n.startswith("⚠️") for n in notes)
    return HealthView(line, notes, degraded)


def _chunk(text: str, limit: int) -> list[str]:
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single absurdly long line
            if current:
                chunks.append(current.rstrip("\n"))
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit and current:
            chunks.append(current.rstrip("\n"))
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip("\n"))
    return chunks


def digest_chunks(
    summary: dict, shortlist: list[dict], health: list[dict] | None, analysis: dict | None,
    report_url: str | None, today: date, max_top: int = 5, limit: int = SLACK_LIMIT,
    tracker_url: str | None = None, drafts_created: int | None = None, playbook_line: str | None = None,
    limit_seen: float | None = None,
) -> list[str]:
    analysis = analysis or {}
    view = _health_view(health, summary, limit_seen)
    reasons = summary.get("reject_reasons", {})
    out = []
    day = summary.get("hunt_day")
    out.append(f"**Job hunt · {today.strftime('%a %d %b %Y')}" + (f" · day {day}**" if day else "**"))
    if view.degraded:
        out.append("⚠️ **Degraded run — today's list may be incomplete. See the warnings below.**")
    out.append(view.line)
    out.extend(view.notes)
    if playbook_line:
        out.append(_plain(playbook_line, 100))
    out.append(
        f"Today: **{summary['new_shortlisted']} new** shortlisted · {summary['already_seen']} already seen · "
        f"{summary['rejected_jobs']} screened out · {summary['below_threshold']} weak matches"
    )
    if reasons:
        top = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        out.append("Screened out because: " + " · ".join(f"{n} {_plain(reason_label(r), 60)}" for r, n in top))
    out.append("")

    picks = shortlist[:max_top]
    if picks:
        out.append("**Top picks**")
        for i, e in enumerate(picks, 1):
            note = analysis.get(e["job_id"], {})
            name, link = _plain(e["title"]), _safe_url(e.get("url"))
            title = f"[{name}]({link})" if link else name
            out.append(f"{i}. **{title}** — {_plain(e['company'])}")
            out.append(
                f"   Score {e['score']} · Tier {e['tier']} · {_pay(e)} · posted {_age(e)}"
                + (" · ⭐ strong" if e.get("strong") else "")
            )
            out.append("   Why: " + (_plain(note.get("why") or e.get("why"), 300) or "n/a"))
            checks = [_plain(flag_label(f), 80) for f in e.get("flags", []) if f != "pay_unlisted"]  # pay is already shown above
            if checks:
                out.append("   Check: " + ", ".join(checks[:6]))
        extra = len(shortlist) - len(picks)
        if extra > 0:
            out.append(f"…and {extra} more in the report.")
    else:
        out.append("No new matches that clear the bar today. That is normal on slow days; the filter is working.")
    out.append("")
    if _safe_url(report_url):
        out.append(f"Full report + outreach drafts: {report_url}")
    if _safe_url(tracker_url):
        out.append(f"Tracker (change a status or add a note): {tracker_url}")
    strong = len(summary.get("outreach_keys") or [])
    if drafts_created:
        out.append(f"{drafts_created} outreach draft(s) saved in Gmail Drafts. Nothing was sent.")
    if strong and drafts_created != strong:
        # Say only what happened: a draft needs an apply email in the post and a working Gmail connection.
        left = strong - (drafts_created or 0)
        out.append(f"Outreach notes for {left} strong match(es) are in the report (no draft was saved). Nothing was sent.")
    if day and day % 14 == 0:
        out.append(f"Day {day} of the hunt. Still searching? Tell Claude \"stop the job hunt\" to pause me.")
    out.append("To stop: tell Claude \"stop the job hunt\", or set a tracker row to Accepted.")
    return _chunk("\n".join(out), limit)


# ----------------------------------------------------------------------- report

def _esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def _para(text) -> str:
    return _esc(text).replace("\n", "<br>")


def render_report_html(
    summary: dict, shortlist: list[dict], health: list[dict] | None, analysis: dict | None, today: date,
    limit_seen: float | None = None,
) -> str:
    analysis = analysis or {}
    view = _health_view(health, summary, limit_seen)
    parts = [
        f"<h1>Job hunt report · {_esc(today.strftime('%A %d %B %Y'))}</h1>",
        f"<p>{_esc(view.line)}</p>",
        *[f"<p>{_esc(note)}</p>" for note in view.notes],
        "<p>"
        f"<b>{summary['new_shortlisted']}</b> new shortlisted · {summary['already_seen']} already seen · "
        f"{summary['rejected_jobs']} screened out · {summary['below_threshold']} weak matches · "
        f"{summary.get('raw_hits') or summary['candidates_in']} hits found</p>",
    ]
    reasons = summary.get("reject_reasons", {})
    if reasons:
        items = "".join(
            f"<li>{n} × {_esc(reason_label(r))}</li>" for r, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        parts.append(f"<h2>Screened out</h2><ul>{items}</ul>")
    parts.append("<h2>New shortlist</h2>")
    if not shortlist:
        parts.append("<p>No new matches cleared the bar today.</p>")
    for e in shortlist:
        note = analysis.get(e["job_id"], {})
        link = f'<a href="{_esc(_safe_url(e.get("url")))}">{_esc(e["title"])}</a>' if _safe_url(e.get("url")) else _esc(e["title"])
        parts.append(f"<h3>{link} — {_esc(e['company'])}</h3>")
        parts.append(
            f"<p>Score <b>{e['score']}</b>{' (strong)' if e.get('strong') else ''} · Tier {_esc(e['tier'])} · "
            f"{_esc(_pay(e))} · posted {_esc(_age(e))} · via {_esc(e['source'])}</p>"
        )
        c = e.get("components", {})
        parts.append(
            "<p>Title " + str(c.get("title")) + " · Skills " + str(c.get("skills")) + " · Seniority "
            + str(c.get("seniority")) + " · Pay " + str(c.get("pay")) + " · Freshness " + str(c.get("freshness"))
            + " · Adjustment " + str(c.get("adjustment")) + "</p>"
        )
        if e.get("flags"):
            parts.append("<p>Check: " + _esc(", ".join(flag_label(f) for f in e["flags"])) + "</p>")
        for url in (u for u in e.get("all_urls", [])[1:] if _safe_url(u)):
            parts.append(f'<p>Also on: <a href="{_esc(url)}">{_esc(url)}</a></p>')
        if note.get("gaps"):
            parts.append(f"<p><b>Fit and gaps</b><br>{_para(note['gaps'])}</p>")
        if note.get("cv_tweaks"):
            tweaks = "".join(f"<li>{_esc(t)}</li>" for t in note["cv_tweaks"])
            parts.append(f"<p><b>CV tweaks for this role</b></p><ul>{tweaks}</ul>")
        if note.get("linkedin_note"):
            parts.append(f"<p><b>LinkedIn note</b><br>{_para(note['linkedin_note'])}</p>")
        if note.get("email_note"):
            parts.append(f"<p><b>Email note</b><br>{_para(note['email_note'])}</p>")
        if e.get("apply_email"):
            parts.append(f"<p>Apply email in the post: {_esc(e['apply_email'])} (draft only, never sent)</p>")
    return "<html><body>" + "\n".join(parts) + "</body></html>"


def render_report_md(
    summary: dict, shortlist: list[dict], health: list[dict] | None, analysis: dict | None, today: date,
    limit_seen: float | None = None,
) -> str:
    analysis = analysis or {}
    view = _health_view(health, summary, limit_seen)
    lines = [f"# Job hunt report · {today.isoformat()}", "", view.line, ""]
    if view.notes:
        lines += [*view.notes, ""]
    lines.append(
        f"{summary['new_shortlisted']} new shortlisted · {summary['already_seen']} already seen · "
        f"{summary['rejected_jobs']} screened out · {summary['below_threshold']} weak matches"
    )
    for r, n in sorted(summary.get("reject_reasons", {}).items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {n} × {reason_label(r)}")
    for e in shortlist:
        note = analysis.get(e["job_id"], {})
        lines += ["", f"## {e['title']} — {e['company']}",
                  f"Score {e['score']} · Tier {e['tier']} · {_pay(e)} · posted {_age(e)}",
                  _safe_url(e.get("url"))]
        for key, label in (("gaps", "Fit and gaps"), ("linkedin_note", "LinkedIn note"), ("email_note", "Email note")):
            if note.get(key):
                lines += ["", f"**{label}**", note[key]]
        if note.get("cv_tweaks"):
            lines += ["", "**CV tweaks**"] + [f"- {t}" for t in note["cv_tweaks"]]
    return "\n".join(lines) + "\n"
