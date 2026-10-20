"""CIX-01 — the persisted code index (`codeindex.py`).

The durable, diffable snapshot of the extracted code surface: every file in
the coverage universe with a content digest, every symbol with its span and
per-tier digests, stamped with injected provenance that never enters a
digest or a comparison (stamps are provenance, never identity — K7/K10).

Features: FEAT-CODEINDEX-001
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from custodex.codeindex import (
    CODE_INDEX_PATH,
    UNREADABLE_DIGEST,
    CodeIndex,
    build_code_index,
    diff_code_index,
    file_digests,
    index_in_sync,
    read_code_index,
    stale_paths,
    write_code_index,
)
from custodex.config import MonitorConfig
from custodex.errors import ExtractionError, SchemaError
from custodex.extract import Audience, DocumentSurface, extract_file

_MOD = '''"""Mod docstring."""
CONST = 1

def alpha(x, y=2):
    """Alpha docs."""
    return x + y

class Widget:
    """Widget docs."""

    def run(self, verbose=False):
        """Run docs."""
        if verbose:
            return 2
        return 1

def _private_helper():
    return None
'''

_OTHER = '''def beta():
    """Beta docs."""
    return 3
'''


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(_MOD, encoding="utf-8")
    (tmp_path / "pkg" / "other.py").write_text(_OTHER, encoding="utf-8")
    return tmp_path


def _config() -> MonitorConfig:
    return MonitorConfig(documents=())


def _build(root: Path, *, source_sha: str | None = None) -> CodeIndex:
    return build_code_index(
        _config(), root, generated_by="custodex/test", source_sha=source_sha
    )


# ---------------------------------------------------------------- build (K10)


def test_build_is_deterministic_and_sorted(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    a = _build(root)
    b = _build(root)
    assert a == b
    assert a.model_dump_json(indent=2) == b.model_dump_json(indent=2)
    paths = [f.path for f in a.files]
    assert paths == sorted(paths) == ["pkg/mod.py", "pkg/other.py"]
    for f in a.files:
        keys = [(s.name, s.lineno) for s in f.symbols]
        assert keys == sorted(keys)


def test_build_digests_match_the_extract_conventions(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    idx = _build(root)
    mod = idx.files[0]
    raw = (root / "pkg" / "mod.py").read_bytes()
    assert mod.content_digest == hashlib.sha256(raw).hexdigest()[:16]

    # sig_digest must equal the DIG-01 cdm.symbol_sigs value for the symbol.
    symbols = extract_file(root / "pkg" / "mod.py")
    surface = DocumentSurface(
        doc_id="x", audience=Audience.ENG_GUIDE, symbols=symbols, records=()
    )
    sig_by_anchor = surface.fingerprint().sig_by_anchor
    assert sig_by_anchor is not None
    by_name = {s.name: s for s in mod.symbols}
    for sym in symbols:
        indexed = by_name[sym.name]
        assert indexed.anchor == sym.anchor_id
        assert sig_by_anchor[sym.anchor_id] == indexed.sig_digest
        assert indexed.body_digest == sym.body_hash
        if sym.docstring is None:
            assert indexed.doc_digest is None
        else:
            expected = hashlib.sha256(sym.docstring.encode("utf-8")).hexdigest()[:16]
            assert indexed.doc_digest == expected
    # Private symbols ARE indexed (the index is the whole surface; audience
    # filters are a downstream concern).
    assert by_name["_private_helper"].is_public is False


def test_build_never_embeds_an_absolute_path(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    dump = _build(root).model_dump_json(indent=2)
    assert str(root) not in dump
    assert tmp_path.as_posix() not in dump


# ------------------------------------------------------- read / write (K7/K8)


def test_write_then_read_roundtrip_and_idempotency(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cdmon = root / ".cdmon"
    idx = _build(root, source_sha="aaa111")
    assert write_code_index(idx, cdmon) is True
    assert read_code_index(cdmon) == idx
    # Second write with identical content: zero bytes written (K7).
    before = (cdmon / CODE_INDEX_PATH.name).read_text(encoding="utf-8")
    assert write_code_index(idx, cdmon) is False
    assert (cdmon / CODE_INDEX_PATH.name).read_text(encoding="utf-8") == before


def test_write_is_stamp_blind(tmp_path: Path) -> None:
    """Same files under a new provenance stamp: no write, old stamp survives."""
    root = _repo(tmp_path)
    cdmon = root / ".cdmon"
    assert write_code_index(_build(root, source_sha="aaa111"), cdmon) is True
    assert write_code_index(_build(root, source_sha="bbb222"), cdmon) is False
    stored = read_code_index(cdmon)
    assert stored is not None
    assert stored.source_sha == "aaa111"  # "content unchanged since aaa111"


def test_read_missing_is_none_and_corrupt_is_loud(tmp_path: Path) -> None:
    cdmon = tmp_path / ".cdmon"
    assert read_code_index(cdmon) is None
    cdmon.mkdir()
    target = cdmon / CODE_INDEX_PATH.name
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(SchemaError):
        read_code_index(cdmon)
    # The writer replaces a corrupt artifact instead of failing (regenerable).
    root = _repo(tmp_path)
    assert write_code_index(_build(root), cdmon) is True
    assert read_code_index(cdmon) is not None


def test_artifact_json_shape_is_versioned(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cdmon = root / ".cdmon"
    write_code_index(_build(root), cdmon)
    payload = json.loads((cdmon / CODE_INDEX_PATH.name).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0.0"
    assert payload["generated_by"] == "custodex/test"
    assert [f["path"] for f in payload["files"]] == ["pkg/mod.py", "pkg/other.py"]
    # a file entry is its content digest and its symbols — nothing that
    # claims to know which edits could change a reference (xref round 6)
    assert {tuple(sorted(f)) for f in payload["files"]} == {
        ("content_digest", "language", "path", "symbols")
    }


# ------------------------------------------------------------------ diff (K10)


def test_diff_identical_is_empty(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert diff_code_index(_build(root), _build(root)).files == ()


def test_diff_signature_change(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    old = _build(root)
    mod = root / "pkg" / "mod.py"
    mod.write_text(_MOD.replace("def alpha(x, y=2)", "def alpha(x, y=3)"), "utf-8")
    (delta,) = diff_code_index(old, _build(root)).files
    assert delta.path == "pkg/mod.py"
    assert delta.status == "modified"
    assert delta.sigs_changed == ("alpha",)
    assert delta.symbols_added == () and delta.symbols_removed == ()


def test_diff_docstring_only_change(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    old = _build(root)
    mod = root / "pkg" / "mod.py"
    mod.write_text(_MOD.replace("Alpha docs.", "Alpha docs, revised."), "utf-8")
    (delta,) = diff_code_index(old, _build(root)).files
    assert delta.docs_changed == ("alpha",)
    assert delta.sigs_changed == () and delta.bodies_changed == ()


def test_diff_body_only_change(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    old = _build(root)
    mod = root / "pkg" / "mod.py"
    mod.write_text(_MOD.replace("return x + y", "return x * y"), "utf-8")
    (delta,) = diff_code_index(old, _build(root)).files
    assert delta.bodies_changed == ("alpha",)
    assert delta.sigs_changed == () and delta.docs_changed == ()


def test_diff_comment_only_change_is_an_empty_modified_delta(tmp_path: Path) -> None:
    """The file moved but the surface did not — honest, bucket-less delta."""
    root = _repo(tmp_path)
    old = _build(root)
    mod = root / "pkg" / "mod.py"
    mod.write_text(_MOD + "# trailing comment\n", "utf-8")
    (delta,) = diff_code_index(old, _build(root)).files
    assert delta.status == "modified"
    assert delta.symbols_added == delta.symbols_removed == ()
    assert delta.sigs_changed == delta.docs_changed == delta.bodies_changed == ()


def test_diff_symbol_and_file_add_remove(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    old = _build(root)
    (root / "pkg" / "other.py").unlink()
    (root / "pkg" / "new.py").write_text("def gamma():\n    return 9\n", "utf-8")
    mod = root / "pkg" / "mod.py"
    mod.write_text(_MOD + "\n\ndef extra():\n    return 0\n", "utf-8")
    diff = diff_code_index(old, _build(root))
    by_path = {d.path: d for d in diff.files}
    assert by_path["pkg/new.py"].status == "added"
    assert by_path["pkg/new.py"].symbols_added == ("gamma",)
    assert by_path["pkg/other.py"].status == "removed"
    assert by_path["pkg/other.py"].symbols_removed == ("beta",)
    assert "extra" in by_path["pkg/mod.py"].symbols_added
    assert list(by_path) == sorted(by_path)


def test_diff_detects_a_change_to_any_duplicate_named_symbol(tmp_path: Path) -> None:
    """Adversarial-review pin: `typing.overload` stacks / try-except fallback
    defs repeat one qualified name — the per-name digest-MULTISET compare
    must flag a change to ANY occurrence (a name-keyed dict silently kept
    only the last one, reporting a breaking overload change as cosmetic)."""
    dup = "def f(a):\n    return 1\n\ndef f(a, b):\n    return 2\n"
    root = tmp_path
    (root / "dup.py").write_text(dup, encoding="utf-8")
    old = _build(root)
    (root / "dup.py").write_text(
        dup.replace("def f(a):", "def f(a, c=0):"), encoding="utf-8"
    )
    (delta,) = diff_code_index(old, _build(root)).files
    assert delta.sigs_changed == ("f",)
    assert delta.symbols_added == () and delta.symbols_removed == ()


# ------------------------------------------ currency helpers (xref input pin)


def test_file_digests_is_the_index_universe_without_extraction(
    tmp_path: Path,
) -> None:
    """The cheap currency listing — path → (language, content_digest) — is
    EXACTLY the code index's file universe and digests (one scan, one digest
    convention), so comparing an xref input pin against the tree agrees
    with comparing it against a freshly built index."""
    # Feature: FEAT-CODEINDEX-001
    root = _repo(tmp_path)
    (root / "run.sh").write_text("echo hi\n", encoding="utf-8")
    # raw bytes, never a text-mode read: a CRLF source must not read as
    # "changed since the join" forever in `cdx graph`
    (root / "pkg" / "win.py").write_bytes(b"def win():\r\n    return 1\r\n")
    # an EXCLUDED file is outside both universes — never a spurious STALE
    # warning or a permanent "caller data unknown" in `cdx graph`
    (root / "pkg" / "vendored.py").write_text("def v():\n    return 1\n", "utf-8")
    cfg = MonitorConfig(
        documents=(),
        coverage={
            "include": ("**/*.py", "**/*.sh"),
            "exclude": ("pkg/vendored.py",),
        },
    )
    idx = build_code_index(cfg, root, generated_by="t")
    listing = file_digests(cfg, root)
    assert listing == {f.path: (f.language, f.content_digest) for f in idx.files}
    assert list(listing) == sorted(listing)  # K10
    assert "run.sh" in listing  # non-python files are in the universe too
    assert "pkg/vendored.py" not in listing
    assert stale_paths(idx, listing) == ()


def test_index_in_sync_is_the_stamp_blind_content_compare(tmp_path: Path) -> None:
    """ONE stamp-blind comparison (⟨R⟩2) backs `codeindex --check`, the
    idempotent writer and `cdx scip`'s stale-index warning: a new stamp is
    in sync, a content change is not."""
    # Feature: FEAT-CODEINDEX-001
    root = _repo(tmp_path)
    a = _build(root, source_sha="aaa")
    assert index_in_sync(a, _build(root, source_sha="bbb")) is True
    (root / "pkg" / "other.py").write_text(_OTHER + "\n# note\n", "utf-8")
    assert index_in_sync(a, _build(root)) is False


def test_stale_paths_names_every_disagreement_with_the_tree(tmp_path: Path) -> None:
    """``stale_paths`` names each file where a stored index and the tree's
    content listing disagree — changed, added or removed — sorted (K10);
    ``()`` means in sync. It is the cheap, extraction-free check behind
    `cdx scip`'s STALE warning, so it must see every kind of drift."""
    # Feature: FEAT-CODEINDEX-001
    root = _repo(tmp_path)
    cfg = _config()
    stored = _build(root)
    assert stale_paths(stored, file_digests(cfg, root)) == ()
    # same bytes, other language (an older extension map): stale too
    relabelled = stored.model_copy(
        update={
            "files": tuple(
                f.model_copy(update={"language": "unknown"})
                if f.path == "pkg/mod.py"
                else f
                for f in stored.files
            )
        }
    )
    assert stale_paths(relabelled, file_digests(cfg, root)) == ("pkg/mod.py",)
    (root / "pkg" / "other.py").write_text(_OTHER + "\n# note\n", "utf-8")
    (root / "pkg" / "added.py").write_text("X = 1\n", "utf-8")
    (root / "pkg" / "mod.py").unlink()
    assert stale_paths(stored, file_digests(cfg, root)) == (
        "pkg/added.py",
        "pkg/mod.py",
        "pkg/other.py",
    )


