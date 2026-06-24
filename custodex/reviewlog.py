"""Append-only JSONL review log (K5, K8, K10).

Every handled drift is appended as one JSON line; existing lines are never
rewritten, so the log is an immutable audit trail a human can review (K5).
Reading parses each line back into a :class:`ReviewRecord`; a corrupt line is a
loud, typed :class:`SchemaError` rather than a silent skip (K8). :func:`summarize`
produces deterministic counts (K10).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from .errors import SchemaError
from .schema import ResolutionRecord, ReviewRecord, Verdict

__all__ = [
    "append",
    "read_all",
    "summarize",
    "select_by_verdict",
    "DEFAULT_RESOLUTIONS_PATH",
    "append_resolution",
    "read_resolutions",
    "resolved_index",
    "summarize_with_resolutions",
]

# Resolutions sit alongside the review log under `.cdmon/` (a separate file so the
# review log stays append-only/immutable — K5; the outcome is a new event, never an
# in-place mutation of a record).
DEFAULT_RESOLUTIONS_PATH = Path(".cdmon") / "resolutions.jsonl"


def append(path: Path, record: ReviewRecord) -> None:
    """Append one record as a JSON line, creating parent dirs/file if missing.

    Append-only (K5): the file is opened in append mode and existing lines are
    never read or rewritten.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json())
        fh.write("\n")


def read_all(path: Path) -> list[ReviewRecord]:
    """Parse every line of the log back into records (missing file -> ``[]``).

    A blank line is skipped; any non-empty line that fails to parse raises a
    :class:`SchemaError` naming the line number (K8).
    """
    if not path.is_file():
        return []
    records: list[ReviewRecord] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ReviewRecord.model_validate_json(line))
        except ValidationError as exc:
            raise SchemaError(
                f"Corrupt review-log line {lineno} in {path}: {exc}"
            ) from exc
    return records


def summarize(records: list[ReviewRecord]) -> dict:
    """Count records by verdict, audience, and doc id, plus a total.

    All grouping maps are sorted by key so the output is deterministic across
    runs (K10).
    """

    def _counts(values: list[str]) -> dict[str, int]:
        return dict(sorted(Counter(values).items()))

    return {
        "total": len(records),
        "by_verdict": _counts([r.verdict.value for r in records]),
        "by_audience": _counts([r.audience.value for r in records]),
        "by_doc_id": _counts([r.doc_id for r in records]),
    }


def select_by_verdict(
    records: list[ReviewRecord], verdict: Verdict
) -> list[ReviewRecord]:
    """Return the records with ``verdict``, preserving the log's append order.

    Aggregate counts (:func:`summarize`) tell a reviewer *how many* drifts a
    verdict covers; this surfaces *which* records they are — the audit detail
    needed to act on, e.g., the ``ESCALATE`` entries that need a human (K5).
    Pure and order-stable: the log is appended chronologically, so the returned
    slice is oldest-first and deterministic (K10).
    """
    return [r for r in records if r.verdict == verdict]


# --- D-01/D-02: resolutions (the human outcome, joined to reviews by FK) --------


def append_resolution(path: Path, record: ResolutionRecord) -> None:
    """Append one resolution as a JSON line, creating parent dirs/file if missing.

    Mirrors :func:`append` exactly — append-only (K5): the file is opened in append
    mode and existing lines are never read or rewritten. A record resolved twice is a
    SECOND line (a correction is a new event, not a mutation; the join applies
    last-write-wins, see :func:`resolved_index`).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json())
        fh.write("\n")


def read_resolutions(path: Path) -> list[ResolutionRecord]:
    """Parse every line of the resolutions log (missing file -> ``[]``).

    Mirrors :func:`read_all`: a blank line is skipped; any non-empty line that fails
    to parse raises a :class:`SchemaError` naming the line number (K8).
    """
    if not path.is_file():
        return []
    records: list[ResolutionRecord] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ResolutionRecord.model_validate_json(line))
        except ValidationError as exc:
            raise SchemaError(
                f"Corrupt resolutions-log line {lineno} in {path}: {exc}"
            ) from exc
    return records


def resolved_index(
    resolutions: list[ResolutionRecord],
) -> dict[str, ResolutionRecord]:
    """Map ``record_id -> ResolutionRecord``, LAST-WRITE-WINS.

    The resolutions log is append-only (K5), so a record resolved more than once has
    multiple lines; the join keeps the LAST appended one (the most recent human
    decision). Iterating in append (chronological) order and overwriting means the
    final entry per id wins — deterministic and order-stable (K10).
    """
    index: dict[str, ResolutionRecord] = {}
    for res in resolutions:
        index[res.record_id] = res
    return index


def summarize_with_resolutions(
    records: list[ReviewRecord], resolutions: list[ResolutionRecord]
) -> dict:
    """Join records↔resolutions: counts of resolved vs unresolved + by-resolution.

    A record is *resolved* iff its ``record_id`` appears in :func:`resolved_index`.
    Orphan resolutions (a ``record_id`` not in ``records``) are ignored so they cannot
    inflate the counts. ``by_resolution`` is sorted by key for determinism (K10).
    """
    index = resolved_index(resolutions)
    resolved = [r for r in records if r.record_id in index]
    by_resolution = Counter(index[r.record_id].resolution.value for r in resolved)
    return {
        "total": len(records),
        "resolved": len(resolved),
        "unresolved": len(records) - len(resolved),
        "by_resolution": dict(sorted(by_resolution.items())),
    }
