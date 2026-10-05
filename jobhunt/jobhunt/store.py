"""Bridge between the tracker rows and the Artifact database (collection `jobs`).

Why a database and not a Drive file: the Drive connector cannot overwrite a file's content, and its
text read-back of a Sheet is lossy at scale (rows cut off past ~115, cells shortened to "..."). The
Artifact database stores one JSON document per job, reads back exactly, and can be written straight
from local files, so nothing is ever retyped.

Read:  ArtifactData list collection=jobs out_dir=DIR  ->  DIR/jobs/<job id>.json  ->  load_dir(DIR)
Write: plan_writes() -> one JSON file per changed document + a manifest of batches for ArtifactData batch.
"""

from __future__ import annotations

import json
from pathlib import Path

from .tracker import COLUMNS, _norm_cell, canonical_status

COLLECTION = "jobs"
BATCH_SIZE = 50  # ArtifactData accepts at most 50 writes per batch


def load_dir(path: str | Path, collection: str = COLLECTION) -> list[dict]:
    """Rows from `ArtifactData list ... out_dir=path`. Accepts DIR or DIR/<collection>."""
    base = Path(path)
    folder = base / collection if (base / collection).is_dir() else base
    rows = []
    for file in sorted(folder.glob("*.json")):
        doc = json.loads(file.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("data"), dict):  # tolerate the {"id","data","version"} envelope
            doc = doc["data"]
        if not isinstance(doc, dict):
            continue
        row = {col: ("" if doc.get(col) is None else str(doc[col])) for col in COLUMNS}
        row["Key"] = row["Key"] or file.stem
        row["Status"] = canonical_status(row["Status"])
        rows.append(row)
    return rows


def doc_from_row(row: dict) -> dict:
    """The document stored for a row. Score is a number so the page and queries can sort on it."""
    doc = {col: row.get(col, "") for col in COLUMNS}
    try:
        doc["Score"] = int(float(doc["Score"]))
    except (TypeError, ValueError):
        pass
    return doc


def _same(col: str, a, b) -> bool:
    return _norm_cell(col, a) == _norm_cell(col, b)


def plan_writes(before: list[dict], after: list[dict], out_dir: str | Path, collection: str = COLLECTION) -> dict:
    """Minimal writes that turn `before` into `after`.

    Creates need no version. Updates and deletes target a document that already exists, and the database
    requires the version you last read (`if_version`); those entries carry `"if_version": null` for the
    agent to fill from the listing it just read. A wrong version is safe: nothing is written.
    """
    out = Path(out_dir)
    folder = out / "writes"
    folder.mkdir(parents=True, exist_ok=True)
    before_by = {r["Key"]: r for r in before}
    after_by = {r["Key"]: r for r in after}
    entries: list[dict] = []

    def write_file(name: str, data: dict) -> str:
        path = folder / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(path.resolve())

    for key in sorted(after_by):
        row = after_by[key]
        if key not in before_by:
            entries.append({"op": "set", "collection": collection, "doc_id": key,
                            "file_path": write_file(f"set-{key}", doc_from_row(row))})
            continue
        changed = {c: row[c] for c in COLUMNS if not _same(c, row.get(c), before_by[key].get(c))}
        if changed:
            if "Score" in changed:
                changed["Score"] = doc_from_row(row)["Score"]
            entries.append({"op": "update", "collection": collection, "doc_id": key, "if_version": None,
                            "file_path": write_file(f"update-{key}", changed)})
    for key in sorted(set(before_by) - set(after_by)):
        entries.append({"op": "delete", "collection": collection, "doc_id": key, "if_version": None})

    batches = [entries[i:i + BATCH_SIZE] for i in range(0, len(entries), BATCH_SIZE)]
    manifest = {
        "counts": {op: sum(1 for e in entries if e["op"] == op) for op in ("set", "update", "delete")},
        "versions_needed": [e["doc_id"] for e in entries if e["op"] in ("update", "delete")],
        "batches": batches,
    }
    (out / "writes.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def run_doc(summary: dict, health: list[dict] | None, report_url: str | None, playbook: str | None = None) -> dict:
    """The document the tracker page shows as 'last run'. `playbook` is the receipt line of the playbook that ran."""
    doc = {
        "Date": summary["today"],
        "HuntDay": summary.get("hunt_day"),
        "NewShortlisted": summary["new_shortlisted"],
        "AlreadySeen": summary["already_seen"],
        "BelowThreshold": summary["below_threshold"],
        "Screened": summary["rejected_jobs"],
        "Health": health or [],
        "ReportUrl": report_url or "",
    }
    if playbook:
        doc["Playbook"] = playbook
    return doc
