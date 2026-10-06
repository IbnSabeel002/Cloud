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

    def test_the_number_of_messages_must_match_the_digests_the_run_had_to_send(self):
        self.assertEqual(sent_doc([link(3), link(2)], NOW, expect=2)["SlackMessages"], 2)
        with self.assertRaises(ValueError) as why:
            sent_doc([link(3)], NOW, expect=2)
        self.assertIn("1 different Slack message(s)", str(why.exception))
        with self.assertRaises(ValueError):
            sent_doc([link(3), ts(3)], NOW, expect=2)  # the same message twice is still one message
        with self.assertRaises(ValueError):
            sent_doc([link(3), link(2)], NOW, expect=1)

    def test_the_edges_of_the_window_are_exact(self):
        limit = MAX_AGE.total_seconds() / 60
        sent_doc([ts(limit - 0.1)], NOW)
        with self.assertRaises(ValueError):
            sent_doc([ts(limit + 0.1)], NOW)
        ahead = slack_record.MAX_AHEAD.total_seconds() / 60
        sent_doc([ts(-(ahead - 0.1))], NOW)
        with self.assertRaises(ValueError):
            sent_doc([ts(-(ahead + 0.1))], NOW)

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


def real_ts(minutes_ago: float) -> str:
    """A Slack message timestamp this many minutes before the real current time."""
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return f"{int(moment.timestamp())}.{moment.microsecond:06d}"


def dubai_time_of(ref: str) -> str:
    return message_time(ref).astimezone(slack_record.DUBAI).strftime("%H:%M")


class CommandTests(unittest.TestCase):
    """The command runs on the real clock, as it does in the daily run: there is no way to give it another one."""

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_sent_writes_the_document_the_playbook_merges_into_the_run_record(self):
        first, second = real_ts(3), real_ts(2)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "run_slack.json"
            code, out, _ = self.run_cli("slack-record", "--sent", first, second, "--expect", "2", "--out", str(target))
            self.assertEqual(code, 0)
            written = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(written, {"SlackSent": dubai_time_of(second), "SlackMessages": 2})
            self.assertEqual(json.loads(out), written)

    def test_a_state_writes_a_word(self):
        for state in ("off", "failed", "unconfirmed"):
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "run_slack.json"
                code, _, _ = self.run_cli("slack-record", "--state", state, "--out", str(target))
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"SlackSent": state, "SlackMessages": 0})

    def test_a_made_up_or_old_reference_exits_2_and_writes_nothing(self):
        for ref in ("made up", real_ts(120), "08:00"):
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "run_slack.json"
                code, out, err = self.run_cli("slack-record", "--sent", ref, "--expect", "1", "--out", str(target))
                self.assertEqual(code, 2, ref)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith("error:"), err)
                self.assertFalse(target.exists(), ref)

    def test_a_refusal_never_leaves_an_earlier_days_note_behind(self):
        # The playbook merges this file into today's run record: a stale one would pass for today's.
        yesterday = {"SlackSent": "07:58", "SlackMessages": 1}
        for argv in (["--sent", "made up", "--expect", "1"], ["--sent", real_ts(120), "--expect", "1"],
                     ["--sent", real_ts(1), "--expect", "2"], ["--sent", real_ts(1)]):
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "run_slack.json"
                target.write_text(json.dumps(yesterday), encoding="utf-8")
                code, _, _ = self.run_cli("slack-record", *argv, "--out", str(target))
                self.assertEqual(code, 2, argv)
                self.assertFalse(target.exists(), f"stale note survived {argv}")

    def test_a_good_run_replaces_an_earlier_days_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "run_slack.json"
            target.write_text(json.dumps({"SlackSent": "07:58", "SlackMessages": 1}), encoding="utf-8")
            ref = real_ts(1)
            self.assertEqual(self.run_cli("slack-record", "--state", "failed", "--out", str(target))[0], 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["SlackSent"], "failed")
            self.assertEqual(self.run_cli("slack-record", "--sent", ref, "--expect", "1", "--out", str(target))[0], 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["SlackSent"], dubai_time_of(ref))

    def test_sent_needs_the_number_of_digests_and_it_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "run_slack.json"
            one, two = real_ts(2), real_ts(1)
            code, _, err = self.run_cli("slack-record", "--sent", one, "--out", str(target))
            self.assertEqual(code, 2)
            self.assertIn("--expect", err)
            self.assertEqual(self.run_cli("slack-record", "--sent", one, "--expect", "2", "--out", str(target))[0], 2)
            self.assertEqual(self.run_cli("slack-record", "--sent", one, one, "--expect", "2", "--out", str(target))[0], 2)
            self.assertFalse(target.exists())
            self.assertEqual(self.run_cli("slack-record", "--sent", one, two, "--expect", "2", "--out", str(target))[0], 0)

    def test_a_file_that_cannot_be_written_is_a_clear_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_folder = str(Path(tmp) / "no" / "such" / "run_slack.json")
            code, out, err = self.run_cli("slack-record", "--state", "off", "--out", missing_folder)
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("error: cannot write"), err)
            code, out, err = self.run_cli("slack-record", "--state", "off", "--out", tmp)  # a folder, not a file
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("error:"), err)

    def test_the_command_cannot_be_given_another_clock(self):
        with self.assertRaises(SystemExit) as stopped, contextlib.redirect_stderr(io.StringIO()):
            main(["slack-record", "--sent", real_ts(1), "--expect", "1", "--out", "/tmp/never-written.json",
                  "--now", "2026-10-07T04:00:00+00:00"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertNotIn("--now", Path(slack_record.__file__).read_text(encoding="utf-8"))

    def test_exactly_one_of_sent_or_state_is_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "x.json")
            for argv in (["slack-record", "--out", out],
                         ["slack-record", "--sent", real_ts(1), "--expect", "1", "--state", "off", "--out", out],
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