def test_index_in_sync_breaks_on_a_schema_version_change(tmp_path: Path) -> None:
    """Identical files under a different artifact ``schema_version`` are NOT
    in sync: `codeindex --check` must report it and the writer must rewrite
    it (K6 — the format version is content, not a stamp)."""
    # Feature: FEAT-CODEINDEX-001
    root = _repo(tmp_path)
    idx = _build(root)
    older = idx.model_copy(update={"schema_version": "0.9.0"})
    assert index_in_sync(older, idx) is False
    cdmon = tmp_path / ".cdmon"
    assert write_code_index(older, cdmon) is True
    assert write_code_index(idx, cdmon) is True  # a format bump rewrites
    stored = json.loads((cdmon / CODE_INDEX_PATH.name).read_text(encoding="utf-8"))
    assert stored["schema_version"] == idx.schema_version
    assert write_code_index(idx, cdmon) is False  # …then is a no-op (K7)


def test_file_digests_is_total_over_unreadable_files(tmp_path: Path) -> None:
    """The currency listing never aborts on one bad file (the
    ``entities.build_registry`` resilience `cdx graph` already has): a
    dangling symlink — the Emacs ``.#name.py`` lock-file shape, which
    ``**/*.py`` matches — or an unreadable file is listed with the
    :data:`UNREADABLE_DIGEST` sentinel, which no real digest can equal, so
    ``stale_paths`` names it STALE and a consumer reports its caller data
    unknown instead of crashing `cdx graph` / `cdx scip` with a traceback."""
    # Feature: FEAT-CODEINDEX-001
    root = _repo(tmp_path)
    cfg = _config()
    stored = _build(root)
    (root / "pkg" / ".#mod.py").symlink_to("juan@host.12345:1695800000")
    listing = file_digests(cfg, root)
    assert listing["pkg/.#mod.py"] == ("python", UNREADABLE_DIGEST)
    assert listing["pkg/mod.py"] == (
        "python",
        hashlib.sha256((root / "pkg" / "mod.py").read_bytes()).hexdigest()[:16],
    )
    assert stale_paths(stored, listing) == ("pkg/.#mod.py",)
    # the sentinel is not hex, so it can never collide with a sha256[:16]
    assert not set(UNREADABLE_DIGEST) <= set("0123456789abcdef")

    other = root / "pkg" / "other.py"
    other.chmod(0)
    try:
        if os.access(other, os.R_OK):  # pragma: no cover - running as root
            pytest.skip("permission bits do not bind this user")
        unreadable = file_digests(cfg, root)
    finally:
        other.chmod(0o644)
    assert unreadable["pkg/other.py"] == ("python", UNREADABLE_DIGEST)
    assert stale_paths(stored, unreadable) == ("pkg/.#mod.py", "pkg/other.py")


