"""CIX-02 — `cdx scip` end-to-end (offline, via CliRunner).

A hand-encoded SCIP fixture (tests/_scip.py) drives the whole path: decode →
join against the code index → summary / `--write` idempotency / `--json` —
and `cdx graph` folds the persisted xrefs in as REFERENCES/indexed edges.

Features: FEAT-SCIP-001
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

_PREFIX = "scip-python python proj 0.1 "

_MAIN = '''"""Caller."""

def caller():
    """Calls helper."""
    return helper()
'''

_LIB = '''"""Lib."""

def helper():
    """Helper."""
    return 1
'''


def _fixture(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "main.py").write_text(_MAIN, encoding="utf-8")
    (tmp_path / "pkg" / "lib.py").write_text(_LIB, encoding="utf-8")
    (tmp_path / "cdmon.yaml").write_text(
        'version: "1.0.0"\nroot: "."\ndocuments: []\n', encoding="utf-8"
    )
    helper = _PREFIX + "`pkg.lib`/helper()."
    scip_path = tmp_path / "index.scip"
    scip_path.write_bytes(
        index([document("pkg/main.py", [occurrence(helper, range_=[4, 11, 17])])])
    )
    return scip_path


def test_summary_write_idempotency_and_graph_fold(tmp_path: Path, monkeypatch) -> None:
    scip_path = _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)

    summary = runner.invoke(app, ["scip", str(scip_path)])
    assert summary.exit_code == 0, summary.output
    assert "1 reference edge(s) from scip-python/0.6.6" in summary.output
    assert "coverage: python" in summary.output
    assert not (tmp_path / ".cdmon").exists()  # summary writes nothing (K1)

    first = runner.invoke(app, ["scip", str(scip_path), "--write"])
    assert first.exit_code == 0, first.output
    assert "wrote" in first.output
    second = runner.invoke(app, ["scip", str(scip_path), "--write"])
    assert "unchanged" in second.output

    graph = runner.invoke(app, ["graph", "--json"])
    assert graph.exit_code == 0, graph.output
    payload = json.loads(graph.output)
    refs = [e for e in payload["edges"] if e["kind"] == "references"]
    assert refs == [
        {
            "source": "symbol pkg/main.py#caller",
            "target": "symbol pkg/lib.py#helper",
            "kind": "references",
            "tier": "indexed",
        }
    ]


def test_json_shape(tmp_path: Path, monkeypatch) -> None:
    scip_path = _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scip", str(scip_path), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0.0"
    assert payload["tool"] == "scip-python/0.6.6"
    assert payload["unmapped"] == 0
    assert [e["count"] for e in payload["edges"]] == [1]


def test_corrupt_index_is_a_clean_error(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.scip"
    bad.write_bytes(b"\xff" * 16)
    result = runner.invoke(app, ["scip", str(bad)])
    assert result.exit_code == 1
    assert "error:" in result.output


# ------------------------------------------- input pin + currency (xref lane)


def _full_scip(path: Path, *, ref_line: int = 4) -> None:
    """A SCIP index with a document for EVERY coverage file (the real
    scip-python shape), so the join pins the whole python universe."""
    helper = _PREFIX + "`pkg.lib`/helper()."
    path.write_bytes(
        index(
            [
                document("pkg/__init__.py", []),
                document("pkg/lib.py", []),
                document(
                    "pkg/main.py", [occurrence(helper, range_=[ref_line, 11, 17])]
                ),
            ]
        )
    )


def test_stale_stored_index_warns_and_counts_dropped_attribution(
    tmp_path: Path, monkeypatch
) -> None:
    """A fresh .scip joined against a STALE stored code index used to drop
    the edge silently ("0 edges, 0 unmapped", exit 0). Now `cdx scip` warns
    on stderr that the stored index differs from the tree — naming the
    files — and the dropped source attribution is counted as
    `unattributed`."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    main = tmp_path / "pkg" / "main.py"
    main.write_text("# a\n# b\n# c\n# d\n" + _MAIN, encoding="utf-8")
    fresh = tmp_path / "fresh.scip"
    _full_scip(fresh, ref_line=8)  # the reference, 4 lines further down

    stale = runner.invoke(app, ["scip", str(fresh)])
    assert stale.exit_code == 0, stale.output
    assert "STALE" in stale.stderr and "cdx codeindex --write" in stale.stderr
    assert "1 file(s): pkg/main.py" in stale.stderr
    assert "0 reference edge(s)" in stale.stdout
    assert "1 unattributed reference(s)" in stale.stdout

    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    synced = runner.invoke(app, ["scip", str(fresh)])
    assert "STALE" not in synced.stderr
    assert "1 reference edge(s)" in synced.stdout
    assert "0 unattributed reference(s)" in synced.stdout


