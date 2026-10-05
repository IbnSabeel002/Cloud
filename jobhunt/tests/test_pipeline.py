"""End-to-end tests on real listings captured 2026-10-05 (see fixtures/)."""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from jobhunt import tracker
from jobhunt.cli import main, pipeline
from jobhunt.profile import load_profile

FIXTURE = Path(__file__).parent / "fixtures" / "candidates_2026-10-05.json"
TODAY = date(2026, 10, 5)


def candidates():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["candidates"]


def by_company(result_rows_or_shortlist, company):
    return [r for r in result_rows_or_shortlist if company.lower() in (r.get("company") or r.get("Company")).lower()]


class GoldenRunTests(unittest.TestCase):
    """Every outcome here was checked by hand against the listing it came from."""

    @classmethod
    def setUpClass(cls):
        cls.result = pipeline(load_profile(), candidates(), [], TODAY)
        cls.s = cls.result.summary

    def test_counts(self):
        s = self.s
        self.assertEqual((s["candidates_in"], s["in_batch_duplicates"], s["unique"]), (19, 2, 17))
        self.assertEqual((s["new_shortlisted"], s["strong"], s["below_threshold"], s["rejected_jobs"]), (5, 3, 3, 9))  # Sokin has no JD: 51 clears the thin bar of 50
        self.assertEqual(s["new_shortlisted"] + s["below_threshold"] + s["rejected_jobs"] + s["already_seen"], s["unique"])

    def test_reject_reason_tallies(self):
        self.assertEqual(self.s["reject_reasons"], {
            "junior_level": 3, "stale": 4, "language:french": 1, "language:chinese": 1,
            "job_type:freelance": 1, "upfront_fee": 1, "whatsapp_only_apply": 1,
        })

    def test_shortlist_is_sorted_best_first(self):
        scores = [e["score"] for e in self.result.shortlist]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual([e["company"] for e in self.result.shortlist][0], "Azya Consulting FZ LLE")

    def test_the_hand_checked_top_pick(self):
        azya = by_company(self.result.shortlist, "azya")
        self.assertEqual(len(azya), 1)
        e = azya[0]
        self.assertEqual(e["components"], {"title": 28, "skills": 25, "seniority": 15, "pay": 20, "freshness": 5, "adjustment": 0})
        self.assertEqual((e["score"], e["tier"], e["pay_display"], e["strong"]), (93, "A", "AED 10,000/mo", True))
        self.assertEqual(len(e["all_urls"]), 2)  # Indeed and Bayt collapsed into one

    def test_the_fresher_listing_that_looks_like_the_target_pay_is_rejected(self):
        # AED 3,500-4,000 labelled Fresher: this is the pay band the user asked for, and it is junior work.
        self.assertEqual(by_company(self.result.shortlist, "creditcare"), [])
        self.assertEqual(by_company(self.result.rows, "creditcare"), [])

    def test_scam_pattern_never_reaches_the_shortlist_even_with_good_pay(self):
        self.assertEqual(by_company(self.result.shortlist, "global reach"), [])

    def test_strong_picks_get_outreach_and_are_capped(self):
        flagged = [e for e in self.result.shortlist if e["outreach"]]
        self.assertEqual(len(flagged), 3)
        self.assertEqual(sorted(self.s["outreach_keys"]), sorted(e["job_id"] for e in flagged))
        profile = load_profile(overrides={"max_outreach": 1})
        capped = pipeline(profile, candidates(), [], TODAY)
        self.assertEqual(len(capped.summary["outreach_keys"]), 1)
        self.assertEqual(capped.summary["outreach_keys"][0], self.result.shortlist[0]["job_id"])

    def test_tracker_rows_match_the_shortlist(self):
        self.assertEqual(len(self.result.rows), 5)
        self.assertEqual({r["Key"] for r in self.result.rows}, {e["job_id"] for e in self.result.shortlist})
        self.assertTrue(all(r["Status"] == "Shortlisted" for r in self.result.rows))

    def test_no_stop_signal_on_day_one(self):
        self.assertEqual(self.s["stop"], {"stop": False, "reasons": []})


