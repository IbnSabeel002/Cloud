import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jobhunt import playbook_gate as gate
from jobhunt.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "candidates_2026-10-05.json"
NOW = 1_800_000_000.0


class SplitTests(unittest.TestCase):
    def test_chunks_rebuild_the_text_exactly_and_respect_the_limit(self):
        text = "".join(f"line {i} " + "x" * (i % 70) + "\n" for i in range(400))
        chunks = gate.split_chunks(text, 1000)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertGreater(len(chunks), 3)

    def test_cuts_fall_on_line_boundaries(self):
        text = "".join(f"row {i}\n" for i in range(500))
        for chunk in gate.split_chunks(text, 400)[:-1]:
            self.assertTrue(chunk.endswith("\n"))

    def test_one_overlong_line_is_cut_by_characters_not_dropped(self):
        chunks = gate.split_chunks("a\n" + "Z" * 2500 + "\nb\n", 1000)
        self.assertEqual("".join(chunks), "a\n" + "Z" * 2500 + "\nb\n")
        self.assertTrue(all(len(c) <= 1000 for c in chunks))

    def test_empty_text(self):
        self.assertEqual(gate.split_chunks(""), [])


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.receipt = Path(self.tmp.name) / "receipt.json"
        self.playbook = Path(self.tmp.name) / "PLAYBOOK.md"
        self.playbook.write_text("".join(f"## {i}. Section {i}\n" + "text line\n" * 400 for i in range(1, 6)), encoding="utf-8")
        patches = [
            mock.patch.dict(os.environ, {gate.RECEIPT_ENV: str(self.receipt)}),
            mock.patch.object(gate, "playbook_path", lambda: self.playbook),
            mock.patch.object(gate, "commit_short", lambda: "abc1234"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(gate.SKIP_ENV, None)  # restored by patch.dict
        self.total = len(gate.split_chunks(self.playbook.read_text()))

    def read_all(self, now=NOW):
        for n in range(1, self.total + 1):
            gate.read_chunk(n, now)

    def test_the_run_clock_starts_when_chunk_one_is_read_and_is_the_scripts_own(self):
        self.assertIsNone(gate.elapsed_minutes(NOW))  # no receipt yet: nothing to trust
        gate.read_chunk(1, NOW)
        self.assertEqual(gate.elapsed_minutes(NOW), 0.0)
        gate.read_chunk(2, NOW + 600)
        gate.read_chunk(3, NOW + 1800)
        self.assertEqual(gate.elapsed_minutes(NOW + 3000), 50.0)  # later chunks do not restart it
        self.assertEqual(gate.elapsed_minutes(NOW - 100), 0.0)    # never negative

    def test_the_largest_elapsed_time_asked_for_is_remembered_for_the_time_limit_check(self):
        self.assertIsNone(gate.limit_seen_minutes())
        self.assertIsNone(gate.note_elapsed(NOW))  # no receipt yet: nothing is remembered
        self.assertIsNone(gate.limit_seen_minutes())
        gate.read_chunk(1, NOW)
        self.assertEqual(gate.note_elapsed(NOW + 300), 5.0)
        self.assertEqual(gate.limit_seen_minutes(), 5.0)
        self.assertEqual(gate.note_elapsed(NOW + 2700), 45.0)
        self.assertEqual(gate.note_elapsed(NOW + 600), 10.0)   # asking again earlier never lowers it
        self.assertEqual(gate.limit_seen_minutes(), 45.0)
        gate.read_chunk(2, NOW + 2800)                          # reading on keeps it
        self.assertEqual(gate.limit_seen_minutes(), 45.0)
        gate.read_chunk(1, NOW + 5000)                          # a new run starts afresh
        self.assertIsNone(gate.limit_seen_minutes())

    def test_reading_chunk_one_again_restarts_the_clock(self):
        gate.read_chunk(1, NOW)
        gate.read_chunk(1, NOW + 3600)
        self.assertEqual(gate.elapsed_minutes(NOW + 3600 + 120), 2.0)

    def test_a_damaged_or_clockless_receipt_gives_no_elapsed_time(self):
        self.receipt.write_text("not json", encoding="utf-8")
        self.assertIsNone(gate.elapsed_minutes(NOW))
        self.receipt.write_text(json.dumps({"sha": "x", "read": [1]}), encoding="utf-8")
        self.assertIsNone(gate.elapsed_minutes(NOW))
        self.receipt.write_text(json.dumps({"started": "yesterday"}), encoding="utf-8")
        self.assertIsNone(gate.elapsed_minutes(NOW))

    def test_there_are_several_chunks(self):
        self.assertGreater(self.total, 2)

    def test_a_chunk_has_a_footer_that_says_where_it_is_and_what_comes_next(self):
        first = gate.read_chunk(1, NOW)
        self.assertIn(f"chunk 1 of {self.total} | playbook @abc1234 sha256:", first)
        self.assertIn("next: --chunk 2", first.splitlines()[-1])
        last = gate.read_chunk(self.total, NOW)
        self.assertTrue(last.endswith(gate.END_MARK))

    def test_an_out_of_range_chunk_is_an_error(self):
        for n in (0, self.total + 1, -3):
            with self.assertRaises(ValueError):
                gate.read_chunk(n, NOW)

    def test_nothing_read_is_not_complete(self):
        ok, line, missing = gate.status(NOW)
        self.assertFalse(ok)
        self.assertEqual(missing, list(range(1, self.total + 1)))
        self.assertIn("PLAYBOOK NOT FULLY READ", line)

    def test_reading_every_chunk_completes_it(self):
        self.read_all()
        ok, line, missing = gate.status(NOW + 60)
        self.assertEqual((ok, missing), (True, []))
        self.assertEqual(line, f"Playbook @abc1234 sha:{gate.sha8(self.playbook.read_text())} read {self.total}/{self.total}")
        self.assertEqual(gate.receipt_line(NOW + 60), line)

    def test_a_skipped_chunk_is_named(self):
        gate.read_chunk(1, NOW)
        gate.read_chunk(3, NOW)
        ok, line, missing = gate.status(NOW)
        self.assertFalse(ok)
        self.assertIn("missing chunks 2", line)
        self.assertEqual(missing[0], 2)
        self.assertNotIn(1, missing)
        self.assertNotIn(3, missing)
        self.assertIsNone(gate.receipt_line(NOW))

    def test_starting_again_from_chunk_one_clears_the_old_reads(self):
        self.read_all()
        gate.read_chunk(1, NOW + 5)
        self.assertFalse(gate.status(NOW + 5)[0])

    def test_a_changed_playbook_invalidates_the_receipt(self):
        self.read_all()
        self.playbook.write_text(self.playbook.read_text() + "## 6. New rule\nDo this now.\n", encoding="utf-8")
        ok, line, _ = gate.status(NOW)
        self.assertFalse(ok)
        self.assertIn("no receipt for this version", line)

    def test_an_old_receipt_expires_after_twelve_hours(self):
        self.read_all()
        self.assertTrue(gate.status(NOW + 12 * 3600 - 1)[0])
        ok, line, _ = gate.status(NOW + 12 * 3600 + 1)
        self.assertFalse(ok)
        self.assertIn("OLD", line)

    def test_a_damaged_receipt_counts_as_unread(self):
        self.receipt.write_text("not json", encoding="utf-8")
        self.assertFalse(gate.status(NOW)[0])
        self.receipt.write_text("[1, 2]", encoding="utf-8")
        self.assertFalse(gate.status(NOW)[0])

    def test_the_gate_blocks_until_everything_is_read_and_names_the_next_chunk(self):
        message = gate.gate(NOW)
        self.assertIn("python3 -m jobhunt playbook --chunk 1", message)
        gate.read_chunk(1, NOW)
        self.assertIn("--chunk 2", gate.gate(NOW))
        self.read_all()
        self.assertIsNone(gate.gate(NOW))

    def test_the_bypass_variable_opens_the_gate(self):
        self.assertIsNotNone(gate.gate(NOW))
        with mock.patch.dict(os.environ, {gate.SKIP_ENV: "1"}):
            self.assertIsNone(gate.gate(NOW))

    def test_section_prints_that_block_only_and_leaves_the_receipt_alone(self):
        block = gate.section(3)
        self.assertTrue(block.startswith("## 3. Section 3"))
        self.assertNotIn("## 4.", block)
        self.assertFalse(self.receipt.exists())
        with self.assertRaises(ValueError):
            gate.section(99)

    def test_the_last_section_runs_to_the_end_of_the_file(self):
        self.assertIn("text line", gate.section(5))


class CliGateTests(unittest.TestCase):
    """The commands that decide things refuse to run until the playbook has been read."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        patch = mock.patch.dict(os.environ, {gate.RECEIPT_ENV: str(self.dir / "receipt.json")})
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop(gate.SKIP_ENV, None)
        self.total = len(gate.split_chunks(gate.playbook_path().read_text(encoding="utf-8")))

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def read_everything(self):
        for n in range(1, self.total + 1):
            code, out, _ = self.cli("playbook", "--chunk", n)
            self.assertEqual(code, 0)

    def test_the_real_playbook_is_served_in_a_handful_of_chunks(self):
        self.assertGreaterEqual(self.total, 3)
        self.assertLessEqual(self.total, 8)
        code, out, _ = self.cli("playbook", "--chunk", 1)
        self.assertEqual(code, 0)
        self.assertIn("# Job-hunt daily run: playbook", out)
        self.assertIn(f"chunk 1 of {self.total}", out)

    def test_every_decision_command_is_blocked_before_the_playbook_is_read(self):
        raw = self.dir / "raw.json"
        raw.write_text("[]")
        for argv in (["prefilter", "--candidates", raw, "--health", self.dir / "health.json", "--out", self.dir / "need.json"],
                     ["run", "--candidates", raw, "--out", self.dir / "out"],
                     ["report", "--out", self.dir / "out"]):
            code, _, err = self.cli(*argv)
            self.assertEqual(code, 2, argv[0])
            self.assertIn("PLAYBOOK NOT FULLY READ", err)
            self.assertIn("playbook --chunk 1", err)
        self.assertFalse((self.dir / "need.json").exists())
        self.assertFalse((self.dir / "out").exists())

    def test_commands_that_only_help_are_never_blocked(self):
        self.assertEqual(self.cli("parse-pay", "AED 5,000")[0], 0)
        self.assertEqual(self.cli("availability", "--card", self.dir / "nope.json")[0], 2)  # its own error, not the gate's

    def test_receipt_exit_codes(self):
        code, out, _ = self.cli("playbook", "--receipt")
        self.assertEqual(code, 1)
        self.assertIn("NOT FULLY READ", out)
        self.read_everything()
        code, out, _ = self.cli("playbook", "--receipt")
        self.assertEqual(code, 0)
        self.assertRegex(out.strip(), rf"^Playbook @\S+ sha:[0-9a-f]{{8}} read {self.total}/{self.total}$")

    def test_after_the_full_read_the_pipeline_works_and_the_digest_names_the_playbook(self):
        self.read_everything()
        out_dir = self.dir / "out"
        code, _, err = self.cli("run", "--candidates", FIXTURE, "--out", out_dir, "--today", "2026-10-05")
        self.assertEqual(code, 0, err)
        health = self.dir / "health.json"
        health.write_text(json.dumps([{"source": "Settings", "ok": True}, {"source": "Tracker write", "ok": True}]))
        code, _, err = self.cli("report", "--out", out_dir, "--health", health)
        self.assertEqual(code, 0, err)
        digest = (out_dir / "digest_1.txt").read_text()
        self.assertRegex(digest, r"Playbook @\S+ sha:[0-9a-f]{8} read \d+/\d+")
        run_doc = json.loads((out_dir / "run_doc.json").read_text())
        self.assertRegex(run_doc["Playbook"], r"^Playbook @")

    def test_a_partial_read_still_blocks(self):
        self.cli("playbook", "--chunk", 1)
        code, _, err = self.cli("run", "--candidates", FIXTURE, "--out", self.dir / "out")
        self.assertEqual(code, 2)
        self.assertIn("missing chunks 2", err)

    def test_the_bypass_variable_lets_a_test_run_without_reading(self):
        with mock.patch.dict(os.environ, {gate.SKIP_ENV: "1"}):
            code, _, _ = self.cli("run", "--candidates", FIXTURE, "--out", self.dir / "out2", "--today", "2026-10-05")
        self.assertEqual(code, 0)
        digest_code, _, _ = self.cli("report", "--out", self.dir / "out2")  # gate is back on: blocked
        self.assertEqual(digest_code, 2)

    def test_a_bad_chunk_number_exits_2(self):
        code, _, err = self.cli("playbook", "--chunk", 999)
        self.assertEqual(code, 2)
        self.assertIn("error", err)
        code, _, err = self.cli("playbook", "--section", 99)
        self.assertEqual(code, 2)

    def test_section_reprints_a_block_of_the_real_playbook(self):
        code, out, _ = self.cli("playbook", "--section", 9)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("## 9. Notify"))
        self.assertNotIn("## 10.", out)


if __name__ == "__main__":
    unittest.main()