def test_write_refreshes_the_input_pin_idempotently(
    tmp_path: Path, monkeypatch
) -> None:
    """K7 with the input pin: re-running with identical inputs writes
    nothing; a comment-only change (identical edges) re-pinned through
    `codeindex --write` rewrites once, then is a no-op again."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    assert "wrote" in runner.invoke(app, ["scip", str(scip_path), "--write"]).output
    artifact = tmp_path / ".cdmon" / "xrefs.json"
    before = artifact.read_bytes()
    again = runner.invoke(app, ["scip", str(scip_path), "--write"])
    assert "unchanged" in again.output
    assert artifact.read_bytes() == before

    lib = tmp_path / "pkg" / "lib.py"
    lib.write_text(_LIB + "# trailing comment\n", encoding="utf-8")
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    assert "wrote" in runner.invoke(app, ["scip", str(scip_path), "--write"]).output
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    stored = json.loads(
        (tmp_path / ".cdmon" / "code-index.json").read_text(encoding="utf-8")
    )
    assert payload["input_digests"] == {
        f["path"]: f["content_digest"] for f in stored["files"]
    }
    assert "unchanged" in (
        runner.invoke(app, ["scip", str(scip_path), "--write"]).output
    )


def test_graph_says_caller_data_unknown_after_the_join(
    tmp_path: Path, monkeypatch
) -> None:
    """`cdx graph` folds REFERENCES from the stored xrefs; when a covered
    file changed or appeared since the join it says so — in the text views,
    in the artifact's `warnings` (JSON / --write), and on stderr for the
    focused JSON view so stdout stays parseable."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)
    assert runner.invoke(app, ["scip", str(scip_path), "--write"]).exit_code == 0

    current = runner.invoke(app, ["graph"])
    assert current.exit_code == 0, current.output
    assert "caller data unknown" not in current.output
    assert json.loads(runner.invoke(app, ["graph", "--json"]).output)["warnings"] == []

    (tmp_path / "pkg" / "new.py").write_text(
        "from pkg.lib import helper\n\n\ndef new_caller():\n    return helper()\n",
        encoding="utf-8",
    )
    text = runner.invoke(app, ["graph"])
    assert "caller data unknown for 1 file(s)" in text.stdout
    assert "pkg/new.py" in text.stdout
    focus = runner.invoke(app, ["graph", "--focus", "symbol pkg/lib.py#helper"])
    assert "caller data unknown for 1 file(s)" in focus.stdout
    payload = json.loads(runner.invoke(app, ["graph", "--json"]).stdout)
    assert any("caller data unknown for 1 file(s)" in w for w in payload["warnings"])
    focused = runner.invoke(
        app, ["graph", "--focus", "symbol pkg/lib.py#helper", "--json"]
    )
    assert json.loads(focused.stdout)  # stdout is still pure JSON
    assert "caller data unknown for 1 file(s)" in focused.stderr

    # the note rides the persisted artifact and stays byte-idempotent (K7)
    assert "wrote" in runner.invoke(app, ["graph", "--write"]).output
    assert "unchanged" in runner.invoke(app, ["graph", "--write"]).output
    persisted = json.loads(
        (tmp_path / ".cdmon" / "graph.json").read_text(encoding="utf-8")
    )
    assert any("pkg/new.py" in w for w in persisted["warnings"])


def test_an_unparseable_tree_is_still_checked_by_content(
    tmp_path: Path, monkeypatch
) -> None:
    """The stored index is checked against the tree's CONTENT listing
    (``file_digests`` — no symbol extraction), so a tree the extractor
    cannot parse (a syntax error) is still verified: the new file is named
    STALE, the join runs on the stored spans for the files it can vouch
    for, and nothing degrades to an unverified pass."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    (tmp_path / "pkg" / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    result = runner.invoke(app, ["scip", str(scip_path), "--json"])
    assert result.exit_code == 0, result.output
    assert "STALE" in result.stderr and "pkg/broken.py" in result.stderr
    assert "NOT verified" not in result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["edges"]) == 1
    assert "pkg/broken.py" not in payload["input_digests"]


def test_graph_judges_caller_currency_against_the_tree(
    tmp_path: Path, monkeypatch
) -> None:
    """`cdx graph` checks the xrefs pin against the TREE (``file_digests``),
    not the stored code index: a caller file added after the join, with
    the code index NOT refreshed, still yields the "caller data unknown"
    note (whereas `cdx impact` judges against its stored baseline)."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    assert runner.invoke(app, ["scip", str(scip_path), "--write"]).exit_code == 0
    assert "caller data unknown" not in runner.invoke(app, ["graph"]).stdout
    (tmp_path / "pkg" / "new.py").write_text(
        "from pkg.lib import helper\n\n\ndef new_caller():\n    return helper()\n",
        encoding="utf-8",
    )
    out = runner.invoke(app, ["graph"]).stdout
    assert "caller data unknown for 1 file(s)" in out and "pkg/new.py" in out


