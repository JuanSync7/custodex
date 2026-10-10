"""Regression corpus — the coverage join agrees with the readers it shadows.

Lesson **[COVLANG-DOCMAP]**. ``docmap.symbol_owners`` (behind ``cdx deps
--suggest``, ``cdx graph``, ``cdx impact`` and the worker's DOCUMENT_GAP feed)
read every code_ref with the Python-only ``extract_file`` and ignored the
ref's selectors, so it silently disagreed with BOTH authoritative readers:

* the graded drift surface (``build_document_surface``), which routes a
  ``symbols`` ref through the extractor registry — a covered shell function
  was graded but never owned;
* ``coverage.resolve_coverage``, which applies ``extract._select`` to every
  ref whatever its ``extract`` kind — a narrowed ref claimed its whole file.

One guard per reader pair, and each carries selector-bearing inputs (a
no-selector guard proves agreement exactly where the bug cannot show):

* join == graded public surface for every ``symbols`` ref without
  ``arg_signature`` (which narrows a surface, not ownership);
* join == the public symbols ``resolve_coverage`` marks documented for every
  ref the Python inventory can see whose ``path`` is already in normal form,
  selector-bearing switches/records refs included. (``resolve_coverage``
  matches the RAW ``ref.path``, so a ``./``-prefixed ref diverges; that known
  limit is pinned in ``tests/unit/test_docmap_lang.py``.)

Every case asserts a NON-EMPTY owned set: a parity over zero items is a pass
that proves nothing.

See ``tests/regression/README.md`` for the case -> lesson map.

Features: FEAT-DOCMAP-004
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.config import Audience, CodeRef, DocumentSpec, MonitorConfig
from custodex.coverage import resolve_coverage
from custodex.docmap import symbol_owners
from custodex.extract import build_document_surface
from custodex.inventory import discover_files, discover_symbols

RUN_SH = (
    "#!/bin/sh\n"  # 1
    "deploy_app() {\n"  # 2
    "  echo deploy\n"  # 3
    "}\n"  # 4
    "rollback() {\n"  # 5
    "  echo back\n"  # 6
    "}\n"  # 7
    "_internal() {\n"  # 8
    "  echo hidden\n"  # 9
    "}\n"  # 10
)
BUILD_PY = (
    "MODE = 'fast'\n"  # 1
    "def p():\n"  # 2
    "    return 1\n"  # 3
    "def build_all():\n"  # 4
    "    return 2\n"  # 5
    "def tune(x, y):\n"  # 6
    "    return x\n"  # 7
    "class Cleaner:\n"  # 8
    "    def clean_all(self):\n"  # 9
    "        return 3\n"  # 10
    "def _helper():\n"  # 11
    "    return 4\n"  # 12
)


def _repo(root: Path) -> Path:
    for rel, text in (
        ("scripts/run.sh", RUN_SH),
        ("scripts/run.bash", RUN_SH),
        ("bin/deploy", RUN_SH),
        ("tools/shellish.py", RUN_SH),  # shell text behind a .py suffix
        ("tools/build.py", BUILD_PY),
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _doc(ref: CodeRef) -> DocumentSpec:
    return DocumentSpec(
        id="d", path="docs/d.md", audience=Audience.ENG_GUIDE, code_refs=(ref,)
    )


def _owned(doc: DocumentSpec, root: Path) -> set[str]:
    owners = symbol_owners(MonitorConfig(documents=(doc,)), root)
    return {k for k, v in owners.items() if "d" in v}


@pytest.mark.parametrize(
    "ref",
    [
        pytest.param(CodeRef(path="tools/build.py"), id="python-suffix"),
        pytest.param(CodeRef(path="scripts/run.sh"), id="sh-suffix"),
        pytest.param(CodeRef(path="scripts/run.bash"), id="bash-suffix"),
        pytest.param(CodeRef(path="bin/deploy", lang="shell"), id="explicit-lang"),
        pytest.param(
            CodeRef(path="tools/shellish.py", lang="shell"),
            id="explicit-lang-over-mapped-suffix",
        ),
        pytest.param(
            CodeRef(path="scripts/run.sh", symbols=("rollback",)),
            id="sh-symbols-selector",
        ),
        pytest.param(
            CodeRef(path="scripts/run.sh", lines=((2, 4),)), id="sh-lines-selector"
        ),
        pytest.param(
            CodeRef(path="tools/build.py", symbols=("Cleaner",)),
            id="py-class-selector",
        ),
        pytest.param(
            CodeRef(path="tools/build.py", names=("MODE",)), id="py-names-selector"
        ),
    ],
)
def test_owners_join_matches_the_graded_surface(tmp_path: Path, ref: CodeRef) -> None:
    """The join owns exactly the graded surface's public symbols.

    Break-it: read the ref with ``extract_file`` (the shell cases go empty), or
    drop ``_select`` (the selector cases widen to the whole file).
    """
    root = _repo(tmp_path)
    doc = _doc(ref)
    graded = {
        f"symbol {ref.path}#{s.name}"
        for s in build_document_surface(doc, root).symbols
        if s.is_public
    }
    owned = _owned(doc, root)
    assert owned, "a parity over zero symbols proves nothing"
    assert owned == graded


@pytest.mark.parametrize(
    "ref",
    [
        pytest.param(CodeRef(path="tools/build.py"), id="whole-file"),
        pytest.param(
            CodeRef(path="tools/build.py", symbols=("build_all",)),
            id="symbols-selector",
        ),
        pytest.param(
            CodeRef(path="tools/build.py", lines=((6, 9),)), id="lines-selector"
        ),
        pytest.param(
            CodeRef(path="tools/build.py", names=("MODE",)), id="names-selector"
        ),
        pytest.param(
            CodeRef(path="tools/build.py", arg_signature=("x", "y")),
            id="arg-signature-only",
        ),
        pytest.param(
            CodeRef(path="tools/build.py", extract="records"), id="records-ref"
        ),
        pytest.param(
            CodeRef(path="tools/build.py", extract="switches"), id="switches-ref"
        ),
        pytest.param(
            CodeRef(path="tools/build.py", extract="switches", symbols=("build_all",)),
            id="switches-ref-with-symbols-selector",
        ),
        pytest.param(
            CodeRef(path="tools/build.py", extract="records", lines=((1, 1),)),
            id="records-ref-with-lines-selector",
        ),
    ],
)
def test_owners_join_matches_the_coverage_resolver(
    tmp_path: Path, ref: CodeRef
) -> None:
    """The join owns exactly the public symbols ``cdx coverage`` marks documented.

    Break-it: skip ``_select`` for non-symbols refs (the selector-bearing
    switches/records cases widen), apply ``arg_signature`` in the join, or keep
    private symbols (``_helper`` leaks).
    """
    root = _repo(tmp_path)
    doc = _doc(ref)
    report = resolve_coverage(
        MonitorConfig(documents=(doc,)),
        # The whole-repo default scope would trip on the shell-in-.py fixture
        # (an unparseable Python file is loud, K8); scope to the graded file.
        discover_symbols(discover_files(root, include=("tools/build.py",)), root),
    )
    documented = {
        f"symbol {s.path}#{s.name}"
        for s in report.symbols
        if s.is_public and "d" in s.owners
    }
    owned = _owned(doc, root)
    assert owned, "a parity over zero symbols proves nothing"
    assert owned == documented
