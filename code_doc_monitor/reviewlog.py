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
from .schema import ReviewRecord

__all__ = ["append", "read_all", "summarize"]


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