def test_index_in_sync_sees_symbol_drift_over_identical_bytes(tmp_path: Path) -> None:
    """The stamp-blind compare is over the whole ``files`` payload, SYMBOLS
    included — not just ``content_digest``: an index written by an older
    extractor that produced different spans over the very same bytes is NOT
    in sync, so `cdx codeindex --check` reports it and the writer replaces
    it. This is the symbol-level staleness `cdx scip`'s content-only STALE
    check deliberately delegates to `codeindex --check`."""
    # Feature: FEAT-CODEINDEX-001
    root = _repo(tmp_path)
    idx = _build(root)
    older = idx.model_copy(
        update={
            "files": tuple(
                f.model_copy(
                    update={
                        "symbols": tuple(
                            s.model_copy(update={"end_lineno": s.end_lineno + 1})
                            for s in f.symbols
                        )
                    }
                )
                if f.path == "pkg/mod.py"
                else f
                for f in idx.files
            )
        }
    )
    # identical bytes: the content listing cannot see it…
    assert [f.content_digest for f in older.files] == [
        f.content_digest for f in idx.files
    ]
    # …the full compare does
    assert index_in_sync(older, idx) is False
    cdmon = tmp_path / ".cdmon"
    assert write_code_index(older, cdmon) is True
    assert write_code_index(idx, cdmon) is True  # the drift is rewritten
    stored = read_code_index(cdmon)
    assert stored is not None and stored.files == idx.files
    assert write_code_index(idx, cdmon) is False  # …then a no-op (K7)


