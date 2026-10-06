import contextlib
import copy
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from jobhunt.alerts import canonical_url, parse_linkedin_alert, parse_threads
from jobhunt.cli import _fold_in_prefilter, main, pipeline, prefilter
from jobhunt.profile import load_profile
from jobhunt.score import ALERT_MARK, UNPARSED_ALERT, evaluate, validate_candidate

FIXTURES = Path(__file__).parent / "fixtures" / "alerts"
TODAY = date(2026, 10, 5)


def fixture(name: str) -> Path:
    return FIXTURES / f"{name}.json"


def body(name: str) -> str:
    return json.loads(fixture(name).read_text())["messages"][0]["plaintextBody"]


class UrlTests(unittest.TestCase):
    def test_tracking_is_stripped_and_the_comm_prefix_dropped(self):
        url = "View job: https://www.linkedin.com/comm/jobs/view/4473884059/?trackingId=abc%3D&refId=x&otpToken=secret"
        self.assertEqual(canonical_url(url), "https://www.linkedin.com/jobs/view/4473884059/")

    def test_a_link_that_is_not_a_job_gives_none(self):
        self.assertIsNone(canonical_url("https://www.linkedin.com/comm/jobs/alerts?x=1"))
        self.assertIsNone(canonical_url(""))
        self.assertIsNone(canonical_url(None))


class SingleAlertTests(unittest.TestCase):
    def test_the_same_job_in_two_sections_is_one_job(self):
        jobs, meta = parse_linkedin_alert(body("linkedin_digest_with_duplicates"))
        self.assertEqual([j["source_id"] for j in jobs], ["4473884059", "4473447453"])  # the text lists 4 job blocks
        self.assertEqual(meta, {"keyword": "social media manager", "place": "Dubai"})

    def test_when_a_repeat_reads_differently_the_first_one_wins(self):
        text = ("Your job alert for brand manager in Dubai\n\n"
                "Head of Social\nAcme\nDubai\nView job: https://www.linkedin.com/comm/jobs/view/77/?x=1\n------------------------------\n"
                "Head of Social (Dubai)\nACME FZ LLC\nDubai, UAE\nView job: https://www.linkedin.com/comm/jobs/view/77/?x=2\n---------------\n")
        jobs, _ = parse_linkedin_alert(text)
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]["title"], jobs[0]["company"], jobs[0]["location"]), ("Head of Social", "Acme", "Dubai"))

    def test_title_company_and_location_are_read_in_order(self):
        jobs, _ = parse_linkedin_alert(body("linkedin_digest_with_duplicates"))
        first = jobs[0]
        self.assertEqual((first["title"], first["company"], first["location"]),
                         ("Content Ecosystem Operation Manager - TikTok LIVE - Dubai", "TikTok", "Dubai"))
        self.assertEqual(first["url"], "https://www.linkedin.com/jobs/view/4473884059/")
        self.assertEqual(first["source"], "linkedin_alert")

    def test_a_school_alum_line_is_not_a_location(self):
        # Seen on a real alert: "1 school alum" sat between the place and the link and was read as the location.
        jobs, _ = parse_linkedin_alert(body("linkedin_digest_with_duplicates"))
        nnc = jobs[1]
        self.assertEqual((nnc["title"], nnc["company"], nnc["location"]),
                         ("Social Media Account Manager", "NNC", "Sharjah Emirate, United Arab Emirates"))

    def test_four_jobs_in_one_email(self):
        jobs, _ = parse_linkedin_alert(body("linkedin_digest_four_jobs"))
        self.assertEqual([(j["title"], j["company"]) for j in jobs], [
            ("Social Media Manager", "MINIMALIST"),
            ("Brand Channel Manager", "DEAL Holdings"),
            ("Brand Channel Manager", "The Food and Beverage Group"),
            ("Campaign Manager", "Clipster"),
        ])

    def test_the_email_gives_no_date_pay_or_description(self):
        jobs, _ = parse_linkedin_alert(body("linkedin_digest_four_jobs"))
        for j in jobs:
            self.assertIsNone(j["posted"])
            self.assertNotIn("pay_text", j)
            self.assertNotIn("description", j)

    def test_no_tracking_survives_anywhere(self):
        for name in ("linkedin_digest_with_duplicates", "linkedin_digest_abroad_and_dubai", "linkedin_digest_four_jobs"):
            for j in parse_linkedin_alert(body(name))[0]:
                self.assertNotIn("?", j["url"])
                self.assertTrue(j["url"].startswith("https://www.linkedin.com/jobs/view/"))

    def test_html_entities_and_odd_spacing_are_cleaned(self):
        text = ("Your job alert for brand manager in Dubai\n\nSocial Media &amp;   Digital Marketing Manager\nAcme &amp; Co\nDubai\n"
                "View job: https://www.linkedin.com/comm/jobs/view/11/?x=1\n----------------------------------------\n")
        jobs, _ = parse_linkedin_alert(text)
        self.assertEqual((jobs[0]["title"], jobs[0]["company"]), ("Social Media & Digital Marketing Manager", "Acme & Co"))

    def test_a_block_with_only_a_title_and_company_still_counts_without_a_location(self):
        text = "Head of Social\nAcme\nView job: https://www.linkedin.com/comm/jobs/view/22/?x=1\n-----------------------------\n"
        jobs, _ = parse_linkedin_alert(text)
        self.assertEqual((jobs[0]["title"], jobs[0]["company"], jobs[0]["location"]), ("Head of Social", "Acme", None))

    def test_a_block_with_nothing_readable_is_dropped_not_guessed(self):
        text = "Apply with resume & profile\nView job: https://www.linkedin.com/comm/jobs/view/33/?x=1\n----------------------\n"
        self.assertEqual(parse_linkedin_alert(text)[0], [])

    def test_empty_and_none_text(self):
        self.assertEqual(parse_linkedin_alert("")[0], [])
        self.assertEqual(parse_linkedin_alert(None)[0], [])


