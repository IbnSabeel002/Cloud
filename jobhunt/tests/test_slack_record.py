"""The Slack note is what the watchdog trusts: it must come from a real, recent message and never from a typed time."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobhunt import slack_record
from jobhunt.cli import main
from jobhunt.slack_record import MAX_AGE, message_time, sent_doc, state_doc

NOW = datetime(2026, 10, 7, 4, 0, 0, tzinfo=timezone.utc)  # 08:00 in Dubai


def ts(minutes_ago: float) -> str:
    """A Slack message timestamp this many minutes before NOW."""
    moment = NOW - timedelta(minutes=minutes_ago)
    return f"{int(moment.timestamp())}.{moment.microsecond:06d}"


def link(minutes_ago: float, query: str = "") -> str:
    seconds, micro = ts(minutes_ago).split(".")
    return f"https://exampleteam.slack.com/archives/DEXAMPLE123/p{seconds}{micro}{query}"


class MessageTimeTests(unittest.TestCase):
    def test_a_message_link_and_a_bare_timestamp_name_the_same_moment(self):
        self.assertEqual(message_time(link(5)), message_time(ts(5)))

    def test_the_link_as_the_send_tool_writes_it_is_accepted(self):
        # The tool's JSON result writes slashes as \/ . The shape comes from a real send result, names masked.
        raw = r"https:\/\/exampleteam.slack.com\/archives\/DEXAMPLE123\/p1791258615952059"
        self.assertEqual(message_time(raw), message_time("1791258615.952059"))
        self.assertEqual(message_time(raw).microsecond, 952059)

    def test_the_microseconds_are_kept(self):
        self.assertEqual(message_time("1791302400.123456").microsecond, 123456)
        self.assertEqual(message_time("https://a.slack.com/archives/D1/p1791302400123456").microsecond, 123456)

    def test_a_link_may_carry_a_query_string(self):
        self.assertEqual(message_time(link(5, "?thread_ts=1791302100.000100&cid=DEXAMPLE123")), message_time(ts(5)))

    def test_anything_else_is_refused(self):
        for bad in (
            "", "nonsense", "08:00", "1791302400", "1791302400.12345", "17913024001.123456", "179130240.123456",
            "https://exampleteam-slack-com/archives/DEXAMPLE123/p1791302400123456",
            "https://exampleteam.slackXcom/archives/DEXAMPLE123/p1791302400123456",
            "http://exampleteam.slack.com/archives/DEXAMPLE123/p1791302400123456",
            "https://evil.example/archives/DEXAMPLE123/p1791302400123456",
            "https://exampleteam.slack.com.evil.example/archives/DEXAMPLE123/p1791302400123456",
            "https://exampleteam.slack.com/archives/DEXAMPLE123/p179130240012345",
            "https://exampleteam.slack.com/archives/DEXAMPLE123/p1791302400123456 and more words",
            "see https://exampleteam.slack.com/archives/DEXAMPLE123/p1791302400123456",
            "https://exampleteam.slack.com/messages/DEXAMPLE123/p1791302400123456",
        ):
            with self.assertRaises(ValueError, msg=bad):
                message_time(bad)


class SentDocTests(unittest.TestCase):
    def test_a_recent_message_gives_its_dubai_time(self):
        self.assertEqual(sent_doc([link(3)], NOW), {"SlackSent": "07:57", "SlackMessages": 1})

    def test_the_stamp_uses_dubai_time_across_midnight(self):
        for utc, expected in (("2026-10-06T19:59:30+00:00", "23:59"), ("2026-10-06T20:00:00+00:00", "00:00"),
                              ("2026-10-07T03:47:00+00:00", "07:47")):
            now = datetime.fromisoformat(utc)
            self.assertEqual(sent_doc([f"{int(now.timestamp())}.000001"], now)["SlackSent"], expected)

    def test_several_messages_use_the_latest_and_are_counted(self):
        doc = sent_doc([link(4), link(2), link(3)], NOW)
        self.assertEqual(doc, {"SlackSent": "07:58", "SlackMessages": 3})

    def test_the_same_message_twice_counts_once(self):
        self.assertEqual(sent_doc([link(2), ts(2)], NOW)["SlackMessages"], 1)

    def test_an_old_message_is_refused(self):
        sent_doc([ts(MAX_AGE.total_seconds() / 60 - 0.5)], NOW)  # just inside the window
        for minutes in (MAX_AGE.total_seconds() / 60 + 1, 600, 24 * 60):
            with self.assertRaises(ValueError, msg=minutes) as why:
                sent_doc([ts(minutes)], NOW)
            self.assertIn("last 30 minutes", str(why.exception))

    def test_a_message_from_the_future_is_refused(self):
        with self.assertRaises(ValueError):
            sent_doc([ts(-10)], NOW)
        sent_doc([ts(-1)], NOW)  # a little clock disagreement is fine

    def test_one_bad_message_spoils_the_lot(self):
        with self.assertRaises(ValueError):
            sent_doc([link(2), "made up"], NOW)
        with self.assertRaises(ValueError):
            sent_doc([link(2), ts(120)], NOW)

    def test_no_message_is_refused_with_a_clear_reason(self):
        with self.assertRaises(ValueError) as why:
            sent_doc([], NOW)
        self.assertIn("no Slack message given", str(why.exception))

    def test_the_stamp_has_the_shape_the_watchdog_looks_for(self):
        for minutes in range(0, 30):
            stamp = sent_doc([ts(minutes)], NOW)["SlackSent"]
            self.assertRegex(stamp, r"^([01]\d|2[0-3]):[0-5]\d$")


class StateDocTests(unittest.TestCase):
    def test_each_state_is_written_as_a_plain_word_with_no_messages(self):
        for state in ("off", "failed", "unconfirmed"):
            self.assertEqual(state_doc(state), {"SlackSent": state, "SlackMessages": 0})
        self.assertEqual(set(slack_record.STATES), {"off", "failed", "unconfirmed"})

    def test_any_other_word_is_refused(self):
        for state in ("sent", "ok", "", "07:58", "OFF", "off "):
            with self.assertRaises(ValueError, msg=state):
                state_doc(state)


class CommandTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_sent_writes_the_document_the_playbook_merges_into_the_run_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "run_slack.json"
            code, out, _ = self.run_cli("slack-record", "--sent", link(3), link(2), "--out", str(target), "--now", NOW.isoformat())
            self.assertEqual(code, 0)
            written = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(written, {"SlackSent": "07:58", "SlackMessages": 2})
            self.assertEqual(json.loads(out), written)

    def test_a_state_writes_a_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "run_slack.json"
            code, _, _ = self.run_cli("slack-record", "--state", "unconfirmed", "--out", str(target))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"SlackSent": "unconfirmed", "SlackMessages": 0})

    def test_a_made_up_or_old_reference_exits_2_and_writes_nothing(self):
        for ref in ("made up", ts(120), "08:00"):
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "run_slack.json"
                code, out, err = self.run_cli("slack-record", "--sent", ref, "--out", str(target), "--now", NOW.isoformat())
                self.assertEqual(code, 2, ref)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith("error:"), err)
                self.assertFalse(target.exists(), ref)

    def test_a_time_without_a_time_zone_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_cli("slack-record", "--sent", ts(2), "--out", str(Path(tmp) / "x.json"), "--now", "2026-10-07T04:00:00")
            self.assertEqual(code, 2)
            self.assertIn("time zone", err)

    def test_exactly_one_of_sent_or_state_is_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "x.json")
            for argv in (["slack-record", "--out", out],
                         ["slack-record", "--sent", ts(1), "--state", "off", "--out", out],
                         ["slack-record", "--state", "sent", "--out", out],
                         ["slack-record", "--state", "off"]):
                with self.assertRaises(SystemExit) as stopped, contextlib.redirect_stderr(io.StringIO()):
                    main(argv)
                self.assertEqual(stopped.exception.code, 2, argv)

    def test_no_real_workspace_or_channel_is_named_in_this_module(self):
        source = Path(slack_record.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"[A-Za-z0-9-]+\.slack\.com/archives/[A-Z0-9]{6,}", source))


if __name__ == "__main__":
    unittest.main()
