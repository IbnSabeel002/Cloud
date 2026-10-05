"""Command line entry points. Thin wrappers over pipeline() so the logic stays testable.

    python -m jobhunt prefilter --candidates raw.json --out need.json [--profile p.json] [--tracker t.csv] [--limit 25]
    python -m jobhunt run    --candidates c.json --out DIR [--profile p.json] [--tracker t.csv] [--today YYYY-MM-DD]
    python -m jobhunt report --out DIR [--analysis a.json] [--health h.json] [--report-url URL]
    python -m jobhunt verify --tracker readback.txt --hash SHA256
    python -m jobhunt parse-pay "AED 4,000 - 5,000"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import tracker
from .profile import load_profile
from .report import digest_chunks, render_report_html, render_report_md
from .salary import parse_pay
from .score import dedupe_candidates, evaluate, validate_candidate

DESCRIPTION_CAP = 2500  # keep shortlist.json small enough to hand to the model


@dataclass
class PipelineResult:
    rows: list
    shortlist: list
    summary: dict


def dubai_today() -> date:
    return datetime.now(timezone(timedelta(hours=4))).date()


def pipeline(profile: dict, candidates: list, existing_rows: list, today: date) -> PipelineResult:
    valid, invalid = [], []
    for i, c in enumerate(candidates):
        problems = validate_candidate(c)
        if problems:
            invalid.append({"index": i, "problems": problems})
        else:
            valid.append(c)
    unique, in_batch_dups = dedupe_candidates(valid)
    evaluations = [evaluate(c, profile, today) for c in unique]
    rows, stats = tracker.merge(existing_rows, evaluations, today, profile)

    added = set(stats["added_ids"])
    new = sorted((e for e in evaluations if e.job_id in added), key=lambda e: (-e.score, e.title))
    strong = [e for e in new if e.strong][: profile["max_outreach"]]
    shortlist = []
    for e in new:
        d = e.to_dict()
        d["description"] = (d["description"] or "")[:DESCRIPTION_CAP]
        d["outreach"] = e in strong
        shortlist.append(d)

    stop = tracker.stop_reasons(rows)
    summary = {
        "today": today.isoformat(),
        "candidates_in": len(candidates),
        "invalid": invalid,
        "in_batch_duplicates": in_batch_dups,
        "unique": len(unique),
        "already_seen": stats["already_seen"],
        "new_shortlisted": len(new),
        "strong": len(strong),
        "outreach_keys": [e.job_id for e in strong],
        "below_threshold": stats["below_threshold"],
        "rejected_jobs": stats["rejected_jobs"],
        "reject_reasons": dict(stats["reject_reasons"]),
        "auto_dead": stats["auto_dead"],
        "pruned": stats["pruned"],
        "tracker_rows": len(rows),
        "tracker_hash": tracker.content_hash(rows),
        "hunt_day": tracker.hunt_day(rows, today, profile.get("hunt_start")),
        "stop": {"stop": bool(stop), "reasons": stop},
    }
    return PipelineResult(rows, shortlist, summary)


def prefilter(profile: dict, raw: list, existing_rows: list, today: date, limit: int = 25) -> dict:
    """Decide which raw search hits deserve a (costly) job-details fetch.

    Works on search-result metadata only: no description is needed to rule a listing out
    for being stale, junior, in the wrong language, off-target, or already tracked.
    """
    known = {r["Key"] for r in existing_rows}
    unique, in_batch_dups = dedupe_candidates([c for c in raw if not validate_candidate(c)])
    skipped: Counter = Counter()
    skipped["invalid"] = len(raw) - sum(1 for c in raw if not validate_candidate(c))
    skipped["duplicate"] = in_batch_dups
    ranked = []
    for c in unique:
        ev = evaluate(c, profile, today)
        if ev.job_id in known:
            skipped["already_seen"] += 1
        elif ev.reject_reasons:
            skipped[ev.reject_reasons[0]] += 1
        elif "off_target_title" in ev.flags:
            skipped["off_target_title"] += 1
        else:
            ranked.append((-ev.components["title"], ev.age_days if ev.age_days is not None else 99, c))
    ranked.sort(key=lambda t: (t[0], t[1]))
    fetch = [c for _, _, c in ranked[:limit]]
    return {
        "fetch": fetch,
        "overflow": max(0, len(ranked) - limit),
        "skipped": {k: v for k, v in skipped.items() if v},
        "raw_in": len(raw),
    }


def _read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _load_candidates(path: str) -> list:
    data = _read_json(path)
    candidates = data["candidates"] if isinstance(data, dict) and "candidates" in data else data
    if not isinstance(candidates, list):
        raise ValueError("candidates file must be a JSON list (or an object with a 'candidates' list)")
    return candidates


def cmd_prefilter(args) -> int:
    today = date.fromisoformat(args.today) if args.today else dubai_today()
    profile = load_profile(args.profile)
    existing = []
    if args.tracker and Path(args.tracker).exists():
        existing, _ = tracker.parse_table(Path(args.tracker).read_text(encoding="utf-8"))
    result = prefilter(profile, _load_candidates(args.candidates), existing, today, args.limit)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "fetch"} | {"fetch": len(result["fetch"])}))
    return 0


def cmd_run(args) -> int:
    today = date.fromisoformat(args.today) if args.today else dubai_today()
    profile = load_profile(args.profile)
    candidates = _load_candidates(args.candidates)
    existing, warnings = [], []
    if args.tracker and Path(args.tracker).exists():
        existing, warnings = tracker.parse_table(Path(args.tracker).read_text(encoding="utf-8"))
    result = pipeline(profile, candidates, existing, today)
    result.summary["tracker_warnings"] = warnings

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "tracker.csv").write_text(tracker.dump_csv(result.rows), encoding="utf-8")
    (out / "shortlist.json").write_text(json.dumps(result.shortlist, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(result.summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result.summary, ensure_ascii=False))
    return 0


def cmd_report(args) -> int:
    out = Path(args.out)
    summary = _read_json(str(out / "summary.json"))
    shortlist = _read_json(str(out / "shortlist.json"))
    analysis = _read_json(args.analysis) if args.analysis and Path(args.analysis).exists() else {}
    health = _read_json(args.health) if args.health and Path(args.health).exists() else None
    today = date.fromisoformat(summary["today"])
    chunks = digest_chunks(summary, shortlist, health, analysis, args.report_url, today)
    for i, chunk in enumerate(chunks, 1):
        (out / f"digest_{i}.txt").write_text(chunk, encoding="utf-8")
    (out / "report.html").write_text(render_report_html(summary, shortlist, health, analysis, today), encoding="utf-8")
    (out / "report.md").write_text(render_report_md(summary, shortlist, health, analysis, today), encoding="utf-8")
    print(json.dumps({"digest_files": len(chunks), "report": ["report.html", "report.md"]}))
    return 0


def cmd_verify(args) -> int:
    rows, warnings = tracker.parse_table(Path(args.tracker).read_text(encoding="utf-8"))
    actual = tracker.content_hash(rows)
    ok = actual == args.hash
    print(json.dumps({"ok": ok, "rows": len(rows), "expected": args.hash, "actual": actual, "warnings": warnings}))
    return 0 if ok else 1


def cmd_parse_pay(args) -> int:
    pay = parse_pay(args.text)
    print(json.dumps(None if pay is None else {
        "low": pay.low, "high": pay.high, "currency": pay.currency, "period": pay.period,
        "assumptions": list(pay.assumptions),
    }))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobhunt", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("prefilter", help="pick which raw search hits are worth a job-details fetch")
    pre.add_argument("--candidates", required=True)
    pre.add_argument("--out", required=True)
    pre.add_argument("--profile")
    pre.add_argument("--tracker")
    pre.add_argument("--today", help="YYYY-MM-DD (default: today in Dubai)")
    pre.add_argument("--limit", type=int, default=25)
    pre.set_defaults(func=cmd_prefilter)

    run = sub.add_parser("run", help="screen, score and merge today's candidates")
    run.add_argument("--candidates", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--profile")
    run.add_argument("--tracker")
    run.add_argument("--today", help="YYYY-MM-DD (default: today in Dubai)")
    run.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="render the Slack digest and the full report")
    rep.add_argument("--out", required=True)
    rep.add_argument("--analysis")
    rep.add_argument("--health")
    rep.add_argument("--report-url")
    rep.set_defaults(func=cmd_report)

    ver = sub.add_parser("verify", help="check a read-back tracker against the expected hash")
    ver.add_argument("--tracker", required=True)
    ver.add_argument("--hash", required=True)
    ver.set_defaults(func=cmd_verify)

    pay = sub.add_parser("parse-pay", help="debug: show how a pay string is read")
    pay.add_argument("text")
    pay.set_defaults(func=cmd_parse_pay)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