# ------------------------------------------ typed extraction failures (K8)


@pytest.mark.parametrize("how", ["a dangling symlink", "permission bits 000"])
def test_an_unreadable_file_is_a_typed_extraction_error(
    tmp_path: Path, how: str
) -> None:
    """Building the index reads every coverage file's bytes; an unreadable
    one — a dangling ``run.sh`` symlink, or one whose permission bits deny
    this user, neither of which an extractor opens first — raises the typed
    :class:`ExtractionError` naming it (K8), so `cdx codeindex` reports a
    clean error and `cdx scip` can fall back to the extraction-free content
    check instead of dying on a bare FileNotFoundError / PermissionError."""
    # Feature: FEAT-CODEINDEX-001
    root = _repo(tmp_path)
    script = root / "run.sh"
    if how == "a dangling symlink":
        script.symlink_to("missing-target.sh")
    else:
        script.write_text("echo hi\n", encoding="utf-8")
        script.chmod(0)
        if os.access(script, os.R_OK):  # pragma: no cover - running as root
            pytest.skip("permission bits do not bind this user")
    cfg = MonitorConfig(
        documents=(), coverage={"include": ("**/*.py", "**/*.sh"), "exclude": ()}
    )
    try:
        with pytest.raises(ExtractionError, match="run.sh"):
            build_code_index(cfg, root, generated_by="t")
    finally:
        if not script.is_symlink():
            script.chmod(0o644)


