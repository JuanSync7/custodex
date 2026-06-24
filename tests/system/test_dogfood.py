"""Dogfood (CDM-07): custodex monitors its OWN source against its docs.

cdmon's canonical self-config is the CONFIG-V2 multi-file ``config/cdmon/`` dir
layout (Z-02 removed the redundant single-file root ``cdmon.yaml``). The units
under ``config/cdmon/`` map this package's modules onto the engineering docs in
``docs/api/`` (with ``schema.py`` as a shared file referenced two ways). These
tests prove (a) the real dir-layout config resolves against the real code and the
checked-in docs are in sync, and (b) the full self-heal loop works on the real
project when the code changes — exercised on a copy so the repo is untouched.

The single-file ``load_config`` path is the supported BACK-COMPAT surface; it is
covered here by ``test_dogfood_single_file_back_compat_loads`` against a SEPARATE
fixture (``examples/external-repo/cdmon.yaml``) and more broadly by
``tests/test_example_external.py`` / ``tests/test_config.py``.

Features: FEAT-CLI-002, FEAT-CONFIG-003, FEAT-CONFIG-008, FEAT-CONFIG-009
Features: FEAT-CONFIGV2-001, FEAT-CONFIGV2-003, FEAT-CONFIGV2-008, FEAT-CONFIGV2-016
Features: FEAT-CONFIGV2-009, FEAT-EXTRACT-001, FEAT-DRIFT-001, FEAT-MONITOR-002
Features: FEAT-MONITOR-003, FEAT-HEAL-001, FEAT-COVERAGE-007, FEAT-COVERAGE-008
Features: FEAT-LAYOUT-001, FEAT-LAYOUT-002, FEAT-LAYOUT-006
"""

from __future__ import annotations

import shutil
from pathlib import Path

from custodex import inventory
from custodex.cli import _blank_updated
from custodex.config import (
    load_bundle,
    load_config,
    load_config_dir,
    regenerate_index,
)
from custodex.coverage import resolve_coverage
from custodex.extract import build_document_surface
from custodex.monitor import Monitor
from tests._repo import REPO_ROOT

_ROOT = REPO_ROOT
# cdmon's canonical self-config: the CONFIG-V2 dir layout (Z-02; root cdmon.yaml
# removed). ``Monitor``'s second arg is the CONFIG DIR — it derives the repo root
# via the ONE resolve_repo_root(config_dir, root) formula (root="../.." ⇒ repo).
_CONFIG_DIR = _ROOT / "config" / "cdmon"
# A SEPARATE single-file fixture exercising the back-compat ``load_config`` path
# (NOT cdmon's own config — that is the dir layout now).
_SINGLE_FILE_FIXTURE = _ROOT / "examples" / "external-repo" / "cdmon.yaml"

# H-02: the committed self-coverage floor — the SAME threshold the CI
# `cdx coverage --fail-under` gate uses (kept a couple points below the
# achieved 100% for headroom). This test makes the self-improvement durable:
# if a new engine module's public symbols land undocumented, self-coverage
# drops and this fails before it can silently regress.
_COVERAGE_THRESHOLD = 95.0


def _copy_dogfood_tree(dst: Path) -> Path:
    """Copy the engine + docs + dir-layout config + templates into ``dst``.

    Mirrors what the dir layout needs to resolve on a temp copy: the package,
    the docs it manages, the ``config/cdmon/`` directory, the
    ``templates/writing/`` tree the ``doc-style.yaml`` pointer resolves against
    (root="../.." ⇒ the copied repo root), and the repo-root ``README.md`` (a
    tracked user-guide document, FEAT-CONFIGV2-016). Returns the copied
    ``config/cdmon``.
    """
    dst.mkdir(exist_ok=True)
    shutil.copytree(_ROOT / "custodex", dst / "custodex")
    shutil.copytree(_ROOT / "docs", dst / "docs")
    shutil.copytree(_ROOT / "config", dst / "config")
    shutil.copytree(_ROOT / "templates", dst / "templates")
    shutil.copy2(_ROOT / "README.md", dst / "README.md")
    # The `tests` unit (FEAT-CONFIGV2-017) mirrors test files → test-docs: its
    # docs live under test-docs/ and its code_refs point at tests/smoke/, so both
    # trees must come along for the surfaces to resolve on the copy.
    shutil.copytree(_ROOT / "test-docs", dst / "test-docs")
    shutil.copytree(_ROOT / "tests" / "smoke", dst / "tests" / "smoke")
    return dst / "config" / "cdmon"