# ---------------------------------------- xref round 2 (review + mutation gaps)


def test_graph_says_currency_unknown_for_pre_pin_xrefs(
    tmp_path: Path, monkeypatch
) -> None:
    """An xrefs artifact written before the input pin existed still feeds
    REFERENCES into `cdx graph`, but its currency is unknowable — the graph
    says so in every view (text, the artifact's `warnings`, and stderr for
    the focused JSON view so stdout stays parseable), never a silent
    "current"."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    cdmon = tmp_path / ".cdmon"
    cdmon.mkdir()
    (cdmon / "xrefs.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "generated_by": "custodex/old",
                "tool": "scip-python/0.6.6",
                "coverage": {"python": "scip-python/0.6.6"},
                "unmapped": 0,
                "edges": [
                    {
                        "source": "symbol pkg/main.py#caller",
                        "target": "symbol pkg/lib.py#helper",
                        "count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    text = runner.invoke(app, ["graph"])
    assert text.exit_code == 0, text.output
    assert "carries no input pin" in text.stdout
    as_json = runner.invoke(app, ["graph", "--json"])
    assert as_json.exit_code == 0, as_json.output
    (note,) = json.loads(as_json.stdout)["warnings"]
    assert "carries no input pin" in note
    focused = runner.invoke(
        app, ["graph", "--focus", "symbol pkg/lib.py#helper", "--json"]
    )
    assert focused.exit_code == 0, focused.output
    assert json.loads(focused.stdout)  # stdout is still pure JSON
    assert "carries no input pin" in focused.stderr


def test_an_unreadable_coverage_file_is_named_not_fatal(
    tmp_path: Path, monkeypatch
) -> None:
    """One unreadable coverage file — a dangling symlink in the Emacs
    ``.#name.py`` lock-file shape, which ``**/*.py`` matches — must not
    crash the read-only currency checks: `cdx graph` (whenever xrefs exist)
    and `cdx scip` (whenever a stored index exists) used to die with an
    uncaught FileNotFoundError traceback. Now the file is named — "caller
    data unknown" in graph, STALE in scip — and both exit 0, as the graph's
    own registry already did for the same file."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    assert runner.invoke(app, ["scip", str(scip_path), "--write"]).exit_code == 0
    (tmp_path / "pkg" / ".#main.py").symlink_to("juan@host.12345:1695800000")

    text = runner.invoke(app, ["graph"])
    assert text.exit_code == 0, text.output
    assert "caller data unknown for 1 file(s)" in text.stdout
    assert "pkg/.#main.py" in text.stdout
    as_json = runner.invoke(app, ["graph", "--json"])
    assert as_json.exit_code == 0, as_json.output
    warnings = json.loads(as_json.stdout)["warnings"]
    assert any("caller data unknown" in w and "pkg/.#main.py" in w for w in warnings)

    joined = runner.invoke(app, ["scip", str(scip_path)])
    assert joined.exit_code == 0, joined.output
    assert "STALE against the tree for 1 file(s): pkg/.#main.py" in joined.stderr
    assert "1 reference edge(s)" in joined.stdout


_PRIV_MAIN = '''"""Caller."""

def _caller():
    """Calls helper."""
    return helper()
'''


