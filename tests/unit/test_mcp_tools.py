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
from custodex.errors import McpError
from custodex.extract import build_document_surface
from custodex.manifest import render_doc, set_fingerprint, set_region
from custodex.mcp.tools import (
    CoverageSummary,
    DocGraph,
    DriftDetail,
    DriftItem,
    OwnershipSummary,
    RecordList,
    StalenessSummary,
    StatusSummary,
    WorklistSummary,
    coverage_summary,
    doc_graph_summary,
    drift_detail,
    list_records,
    load_repo_bundle,
    ownership_summary,
    resolve_repo_id,
    staleness_summary,
    status_summary,
    worklist_summary,
)
from custodex.monitor import DEFAULT_LOG_PATH
from custodex.ownership import Identity, RosterSnapshot
from custodex.reviewlog import append
from custodex.schema import ProposedFix, ReviewRecord, Verdict
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
    assert detail.total >= 1
    assert detail.shown == len(detail.items)
    assert all(isinstance(i, DriftItem) for i in detail.items)
    # by_kind partitions the (filtered) total exactly — no double-count, no drop.
    assert sum(detail.by_kind.values()) == detail.total


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
    # A never-reviewed, unowned doc → one STALE work item in the unowned bucket.
    spec = DocumentSpec(id="api", path="api.md", audience=Audience.ENG_GUIDE)
    cfg = MonitorConfig(root=".", documents=(spec,))
    wl = worklist_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    assert isinstance(wl, WorklistSummary)
    assert wl.item_count >= 1
    assert wl.orphans_included is False  # no roster supplied
    assert any(item.reason == "stale" for item in wl.items)


def test_worklist_summary_cap_truncates(tmp_path: Path) -> None:
    specs = tuple(
        DocumentSpec(id=f"d{i}", path=f"d{i}.md", audience=Audience.ENG_GUIDE)
        for i in range(3)
    )
    cfg = MonitorConfig(root=".", documents=specs)
    wl = worklist_summary(cfg, tmp_path, repo_id="demo", now=NOW, limit=1)
    assert wl.returned_item_count == 1
    assert wl.truncated is True
    assert wl.item_count >= 3  # the total is exact regardless of the cap


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


# --- custodex_records ----------------------------------------------------------


def _record(record_id: str, verdict: Verdict, detected_at: str) -> ReviewRecord:
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
        resolved_at=detected_at,
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