def test_dogfood_config_loads() -> None:
    cfg = load_config_dir(_CONFIG_DIR)
    assert cfg.documents
    # the shared file is referenced by more than one document
    refs = [(d.id, r.path) for d in cfg.documents for r in d.code_refs]
    shared = [p for _id, p in refs if p.endswith("schema.py")]
    assert len(shared) >= 2, "schema.py should be a shared, multiply-referenced file"


def test_dogfood_central_client_carries_context_refs() -> None:
    """EDITOR E-12: cdmon's own `central-client` doc declares a `context_refs`
    glance-through reference to the `server` doc — additive (K6), NOT a code_ref
    and NOT coverage, so it must NOT appear in the documented surface."""
    cfg = load_config_dir(_CONFIG_DIR)
    spec = next(d for d in cfg.documents if d.id == "central-client")
    paths = {r.path for r in spec.context_refs}
    assert "docs/api/server.md" in paths
    # Every context ref carries an honest, non-empty note; none is a code_ref.
    assert all(r.note for r in spec.context_refs)
    assert "docs/api/server.md" not in {r.path for r in spec.code_refs}


def test_dogfood_surfaces_resolve_against_real_code() -> None:
    cfg = load_config_dir(_CONFIG_DIR)
    for spec in cfg.documents:
        if not spec.code_refs:
            continue  # an index/collection doc has no code surface of its own
        surface = build_document_surface(spec, _ROOT)
        assert surface.symbols, f"{spec.id}: no symbols extracted from real code"


def test_dogfood_docs_are_in_sync() -> None:
    """The checked-in docs match the checked-in code (`cdx monitor --apply`)."""
    cfg = load_config_dir(_CONFIG_DIR)
    report = Monitor(cfg, _CONFIG_DIR).check()
    assert report.ok, report.summary()


def test_dogfood_self_heals_on_a_copy(tmp_path: Path) -> None:
    # Copy the package + docs + config + templates so the real repo is never
    # mutated.
    dst = tmp_path / "proj"
    config_dir = _copy_dogfood_tree(dst)
    cfg = load_config_dir(config_dir)

    assert Monitor(cfg, config_dir).check().ok  # copy starts clean

    # Mutate a real source file: add a public function to config.py.
    target = dst / "custodex" / "config.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\n\ndef brand_new_public_helper(x: int) -> int:\n    return x\n",
        encoding="utf-8",
    )
    assert not Monitor(cfg, config_dir).check().ok  # drift detected

    result = Monitor(cfg, config_dir, now=lambda: "2026-06-01T00:00:00Z").run(
        apply=True
    )
    assert result.records  # a verdict was recorded for review
    assert Monitor(cfg, config_dir).check().ok  # fully self-healed


def _dogfood_coverage_report() -> object:
    """Resolve the real dogfood coverage report exactly as `cdx coverage` does."""
    cfg = load_config_dir(_CONFIG_DIR)
    root = _CONFIG_DIR / cfg.root
    inv = inventory.discover_files(
        root,
        include=cfg.coverage.include,
        exclude=cfg.coverage.exclude,
    )
    sym = inventory.discover_symbols(inv, root)
    return resolve_coverage(cfg, sym)


