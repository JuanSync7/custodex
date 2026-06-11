"""Tests for code_doc_monitor.coverage (A-03).

Pure ownership resolution: crosses a :class:`SymbolInventory` with a
:class:`MonitorConfig`'s document code_refs to decide what is documented vs an
undocumented gap, at file AND public-symbol granularity (lossless). Written
before the implementation (K9, TDD). Deterministic sorted output (K10), reuses
``extract._select`` for selection (K0), ignores audience for ownership.

Features: FEAT-COVERAGE-006, FEAT-COVERAGE-007, FEAT-COVERAGE-008
Features: FEAT-COVERAGE-009, FEAT-COVERAGE-010
"""

from __future__ import annotations

from pathlib import Path

from code_doc_monitor.config import (
    Audience,
    CodeRef,
    CoverageConfig,
    DocumentSpec,
    MonitorConfig,
    WaiverEntry,
)
from code_doc_monitor.coverage import (
    CoverageReport,
    OwnedFile,
    OwnedSymbol,
    OwnerSuggestion,
    _proposed_doc_id,
    coverage_snapshot,
    resolve_coverage,
    suggest_owners,
)
from code_doc_monitor.inventory import discover_files, discover_symbols

# --------------------------------------------------------------------------
# Real fixture mini-repo: 3 files, mixed ownership.
#   a.py -> referenced whole-file by doc D1
#   b.py -> referenced by doc D2 with symbols=["Foo"] (Foo + Foo.method owned,
#           sibling `bar` unowned, private `_secret` not counted)
#   c.py -> referenced by no doc (an undocumented file)
# --------------------------------------------------------------------------

A_PY = '''\
def alpha(x: int) -> int:
    """Public fn."""
    return x


GAMMA = 1
'''

B_PY = '''\
class Foo:
    """A class."""

    def method(self, y: int) -> int:
        return y


def bar(z: int) -> int:
    """Sibling function, not referenced."""
    return z


def _secret() -> None:
    """Private — tracked but never a gap."""
'''

C_PY = '''\
def orphan() -> None:
    """In an unreferenced file."""
'''


def _build_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text(A_PY, encoding="utf-8")
    (root / "src" / "b.py").write_text(B_PY, encoding="utf-8")
    (root / "src" / "c.py").write_text(C_PY, encoding="utf-8")


def _inventory(root: Path):
    return discover_symbols(discover_files(root), root)


def _config(documents: tuple[DocumentSpec, ...]) -> MonitorConfig:
    return MonitorConfig(documents=documents)


def _fixture_config() -> MonitorConfig:
    d1 = DocumentSpec(
        id="D1",
        path="docs/d1.md",
        audience=Audience.USER_GUIDE,
        code_refs=(CodeRef(path="src/a.py"),),
    )
    d2 = DocumentSpec(
        id="D2",
        path="docs/d2.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/b.py", symbols=("Foo",)),),
    )
    return _config((d1, d2))


def _by_name(report: CoverageReport, path: str, name: str) -> OwnedSymbol:
    [sym] = [s for s in report.symbols if s.path == path and s.name == name]
    return sym


# --------------------------------------------------------------------------
# real fixture / integration: exact baskets, owners, percentages
# --------------------------------------------------------------------------


