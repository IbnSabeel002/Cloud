"""The note the daily run keeps about its Slack message, so the watchdog can look for it.

The run record is written before the digest goes out, so this note is added to it afterwards. The model never types the
time. It passes what the Slack tool returned (a message link or a message timestamp); this module checks that it is
recent, turns it into a Dubai-time stamp, and writes the exact document the playbook then merges into the run record.

A run that did not send (or could not say) records a plain word instead of a time:
    off          Slack is switched off in the settings
    failed       the send failed twice
    unconfirmed  the send looked fine but the tool gave back nothing that proves it
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

DUBAI = timezone(timedelta(hours=4))  # no daylight saving in the UAE; the run ids use this clock
STATES = ("off", "failed", "unconfirmed")
MAX_AGE = timedelta(minutes=30)    # the digest goes out in the last minutes of a run, and this runs right after it
MAX_AHEAD = timedelta(minutes=2)   # allowance for the two clocks disagreeing a little

# https://<workspace>.slack.com/archives/<channel>/p<10 digits of seconds><6 digits of microseconds>[?query]
_LINK = re.compile(r"https://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.slack\.com/archives/[A-Z0-9]+/p(\d{10})(\d{6})(?:\?\S*)?")
_TS = re.compile(r"(\d{10})\.(\d{6})")


def message_time(ref: str) -> datetime:
    """When a Slack message was posted, from its link or its timestamp. Anything else is refused."""
    text = str(ref).strip().replace("\\/", "/")  # the send result is JSON, which may write slashes as \/
    match = _LINK.fullmatch(text) or _TS.fullmatch(text)
    if not match:
        raise ValueError(f"not a Slack message link or timestamp: {text[:60]!r}")
    seconds, micro = match.groups()
    return datetime.fromtimestamp(int(seconds) + int(micro) / 1_000_000, tz=timezone.utc)


def sent_doc(refs: list[str], now: datetime | None = None, expect: int | None = None) -> dict:
    """The run-record fields for a digest that went out. Every reference must be a recent message.

    `expect` is how many digest messages the run had to send; when given, exactly that many distinct messages must be named.
    """
    now = now or datetime.now(timezone.utc)
    if not refs:
        raise ValueError("no Slack message given")
    times = {}
    for ref in refs:
        posted = message_time(ref)
        if posted < now - MAX_AGE or posted > now + MAX_AHEAD:
            raise ValueError(f"that Slack message is not from the last {int(MAX_AGE.total_seconds() // 60)} minutes: "
                             f"{posted.astimezone(DUBAI):%Y-%m-%d %H:%M} Dubai time")
        times[str(ref).strip()] = posted
    distinct = len(set(times.values()))
    if expect is not None and distinct != expect:
        raise ValueError(f"{distinct} different Slack message(s) given, but the run had {expect} digest message(s) to send")
    latest = max(times.values()).astimezone(DUBAI)
    return {"SlackSent": latest.strftime("%H:%M"), "SlackMessages": distinct}


def state_doc(state: str) -> dict:
    if state not in STATES:
        raise ValueError(f"state must be one of: {', '.join(STATES)}")
    return {"SlackSent": state, "SlackMessages": 0}