def test_dogfood_self_coverage_meets_committed_threshold() -> None:
    """H-02: engine public-symbol self-coverage stays >= the committed floor.

    Mirrors the CI `cdx coverage --fail-under` gate so the self-improvement
    cannot silently regress: a new undocumented engine symbol drops the % below
    the threshold and fails here (and in CI) until it is documented or waived.
    """
    report = _dogfood_coverage_report()
    pct = report.percent_public_symbols  # type: ignore[attr-defined]
    assert pct >= _COVERAGE_THRESHOLD, (
        f"engine self-coverage {pct:.1f}% < committed {_COVERAGE_THRESHOLD}%; "
        "document the new public symbols (or waive with a reason in a unit file)"
    )


def test_dogfood_every_waiver_carries_a_reason() -> None:
    """Each coverage waiver justifies itself (A-04/K8) — losslessness is explicit."""
    report = _dogfood_coverage_report()
    waived = report.waived_symbols  # type: ignore[attr-defined]
    for sym in waived:
        assert sym.waived_reason, f"waived {sym.path}::{sym.name} has no reason"


def test_dogfood_dir_layout_loads_and_is_in_sync() -> None:
    """Z-01b/Z-02: cdmon's own ``config/cdmon/`` dir layout loads + the checked-in
    docs are in sync under it (the canonical self-config since Z-02)."""
    bundle = load_bundle(_CONFIG_DIR)
    assert bundle.config.documents
    # Monitor's second arg is the CONFIG DIR; it derives the repo root via the ONE
    # resolve_repo_root(config_dir, root) formula (root="../.." ⇒ the repo).
    report = Monitor(bundle.config, _CONFIG_DIR).check()
    assert report.ok, report.summary()


def test_dogfood_own_index_is_in_sync() -> None:
    """cdmon's OWN ``config/cdmon/index.yaml`` passes its own ``index --check``.

    Regression guard for Z-04: the shipped index's ``units:`` list MUST match what
    ``regenerate_index`` emits (alphabetical), or ``cdx index --check`` (the CI
    gate) exits 1 — yet the shipped file shipped out of sync because no test
    covered the dogfood index itself. This exercises the SAME codepath the
    ``index --check`` CLI uses: compare the on-disk text to a freshly regenerated
    one with the wall-clock ``updated:`` line blanked on both sides (so a pure
    timestamp delta is not drift, N-06). A real units-list change fails here.
    """
    on_disk = (_CONFIG_DIR / "index.yaml").read_text(encoding="utf-8")
    regenerated = regenerate_index(_CONFIG_DIR)
    assert _blank_updated(on_disk) == _blank_updated(regenerated), (
        "config/cdmon/index.yaml is OUT OF SYNC with regenerate_index — run "
        "`cdx index` (the units: list must be alphabetical) and reheal the docs"
    )


def test_dogfood_single_file_back_compat_loads() -> None:
    """Z-02: the single-file ``load_config`` path remains a SUPPORTED back-compat
    capability — proven against a SEPARATE fixture (an external-repo adopter),
    NOT cdmon's own config (which is the dir layout now).

    Keeps coverage of ``load_config`` even though cdx no longer ships a
    single-file ``cdmon.yaml``: a typo'd or removed loader would red here.
    """
    cfg = load_config(_SINGLE_FILE_FIXTURE)
    assert cfg.documents
    assert all(d.id for d in cfg.documents)


def test_dogfood_docs_conform_to_layout_standard() -> None:
    """CDM-08: the checked-in docs satisfy the Document Layout Standard."""
    from custodex.layout import lint_config

    cfg = load_config_dir(_CONFIG_DIR)
    issues = lint_config(cfg, _ROOT)
    assert issues == [], [f"{i.doc_id}: {i.code.value} — {i.detail}" for i in issues]


