import unittest
from datetime import date, timedelta

from jobhunt import tracker
from jobhunt.profile import DEFAULT_PROFILE
from jobhunt.score import evaluate

from .test_score import RICH_JD, cand

TODAY = date(2026, 10, 5)


def ev(**kw):
    return evaluate(cand(**kw), DEFAULT_PROFILE, TODAY)


def row(**kw):
    base = {c: "" for c in tracker.COLUMNS}
    base.update({"Key": "j_0000000001", "FirstSeen": "2026-10-01", "LastSeen": "2026-10-01",
                 "Status": "Shortlisted", "Score": "80", "Company": "Acme", "Title": "Role"})
    base.update(kw)
    return base


class ParseTests(unittest.TestCase):
    def test_csv_round_trip_preserves_everything_including_awkward_cells(self):
        rows = [
            row(Key="j_a", Title='Lead, "Creative" AI\nSpecialist', Notes="call back, ask about visa", Score="91"),
            row(Key="j_b", Status="Applied", Score="70", URL="https://example.com/x?a=1&b=2"),
        ]
        parsed, warnings = tracker.parse_table(tracker.dump_csv(rows))
        self.assertEqual(warnings, [])
        self.assertEqual(tracker.content_hash(parsed), tracker.content_hash(rows))
        by_key = {r["Key"]: r for r in parsed}
        # CSV quoting keeps commas, quotes and even a newline in a user-edited cell exactly.
        self.assertEqual(by_key["j_a"]["Title"], 'Lead, "Creative" AI\nSpecialist')
        self.assertEqual(by_key["j_a"]["Notes"], "call back, ask about visa")
        self.assertEqual(by_key["j_b"]["URL"], "https://example.com/x?a=1&b=2")

    def test_scraped_text_with_newlines_is_flattened_before_it_reaches_the_tracker(self):
        e = ev(title="Creative AI\nSpecialist", company="Acme\tStudio  ")
        rows, _ = tracker.merge([], [e], TODAY, DEFAULT_PROFILE)
        self.assertEqual((rows[0]["Title"], rows[0]["Company"]), ("Creative AI Specialist", "Acme Studio"))

    def test_hash_ignores_order_quoting_and_whitespace(self):
        a = [row(Key="j_a", Notes="x  y"), row(Key="j_b", Score="70")]
        b = [row(Key="j_b", Score="70.0"), row(Key="j_a", Notes=" x y ")]
        self.assertEqual(tracker.content_hash(a), tracker.content_hash(b))

    def test_hash_changes_when_content_changes(self):
        base = [row(Key="j_a")]
        self.assertNotEqual(tracker.content_hash(base), tracker.content_hash([row(Key="j_a", Status="Applied")]))
        self.assertNotEqual(tracker.content_hash(base), tracker.content_hash(base + [row(Key="j_b")]))
        self.assertNotEqual(tracker.content_hash(base), tracker.content_hash([]))

    def test_markdown_table_and_preface_lines(self):
        text = (
            "Sheet: Job Hunt Tracker\nSome preface the connector adds\n\n"
            "| Key | FirstSeen | LastSeen | Status | Score | Company | Title |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| j_a | 2026-10-01 | 2026-10-04 | applied | 88 | Acme | Creative AI Specialist |\n"
        )
        rows, warnings = tracker.parse_table(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["Key"], rows[0]["Status"], rows[0]["Score"]), ("j_a", "Applied", "88"))
        self.assertEqual(rows[0]["Notes"], "")

    def test_tsv(self):
        text = "Key\tStatus\tScore\tCompany\nj_a\tInterviewing\t77\tAcme\n"
        rows, _ = tracker.parse_table(text)
        self.assertEqual((rows[0]["Status"], rows[0]["Company"]), ("Interview", "Acme"))

    def test_bom_and_case_insensitive_headers(self):
        rows, _ = tracker.parse_table("﻿key,STATUS,score\nj_a,offer,90\n")
        self.assertEqual((rows[0]["Key"], rows[0]["Status"]), ("j_a", "Offer"))

    def test_unknown_columns_warn_and_are_dropped(self):
        rows, warnings = tracker.parse_table("Key,Status,Mood\nj_a,Applied,great\n")
        self.assertEqual(len(rows), 1)
        self.assertTrue(any("Mood" in w for w in warnings))

    def test_rows_without_key_are_skipped_with_a_warning(self):
        rows, warnings = tracker.parse_table("Key,Status\nj_a,Applied\n,Applied\n")
        self.assertEqual(len(rows), 1)
        self.assertTrue(any("no Key" in w for w in warnings))

    def test_garbage_and_empty_input_never_raise(self):
        self.assertEqual(tracker.parse_table("")[0], [])
        rows, warnings = tracker.parse_table("this is not a table at all")
        self.assertEqual(rows, [])
        self.assertTrue(warnings)
        self.assertEqual(tracker.parse_table("Key,Notes\nj_a,hi")[0], [])

    def test_short_rows_are_padded(self):
        rows, _ = tracker.parse_table("Key,Status,Score,Company\nj_a,Applied\n")
        self.assertEqual((rows[0]["Score"], rows[0]["Company"]), ("", ""))


