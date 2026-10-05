import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from jobhunt.availability import availability_line
from jobhunt.cli import main

ENDS = {"notice_ends_by": "2026-10-09"}  # a Friday


class AvailabilityLineTests(unittest.TestCase):
    def test_before_the_end_date_it_names_the_day(self):
        self.assertEqual(availability_line(ENDS, date(2026, 10, 5)), "My notice period ends by Friday 9 October.")
        self.assertEqual(availability_line(ENDS, date(2026, 10, 8)), "My notice period ends by Friday 9 October.")

    def test_no_zero_padding_on_the_day(self):
        self.assertEqual(availability_line({"notice_ends_by": "2026-11-03"}, date(2026, 10, 5)),
                         "My notice period ends by Tuesday 3 November.")

    def test_on_the_day_it_says_today(self):
        self.assertEqual(availability_line(ENDS, date(2026, 10, 9)), "My notice period ends today.")

    def test_after_the_end_date_the_old_wording_is_gone(self):
        # The point of the script: "ends this week" must not survive into next week.
        line = availability_line(ENDS, date(2026, 10, 12))
        self.assertEqual(line, "My notice period has ended, so I am available to join immediately.")
        self.assertNotIn("ends by", line)

    def test_the_date_wins_over_the_free_text(self):
        card = {"notice_ends_by": "2026-10-09", "availability": "Notice period ends this week."}
        self.assertEqual(availability_line(card, date(2026, 10, 20)),
                         "My notice period has ended, so I am available to join immediately.")

    def test_without_a_date_the_free_text_is_used_as_written(self):
        self.assertEqual(availability_line({"availability": "  Available from 1 November.  "}, date(2026, 10, 5)),
                         "Available from 1 November.")

    def test_an_unreadable_date_is_ignored_not_guessed(self):
        card = {"notice_ends_by": "end of next week", "availability": "Serving notice."}
        self.assertEqual(availability_line(card, date(2026, 10, 5)), "Serving notice.")
        self.assertIsNone(availability_line({"notice_ends_by": "soon"}, date(2026, 10, 5)))

    def test_nothing_known_gives_none(self):
        self.assertIsNone(availability_line({}, date(2026, 10, 5)))
        self.assertIsNone(availability_line({"availability": "  ", "notice_ends_by": None}, date(2026, 10, 5)))


class AvailabilityCliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def card(self, tmp, data):
        path = Path(tmp) / f"card{len(list(Path(tmp).iterdir()))}.json"  # a new file each time
        path.write_text(json.dumps(data) if not isinstance(data, str) else data)
        return str(path)

    def test_prints_the_line_for_the_given_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_cli("availability", "--card", self.card(tmp, ENDS), "--today", "2026-10-05")
            self.assertEqual((code, out.strip()), (0, "My notice period ends by Friday 9 October."))
            code, out, _ = self.run_cli("availability", "--card", self.card(tmp, ENDS), "--today", "2026-10-10")
            self.assertEqual(out.strip(), "My notice period has ended, so I am available to join immediately.")

    def test_prints_an_empty_line_when_nothing_is_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_cli("availability", "--card", self.card(tmp, {}), "--today", "2026-10-05")
            self.assertEqual((code, out), (0, "\n"))

    def test_a_bad_card_or_date_exits_2_with_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            for argv in (["--card", "/no/such/card.json"], ["--card", self.card(tmp, "not json")],
                         ["--card", self.card(tmp, [1, 2])], ["--card", self.card(tmp, {}), "--today", "yesterday"]):
                code, _, err = self.run_cli("availability", *argv)
                self.assertEqual(code, 2, argv)
                self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