def test_unsynced_paths_names_every_entry_disagreement(tmp_path: Path) -> None:
    """``unsynced_paths`` is :func:`index_in_sync` per file: it names every
    path whose WHOLE entry differs — symbols and spans over identical bytes
    included, not just the content digest — plus added and removed files,
    sorted (K10). ``()`` = the file sets and entries agree."""
    # Feature: FEAT-CODEINDEX-001
    from custodex.codeindex import unsynced_paths

    root = _repo(tmp_path)
    idx = _build(root)
    assert unsynced_paths(idx, idx) == ()
    drifted = idx.model_copy(
        update={
            "files": tuple(
                f.model_copy(
                    update={
                        "symbols": tuple(
                            s.model_copy(update={"end_lineno": s.lineno})
                            for s in f.symbols
                        )
                    }
                )
                if f.path == "pkg/mod.py"
                else f
                for f in idx.files
            )
        }
    )
    assert stale_paths(drifted, file_digests(_config(), root)) == ()
    assert unsynced_paths(drifted, idx) == ("pkg/mod.py",)
    # any other field of the entry counts too — a docstring digest over the
    # same bytes and spans: `cdx scip` names it STALE rather than unpinning
    # it silently
    redoc = idx.model_copy(
        update={
            "files": tuple(
                f.model_copy(
                    update={
                        "symbols": tuple(
                            s.model_copy(update={"doc_digest": None}) for s in f.symbols
                        )
                    }
                )
                for f in idx.files
            )
        }
    )
    assert unsynced_paths(redoc, idx) == ("pkg/mod.py", "pkg/other.py")
    (root / "pkg" / "new.py").write_text("X = 1\n", encoding="utf-8")
    (root / "pkg" / "other.py").unlink()
    assert unsynced_paths(drifted, _build(root)) == (
        "pkg/mod.py",
        "pkg/new.py",
        "pkg/other.py",
    )


