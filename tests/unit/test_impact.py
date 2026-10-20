"""CIX-03 — the diff→docs surgical join (`codeindex.impact_report`).

A changed symbol reaches a doc two ways: the doc covers it (`direct`, the
docmap.symbol_owners join, file-level fallback for added/removed symbols),
or the doc covers one of its CALLERS (`via_callers`, one xref hop). No
xrefs artifact ⇒ `callers_available=False` — absence of data, never
absence of callers. Every file the diff MODIFIES is "caller data unknown":
its outgoing references are not in the stored xrefs.

Features: FEAT-CODEINDEX-002
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from custodex.codeindex import CodeIndex, build_code_index, impact_report
from custodex.config import Audience, CodeRef, DocumentSpec, MonitorConfig
from custodex.scip import XrefEdge, XrefSet

_LIB = '''"""Lib."""

def helper(x):
    """Helps."""
    return x

def unrelated():
    """Untouched."""
    return 0
'''

_MAIN = '''"""Main."""
from pkg.lib import helper

def caller():
    """Calls helper."""
    return helper(1)
'''


def _config() -> MonitorConfig:
    return MonitorConfig(
        documents=(
            DocumentSpec(
                id="lib-guide",
                path="docs/lib.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="pkg/lib.py"),),
            ),
            DocumentSpec(
                id="main-guide",
                path="docs/main.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="pkg/main.py"),),
            ),
        )
    )


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "lib.py").write_text(_LIB, encoding="utf-8")
    (tmp_path / "pkg" / "main.py").write_text(_MAIN, encoding="utf-8")
    return tmp_path


def _xrefs(pinned: CodeIndex | None = None) -> XrefSet:
    """The caller edge, input-pinned to ``pinned``'s content (None = a
    legacy artifact written before the pin existed)."""
    return XrefSet(
        generated_by="custodex/test",
        tool="scip-python/0.6.6",
        coverage={"python": "scip-python/0.6.6"},
        unmapped=0,
        edges=(
            XrefEdge(
                source="symbol pkg/main.py#caller",
                target="symbol pkg/lib.py#helper",
                count=1,
            ),
        ),
        input_digests=(
            None if pinned is None else {f.path: f.content_digest for f in pinned.files}
        ),
        input_languages=() if pinned is None else ("python",),
    )


def test_no_change_is_an_empty_report(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cfg = _config()
    idx = build_code_index(cfg, root, generated_by="t")
    report = impact_report(cfg, root, idx, idx, None)
    assert report.deltas == () and report.docs == ()
    assert report.callers_available is False


def test_signature_change_direct_and_via_callers(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cfg = _config()
    stored = build_code_index(cfg, root, generated_by="t")
    lib = root / "pkg" / "lib.py"
    lib.write_text(_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8")
    current = build_code_index(cfg, root, generated_by="t")

    report = impact_report(cfg, root, stored, current, _xrefs(stored))
    # the pin matches the baseline, but lib.py is EDITED: its outgoing
    # references are not in the stored xrefs, so its caller data is unknown
    assert report.callers_available is False
    assert report.callers_unknown == ("pkg/lib.py",)
    (delta,) = report.deltas
    assert delta.sigs_changed == ("helper",)
    by_id = {d.doc_id: d for d in report.docs}
    # lib-guide covers helper itself; main-guide covers its caller.
    assert by_id["lib-guide"].direct == ("symbol pkg/lib.py#helper",)
    assert by_id["lib-guide"].via_callers == ()
    assert by_id["main-guide"].direct == ()
    assert by_id["main-guide"].via_callers == ("symbol pkg/lib.py#helper",)


def test_without_xrefs_callers_are_honestly_unknown(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cfg = _config()
    stored = build_code_index(cfg, root, generated_by="t")
    lib = root / "pkg" / "lib.py"
    lib.write_text(_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8")
    current = build_code_index(cfg, root, generated_by="t")

    report = impact_report(cfg, root, stored, current, None)
    assert report.callers_available is False
    by_id = {d.doc_id: d for d in report.docs}
    assert list(by_id) == ["lib-guide"]  # main-guide invisible without xrefs
    assert by_id["lib-guide"].direct == ("symbol pkg/lib.py#helper",)


def test_removed_symbol_falls_back_to_the_file_join(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cfg = _config()
    stored = build_code_index(cfg, root, generated_by="t")
    (root / "pkg" / "lib.py").write_text(
        '"""Lib."""\n\ndef helper(x):\n    """Helps."""\n    return x\n', "utf-8"
    )  # `unrelated` deleted
    current = build_code_index(cfg, root, generated_by="t")

    report = impact_report(cfg, root, stored, current, None)
    (delta,) = report.deltas
    assert delta.symbols_removed == ("unrelated",)
    by_id = {d.doc_id: d for d in report.docs}
    # the removed symbol no longer exists in the owners join — the doc that
    # covers the FILE is still flagged (the honest fallback).
    assert by_id["lib-guide"].direct == ("symbol pkg/lib.py#unrelated",)


def test_report_is_deterministic(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cfg = _config()
    stored = build_code_index(cfg, root, generated_by="t")
    (root / "pkg" / "lib.py").write_text(_LIB + "\nNEW = 1\n", "utf-8")
    current = build_code_index(cfg, root, generated_by="t")
    a = impact_report(cfg, root, stored, current, _xrefs(stored))
    b = impact_report(cfg, root, stored, current, _xrefs(stored))
    assert a == b
    assert a.model_dump_json() == b.model_dump_json()


def test_surviving_private_change_yields_deltas_but_no_doc_impact(
    tmp_path: Path,
) -> None:
    """Adversarial-review pin: the file-level fallback is for added/removed
    symbols ONLY — a surviving private helper's body change must never
    fabricate direct doc impact (the docmap public-universe contract)."""
    root = _repo(tmp_path)
    cfg = _config()
    private = _LIB + "\n\ndef _hidden():\n    return 1\n"
    (root / "pkg" / "lib.py").write_text(private, "utf-8")
    stored = build_code_index(cfg, root, generated_by="t")
    (root / "pkg" / "lib.py").write_text(
        private.replace("def _hidden():\n    return 1", "def _hidden():\n    return 2"),
        "utf-8",
    )
    current = build_code_index(cfg, root, generated_by="t")
    report = impact_report(cfg, root, stored, current, None)
    (delta,) = report.deltas
    assert delta.bodies_changed == ("_hidden",)
    assert report.docs == ()  # deltas honest, doc join silent


_NEW = '''"""New."""
from pkg.lib import helper

def new_caller():
    """A caller the xrefs never saw."""
    return helper(2)
'''


def test_stale_xrefs_report_unknown_callers_not_absent_ones(tmp_path: Path) -> None:
    """The verified reproduction (critic 1.17): xrefs joined at T0; T1 adds
    pkg/new.py calling helper and refreshes ONLY the code index; T2 changes
    helper's signature. The caller edge from new.py is missing, so the doc
    covering it cannot appear — the report must SAY so: callers_available is
    False and callers_unknown names the file (never a silent "complete")."""
    # Feature: FEAT-CODEINDEX-002
    root = _repo(tmp_path)
    cfg = MonitorConfig(
        documents=(
            *_config().documents,
            DocumentSpec(
                id="new-guide",
                path="docs/new.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="pkg/new.py"),),
            ),
        )
    )
    t0 = build_code_index(cfg, root, generated_by="t")
    xrefs = _xrefs(t0)
    (root / "pkg" / "new.py").write_text(_NEW, encoding="utf-8")
    stored = build_code_index(cfg, root, generated_by="t")  # codeindex --write
    lib = root / "pkg" / "lib.py"
    lib.write_text(_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8")
    current = build_code_index(cfg, root, generated_by="t")

    report = impact_report(cfg, root, stored, current, xrefs)
    assert report.callers_available is False
    assert report.callers_unknown == ("pkg/lib.py", "pkg/new.py")
    by_id = {d.doc_id: d for d in report.docs}
    # the KNOWN caller still reaches its doc; the unknown one cannot
    assert by_id["main-guide"].via_callers == ("symbol pkg/lib.py#helper",)
    assert "new-guide" not in by_id


def test_unpinned_xrefs_are_never_reported_as_complete(tmp_path: Path) -> None:
    """A legacy artifact (no input pin) still contributes its edges, but its
    currency is unknowable — callers_available is False with no file list."""
    # Feature: FEAT-CODEINDEX-002
    root = _repo(tmp_path)
    cfg = _config()
    stored = build_code_index(cfg, root, generated_by="t")
    lib = root / "pkg" / "lib.py"
    lib.write_text(_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8")
    current = build_code_index(cfg, root, generated_by="t")

    report = impact_report(cfg, root, stored, current, _xrefs())
    assert report.callers_available is False
    assert report.callers_unknown == ()
    by_id = {d.doc_id: d for d in report.docs}
    assert by_id["main-guide"].via_callers == ("symbol pkg/lib.py#helper",)


# ------------------- every edited file is caller data unknown (xref round 6)

_HANDLERS_T0 = (
    "from pkg.lib import helper\n\n"
    'HANDLERS = {"alpha": len, "beta": len, "gamma": len, "delta": len, "eps": len}\n'
)
_HOOK_T0 = (
    "from pkg.lib import helper\n\n\nclass Plugin:\n"
    '    """Plugin."""\n\n    name = "p"\n\n\n'
    "DEFAULT_HOOK, FALLBACK_HOOK = helper, None\n"
)
_SHARED_T0 = "from pkg.lib import helper\n\nALPHA = 1; _beta = 2\n"
_TIE_T0 = "from pkg.lib import helper\n\n\nclass Plugin: _hooks = [\n    None,\n]\n"
_SHADOW_T0 = "from pkg.alt import helper\nALIAS = helper\nfrom pkg.lib import helper\n"
_PEP695_T0 = (
    "from pkg.lib import helper\n\n\ndef run[T: object](item: T) -> T:\n"
    "    return item\n"
)
_NEEDS_312 = pytest.mark.skipif(
    sys.version_info < (3, 12), reason="PEP 695 syntax needs Python 3.12+"
)


@pytest.mark.parametrize(
    ("what", "before", "after"),
    [
        pytest.param(
            "a function body edit (a symbol tier moves)",
            _MAIN,
            _MAIN.replace("helper(1)", "helper(1) + helper(2)"),
            id="a-function-body-edit-a-symbol-tier-moves",
        ),
        pytest.param(
            "a comment-only edit (no tier moves)",
            _MAIN,
            _MAIN + "# reviewed\n",
            id="a-comment-only-edit-no-tier-moves",
        ),
        pytest.param(
            "an elided value (HANDLERS = ...)",
            _HANDLERS_T0,
            _HANDLERS_T0.replace('"eps": len', '"eps": helper'),
            id="an-elided-value-handlers",
        ),
        pytest.param(
            "a statement indented into a class body",
            _HOOK_T0,
            _HOOK_T0.replace("\nDEFAULT_HOOK", "\n    DEFAULT_HOOK"),
            id="a-statement-indented-into-a-class-body",
        ),
        pytest.param(
            "a private assignment joined onto a public one",
            _SHARED_T0,
            _SHARED_T0.replace("_beta = 2", "_beta = helper"),
            id="a-private-assignment-joined-onto-a-public-one",
        ),
        pytest.param(
            "a class field continuing on its header's line",
            _TIE_T0,
            _TIE_T0.replace("    None,", "    helper,"),
            id="a-class-field-continuing-on-its-header-s-line",
        ),
        pytest.param(
            "a statement moved across a shadowing import",
            _SHADOW_T0,
            "from pkg.alt import helper\nfrom pkg.lib import helper\nALIAS = helper\n",
            id="a-statement-moved-across-a-shadowing-import",
        ),
        pytest.param(
            "a PEP 695 type-parameter bound of a function",
            _PEP695_T0,
            _PEP695_T0.replace("[T: object]", "[T: helper]"),
            id="a-pep-695-type-parameter-bound-of-a-function",
            marks=_NEEDS_312,
        ),
    ],
)
def test_every_modified_file_is_caller_data_unknown(
    tmp_path: Path, what: str, before: str, after: str
) -> None:
    """The stored xrefs were joined BEFORE the edit, so they cannot hold an
    edited file's current outgoing references — whatever the edit, and
    whether or not any symbol tier moved. Every file the diff modifies
    (content digest differs from the baseline) is therefore "caller data
    unknown", even when the pin holds it at the baseline: here the edited
    pkg/main.py and the edited pkg/lib.py (helper's signature). The earlier
    rule exempted edits a symbol tier "witnessed" and missed a new caller's
    doc wherever the line's owner was not the symbol whose tier moved — a
    class field continuing on its header's line, a statement moved across a
    shadowing import, a PEP 695 bound (the last three cases, each a
    reproduced silent under-report). Over-reporting an edit that adds no
    reference is the accepted cost."""
    # Feature: FEAT-CODEINDEX-002
    root = _repo(tmp_path)
    cfg = _config()
    main = root / "pkg" / "main.py"
    main.write_text(before, encoding="utf-8")
    stored = build_code_index(cfg, root, generated_by="t")
    main.write_text(after, encoding="utf-8")
    lib = root / "pkg" / "lib.py"
    lib.write_text(_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8")
    current = build_code_index(cfg, root, generated_by="t")

    report = impact_report(cfg, root, stored, current, _xrefs(stored))
    assert {d.path: d.status for d in report.deltas} == {
        "pkg/lib.py": "modified",
        "pkg/main.py": "modified",
    }, what
    assert "pkg/main.py" in report.callers_unknown, what
    assert report.callers_unknown == ("pkg/lib.py", "pkg/main.py"), what
    assert report.callers_available is False


def test_edits_outside_the_covered_languages_are_not_listed(
    tmp_path: Path,
) -> None:
    """The edited-file rule follows the pin's covered languages exactly as
    the baseline check does: an edit in a language no SCIP document joined
    is the ``coverage`` map's honesty, never an "unknown caller" entry."""
    # Feature: FEAT-CODEINDEX-002
    root = _repo(tmp_path)
    cfg = MonitorConfig(
        documents=_config().documents,
        coverage={"include": ("**/*.py", "**/*.sh"), "exclude": ()},
    )
    script = root / "run.sh"
    script.write_text("echo one\n", encoding="utf-8")
    stored = build_code_index(cfg, root, generated_by="t")
    script.write_text("echo two\n", encoding="utf-8")
    current = build_code_index(cfg, root, generated_by="t")
    pinned = _xrefs(stored).model_copy(
        update={
            "input_digests": {
                f.path: f.content_digest for f in stored.files if f.language == "python"
            }
        }
    )
    report = impact_report(cfg, root, stored, current, pinned)
    assert [d.path for d in report.deltas] == ["run.sh"]
    assert report.callers_unknown == ()
    assert report.callers_available is True


def test_added_and_removed_files_are_not_edits(tmp_path: Path) -> None:
    """Only a MODIFIED file is an edit the stored xrefs cannot see. An added
    file can source edges only from its own symbols, every one of them in
    ``symbols_added``, so the doc covering such a caller is already
    ``direct`` through the same owners join; a removed file's symbols are
    in no current doc's coverage, so its stale edges reach no doc. Neither
    is listed; the edited pkg/lib.py is."""
    # Feature: FEAT-CODEINDEX-002
    root = _repo(tmp_path)
    cfg = MonitorConfig(
        documents=(
            *_config().documents,
            DocumentSpec(
                id="new-guide",
                path="docs/new.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="pkg/new.py"),),
            ),
        )
    )
    old = root / "pkg" / "old.py"
    old.write_text("class Legacy:\n    pass\n", encoding="utf-8")
    stored = build_code_index(cfg, root, generated_by="t")
    old.unlink()
    (root / "pkg" / "new.py").write_text(_NEW, encoding="utf-8")
    lib = root / "pkg" / "lib.py"
    lib.write_text(_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8")
    current = build_code_index(cfg, root, generated_by="t")

    report = impact_report(cfg, root, stored, current, _xrefs(stored))
    statuses = {d.path: d.status for d in report.deltas}
    assert statuses == {
        "pkg/lib.py": "modified",
        "pkg/new.py": "added",
        "pkg/old.py": "removed",
    }
    assert report.callers_unknown == ("pkg/lib.py",)
    assert report.callers_available is False
    by_id = {d.doc_id: d for d in report.docs}
    assert by_id["new-guide"].direct == ("symbol pkg/new.py#new_caller",)