def test_a_stale_private_span_drop_is_counted(tmp_path: Path, monkeypatch) -> None:
    """The STALE warning promises dropped edges are "counted as
    unattributed": a caller indexed while PRIVATE and renamed public in the
    tree loses its edge to the stale private span — that drop is now in the
    summary's count instead of a silent "0 unattributed"."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    main = tmp_path / "pkg" / "main.py"
    main.write_text(_PRIV_MAIN, encoding="utf-8")
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    main.write_text(_MAIN, encoding="utf-8")  # `_caller` → `caller`
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)

    stale = runner.invoke(app, ["scip", str(scip_path)])
    assert stale.exit_code == 0, stale.output
    assert "STALE against the tree for 1 file(s): pkg/main.py" in stale.stderr
    assert "0 reference edge(s)" in stale.stdout
    assert "1 unattributed reference(s)" in stale.stdout

    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    synced = runner.invoke(app, ["scip", str(scip_path)])
    assert "1 reference edge(s)" in synced.stdout
    assert "0 unattributed reference(s)" in synced.stdout


# ---------------------------------------------- xref round 4 (review minors)

_OLD = '''"""Old caller."""

def old_entry():
    """Calls helper."""
    return helper()
'''


def test_graph_names_a_deleted_caller_the_join_left_unpinned(
    tmp_path: Path, monkeypatch
) -> None:
    """A caller file deleted after `cdx codeindex --write` is STALE when an
    older .scip is joined: the join leaves it unpinned, yet its edges are
    attributed through the stored spans. `cdx graph` used to show those
    REFERENCES with no note (its listing no longer holds the file); the
    unpinned edge source is now reported "caller data unknown", as the
    STALE warning promises."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    old = tmp_path / "pkg" / "old.py"
    old.write_text(_OLD, encoding="utf-8")
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    old.unlink()
    helper = _PREFIX + "`pkg.lib`/helper()."
    scip_path = tmp_path / "older.scip"
    scip_path.write_bytes(
        index(
            [
                document("pkg/__init__.py", []),
                document("pkg/lib.py", []),
                document("pkg/main.py", [occurrence(helper, range_=[4, 11, 17])]),
                document("pkg/old.py", [occurrence(helper, range_=[4, 11, 17])]),
            ]
        )
    )
    joined = runner.invoke(app, ["scip", str(scip_path), "--write"])
    assert joined.exit_code == 0, joined.output
    assert "1 file(s): pkg/old.py" in joined.stderr
    stored = json.loads((tmp_path / ".cdmon" / "xrefs.json").read_text("utf-8"))
    assert "pkg/old.py" not in stored["input_digests"]
    assert any(e["source"] == "symbol pkg/old.py#old_entry" for e in stored["edges"])

    focus = runner.invoke(app, ["graph", "--focus", "symbol pkg/lib.py#helper"])
    assert focus.exit_code == 0, focus.output
    assert "symbol pkg/old.py#old_entry" in focus.stdout
    assert "caller data unknown for 1 file(s)" in focus.stdout
    assert "pkg/old.py" in focus.stdout.split("caller data unknown", 1)[1]
    warnings = json.loads(runner.invoke(app, ["graph", "--json"]).stdout)["warnings"]
    assert any("caller data unknown" in w and "pkg/old.py" in w for w in warnings)


def test_scip_vouches_only_what_a_fresh_build_reproduces(
    tmp_path: Path, monkeypatch
) -> None:
    """`cdx scip` checks the stored code index against a FRESH in-memory
    build, entry by entry — not just file bytes. A stored index whose spans
    drifted over identical bytes (an extractor change between custodex
    versions; ``codeindex --check`` says STALE) is named in the STALE
    warning and its file is left unpinned, so `cdx graph` reports that
    caller data unknown instead of trusting the drifted spans."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    artifact = tmp_path / ".cdmon" / "code-index.json"
    stored = json.loads(artifact.read_text("utf-8"))
    for entry in stored["files"]:
        for sym in entry["symbols"]:
            if entry["path"] == "pkg/main.py" and sym["name"] == "caller":
                sym["end_lineno"] = sym["lineno"]
    artifact.write_text(json.dumps(stored), encoding="utf-8")
    assert runner.invoke(app, ["codeindex", "--check"]).exit_code == 1

    summary = runner.invoke(app, ["scip", str(scip_path)])
    assert summary.exit_code == 0, summary.output
    assert "STALE against the tree for 1 file(s): pkg/main.py" in summary.stderr
    assert "0 reference edge(s)" in summary.stdout
    assert "1 unattributed reference(s)" in summary.stdout
    assert runner.invoke(app, ["scip", str(scip_path), "--write"]).exit_code == 0
    pinned = json.loads((tmp_path / ".cdmon" / "xrefs.json").read_text("utf-8"))
    assert "pkg/main.py" not in pinned["input_digests"]
    graph = runner.invoke(app, ["graph"])
    assert "caller data unknown for 1 file(s)" in graph.stdout
    assert "pkg/main.py" in graph.stdout.split("caller data unknown", 1)[1]

    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    synced = runner.invoke(app, ["scip", str(scip_path)])
    assert "STALE" not in synced.stderr
    assert "1 reference edge(s)" in synced.stdout


def test_a_tree_that_does_not_extract_falls_back_to_the_content_check(
    tmp_path: Path, monkeypatch
) -> None:
    """When the fresh build cannot run — an unreadable ``run.sh`` (a
    dangling symlink) in the coverage universe — `cdx scip` falls back to
    the extraction-free content check: exit 0, the join still made, and
    every file whose content disagrees with the stored index (the
    unreadable one, and an edited ``lib.py``) named STALE and left out of
    the pin. Never a bare OSError traceback."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    (tmp_path / "cdmon.yaml").write_text(
        'version: "1.0.0"\nroot: "."\ndocuments: []\n'
        'coverage:\n  include: ["**/*.py", "**/*.sh"]\n  exclude: []\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    (tmp_path / "run.sh").symlink_to("missing-target.sh")
    lib = tmp_path / "pkg" / "lib.py"
    lib.write_text(_LIB + "# edited\n", encoding="utf-8")

    result = runner.invoke(app, ["scip", str(scip_path), "--json"])
    assert result.exit_code == 0, result.output
    assert "STALE against the tree for 2 file(s): pkg/lib.py, run.sh" in result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["edges"]) == 1
    assert "pkg/lib.py" not in payload["input_digests"]
    assert "pkg/main.py" in payload["input_digests"]


