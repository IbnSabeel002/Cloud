"""The coverage rules are what stops a hasty run from looking complete. Pin each verdict and each edge."""

import unittest

from jobhunt import coverage as cov


def row(source, ok=True, **extra):
    return {"source": source, "ok": ok, **extra}


def full_health(**overrides):
    rows = {
        "Settings": row("Settings", detail="loaded"),
        "Indeed connector": row("Indeed connector", detail="10 searches", hits_seen=94),
        "Tiny Fish pages": row("Tiny Fish pages", detail="3 pages"),
        "Bayt pages": row("Bayt pages", detail="2 of 30 usable"),
        "GulfTalent": row("GulfTalent", detail="4 snippets"),
        "Naukrigulf": row("Naukrigulf", detail="empty"),
        "Gmail alerts": row("Gmail alerts", detail="2 threads, 8 jobs"),
        "Other alerts": row("Other alerts", detail="0 threads, 0 jobs"),
    }
    rows.update(overrides)
    return list(rows.values())


class NamesTests(unittest.TestCase):
    def test_every_required_name_is_known_and_the_watchdog_keeps_its_original_five(self):
        self.assertEqual(len(cov.REQUIRED), 9)
        self.assertEqual(cov.WATCHDOG_NAMES, ("Settings", "Indeed connector", "Tiny Fish pages", "Gmail alerts", "Tracker write"))
        for name in cov.REQUIRED:
            self.assertEqual(cov.canonical(name), name)

    def test_case_spacing_ampersand_and_punctuation_do_not_matter(self):
        for variant, name in (("tiny fish pages", "Tiny Fish pages"), ("TINY-FISH_PAGES", "Tiny Fish pages"),
                              ("Indeed  Connector", "Indeed connector"), ("gulftalent", "GulfTalent"),
                              ("GulfTalent pages", "GulfTalent"), ("Naukri-gulf", "Naukrigulf"),
                              ("other alert", "Other alerts"), ("Bayt", "Bayt pages"), ("Bayt page", "Bayt pages")):
            self.assertEqual(cov.canonical(variant), name, variant)

    def test_unknown_names_stand_for_nothing(self):
        for name in ("Firecrawl", "", None, "GulfTalent and Naukrigulf", "Gmail drafts"):
            self.assertEqual(cov.canonical(name), "", name)

    def test_only_a_real_true_is_ok(self):
        self.assertTrue(cov.is_ok({"ok": True}))
        for bad in ("true", "false", 1, "yes", None):
            self.assertFalse(cov.is_ok({"ok": bad}), bad)
        self.assertFalse(cov.is_ok({}))


class FailureReasonTests(unittest.TestCase):
    def problem(self, **row_fields):
        return cov.failure_problem({"ok": False, **row_fields}, limit_seen=row_fields.pop("_limit", None))

    def test_each_allowed_reason_with_evidence_counts(self):
        for reason in ("tool_error", "tool_missing", "refused"):
            self.assertIsNone(cov.failure_problem({"reason": reason, "detail": "first line of the error"}), reason)

    def test_the_reason_is_normalised(self):
        for reason in ("Tool_Error", "tool error", "tool-error", " TOOL_ERROR "):
            self.assertIsNone(cov.failure_problem({"reason": reason, "detail": "x"}), reason)

    def test_no_reason_an_unknown_reason_or_no_evidence_does_not_count(self):
        self.assertEqual(cov.failure_problem({"detail": "x"}), "no reason was given")
        self.assertEqual(cov.failure_problem({"reason": "not needed today", "detail": "x"}), "the reason given is not an allowed one")
        self.assertEqual(cov.failure_problem({"reason": "tool_error", "detail": "  "}), "no evidence was given")

    def test_a_reason_that_is_not_required_may_be_left_out(self):
        self.assertIsNone(cov.failure_problem({"detail": "verify mismatch"}, reason_required=False))
        self.assertEqual(cov.failure_problem({"reason": "bogus", "detail": "x"}, reason_required=False), "the reason given is not an allowed one")

    def test_a_note_that_reads_like_an_excuse_is_not_evidence(self):
        for note in ("skipped to stay lean", "Skipped to keep the run short", "not needed today", "to save time",
                     "skip it, low yield", "kept it short"):
            self.assertIsNotNone(cov.failure_problem({"reason": "tool_error", "detail": note}), note)
        for note in ("Request timed out after 30s", "Rate limit exceeded for account. Try again in 39 seconds",
                     "short read: connection closed"):
            self.assertIsNone(cov.failure_problem({"reason": "tool_error", "detail": note}), note)

    def test_the_time_limit_needs_the_script_to_have_seen_forty_minutes(self):
        claim = {"reason": "time_limit", "detail": "past 40 minutes"}
        self.assertIn("never run", cov.failure_problem(claim, None))
        self.assertIn("only 3 of 40 minutes", cov.failure_problem(claim, 3.4))
        self.assertIn("only 39 of 40 minutes", cov.failure_problem(claim, 39.99))
        self.assertIsNone(cov.failure_problem(claim, 40))
        self.assertIsNone(cov.failure_problem(claim, 71.5))
        self.assertIn("never run", cov.failure_problem(claim, True))  # a bool is not a number of minutes
        self.assertIn("never run", cov.failure_problem(claim, "45"))

    def test_the_time_limit_is_not_needed_for_other_reasons(self):
        self.assertIsNone(cov.failure_problem({"reason": "tool_error", "detail": "e"}, None))


