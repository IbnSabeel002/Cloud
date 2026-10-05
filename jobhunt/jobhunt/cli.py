"""Command line entry points. Thin wrappers over pipeline() so the logic stays testable.

    python -m jobhunt prefilter --candidates raw.json --out need.json [--profile p.json] [--db-dir DIR] [--limit 25]
    python -m jobhunt run    --candidates c.json --out DIR [--profile p.json] [--db-dir DIR] [--prefilter need.json] [--today YYYY-MM-DD]
    python -m jobhunt report --out DIR [--analysis a.json] [--health h.json] [--report-url URL] [--tracker-url URL] [--drafts N]
    python -m jobhunt verify --db-dir DIR --hash SHA256
    python -m jobhunt parse-alert --thread thread1.json [thread2.json ...] --out alerts.json
    python -m jobhunt availability --card card.json [--today YYYY-MM-DD]
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

from . import store, tracker
from .normalize import job_id, job_key
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
    skipped_ids: dict[str, list] = {}  # which jobs each count stands for, so `run` can count each job once

    def drop(reason: str, job: str) -> None:
        skipped[reason] += 1
        skipped_ids.setdefault(reason, []).append(job)

    ranked = []
    for c in unique:
        ev = evaluate(c, profile, today)
        if ev.job_id in known:
            drop("already_seen", ev.job_id)
        elif ev.reject_reasons:
            drop(ev.reject_reasons[0], ev.job_id)
        elif "off_target_title" in ev.flags:
            drop("off_target_title", ev.job_id)
        else:
            ranked.append((-ev.components["title"], ev.age_days if ev.age_days is not None else 99, c))
    ranked.sort(key=lambda t: (t[0], t[1]))
    fetch = [c for _, _, c in ranked[:limit]]
    return {
        "fetch": fetch,
        "overflow": max(0, len(ranked) - limit),
        "skipped": {k: v for k, v in skipped.items() if v},
        "skipped_ids": skipped_ids,
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


def _load_existing(args) -> tuple[list, list]:
    """Yesterday's rows: from the Artifact database export (--db-dir) or a tracker CSV (--tracker)."""
    if getattr(args, "db_dir", None):
        if not Path(args.db_dir).exists():
            return [], []  # first run: nothing stored yet
        return store.load_dir(args.db_dir), []
    if args.tracker and Path(args.tracker).exists():
        return tracker.parse_table(Path(args.tracker).read_text(encoding="utf-8"))
    return [], []


def cmd_prefilter(args) -> int:
    today = date.fromisoformat(args.today) if args.today else dubai_today()
    profile = load_profile(args.profile)
    existing, _ = _load_existing(args)
    result = prefilter(profile, _load_candidates(args.candidates), existing, today, args.limit)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "fetch"} | {"fetch": len(result["fetch"])}))
    return 0


def _fold_in_prefilter(summary: dict, need: dict, run_ids: set | None = None) -> None:
    """Jobs the prefilter dropped never reached `run`. Count them so the digest shows the whole funnel.

    A job that `run` evaluated has already been counted by `run`, so it is not counted again here. This
    matters when the candidate file holds every search hit instead of only the ones that were fetched
    (a live test counted 75 screened-out jobs out of 58 hits).
    """
    skipped = need.get("skipped", {})
    skipped_ids = need.get("skipped_ids") or {}
    summary["raw_hits"] = need.get("raw_in", 0)
    for reason, count in skipped.items():
        if run_ids and reason in skipped_ids:
            count = len(set(skipped_ids[reason]) - run_ids)
        if not count:
            continue
        if reason == "already_seen":
            summary["already_seen"] += count
        elif reason in ("duplicate", "invalid"):
            continue  # not jobs the user was ever going to see
        else:
            summary["reject_reasons"][reason] = summary["reject_reasons"].get(reason, 0) + count
            summary["rejected_jobs"] += count