def test_real_fixture_exact_baskets(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    report = resolve_coverage(_fixture_config(), inv)

    # Files: a.py + b.py documented, c.py the lone gap.
    assert tuple(f.path for f in report.documented_files) == ("src/a.py", "src/b.py")
    assert tuple(f.path for f in report.undocumented_files) == ("src/c.py",)
    assert tuple(f.owners for f in report.files) == (("D1",), ("D2",), ())

    # D1 owns ALL of a.py's symbols (whole-file ref).
    assert _by_name(report, "src/a.py", "alpha").owners == ("D1",)
    assert _by_name(report, "src/a.py", "GAMMA").owners == ("D1",)

    # b.py: Foo + Foo.method owned by D2; sibling bar is a gap; _secret private.
    assert _by_name(report, "src/b.py", "Foo").owners == ("D2",)
    assert _by_name(report, "src/b.py", "Foo.method").owners == ("D2",)
    assert _by_name(report, "src/b.py", "bar").owners == ()
    assert _by_name(report, "src/b.py", "_secret").owners == ()

    # Gap basket = public, unowned symbols only: just b.py's bar and c.py's orphan.
    assert tuple((s.path, s.name) for s in report.undocumented_symbols) == (
        ("src/b.py", "bar"),
        ("src/c.py", "orphan"),
    )
    # Private _secret is tracked but never in the gap basket.
    assert all(s.is_public for s in report.undocumented_symbols)
    assert _by_name(report, "src/b.py", "_secret") in report.symbols

    # Percentages. Files: 2/3. Public symbols: documented = alpha, GAMMA, Foo,
    # Foo.method (4); total public = those 4 + bar + orphan (6) => 66.67%.
    assert report.percent_files == 2 / 3 * 100
    assert report.percent_public_symbols == 4 / 6 * 100


# --------------------------------------------------------------------------
# unit: each selector kind attributes ownership
# --------------------------------------------------------------------------


def test_whole_file_selector_owns_every_symbol(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    cfg = _config(
        (
            DocumentSpec(
                id="D",
                path="docs/d.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="src/b.py"),),
            ),
        )
    )
    report = resolve_coverage(cfg, inv)
    owned = {s.name for s in report.symbols if s.path == "src/b.py" and s.owners}
    assert owned == {"Foo", "Foo.method", "bar", "_secret"}


def test_symbols_selector_pulls_in_methods(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    report = resolve_coverage(_fixture_config(), inv)
    # Selecting the class Foo by name pulls in Foo.method (via _select).
    assert _by_name(report, "src/b.py", "Foo").owners == ("D2",)
    assert _by_name(report, "src/b.py", "Foo.method").owners == ("D2",)


def test_lines_selector_overlap(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # a.py: alpha is lines 1-3, GAMMA is line 6. A 1..3 range owns alpha only.
    cfg = _config(
        (
            DocumentSpec(
                id="L",
                path="docs/l.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="src/a.py", lines=((1, 3),)),),
            ),
        )
    )
    report = resolve_coverage(cfg, inv)
    assert _by_name(report, "src/a.py", "alpha").owners == ("L",)
    assert _by_name(report, "src/a.py", "GAMMA").owners == ()


def test_names_selector_owns_variable(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    cfg = _config(
        (
            DocumentSpec(
                id="N",
                path="docs/n.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="src/a.py", names=("GAMMA",)),),
            ),
        )
    )
    report = resolve_coverage(cfg, inv)
    assert _by_name(report, "src/a.py", "GAMMA").owners == ("N",)
    assert _by_name(report, "src/a.py", "alpha").owners == ()


def test_shared_file_two_owners_sorted(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # Two docs both reference a.py whole-file; owners is sorted + deduped.
    cfg = _config(
        (
            DocumentSpec(
                id="Zeta",
                path="docs/z.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="src/a.py"),),
            ),
            DocumentSpec(
                id="Alpha",
                path="docs/al.md",
                audience=Audience.USER_GUIDE,
                code_refs=(CodeRef(path="src/a.py"),),
            ),
        )
    )
    report = resolve_coverage(cfg, inv)
    afile = next(f for f in report.files if f.path == "src/a.py")
    assert afile.owners == ("Alpha", "Zeta")
    assert _by_name(report, "src/a.py", "alpha").owners == ("Alpha", "Zeta")


def test_ownership_ignores_audience(tmp_path: Path) -> None:
    """A user-guide ref over b.py still covers the PRIVATE _secret symbol.

    Deliberate divergence from build_document_surface, which would drop the
    private symbol for a user-guide. Ownership is "is this code referenced",
    not "is it in the audience-filtered surface".
    """
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    cfg = _config(
        (
            DocumentSpec(
                id="UG",
                path="docs/ug.md",
                audience=Audience.USER_GUIDE,
                code_refs=(CodeRef(path="src/b.py"),),
            ),
        )
    )
    report = resolve_coverage(cfg, inv)
    # Private symbol IS owned (audience ignored)...
    assert _by_name(report, "src/b.py", "_secret").owners == ("UG",)
    # ...but never appears in the public gap/documented baskets.
    assert _by_name(report, "src/b.py", "_secret") not in report.documented_symbols
    assert _by_name(report, "src/b.py", "_secret") not in report.undocumented_symbols


def test_private_excluded_from_gap_basket_but_tracked(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # No documents at all -> everything is unowned.
    report = resolve_coverage(_config(()), inv)
    secret = _by_name(report, "src/b.py", "_secret")
    assert secret in report.symbols  # tracked (lossless)
    assert secret not in report.undocumented_symbols  # not a gap target
    assert not secret.is_public


def test_empty_repo_is_100_percent(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    inv = _inventory(root)
    report = resolve_coverage(_config(()), inv)
    assert report.files == ()
    assert report.symbols == ()
    assert report.percent_files == 100.0
    assert report.percent_public_symbols == 100.0


def test_repo_with_only_private_symbols_is_100_percent(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "p.py").write_text("def _x() -> None: ...\n", encoding="utf-8")
    inv = _inventory(root)
    report = resolve_coverage(_config(()), inv)
    # File is an undocumented gap, but there are zero PUBLIC symbols, so the
    # public-symbol metric is vacuously 100% (no zero-division).
    assert report.percent_public_symbols == 100.0
    assert report.percent_files == 0.0


# --------------------------------------------------------------------------
# determinism (K10)
# --------------------------------------------------------------------------


def test_deterministic_same_inputs_same_report(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    cfg = _fixture_config()
    assert resolve_coverage(cfg, inv) == resolve_coverage(cfg, inv)


def test_models_are_frozen_and_forbid_extra() -> None:
    import pytest
    from pydantic import ValidationError

    of = OwnedFile(path="x", language="python", owners=())
    with pytest.raises(ValidationError):
        of.path = "y"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        OwnedSymbol(  # type: ignore[call-arg]
            path="x", name="n", kind="function", is_public=True, owners=(), bogus=1
        )


# --------------------------------------------------------------------------
# A-04 — waivers: fold config.coverage.waive into the report
# --------------------------------------------------------------------------


def _waived_config(
    documents: tuple[DocumentSpec, ...], waive: tuple[WaiverEntry, ...]
) -> MonitorConfig:
    return MonitorConfig(documents=documents, coverage=CoverageConfig(waive=waive))


def test_symbol_waiver_moves_gap_to_waived_and_lifts_percent(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # Baseline (A-03 fixture): bar in b.py and orphan in c.py are the 2 gaps;
    # percent_public_symbols == 4/6.
    base = resolve_coverage(_fixture_config(), inv)
    assert base.percent_public_symbols == 4 / 6 * 100

    # Waive b.py's bar with a reason.
    waiver = WaiverEntry(path="src/b.py", symbol="bar", reason="legacy shim")
    docs = _fixture_config().documents
    report = resolve_coverage(_waived_config(docs, (waiver,)), inv)

    bar = _by_name(report, "src/b.py", "bar")
    # bar leaves the gap basket, enters the waived basket WITH its reason.
    assert bar not in report.undocumented_symbols
    assert bar in report.waived_symbols
    assert bar.waived_reason == "legacy shim"
    # Only orphan remains a gap.
    assert tuple((s.path, s.name) for s in report.undocumented_symbols) == (
        ("src/c.py", "orphan"),
    )
    # Universe drops bar from BOTH sides: 4 documented / 5 public = 80%.
    assert report.percent_public_symbols == 4 / 5 * 100


def test_whole_file_waiver_waives_file_and_all_its_symbols(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # Whole-file waiver (symbol=None) of the unreferenced c.py.
    waiver = WaiverEntry(path="src/c.py", reason="generated, not documented")
    docs = _fixture_config().documents
    report = resolve_coverage(_waived_config(docs, (waiver,)), inv)

    cfile = next(f for f in report.files if f.path == "src/c.py")
    assert cfile in report.waived_files
    assert cfile not in report.undocumented_files
    assert cfile.waived_reason == "generated, not documented"

    orphan = _by_name(report, "src/c.py", "orphan")
    assert orphan in report.waived_symbols
    assert orphan not in report.undocumented_symbols
    assert orphan.waived_reason == "generated, not documented"

    # Now only bar is a gap; files universe drops c.py: 2 documented / 2 = 100%.
    assert tuple((s.path, s.name) for s in report.undocumented_symbols) == (
        ("src/b.py", "bar"),
    )
    assert report.percent_files == 100.0


def test_glob_path_waiver_matches(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # A glob over src/*.py + symbol orphan waives c.py's orphan only.
    waiver = WaiverEntry(path="src/*.py", symbol="orphan", reason="scratch")
    docs = _fixture_config().documents
    report = resolve_coverage(_waived_config(docs, (waiver,)), inv)
    orphan = _by_name(report, "src/c.py", "orphan")
    assert orphan in report.waived_symbols
    assert orphan.waived_reason == "scratch"


def test_waiver_on_documented_symbol_is_inert(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # alpha in a.py is owned by D1 (documented). Waiving it is a no-op: it stays
    # documented, does NOT enter the waived basket, percentages unchanged.
    waiver = WaiverEntry(path="src/a.py", symbol="alpha", reason="should not apply")
    docs = _fixture_config().documents
    report = resolve_coverage(_waived_config(docs, (waiver,)), inv)
    alpha = _by_name(report, "src/a.py", "alpha")
    assert alpha in report.documented_symbols
    assert alpha not in report.waived_symbols
    assert alpha.waived_reason is None
    # Identical to the un-waived fixture report.
    assert report.percent_public_symbols == 4 / 6 * 100


def test_non_matching_waiver_is_silently_inert(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # A waiver matching no file/symbol does NOT raise (A-04: silent-inert) and
    # leaves the report identical to A-03.
    waiver = WaiverEntry(path="src/nope.py", symbol="ghost", reason="stale")
    docs = _fixture_config().documents
    report = resolve_coverage(_waived_config(docs, (waiver,)), inv)
    assert report.waived_symbols == ()
    assert report.waived_files == ()
    assert report.percent_public_symbols == 4 / 6 * 100


def test_private_symbol_is_not_waivable_into_public_basket(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # _secret is private — even an explicit waiver does not surface it in the
    # public waived basket (private symbols are never doc targets / gaps).
    waiver = WaiverEntry(path="src/b.py", symbol="_secret", reason="private")
    docs = _fixture_config().documents
    report = resolve_coverage(_waived_config(docs, (waiver,)), inv)
    assert all(s.is_public for s in report.waived_symbols)
    secret = _by_name(report, "src/b.py", "_secret")
    assert secret not in report.waived_symbols


def test_default_empty_waive_is_identical_to_a03(tmp_path: Path) -> None:
    # The additive guarantee at the resolver level: an explicit empty waive
    # yields the exact same report as the A-03 path (no coverage section).
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    a03 = resolve_coverage(_fixture_config(), inv)
    a04 = resolve_coverage(_waived_config(_fixture_config().documents, ()), inv)
    assert a03 == a04


# --------------------------------------------------------------------------
# A-07 — suggest_owners: deterministic gap→owner heuristic (no Backend, no LLM)
# --------------------------------------------------------------------------


def _suggestions(report: CoverageReport, config: MonitorConfig):
    return suggest_owners(report, config)


def test_sibling_owned_file_suggests_existing_doc(tmp_path: Path) -> None:
    """A gap in a partly-owned file → the doc already owning a sibling (existing)."""
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    cfg = _fixture_config()  # D2 owns Foo+Foo.method in b.py; sibling bar is a gap
    report = resolve_coverage(cfg, inv)
    sugg = _suggestions(report, cfg)

    bar = next(s for s in sugg if s.path == "src/b.py" and s.name == "bar")
    assert bar.suggested_doc_id == "D2"
    assert bar.is_new_doc is False
    assert "D2" in bar.reason
    assert "sibling" in bar.reason.lower()


def test_sibling_lowest_doc_id_when_several_own(tmp_path: Path) -> None:
    """If several docs own siblings, suggest the LOWEST doc id (deterministic)."""
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    # Two docs both own alpha in a.py (via symbols=); GAMMA stays the public gap.
    # The sibling-suggestion for GAMMA must be the LOWEST owning doc id (Aaa).
    cfg = _config(
        (
            DocumentSpec(
                id="Zed",
                path="docs/z.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="src/a.py", symbols=("alpha",)),),
            ),
            DocumentSpec(
                id="Aaa",
                path="docs/a.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="src/a.py", symbols=("alpha",)),),
            ),
        )
    )
    report = resolve_coverage(cfg, inv)
    sugg = _suggestions(report, cfg)
    gamma = next(s for s in sugg if s.path == "src/a.py" and s.name == "GAMMA")
    assert gamma.suggested_doc_id == "Aaa"  # lowest of {Aaa, Zed}
    assert gamma.is_new_doc is False


def test_fully_unowned_file_proposes_new_doc_grouped(tmp_path: Path) -> None:
    """A fully-unowned file → one proposed new doc id grouping all its gaps."""
    root = tmp_path / "repo"
    (root / "pkg" / "sub").mkdir(parents=True)
    (root / "pkg" / "sub" / "mod.py").write_text(
        "def one() -> None: ...\n\n\ndef two() -> None: ...\n", encoding="utf-8"
    )
    inv = _inventory(root)
    cfg = _config(())  # nothing documented
    report = resolve_coverage(cfg, inv)
    sugg = _suggestions(report, cfg)

    mod = [s for s in sugg if s.path == "pkg/sub/mod.py"]
    assert {s.name for s in mod} == {"one", "two"}
    # Scheme: pkg/sub/mod.py -> pkg-sub-mod (drop .py, '/'->'-'); grouped + new.
    assert all(s.suggested_doc_id == "pkg-sub-mod" for s in mod)
    assert all(s.is_new_doc is True for s in mod)
    assert all("pkg/sub/mod.py" in s.reason for s in mod)


def test_private_gaps_not_suggested(tmp_path: Path) -> None:
    """Private symbols are never suggested (they are not doc targets)."""
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    cfg = _config(())
    report = resolve_coverage(cfg, inv)
    sugg = _suggestions(report, cfg)
    assert all(s.name != "_secret" for s in sugg)
    # Only public gaps appear.
    gap_names = {(s.path, s.name) for s in report.undocumented_symbols}
    assert all((s.path, s.name) in gap_names for s in sugg)


def test_waived_gaps_not_suggested(tmp_path: Path) -> None:
    """A waived public gap is excused, so it produces no suggestion."""
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    waiver = WaiverEntry(path="src/b.py", symbol="bar", reason="legacy")
    cfg = _waived_config(_fixture_config().documents, (waiver,))
    report = resolve_coverage(cfg, inv)
    sugg = _suggestions(report, cfg)
    assert all(s.name != "bar" for s in sugg)


def test_suggestions_sorted_by_path_then_name(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    cfg = _config(())  # all public symbols are gaps
    report = resolve_coverage(cfg, inv)
    sugg = _suggestions(report, cfg)
    keys = [(s.path, s.name or "") for s in sugg]
    assert keys == sorted(keys)


def test_suggest_owners_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    cfg = _fixture_config()
    report = resolve_coverage(cfg, inv)
    assert suggest_owners(report, cfg) == suggest_owners(report, cfg)


def test_owner_suggestion_is_frozen_and_forbids_extra() -> None:
    import pytest
    from pydantic import ValidationError

    s = OwnerSuggestion(
        path="x", name="n", suggested_doc_id="D", is_new_doc=False, reason="r"
    )
    with pytest.raises(ValidationError):
        s.path = "y"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        OwnerSuggestion(  # type: ignore[call-arg]
            path="x",
            name=None,
            suggested_doc_id="D",
            is_new_doc=True,
            reason="r",
            bogus=1,
        )


# --------------------------------------------------------------------------
# T-02 — coverage_snapshot: the serializable wire shape (pure, K10)
# --------------------------------------------------------------------------


def test_coverage_snapshot_top_level_shape(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    report = resolve_coverage(_fixture_config(), inv)
    snap = coverage_snapshot(report)

    assert snap["schema_version"] == "1.0.0"
    assert snap["percent_files"] == report.percent_files
    assert snap["percent_public_symbols"] == report.percent_public_symbols
    # ratio is percent_public_symbols / 100 (back-compat for _compute_status).
    assert snap["ratio"] == report.percent_public_symbols / 100
    # FILE basket counts mirror the report properties.
    assert snap["documented"] == len(report.documented_files)
    assert snap["undocumented"] == len(report.undocumented_files)
    assert snap["waived"] == len(report.waived_files)


def test_coverage_snapshot_files_one_per_file_with_status(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    report = resolve_coverage(_fixture_config(), inv)
    snap = coverage_snapshot(report)

    files = snap["files"]
    # One dict per inventory file, in the report's path-sorted order (K10).
    assert [f["path"] for f in files] == [f.path for f in report.files]

    by_path = {f["path"]: f for f in files}
    # a.py documented (owned by D1), b.py documented (D2), c.py undocumented.
    assert by_path["src/a.py"]["status"] == "documented"
    assert by_path["src/a.py"]["owners"] == ["D1"]
    assert by_path["src/a.py"]["language"] == "python"
    assert by_path["src/a.py"]["waived_reason"] is None
    assert by_path["src/b.py"]["status"] == "documented"
    assert by_path["src/b.py"]["owners"] == ["D2"]
    assert by_path["src/c.py"]["status"] == "undocumented"
    assert by_path["src/c.py"]["owners"] == []
    assert by_path["src/c.py"]["waived_reason"] is None


def test_coverage_snapshot_waived_file_shows_reason(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    waiver = WaiverEntry(path="src/c.py", reason="generated, not documented")
    docs = _fixture_config().documents
    report = resolve_coverage(_waived_config(docs, (waiver,)), inv)
    snap = coverage_snapshot(report)

    by_path = {f["path"]: f for f in snap["files"]}
    assert by_path["src/c.py"]["status"] == "waived"
    assert by_path["src/c.py"]["waived_reason"] == "generated, not documented"
    assert by_path["src/c.py"]["owners"] == []
    # Basket counts reflect the waiver: c.py left the undocumented basket.
    assert snap["waived"] == 1
    assert snap["undocumented"] == 0


def test_coverage_snapshot_is_json_safe_and_deterministic(tmp_path: Path) -> None:
    import json

    root = tmp_path / "repo"
    _build_repo(root)
    inv = _inventory(root)
    report = resolve_coverage(_fixture_config(), inv)
    snap = coverage_snapshot(report)
    # Round-trips through JSON unchanged (JSON-safe), and is deterministic (K10).
    assert json.loads(json.dumps(snap)) == snap
    assert coverage_snapshot(report) == coverage_snapshot(report)


def test_coverage_snapshot_empty_repo(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    inv = _inventory(root)
    report = resolve_coverage(_config(()), inv)
    snap = coverage_snapshot(report)
    assert snap["files"] == []
    assert snap["documented"] == snap["undocumented"] == snap["waived"] == 0
    assert snap["percent_files"] == 100.0
    assert snap["ratio"] == 1.0


# --------------------------------------------------------------------------- #
# _proposed_doc_id — the A-07 deterministic gap→doc-id scheme (K10)
# --------------------------------------------------------------------------- #
def test_proposed_doc_id_strips_py_suffix_and_joins_path() -> None:
    # `pkg/sub/mod.py` -> `pkg-sub-mod`: drop a .py/.pyi suffix, '/' -> '-'.
    assert _proposed_doc_id("pkg/sub/mod.py") == "pkg-sub-mod"
    assert _proposed_doc_id("a/b/stub.pyi") == "a-b-stub"


def test_proposed_doc_id_leaves_non_python_path_suffix_intact() -> None:
    # A path with neither .py nor .pyi keeps its name (only '/' is rewritten),
    # so the scheme stays total over any file the owner-suggester is handed.
    assert _proposed_doc_id("scripts/run.sh") == "scripts-run.sh"
    assert _proposed_doc_id("Makefile") == "Makefile"
