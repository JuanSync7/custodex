"""Unit tests for ``custodex.mcp.tools`` — the pure MCP projection logic.

These import ONLY the pure ``tools`` layer (no ``mcp`` SDK), proving the
boundary: the projections + config resolution test even in a core-only install.
Covers the enriched status fold, both ``load_repo_bundle`` layouts + the loud
no-config path, ``resolve_repo_id``, and the seven MCP-01 read helpers
(drift/coverage/ownership/staleness/worklist/doc-graph/records) — each with a
clean case and its drifted/gap/stale/suspect/orphan case, deterministic ``now``,
cap/truncation flags, and the loud typed error paths.

Features: FEAT-MCP-001
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from custodex.blocks import symbol_table
from custodex.config import (
    Audience,
    CodeRef,
    DocDepsConfig,
    DocEdge,
    DocumentSpec,
    MonitorConfig,
    write_template,
)
from custodex.docdeps import stamp_edges
from custodex.drift import DriftKind
from custodex.errors import CodeDocMonitorError, McpError
from custodex.extract import build_document_surface
from custodex.manifest import render_doc, set_fingerprint, set_region
from custodex.mcp.tools import (
    CoverageSummary,
    DocGraph,
    DriftDetail,
    DriftItem,
    OwnershipSummary,
    RecordList,
    RemediationItem,
    RemediationResult,
    ResolutionResult,
    StalenessSummary,
    StatusSummary,
    SyncDocsResult,
    WorklistSummary,
    _fix_preview,
    coverage_summary,
    doc_graph_summary,
    drift_detail,
    list_records,
    load_repo_bundle,
    ownership_summary,
    remediate_drift,
    resolve_drift,
    resolve_repo_id,
    staleness_summary,
    status_summary,
    sync_docs,
    worklist_summary,
)
from custodex.monitor import DEFAULT_LOG_PATH
from custodex.ownership import Identity, RosterSnapshot
from custodex.reviewlog import (
    DEFAULT_RESOLUTIONS_PATH,
    append,
    read_all,
    read_resolutions,
    resolved_index,
)
from custodex.schema import ProposedFix, Resolution, ReviewRecord, Verdict
from custodex.templates_v2 import scaffold_config_dir

# A fixed as-of date so the staleness/worklist folds are deterministic (K10).
NOW = "2026-06-01T00:00:00+00:00"

CODE_V1 = '''\
def greet(name: str) -> str:
    """Say hello."""
    return f"hi {name}"
'''

# The public signature changed (a new parameter) → the symbol region + the
# surface fingerprint both drift (an eng-guide surface change, K3).
CODE_V2 = '''\
def greet(name: str, loud: bool) -> str:
    """Say hello."""
    return f"hi {name}"
'''


def _synced_repo(tmp_path: Path) -> MonitorConfig:
    """A one-doc repo whose region + fingerprint match CODE_V1 (in sync)."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(CODE_V1, encoding="utf-8")
    spec = DocumentSpec(
        id="api",
        path="docs/api.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
    )
    surface = build_document_surface(spec, root)
    body = "# API\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")
    return MonitorConfig(root="repo", documents=(spec,))


