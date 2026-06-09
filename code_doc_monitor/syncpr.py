"""C-01 — the doc-patch producer behind ``cdmon sync-pr`` (git-free, offline).

:func:`sync_pr` orchestrates AROUND an existing
:class:`~code_doc_monitor.monitor.Monitor` to answer one question: *"what would
healing the docs change?"* — and hands back a
deterministic unified diff (a patch) of exactly the changed documents. It is the
fully-testable, network-free core of the docs-PR flow; the bot that turns the patch
into a real merge request is C-03.

The flow is deliberately thin (no new heal/backend logic — that would duplicate the
pipeline and risk drift):

1. **Snapshot BEFORE** — each configured document's current text, or ``None`` when the
   file is missing.
2. **Heal in place** — ``monitor.run(apply=True)``. Because this is the SAME pipeline
   ``cdmon monitor --apply`` uses, B-02/B-03 region authority is honored automatically:
   a ``human`` (or locked ``llm-seeded``) region is never authored by the engine, so
   its body never appears in the patch.
3. **Read AFTER** — and for every document whose text changed, build a per-file
   ``difflib.unified_diff`` (deterministic, K10).
4. **dry_run restore (K1)** — if requested, put the document tree back byte-for-byte:
   rewrite each pre-existing doc to its before-text AND DELETE any file the run newly
   created (e.g. a ``MISSING_DOC`` stub). The patch is still returned; only the tree is
   reverted.

A clean repo (or a second run after an apply) heals nothing, so AFTER == BEFORE for
every doc and the patch is empty (idempotent, K7). Offline by default (the mock
backend, K4).
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict

from .config import MonitorConfig
from .monitor import Monitor

__all__ = ["SyncResult", "sync_pr", "should_sync"]


def _norm(path: str) -> str:
    """Normalize a repo-relative path to a comparable POSIX string (C-04, K10).

    Back-slashes become ``/`` and a leading ``./`` (and any ``.`` segments) are
    collapsed via :class:`PurePosixPath`, so ``./docs/x.md``, ``docs/x.md`` and
    ``docs\\x.md`` all compare equal to the managed doc path ``docs/x.md``.
    """
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def should_sync(changed_files: Iterable[str], config: MonitorConfig) -> bool:
    """Return ``True`` iff a heal/sync should run for this changed-file set (C-04).

    The structural loop-breaker: a bot doc-only commit (every changed file is a
    managed document path) returns ``False`` so the heal does NOT re-trigger and
    open another docs PR. ANY changed file outside the managed-doc set returns
    ``True`` (a real code change → proceed). An empty set returns ``False``
    (nothing to do). Pure, deterministic, read-only (K1/K10) — provider-agnostic:
    it only needs the changed-file list, however CI obtains it.
    """
    managed = {_norm(doc.path) for doc in config.documents}
    changed = [_norm(f) for f in changed_files]
    if not changed:
        return False
    return any(f not in managed for f in changed)


# Frozen + extra="forbid": a SyncResult is an immutable snapshot of one sync.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class SyncResult(BaseModel):
    """The outcome of one :func:`sync_pr`: the patch, the changed docs, a summary."""

    model_config = _MODEL_CONFIG

    patch: str  # concatenated per-file unified diffs ("" if nothing changed)
    changed_paths: tuple[
        str, ...
    ]  # repo-relative POSIX doc paths that changed (sorted)
    summary: str  # human one-liner ("N doc(s) updated" / "clean")


def _diff_one(path: str, before: str, after: str) -> str:
    """A deterministic unified diff for one document (``a/<path>`` → ``b/<path>``)."""
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "".join(lines)


def sync_pr(monitor: Monitor, *, dry_run: bool = False) -> SyncResult:
    """Heal the docs and return a unified-diff patch of exactly the changed docs.

    ``dry_run`` computes the same patch but restores the document tree to its
    starting bytes (K1) — including DELETING any file the run newly created.
    """
    specs = monitor.config.documents
    # Snapshot BEFORE: repo-relative POSIX path -> current text, or None if missing.
    before: dict[str, str | None] = {}
    doc_paths = {}
    for spec in specs:
        rel = spec.path
        doc_path = monitor.root / spec.path
        doc_paths[rel] = doc_path
        before[rel] = (
            doc_path.read_text(encoding="utf-8") if doc_path.is_file() else None
        )

    # Heal in place via the existing pipeline (honors B-02/B-03 authority, K5/K7).
    monitor.run(apply=True)

    diffs: list[str] = []
    changed: list[str] = []
    for rel in sorted(before):
        doc_path = doc_paths[rel]
        after_text = (
            doc_path.read_text(encoding="utf-8") if doc_path.is_file() else None
        )
        before_text = before[rel]
        if after_text == before_text:
            continue
        changed.append(rel)
        diffs.append(_diff_one(rel, before_text or "", after_text or ""))

    if dry_run:
        # Restore the tree byte-for-byte (K1): rewrite pre-existing docs to their
        # before-text and DELETE any file the run newly created.
        for rel in changed:
            doc_path = doc_paths[rel]
            before_text = before[rel]
            if before_text is None:
                if doc_path.is_file():
                    doc_path.unlink()
            else:
                doc_path.write_text(before_text, encoding="utf-8")

    patch = "".join(diffs)
    summary = "clean" if not changed else f"{len(changed)} doc(s) updated"
    return SyncResult(patch=patch, changed_paths=tuple(changed), summary=summary)
