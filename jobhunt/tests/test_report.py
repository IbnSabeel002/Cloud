import json
import unittest
from datetime import date
from pathlib import Path

from jobhunt.cli import pipeline
from jobhunt.profile import load_profile
from jobhunt.report import (
    digest_chunks, flag_label, reason_label, render_report_html, render_report_md,
)

FIXTURE = Path(__file__).parent / "fixtures" / "candidates_2026-10-05.json"
TODAY = date(2026, 10, 5)
HEALTHY = [{"source": "Indeed", "ok": True}, {"source": "Tiny Fish", "ok": True}]


def run():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))["candidates"]
    return pipeline(load_profile(), data, [], TODAY)


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.r = run()

    def digest(self, **kw):
        args = dict(summary=self.r.summary, shortlist=self.r.shortlist, health=HEALTHY, analysis=None,
                    report_url="https://example.com/report", today=TODAY)
        args.update(kw)
        return "\n".join(digest_chunks(**args))

    def test_header_counts_and_health(self):
        text = self.digest()
        self.assertIn("Mon 05 Oct 2026", text)
        self.assertIn("day 1", text)
        self.assertIn("✅ Indeed · ✅ Tiny Fish", text)
        self.assertIn("**5 new** shortlisted", text)
        self.assertIn("9 screened out", text)
        self.assertNotIn("Degraded", text)

    def test_reject_reasons_are_humanised_and_ranked(self):
        text = self.digest()
        self.assertIn("4 posting too old", text)
        self.assertIn("3 fresher/entry/junior", text)
        self.assertNotIn("junior_level", text)

    def test_top_pick_has_link_pay_source_and_flags(self):
        text = self.digest()
        self.assertIn("[Social Media and Marketing Manager](https://example.com/jobs/azya-smmm)", text)
        self.assertIn("Score 93 · Tier A · AED 10,000/mo (listing) · posted 3d ago · ⭐ strong", text)
        self.assertIn("Check: visa not stated", text)
        self.assertNotIn("assumed monthly", text)  # the normal case is not worth a warning
        self.assertNotIn("(unknown)", text)
        self.assertIn("Score 76 · Tier U · pay not listed · posted 6d ago · ⭐ strong", text)
        self.assertNotIn("Check: pay not listed", text)  # pay is already shown on the line above
        self.assertIn("Full report + outreach drafts: https://example.com/report", text)
        # No draft was created, so the digest must not claim one was.
        self.assertNotIn("saved in Gmail Drafts", text)
        self.assertIn("Outreach notes for 3 strong match(es) are in the report (no draft was saved). Nothing was sent.", text)

    def test_pay_is_not_checked_when_no_description_was_captured(self):
        # A live run said "pay not listed" for a job whose page showed AED 3,500 to 4,000: the pay had never been opened.
        thin = dict(self.r.shortlist[0], pay_display="not listed", flags=["no_jd", "pay_unlisted"], url="")
        text = self.digest(shortlist=[thin])
        self.assertIn("pay not checked", text)
        self.assertNotIn("pay not listed", text)
        listed_none = dict(self.r.shortlist[0], pay_display="not listed", flags=["pay_unlisted"])
        self.assertIn("pay not listed", self.digest(shortlist=[listed_none]))
        self.assertNotIn("pay not checked", self.digest(shortlist=[listed_none]))

    def test_a_job_with_no_link_is_shown_by_name_and_does_not_break_the_digest(self):
        no_link = dict(self.r.shortlist[0], url="", flags=["no_job_link"])
        text = self.digest(shortlist=[no_link])
        self.assertIn(f"**{no_link['title']}** —", text)
        self.assertNotIn("[" + no_link["title"] + "](", text)
        self.assertIn("no direct link to the job", text)

    def test_digest_claims_only_the_drafts_that_exist(self):
        self.assertIn("3 outreach draft(s) saved in Gmail Drafts. Nothing was sent.", self.digest(drafts_created=3))
        self.assertNotIn("no draft was saved", self.digest(drafts_created=3))
        mixed = self.digest(drafts_created=1)
        self.assertIn("1 outreach draft(s) saved in Gmail Drafts", mixed)
        self.assertIn("Outreach notes for 2 strong match(es) are in the report", mixed)
        self.r.summary["outreach_keys"] = []
        self.assertNotIn("Outreach notes", self.digest())
        self.assertNotIn("Gmail Drafts", self.digest())

    def test_digest_links_to_the_tracker_page_when_given(self):
        text = self.digest(tracker_url="https://claude.ai/artifact/abc")
        self.assertIn("Tracker (change a status or add a note): https://claude.ai/artifact/abc", text)
        self.assertNotIn("Tracker (change", self.digest())

    def test_model_written_why_overrides_the_auto_one(self):
        top = self.r.shortlist[0]["job_id"]
        text = self.digest(analysis={top: {"why": "Pay is real and the JD asks for your exact stack."}})
        self.assertIn("Why: Pay is real and the JD asks for your exact stack.", text)

    def test_degraded_run_is_loud(self):
        health = [{"source": "Indeed", "ok": True}, {"source": "Bayt", "ok": False, "detail": "timeout"}]
        text = self.digest(health=health)
        self.assertIn("Degraded run", text)
        self.assertIn("⚠️ Bayt failed (timeout)", text)

    def test_missing_health_report_counts_as_degraded(self):
        self.assertIn("Degraded run", self.digest(health=None))

    def test_quiet_day_says_so_instead_of_staying_silent(self):
        empty = pipeline(load_profile(), [], [], TODAY)
        text = "\n".join(digest_chunks(empty.summary, empty.shortlist, HEALTHY, None, None, TODAY))
        self.assertIn("No new matches that clear the bar today", text)
        self.assertIn("**0 new**", text)

    def test_max_top_limits_and_mentions_the_rest(self):
        text = self.digest(max_top=2)
        self.assertIn("and 3 more in the report", text)
        self.assertEqual(text.count("Score "), 2)

    def test_fortnightly_nudge_only_on_day_14(self):
        self.r.summary["hunt_day"] = 14
        self.assertIn("Day 14 of the hunt", self.digest())
        self.r.summary["hunt_day"] = 13
        self.assertNotIn("of the hunt", self.digest())

    def test_stop_instructions_always_present(self):
        self.assertIn("stop the job hunt", self.digest())

    def test_chunks_respect_the_slack_limit_and_lose_nothing(self):
        big = [dict(self.r.shortlist[0], job_id=f"j_{i}", title=f"Role number {i}", why="x" * 400, flags=["no_jd"] * 6)
               for i in range(60)]
        chunks = digest_chunks(self.r.summary, big, HEALTHY, None, None, TODAY, max_top=60, limit=1500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 1500 for c in chunks), [len(c) for c in chunks])
        joined = "\n".join(chunks)
        for i in range(60):
            self.assertIn(f"Role number {i}]", joined)

    def test_a_single_overlong_line_is_split_not_dropped(self):
        shortlist = [dict(self.r.shortlist[0], why="Q" * 3000)]  # "Q" appears nowhere else in a digest
        chunks = digest_chunks(self.r.summary, shortlist, HEALTHY, None, None, TODAY, limit=1000)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertEqual(sum(c.count("Q") for c in chunks), 3000)