REAL_CSV_SENT_TO_DRIVE = '''Key,FirstSeen,LastSeen,Status,Score,Tier,Pay,PaySource,Company,Title,Source,URL,Flags,Notes
j_9c7980927f,2026-10-05,2026-10-05,Shortlisted,86,A,"AED 18,000+/mo",listing,Trade Quo Global Ltd,AI Influencer Marketer,indeed,https://to.indeed.com/aa7gldpglphd,asks_current_salary,
j_217e1063d1,2026-10-05,2026-10-05,Shortlisted,73,A,"AED 8,000–11,000/mo",listing,Rayqube Futrue Tech,"Lead Graphic, Motion Graphics & AI Video Specialist",indeed,https://to.indeed.com/aagrw6wjhq28,heavy_overtime,
j_595315ebf5,2026-10-05,2026-10-05,Shortlisted,68,U,"AED 1,111+/mo",listing,Varasto,AI SPECIALIST,indeed,https://to.indeed.com/aahgfqcyqryb,pay_min_below_floor;visa_not_stated,
j_61c519ef63,2026-10-05,2026-10-05,Shortlisted,65,U,not listed,unknown,Wodoh Engineering Services,Generative AI Software Engineer & Digital Marketing Specialist | AI Automation,indeed,https://to.indeed.com/aadjjgskypmg,pay_unlisted;visa_not_stated;engineering_role,
j_a5a999ae09,2026-10-05,2026-10-05,Shortlisted,60,U,not listed,unknown,Sokin,Senior Social Media Manager (Global) - Dubai,indeed,https://to.indeed.com/aatdyrdclw9w,pay_unlisted;visa_not_stated,
'''
FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


class DriveReadbackTests(unittest.TestCase):
    """The fixture is what Google Drive's read_file_content returned for a Sheet made from REAL_CSV_SENT_TO_DRIVE."""

    def setUp(self):
        self.readback = (FIXTURES / "drive_sheet_readback.txt").read_text(encoding="utf-8")

    def test_real_round_trip_through_drive_is_exact(self):
        sent, _ = tracker.parse_table(REAL_CSV_SENT_TO_DRIVE)
        got, warnings = tracker.parse_table(self.readback)
        self.assertEqual(warnings, [])
        self.assertEqual(len(got), 5)
        self.assertEqual(tracker.content_hash(got), tracker.content_hash(sent))

    def test_markdown_escapes_are_undone(self):
        got, _ = tracker.parse_table(self.readback)
        keys = [r["Key"] for r in got]
        self.assertTrue(all("\\" not in k for k in keys), keys)  # j\_9c79... must come back as j_9c79...
        self.assertIn("j_9c7980927f", keys)
        wodoh = next(r for r in got if r["Company"].startswith("Wodoh"))
        self.assertEqual(wodoh["Title"], "Generative AI Software Engineer & Digital Marketing Specialist | AI Automation")
        self.assertIn("pay_unlisted;visa_not_stated;engineering_role", wodoh["Flags"])

    def test_the_summary_drive_appends_after_the_table_is_not_read_as_rows(self):
        got, _ = tracker.parse_table(self.readback)
        self.assertEqual(len(got), 5)
        self.assertFalse([r for r in got if r["Key"].startswith(("-", "#"))])

    def test_a_user_edit_in_the_sheet_survives(self):
        edited = self.readback.replace("| Shortlisted | 86 ", "| Applied     | 86 ")
        got, _ = tracker.parse_table(edited)
        self.assertEqual(next(r for r in got if r["Key"] == "j_9c7980927f")["Status"], "Applied")

    def test_a_truncated_readback_is_detected_from_the_declared_range(self):
        lines = self.readback.splitlines()
        cut = [ln for ln in lines if "j\\_a5a999ae09" not in ln or not ln.startswith("|")]
        got, warnings = tracker.parse_table("\n".join(cut))
        self.assertEqual(len(got), 4)
        self.assertTrue(any("readback incomplete" in w and "reports 5" in w for w in warnings), warnings)

    def test_unescape_helper(self):
        self.assertEqual(tracker._md_unescape(r"j\_9c \| x \\ y \* z"), r"j_9c | x \ y * z")
        self.assertEqual(tracker._md_unescape("plain text 5-10"), "plain text 5-10")