def cmd_run(args) -> int:
    today = date.fromisoformat(args.today) if args.today else dubai_today()
    profile = load_profile(args.profile)
    candidates = _load_candidates(args.candidates)
    existing, warnings = _load_existing(args)
    result = pipeline(profile, candidates, existing, today)
    result.summary["tracker_warnings"] = warnings
    if args.prefilter:
        run_ids = {
            job_id(job_key(c.get("company"), c.get("title"), c.get("location")))
            for c in candidates if isinstance(c, dict)
        }
        _fold_in_prefilter(result.summary, _read_json(args.prefilter), run_ids)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.db_dir:
        manifest = store.plan_writes(existing, result.rows, out)
        result.summary["writes"] = manifest["counts"]
        result.summary["versions_needed"] = manifest["versions_needed"]
    (out / "tracker.csv").write_text(tracker.dump_csv(result.rows), encoding="utf-8")
    (out / "shortlist.json").write_text(json.dumps(result.shortlist, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(result.summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result.summary, ensure_ascii=False))
    return 0


def cmd_parse_alert(args) -> int:
    from .alerts import parse_threads  # only this command needs it

    try:
        jobs, stats = parse_threads([Path(p) for p in args.thread])
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats | {"jobs": len(jobs)}))
    return 0


def cmd_availability(args) -> int:
    from .availability import availability_line  # only this command needs it

    try:
        card = _read_json(args.card)
        today = date.fromisoformat(args.today) if args.today else dubai_today()
        if not isinstance(card, dict):
            raise ValueError("the card must be a JSON object")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(availability_line(card, today) or "")
    return 0


def cmd_report(args) -> int:
    out = Path(args.out)
    summary = _read_json(str(out / "summary.json"))
    shortlist = _read_json(str(out / "shortlist.json"))
    analysis = _read_json(args.analysis) if args.analysis and Path(args.analysis).exists() else {}
    health = _read_json(args.health) if args.health and Path(args.health).exists() else None
    today = date.fromisoformat(summary["today"])
    chunks = digest_chunks(summary, shortlist, health, analysis, args.report_url, today, tracker_url=args.tracker_url,
                           drafts_created=args.drafts)
    for i, chunk in enumerate(chunks, 1):
        (out / f"digest_{i}.txt").write_text(chunk, encoding="utf-8")
    (out / "report.html").write_text(render_report_html(summary, shortlist, health, analysis, today), encoding="utf-8")
    (out / "report.md").write_text(render_report_md(summary, shortlist, health, analysis, today), encoding="utf-8")
    (out / "run_doc.json").write_text(
        json.dumps(store.run_doc(summary, health, args.report_url), ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"digest_files": len(chunks), "report": ["report.html", "report.md"], "run_doc": "run_doc.json"}))
    return 0


def cmd_verify(args) -> int:
    if args.db_dir:
        rows, warnings = store.load_dir(args.db_dir), []
    else:
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
    pre.add_argument("--db-dir", help="folder written by ArtifactData list out_dir (holds jobs/*.json)")
    pre.add_argument("--today", help="YYYY-MM-DD (default: today in Dubai)")
    pre.add_argument("--limit", type=int, default=25)
    pre.set_defaults(func=cmd_prefilter)

    run = sub.add_parser("run", help="screen, score and merge today's candidates")
    run.add_argument("--candidates", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--profile")
    run.add_argument("--tracker")
    run.add_argument("--db-dir", help="folder written by ArtifactData list out_dir (holds jobs/*.json)")
    run.add_argument("--prefilter", help="need.json from the prefilter step, so its skipped jobs are counted")
    run.add_argument("--today", help="YYYY-MM-DD (default: today in Dubai)")
    run.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="render the Slack digest and the full report")
    rep.add_argument("--out", required=True)
    rep.add_argument("--analysis")
    rep.add_argument("--health")
    rep.add_argument("--report-url")
    rep.add_argument("--tracker-url", help="link to the tracker page, shown in the digest")
    rep.add_argument("--drafts", type=int, default=0, help="how many Gmail drafts were really created (default 0)")
    rep.set_defaults(func=cmd_report)

    ver = sub.add_parser("verify", help="check a read-back tracker against the expected hash")
    ver.add_argument("--tracker", help="a tracker CSV or a text read-back of one")
    ver.add_argument("--db-dir", help="folder written by ArtifactData list out_dir (holds jobs/*.json)")
    ver.add_argument("--hash", required=True)
    ver.set_defaults(func=cmd_verify)

    alert = sub.add_parser("parse-alert", help="read saved Gmail job-alert threads into candidate jobs")
    alert.add_argument("--thread", nargs="+", required=True, help="files written by Gmail get_thread")
    alert.add_argument("--out", required=True)
    alert.set_defaults(func=cmd_parse_alert)

    avail = sub.add_parser("availability", help="print the sentence about when the candidate can start, for today")
    avail.add_argument("--card", required=True, help="the merged candidate card (JSON)")
    avail.add_argument("--today")
    avail.set_defaults(func=cmd_availability)

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
