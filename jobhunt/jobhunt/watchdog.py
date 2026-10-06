"""The watchdog routine's prompt: one template in WATCHDOG.md, filled in with private values when the routine is made.

The values (tracker address, routine id, Slack id, dispatcher session) are never stored in git. They are checked for
shape before they go into a prompt, so a typo or a pasted sentence cannot change what the watchdog is told to do.
"""

from __future__ import annotations

import re
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


def render(values: dict) -> str:
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
    for name in PLACEHOLDERS:
        prompt = prompt.replace(f"<{name}>", str(values[name]))
    return prompt