class MultiDayTests(unittest.TestCase):
    def test_same_day_rerun_is_a_no_op(self):
        first = pipeline(load_profile(), candidates(), [], TODAY)
        second = pipeline(load_profile(), candidates(), first.rows, TODAY)
        self.assertEqual(second.summary["new_shortlisted"], 0)
        self.assertEqual(second.summary["already_seen"], first.summary["new_shortlisted"])
        self.assertEqual(second.summary["tracker_hash"], first.summary["tracker_hash"])
        self.assertEqual(second.shortlist, [])

    def test_next_day_suppresses_repeats_and_keeps_user_edits(self):
        first = pipeline(load_profile(), candidates(), [], TODAY)
        rows = [dict(r) for r in first.rows]
        rows[0]["Status"] = "Applied"
        rows[0]["Notes"] = "emailed on the 5th"
        applied_key = rows[0]["Key"]
        tomorrow = TODAY + timedelta(days=1)
        second = pipeline(load_profile(), candidates(), rows, tomorrow)
        self.assertEqual(second.summary["new_shortlisted"], 0)
        kept = {r["Key"]: r for r in second.rows}
        self.assertEqual((kept[applied_key]["Status"], kept[applied_key]["Notes"]), ("Applied", "emailed on the 5th"))
        self.assertTrue(all(r["FirstSeen"] == "2026-10-05" for r in second.rows))
        # Seeing the same jobs again writes nothing: the only difference from day one is the user's own edit.
        self.assertEqual(second.summary["tracker_hash"], tracker.content_hash(rows))

    def test_a_genuinely_new_job_appears_the_next_day(self):
        first = pipeline(load_profile(), candidates(), [], TODAY)
        fresh = dict(candidates()[2], title="Creative AI Producer", company="New Studio",
                     posted="Today", url="https://example.com/jobs/new")
        second = pipeline(load_profile(), candidates() + [fresh], first.rows, TODAY + timedelta(days=1))
        self.assertEqual(second.summary["new_shortlisted"], 1)
        self.assertEqual(second.shortlist[0]["company"], "New Studio")

    def test_accepted_row_raises_the_stop_signal(self):
        first = pipeline(load_profile(), candidates(), [], TODAY)
        rows = [dict(r) for r in first.rows]
        rows[0]["Status"] = "accepted"
        second = pipeline(load_profile(), candidates(), tracker.parse_table(tracker.dump_csv(rows))[0], TODAY)
        self.assertTrue(second.summary["stop"]["stop"])
        self.assertEqual(len(second.summary["stop"]["reasons"]), 1)

    def test_invalid_candidates_are_reported_not_fatal(self):
        data = candidates() + [{"title": "No company here"}, "not even an object"]
        result = pipeline(load_profile(), data, [], TODAY)
        self.assertEqual(len(result.summary["invalid"]), 2)
        self.assertEqual(result.summary["new_shortlisted"], 5)

    def test_empty_day_is_valid(self):
        result = pipeline(load_profile(), [], [], TODAY)
        self.assertEqual((result.summary["new_shortlisted"], result.summary["tracker_rows"]), (0, 0))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(a) for a in args])
        self.stdout, self.stderr = out.getvalue(), err.getvalue()
        return code

    def test_run_writes_files_and_second_run_is_idempotent(self):
        out = self.dir / "out"
        self.assertEqual(self.run_cli("run", "--candidates", FIXTURE, "--out", out, "--today", "2026-10-05"), 0)
        for name in ("tracker.csv", "shortlist.json", "summary.json"):
            self.assertTrue((out / name).exists(), name)
        first = json.loads((out / "summary.json").read_text())
        self.assertEqual(first["new_shortlisted"], 5)

        out2 = self.dir / "out2"
        code = self.run_cli("run", "--candidates", FIXTURE, "--out", out2, "--tracker", out / "tracker.csv", "--today", "2026-10-05")
        self.assertEqual(code, 0)
        second = json.loads((out2 / "summary.json").read_text())
        self.assertEqual((second["new_shortlisted"], second["already_seen"]), (0, 5))
        self.assertEqual(second["tracker_hash"], first["tracker_hash"])

    def test_verify_accepts_a_round_trip_and_rejects_a_tampered_copy(self):
        out = self.dir / "out"
        self.run_cli("run", "--candidates", FIXTURE, "--out", out, "--today", "2026-10-05")
        digest = json.loads((out / "summary.json").read_text())["tracker_hash"]
        self.assertEqual(self.run_cli("verify", "--tracker", out / "tracker.csv", "--hash", digest), 0)
        tampered = self.dir / "tampered.csv"
        tampered.write_text((out / "tracker.csv").read_text().replace("Shortlisted", "Applied", 1))
        self.assertEqual(self.run_cli("verify", "--tracker", tampered, "--hash", digest), 1)
        truncated = self.dir / "truncated.csv"
        truncated.write_text("\n".join((out / "tracker.csv").read_text().splitlines()[:-1]) + "\n")
        self.assertEqual(self.run_cli("verify", "--tracker", truncated, "--hash", digest), 1)

    def test_report_writes_digest_and_report(self):
        out = self.dir / "out"
        self.run_cli("run", "--candidates", FIXTURE, "--out", out, "--today", "2026-10-05")
        health = self.dir / "health.json"
        health.write_text(json.dumps([{"source": "Indeed", "ok": True}, {"source": "Bayt", "ok": False, "detail": "timeout"}]))
        self.assertEqual(self.run_cli("report", "--out", out, "--health", health, "--report-url", "https://example.com/doc"), 0)
        digest = (out / "digest_1.txt").read_text()
        self.assertIn("Degraded run", digest)
        self.assertIn("https://example.com/doc", digest)
        self.assertTrue((out / "report.html").read_text().startswith("<html>"))
        self.assertIn("# Job hunt report", (out / "report.md").read_text())

    def test_bad_input_exits_2_with_a_message(self):
        self.assertEqual(self.run_cli("run", "--candidates", self.dir / "missing.json", "--out", self.dir / "o"), 2)
        self.assertIn("error:", self.stderr)
        bad = self.dir / "bad.json"
        bad.write_text("{not json")
        self.assertEqual(self.run_cli("run", "--candidates", bad, "--out", self.dir / "o"), 2)
        self.assertIn("error:", self.stderr)
        notlist = self.dir / "notlist.json"
        notlist.write_text('{"candidates": "nope"}')
        self.assertEqual(self.run_cli("run", "--candidates", notlist, "--out", self.dir / "o"), 2)
        self.assertIn("must be a JSON list", self.stderr)

    def test_parse_pay_command(self):
        self.assertEqual(self.run_cli("parse-pay", "AED 4,000 - 5,000 per month"), 0)
        self.assertEqual(json.loads(self.stdout)["low"], 4000)
        self.assertEqual(self.run_cli("parse-pay", "competitive"), 0)
        self.assertEqual(json.loads(self.stdout), None)

    def test_profile_file_overrides_defaults(self):
        profile = self.dir / "profile.json"
        profile.write_text(json.dumps({"floor": 6000, "tier_b": 7000, "tier_a": 9000}))
        out = self.dir / "out"
        self.run_cli("run", "--candidates", FIXTURE, "--out", out, "--profile", profile, "--today", "2026-10-05")
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(summary["new_shortlisted"], 5)  # 10,000 still clears; unlisted pay is not judged

    def test_invalid_profile_exits_2(self):
        profile = self.dir / "profile.json"
        profile.write_text(json.dumps({"floor": 9000}))
        self.assertEqual(self.run_cli("run", "--candidates", FIXTURE, "--out", self.dir / "o", "--profile", profile), 2)