class StatusTests(unittest.TestCase):
    def test_synonyms(self):
        cases = {
            "": "Shortlisted", "new": "Shortlisted", " Applied ": "Applied", "INTERVIEWING": "Interview",
            "hired": "Accepted", "joined": "Accepted", "not interested": "Rejected", "skip": "Rejected",
            "closed": "Dead", "offer": "Offer",
        }
        for raw, expected in cases.items():
            self.assertEqual(tracker.canonical_status(raw), expected, raw)

    def test_unknown_text_is_kept_as_typed(self):
        self.assertEqual(tracker.canonical_status("call Sara first"), "call Sara first")


class MergeTests(unittest.TestCase):
    def merge(self, existing, evals, today=TODAY, profile=DEFAULT_PROFILE):
        return tracker.merge(existing, evals, today, profile)

    def test_new_shortlisted_job_is_added(self):
        e = ev()
        rows, stats = self.merge([], [e])
        self.assertEqual(stats["added_ids"], [e.job_id])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["Key"], r["Status"], r["FirstSeen"], r["LastSeen"]), (e.job_id, "Shortlisted", "2026-10-05", "2026-10-05"))
        self.assertEqual((r["Tier"], r["Score"], r["Company"]), ("A", str(e.score), "Acme Studio"))

    def test_second_identical_run_adds_nothing_and_changes_nothing(self):
        e = ev()
        first, _ = self.merge([], [e])
        second, stats = self.merge(first, [e])
        self.assertEqual(stats["added_ids"], [])
        self.assertEqual(stats["already_seen"], 1)
        self.assertEqual(tracker.content_hash(first), tracker.content_hash(second))

    def test_user_edits_survive_and_status_is_not_auto_changed(self):
        e = ev()
        existing = [row(Key=e.job_id, Status="Applied", Notes="sent CV 4 Oct", Score="50", LastSeen="2026-10-02")]
        rows, stats = self.merge(existing, [e])
        r = rows[0]
        self.assertEqual((r["Status"], r["Notes"], r["Score"]), ("Applied", "sent CV 4 Oct", "50"))
        self.assertEqual(r["LastSeen"], "2026-10-02")  # seeing a job again is not a write
        self.assertEqual(stats["added_ids"], [])

    def test_auto_fields_refresh_only_while_shortlisted(self):
        e = ev()
        rows, _ = self.merge([row(Key=e.job_id, Score="10", Tier="C")], [e])
        self.assertEqual((rows[0]["Score"], rows[0]["Tier"]), (str(e.score), "A"))
        self.assertEqual(rows[0]["LastSeen"], "2026-10-05")  # a real change is a write

    def test_an_unchanged_job_seen_again_changes_nothing_at_all(self):
        e = ev()
        first, _ = self.merge([], [e])
        before = [dict(r) for r in first]
        later, _ = self.merge(first, [e], today=TODAY + timedelta(days=3))
        self.assertEqual(later, before)  # not even LastSeen moves

    def test_rejected_by_user_is_never_resurrected(self):
        e = ev()
        existing = [row(Key=e.job_id, Status="Rejected")]
        rows, stats = self.merge(existing, [e])
        self.assertEqual(rows[0]["Status"], "Rejected")
        self.assertEqual(stats["added_ids"], [])
        self.assertEqual(stats["already_seen"], 1)

    def test_shortlisted_job_that_goes_stale_becomes_dead(self):
        e = ev(posted="2026-08-01")
        self.assertIn("stale", e.reject_reasons)
        rows, stats = self.merge([row(Key=e.job_id, Status="Shortlisted")], [e])
        self.assertEqual(rows[0]["Status"], "Dead")
        self.assertIn("stale", rows[0]["Notes"])
        self.assertEqual(stats["auto_dead"], 1)

    def test_applied_job_that_goes_stale_is_left_alone(self):
        e = ev(posted="2026-08-01")
        rows, stats = self.merge([row(Key=e.job_id, Status="Applied")], [e])
        self.assertEqual(rows[0]["Status"], "Applied")
        self.assertEqual(stats["auto_dead"], 0)

    def test_counters_for_rejected_and_below_threshold(self):
        evals = [
            ev(title="Junior Video Editor"),
            ev(title="Marketing Intern", company="Other Co"),
            ev(title="Content Creator", company="Third Co", description="short", pay_text=None, posted="14 days ago"),
        ]
        rows, stats = self.merge([], evals)
        self.assertEqual(rows, [])
        self.assertEqual(stats["rejected_jobs"], 2)
        self.assertEqual(stats["reject_reasons"]["junior_level"], 2)
        self.assertEqual(stats["below_threshold"], 1)

    def test_prune_drops_old_unprotected_rows_only(self):
        old = (TODAY - timedelta(days=DEFAULT_PROFILE["prune_days"] + 1)).isoformat()
        existing = [
            row(Key="j_short", Status="Shortlisted", FirstSeen=old),
            row(Key="j_rej", Status="Rejected", FirstSeen=old),
            row(Key="j_dead", Status="Dead", FirstSeen=old),
            row(Key="j_app", Status="Applied", FirstSeen=old),
            row(Key="j_int", Status="Interview", FirstSeen=old),
            row(Key="j_off", Status="Offer", FirstSeen=old),
            row(Key="j_new", Status="Shortlisted", FirstSeen=TODAY.isoformat()),
        ]
        rows, stats = self.merge(existing, [])
        self.assertEqual({r["Key"] for r in rows}, {"j_app", "j_int", "j_off", "j_new"})
        self.assertEqual(stats["pruned"], 3)

    def test_prune_boundary_is_exactly_prune_days(self):
        n = DEFAULT_PROFILE["prune_days"]
        on_the_line = (TODAY - timedelta(days=n)).isoformat()
        one_past = (TODAY - timedelta(days=n + 1)).isoformat()
        rows, stats = self.merge([row(Key="j_keep", FirstSeen=on_the_line), row(Key="j_drop", FirstSeen=one_past)], [])
        self.assertEqual([r["Key"] for r in rows], ["j_keep"])
        self.assertEqual(stats["pruned"], 1)

    def test_unparseable_date_is_kept_not_dropped(self):
        rows, stats = self.merge([row(Key="j_x", FirstSeen="whenever")], [])
        self.assertEqual([r["Key"] for r in rows], ["j_x"])
        self.assertEqual(stats["pruned"], 0)

    def test_merge_does_not_mutate_its_input(self):
        existing = [row(Key="j_a", LastSeen="2026-10-01")]
        snapshot = [dict(r) for r in existing]
        self.merge(existing, [ev()])
        self.assertEqual(existing, snapshot)


