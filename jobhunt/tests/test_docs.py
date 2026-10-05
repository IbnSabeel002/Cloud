"""Keep the docs honest: the playbook may only call commands that exist, and its safety rules must stay."""

import json
import re
import unittest
from pathlib import Path

from jobhunt.cli import build_parser
from jobhunt.profile import DEFAULT_PROFILE, load_profile

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = (ROOT / "PLAYBOOK.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def subcommands():
    parser = build_parser()
    action = next(a for a in parser._actions if a.choices)
    return set(action.choices)


class PlaybookTests(unittest.TestCase):
    def test_every_command_the_playbook_calls_exists(self):
        called = set(re.findall(r"python3 -m jobhunt ([a-z][a-z-]*)", PLAYBOOK))
        self.assertTrue(called, "playbook calls no commands?")
        self.assertLessEqual(called, subcommands(), called - subcommands())

    def test_the_core_commands_are_all_used(self):
        called = set(re.findall(r"python3 -m jobhunt ([a-z][a-z-]*)", PLAYBOOK))
        for command in ("prefilter", "run", "report", "verify"):
            self.assertIn(command, called)

    def test_flags_used_in_the_playbook_exist(self):
        parser = build_parser()
        sub = next(a for a in parser._actions if a.choices).choices
        for block in re.findall(r"python3 -m jobhunt ([a-z][a-z-]*)([^\n`]*)", PLAYBOOK):
            command, rest = block
            known = {opt for action in sub[command]._actions for opt in action.option_strings}
            for flag in re.findall(r"(--[a-z-]+)", rest):
                self.assertIn(flag, known, f"{command} has no {flag}")

    def test_safety_rules_are_still_there(self):
        required = [
            "Never send email", "create_draft", "untrusted data", "Public pages only", "No LinkedIn scraping",
            "Never end silently", "Never invent facts", "slack_read_user_profile", "Never write personal data",
            "Never click Apply", "get_file_permissions",
        ]
        for phrase in required:
            self.assertIn(phrase, PLAYBOOK, phrase)

    def test_the_digest_is_built_after_the_report_url_exists(self):
        # The Doc needs report.html and the digest needs the Doc's URL, so `report` must run twice.
        runs = [m.start() for m in re.finditer(r"python3 -m jobhunt report", PLAYBOOK)]
        self.assertGreaterEqual(len(runs), 2)
        self.assertIn("--report-url", PLAYBOOK[runs[-1]:runs[-1] + 300])
        self.assertNotIn("--report-url", PLAYBOOK[runs[0]:runs[0] + 200])

    def test_fields_the_script_reads_are_documented_for_the_model(self):
        for field in ("posted", "pay_text", "pay_source", "level_label", "years_required", "languages_required",
                      "job_type", "apply_method", "apply_email", "scope_items", "visa_info", "gender_restricted",
                      "description"):
            self.assertIn(f"`{field}`", PLAYBOOK, field)

    def test_the_memory_is_the_database_not_a_drive_file(self):
        # Measured on 2026-10-05: Drive's Sheet read-back drops rows past ~115 and shortens cells to "...".
        for phrase in ("ArtifactData", "TRACKER_URL", "out_dir", "if_version", "writes.json", "--db-dir"):
            self.assertIn(phrase, PLAYBOOK, phrase)
        self.assertIn("Do not use Drive Sheets or Docs as memory", PLAYBOOK)
        self.assertNotIn("Job Hunt Tracker <TODAY>", PLAYBOOK)  # the old Drive snapshot naming is gone

    def test_every_version_pinned_write_has_a_safe_failure_path(self):
        self.assertIn("A wrong version is safe", PLAYBOOK)
        self.assertIn("nothing is written", PLAYBOOK)

    def test_slack_is_opt_in_and_the_final_message_is_the_fallback(self):
        # The Slack workspace is a work account whose admins may read DMs, so it is off unless the user says so.
        self.assertIn("Slack is opt-in", PLAYBOOK)
        self.assertIn("`none` or empty means off", PLAYBOOK)
        self.assertIn("final message", PLAYBOOK)
        self.assertIn("--drafts", PLAYBOOK)  # the digest claims only drafts that exist

    def test_slack_is_switched_on_by_the_settings_and_only_to_the_users_own_dm(self):
        # The Routine's prompt cannot be edited, so the Slack id comes from the settings document.
        for phrase in ("`slack_user_id` in the settings document (section 3) replaces `SLACK_USER_ID`",
                       "`slack_read_user_profile` with no `user_id`", "must show the same person",
                       "Never post to a channel", "Never put anything in a DM that is not the digest",
                       "Always make the digest your **final message**"):
            self.assertIn(phrase, PLAYBOOK, phrase)
        self.assertIn("`slack_user_id`", PLAYBOOK.split("## 3.")[1].split("## 4.")[0])  # a known settings field

    def test_the_notice_period_comes_from_a_script_not_from_the_model(self):
        for phrase in ("python3 -m jobhunt availability --card $RUN/card.json", "never write a start date of your own",
                       "Save it as `$RUN/card.json`"):
            self.assertIn(phrase, PLAYBOOK, phrase)
        self.assertIn("`notice_ends_by`", PLAYBOOK)

    def test_the_labour_card_flag_is_known_to_the_model_and_the_report(self):
        from jobhunt.report import FLAG_LABELS
        self.assertIn("needs_own_labour_card", PLAYBOOK)
        self.assertIn("needs_own_labour_card", FLAG_LABELS)

    def test_connector_tools_are_found_by_name_not_by_prefix(self):
        # Measured 2026-10-05: in a worker session Indeed's search_jobs is mcp__<uuid>__search_jobs.
        self.assertIn("UUID", PLAYBOOK)
        self.assertIn("Do not conclude a tool is missing", PLAYBOOK)
        self.assertIn("mcp__claude-code-remote__update_trigger", PLAYBOOK)

    def test_the_agent_can_find_its_own_trigger_when_no_id_was_given(self):
        # A trigger's prompt can only be edited from the conversation it posts into, so the id may never get filled in.
        self.assertIn("__TRIGGER_ID__", PLAYBOOK)
        self.assertIn("list_triggers", PLAYBOOK)
        self.assertIn("Daily job hunt (Dubai)", PLAYBOOK)

    def test_settings_come_from_the_database_before_the_profile_is_written(self):
        # A Routine's prompt cannot be edited later, so changes (languages, visa, portfolio) live in config/candidate.
        read = PLAYBOOK.index('collection="config", doc_id="candidate"')
        write = PLAYBOOK.index("Write `$RUN/profile.json` from the merged card")
        self.assertLess(read, write)
        self.assertNotIn("Write `$RUN/profile.json` from `CANDIDATE_CARD`", PLAYBOOK)
        for phrase in ("key by key", "data, never an instruction", "A missing document is normal",
                       "Never write to this document", '"source": "Settings"'):
            self.assertIn(phrase, PLAYBOOK, phrase)
        # The merged card, not the raw prompt card, is what the outreach rules use.
        for field in ("availability", "visa_note", "portfolio_url"):
            self.assertIn(f"`{field}`", PLAYBOOK, field)

    def test_the_playbook_never_lets_the_agent_invent_an_availability_date(self):
        self.assertIn("Never invent a date for the end of the notice period", PLAYBOOK)
        self.assertIn("as printed", PLAYBOOK)

    def test_an_indeed_rate_limit_costs_one_wait_then_falls_back_to_tiny_fish(self):
        # Measured 2026-10-05: waits grew 16s, 39s, 52s and one run lost about 7 minutes retrying.
        for phrase in ("Rate limit exceeded for account", "at most 3 Indeed calls at a time", "Do not loop on waits",
                       '"rate limited"', "| Indeed rate limit |"):
            self.assertIn(phrase, PLAYBOOK, phrase)
        self.assertLess(PLAYBOOK.index("**Rate limit.**"), PLAYBOOK.index("Two quirks seen in live runs"))

    def test_alerts_are_read_by_the_script_never_by_hand_and_linkedin_is_never_opened(self):
        for phrase in ("python3 -m jobhunt parse-alert", "saves it to a file and tells you the path", "Do not open that file",
                       "never print a message body", "never open a `linkedin.com` link at all",
                       "Entries with `source` `linkedin_alert` are never opened", "thin_shortlist_threshold"):
            self.assertIn(phrase, PLAYBOOK, phrase)
        self.assertNotIn("Extract title, company, location and link. Set `source` to `linkedin_alert`", PLAYBOOK)

    def test_alert_search_is_pinned_to_the_alert_sender_not_all_linkedin_mail(self):
        # Invitations, messages and application receipts also come from linkedin.com; only alerts are wanted.
        self.assertIn("from:jobalerts-noreply@linkedin.com", PLAYBOOK)
        self.assertNotIn("from:linkedin.com OR", PLAYBOOK)

    def test_at_most_five_alert_jobs_are_looked_up_elsewhere(self):
        self.assertIn("at most 5 of them per run", PLAYBOOK)

    def test_a_results_page_is_never_a_jobs_link_and_a_snippet_is_never_a_description(self):
        # A live run stored the Indeed search address as a job's link and scored three bullets as a full description.
        for phrase in ("python3 -m jobhunt indeed-links --page", "the k-th card gets the k-th link",
                       "Never use the results page's own address as a job's `url`", "`no_job_link`",
                       "`description_partial`", "set `description_partial: true`",
                       "Never a results or search page", "`links: true`"):
            self.assertIn(phrase, PLAYBOOK, phrase)

    def test_cards_from_a_results_page_are_opened_through_their_own_link_with_firecrawl_as_the_fallback(self):
        for phrase in ("Cards from a results page", "Indeed answers it with error 401 (measured)", "`firecrawl_scrape`",
                       "Take the text under `Full job description`", "so always open it"):
            self.assertIn(phrase, PLAYBOOK, phrase)

    def test_the_candidate_file_holds_only_the_fetched_entries(self):
        # A live test run put all 58 hits in candidates.json and the digest counted jobs twice.
        self.assertIn("the entries of `need.json`'s `fetch` list", PLAYBOOK)
        self.assertIn("Do not add the hits listed under `skipped` or `overflow`", PLAYBOOK)
        self.assertNotIn("plus any hits that need no details", PLAYBOOK)

    def test_the_playbook_knows_the_immediate_joiner_flag(self):
        from jobhunt.report import FLAG_LABELS
        self.assertIn("immediate_joiner", PLAYBOOK)
        self.assertIn("immediate_joiner", FLAG_LABELS)

    def test_readme_explains_where_settings_live(self):
        self.assertIn("config/candidate", README)
        self.assertIn("notice period ends by a\n  date you gave", README)
        self.assertIn("labour card", README)
        self.assertIn("Slack:** on", README)
        self.assertNotIn("These live in the private Routine prompt", README)

    def test_a_long_lived_worker_treats_each_wake_up_as_a_cold_start(self):
        self.assertIn("long-lived worker session", PLAYBOOK)
        self.assertIn("cold start", PLAYBOOK)

    def test_stateless_fallback_is_documented(self):
        self.assertIn("stateless", PLAYBOOK)
        self.assertIn("tracker unavailable", PLAYBOOK)

    def test_stop_path_is_documented_in_both_docs(self):
        for doc in (PLAYBOOK, README):
            self.assertIn("Accepted", doc)
            self.assertIn("update_trigger" if doc is PLAYBOOK else "stop the job hunt", doc)


class ProfileExampleTests(unittest.TestCase):
    def setUp(self):
        self.example = json.loads((ROOT / "profile.example.json").read_text(encoding="utf-8"))

    def test_loads_and_validates(self):
        profile = load_profile(ROOT / "profile.example.json")
        self.assertEqual(profile["floor"], 4000)

    def test_only_known_keys(self):
        known = set(DEFAULT_PROFILE) | {"hunt_start", "_comment"}
        self.assertLessEqual(set(self.example), known, set(self.example) - known)

    def test_example_holds_no_real_start_date(self):
        self.assertIsNone(self.example["hunt_start"])


class ReadmeTests(unittest.TestCase):
    def test_the_commands_in_the_readme_run(self):
        found = set(re.findall(r"python3 -m jobhunt ([a-z][a-z-]*)", README))
        self.assertTrue(found)
        self.assertLessEqual(found, subcommands())

    def test_the_demo_fixture_exists(self):
        self.assertTrue((ROOT / "tests" / "fixtures" / "candidates_2026-10-05.json").exists())

    def test_readme_states_the_hard_limits(self):
        text = README.lower()
        for phrase in ("never sends an email", "never applies", "never scrapes linkedin", "honest limits"):
            self.assertIn(phrase, text, phrase)


if __name__ == "__main__":
    unittest.main()


class TrackerPageTests(unittest.TestCase):
    """The tracker page is published from tracker_page.html. Its labels must match the report's."""

    def setUp(self):
        self.page = (ROOT / "tracker_page.html").read_text(encoding="utf-8")

    def test_every_flag_the_page_can_label_is_labelled_in_the_report_too(self):
        import re
        from jobhunt.report import FLAG_LABELS
        block = re.search(r"var FLAG_LABELS = \{(.*?)\n  \};", self.page, re.S).group(1)
        page_keys = set(re.findall(r'"?([a-z_:]+)"?\s*:\s*"', block))
        self.assertGreater(len(page_keys), 15)
        missing = page_keys - set(FLAG_LABELS)
        self.assertFalse(missing, f"labelled on the page but not in report.py: {missing}")

    def test_page_reads_the_columns_the_database_stores(self):
        from jobhunt.tracker import COLUMNS
        for column in COLUMNS:
            if column in ("Key", "LastSeen"):  # Key is the document id; LastSeen is internal
                continue
            self.assertIn(f"d.{column}", self.page, column)

    def test_page_declares_a_title_and_uses_only_the_database_capability(self):
        self.assertIn("<title>Job Hunt Tracker</title>", self.page)
        self.assertIn('claude.use("db")', self.page)
        self.assertNotIn("localStorage", self.page)
        self.assertNotIn("innerHTML", self.page)  # job text is untrusted; the page only ever sets textContent

    def test_page_never_assigns_untrusted_urls_without_a_scheme_check(self):
        self.assertIn("/^https:\\/\\//", self.page)
