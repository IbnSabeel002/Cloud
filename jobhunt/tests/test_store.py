import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from jobhunt import store, tracker
from jobhunt.cli import main, pipeline
from jobhunt.profile import load_profile

from .support import write_health
from .test_tracker import TODAY, ev, row

FIXTURES = Path(__file__).parent / "fixtures"
DB = FIXTURES / "db"
# Hash computed BEFORE these five jobs were written to the live Artifact database on 2026-10-05.
HASH_BEFORE_WRITE = "699bf2d858692f3c80e43932d2faf81cc11e9ebc0e7acaa07d9a2d0b1bbf6fde"


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)


class LoadDirTests(TempDirCase):
    """The fixture holds the documents exactly as `ArtifactData list ... out_dir` saved them from the live database."""

    def test_live_round_trip_is_exact(self):
        rows = store.load_dir(DB)
        self.assertEqual(len(rows), 5)
        self.assertEqual(tracker.content_hash(rows), HASH_BEFORE_WRITE)

    def test_nothing_is_truncated_or_escaped(self):
        rows = {r["Key"]: r for r in store.load_dir(DB)}  # Drive's read-back cut URLs to "..." and escaped "_" and "|"
        wodoh = rows["j_61c519ef63"]
        self.assertEqual(wodoh["Title"], "Generative AI Software Engineer & Digital Marketing Specialist | AI Automation")
        self.assertEqual(wodoh["URL"], "https://to.indeed.com/aadjjgskypmg")
        self.assertEqual(rows["j_217e1063d1"]["Pay"], "AED 8,000–11,000/mo")
        self.assertEqual(wodoh["Flags"], "pay_unlisted;visa_not_stated;engineering_role")

    def test_accepts_the_folder_or_its_parent(self):
        self.assertEqual(len(store.load_dir(DB / "jobs")), 5)

    def test_tolerates_an_envelope_and_missing_fields(self):
        folder = self.dir / "jobs"
        folder.mkdir()
        (folder / "j_a.json").write_text(json.dumps({"id": "j_a", "version": 3, "data": {"Title": "T", "Status": "applied", "Score": 80}}))
        (folder / "junk.json").write_text(json.dumps(["not", "an", "object"]))
        rows = store.load_dir(self.dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["Key"], rows[0]["Status"], rows[0]["Score"], rows[0]["Company"]), ("j_a", "Applied", "80", ""))

    def test_an_empty_or_missing_collection_is_no_rows(self):
        self.assertEqual(store.load_dir(self.dir), [])


