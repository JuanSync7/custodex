"""DOCUMENT_GAP advice names the doc whose code_ref already names the file.

Since COVLANG-DOCMAP the coverage join honours each ref's selectors, so a
public symbol a narrowed ref does NOT select is an undocumented gap even
though some doc's code_ref names its file. The next verb for that gap is
"widen that doc's selector", not ``cdx write-doc <file>`` (which would
register a second whole-file doc for a file that already has an owner).
``cdx write-doc`` stays the advice for a file no doc names.

Features: FEAT-WORKERS-001
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import (
    Audience,
    CodeRef,
    CoverageConfig,
    DocumentSpec,
    MonitorConfig,
)
from custodex.workers import SuggestionKind, suggest_docs_tick

_NOW = "2026-07-06T12:00:00+00:00"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _gaps(
    tmp_path: Path, *refs: CodeRef, c_refs: tuple[CodeRef, ...] = ()
) -> dict[str, str]:
    _write(
        tmp_path,
        "pkg/two.py",
        "def solve_widget(x):\n    return x\ndef tune_widget(y):\n    return y\n",
    )
    _write(tmp_path, "pkg/lone.py", "def lone_fn(z):\n    return z\n")
    _write(
        tmp_path,
        "docs/a.md",
        "# A\n\nCall `tune_widget`, `solve_widget` and `lone_fn`.\n",
    )
    _write(tmp_path, "docs/b.md", "# B\n\nRef.\n")
    _write(tmp_path, "docs/c.md", "# C\n\nRef.\n")
    docs = [
        DocumentSpec(id="a", path="docs/a.md", audience=Audience.USER_GUIDE),
        DocumentSpec(
            id="b", path="docs/b.md", audience=Audience.ENG_GUIDE, code_refs=refs
        ),
        DocumentSpec(
            id="c", path="docs/c.md", audience=Audience.ENG_GUIDE, code_refs=c_refs
        ),
    ]
    cfg = MonitorConfig(
        documents=tuple(docs), coverage=CoverageConfig(include=("**/*.py",), exclude=())
    )
    out = suggest_docs_tick(cfg, tmp_path, now=_NOW)
    return {s.target: s.detail for s in out if s.kind is SuggestionKind.DOCUMENT_GAP}


def test_an_unselected_symbol_in_a_named_file_advises_widening_the_selector(
    tmp_path: Path,
) -> None:
    gaps = _gaps(tmp_path, CodeRef(path="pkg/two.py", symbols=("solve_widget",)))
    detail = gaps["symbol pkg/two.py#tune_widget"]
    assert "cdx write-doc" not in detail
    assert "`b`" in detail and "tune_widget" in detail and "selector" in detail
    assert "`b` already names pkg/two.py" in detail


def test_a_file_no_doc_names_keeps_the_write_doc_advice(tmp_path: Path) -> None:
    gaps = _gaps(tmp_path, CodeRef(path="pkg/two.py", symbols=("solve_widget",)))
    assert "cdx write-doc pkg/lone.py" in gaps["symbol pkg/lone.py#lone_fn"]


def test_every_naming_doc_is_listed_sorted_and_the_path_is_normalized(
    tmp_path: Path,
) -> None:
    gaps = _gaps(
        tmp_path,
        CodeRef(path="./pkg/two.py", symbols=("solve_widget",)),
        c_refs=(CodeRef(path="pkg/two.py", lines=((1, 2),)),),
    )
    detail = gaps["symbol pkg/two.py#tune_widget"]
    assert "cdx write-doc" not in detail
    assert "`b`, `c` already name pkg/two.py" in detail