class RowCountTests(unittest.TestCase):
    def test_missing_and_duplicate_rows(self):
        health = full_health()
        self.assertEqual(cov.missing_rows(health, cov.BEFORE_PREFILTER), [])
        self.assertEqual(cov.missing_rows(health), ["Tracker write"])
        trimmed = [h for h in health if h["source"] not in ("Bayt pages", "Other alerts")]
        self.assertEqual(cov.missing_rows(trimmed, cov.BEFORE_PREFILTER), ["Bayt pages", "Other alerts"])
        self.assertEqual(cov.duplicate_rows(health + [row("bayt PAGES")]), ["Bayt pages"])
        self.assertEqual(cov.missing_rows(["junk", 3, None]), list(cov.REQUIRED))  # junk rows are ignored, not a crash

    def test_typed_entries_are_counted_per_row_by_the_scripts_own_labels(self):
        raw = {"indeed": 27, "indeed_page": 3, "careers": 4, "bayt": 2, "naukrigulf": 5, "linkedin_alert": 8, "other": 1,
               "indeed_alert": 2}
        self.assertEqual(cov.typed_count(raw, "Indeed connector"), 27)
        self.assertEqual(cov.typed_count(raw, "Tiny Fish pages"), 7)  # the Indeed pages and the watchlist pages
        self.assertEqual(cov.typed_count(raw, "Naukrigulf"), 5)
        self.assertEqual(cov.typed_count(raw, "Bayt pages"), 2)
        self.assertEqual(cov.typed_count(raw, "GulfTalent"), 0)
        self.assertEqual(cov.typed_count(raw, "Gmail alerts"), 8)
        self.assertEqual(cov.typed_count(raw, "Other alerts"), 3)
        self.assertIsNone(cov.typed_count(raw, "Settings"))
        self.assertIsNone(cov.typed_count(None, "Bayt pages"))  # no prefilter result: no count to give

    def test_unknown_source_labels_are_listed(self):
        self.assertEqual(cov.unknown_sources({"indeed": 3, "indeed_ae": 4, "Indeed": 1, "other": 0, "": 2}),
                         {"indeed_ae": 4, "Indeed": 1, "": 2})
        self.assertEqual(cov.unknown_sources(None), {})


class IndeedCoverageTests(unittest.TestCase):
    def test_hits_seen_must_be_a_plain_whole_number(self):
        self.assertEqual(cov.hits_seen({"hits_seen": 94}), 94)
        self.assertEqual(cov.hits_seen({"hits_seen": 0}), 0)
        for bad in (True, False, "94", "about 94", 94.0, -1, None, [94]):
            self.assertIsNone(cov.hits_seen({"hits_seen": bad}), bad)
        self.assertIsNone(cov.hits_seen({}))

    def test_the_failure_of_2026_10_07_is_caught(self):
        self.assertIn("only 27 of the 94", cov.indeed_problem({"ok": True, "hits_seen": 94}, 27))

    def test_the_boundary_is_eighty_percent_with_at_least_ten_results(self):
        ok = {"ok": True}
        self.assertIsNone(cov.indeed_problem({**ok, "hits_seen": 100}, 80))
        self.assertIsNotNone(cov.indeed_problem({**ok, "hits_seen": 100}, 79))
        self.assertIsNone(cov.indeed_problem({**ok, "hits_seen": 10}, 8))
        self.assertIsNotNone(cov.indeed_problem({**ok, "hits_seen": 10}, 7))
        self.assertIsNone(cov.indeed_problem({**ok, "hits_seen": 9}, 1))  # too few results to judge
        self.assertIsNone(cov.indeed_problem({**ok, "hits_seen": 94}, 94))

    def test_typing_every_row_including_duplicates_passes_and_typing_more_than_came_back_does_not(self):
        self.assertIsNone(cov.indeed_problem({"ok": True, "hits_seen": 94}, 94))
        self.assertIn("only 60 results were reported", cov.indeed_problem({"ok": True, "hits_seen": 60}, 94))

    def test_a_missing_count_on_a_working_connector_is_a_problem_but_not_on_a_failed_one(self):
        self.assertIn("hits_seen", cov.indeed_problem({"ok": True}, 30))
        self.assertIsNone(cov.indeed_problem({"ok": False, "reason": "tool_missing", "detail": "x"}, 0))

    def test_a_working_connector_that_returned_nothing_is_flagged(self):
        self.assertIn("returned nothing", cov.indeed_problem({"ok": True, "hits_seen": 0}, 0))
        self.assertIsNone(cov.indeed_problem({"ok": False, "hits_seen": 0}, 0))

    def test_the_check_also_runs_on_a_rate_limited_day(self):
        failed = {"ok": False, "reason": "tool_error", "detail": "rate limited", "hits_seen": 60}
        self.assertIn("only 10 of the 60", cov.indeed_problem(failed, 10))

    def test_no_script_count_means_no_check(self):
        self.assertIsNone(cov.indeed_problem({"ok": True, "hits_seen": 94}, None))