class StopTests(unittest.TestCase):
    def test_accepted_stops_the_hunt(self):
        reasons = tracker.stop_reasons([row(Status="Accepted", Company="Acme", Title="Role"), row(Key="j_2")])
        self.assertEqual(reasons, ["Accepted: Acme - Role"])
        self.assertEqual(tracker.stop_reasons([row(Status="Offer"), row(Key="j_2", Status="Applied")]), [])


class HuntDayTests(unittest.TestCase):
    def test_uses_profile_start_date(self):
        self.assertEqual(tracker.hunt_day([], TODAY, "2026-10-05"), 1)
        self.assertEqual(tracker.hunt_day([], TODAY, "2026-09-22"), 14)

    def test_falls_back_to_earliest_first_seen(self):
        rows = [row(FirstSeen="2026-10-03"), row(Key="j_2", FirstSeen="2026-10-01")]
        self.assertEqual(tracker.hunt_day(rows, TODAY), 5)

    def test_none_when_unknown(self):
        self.assertIsNone(tracker.hunt_day([], TODAY))
        self.assertIsNone(tracker.hunt_day([row(FirstSeen="bad")], TODAY))

    def test_bad_start_date_falls_back(self):
        self.assertEqual(tracker.hunt_day([row(FirstSeen="2026-10-04")], TODAY, "not-a-date"), 2)


class OrderingTests(unittest.TestCase):
    def test_dump_orders_active_work_first_then_score(self):
        rows = [
            row(Key="j_1", Status="Shortlisted", Score="90"),
            row(Key="j_2", Status="Interview", Score="60"),
            row(Key="j_3", Status="Shortlisted", Score="95"),
            row(Key="j_4", Status="Rejected", Score="99"),
        ]
        parsed, _ = tracker.parse_table(tracker.dump_csv(rows))
        self.assertEqual([r["Key"] for r in parsed], ["j_2", "j_3", "j_1", "j_4"])


if __name__ == "__main__":
    unittest.main()
