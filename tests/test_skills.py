"""Keep the loop-engineering skills loadable and true to the docs they were written from."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_skills  # noqa: E402

SKILLS = ROOT / ".claude" / "skills"
LOOP_SKILLS = ["loop-engineering", "verify-work", "goal-loop", "time-loop", "proactive-loop"]


def read(name, file="SKILL.md"):
    return (SKILLS / name / file).read_text(encoding="utf-8")


class ValidatorTests(unittest.TestCase):
    def test_all_skills_pass(self):
        _, problems = check_skills.check_all()
        self.assertEqual(problems, [])

    def test_validator_catches_broken_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad-skill"
            bad.mkdir()
            (bad / "SKILL.md").write_text(
                "---\nname: other\ndescripton: typo\n---\nno heading [x](missing.md) `ghost-loop`\n")
            _, problems = check_skills.check_all(Path(tmp))
        joined = "\n".join(problems)
        for expected in ("does not match its folder", "unknown field 'descripton'", "description missing",
                         "should start with a heading", "broken link to missing.md", "missing skill `ghost-loop`"):
            self.assertIn(expected, joined)

    def test_frontmatter_must_open_on_line_one(self):
        with self.assertRaises(ValueError):
            check_skills.parse_frontmatter("\n---\nname: x\n---\n")

    def test_listing_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "long-one"
            skill.mkdir()
            (skill / "SKILL.md").write_text(f"---\ndescription: {'x' * 1600}\n---\n# Long\n")
            _, problems = check_skills.check_all(Path(tmp))
        self.assertTrue(any("limit 1536" in p for p in problems), problems)


class ContentTests(unittest.TestCase):
    def test_all_five_skills_exist(self):
        for name in LOOP_SKILLS:
            self.assertTrue((SKILLS / name / "SKILL.md").is_file(), name)

    def test_router_covers_every_loop_and_tool_from_the_slides(self):
        text = read("loop-engineering")
        for phrase in ("Turn-based", "Goal-based", "Time-based", "Proactive", "the check", "the stop condition",
                       "the trigger", "the prompt", "`/goal`", "`/loop`", "`/schedule`"):
            self.assertIn(phrase, text)
        for skill in LOOP_SKILLS[1:]:
            self.assertIn(f"`{skill}`", text)

    def test_facts_from_the_docs_stay_correct(self):
        ref = read("loop-engineering", "reference.md")
        # /goal is a built-in command the evaluator of which only reads the transcript.
        self.assertIn("Only the user can type it", ref)
        self.assertIn("does not run commands or read files", ref)
        # Cloud tasks cannot run more often than hourly; /loop expires after 7 days.
        self.assertIn("Minimum interval is 1 hour", ref)
        self.assertIn("expire after 7 days", ref)
        self.assertIn("1 hour minimum", read("time-loop"))

    def test_every_loop_has_an_exit_and_forbids_gaming_it(self):
        self.assertIn("Every loop needs an exit", read("loop-engineering"))
        self.assertIn("Change the condition, the check, or the threshold", read("goal-loop"))
        self.assertIn("Weaken, skip, or delete a test", read("verify-work"))
        self.assertIn("never merges", read("proactive-loop"))
        self.assertIn("Exit", read("time-loop"))

    def test_claude_md_routes_to_the_skills(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        for skill in LOOP_SKILLS:
            self.assertIn(f"`{skill}`", text)


class InstallerTests(unittest.TestCase):
    def run_installer(self, home, *args):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(home))
        return subprocess.run(["bash", str(ROOT / "scripts" / "install_loop_skills.sh"), *args],
                              env=env, capture_output=True, text=True, check=True).stdout

    def test_installs_then_skips_then_forces(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.run_installer(home)
            for name in LOOP_SKILLS:
                self.assertEqual((home / "skills" / name / "SKILL.md").read_text(), read(name))
            (home / "skills" / "goal-loop" / "SKILL.md").write_text("mine")
            out = self.run_installer(home)
            self.assertIn("skip   goal-loop", out)
            self.assertEqual((home / "skills" / "goal-loop" / "SKILL.md").read_text(), "mine")
            self.run_installer(home, "--force")
            self.assertEqual((home / "skills" / "goal-loop" / "SKILL.md").read_text(), read("goal-loop"))


if __name__ == "__main__":
    unittest.main()