class ThreadFileTests(unittest.TestCase):
    ALL = [fixture(n) for n in ("linkedin_digest_with_duplicates", "linkedin_digest_abroad_and_dubai",
                                "linkedin_digest_four_jobs", "application_receipt_synthetic")]

    def test_only_job_alerts_are_read(self):
        jobs, stats = parse_threads(self.ALL)
        self.assertEqual(stats["emails"], 4)
        self.assertEqual(stats["alerts"], 3)
        self.assertEqual(stats["skipped"], {"not_a_linkedin_job_alert": 1})
        self.assertNotIn("Example Co", {j["company"] for j in jobs})  # the receipt's jobs are not alert jobs

    def test_a_job_in_two_emails_is_one_candidate(self):
        once, _ = parse_threads(self.ALL)
        twice, stats = parse_threads(self.ALL + self.ALL)  # every email arrives a second time
        ids = [j["source_id"] for j in twice]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [j["source_id"] for j in once])
        self.assertEqual(stats["jobs_in_alerts"], 2 * 9)  # 9 jobs per pass over the three alerts

    def test_a_real_thread_file_with_extra_text_around_the_json_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "thread.json"
            path.write_text("noise before\n" + fixture("linkedin_digest_four_jobs").read_text())
            jobs, _ = parse_threads([path])
            self.assertEqual(len(jobs), 4)

    def test_a_bare_message_list_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "msgs.json"
            msgs = json.loads(fixture("linkedin_digest_four_jobs").read_text())["messages"]
            path.write_text(json.dumps(msgs))
            self.assertEqual(len(parse_threads([path])[0]), 4)

    def test_an_alert_with_no_jobs_is_counted_and_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            path.write_text(json.dumps({"messages": [{"sender": "LinkedIn <jobalerts-noreply@linkedin.com>",
                                                      "plaintextBody": "Your job alert for x in Dubai\nNothing today."}]}))
            jobs, stats = parse_threads([path])
            self.assertEqual((jobs, stats["skipped"]), ([], {"alert_without_jobs": 1}))

    def test_the_sender_may_carry_a_display_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            msg = json.loads(fixture("linkedin_digest_four_jobs").read_text())["messages"][0]
            msg["sender"] = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
            path.write_text(json.dumps({"messages": [msg]}))
            self.assertEqual(len(parse_threads([path])[0]), 4)

    def test_a_look_alike_sender_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            msg = json.loads(fixture("linkedin_digest_four_jobs").read_text())["messages"][0]
            msg["sender"] = "jobalerts-noreply@linkedin.com.evil.example"
            path.write_text(json.dumps({"messages": [msg]}))
            self.assertEqual(parse_threads([path])[0], [])

    def test_unreadable_files_raise_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            path.write_text("not json at all")
            with self.assertRaises(ValueError):
                parse_threads([path])


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_parse_alert_writes_candidates_and_prints_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sub" / "alerts.json"
            code, stdout, _ = self.run_cli("parse-alert", "--thread", str(fixture("linkedin_digest_four_jobs")),
                                           str(fixture("application_receipt_synthetic")), "--out", str(out))
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(out.read_text())), 4)
            printed = json.loads(stdout)
            self.assertEqual((printed["jobs"], printed["alerts"], printed["skipped"]), (4, 1, {"not_a_linkedin_job_alert": 1}))

    def test_a_missing_file_exits_2_with_a_message(self):
        code, _, err = self.run_cli("parse-alert", "--thread", "/no/such/file.json", "--out", "/tmp/never.json")
        self.assertEqual(code, 2)
        self.assertIn("error", err)