class HtmlTests(unittest.TestCase):
    def setUp(self):
        self.r = run()

    def test_untrusted_text_is_escaped_everywhere(self):
        evil = dict(self.r.shortlist[0], title="<script>alert(1)</script>", company='"><img src=x onerror=alert(2)>',
                    url='https://example.com/"><script>alert(3)</script>')
        analysis = {evil["job_id"]: {
            "gaps": "<b>bold</b>\nsecond line", "linkedin_note": "<iframe src=//evil>",
            "email_note": "hi & bye", "cv_tweaks": ["<u>x</u>"],
        }}
        page = render_report_html(self.r.summary, [evil], HEALTHY, analysis, TODAY)
        for raw in ("<script>", "<img src=x", "<iframe", "<b>bold</b>", "<u>x</u>"):
            self.assertNotIn(raw, page, raw)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;<br>second line", page)
        self.assertIn("hi &amp; bye", page)

    def test_report_contains_every_new_job_and_the_screened_out_summary(self):
        page = render_report_html(self.r.summary, self.r.shortlist, HEALTHY, None, TODAY)
        for e in self.r.shortlist:
            self.assertIn(e["company"], page)
        self.assertIn("4 × posting too old", page)
        self.assertIn("Also on:", page)  # the Azya listing seen on two boards

    def test_the_report_counts_every_hit_found_not_just_those_opened(self):
        self.r.summary["raw_hits"] = 68
        page = render_report_html(self.r.summary, self.r.shortlist, HEALTHY, None, TODAY)
        self.assertIn("68 hits found", page)
        del self.r.summary["raw_hits"]
        self.assertIn("19 hits found", render_report_html(self.r.summary, self.r.shortlist, HEALTHY, None, TODAY))

    def test_analysis_sections_appear_when_supplied(self):
        top = self.r.shortlist[0]["job_id"]
        analysis = {top: {"gaps": "Gap: no portfolio link.", "cv_tweaks": ["Add portfolio URL"],
                          "linkedin_note": "Hi there", "email_note": "Dear team"}}
        page = render_report_html(self.r.summary, self.r.shortlist, HEALTHY, analysis, TODAY)
        for text in ("Fit and gaps", "Gap: no portfolio link.", "CV tweaks for this role", "Add portfolio URL",
                     "LinkedIn note", "Email note"):
            self.assertIn(text, page)

    def test_empty_day(self):
        empty = pipeline(load_profile(), [], [], TODAY)
        page = render_report_html(empty.summary, [], HEALTHY, None, TODAY)
        self.assertIn("No new matches cleared the bar today", page)

    def test_markdown_report(self):
        top = self.r.shortlist[0]["job_id"]
        md = render_report_md(self.r.summary, self.r.shortlist, HEALTHY, {top: {"gaps": "G", "cv_tweaks": ["T"]}}, TODAY)
        self.assertIn("# Job hunt report · 2026-10-05", md)
        self.assertIn("**Fit and gaps**", md)
        self.assertIn("- T", md)


