#!/usr/bin/env python3
"""Check every skill under .claude/skills against the rules Claude Code enforces (and a few of ours).

Usage: python3 scripts/check_skills.py [skills_dir]
Exits 1 and lists every problem if any skill is broken.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".claude" / "skills"

# Fields Claude Code reads. Anything else is silently ignored, which usually means a typo.
KNOWN_FIELDS = {
    "name", "description", "when_to_use", "argument-hint", "arguments", "disable-model-invocation",
    "user-invocable", "allowed-tools", "disallowed-tools", "model", "effort", "context", "agent",
    "background", "hooks", "paths", "shell", "metadata", "license", "compatibility",
}
LISTING_LIMIT = 1536  # description + when_to_use are cut off here in the skill listing
MAX_LINES = 500
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def parse_frontmatter(text):
    """Return (fields, body). Fields are top-level `key: value` lines; values keep their quotes stripped."""
    if not text.startswith("---\n"):
        raise ValueError("frontmatter must start on line 1 with ---")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter has no closing ---")
    fields = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"bad frontmatter line: {line!r}")
        key = key.strip()
        if key in fields:
            raise ValueError(f"duplicate field: {key}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    return fields, text[end + 5:]


def check_skill(skill_dir, all_names):
    problems = []
    path = skill_dir / "SKILL.md"
    if not path.is_file():
        return [f"{skill_dir.name}: no SKILL.md"]
    text = path.read_text(encoding="utf-8")
    try:
        fields, body = parse_frontmatter(text)
    except ValueError as err:
        return [f"{skill_dir.name}: {err}"]

    name = fields.get("name", skill_dir.name)
    if name != skill_dir.name:
        problems.append(f"{skill_dir.name}: name {name!r} does not match its folder")
    if not NAME_RE.match(name):
        problems.append(f"{skill_dir.name}: name must be lowercase words joined by hyphens")
    for key in fields:
        if key not in KNOWN_FIELDS:
            problems.append(f"{skill_dir.name}: unknown field {key!r} (Claude Code ignores it)")
    description = fields.get("description", "")
    if len(description) < 40:
        problems.append(f"{skill_dir.name}: description missing or too short to trigger on")
    listing = len(description) + len(fields.get("when_to_use", ""))
    if listing > LISTING_LIMIT:
        problems.append(f"{skill_dir.name}: description + when_to_use is {listing} chars (limit {LISTING_LIMIT})")
    if len(text.splitlines()) > MAX_LINES:
        problems.append(f"{skill_dir.name}: SKILL.md is over {MAX_LINES} lines")
    if not body.strip().startswith("#"):
        problems.append(f"{skill_dir.name}: body should start with a heading")

    # Local markdown links must point at files that exist.
    for target in re.findall(r"\]\(([^)#\s]+)\)", body):
        if "://" not in target and not (skill_dir / target).exists():
            problems.append(f"{skill_dir.name}: broken link to {target}")
    # Backticked skill names that look like ours must exist.
    for ref in set(re.findall(r"`([a-z]+(?:-[a-z]+)+)`", body)):
        if ref.endswith(("-loop", "-work", "-engineering")) and ref not in all_names:
            problems.append(f"{skill_dir.name}: refers to missing skill `{ref}`")
    return problems


def check_all(skills_dir=SKILLS_DIR):
    dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    names = {p.name for p in dirs}
    problems = []
    for skill_dir in dirs:
        problems.extend(check_skill(skill_dir, names))
    return dirs, problems


def main(argv):
    skills_dir = Path(argv[1]) if len(argv) > 1 else SKILLS_DIR
    dirs, problems = check_all(skills_dir)
    for problem in problems:
        print(f"FAIL {problem}")
    print(f"{len(dirs)} skills checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