class AlertTests(unittest.TestCase):
    def test_mails_found_but_no_jobs_taken_is_a_gap(self):
        self.assertIn("3 alert mail(s)", cov.alert_problem({"detail": "3 threads, 0 jobs"}))
        self.assertIn("1 alert mail(s)", cov.alert_problem({"detail": "found 1 thread and took 0 jobs"}))

    def test_no_mails_or_some_jobs_is_fine(self):
        for detail in ("0 threads, 0 jobs", "2 threads, 8 jobs", "no alerts found (set up job alerts)", "", None):
            self.assertIsNone(cov.alert_problem({"detail": detail}), detail)


class GateTests(unittest.TestCase):
    def test_a_complete_honest_health_file_passes(self):
        self.assertEqual(cov.gate_problems(full_health()), [])

    def test_the_run_of_2026_10_07_would_have_been_stopped_before_the_prefilter(self):
        health = [row("Settings"), row("Indeed connector", detail="10 searches, 3 detail calls", hits_seen=94),
                  row("Tiny Fish pages", detail="3 Indeed UAE pages read"), row("Gmail alerts", detail="2 alerts, 8 jobs"),
                  row("Firecrawl", detail="1 page")]
        problems = cov.gate_problems(health)
        self.assertEqual(len(problems), 1)
        for name in ("Bayt pages", "GulfTalent", "Naukrigulf", "Other alerts"):
            self.assertIn(name, problems[0])
        self.assertIn("Bayt listings", problems[0])  # the message says what is missing in the owner's words
        self.assertNotIn("Tracker write", problems[0])  # that row only exists after section 8

    def test_a_failed_source_needs_an_allowed_reason_before_the_prefilter(self):
        health = full_health(**{"Bayt pages": row("Bayt pages", ok=False, detail="skipped to stay lean")})
        self.assertTrue(any("Bayt pages is marked failed but no reason was given" in p for p in cov.gate_problems(health)))
        fixed = full_health(**{"Bayt pages": row("Bayt pages", ok=False, reason="tool_error", detail="HTTP 403 from bayt.com")})
        self.assertEqual(cov.gate_problems(fixed), [])

    def test_settings_may_fail_without_a_reason_because_it_is_not_a_search_source(self):
        health = full_health(Settings=row("Settings", ok=False, detail="could not read the settings"))
        self.assertEqual(cov.gate_problems(health), [])

    def test_the_time_limit_excuse_is_checked_against_the_scripts_clock(self):
        health = full_health(Naukrigulf=row("Naukrigulf", ok=False, reason="time_limit", detail="past 40 minutes"))
        self.assertTrue(any("never run" in p for p in cov.gate_problems(health, None)))
        self.assertTrue(any("only 3 of 40" in p for p in cov.gate_problems(health, 3)))
        self.assertEqual(cov.gate_problems(health, 41), [])

    def test_ok_must_be_a_real_boolean(self):
        health = full_health(Settings={"source": "Settings", "ok": "false", "detail": "x"})
        self.assertTrue(any("Settings: ok must be true or false" in p for p in cov.gate_problems(health)))

    def test_a_working_indeed_row_needs_hits_seen_before_the_prefilter(self):
        health = full_health(**{"Indeed connector": row("Indeed connector", detail="10 searches")})
        self.assertTrue(any("hits_seen" in p for p in cov.gate_problems(health)))
        failed = full_health(**{"Indeed connector": row("Indeed connector", ok=False, reason="tool_missing",
                                                         detail="search_jobs does not exist even after ToolSearch")})
        self.assertEqual(cov.gate_problems(failed), [])

    def test_two_rows_for_one_source_are_refused(self):
        self.assertTrue(any("more than one row" in p for p in cov.gate_problems(full_health() + [row("bayt pages")])))

    def test_junk_in_the_file_is_a_message_not_a_crash(self):
        self.assertEqual(len(cov.gate_problems({"Settings": True})), 1)
        self.assertTrue(any("must be an object" in p for p in cov.gate_problems(full_health() + ["junk"])))
        self.assertIn("write a row", cov.gate_problems([])[0])


if __name__ == "__main__":
    unittest.main()
