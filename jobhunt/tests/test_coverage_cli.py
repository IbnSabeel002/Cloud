"""The commands that put the coverage rules to work: prefilter refuses an incomplete run, run counts what came back,
report says what was missed, and `elapsed` is the only clock a time-limit excuse may rely on."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jobhunt import coverage, playbook_gate
from jobhunt.cli import main

from .support import complete_health, write_health

FIXTURE = Path(__file__).parent / "fixtures" / "candidates_2026-10-05.json"


def replace_row(health, name, new):
    return [dict(new) if row["source"] == name else row for row in health]


def hit(n, source="indeed", **extra):
    return {"title": f"Creative AI Specialist {n}", "company": f"Studio {n}", "location": "Dubai",
            "posted": "Posted on: October 03, 2026", "url": f"https://x.example/{n}", "source": source, **extra}


class CliCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        patch = mock.patch.dict(os.environ, {playbook_gate.RECEIPT_ENV: str(self.dir / "receipt.json")})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def raw(self, entries):
        path = self.dir / "raw.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path

    def prefilter(self, entries, health, *extra):
        return self.cli("prefilter", "--candidates", self.raw(entries), "--health", write_health(self.dir / "health.json", health),
                        "--out", self.dir / "need.json", "--today", "2026-10-05", *extra)


class PrefilterGateTests(CliCase):
    def test_a_complete_health_file_lets_the_prefilter_run_and_the_counts_by_source_are_kept(self):
        code, out, _ = self.prefilter([hit(1), hit(2), hit(3, "bayt"), hit(4, "indeed_page")], complete_health())
        self.assertEqual(code, 0)
        need = json.loads((self.dir / "need.json").read_text())
        self.assertEqual(need["raw_by_source"], {"indeed": 2, "bayt": 1, "indeed_page": 1})
        self.assertEqual(json.loads(out)["raw_by_source"], need["raw_by_source"])

    def test_the_run_of_2026_10_07_is_stopped_before_it_can_go_on(self):
        thin = [row for row in complete_health() if row["source"] in ("Settings", "Indeed connector", "Tiny Fish pages", "Gmail alerts")]
        thin = replace_row(thin, "Indeed connector", {"source": "Indeed connector", "ok": True, "hits_seen": 94, "detail": "10 searches"})
        code, _, err = self.prefilter([hit(n) for n in range(27)], thin)
        self.assertEqual(code, 2)
        for name in ("Bayt pages", "GulfTalent", "Naukrigulf", "Other alerts"):
            self.assertIn(name, err)
        self.assertIn("only 27 of the 94 results that came back were written down", err)
        self.assertFalse((self.dir / "need.json").exists())

    def test_a_refusal_removes_the_need_file_from_an_earlier_attempt(self):
        (self.dir / "need.json").write_text('{"fetch": []}')
        code, _, _ = self.prefilter([hit(1)], [])
        self.assertEqual(code, 2)
        self.assertFalse((self.dir / "need.json").exists())

    def test_a_missing_health_file_is_an_error_not_a_pass(self):
        code, _, err = self.cli("prefilter", "--candidates", self.raw([hit(1)]), "--health", self.dir / "nope.json",
                                "--out", self.dir / "need.json")
        self.assertEqual(code, 2)
        self.assertIn("write one health row for every source first", err)

    def test_the_health_option_cannot_be_left_out(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["prefilter", "--candidates", str(self.raw([])), "--out", str(self.dir / "need.json")])

    def test_typing_every_indeed_result_passes(self):
        health = replace_row(complete_health(), "Indeed connector",
                             {"source": "Indeed connector", "ok": True, "hits_seen": 40, "detail": "10 searches"})
        code, _, err = self.prefilter([hit(n) for n in range(40)], health)
        self.assertEqual((code, err), (0, ""))

    def test_an_unknown_source_label_is_refused_so_nothing_is_counted_nowhere(self):
        code, _, err = self.prefilter([hit(1, "indeed_ae"), hit(2)], complete_health())
        self.assertEqual(code, 2)
        self.assertIn("indeed_ae x1", err)

    def test_a_time_limit_excuse_needs_the_scripts_own_clock(self):
        health = replace_row(complete_health(), "GulfTalent",
                             {"source": "GulfTalent", "ok": False, "reason": "time_limit", "detail": "past 40 minutes"})
        code, _, err = self.prefilter([hit(1)], health)
        self.assertEqual(code, 2)
        self.assertIn("`elapsed` command was never run", err)
        # a run that really took 41 minutes: chunk 1 was read 41 minutes ago and `elapsed` was asked
        playbook_gate.read_chunk(1, now=1_000_000.0)
        self.assertEqual(self.cli("elapsed")[0], 0)  # real clock: far past the fake start, so the largest value is huge
        code, _, err = self.prefilter([hit(1)], health)
        self.assertEqual((code, err), (0, ""))

    def test_a_time_limit_excuse_after_only_a_few_minutes_is_refused(self):
        health = replace_row(complete_health(), "GulfTalent",
                             {"source": "GulfTalent", "ok": False, "reason": "time_limit", "detail": "past 40 minutes"})
        with mock.patch("time.time", return_value=1_000_000.0 + 3 * 60):
            playbook_gate.read_chunk(1, now=1_000_000.0)
            self.assertEqual(self.cli("elapsed")[1].strip(), "elapsed 3 of 40 minutes")
        code, _, err = self.prefilter([hit(1)], health)
        self.assertEqual(code, 2)
        self.assertIn("only 3 of 40 minutes had passed", err)


class ElapsedCommandTests(CliCase):
    def test_it_prints_the_minutes_and_remembers_the_largest(self):
        playbook_gate.read_chunk(1, now=1_000_000.0)
        for now, words in ((1_000_000.0 + 125, "elapsed 2 of 40 minutes"), (1_000_000.0 + 61 * 60, "elapsed 61 of 40 minutes"),
                           (1_000_000.0 + 10 * 60, "elapsed 10 of 40 minutes")):
            with mock.patch("time.time", return_value=now):
                self.assertEqual(self.cli("elapsed")[1].strip(), words)
        self.assertEqual(playbook_gate.limit_seen_minutes(), 61.0)

    def test_without_a_gate_start_it_says_it_does_not_know(self):
        code, out, err = self.cli("elapsed")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("elapsed unknown", err)
        self.assertIsNone(playbook_gate.limit_seen_minutes())

    def test_reading_chunk_one_again_starts_the_clock_and_the_memory_afresh(self):
        playbook_gate.read_chunk(1, now=1_000_000.0)
        with mock.patch("time.time", return_value=1_000_000.0 + 50 * 60):
            self.cli("elapsed")
        playbook_gate.read_chunk(1, now=1_000_000.0 + 51 * 60)
        self.assertIsNone(playbook_gate.limit_seen_minutes())


class RunCoverageTests(CliCase):
    def run_it(self, picked, candidates, *, need_extra=None, use_prefilter=True):
        need = {"fetch": picked, "overflow": 0, "skipped": {}, "skipped_ids": {}, "unparsed_alert_entries": 0,
                "raw_in": len(picked), "raw_by_source": {"indeed": len(picked)}, **(need_extra or {})}
        (self.dir / "need.json").write_text(json.dumps(need), encoding="utf-8")
        cand = self.dir / "candidates.json"
        cand.write_text(json.dumps(candidates), encoding="utf-8")
        extra = ["--prefilter", self.dir / "need.json"] if use_prefilter else []
        self.assertEqual(self.cli("run", "--candidates", cand, "--out", self.dir / "out", "--today", "2026-10-05", *extra)[0], 0)
        return json.loads((self.dir / "out" / "summary.json").read_text())

    def test_every_picked_job_coming_back_is_counted_as_finished(self):
        picked = [hit(n) for n in range(5)]
        summary = self.run_it(picked, picked)
        self.assertEqual((summary["picked"], summary["finished"]), (5, 5))
        self.assertEqual(summary["raw_by_source"], {"indeed": 5})
        self.assertNotIn("coverage_unknown", summary)

    def test_jobs_picked_but_never_finished_are_counted(self):
        picked = [hit(n) for n in range(5)]
        summary = self.run_it(picked, picked[:2])
        self.assertEqual((summary["picked"], summary["finished"]), (5, 2))

    def test_a_job_that_came_back_twice_is_counted_once(self):
        picked = [hit(1), hit(2)]
        summary = self.run_it(picked, picked + [hit(1)])
        self.assertEqual((summary["picked"], summary["finished"]), (2, 2))

    def test_entries_beyond_the_limit_are_reported_as_overflow(self):
        self.assertEqual(self.run_it([hit(1)], [hit(1)], need_extra={"overflow": 12})["overflow"], 12)

    def test_running_without_the_prefilter_result_is_flagged_as_coverage_unknown(self):
        summary = self.run_it([hit(1)], [hit(1)], use_prefilter=False)
        self.assertTrue(summary["coverage_unknown"])
        self.assertNotIn("picked", summary)

    def test_the_report_and_the_run_record_carry_the_warnings(self):
        picked = [hit(n) for n in range(5)]
        self.run_it(picked, picked[:3])
        health = complete_health()
        health.append({"source": "Tracker write", "ok": True, "detail": "test"})
        health_path = write_health(self.dir / "health.json", health)
        self.assertEqual(self.cli("report", "--out", self.dir / "out", "--health", health_path)[0], 0)
        doc = json.loads((self.dir / "out" / "run_doc.json").read_text())
        self.assertTrue(doc["Degraded"])
        self.assertIn("⚠️ 2 of 5 jobs picked for a closer look did not come back finished.", doc["Warnings"])
        self.assertEqual(doc["RawBySource"], {"indeed": 5})
        digest = (self.dir / "out" / "digest_1.txt").read_text(encoding="utf-8")
        self.assertIn("did not come back finished", digest)
        self.assertIn("Degraded run", digest)
        for name in ("report.html", "report.md"):
            self.assertIn("did not come back finished", (self.dir / "out" / name).read_text(encoding="utf-8"))

    def test_a_clean_run_has_no_warnings_in_its_record(self):
        picked = [hit(n) for n in range(3)]
        self.run_it(picked, picked)
        health = replace_row(complete_health(), "Indeed connector", {"source": "Indeed connector", "ok": True, "hits_seen": 3})
        health.append({"source": "Tracker write", "ok": True})
        self.assertEqual(self.cli("report", "--out", self.dir / "out", "--health", write_health(self.dir / "health.json", health))[0], 0)
        doc = json.loads((self.dir / "out" / "run_doc.json").read_text())
        self.assertFalse(doc["Degraded"])
        self.assertNotIn("Warnings", doc)


class NamesStayInStepTests(unittest.TestCase):
    def test_the_prefilter_needs_every_required_row_except_the_tracker_write(self):
        self.assertEqual({row["source"] for row in complete_health()}, set(coverage.BEFORE_PREFILTER))


if __name__ == "__main__":
    unittest.main()