class LabelTests(unittest.TestCase):
    def test_reason_labels(self):
        self.assertEqual(reason_label("stale"), "posting too old")
        self.assertEqual(reason_label("language:french"), "needs French")
        self.assertEqual(reason_label("job_type:part-time"), "part-time role")
        self.assertEqual(reason_label("location:riyadh"), "based in Riyadh")
        self.assertEqual(reason_label("location:hong_kong"), "based in Hong Kong")
        self.assertEqual(reason_label("something_new"), "something_new")

    def test_flag_labels(self):
        self.assertEqual(flag_label("visa_not_stated"), "visa not stated")
        self.assertEqual(flag_label("language:arabic"), "Arabic required")
        self.assertEqual(flag_label("pay_assumed:period_assumed_yearly"), "pay period assumed yearly")
        self.assertEqual(flag_label("brand_new_flag"), "brand_new_flag")
        self.assertEqual(flag_label("pay_min_below_floor"), "advertised minimum is under your floor")
        self.assertEqual(flag_label("employer_mismatch"), "employer name differs from the job text")
        self.assertEqual(flag_label("title_says:part_time"), "title says part time")
        self.assertEqual(flag_label("immediate_joiner"), "wants an immediate joiner (check your notice end date)")
        self.assertEqual(flag_label("needs_own_labour_card"),
                         "wants you to bring your own labour card (yours must come from the new employer)")
        self.assertEqual(flag_label("no_job_link"), "no direct link to the job (search its title and company)")
        self.assertEqual(flag_label("outside_dubai:abu_dhabi"), "based in Abu Dhabi, not Dubai")
        self.assertEqual(flag_label("outside_dubai:ras_al_khaimah"), "based in Ras Al Khaimah, not Dubai")


if __name__ == "__main__":
    unittest.main()
