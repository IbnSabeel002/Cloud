"""The watchdog routine's prompt: one template in WATCHDOG.md, filled in with private values when the routine is made.

The values (tracker address, routine id, Slack id, dispatcher session) are never stored in git. They are checked for
shape before they go into a prompt, so a typo or a pasted sentence cannot change what the watchdog is told to do.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

BEGIN = "<!-- BEGIN WATCHDOG PROMPT -->"
END = "<!-- END WATCHDOG PROMPT -->"

# name -> pattern the value must match completely
PLACEHOLDERS = {
    "TRACKER_URL": r"https://claude\.ai/artifact/[A-Za-z0-9_-]+",
    "DAILY_TRIGGER_ID": r"trig_[A-Za-z0-9]+",
    "OWNER_SLACK_ID": r"U[A-Z0-9]{6,}",
    "DISPATCHER_SESSION": r"session_[A-Za-z0-9]+",
}


def watchdog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "WATCHDOG.md"


def template() -> str:
    """The prompt text between the markers, with the markdown fence around it removed."""
    text = watchdog_path().read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) > text.index(END):
        raise ValueError("WATCHDOG.md must hold exactly one BEGIN and one END marker, in that order")
    block = text.split(BEGIN, 1)[1].split(END, 1)[0].strip("\n")
    lines = block.splitlines()
    if not (lines and lines[0].startswith("````") and lines[-1].strip() == "````"):
        raise ValueError("the prompt must sit inside a four-backtick fence")
    return "\n".join(lines[1:-1]) + "\n"


# A test build fixes the date and the time window in the owner-written prompt. It is never switched on by anything the
# watchdog reads: a message from another session is not "typed by the user", and a model rightly ignores it.
TEST_FIELDS = {
    "date": r"20[0-9]{2}-[0-9]{2}-[0-9]{2}",
    "from": r"(?:[01][0-9]|2[0-3])[0-5][0-9]",
    "to": r"(?:[01][0-9]|2[0-3])[0-5][0-9]",
}
TEST_NOTE = (
    "TEST BUILD (written by the owner into this prompt, not by anything you read). TODAY is <TEST_DATE> instead of "
    "the date from step 0, FROM is <TEST_FROM> and TO is <TEST_TO>. STAMP is for TODAY: compute it with "
    "`TZ=Asia/Dubai date -d '<TEST_DATE>' '+%a %d %b %Y'`. Still run step 0's clock check, but skip its early-start "
    "rule. In step 2 still convert last_fired_at, but make a finding of it only if TODAY is today's date. Start line 1 "
    "of the final message with `(test) `, and add ` · window <TEST_FROM>-<TEST_TO>` to the OK line."
)


def render(values: dict, test: dict | None = None) -> str:
    """The prompt with private values filled in. `test` ({"date", "from", "to"}) makes a test build; None is production."""
    missing = [name for name in PLACEHOLDERS if not str(values.get(name) or "").strip()]
    if missing:
        raise ValueError("missing values: " + ", ".join(missing))
    unknown = sorted(set(values) - set(PLACEHOLDERS))
    if unknown:
        raise ValueError("unknown values: " + ", ".join(unknown))
    for name, pattern in PLACEHOLDERS.items():
        if not re.fullmatch(pattern, str(values[name])):
            raise ValueError(f"{name} does not look right")
    prompt = template()
    if prompt.count("<TEST_NOTE>\n") != 1:
        raise ValueError("the template must hold exactly one <TEST_NOTE> line")
    if test is None:
        prompt = prompt.replace("<TEST_NOTE>\n", "")
    else:
        if set(test) != set(TEST_FIELDS):
            raise ValueError("a test build needs exactly: date, from, to")
        for name, pattern in TEST_FIELDS.items():
            if not re.fullmatch(pattern, str(test[name])):
                raise ValueError(f"test {name} does not look right")
        date.fromisoformat(str(test["date"]))  # a real calendar day, not 2026-13-45
        if str(test["from"]) > str(test["to"]):
            raise ValueError("test from must not be after test to")
        note = TEST_NOTE
        for name in TEST_FIELDS:
            note = note.replace(f"<TEST_{name.upper()}>", str(test[name]))
        prompt = prompt.replace("<TEST_NOTE>\n", note + "\n")
    for name in PLACEHOLDERS:
        prompt = prompt.replace(f"<{name}>", str(values[name]))
    return prompt