class _Py310Ast:
    """``ast`` as Python 3.10 — the supported floor — behaves: ``parse``
    raises ValueError, not SyntaxError, for a NUL byte (3.11 raises
    SyntaxError, which the extractor already types). Everything else is the
    real module, so patching a module's ``ast`` name with it is scoped."""

    def __getattr__(self, name: str) -> object:
        import ast

        return getattr(ast, name)

    @staticmethod
    def parse(source: object, *args: object, **kwargs: object) -> object:
        import ast

        if isinstance(source, str) and "\x00" in source:
            raise ValueError("source code string cannot contain null bytes")
        return ast.parse(source, *args, **kwargs)  # type: ignore[call-overload]


def test_a_parser_value_error_is_a_typed_extraction_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Python 3.10 the extractor's ``ast.parse`` raises ValueError for a
    NUL byte, and the extractor types only SyntaxError. Building the index
    turns it into the typed :class:`ExtractionError` naming the file (K8),
    so `cdx codeindex`/`cdx impact` print a clean ``error:`` and `cdx scip`
    falls back to its content check instead of a traceback."""
    # Feature: FEAT-CODEINDEX-001
    root = _repo(tmp_path)
    monkeypatch.setattr("custodex.extract.ast", _Py310Ast())
    assert index_in_sync(_build(root), _build(root))  # clean files still parse
    (root / "pkg" / "bad.py").write_bytes(b"x = 1\n\x00\n")
    with pytest.raises(ExtractionError, match="pkg/bad.py"):
        _build(root)


def test_a_value_the_extractor_cannot_render_is_a_typed_extraction_error(
    tmp_path: Path,
) -> None:
    """A file can parse and still fail extraction: a hex literal past the
    int-to-str digit limit (Python 3.11+, and 3.10.7+) parses, but the
    extractor renders the value with ``ast.unparse`` and that raises
    ValueError. Building the index types it — :class:`ExtractionError`
    naming the file (K8) — so `cdx codeindex`/`cdx impact` print a clean
    ``error:`` and `cdx scip` names the file STALE, never a traceback."""
    # Feature: FEAT-CODEINDEX-001
    limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
    if not limit:  # e.g. PYTHONINTMAXSTRDIGITS=0
        pytest.skip("this interpreter has no int-to-str digit limit")
    root = _repo(tmp_path)
    big = "X = 0x" + "f" * (limit + 1) + "\n"  # more decimal digits than limit
    (root / "pkg" / "big.py").write_text(big, "utf-8")
    with pytest.raises(ExtractionError, match="pkg/big.py"):
        _build(root)