class PlanWritesTests(TempDirCase):
    def plan(self, before, after):
        return store.plan_writes(before, after, self.dir)

    def test_new_rows_are_created_without_a_version(self):
        manifest = self.plan([], [row(Key="j_a", Score="90"), row(Key="j_b", Score="70")])
        entries = manifest["batches"][0]
        self.assertEqual([(e["op"], e["doc_id"]) for e in entries], [("set", "j_a"), ("set", "j_b")])
        self.assertTrue(all("if_version" not in e for e in entries))
        self.assertEqual(manifest["counts"], {"set": 2, "update": 0, "delete": 0})
        self.assertEqual(manifest["versions_needed"], [])
        doc = json.loads(Path(entries[0]["file_path"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["Score"], 90)  # a number, so the page can sort on it
        self.assertEqual(doc["Key"], "j_a")

    def test_nothing_changed_means_nothing_to_write(self):
        rows = [row(Key="j_a"), row(Key="j_b")]
        manifest = self.plan(rows, [dict(r) for r in rows])
        self.assertEqual((manifest["batches"], manifest["versions_needed"]), ([], []))

    def test_a_change_writes_only_the_changed_fields_and_asks_for_a_version(self):
        before = [row(Key="j_a", Score="60", Notes="keep me", Status="Applied")]
        after = [row(Key="j_a", Score="75", Notes="keep me", Status="Applied", Pay="AED 9,000/mo")]
        manifest = self.plan(before, after)
        (entry,) = manifest["batches"][0]
        self.assertEqual((entry["op"], entry["doc_id"], entry["if_version"]), ("update", "j_a", None))
        self.assertEqual(manifest["versions_needed"], ["j_a"])
        patch = json.loads(Path(entry["file_path"]).read_text(encoding="utf-8"))
        self.assertEqual(patch, {"Score": 75, "Pay": "AED 9,000/mo"})  # never overwrites Notes or Status

    def test_a_removed_row_is_a_delete_that_needs_a_version(self):
        manifest = self.plan([row(Key="j_a"), row(Key="j_b")], [row(Key="j_b")])
        (entry,) = manifest["batches"][0]
        self.assertEqual((entry["op"], entry["doc_id"], entry["if_version"]), ("delete", "j_a", None))
        self.assertNotIn("file_path", entry)
        self.assertEqual(manifest["versions_needed"], ["j_a"])

    def test_batches_respect_the_database_limit_of_50(self):
        manifest = self.plan([], [row(Key=f"j_{i:03d}") for i in range(120)])
        self.assertEqual([len(b) for b in manifest["batches"]], [50, 50, 20])
        ids = [e["doc_id"] for b in manifest["batches"] for e in b]
        self.assertEqual(len(ids), len(set(ids)))  # each document at most once per batch

    def test_unicode_survives_in_the_written_file(self):
        manifest = self.plan([], [row(Key="j_a", Pay="AED 8,000–11,000/mo", Title="Lead — AI Specialist")])
        doc = json.loads(Path(manifest["batches"][0][0]["file_path"]).read_text(encoding="utf-8"))
        self.assertEqual((doc["Pay"], doc["Title"]), ("AED 8,000–11,000/mo", "Lead — AI Specialist"))

    def test_the_manifest_is_saved_for_the_agent(self):
        self.plan([], [row(Key="j_a")])
        saved = json.loads((self.dir / "writes.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["counts"]["set"], 1)

    def test_a_users_edit_in_the_database_is_not_overwritten_by_the_next_run(self):
        # End to end: yesterday's rows from the database include the user's Applied + note.
        e = ev()
        day1, _ = tracker.merge([], [e], TODAY, load_profile())
        stored = [dict(r) for r in day1]
        stored[0]["Status"], stored[0]["Notes"] = "Applied", "sent CV"
        merged, _ = tracker.merge(stored, [e], TODAY, load_profile())
        manifest = self.plan(stored, merged)
        self.assertEqual(manifest["batches"], [])  # the agent writes nothing, so the edit cannot be clobbered


class RunDocTests(unittest.TestCase):
    def test_fields_the_page_reads(self):
        summary = {"today": "2026-10-05", "hunt_day": 1, "new_shortlisted": 4, "already_seen": 2, "below_threshold": 10, "rejected_jobs": 7}
        doc = store.run_doc(summary, [{"source": "Indeed", "ok": True}], "https://example.com/r")
        self.assertEqual(doc, {"Date": "2026-10-05", "HuntDay": 1, "NewShortlisted": 4, "AlreadySeen": 2, "BelowThreshold": 10,
                               "Screened": 7, "Health": [{"source": "Indeed", "ok": True}], "ReportUrl": "https://example.com/r"})
        self.assertEqual(store.run_doc(summary, None, None)["Health"], [])
        self.assertEqual(store.run_doc(summary, None, None)["ReportUrl"], "")


class CliDatabaseTests(TempDirCase):
    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(a) for a in args])
        self.stdout, self.stderr = out.getvalue(), err.getvalue()
        return code

    def candidates_file(self):
        path = self.dir / "c.json"
        shutil.copy(FIXTURES / "candidates_2026-10-05.json", path)
        return path

    def test_first_run_with_no_database_folder_yet(self):
        code = self.cli("run", "--candidates", self.candidates_file(), "--db-dir", self.dir / "does-not-exist", "--out", self.dir / "o", "--today", "2026-10-05")
        self.assertEqual(code, 0)
        summary = json.loads((self.dir / "o" / "summary.json").read_text())
        self.assertEqual(summary["writes"], {"set": 5, "update": 0, "delete": 0})
        manifest = json.loads((self.dir / "o" / "writes.json").read_text())
        self.assertEqual(sum(len(b) for b in manifest["batches"]), 5)

    def test_jobs_already_in_the_database_are_not_created_again(self):
        # Two of the fixture's jobs are the same two jobs stored in the live-database fixture.
        code = self.cli("run", "--candidates", self.candidates_file(), "--db-dir", DB, "--out", self.dir / "o", "--today", "2026-10-05")
        self.assertEqual(code, 0)
        summary = json.loads((self.dir / "o" / "summary.json").read_text())
        manifest = json.loads((self.dir / "o" / "writes.json").read_text())
        created = {e["doc_id"] for b in manifest["batches"] for e in b if e["op"] == "set"}
        self.assertTrue({"j_9c7980927f", "j_217e1063d1"}.isdisjoint(created), created)
        self.assertGreaterEqual(summary["already_seen"], 2)

    def test_verify_against_the_database_export(self):
        self.assertEqual(self.cli("verify", "--db-dir", DB, "--hash", HASH_BEFORE_WRITE), 0)
        self.assertTrue(json.loads(self.stdout)["ok"])
        self.assertEqual(self.cli("verify", "--db-dir", DB, "--hash", "0" * 64), 1)
        self.assertFalse(json.loads(self.stdout)["ok"])

    def test_verify_detects_a_missing_document(self):
        partial = self.dir / "partial"
        shutil.copytree(DB, partial)
        (partial / "jobs" / "j_a5a999ae09.json").unlink()
        self.assertEqual(self.cli("verify", "--db-dir", partial, "--hash", HASH_BEFORE_WRITE), 1)

    def test_prefilter_skips_what_the_database_already_holds(self):
        raw = self.dir / "raw.json"
        raw.write_text(json.dumps([
            {"title": "AI Influencer Marketer", "company": "Trade Quo Global Ltd", "location": "Dubai", "posted": "Posted on: September 27, 2026", "url": "https://x"},
            {"title": "Creative AI Producer", "company": "New Studio", "location": "Dubai", "posted": "Posted on: October 03, 2026", "url": "https://y"},
        ]))
        self.assertEqual(self.cli("prefilter", "--candidates", raw, "--health", write_health(self.dir / "health.json"), "--db-dir", DB,
                                  "--out", self.dir / "need.json", "--today", "2026-10-05"), 0)
        need = json.loads((self.dir / "need.json").read_text())
        self.assertEqual([c["company"] for c in need["fetch"]], ["New Studio"])
        self.assertEqual(need["skipped"]["already_seen"], 1)

    def test_report_writes_the_run_document_for_the_page(self):
        out = self.dir / "o"
        self.cli("run", "--candidates", self.candidates_file(), "--out", out, "--today", "2026-10-05")
        self.assertEqual(self.cli("report", "--out", out, "--report-url", "https://docs.example.com/d"), 0)
        doc = json.loads((out / "run_doc.json").read_text())
        self.assertEqual((doc["Date"], doc["NewShortlisted"], doc["ReportUrl"]), ("2026-10-05", 5, "https://docs.example.com/d"))


if __name__ == "__main__":
    unittest.main()
