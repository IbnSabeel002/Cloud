"""Make "read the playbook" something the code can check.

A long-lived worker session was told to follow PLAYBOOK.md and did not read it: it ran from its memory of an
older version and skipped the settings, the Slack step and the rate-limit rule. A prompt cannot make a model
read a file, so the file is served in numbered chunks by this module. Each chunk read is written to a receipt,
and `prefilter`, `run` and `report` refuse to work until every chunk of the current playbook has been read.
The digest carries the playbook's commit and checksum, so a run that skipped it is visible.

This is a guard against skipping, not against lying: someone determined to bypass it can set the bypass
variable, which the playbook forbids.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

CHUNK_CHARS = 7500
RECEIPT_MAX_AGE_SECONDS = 12 * 3600
SKIP_ENV = "JOBHUNT_SKIP_PLAYBOOK_GATE"  # the tests set it; a run must never
RECEIPT_ENV = "JOBHUNT_RECEIPT"
DEFAULT_RECEIPT = "/tmp/jobhunt-playbook-receipt.json"  # outside $RUN, so the bootstrap's rm -rf cannot delete it
END_MARK = "=== END OF PLAYBOOK ==="


def playbook_path() -> Path:
    return Path(__file__).resolve().parents[1] / "PLAYBOOK.md"


def receipt_path() -> Path:
    return Path(os.environ.get(RECEIPT_ENV) or DEFAULT_RECEIPT)


def gate_disabled() -> bool:
    return bool(os.environ.get(SKIP_ENV))


def _text() -> str:
    return playbook_path().read_text(encoding="utf-8")


def sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def commit_short() -> str:
    """Short commit of the checkout this playbook came from, or 'nogit'."""
    try:
        out = subprocess.run(["git", "-C", str(playbook_path().parent), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "nogit"
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def split_chunks(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Pieces of at most `limit` characters, cut on line boundaries (a longer single line is cut by characters)."""
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit and current:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


def _load_receipt() -> dict:
    try:
        data = json.loads(receipt_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_receipt(data: dict) -> None:
    path = receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def read_chunk(n: int, now: float | None = None) -> str:
    """The text of chunk `n` (1-based), with a footer. Records the read. Raises ValueError for a bad number."""
    text = _text()
    chunks = split_chunks(text)
    total = len(chunks)
    if not 1 <= n <= total:
        raise ValueError(f"the playbook has {total} chunks; ask for 1 to {total}")
    now = time.time() if now is None else now
    sha = sha8(text)
    receipt = _load_receipt()
    if n == 1 or receipt.get("sha") != sha or receipt.get("total") != total:
        # `started` is the script's own clock for the run: reading chunk 1 is the worker's first mandatory command.
        # Re-reading chunk 1 later can only make the run look younger, which is the safe side.
        receipt = {"sha": sha, "total": total, "read": [], "commit": commit_short(), "at": now, "started": now}
    receipt["read"] = sorted(set(receipt.get("read", [])) | {n})
    receipt["at"] = now
    _save_receipt(receipt)
    footer = f"--- chunk {n} of {total} | playbook @{receipt['commit']} sha256:{sha} | "
    footer += f"next: --chunk {n + 1}" if n < total else END_MARK
    return chunks[n - 1].rstrip("\n") + "\n" + footer


def section(n: int) -> str:
    """The block that starts at '## N.' and runs to the next '## ' heading. Does not touch the receipt."""
    text = _text()
    match = re.search(rf"^## {n}\. .*?(?=^## \d+\. |\Z)", text, re.M | re.S)
    if not match:
        raise ValueError(f"the playbook has no section {n}")
    return match.group(0).rstrip("\n")


def status(now: float | None = None) -> tuple[bool, str, list[int]]:
    """(complete, one-line receipt, missing chunk numbers)."""
    now = time.time() if now is None else now
    text = _text()
    total = len(split_chunks(text))
    sha = sha8(text)
    receipt = _load_receipt()
    if receipt.get("sha") != sha or receipt.get("total") != total:
        return False, "PLAYBOOK NOT FULLY READ (no receipt for this version)", list(range(1, total + 1))
    read = set(receipt.get("read", []))
    missing = [i for i in range(1, total + 1) if i not in read]
    if missing:
        return False, f"PLAYBOOK NOT FULLY READ (missing chunks {','.join(map(str, missing))})", missing
    if now - float(receipt.get("at", 0)) > RECEIPT_MAX_AGE_SECONDS:
        return False, "PLAYBOOK RECEIPT IS OLD (read it again from chunk 1)", list(range(1, total + 1))
    return True, f"Playbook @{receipt.get('commit', 'nogit')} sha:{sha} read {total}/{total}", []


def elapsed_minutes(now: float | None = None) -> float | None:
    """Minutes since this run read chunk 1, by the script's clock. None when there is no usable start (nothing to trust)."""
    try:
        started = float(_load_receipt()["started"])
    except (KeyError, TypeError, ValueError):
        return None
    now = time.time() if now is None else now
    return max(0.0, (now - started) / 60)


def note_elapsed(now: float | None = None) -> float | None:
    """Print-time helper for `elapsed`: the minutes so far, remembered as the largest the script has ever said in this run.

    A worker that cites the time limit as the reason it skipped a source must have asked for this number, and the
    number must have reached 40. The receipt (and so this memory) starts afresh with every chunk-1 read.
    """
    minutes = elapsed_minutes(now)
    if minutes is None:
        return None
    receipt = _load_receipt()
    receipt["limit_seen"] = max(float(receipt.get("limit_seen") or 0), minutes)
    _save_receipt(receipt)
    return minutes


def limit_seen_minutes() -> float | None:
    """The largest elapsed time `elapsed` has printed in this run, or None if it was never asked."""
    try:
        return float(_load_receipt()["limit_seen"])
    except (KeyError, TypeError, ValueError):
        return None


def receipt_line(now: float | None = None) -> str | None:
    """The line the digest shows, or None when there is no complete receipt."""
    ok, line, _ = status(now)
    return line if ok else None


def gate(now: float | None = None) -> str | None:
    """None if the command may proceed, else the message to print. Disabled by the bypass variable."""
    if gate_disabled():
        return None
    ok, line, missing = status(now)
    if ok:
        return None
    first = missing[0] if missing else 1
    return f"{line}. Read it first: python3 -m jobhunt playbook --chunk {first} (and on to the last chunk)."
