"""CIX-03 — `cdx impact` end-to-end (offline, via CliRunner).

Features: FEAT-CODEINDEX-002
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from custodex.cli import app
from tests._scip import document, index, occurrence

runner = CliRunner()

_CODE = '''"""Mod."""

def doubler(x):
    """Double x."""
    return x * 2
'''


def _fixture(tmp_path: Path) -> None:
    (tmp_path / "code.py").write_text(_CODE, encoding="utf-8")
    (tmp_path / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "cdmon.yaml").write_text(
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "eng-guide"\n'
        "    code_refs:\n"
        '      - path: "code.py"\n',
        encoding="utf-8",
    )


def test_missing_index_is_loud(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["impact"])
    assert result.exit_code == 1
    assert "no stored code index" in result.output


def test_impact_happy_path_and_json(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0

    clean = runner.invoke(app, ["impact"])
    assert clean.exit_code == 0, clean.output
    assert "no impact" in clean.output

    (tmp_path / "code.py").write_text(
        _CODE.replace("def doubler(x)", "def doubler(x, y=1)"), encoding="utf-8"
    )
    result = runner.invoke(app, ["impact"])
    assert result.exit_code == 0, result.output
    assert "1 changed file(s), 1 changed symbol(s), 1 affected doc(s)" in result.output
    assert "doc guide:" in result.output
    assert "direct: symbol code.py#doubler" in result.output
    assert "caller impact unknown" in result.output  # no xrefs artifact

    as_json = runner.invoke(app, ["impact", "--json"])
    payload = json.loads(as_json.output)
    assert payload["callers_available"] is False
    assert payload["docs"] == [
        {
            "doc_id": "guide",
            "direct": ["symbol code.py#doubler"],
            "via_callers": [],
        }
    ]
    # the join writes nothing (K1): the stored artifact still has the OLD surface
    stored = json.loads(
        (tmp_path / ".cdmon" / "code-index.json").read_text(encoding="utf-8")
    )
    signatures = [s["signature"] for f in stored["files"] for s in f["symbols"]]
    assert signatures == ["def doubler(x)"]


# --------------------------------------------- stale xrefs (critic 1.17 repro)

_HELPER = "scip-python python pkg 0.1 `pkg.lib`/helper()."

_PKG_LIB = '''"""Lib."""


def helper(x):
    """Help."""
    return x
'''

_PKG_CALLER = '''from pkg.lib import helper


def {name}():
    """Calls helper."""
    return helper(1)
'''


def _pkg_config(tmp_path: Path, *, with_new: bool) -> None:
    docs = [("lib-doc", "lib"), ("main-doc", "main")]
    if with_new:
        docs.append(("new-doc", "new"))
    lines = ['version: "1.0.0"', 'root: "."', "documents:"]
    for doc_id, stem in docs:
        (tmp_path / "docs" / f"{stem}.md").write_text(f"# {stem}\n", "utf-8")
        lines += [
            f'  - id: "{doc_id}"',
            f'    path: "docs/{stem}.md"',
            '    audience: "eng-guide"',
            "    code_refs:",
            f'      - path: "pkg/{stem}.py"',
        ]
    (tmp_path / "cdmon.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pkg_scip(path: Path, callers: list[str], *, ref_line: int = 5) -> None:
    """Hand-encoded SCIP: every caller file references helper once (at
    0-based ``ref_line``), and pkg/lib.py + pkg/__init__.py have
    (reference-free) documents too."""
    docs = [document("pkg/__init__.py", []), document("pkg/lib.py", [])]
    docs += [
        document(f"pkg/{stem}.py", [occurrence(_HELPER, range_=[ref_line, 11, 17])])
        for stem in callers
    ]
    path.write_bytes(index(docs))


def test_stale_xrefs_say_caller_data_is_unknown(tmp_path: Path, monkeypatch) -> None:
    """End to end, the verified reproduction: xrefs built at T0, pkg/new.py
    (a new helper caller) added and ONLY the code index refreshed, then
    helper's signature changed. `cdx impact` cannot list new-doc — and now
    it says why instead of reporting callers_available=True."""
    # Feature: FEAT-CODEINDEX-002
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text('"""Pkg."""\n', "utf-8")
    (tmp_path / "pkg" / "lib.py").write_text(_PKG_LIB, "utf-8")
    (tmp_path / "pkg" / "main.py").write_text(
        _PKG_CALLER.format(name="main_entry"), "utf-8"
    )
    _pkg_config(tmp_path, with_new=False)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    _pkg_scip(tmp_path / "t0.scip", ["main"])
    assert runner.invoke(app, ["scip", "t0.scip", "--write"]).exit_code == 0

    (tmp_path / "pkg" / "new.py").write_text(
        _PKG_CALLER.format(name="new_caller"), "utf-8"
    )
    _pkg_config(tmp_path, with_new=True)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    (tmp_path / "pkg" / "lib.py").write_text(
        _PKG_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8"
    )

    text = runner.invoke(app, ["impact"])
    assert text.exit_code == 0, text.output
    assert "doc main-doc:" in text.output  # the known caller still reaches
    assert "doc new-doc:" not in text.output
    # new.py (never joined) and lib.py (edited since the baseline)
    assert "caller data unknown for 2 file(s)" in text.output
    assert "pkg/new.py" in text.output

    payload = json.loads(runner.invoke(app, ["impact", "--json"]).output)
    assert payload["callers_available"] is False
    assert payload["callers_unknown"] == ["pkg/lib.py", "pkg/new.py"]

    # control: re-index the BASELINE (new.py now has a document), then make
    # the edit — the realistic "index, then edit" flow — and the missing doc
    # appears through its caller; only the edited lib.py stays unknown.
    (tmp_path / "pkg" / "lib.py").write_text(_PKG_LIB, "utf-8")
    _pkg_scip(tmp_path / "t1.scip", ["main", "new"])
    rejoin = runner.invoke(app, ["scip", "t1.scip", "--write"])
    assert rejoin.exit_code == 0, rejoin.output
    assert "STALE" not in rejoin.stderr  # the join ran on a current index
    (tmp_path / "pkg" / "lib.py").write_text(
        _PKG_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8"
    )
    fixed = json.loads(runner.invoke(app, ["impact", "--json"]).output)
    assert fixed["callers_available"] is False
    assert fixed["callers_unknown"] == ["pkg/lib.py"]
    assert "new-doc" in {d["doc_id"] for d in fixed["docs"]}
    current = runner.invoke(app, ["impact"]).stdout
    assert "doc new-doc:" in current
    assert "caller data unknown for 1 file(s)" in current
    assert "pkg/new.py" not in current.split("caller data unknown", 1)[1]
    assert "no xrefs" not in current


def test_unpinned_xrefs_say_currency_is_unknown(tmp_path: Path, monkeypatch) -> None:
    """An xrefs artifact written before the input pin existed still feeds
    via-callers, but `cdx impact` says its currency is unknown and reports
    callers_available=false — never a silent "complete"."""
    # Feature: FEAT-CODEINDEX-002
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    (tmp_path / ".cdmon" / "xrefs.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "generated_by": "custodex/old",
                "tool": "scip-python/0.6.6",
                "coverage": {"python": "scip-python/0.6.6"},
                "unmapped": 0,
                "edges": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "code.py").write_text(
        _CODE.replace("def doubler(x)", "def doubler(x, y=1)"), encoding="utf-8"
    )
    result = runner.invoke(app, ["impact"])
    assert result.exit_code == 0, result.output
    assert "no input pin" in result.output
    assert "do NOT run `cdx codeindex --write`" in result.output  # impact's remedy
    assert "no xrefs artifact" not in result.output
    payload = json.loads(runner.invoke(app, ["impact", "--json"]).output)
    assert payload["callers_available"] is False
    assert payload["callers_unknown"] == []


def test_a_join_against_a_stale_code_index_leaves_callers_unknown(
    tmp_path: Path, monkeypatch
) -> None:
    """Review scenario C end to end: the code index is written at T0,
    pkg/main.py is edited (its spans shift) WITHOUT re-indexing, and a fresh
    .scip is joined with `--write`. The stale spans drop main.py's edge, so
    the join must not vouch for main.py: after helper's signature changes,
    `cdx impact` — judging against that same stored index — reports
    callers_available=false with pkg/main.py in callers_unknown, and `cdx
    graph` agrees. Never a silent "complete" that loses main-doc."""
    # Feature: FEAT-CODEINDEX-002
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text('"""Pkg."""\n', "utf-8")
    (tmp_path / "pkg" / "lib.py").write_text(_PKG_LIB, "utf-8")
    main = tmp_path / "pkg" / "main.py"
    main.write_text(_PKG_CALLER.format(name="main_entry"), "utf-8")
    _pkg_config(tmp_path, with_new=False)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    main.write_text("# a\n# b\n# c\n# d\n" + main.read_text("utf-8"), "utf-8")
    _pkg_scip(tmp_path / "fresh.scip", ["main"], ref_line=9)

    joined = runner.invoke(app, ["scip", "fresh.scip", "--write"])
    assert joined.exit_code == 0, joined.output
    assert "STALE" in joined.stderr and "pkg/main.py" in joined.stderr
    again = runner.invoke(app, ["scip", "fresh.scip", "--write"])
    assert "unchanged" in again.stdout  # identical inputs: a no-op (K7)

    (tmp_path / "pkg" / "lib.py").write_text(
        _PKG_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8"
    )
    text = runner.invoke(app, ["impact"])
    assert text.exit_code == 0, text.output
    assert "doc main-doc:" not in text.output  # the dropped edge…
    assert "caller data unknown for 2 file(s)" in text.output  # …is SAID
    assert "pkg/main.py" in text.output
    payload = json.loads(runner.invoke(app, ["impact", "--json"]).output)
    assert payload["callers_available"] is False
    assert payload["callers_unknown"] == ["pkg/lib.py", "pkg/main.py"]

    focus = runner.invoke(app, ["graph", "--focus", "symbol pkg/lib.py#helper"])
    assert "caller data unknown" in focus.stdout and "pkg/main.py" in focus.stdout


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
_TIE_T0 = "from pkg.lib import helper\n\n\nclass Plugin: _hooks = [\n    None,\n]\n"
_SHADOW_T0 = "from pkg.alt import helper\nALIAS = helper\nfrom pkg.lib import helper\n"
_PEP695_T0 = (
    "from pkg.lib import helper\n\n\ndef run[T: object](item: T) -> T:\n"
    "    return item\n"
)


@pytest.mark.parametrize(
    ("what", "before", "after"),
    [
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
            "from pkg.lib import helper\n\nALPHA = 1; _beta = 2\n",
            "from pkg.lib import helper\n\nALPHA = 1; _beta = helper\n",
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
            marks=pytest.mark.skipif(
                sys.version_info < (3, 12), reason="PEP 695 syntax needs 3.12+"
            ),
        ),
    ],
)
def test_an_edited_caller_is_caller_data_unknown(
    tmp_path: Path, monkeypatch, what: str, before: str, after: str
) -> None:
    """End to end: the code index and xrefs are current at T0 (pkg/main.py
    joined and pinned, referencing nothing); the edit gives pkg/main.py a
    reference to helper and changes helper's signature. A current join
    would credit that reference to a main.py symbol and list main-doc
    through its caller; the stored xrefs cannot. So `cdx impact` names
    pkg/main.py — every edited file — as caller data unknown, with
    callers_available false, and `cdx graph` agrees. The last three shapes
    are the round-5 review's reproductions, where the old "a symbol tier
    witnessed the edit" rule printed only lib-doc with no note."""
    # Feature: FEAT-CODEINDEX-002
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", "utf-8")
    lib = tmp_path / "pkg" / "lib.py"
    lib.write_text(_PKG_LIB, "utf-8")
    main = tmp_path / "pkg" / "main.py"
    main.write_text(before, "utf-8")
    _pkg_config(tmp_path, with_new=False)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    (tmp_path / "t0.scip").write_bytes(
        index(
            [
                document("pkg/__init__.py", []),
                document("pkg/lib.py", []),
                document("pkg/main.py", []),  # T0: main.py references nothing
            ]
        )
    )
    joined = runner.invoke(app, ["scip", "t0.scip", "--write"])
    assert joined.exit_code == 0 and "STALE" not in joined.stderr
    pinned = json.loads((tmp_path / ".cdmon" / "xrefs.json").read_text("utf-8"))
    assert "pkg/main.py" in pinned["input_digests"], what

    main.write_text(after, "utf-8")
    lib.write_text(_PKG_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8")
    text = runner.invoke(app, ["impact"])
    assert text.exit_code == 0, text.output
    assert "doc main-doc" not in text.output, what
    assert "caller data unknown for 2 file(s)" in text.output, what
    note = text.output.split("caller data unknown", 1)[1]
    assert "pkg/main.py" in note and "pkg/lib.py" in note, what
    payload = json.loads(runner.invoke(app, ["impact", "--json"]).output)
    assert payload["callers_available"] is False
    assert payload["callers_unknown"] == ["pkg/lib.py", "pkg/main.py"], what
    graph = runner.invoke(app, ["graph", "--focus", "symbol pkg/lib.py#helper"])
    assert "pkg/main.py" in graph.stdout.split("caller data unknown", 1)[1], what


_KEEP_BASELINE = "do NOT run `cdx codeindex --write`"


def test_impact_advises_a_remedy_that_keeps_its_baseline(
    tmp_path: Path, monkeypatch
) -> None:
    """`cdx impact` diffs the STORED code index against the tree, so its
    "caller data unknown" note must never advise refreshing that index
    (it resets the baseline — the next run says "no impact" and the pending
    change's docs are never listed). Its remedy is to re-index and re-join
    only; following it keeps the baseline and surfaces the new caller's
    doc, while the files with pending edits stay unknown until the change
    lands. `cdx graph`, which judges the tree, keeps the refresh advice."""
    # Feature: FEAT-CODEINDEX-002
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", "utf-8")
    lib = tmp_path / "pkg" / "lib.py"
    lib.write_text(_PKG_LIB, "utf-8")
    main = tmp_path / "pkg" / "main.py"
    main.write_text(_HANDLERS_T0, "utf-8")
    _pkg_config(tmp_path, with_new=False)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    (tmp_path / "t0.scip").write_bytes(
        index(
            [
                document("pkg/__init__.py", []),
                document("pkg/lib.py", []),
                document("pkg/main.py", []),
            ]
        )
    )
    assert runner.invoke(app, ["scip", "t0.scip", "--write"]).exit_code == 0
    main.write_text(_HANDLERS_T0.replace('"eps": len', '"eps": helper'), "utf-8")
    lib.write_text(_PKG_LIB.replace("def helper(x)", "def helper(x, y=0)"), "utf-8")

    note = runner.invoke(app, ["impact"]).stdout.split("caller data unknown", 1)[1]
    assert _KEEP_BASELINE in note
    assert "bring the code index current" not in note
    assert "pending edit" in note
    graph = runner.invoke(app, ["graph"]).stdout.split("caller data unknown", 1)[1]
    assert "bring the code index current" in graph

    # follow impact's advice: re-index the tree, re-join, keep the baseline
    (tmp_path / "t1.scip").write_bytes(
        index(
            [
                document("pkg/__init__.py", []),
                document("pkg/lib.py", []),
                document("pkg/main.py", [occurrence(_HELPER, range_=[2, 74, 80])]),
            ]
        )
    )
    rejoin = runner.invoke(app, ["scip", "t1.scip", "--write"])
    assert rejoin.exit_code == 0, rejoin.output
    # the STALE warning's refresh advice carries the same caveat
    assert "once any pending `cdx impact` is reviewed" in rejoin.stderr
    after = runner.invoke(app, ["impact"]).stdout
    assert "no impact" not in after
    assert "via caller: symbol pkg/lib.py#helper" in after
    payload = json.loads(runner.invoke(app, ["impact", "--json"]).stdout)
    by_doc = {d["doc_id"]: d for d in payload["docs"]}
    assert by_doc["main-doc"]["via_callers"] == ["symbol pkg/lib.py#helper"]
    assert payload["callers_unknown"] == ["pkg/lib.py", "pkg/main.py"]
