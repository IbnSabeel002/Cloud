import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from jobhunt.cli import main, pipeline, prefilter
from jobhunt.profile import load_profile

from .support import write_health

FIXTURE = Path(__file__).parent / "fixtures" / "candidates_2026-10-05.json"
TODAY = date(2026, 10, 5)
SEARCH_KEYS = ("source", "source_id", "title", "company", "location", "url", "posted")


def raw_search_hits():
    """What a search result gives you before any job page is opened: no description, no pay."""
    full = json.loads(FIXTURE.read_text(encoding="utf-8"))["candidates"]
    return [{k: c[k] for k in SEARCH_KEYS if k in c} | {"level_label": c.get("level_label"),
            "languages_required": c.get("languages_required", []), "job_type": c.get("job_type")} for c in full]


class PrefilterTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile()
        self.result = prefilter(self.profile, raw_search_hits(), [], TODAY)

    def titles(self, result=None):
        return [c["title"] for c in (result or self.result)["fetch"]]

    def test_only_plausible_listings_are_fetched(self):
        titles = self.titles()
        self.assertEqual(sorted(titles), sorted([
            "Lead Graphic, Motion Graphics & AI Video Specialist",
            "AI Influencer Marketer",
            "Social Media and Marketing Manager",
            "Social Media Marketing Manager",
            "Senior Social Media Manager (Global) - Dubai",
            "Marketing Manager - Brokerage & Group Support",
            # The invented scam post must still be fetched: nothing on a search result
            # reveals the WhatsApp-only apply or the fee. Only the job page does.
            "Social Media Manager",
        ]))

    def test_skip_reasons_are_counted(self):
        skipped = self.result["skipped"]
        self.assertEqual(skipped["duplicate"], 2)
        self.assertEqual(skipped["stale"], 4)
        self.assertEqual(skipped["junior_level"], 3)
        self.assertEqual(skipped["off_target_title"], 2)
        self.assertEqual(self.result["raw_in"], 19)

    def test_best_title_matches_come_first(self):
        self.assertEqual(self.titles()[:2], ["Lead Graphic, Motion Graphics & AI Video Specialist", "AI Influencer Marketer"])

    def test_limit_and_overflow(self):
        result = prefilter(self.profile, raw_search_hits(), [], TODAY, limit=2)
        self.assertEqual(len(result["fetch"]), 2)
        self.assertEqual(result["overflow"], 5)  # 7 plausible listings, 2 fetched

    def test_already_tracked_jobs_are_not_fetched_again(self):
        full = json.loads(FIXTURE.read_text(encoding="utf-8"))["candidates"]
        first = pipeline(self.profile, full, [], TODAY)
        again = prefilter(self.profile, raw_search_hits(), first.rows, TODAY)
        self.assertEqual(again["skipped"]["already_seen"], 5)
        self.assertNotIn("AI Influencer Marketer", self.titles(again))
        self.assertNotIn("Lead Graphic, Motion Graphics & AI Video Specialist", self.titles(again))

    def test_every_skipped_job_is_listed_by_id_so_it_is_counted_once(self):
        ids = self.result["skipped_ids"]
        for reason in ("stale", "junior_level", "off_target_title"):
            self.assertEqual(len(ids[reason]), self.result["skipped"][reason], reason)
        flat = [i for group in ids.values() for i in group]
        self.assertEqual(len(flat), len(set(flat)), "a job must be dropped for one reason only")
        self.assertTrue(all(i.startswith("j_") for i in flat))
        # duplicates and invalid records are not jobs, so they have no ids
        self.assertNotIn("duplicate", ids)
        self.assertNotIn("invalid", ids)

    def test_invalid_entries_are_counted_not_fatal(self):
        result = prefilter(self.profile, raw_search_hits() + [{"title": "no company"}], [], TODAY)
        self.assertEqual(result["skipped"]["invalid"], 1)

    def test_does_not_mutate_input(self):
        raw = raw_search_hits()
        import copy
        before = copy.deepcopy(raw)
        prefilter(self.profile, raw, [], TODAY)
        self.assertEqual(raw, before)

    def test_empty_input(self):
        result = prefilter(self.profile, [], [], TODAY)
        self.assertEqual((result["fetch"], result["overflow"], result["skipped"]), ([], 0, {}))


class PrefilterCliTests(unittest.TestCase):
    def test_cli_writes_the_fetch_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.json"
            raw.write_text(json.dumps(raw_search_hits()))
            out = Path(tmp) / "sub" / "need.json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["prefilter", "--candidates", str(raw), "--health", str(write_health(Path(tmp) / "health.json")),
                             "--out", str(out), "--today", "2026-10-05", "--limit", "3"])
            self.assertEqual(code, 0)
            written = json.loads(out.read_text())
            self.assertEqual(len(written["fetch"]), 3)
            printed = json.loads(buf.getvalue())
            self.assertEqual(printed["fetch"], 3)  # the CLI prints counts, not the whole list


if __name__ == "__main__":
    unittest.main()
