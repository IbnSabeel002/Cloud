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
        self.assertIn("`SLACK_USER_ID` is `none`", PLAYBOOK)
        self.assertIn("final message", PLAYBOOK)
        self.assertIn("--drafts", PLAYBOOK)  # the digest claims only drafts that exist

    def test_connector_tools_are_found_by_name_not_by_prefix(self):
        # Measured 2026-10-05: in a worker session Indeed's search_jobs is mcp__<uuid>__search_jobs.
        self.assertIn("UUID", PLAYBOOK)
        self.assertIn("Do not conclude a tool is missing", PLAYBOOK)
        self.assertIn("mcp__claude-code-remote__update_trigger", PLAYBOOK)

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