def test_status_summary_clean(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert isinstance(summary, StatusSummary)
    assert summary.repo_id == "demo"
    assert summary.clean is True
    assert summary.drift_total == 0
    assert summary.code_doc_drift == 0
    assert summary.suspect_link_drift == 0
    assert summary.doc_count == 1
    assert "clean" in summary.summary.lower()
    # MCP-01 enrichment: the 4-pillar counts must AGREE with the dedicated
    # helpers (the overview never disagrees with the drill-down tools).
    cov = coverage_summary(cfg, tmp_path, repo_id="demo")
    own = ownership_summary(cfg, tmp_path, repo_id="demo")
    stale = staleness_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert summary.coverage_file_pct == cov.percent_files
    assert summary.coverage_symbol_pct == cov.percent_public_symbols
    assert summary.docs_unowned == own.unowned_count
    assert summary.docs_needing_review == stale.needs_review_total


def test_status_summary_flags_code_doc_drift(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    # Mutate the public signature → the doc's symbol region + fingerprint drift.
    (tmp_path / "repo" / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert summary.clean is False
    assert summary.drift_total >= 1
    assert summary.code_doc_drift >= 1
    assert summary.suspect_link_drift == 0
    # The counts partition the total (no double-counting).
    assert summary.code_doc_drift + summary.suspect_link_drift == summary.drift_total


def test_status_summary_counts_suspect_link_drift(tmp_path: Path) -> None:
    # A doc↔doc edge (api depends_on overview) goes SUSPECT when the upstream body
    # moves — exercises the code↔doc vs doc↔doc split with suspect_link_drift != 0
    # (so a one-sided miscount of the split can't survive; the code↔doc side is
    # covered by test_status_summary_flags_code_doc_drift).
    overview = DocumentSpec(
        id="overview", path="overview.md", audience=Audience.ENG_GUIDE
    )
    api = DocumentSpec(
        id="api",
        path="api.md",
        audience=Audience.USER_GUIDE,
        depends_on=(DocEdge(doc="overview"),),
    )
    cfg = MonitorConfig(
        root=".", documents=(overview, api), docdeps=DocDepsConfig(enabled=True)
    )

    def _managed(spec: DocumentSpec, body: str) -> None:
        surface = build_document_surface(spec, tmp_path)
        meta = set_fingerprint({}, surface.surface_hash())
        (tmp_path / spec.path).write_text(render_doc(meta, body), encoding="utf-8")

    _managed(overview, "# Overview\nupstream\n")
    _managed(api, "# API\ndownstream\n")
    stamp_edges(cfg, tmp_path, "api")  # baseline the edge → starts OK
    assert status_summary(cfg, tmp_path, repo_id="demo", now=NOW).clean is True

    _managed(overview, "# Overview\nUPSTREAM MOVED\n")  # move the upstream body
    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert summary.clean is False
    assert summary.suspect_link_drift >= 1
    assert summary.code_doc_drift == 0  # the ONLY drift is the doc↔doc suspect link
    assert summary.code_doc_drift + summary.suspect_link_drift == summary.drift_total


def test_status_enrichment_coverage_axes_map_correctly(tmp_path: Path) -> None:
    # An ASYMMETRIC repo: `extra.py` has two undocumented public symbols, so
    # file% (1/2) != symbol% (1/3). A swapped file%↔symbol% mapping can't survive.
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "extra.py").write_text(
        "def one():\n    return 1\n\n\ndef two():\n    return 2\n", encoding="utf-8"
    )
    cov = coverage_summary(cfg, tmp_path, repo_id="demo")
    assert cov.percent_files != cov.percent_public_symbols  # genuinely asymmetric
    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert summary.coverage_available is True
    assert summary.coverage_file_pct == cov.percent_files
    assert summary.coverage_symbol_pct == cov.percent_public_symbols


def test_status_enrichment_ownership_staleness_map_correctly(tmp_path: Path) -> None:
    # An ASYMMETRIC repo: unowned (2) != needs-review (1), so a swapped
    # docs_unowned↔docs_needing_review mapping can't survive.
    docs = (
        # owned + fresh → neither unowned nor needs-review
        DocumentSpec(
            id="a",
            path="a.md",
            audience=Audience.ENG_GUIDE,
            owner="alice",
            reviewed="2026-05-30T00:00:00+00:00",
        ),
        # unowned + fresh → unowned only
        DocumentSpec(
            id="b",
            path="b.md",
            audience=Audience.ENG_GUIDE,
            reviewed="2026-05-30T00:00:00+00:00",
        ),
        # unowned + never-reviewed → both
        DocumentSpec(id="c", path="c.md", audience=Audience.ENG_GUIDE),
    )
    cfg = MonitorConfig(root=".", documents=docs)
    for doc in docs:
        (tmp_path / doc.path).write_text("# doc\n", encoding="utf-8")
    own = ownership_summary(cfg, tmp_path, repo_id="demo")
    stale = staleness_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert own.unowned_count == 2
    assert stale.needs_review_total == 1
    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert summary.docs_unowned == own.unowned_count
    assert summary.docs_needing_review == stale.needs_review_total


def test_status_summary_degrades_on_coverage_parse_error(tmp_path: Path) -> None:
    # An unparseable in-scope .py file must NOT abort the "call first" overview:
    # coverage degrades to an honest partial while the other pillars still answer,
    # and the dedicated coverage tool stays loud (K8).
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "broken.py").write_text("def (:\n", encoding="utf-8")
    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert summary.coverage_available is False
    assert summary.coverage_file_pct == -1.0
    assert summary.coverage_symbol_pct == -1.0
    assert summary.doc_count == 1  # the other pillars are still populated
    with pytest.raises(CodeDocMonitorError):
        coverage_summary(cfg, tmp_path, repo_id="demo")


def test_load_repo_bundle_single_file(tmp_path: Path) -> None:
    write_template(tmp_path / "cdmon.yaml")
    cfg, config_dir = load_repo_bundle(tmp_path)
    assert isinstance(cfg, MonitorConfig)
    assert config_dir == tmp_path


def test_load_repo_bundle_dir_layout(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "cdmon"
    scaffold_config_dir(config_dir, repo="demo", now="2026-01-01T00:00:00+00:00")
    cfg, resolved_dir = load_repo_bundle(tmp_path)
    assert isinstance(cfg, MonitorConfig)
    assert resolved_dir == config_dir


def test_load_repo_bundle_no_config_is_loud(tmp_path: Path) -> None:
    with pytest.raises(McpError):
        load_repo_bundle(tmp_path)


def test_resolve_repo_id_from_index(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "cdmon"
    scaffold_config_dir(config_dir, repo="widget", now="2026-01-01T00:00:00+00:00")
    assert resolve_repo_id(tmp_path, config_dir) == "widget"


def test_resolve_repo_id_falls_back_to_dir_name(tmp_path: Path) -> None:
    # No index.yaml under config_dir → the repo directory name is the safe id.
    assert resolve_repo_id(tmp_path, tmp_path) == tmp_path.name


def test_resolve_repo_id_falls_back_when_bundle_load_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An index.yaml is present but the bundle fails to load → the dir name is the
    # safe id (the status detect step surfaces the real config error loudly, K8).
    import custodex.mcp.tools as tools_mod

    config_dir = tmp_path / "config" / "cdmon"
    config_dir.mkdir(parents=True)
    (config_dir / "index.yaml").write_text("repo: broken\n", encoding="utf-8")

    def _boom(_dir: Path) -> object:
        from custodex.errors import ConfigError

        raise ConfigError("malformed bundle")

    monkeypatch.setattr(tools_mod, "load_bundle", _boom)
    assert resolve_repo_id(tmp_path, config_dir) == tmp_path.name


# --- custodex_drift ------------------------------------------------------------


def test_drift_detail_clean_repo(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    detail = drift_detail(cfg, tmp_path, repo_id="demo")
    assert isinstance(detail, DriftDetail)
    assert detail.clean is True
    assert detail.total == 0
    assert detail.items == ()
    assert detail.truncated is False


def test_drift_detail_lists_and_partitions(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    detail = drift_detail(cfg, tmp_path, repo_id="demo")
    assert detail.clean is False
    assert detail.shown == len(detail.items)
    assert all(isinstance(i, DriftItem) for i in detail.items)
    # The signature bump drifts BOTH the surface fingerprint (HASH) and the
    # symbol region (REGION). Pin the exact partition + count (catches a
    # collapsed/mislabelled by_kind bucket), not just the sum.
    assert detail.total == 2
    assert detail.by_kind == {"HASH": 1, "REGION": 1}
    # Deterministic sort (doc_id, region_id or "", kind): HASH (no region) first.
    assert [i.kind for i in detail.items] == ["HASH", "REGION"]
    # Field-level pins — a doc_id / doc_path / message / severity swap can't hide.
    hash_item = next(i for i in detail.items if i.kind == "HASH")
    assert hash_item.doc_id == "api"
    assert hash_item.doc_path == "docs/api.md"
    assert hash_item.audience == "eng-guide"  # K3-visible
    assert hash_item.healable is True
    assert hash_item.region_id is None
    assert hash_item.change_severity == "unknown"
    assert "fingerprint" in hash_item.message
    region_item = next(i for i in detail.items if i.kind == "REGION")
    assert region_item.region_id == "symbols"
    assert "symbols" in region_item.message


def test_drift_detail_cap_truncates(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    detail = drift_detail(cfg, tmp_path, repo_id="demo", limit=0)
    assert detail.shown == 0
    assert detail.truncated is True
    assert detail.total >= 1  # the total is exact regardless of the cap


def test_drift_detail_kind_filter_excludes(tmp_path: Path) -> None:
    # Filtering to a kind that isn't present yields an empty list, but `clean`
    # still reflects the WHOLE repo (there IS code↔doc drift, just not this kind).
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    detail = drift_detail(cfg, tmp_path, repo_id="demo", kind=DriftKind.SUSPECT_LINK)
    assert detail.total == 0
    assert detail.items == ()
    assert detail.clean is False


def test_drift_detail_kind_filter_includes_subset(tmp_path: Path) -> None:
    # A POSITIVE filter: kind=HASH returns strictly the HASH subset (1 of the 2
    # drifts) — a predicate that only over-includes is caught.
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    only_hash = drift_detail(cfg, tmp_path, repo_id="demo", kind=DriftKind.HASH)
    assert only_hash.total == 1
    assert only_hash.by_kind == {"HASH": 1}
    assert all(i.kind == "HASH" for i in only_hash.items)


def test_drift_detail_audience_filter(tmp_path: Path) -> None:
    # The drift is on an ENG_GUIDE doc (K3), so a USER_GUIDE filter removes it
    # while an ENG_GUIDE filter keeps the full set — the predicate runs both ways
    # (a no-op `audience is None or True` filter can't survive).
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    unfiltered = drift_detail(cfg, tmp_path, repo_id="demo")
    user = drift_detail(cfg, tmp_path, repo_id="demo", audience=Audience.USER_GUIDE)
    eng = drift_detail(cfg, tmp_path, repo_id="demo", audience=Audience.ENG_GUIDE)
    assert user.total == 0
    assert eng.total == unfiltered.total >= 1


# --- custodex_coverage ---------------------------------------------------------


def test_coverage_summary_documented(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    cov = coverage_summary(cfg, tmp_path, repo_id="demo")
    assert isinstance(cov, CoverageSummary)
    assert cov.repo_id == "demo"
    assert cov.documented_files >= 1
    assert cov.undocumented_symbols == 0
    assert 0.0 <= cov.percent_public_symbols <= 100.0


def test_coverage_summary_flags_a_gap(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    # A second source file no doc references → its public symbol is a gap.
    (tmp_path / "repo" / "src" / "extra.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8"
    )
    cov = coverage_summary(cfg, tmp_path, repo_id="demo")
    assert cov.undocumented_symbols >= 1
    assert any(g.name == "helper" for g in cov.top_gaps)


def test_coverage_summary_gap_cap(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "extra.py").write_text(
        "def one():\n    return 1\n\n\ndef two():\n    return 2\n", encoding="utf-8"
    )
    cov = coverage_summary(cfg, tmp_path, repo_id="demo", gap_limit=1)
    assert len(cov.top_gaps) == 1
    assert cov.gaps_truncated is (cov.undocumented_symbols > 1)


# --- custodex_ownership --------------------------------------------------------


def test_ownership_summary_unowned_no_roster(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)  # the `api` doc declares no owner
    own = ownership_summary(cfg, tmp_path, repo_id="demo")
    assert isinstance(own, OwnershipSummary)
    assert own.roster_checked is False
    assert own.unowned_count == 1
    assert own.orphan_count == 0
    assert own.clean is True  # no roster ⇒ no departed-owner orphan detectable
    assert own.findings == ()


def test_ownership_summary_inherits_unit_owner(tmp_path: Path) -> None:
    # A dir-layout config: the doc declares no owner of its own but INHERITS its
    # unit's frontmatter owner (the `_unit_owner_map` dir-layout path), so it is
    # NOT unowned — if that map were empty the doc would count as a gap.
    config_dir = tmp_path / "config" / "cdmon"
    scaffold_config_dir(config_dir, repo="widget", now="2026-01-01T00:00:00+00:00")
    cfg, resolved = load_repo_bundle(tmp_path)
    own = ownership_summary(cfg, resolved, repo_id="widget")
    assert own.doc_count == 1
    assert own.unowned_count == 0


def test_ownership_summary_roster_flags_orphan(tmp_path: Path) -> None:
    spec = DocumentSpec(
        id="api", path="api.md", audience=Audience.ENG_GUIDE, owner="alice"
    )
    cfg = MonitorConfig(root=".", documents=(spec,))
    roster = RosterSnapshot(
        identities=(
            Identity(
                name="alice",
                kind="person",
                active=False,
                departed_at="2026-05-01T00:00:00+00:00",
            ),
        )
    )
    own = ownership_summary(cfg, tmp_path, repo_id="demo", roster=roster)
    assert own.roster_checked is True
    assert own.unowned_count == 0
    assert own.orphan_count == 1
    assert own.clean is False
    assert own.findings and own.findings[0].doc_id == "api"


# --- custodex_staleness --------------------------------------------------------


def test_staleness_summary_never_reviewed(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)  # the `api` doc has no `reviewed` stamp
    stale = staleness_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert isinstance(stale, StalenessSummary)
    assert stale.now == NOW
    assert stale.never_reviewed_count == 1
    assert stale.needs_review_total == 1
    assert stale.fresh is False


def test_staleness_summary_fresh(tmp_path: Path) -> None:
    spec = DocumentSpec(
        id="api",
        path="api.md",
        audience=Audience.ENG_GUIDE,
        reviewed="2026-05-30T00:00:00+00:00",
    )
    cfg = MonitorConfig(root=".", documents=(spec,))
    stale = staleness_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert stale.fresh is True
    assert stale.needs_review_total == 0
    assert stale.stale_count == 0


# --- custodex_worklist ---------------------------------------------------------


def test_worklist_summary_stale_item(tmp_path: Path) -> None:
    # An owned, never-reviewed doc → one STALE work item carrying its owner. Pin
    # the full projected WorkItemView so a dropped/swapped field is caught.
    spec = DocumentSpec(
        id="api", path="api.md", audience=Audience.ENG_GUIDE, owner="bob"
    )
    cfg = MonitorConfig(root=".", documents=(spec,))
    wl = worklist_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert isinstance(wl, WorklistSummary)
    assert wl.item_count == 1
    assert wl.orphans_included is False  # no roster supplied
    item = wl.items[0]
    assert item.accountable == "bob"
    assert item.doc_id == "api"
    assert item.doc_path == "api.md"
    assert item.audience == "eng-guide"
    assert item.reason == "stale"
    assert item.severity == "high"  # NEVER_REVIEWED → HIGH
    assert item.upstream_id is None


def test_worklist_summary_global_priority_cap(tmp_path: Path) -> None:
    # Three items differing on the sort key across two owners + the unowned
    # bucket. worklist_from_repo emits them in OWNER order (alice, bob, unowned),
    # so a correct GLOBAL re-sort must reorder before the cap: the single
    # highest-priority item is bob's never-reviewed doc (HIGH, doc_id "a"), NOT
    # alice's MEDIUM stale doc that sorts first in owner order. Kills a
    # no-resort or reverse-sort mutation of the global priority order.
    docs = (
        DocumentSpec(id="a", path="a.md", audience=Audience.ENG_GUIDE, owner="bob"),
        DocumentSpec(
            id="b",
            path="b.md",
            audience=Audience.ENG_GUIDE,
            owner="alice",
            reviewed="2020-01-01T00:00:00+00:00",  # long past SLA → STALE (MEDIUM)
        ),
        DocumentSpec(id="c", path="c.md", audience=Audience.ENG_GUIDE),  # unowned
    )
    cfg = MonitorConfig(root=".", documents=docs)
    wl = worklist_summary(cfg, tmp_path, repo_id="demo", now=NOW, limit=1)
    assert wl.item_count == 3  # total is exact regardless of the cap
    assert wl.returned_item_count == 1
    assert wl.truncated is True
    top = wl.items[0]
    assert top.doc_id == "a"
    assert top.accountable == "bob"
    assert top.severity == "high"


# --- custodex_doc_graph --------------------------------------------------------


def test_doc_graph_summary_edges_and_suspect(tmp_path: Path) -> None:
    overview = DocumentSpec(
        id="overview", path="overview.md", audience=Audience.ENG_GUIDE
    )
    api = DocumentSpec(
        id="api",
        path="api.md",
        audience=Audience.USER_GUIDE,
        depends_on=(DocEdge(doc="overview"),),
    )
    cfg = MonitorConfig(
        root=".", documents=(overview, api), docdeps=DocDepsConfig(enabled=True)
    )

    def _managed(spec: DocumentSpec, body: str) -> None:
        surface = build_document_surface(spec, tmp_path)
        meta = set_fingerprint({}, surface.surface_hash())
        (tmp_path / spec.path).write_text(render_doc(meta, body), encoding="utf-8")

    _managed(overview, "# Overview\nupstream\n")
    _managed(api, "# API\ndownstream\n")
    stamp_edges(cfg, tmp_path, "api")
    graph = doc_graph_summary(cfg, tmp_path, repo_id="demo")
    assert isinstance(graph, DocGraph)
    assert graph.enabled is True
    assert graph.gates == cfg.docdeps.gate
    assert graph.edge_count == 1
    assert graph.suspect_count == 0  # freshly stamped edge is OK

    _managed(overview, "# Overview\nMOVED\n")  # move the upstream body
    moved = doc_graph_summary(cfg, tmp_path, repo_id="demo")
    assert moved.suspect_count == 1


def test_doc_graph_summary_disabled_is_unambiguous(tmp_path: Path) -> None:
    spec = DocumentSpec(id="api", path="api.md", audience=Audience.ENG_GUIDE)
    cfg = MonitorConfig(
        root=".", documents=(spec,), docdeps=DocDepsConfig(enabled=False)
    )
    graph = doc_graph_summary(cfg, tmp_path, repo_id="demo")
    # `enabled=False` disambiguates "detection off" from "genuinely no edges".
    assert graph.enabled is False
    assert graph.edge_count == 0


def test_doc_graph_summary_gates_passthrough(tmp_path: Path) -> None:
    # `gates` is the config's docdeps.gate verbatim — pin the False case so a
    # hardcoded-True mutant is caught (the enabled test only sees the default).
    spec = DocumentSpec(id="api", path="api.md", audience=Audience.ENG_GUIDE)
    cfg = MonitorConfig(
        root=".",
        documents=(spec,),
        docdeps=DocDepsConfig(enabled=True, gate=False),
    )
    graph = doc_graph_summary(cfg, tmp_path, repo_id="demo")
    assert graph.gates is False


# --- custodex_records ----------------------------------------------------------


def _record(record_id: str, verdict: Verdict, detected_at: str) -> ReviewRecord:
    # resolved_at is deliberately DISTINCT from detected_at so the projection's
    # detected_at↔resolved_at mapping is checkable (a swap can't hide).
    return ReviewRecord(
        record_id=record_id,
        doc_id="api",
        doc_path="api.md",
        audience=Audience.ENG_GUIDE,
        drift_kind="HASH",
        drift_detail="moved",
        cause="changed",
        verdict=verdict,
        fix=(
            ProposedFix(
                region_id="symbols",
                new_region_body="body",
                new_doc_text=None,
                rationale="r",
            )
            if verdict is Verdict.FIX
            else None
        ),
        surface_hash="hash",
        backend_kind="mock",
        detected_at=detected_at,
        resolved_at=detected_at.replace("T00:00:00", "T00:00:05"),
        config_snapshot={},
    )


def test_list_records_empty_log_is_not_an_error(tmp_path: Path) -> None:
    cfg = MonitorConfig(root=".", documents=())
    records = list_records(cfg, tmp_path, repo_id="demo")
    assert isinstance(records, RecordList)
    assert records.total == 0
    assert records.records == ()
    assert records.truncated is False


def test_list_records_newest_first_and_by_verdict(tmp_path: Path) -> None:
    cfg = MonitorConfig(root=".", documents=())
    log = tmp_path / DEFAULT_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    append(log, _record("r1", Verdict.FIX, "2026-06-01T00:00:00+00:00"))
    append(log, _record("r2", Verdict.INVALIDATE, "2026-06-02T00:00:00+00:00"))
    records = list_records(cfg, tmp_path, repo_id="demo")
    assert records.total == 2
    assert [r.record_id for r in records.records] == ["r2", "r1"]  # newest first
    assert records.by_verdict == {"FIX": 1, "INVALIDATE": 1}
    # Field-level pins on the newest record — catches a dropped/swapped field,
    # especially the detected_at↔resolved_at pair (deliberately distinct).
    top = records.records[0]
    assert top.record_id == "r2"
    assert top.verdict == "INVALIDATE"
    assert top.doc_id == "api"
    assert top.doc_path == "api.md"
    assert top.audience == "eng-guide"
    assert top.drift_kind == "HASH"
    assert top.detected_at == "2026-06-02T00:00:00+00:00"
    assert top.resolved_at == "2026-06-02T00:00:05+00:00"
    assert isinstance(top.change_severity, str)


def test_list_records_verdict_filter(tmp_path: Path) -> None:
    cfg = MonitorConfig(root=".", documents=())
    log = tmp_path / DEFAULT_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    append(log, _record("r1", Verdict.FIX, "2026-06-01T00:00:00+00:00"))
    append(log, _record("r2", Verdict.INVALIDATE, "2026-06-02T00:00:00+00:00"))
    records = list_records(cfg, tmp_path, repo_id="demo", verdict="FIX")
    assert records.total == 1
    assert records.records[0].record_id == "r1"


def test_list_records_bad_verdict_is_loud(tmp_path: Path) -> None:
    cfg = MonitorConfig(root=".", documents=())
    with pytest.raises(McpError):
        list_records(cfg, tmp_path, repo_id="demo", verdict="BOGUS")


def test_list_records_cap_truncates(tmp_path: Path) -> None:
    cfg = MonitorConfig(root=".", documents=())
    log = tmp_path / DEFAULT_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        append(log, _record(f"r{i}", Verdict.FIX, f"2026-06-0{i + 1}T00:00:00+00:00"))
    records = list_records(cfg, tmp_path, repo_id="demo", limit=2)
    assert records.total == 3
    assert records.returned == 2
    assert records.truncated is True
    assert records.records[0].record_id == "r2"  # newest of the capped slice


# --- MCP-02: the gated write tools (remediate / resolve / sync_docs) --------------


def _drifted_repo(tmp_path: Path) -> tuple[MonitorConfig, Path]:
    """The synced one-doc repo, then a public-signature change → HASH+REGION drift.

    Returns ``(cfg, doc_path)`` so a test can assert the doc's bytes before/after a
    write tool runs — the load-bearing K11 check (``apply=False`` never mutates).
    """
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    return cfg, tmp_path / "repo" / "docs" / "api.md"


def test_remediate_drift_apply_false_records_but_never_mutates_doc(
    tmp_path: Path,
) -> None:
    cfg, doc = _drifted_repo(tmp_path)
    before = doc.read_text(encoding="utf-8")
    result = remediate_drift(cfg, tmp_path, repo_id="demo", now=NOW, apply=False)
    assert isinstance(result, RemediationResult)
    # The K11/K5 core guarantee: proposals are RECORDED, the doc is UNTOUCHED.
    assert doc.read_text(encoding="utf-8") == before
    assert result.applied is False
    assert result.applied_count == 0
    assert result.clean is False  # nothing healed → drift persists
    assert result.remaining_count >= 1
    assert result.handled_count == 2  # HASH + REGION on the one doc
    assert result.record_count == 2  # one ReviewRecord per handled drift (K5)
    assert result.by_verdict == {"FIX": 2}
    # A ReviewRecord per handled drift is actually on disk (custodex_records sees it),
    # stamped with the INJECTED now (K10) — a dropped `now=lambda: now` would make
    # detected_at the wall clock and fail this.
    assert (tmp_path / DEFAULT_LOG_PATH).is_file()
    written = read_all(tmp_path / DEFAULT_LOG_PATH)
    assert written and all(r.detected_at == NOW for r in written)
    # Every item is advisory (applied False), carries a verdict + an FK record_id.
    assert all(it.applied is False for it in result.items)
    assert all(it.verdict == "FIX" for it in result.items)
    assert all(it.record_id for it in result.items)
    # Sorted (doc_id, region_id or '', drift_kind): HASH (region '') before REGION.
    assert [it.drift_kind for it in result.items] == ["HASH", "REGION"]
    hash_item, region_item = result.items
    assert hash_item.region_id is None
    assert hash_item.fix_preview is not None and hash_item.rationale is not None
    assert region_item.region_id == "symbols"
    assert region_item.fix_preview is not None


def test_remediate_drift_apply_true_heals_and_is_idempotent(tmp_path: Path) -> None:
    cfg, doc = _drifted_repo(tmp_path)
    before = doc.read_text(encoding="utf-8")
    result = remediate_drift(cfg, tmp_path, repo_id="demo", now=NOW, apply=True)
    assert result.applied is True
    assert result.applied_count >= 1
    assert doc.read_text(encoding="utf-8") != before  # healed
    assert result.clean is True
    assert result.remaining_count == 0
    # K7: a second apply run finds nothing to do — no new handled drift / records.
    again = remediate_drift(cfg, tmp_path, repo_id="demo", now=NOW, apply=True)
    assert again.handled_count == 0
    assert again.record_count == 0
    assert again.clean is True


def test_remediate_drift_clean_repo_is_a_noop(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    result = remediate_drift(cfg, tmp_path, repo_id="demo", now=NOW)  # default apply
    assert result.applied is False
    assert result.handled_count == 0
    assert result.record_count == 0
    assert result.clean is True
    assert result.by_verdict == {}
    assert result.items == ()


def test_remediate_drift_cap_truncates_but_totals_stay_exact(tmp_path: Path) -> None:
    cfg, _ = _drifted_repo(tmp_path)
    result = remediate_drift(cfg, tmp_path, repo_id="demo", now=NOW, limit=1)
    assert result.handled_count == 2  # the FULL count, not the capped slice
    assert result.record_count == 2
    assert len(result.items) == 1
    assert result.truncated is True


def test_remediate_drift_fix_preview_truncates(tmp_path: Path) -> None:
    cfg, _ = _drifted_repo(tmp_path)
    result = remediate_drift(
        cfg, tmp_path, repo_id="demo", now=NOW, apply=False, fix_preview_limit=8
    )
    trimmed = [it for it in result.items if it.fix_truncated]
    assert trimmed, "expected at least one fix preview long enough to trip the cap"
    assert all(
        it.fix_preview is not None and len(it.fix_preview) <= 8 for it in trimmed
    )


def test_resolve_drift_records_the_outcome(tmp_path: Path) -> None:
    cfg = MonitorConfig(root=".", documents=())
    log = tmp_path / DEFAULT_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    append(log, _record("r1", Verdict.FIX, "2026-06-01T00:00:00+00:00"))
    result = resolve_drift(
        cfg, tmp_path, repo_id="demo", record_id="r1", resolution="accepted", now=NOW
    )
    assert isinstance(result, ResolutionResult)
    assert result.recorded is True
    assert result.record_id == "r1"
    assert result.resolution == "accepted"
    assert result.resolved_at == NOW  # INJECTED now, never a clock read (K10)
    assert result.resolutions_path == ".cdmon/resolutions.jsonl"
    # The ResolutionRecord is on disk + joinable to the review record by FK.
    idx = resolved_index(read_resolutions(tmp_path / DEFAULT_RESOLUTIONS_PATH))
    assert "r1" in idx
    assert idx["r1"].resolution is Resolution.ACCEPTED
    assert idx["r1"].resolved_at == NOW


def test_resolve_drift_unknown_record_is_loud(tmp_path: Path) -> None:
    cfg = MonitorConfig(root=".", documents=())
    with pytest.raises(McpError):
        resolve_drift(
            cfg,
            tmp_path,
            repo_id="demo",
            record_id="nope",
            resolution="accepted",
            now=NOW,
        )


def test_resolve_drift_bad_resolution_is_loud(tmp_path: Path) -> None:
    cfg = MonitorConfig(root=".", documents=())
    log = tmp_path / DEFAULT_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    append(log, _record("r1", Verdict.FIX, "2026-06-01T00:00:00+00:00"))
    with pytest.raises(McpError) as exc:
        resolve_drift(
            cfg, tmp_path, repo_id="demo", record_id="r1", resolution="bogus", now=NOW
        )
    assert "accepted" in str(exc.value)  # loud + lists the legal choices (K8)


def test_resolve_drift_overridden_carries_text_and_by(tmp_path: Path) -> None:
    cfg = MonitorConfig(root=".", documents=())
    log = tmp_path / DEFAULT_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    append(log, _record("r1", Verdict.FIX, "2026-06-01T00:00:00+00:00"))
    result = resolve_drift(
        cfg,
        tmp_path,
        repo_id="demo",
        record_id="r1",
        resolution="OVERRIDDEN",  # case-insensitive parse (mirrors cli._parse)
        now=NOW,
        resolved_text="my final body",
        resolved_by="alice",
        note="see PR",
    )
    assert result.resolution == "overridden"
    assert result.resolved_by == "alice"
    assert result.note == "see PR"
    idx = resolved_index(read_resolutions(tmp_path / DEFAULT_RESOLUTIONS_PATH))
    assert idx["r1"].resolution is Resolution.OVERRIDDEN
    assert idx["r1"].resolved_text == "my final body"


def test_remediate_record_id_feeds_resolve(tmp_path: Path) -> None:
    # The two write tools COMPOSE: a record_id surfaced by custodex_remediate is the
    # exact FK custodex_resolve consumes — the human-in-the-loop apply seam (K5/K11),
    # and the "chain" the MCP client orchestrates.
    cfg, _ = _drifted_repo(tmp_path)
    rem = remediate_drift(cfg, tmp_path, repo_id="demo", now=NOW, apply=False)
    rid = rem.items[0].record_id
    res = resolve_drift(
        cfg, tmp_path, repo_id="demo", record_id=rid, resolution="accepted", now=NOW
    )
    assert res.recorded is True
    idx = resolved_index(read_resolutions(tmp_path / DEFAULT_RESOLUTIONS_PATH))
    assert rid in idx


def test_remediate_record_id_is_per_doc_review_record(tmp_path: Path) -> None:
    # CONTRACT PIN (MCP02-CORR-1): a doc's simultaneous drifts (HASH + REGION here)
    # SHARE one record_id — it identifies the review RECORD, not the drift, exactly
    # as the .cdmon log + `cdx resolve` key it. `drift_kind`/`region_id` disambiguate
    # the facets. This pins the truthful contract (the docstrings no longer promise a
    # 1:1 per-drift FK) so a change to the id grain is a deliberate, caught decision.
    cfg, _ = _drifted_repo(tmp_path)
    result = remediate_drift(cfg, tmp_path, repo_id="demo", now=NOW, apply=False)
    assert result.handled_count == 2
    # Same doc → ONE shared record_id across both items...
    assert len({it.record_id for it in result.items}) == 1
    # ...but the drift facets are distinguishable (locus differs).
    assert {(it.drift_kind, it.region_id) for it in result.items} == {
        ("HASH", None),
        ("REGION", "symbols"),
    }


def test_sync_docs_dry_run_previews_without_touching_the_tree(tmp_path: Path) -> None:
    cfg, doc = _drifted_repo(tmp_path)
    before = doc.read_text(encoding="utf-8")
    result = sync_docs(cfg, tmp_path, repo_id="demo", now=NOW, apply=False)
    assert isinstance(result, SyncDocsResult)
    assert result.applied is False
    assert result.clean is False
    assert result.changed_count == 1
    assert result.changed_paths == ("docs/api.md",)
    assert result.patch and "docs/api.md" in result.patch
    assert result.patch_truncated is False
    # K1: the NET effect is an untouched tree (sync_pr heals-then-restores).
    assert doc.read_text(encoding="utf-8") == before
    # K10: the audit records the dry-run still writes are stamped with the injected
    # now (a dropped `now=lambda: now` would leave the wall clock and fail this).
    written = read_all(tmp_path / DEFAULT_LOG_PATH)
    assert written and all(r.detected_at == NOW for r in written)


def test_sync_docs_apply_heals_and_is_idempotent(tmp_path: Path) -> None:
    cfg, doc = _drifted_repo(tmp_path)
    before = doc.read_text(encoding="utf-8")
    result = sync_docs(cfg, tmp_path, repo_id="demo", now=NOW, apply=True)
    assert result.applied is True
    assert result.clean is False  # the diff of what WAS healed
    assert doc.read_text(encoding="utf-8") != before
    # K7: a second apply finds nothing left to heal.
    again = sync_docs(cfg, tmp_path, repo_id="demo", now=NOW, apply=True)
    assert again.clean is True
    assert again.patch == ""
    assert again.changed_count == 0


def test_sync_docs_clean_repo_is_empty_patch(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    result = sync_docs(cfg, tmp_path, repo_id="demo", now=NOW)  # default apply=False
    assert result.clean is True
    assert result.patch == ""
    assert result.changed_count == 0
    assert result.changed_paths == ()


def test_sync_docs_patch_truncates(tmp_path: Path) -> None:
    cfg, _ = _drifted_repo(tmp_path)
    result = sync_docs(
        cfg, tmp_path, repo_id="demo", now=NOW, apply=False, patch_limit=12
    )
    assert result.patch_truncated is True
    assert len(result.patch) <= 12


def test_remediate_drift_escalate_item_has_no_fix(tmp_path: Path) -> None:
    # A MISSING_DOC drift the mock backend cannot remediate → ESCALATE with fix=None:
    # the item still records for audit (K5) but carries no rationale/preview (the
    # fix-less verdict path — proves a non-FIX verdict is shaped, not just FIX).
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(CODE_V1, encoding="utf-8")
    spec = DocumentSpec(
        id="api",
        path="docs/api.md",  # deliberately never created → MISSING_DOC drift
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
    )
    cfg = MonitorConfig(root="repo", documents=(spec,))
    result = remediate_drift(cfg, tmp_path, repo_id="demo", now=NOW, apply=False)
    assert result.by_verdict == {"ESCALATE": 1}
    (item,) = result.items
    assert item.verdict == "ESCALATE"
    assert item.applied is False
    assert item.fix_preview is None
    assert item.rationale is None
    assert item.region_id is None
    assert item.record_id  # still recorded for the audit trail (K5)


def test_fix_preview_region_only_fix_has_no_body() -> None:
    # A degenerate fix carrying a region_id but no body: the preview surfaces the
    # region locus with a None body (the defensive shape heal itself would reject).
    region_id, preview, truncated = _fix_preview(
        ProposedFix(
            region_id="symbols",
            new_region_body=None,
            new_doc_text=None,
            rationale="none",
        ),
        100,
    )
    assert region_id == "symbols"
    assert preview is None
    assert truncated is False


def test_fix_preview_whole_doc_wins_over_region_body() -> None:
    # heal.apply_fix precedence: when BOTH bodies are set, new_doc_text wins — so the
    # preview shows the whole-doc text a client would review, not the region body.
    _region_id, preview, _truncated = _fix_preview(
        ProposedFix(
            region_id="r",
            new_region_body="REGION",
            new_doc_text="WHOLEDOC",
            rationale="x",
        ),
        100,
    )
    assert preview == "WHOLEDOC"


@pytest.mark.parametrize(
    "model",
    [RemediationItem, RemediationResult, ResolutionResult, SyncDocsResult],
)
def test_mcp02_result_models_are_frozen_and_forbid_extra(model: type) -> None:
    # The shaped-wire contract: every MCP-02 result model is frozen (immutable on the
    # wire) + extra="forbid" (a stray/renamed field is a loud error, not silent
    # drift). Guards against a mutation relaxing either config flag.
    assert model.model_config.get("frozen") is True
    assert model.model_config.get("extra") == "forbid"


def test_remediation_result_is_immutable_and_rejects_unknown_fields(
    tmp_path: Path,
) -> None:
    # Behavioural teeth on the two config flags above, on a real instance.
    cfg, _ = _drifted_repo(tmp_path)
    result = remediate_drift(cfg, tmp_path, repo_id="demo", now=NOW)
    with pytest.raises(ValidationError):
        result.repo_id = "mutated"  # frozen → no in-place mutation
    with pytest.raises(ValidationError):
        RemediationResult.model_validate({**result.model_dump(), "bogus": 1})