class AlertProvenanceTests(unittest.TestCase):
    """Only the parse-alert command may make a linkedin_alert entry. A canary run typed them in by hand instead:
    no links and no sender check, so an entry without the command's mark is refused and counted."""

    @classmethod
    def setUpClass(cls):
        cls.parsed, _ = parse_threads([fixture("linkedin_digest_four_jobs")])
        cls.profile = load_profile(overrides={"languages_flag_only": [], "needs_visa_sponsorship": False})

    def hand_typed(self):
        return {"source": "linkedin_alert", "title": "Social Media Manager", "company": "Acme Typed By Hand",
                "location": "Dubai", "url": None}

    def test_every_parsed_job_carries_the_mark_and_is_valid(self):
        self.assertTrue(self.parsed)
        for job in self.parsed:
            self.assertEqual(job["parsed_by"], ALERT_MARK)
            self.assertEqual(validate_candidate(job), [])

    def test_a_hand_typed_alert_entry_is_refused(self):
        self.assertEqual(validate_candidate(self.hand_typed()), [UNPARSED_ALERT])

    def test_a_wrong_mark_is_refused_too(self):
        self.assertEqual(validate_candidate(dict(self.hand_typed(), parsed_by="me")), [UNPARSED_ALERT])

    def test_other_sources_do_not_need_the_mark(self):
        for source in ("indeed", "bayt", "indeed_alert", "bayt_alert", "other"):
            self.assertEqual(validate_candidate(dict(self.hand_typed(), source=source)), [], source)

    def test_the_pipeline_drops_and_counts_hand_typed_entries(self):
        result = pipeline(self.profile, self.parsed + [self.hand_typed()], [], TODAY)
        self.assertEqual(result.summary["unparsed_alert_entries"], 1)
        self.assertEqual(result.summary["unique"], len(self.parsed))
        self.assertNotIn("Acme Typed By Hand", [e["company"] for e in result.shortlist])
        self.assertNotIn("Acme Typed By Hand", [r["Company"] for r in result.rows])

    def test_a_clean_run_counts_none(self):
        self.assertEqual(pipeline(self.profile, self.parsed, [], TODAY).summary["unparsed_alert_entries"], 0)

    def test_the_prefilter_drops_and_counts_them_too(self):
        need = prefilter(self.profile, self.parsed + [self.hand_typed()], [], TODAY)
        self.assertEqual(need["unparsed_alert_entries"], 1)
        self.assertNotIn("Acme Typed By Hand", [c["company"] for c in need["fetch"]])
        self.assertEqual(prefilter(self.profile, self.parsed, [], TODAY)["unparsed_alert_entries"], 0)

    def test_the_funnel_takes_the_larger_count_so_a_re_added_entry_is_not_counted_twice(self):
        summary = {"already_seen": 0, "reject_reasons": {}, "rejected_jobs": 0, "unparsed_alert_entries": 1}
        _fold_in_prefilter(summary, {"unparsed_alert_entries": 1, "raw_in": 5})
        self.assertEqual(summary["unparsed_alert_entries"], 1)
        _fold_in_prefilter(summary, {"unparsed_alert_entries": 3, "raw_in": 5})
        self.assertEqual(summary["unparsed_alert_entries"], 3)

    def test_the_command_line_run_reports_the_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand = Path(tmp) / "c.json"
            cand.write_text(json.dumps(self.parsed + [self.hand_typed()]))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["run", "--candidates", str(cand), "--out", str(Path(tmp) / "out"), "--today", "2026-10-05"])
            self.assertEqual(code, 0)
            summary = json.loads((Path(tmp) / "out" / "summary.json").read_text())
            self.assertEqual(summary["unparsed_alert_entries"], 1)