def test_dogfood_readme_is_a_monitored_user_guide_doc() -> None:
    """FEAT-CONFIGV2-016: cdmon's own README.md is a monitored narrative document.

    It is declared as a ``user-guide`` document with code_refs to the CLI surface
    it documents and NO managed region (the engine never authors README prose, K2),
    so it is tracked by the whole-doc fingerprint over that surface. The eng-only
    ``api-index`` is NOT flagged for omitting it — its ``kind: eng-guide`` audience
    scope excludes a user-guide doc (the INDEX_INCOMPLETE refinement)."""
    from custodex.config import Audience
    from custodex.layout import LayoutCode, _index_coverage_issues

    cfg = load_config_dir(_CONFIG_DIR)
    readme = next(d for d in cfg.documents if d.id == "readme")
    assert readme.path == "README.md"
    assert readme.audience is Audience.USER_GUIDE
    assert readme.region_keys == ()  # no managed region — fingerprint-tracked only
    assert "custodex/cli.py" in {r.path for r in readme.code_refs}
    # It tracks a real surface (cli.py has public commands to fingerprint).
    surface = build_document_surface(readme, _ROOT)
    assert surface.symbols, "readme: no symbols extracted from the CLI surface"
    # The eng-only api-index is not required to link the user-guide README.
    bad = [
        i
        for i in _index_coverage_issues(cfg, _ROOT)
        if i.code is LayoutCode.INDEX_INCOMPLETE
    ]
    assert bad == [], [i.detail for i in bad]


def test_dogfood_readme_drifts_on_public_cli_change_and_reheals(tmp_path: Path) -> None:
    """FEAT-CONFIGV2-016 (K3/K5): a PUBLIC ``cli.py`` change drifts the user-guide
    README; ``monitor --apply`` reheals its fingerprint WITHOUT touching the prose
    (the engine never authors a README, and a ReviewRecord captures the change)."""
    dst = tmp_path / "proj"
    config_dir = _copy_dogfood_tree(dst)
    cfg = load_config_dir(config_dir)
    assert Monitor(cfg, config_dir).check().ok  # copy starts clean

    readme_path = dst / "README.md"
    original = readme_path.read_text(encoding="utf-8")

    # Add a PUBLIC command-shaped function to cli.py: the user-guide surface moves.
    cli = dst / "custodex" / "cli.py"
    cli.write_text(
        cli.read_text(encoding="utf-8")
        + "\n\ndef brand_new_public_command(name: str) -> str:\n"
        '    """A brand new public command."""\n    return name\n',
        encoding="utf-8",
    )
    drifts = Monitor(cfg, config_dir).check().drifts
    assert any(d.doc_id == "readme" and d.kind.value == "HASH" for d in drifts), (
        "a public CLI surface change must drift the user-guide README"
    )

    result = Monitor(cfg, config_dir, now=lambda: "2026-06-01T00:00:00Z").run(
        apply=True
    )
    assert result.records  # a ReviewRecord was written for the human (K5)
    assert Monitor(cfg, config_dir).check().ok  # fully rehealed

    # Only the front-matter fingerprint moved — the prose body is byte-identical.
    healed = readme_path.read_text(encoding="utf-8")
    assert original.split("## Why", 1)[1] == healed.split("## Why", 1)[1]


def test_dogfood_api_index_is_a_landing_page_that_links_every_doc() -> None:
    """The api-index doc is declared `index: true`, and the active INDEX_INCOMPLETE
    lint it turns on holds: the landing page links every OTHER document. Removing
    a doc's link (or adding an unlinked doc) is then caught by CI."""
    from custodex.layout import LayoutCode, _index_coverage_issues

    cfg = load_config_dir(_CONFIG_DIR)
    landing = [s for s in cfg.documents if s.index]
    assert [s.id for s in landing] == ["api-index"], (
        "exactly the api-index doc should be the declared landing page"
    )
    issues = _index_coverage_issues(cfg, _ROOT)
    assert [i for i in issues if i.code is LayoutCode.INDEX_INCOMPLETE] == []