if __name__ == "__main__":
    unittest.main()


class PrefilterFoldInTests(unittest.TestCase):
    """The prefilter drops most hits before `run` sees them. The digest must still count them."""

    def test_skipped_jobs_join_the_funnel_counts(self):
        from jobhunt.cli import _fold_in_prefilter
        summary = {"already_seen": 1, "rejected_jobs": 2, "reject_reasons": {"stale": 1}}
        need = {"raw_in": 68, "skipped": {"stale": 39, "off_target_title": 16, "already_seen": 3, "duplicate": 26, "invalid": 1}}
        _fold_in_prefilter(summary, need)
        self.assertEqual(summary["reject_reasons"], {"stale": 40, "off_target_title": 16})
        self.assertEqual(summary["rejected_jobs"], 2 + 39 + 16)
        self.assertEqual(summary["already_seen"], 1 + 3)  # a seen job is still a seen job
        self.assertEqual(summary["raw_hits"], 68)  # duplicates and invalid records are not jobs the user would see

    def test_a_job_that_run_evaluated_is_not_counted_again(self):
        # Seen in a live test run: the candidate file held all 58 hits, so every dropped hit was counted
        # twice ("75 screened out" from "58 hits found", "10 already seen" with 6 jobs stored).
        from jobhunt.cli import _fold_in_prefilter
        summary = {"already_seen": 2, "rejected_jobs": 3, "reject_reasons": {"stale": 3}}
        need = {"raw_in": 8, "skipped": {"stale": 3, "already_seen": 2},
                "skipped_ids": {"stale": ["j_a", "j_b", "j_c"], "already_seen": ["j_x", "j_y"]}}
        _fold_in_prefilter(summary, need, run_ids={"j_a", "j_b", "j_c", "j_x", "j_y"})  # run saw all of them
        self.assertEqual(summary["rejected_jobs"], 3)
        self.assertEqual(summary["already_seen"], 2)
        self.assertEqual(summary["reject_reasons"], {"stale": 3})

    def test_only_the_jobs_run_did_not_see_are_added(self):
        from jobhunt.cli import _fold_in_prefilter
        summary = {"already_seen": 0, "rejected_jobs": 1, "reject_reasons": {"stale": 1}}
        need = {"raw_in": 5, "skipped": {"stale": 3}, "skipped_ids": {"stale": ["j_a", "j_b", "j_c"]}}
        _fold_in_prefilter(summary, need, run_ids={"j_a"})  # j_a was counted by run, j_b and j_c were not
        self.assertEqual(summary["rejected_jobs"], 1 + 2)
        self.assertEqual(summary["reject_reasons"], {"stale": 3})

    def test_a_need_file_without_ids_still_folds_by_count(self):
        # Older need.json files carry counts only; they must keep working.
        from jobhunt.cli import _fold_in_prefilter
        summary = {"already_seen": 0, "rejected_jobs": 0, "reject_reasons": {}}
        _fold_in_prefilter(summary, {"raw_in": 4, "skipped": {"stale": 4}}, run_ids={"j_a"})
        self.assertEqual(summary["rejected_jobs"], 4)

    def test_passing_every_hit_to_run_cannot_inflate_the_funnel(self):
        # End to end on the real fixture: prefilter the raw hits, then hand `run` ALL of them anyway.
        from jobhunt.cli import prefilter
        from jobhunt.profile import load_profile
        import copy
        full = json.loads(FIXTURE.read_text(encoding="utf-8"))["candidates"]
        profile = load_profile()
        need = prefilter(profile, copy.deepcopy(full), [], date(2026, 10, 5))
        with tempfile.TemporaryDirectory() as tmp:
            need_path = Path(tmp) / "need.json"
            need_path.write_text(json.dumps(need))
            outs = {}
            for label, candidates in (("everything", full), ("only fetch", need["fetch"])):
                cand_path = Path(tmp) / f"{label}.json"
                cand_path.write_text(json.dumps(candidates))
                out = Path(tmp) / label.replace(" ", "_")
                with contextlib.redirect_stdout(io.StringIO()):
                    main(["run", "--candidates", str(cand_path), "--prefilter", str(need_path), "--out", str(out),
                          "--today", "2026-10-05"])
                outs[label] = json.loads((out / "summary.json").read_text())
        # Every distinct job lands in exactly one bucket: 19 raw hits minus 2 duplicates is 17 jobs.
        distinct_jobs = need["raw_in"] - need["skipped"]["duplicate"]
        for label, s in outs.items():
            seen_jobs = s["already_seen"] + s["rejected_jobs"] + s["below_threshold"] + s["new_shortlisted"]
            self.assertEqual(seen_jobs, distinct_jobs, f"{label}: a job was counted twice or not at all")
        # The shortlist is the same either way.
        self.assertEqual(outs["everything"]["new_shortlisted"], outs["only fetch"]["new_shortlisted"])

    def test_cli_applies_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            need = Path(tmp) / "need.json"
            need.write_text(json.dumps({"raw_in": 10, "skipped": {"stale": 7}}))
            out = Path(tmp) / "o"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["run", "--candidates", str(FIXTURE), "--prefilter", str(need), "--out", str(out), "--today", "2026-10-05"])
            self.assertEqual(code, 0)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["reject_reasons"]["stale"], 4 + 7)
            self.assertEqual(summary["rejected_jobs"], 9 + 7)