class AlertJobsThroughThePipelineTests(unittest.TestCase):
    """An alert gives title, company and place only. The pipeline must still treat it fairly and honestly."""

    @classmethod
    def setUpClass(cls):
        cls.jobs, _ = parse_threads([fixture(n) for n in (
            "linkedin_digest_with_duplicates", "linkedin_digest_abroad_and_dubai", "linkedin_digest_four_jobs")])
        cls.profile = load_profile(overrides={"languages_flag_only": [], "needs_visa_sponsorship": False})

    def evaluation(self, company):
        job = next(j for j in self.jobs if j["company"] == company)
        return evaluate(copy.deepcopy(job), self.profile, TODAY)

    def test_a_clear_title_match_with_no_description_is_shortlisted_to_check(self):
        e = self.evaluation("MINIMALIST")  # "Social Media Manager"
        self.assertEqual(e.status, "shortlisted")
        self.assertFalse(e.strong)
        for flag in ("no_jd", "no_date", "pay_unlisted"):
            self.assertIn(flag, e.flags)
        self.assertEqual(e.tier, "U")

    def test_a_social_media_and_digital_marketing_title_counts_as_a_social_media_title(self):
        e = self.evaluation("Lenovo")  # "Social Media & Digital Marketing Manager, Motorola META"
        self.assertEqual(e.components["title"], 24)
        self.assertEqual(e.status, "shortlisted")

    def test_a_job_in_another_country_is_screened_out(self):
        e = self.evaluation("Futu Holdings Limited")  # location Riyadh
        self.assertEqual(e.status, "rejected")
        self.assertEqual(e.reject_reasons, ["location:riyadh"])

    def test_another_emirate_is_flagged_not_rejected(self):
        e = self.evaluation("NNC")  # Sharjah
        self.assertIn("outside_dubai:sharjah", e.flags)
        self.assertNotIn("location:sharjah", e.reject_reasons)

    def test_off_target_titles_stay_below_the_bar(self):
        for company in ("DEAL Holdings", "Clipster", "TikTok"):
            self.assertEqual(self.evaluation(company).status, "below_threshold", company)

    def test_a_hidden_employer_is_marked_down(self):
        e = self.evaluation("Confidential")
        self.assertIn("employer_hidden", e.flags)
        self.assertEqual(e.status, "below_threshold")

    def test_the_whole_pipeline_is_idempotent_for_alert_jobs(self):
        first = pipeline(self.profile, copy.deepcopy(self.jobs), [], TODAY)
        again = pipeline(self.profile, copy.deepcopy(self.jobs), first.rows, TODAY)
        self.assertGreater(first.summary["new_shortlisted"], 0)
        self.assertEqual(again.summary["new_shortlisted"], 0)
        # Only shortlisted jobs are stored, so those are exactly the ones seen again.
        self.assertEqual(again.summary["already_seen"], first.summary["new_shortlisted"])
        self.assertEqual(first.summary["tracker_hash"], again.summary["tracker_hash"])


if __name__ == "__main__":
    unittest.main()