class _Py310Ast:
    """``ast`` as Python 3.10 — the supported floor — behaves: ``parse``
    raises ValueError, not SyntaxError, for a NUL byte. Everything else is
    the real module, so patching the extractor's ``ast`` name is scoped."""

    def __getattr__(self, name: str) -> object:
        import ast

        return getattr(ast, name)

    @staticmethod
    def parse(source: object, *args: object, **kwargs: object) -> object:
        import ast

        if isinstance(source, str) and "\x00" in source:
            raise ValueError("source code string cannot contain null bytes")
        return ast.parse(source, *args, **kwargs)  # type: ignore[call-overload]


def test_a_nul_byte_on_python_3_10_falls_back_to_the_content_check(
    tmp_path: Path, monkeypatch
) -> None:
    """Python 3.10's parser raises ValueError (not SyntaxError) for a NUL
    byte, which the extractor does not type. Since `cdx scip` builds the
    tree fresh whenever a stored index exists, that used to be a ValueError
    traceback (exit 1) where the pre-fresh-build verb ran fine. The build
    now types it, so `cdx scip` takes its content fallback: exit 0, the
    file named STALE, the join still made."""
    # Feature: FEAT-SCIP-001
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("custodex.extract.ast", _Py310Ast())
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    (tmp_path / "pkg" / "bad.py").write_bytes(b"x = 1\n\x00\n")

    result = runner.invoke(app, ["scip", str(scip_path), "--json"])
    assert result.exit_code == 0, result.output
    assert "STALE against the tree for 1 file(s): pkg/bad.py" in result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["edges"]) == 1
    assert "pkg/bad.py" not in payload["input_digests"]
    assert "pkg/main.py" in payload["input_digests"]


def test_a_value_the_extractor_cannot_render_falls_back_to_the_content_check(
    tmp_path: Path, monkeypatch
) -> None:
    """A covered file that parses but cannot be extracted — a hex literal
    past the int-to-str digit limit, whose ``ast.unparse`` raises
    ValueError — makes the fresh build fail with the typed error, so `cdx
    scip` takes its content fallback: exit 0, the file named STALE and left
    out of the pin, the join still made. Never a ValueError traceback."""
    # Feature: FEAT-SCIP-001
    limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
    if not limit:  # e.g. PYTHONINTMAXSTRDIGITS=0
        pytest.skip("this interpreter has no int-to-str digit limit")
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    scip_path = tmp_path / "full.scip"
    _full_scip(scip_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    big = "X = 0x" + "f" * (limit + 1) + "\n"  # more decimal digits than limit
    (tmp_path / "pkg" / "big.py").write_text(big, "utf-8")

    result = runner.invoke(app, ["scip", str(scip_path), "--json"])
    assert result.exit_code == 0, result.output
    assert "STALE against the tree for 1 file(s): pkg/big.py" in result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["edges"]) == 1
    assert "pkg/big.py" not in payload["input_digests"]
    assert "pkg/main.py" in payload["input_digests"]
