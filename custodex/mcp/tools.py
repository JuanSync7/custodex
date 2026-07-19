"""MCP tool logic (EPIC MCP, MCP-00 + MCP-01 read projections, MCP-02 write tools).

Imports ONLY core deps — never the ``mcp`` SDK — so the projection logic is
testable without the ``[mcp]`` extra and the engine's K0 surface is untouched.
The FastMCP registration that turns these into MCP tools lives in
:mod:`custodex.mcp.server` (the only module that imports the SDK).

The MCP-00/01 helpers (`status_summary` + the seven per-domain read projections
drift/coverage/ownership/staleness/worklist/doc-graph/records) each READ the same
detector the matching ``cdx`` verb calls (K1/K2) — a pure fold, no re-detection,
no mutation. The MCP-02 helpers (`remediate_drift`/`resolve_drift`/`sync_docs`)
DELIBERATELY mutate via the engine's existing write seams (`Monitor.run` /
`reviewlog.append_resolution` / `syncpr.sync_pr`), gated by an advisory
``apply=False`` default + the server's ``read_only`` switch (K11) — see the block
comment above :func:`remediate_drift`.

Across both layers: output is SHAPED + CAPPED + deterministically sorted (K10);
any as-of ``now`` is INJECTED by the caller (the server wrapper), never read from
a clock here; bad input surfaces a loud typed error (K8), never a silent pass.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..config import (
    Audience,
    MonitorConfig,
    load_bundle,
    load_config,
    load_config_dir,
    resolve_repo_root,
)
from ..coverage import resolve_coverage
from ..docdeps import SuspectLink, SuspectStatus, detect_suspect_links
from ..drift import DriftKind
from ..errors import CodeDocMonitorError, McpError
from ..inventory import discover_files, discover_symbols
from ..monitor import DEFAULT_LOG_PATH, Monitor
from ..ownership import (
    OwnershipFinding,
    OwnershipStatus,
    RosterSnapshot,
    detect_orphans,
    resolve_ownership,
)
from ..reviewlog import (
    DEFAULT_RESOLUTIONS_PATH,
    append_resolution,
    read_all,
    select_by_verdict,
    summarize,
)
from ..schema import ProposedFix, Resolution, ResolutionRecord, Verdict
from ..staleness import (
    StalenessFinding,
    StalenessStatus,
    detect_stale,
    reviewed_docs_from_config,
)
from ..syncpr import sync_pr
from ..worklist import WorkItem, _item_sort_key, worklist_from_repo

__all__ = [
    "CoverageSummary",
    "DocGraph",
    "DriftDetail",
    "DriftItem",
    "OwnershipSummary",
    "RecordList",
    "RecordSummary",
    "RemediationItem",
    "RemediationResult",
    "ResolutionResult",
    "StalenessSummary",
    "StatusSummary",
    "SymbolGap",
    "SyncDocsResult",
    "WorkItemView",
    "WorklistSummary",
    "coverage_summary",
    "doc_graph_summary",
    "drift_detail",
    "list_records",
    "load_repo_bundle",
    "ownership_summary",
    "remediate_drift",
    "resolve_drift",
    "resolve_repo_id",
    "staleness_summary",
    "status_summary",
    "sync_docs",
    "worklist_summary",
]

# Where a repo's dir-layout config lives, relative to the repo root (CONFIG-V2 §1).
_CONFIG_SUBDIR = ("config", "cdmon")

# Default caps for the shaped list outputs (K10 — bound the wire, keep the totals
# exact). A client that wants the full list raises the tool's ``limit`` param.
_DEFAULT_LIST_CAP = 50
_DEFAULT_RECORD_CAP = 20

# MCP-02 write-tool caps. The full proposed fix lives in the on-disk ReviewRecord;
# the remediation item embeds only a CAPPED preview (apply re-derives the applied
# text from that record, never from this teaser, so truncation is lossless-safe).
_DEFAULT_FIX_PREVIEW = 2000
# Bound the sync_docs unified-diff on the wire (a large diff must not swamp context).
_DEFAULT_PATCH_CAP = 20000


def load_repo_bundle(repo_root: Path) -> tuple[MonitorConfig, Path]:
    """Resolve ``repo_root``'s Custodex config to ``(cfg, config_dir)`` (K8).

    The CONFIG-V2 ``config/cdmon/`` dir layout wins (``index.yaml`` present),
    else the single-file ``cdmon.yaml`` back-compat path. Neither present is a
    loud :class:`McpError` — there is nothing to serve. Returns the same
    ``(cfg, config_dir)`` pair the CLI's ``_load`` yields, so ``Monitor`` and the
    detectors resolve paths identically (a malformed config still raises the
    loader's own :class:`~custodex.errors.ConfigError`, K8).
    """
    config_dir = repo_root.joinpath(*_CONFIG_SUBDIR)
    if (config_dir / "index.yaml").is_file():
        return load_config_dir(config_dir), config_dir
    single = repo_root / "cdmon.yaml"
    if single.is_file():
        return load_config(single), repo_root
    raise McpError(
        f"no Custodex config under {repo_root} — expected config/cdmon/index.yaml "
        f"or cdmon.yaml (run `cdx init --v2` first)"
    )


def resolve_repo_id(repo_root: Path, config_dir: Path) -> str:
    """The repo id: the bundle index ``repo`` field, else the dir name (K8-safe).

    Mirrors :func:`custodex.server.standalone.resolve_repo_id` WITHOUT importing
    the ``[server]`` subpackage. A malformed/absent index falls back to the
    directory name so the status tool never fails on the id alone — the real
    config error surfaces loudly in the detect step (K8).
    """
    if (config_dir / "index.yaml").is_file():
        try:
            return load_bundle(config_dir).index.frontmatter.repo
        except CodeDocMonitorError:
            pass
    return repo_root.name


def _unit_owner_map(config_dir: Path) -> dict[str, str]:
    """``doc_id`` → its unit-frontmatter owner for a dir-layout config (EPIC OWN).

    A PURE copy of ``cli._unit_owner_map`` — importing ``cli`` would drag in
    ``typer`` and break the K0 core-deps-only boundary of this module. A
    single-file config has no units, so this is empty there (no fallback).
    """
    if not (config_dir / "index.yaml").is_file():
        return {}
    bundle = load_bundle(config_dir)
    return {
        doc.id: unit.frontmatter.owner
        for unit in bundle.units
        for doc in unit.documents
    }


class StatusSummary(BaseModel):
    """The ``custodex_status`` overview: the 4-pillar repo health in one call.

    ADDITIVE (K6): MCP-00 shipped the drift fields; MCP-01 enriched it with the
    coverage / ownership / staleness headline counts, so a client reading only
    the original fields keeps working. ``clean`` is true only when there is no
    drift of any kind; ``drift_total`` splits into ``code↔doc`` (``code_doc_drift``)
    and ``doc↔doc`` (``suspect_link_drift``). The enrichment counts mirror the
    dedicated tools (``custodex_coverage``/``custodex_ownership``/
    ``custodex_staleness``) so the overview and the drill-downs agree.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    clean: bool
    doc_count: int
    drift_total: int
    code_doc_drift: int
    suspect_link_drift: int
    coverage_available: bool
    coverage_file_pct: float
    coverage_symbol_pct: float
    docs_unowned: int
    docs_needing_review: int
    summary: str


def status_summary(
    cfg: MonitorConfig, config_dir: Path, *, repo_id: str, now: str
) -> StatusSummary:
    """Project the live 4-pillar health into a shaped overview (K1/K2/K10).

    Runs the SAME detect ``cdx check`` runs (:meth:`Monitor.check`) and folds in
    the coverage / ownership / staleness headline counts from the dedicated
    helpers (so the overview never disagrees with the drill-down tools). ``now``
    is INJECTED (the staleness fold is as-of that date, K10) — no clock read, no
    mutation, no network.

    Unlike drift/ownership/staleness (bounded to the config), coverage does a
    FULL-repo tree walk + symbol extraction, so an unparseable in-scope ``.py``
    file (e.g. a WIP file mid-edit) would otherwise abort the WHOLE overview. As
    the "call first" progressive-disclosure entrypoint, ``custodex_status`` must
    stay answerable for the other pillars, so a coverage failure DEGRADES to an
    honest partial (``coverage_available=False``, sentinel ``-1.0`` percentages) —
    the dedicated ``custodex_coverage`` tool still surfaces the parse error loudly
    (K8). This mirrors the ``roster_checked=False`` honest-partial precedent.
    """
    report = Monitor(cfg, config_dir).check()
    total = len(report.drifts)
    suspect = sum(1 for d in report.drifts if d.kind is DriftKind.SUSPECT_LINK)
    own = ownership_summary(cfg, config_dir, repo_id=repo_id)
    stale = staleness_summary(cfg, config_dir, repo_id=repo_id, now=now)
    try:
        cov = coverage_summary(cfg, config_dir, repo_id=repo_id)
        coverage_available = True
        coverage_file_pct = cov.percent_files
        coverage_symbol_pct = cov.percent_public_symbols
    except CodeDocMonitorError:
        coverage_available = False
        coverage_file_pct = -1.0
        coverage_symbol_pct = -1.0
    return StatusSummary(
        repo_id=repo_id,
        clean=report.ok,
        doc_count=len(cfg.documents),
        drift_total=total,
        code_doc_drift=total - suspect,
        suspect_link_drift=suspect,
        coverage_available=coverage_available,
        coverage_file_pct=coverage_file_pct,
        coverage_symbol_pct=coverage_symbol_pct,
        docs_unowned=own.unowned_count,
        docs_needing_review=stale.needs_review_total,
        summary=report.summary(),
    )


# --- custodex_drift: the per-drift detail list (custodex_status only COUNTS) -----


class DriftItem(BaseModel):
    """One shaped drift row — the actionable subset, not raw ``Drift`` internals.

    Drops the heavy wire fields (the unified ``diff`` and the P2/P4/DIG-01 tuples);
    their meaning is folded into ``change_severity`` (the at-a-glance API-impact
    verdict) + the human ``message``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str
    doc_path: str
    kind: str
    audience: str
    healable: bool
    region_id: str | None
    change_severity: str
    message: str


class DriftDetail(BaseModel):
    """The ``custodex_drift`` result: a shaped, filtered, capped per-drift list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    clean: bool
    total: int
    shown: int
    truncated: bool
    by_kind: dict[str, int]
    items: tuple[DriftItem, ...]


def drift_detail(
    cfg: MonitorConfig,
    config_dir: Path,
    *,
    repo_id: str,
    limit: int = _DEFAULT_LIST_CAP,
    kind: DriftKind | None = None,
    audience: Audience | None = None,
) -> DriftDetail:
    """Project the live drift report into a shaped per-drift list (K1/K2/K10).

    Runs the SAME detect ``cdx check`` runs, optionally filters by ``kind`` /
    ``audience`` (K3), sorts deterministically ``(doc_id, region_id, kind)``, and
    caps at ``limit``. ``total`` is the count AFTER the filter (so ``truncated``
    reflects the returned slice); ``clean`` reflects the WHOLE repo (unfiltered).
    """
    report = Monitor(cfg, config_dir).check()
    matched = [
        d
        for d in report.drifts
        if (kind is None or d.kind is kind)
        and (audience is None or d.audience is audience)
    ]
    matched.sort(key=lambda d: (d.doc_id, d.region_id or "", d.kind.value))
    by_kind: dict[str, int] = {}
    for d in matched:
        by_kind[d.kind.value] = by_kind.get(d.kind.value, 0) + 1
    items = tuple(
        DriftItem(
            doc_id=d.doc_id,
            doc_path=d.doc_path,
            kind=d.kind.value,
            audience=d.audience.value,
            healable=d.healable,
            region_id=d.region_id,
            change_severity=d.change_severity.value,
            message=d.detail,
        )
        for d in matched[:limit]
    )
    return DriftDetail(
        repo_id=repo_id,
        clean=report.ok,
        total=len(matched),
        shown=len(items),
        truncated=len(matched) > len(items),
        by_kind=dict(sorted(by_kind.items())),
        items=items,
    )


# --- custodex_coverage: doc-coverage % + capped symbol gaps ----------------------


class SymbolGap(BaseModel):
    """One undocumented public symbol — the minimal stable gap shape."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    name: str
    kind: str


class CoverageSummary(BaseModel):
    """The ``custodex_coverage`` result: percentages + basket counts + top gaps.

    Returns COUNTS (K10 shaping), never the lossless per-file/per-symbol tables
    (thousands of rows on a large repo would swamp an LLM's context); the gap
    list is a CAPPED, already-sorted ``top_gaps`` with a ``gaps_truncated`` flag.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    percent_files: float
    percent_public_symbols: float
    documented_files: int
    undocumented_files: int
    waived_files: int
    documented_symbols: int
    undocumented_symbols: int
    waived_symbols: int
    top_gaps: tuple[SymbolGap, ...]
    gaps_truncated: bool
    summary: str


def coverage_summary(
    cfg: MonitorConfig,
    config_dir: Path,
    *,
    repo_id: str,
    gap_limit: int = _DEFAULT_LIST_CAP,
) -> CoverageSummary:
    """Project the live coverage report into a shaped overview (K1/K2/K10).

    Composes the SAME engine ``cdx coverage`` runs — ``discover_files`` →
    ``discover_symbols`` → ``resolve_coverage`` over ``resolve_repo_root`` — then
    folds the report into percentages + basket sizes + a capped ``top_gaps``. A
    bad root / unparseable file surfaces the loader's typed error loudly (K8).
    """
    root = resolve_repo_root(config_dir, cfg.root)
    inv = discover_files(
        root, include=cfg.coverage.include, exclude=cfg.coverage.exclude
    )
    sym = discover_symbols(inv, root)
    report = resolve_coverage(cfg, sym)
    gaps = report.undocumented_symbols
    documented_files = len(report.documented_files)
    documented_symbols = len(report.documented_symbols)
    top_gaps = tuple(
        SymbolGap(path=s.path, name=s.name, kind=s.kind) for s in gaps[:gap_limit]
    )
    summary = (
        f"files {report.percent_files:.1f}% "
        f"({documented_files}/{documented_files + len(report.undocumented_files)} "
        f"documented), public symbols {report.percent_public_symbols:.1f}% "
        f"({documented_symbols}/{documented_symbols + len(gaps)}); "
        f"{len(gaps)} symbol gap(s)"
    )
    return CoverageSummary(
        repo_id=repo_id,
        percent_files=report.percent_files,
        percent_public_symbols=report.percent_public_symbols,
        documented_files=documented_files,
        undocumented_files=len(report.undocumented_files),
        waived_files=len(report.waived_files),
        documented_symbols=documented_symbols,
        undocumented_symbols=len(gaps),
        waived_symbols=len(report.waived_symbols),
        top_gaps=top_gaps,
        gaps_truncated=len(gaps) > gap_limit,
        summary=summary,
    )


# --- custodex_ownership: owner-per-doc + unowned + (roster) orphans --------------


class OwnershipSummary(BaseModel):
    """The ``custodex_ownership`` result: unowned + departed-owner orphan counts.

    ``unowned_count`` (a coverage gap: no owner/team/dri anywhere) is roster-free
    and always computed. ``orphan_count`` (a departed accountable owner) needs a
    roster; without one, ``roster_checked`` is False and ``findings`` is empty —
    the honest partial (the CLI's vacuous-gate precedent), never a false "clean".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    doc_count: int
    unowned_count: int
    orphan_count: int
    roster_checked: bool
    clean: bool
    findings: tuple[OwnershipFinding, ...]
    findings_truncated: bool


def ownership_summary(
    cfg: MonitorConfig,
    config_dir: Path,
    *,
    repo_id: str,
    roster: RosterSnapshot | None = None,
    limit: int = _DEFAULT_LIST_CAP,
) -> OwnershipSummary:
    """Resolve owners, count unowned docs, and (with a roster) departed orphans.

    Reuses ``resolve_ownership`` (config = source of truth, K2) with the unit
    owner fallback. ``unowned`` = docs whose resolved accountable is None. Orphans
    (``detect_orphans``) only run when a ``roster`` is supplied — the stdio server
    governs a local repo with no central roster, so this defaults off (honest).
    """
    owners = resolve_ownership(cfg, unit_owner=_unit_owner_map(config_dir))
    unowned_count = sum(1 for o in owners if o.accountable is None)
    if roster is not None:
        all_findings = detect_orphans(owners, roster)
        orphan_count = sum(
            1
            for f in all_findings
            if f.status
            in (
                OwnershipStatus.ORPHAN_OWNER_DEPARTED,
                OwnershipStatus.ORPHAN_DRI_VACANT,
            )
        )
        return OwnershipSummary(
            repo_id=repo_id,
            doc_count=len(owners),
            unowned_count=unowned_count,
            orphan_count=orphan_count,
            roster_checked=True,
            clean=orphan_count == 0,
            findings=tuple(all_findings[:limit]),
            findings_truncated=len(all_findings) > limit,
        )
    return OwnershipSummary(
        repo_id=repo_id,
        doc_count=len(owners),
        unowned_count=unowned_count,
        orphan_count=0,
        roster_checked=False,
        clean=True,
        findings=(),
        findings_truncated=False,
    )


# --- custodex_staleness: review-SLA grading, as-of an injected now ---------------


class StalenessSummary(BaseModel):
    """The ``custodex_staleness`` result: docs past their (audience-aware) SLA."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    now: str
    doc_count: int
    stale_count: int
    never_reviewed_count: int
    needs_review_total: int
    fresh: bool
    findings: tuple[StalenessFinding, ...]
    findings_truncated: bool
    summary: str


def staleness_summary(
    cfg: MonitorConfig,
    config_dir: Path,
    *,
    repo_id: str,
    now: str,
    include_fresh: bool = False,
    limit: int = _DEFAULT_LIST_CAP,
) -> StalenessSummary:
    """Grade each doc's ``reviewed`` date against its audience SLA, as-of ``now``.

    Reuses ``detect_stale`` (``now`` INJECTED — K10, never a clock read here);
    audience changes the SLA window (K3). ``needs_review_total`` = stale +
    never-reviewed; ``fresh`` is the one-glance "all within SLA" verdict. The
    counts stay exact regardless of the ``limit`` cap on ``findings``.
    """
    findings = detect_stale(
        reviewed_docs_from_config(cfg),
        now=now,
        default_days=cfg.staleness.default_days,
        audience_days=cfg.staleness.audience_days,
        include_fresh=include_fresh,
    )
    stale_count = sum(1 for f in findings if f.status is StalenessStatus.STALE)
    never = sum(1 for f in findings if f.status is StalenessStatus.NEVER_REVIEWED)
    needs = stale_count + never
    summary = (
        f"{needs} doc(s) need review "
        f"({stale_count} stale, {never} never reviewed) as of {now}"
    )
    return StalenessSummary(
        repo_id=repo_id,
        now=now,
        doc_count=len(cfg.documents),
        stale_count=stale_count,
        never_reviewed_count=never,
        needs_review_total=needs,
        fresh=needs == 0,
        findings=tuple(findings[:limit]),
        findings_truncated=len(findings) > limit,
        summary=summary,
    )


# --- custodex_worklist: the prioritised accountability join ----------------------


class WorkItemView(BaseModel):
    """One flattened work item — a :class:`WorkItem` tagged with its owner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accountable: str | None
    doc_id: str
    doc_path: str
    audience: str
    reason: str
    severity: str
    detail: str
    upstream_id: str | None


class WorklistSummary(BaseModel):
    """The ``custodex_worklist`` result: the top-``limit`` items in global order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    item_count: int
    doc_count: int
    owner_count: int
    includes_suspect: bool
    orphans_included: bool
    truncated: bool
    returned_item_count: int
    items: tuple[WorkItemView, ...]
    summary: str


def worklist_summary(
    cfg: MonitorConfig,
    config_dir: Path,
    *,
    repo_id: str,
    now: str,
    owner_filter: str | None = None,
    include_suspect: bool = True,
    roster: RosterSnapshot | None = None,
    limit: int = _DEFAULT_LIST_CAP,
) -> WorklistSummary:
    """Build the repo worklist, flatten across owners, and return the top-``limit``.

    Reuses ``worklist_from_repo`` (the ONE place the engine joins orphan + stale +
    suspect; ``now`` INJECTED, K10). Flattens every owner's queue and re-sorts by
    the engine's OWN priority key (``_item_sort_key``) so the cap drops the
    lowest-priority tail GLOBALLY (not per owner). ``item_count`` / ``doc_count``
    stay the untruncated totals. Orphans need a roster (``orphans_included``);
    ``includes_suspect`` echoes whether the doc↔doc detector ran.
    """
    root = resolve_repo_root(config_dir, cfg.root)
    worklist = worklist_from_repo(
        cfg,
        root,
        now=now,
        roster=roster,
        unit_owner=_unit_owner_map(config_dir),
        include_suspect=include_suspect,
        owner_filter=owner_filter,
    )
    flat: list[tuple[str | None, WorkItem]] = [
        (owner.accountable, item) for owner in worklist.owners for item in owner.items
    ]
    # Global priority order: the engine's OWN item key (severity, reason, doc_id,
    # upstream) — which is UNIQUE per work item (granularity is (doc_id, reason,
    # upstream_id)), so it is a total order and the cap keeps the highest-priority
    # items across ALL owners deterministically (K10). Reusing _item_sort_key keeps
    # the MCP order in lockstep with the CLI/engine rather than duplicating the
    # rank maps; no owner tiebreak is needed (the key never ties).
    flat.sort(key=lambda pair: _item_sort_key(pair[1]))
    items = tuple(
        WorkItemView(
            accountable=accountable,
            doc_id=item.doc_id,
            doc_path=item.doc_path,
            audience=item.audience.value,
            reason=item.reason.value,
            severity=item.severity.value,
            detail=item.detail,
            upstream_id=item.upstream_id,
        )
        for accountable, item in flat[:limit]
    )
    summary = (
        f"{worklist.item_count} item(s) across {worklist.doc_count} doc(s), "
        f"{len(worklist.owners)} owner(s)"
    )
    return WorklistSummary(
        repo_id=repo_id,
        item_count=worklist.item_count,
        doc_count=worklist.doc_count,
        owner_count=len(worklist.owners),
        includes_suspect=worklist.includes_suspect,
        orphans_included=roster is not None,
        truncated=len(flat) > len(items),
        returned_item_count=len(items),
        items=items,
        summary=summary,
    )


# --- custodex_doc_graph: doc↔doc edges + per-edge suspect status ------------------


class DocGraph(BaseModel):
    """The ``custodex_doc_graph`` result: the full graph with per-edge status.

    Richer than the hub's graph-only view: locally we hold the doc bodies, so
    every edge carries its SUSPECT status (K2). ``enabled`` disambiguates an empty
    graph (detection off vs genuinely no edges). The transitive-suspect advisory
    is deferred to a later additive field (K6).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    enabled: bool
    doc_count: int
    edge_count: int
    suspect_count: int
    gates: bool
    edges: tuple[SuspectLink, ...]
    summary: str


def doc_graph_summary(
    cfg: MonitorConfig, config_dir: Path, *, repo_id: str
) -> DocGraph:
    """Project the doc↔doc dependency graph + per-edge suspect status (K1/K2/K10).

    Reuses ``detect_suspect_links(include_ok=True)`` (the FULL graph, sorted
    ``(doc_id, upstream_id)``; returns ``()`` when ``docdeps`` is disabled — hence
    the explicit ``enabled`` flag). ``gates`` echoes whether a suspect link counts
    toward ``cdx check`` exit-1. Pure: no clock, no mutation.
    """
    root = resolve_repo_root(config_dir, cfg.root)
    edges = detect_suspect_links(cfg, root, include_ok=True)
    suspect_count = sum(1 for e in edges if e.status is not SuspectStatus.OK)
    summary = (
        f"doc graph: {len(edges)} edge(s) across {len(cfg.documents)} doc(s); "
        f"{suspect_count} suspect"
    )
    return DocGraph(
        repo_id=repo_id,
        enabled=cfg.docdeps.enabled,
        doc_count=len(cfg.documents),
        edge_count=len(edges),
        suspect_count=suspect_count,
        gates=cfg.docdeps.gate,
        edges=edges,
        summary=summary,
    )


# --- custodex_records: the local .cdmon review-log audit ------------------------


class RecordSummary(BaseModel):
    """One shaped audit row — the compact projection of a ``ReviewRecord``.

    Drops the heavy embedded blobs (``config_snapshot``, ``ticket``, ``fix``,
    tier tuples) — an MCP client wants the verdict + locus, not the full record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str
    doc_id: str
    doc_path: str
    audience: str
    drift_kind: str
    verdict: str
    change_severity: str
    detected_at: str
    resolved_at: str


class RecordList(BaseModel):
    """The ``custodex_records`` result: the newest-first, capped audit log."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    total: int
    returned: int
    truncated: bool
    by_verdict: dict[str, int]
    records: tuple[RecordSummary, ...]


def list_records(
    cfg: MonitorConfig,
    config_dir: Path,
    *,
    repo_id: str,
    verdict: str | None = None,
    limit: int = _DEFAULT_RECORD_CAP,
) -> RecordList:
    """Read the local ``.cdmon`` review log, newest-first, optionally by verdict.

    Reads ``config_dir / DEFAULT_LOG_PATH`` via ``reviewlog.read_all`` (a missing
    log is NORMAL — returns an empty list, not an error, K8-distinct from a
    malformed config). A bad ``verdict`` string is a loud typed :class:`McpError`.
    NEWEST-FIRST reverses the append-ordered log (the one deviation from the
    oldest-first CLI/server) — deterministic without parsing timestamps. Projects
    each record to a compact :class:`RecordSummary`. ``cfg`` is taken for
    signature symmetry with the other helpers (the log is under ``config_dir``).
    """
    _ = cfg  # signature symmetry; the review log lives under config_dir
    records = read_all(config_dir / DEFAULT_LOG_PATH)
    if verdict is not None:
        try:
            selected = Verdict(verdict)
        except ValueError as exc:
            valid = ", ".join(v.value for v in Verdict)
            raise McpError(
                f"unknown verdict {verdict!r}; expected one of: {valid}"
            ) from exc
        records = select_by_verdict(records, selected)
    by_verdict = summarize(records)["by_verdict"]
    capped = records[::-1][:limit]
    items = tuple(
        RecordSummary(
            record_id=r.record_id,
            doc_id=r.doc_id,
            doc_path=r.doc_path,
            audience=r.audience.value,
            drift_kind=r.drift_kind,
            verdict=r.verdict.value,
            change_severity=r.change_severity,
            detected_at=r.detected_at,
            resolved_at=r.resolved_at,
        )
        for r in capped
    )
    return RecordList(
        repo_id=repo_id,
        total=len(records),
        returned=len(items),
        truncated=len(records) > len(items),
        by_verdict=by_verdict,
        records=items,
    )


# --- MCP-02: the gated write tools (remediate / resolve / sync_docs) --------------
#
# Unlike every helper above (pure detect projections — K1), these three MUTATE via
# the engine's EXISTING write seams (``Monitor.run`` / ``reviewlog.append_resolution``
# / ``syncpr.sync_pr``). Each is GATED: an explicit ``apply=False`` default (K11 —
# "agents suggest; humans apply") passed THROUGH so a repo's ``apply_default`` can
# never re-enable a write implicitly, plus a per-server ``read_only`` switch (in
# ``server.py``) that refuses to mount them at all. The clock is INJECTED (K10); a
# bad input fails LOUD (K8) and a write NEVER half-degrades (no honest-partial here).


class RemediationItem(BaseModel):
    """One handled drift with its verdict, applied flag, record FK, and fix preview.

    The shaped subset of a ``HandledDrift`` + its ``ReviewRecord`` — DROPS the heavy
    ``config_snapshot``/``ticket``/tier blobs. ``record_id`` is the review-record id
    a client feeds to ``custodex_resolve`` — but it identifies the REVIEW RECORD, not
    this individual drift: every drift detected on ONE doc in ONE run shares it
    (``record_id`` = hash of ``doc_id`` + the doc's ``surface_hash`` + the injected
    stamp), exactly as the ``.cdmon`` log and ``cdx resolve`` already key it. So a
    resolution is recorded at the doc's-review-record grain (resolving it covers all
    of that doc's simultaneous drifts); use ``drift_kind`` + ``region_id`` to tell the
    facets apart. ``fix_preview`` is a CAPPED teaser of the proposed body
    (``fix_truncated`` flags the cut); the full fix stays in the on-disk record, so
    an apply never depends on this preview.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str
    doc_path: str
    drift_kind: str
    audience: str
    verdict: str
    cause: str
    applied: bool
    record_id: str
    region_id: str | None
    rationale: str | None
    fix_preview: str | None
    fix_truncated: bool


class RemediationResult(BaseModel):
    """The ``custodex_remediate`` result: per-drift verdicts + the audit outcome.

    ``applied`` echoes the effective gate; ``applied_count`` is how many drifts were
    actually written to a doc (only under ``apply=True`` + a ``FIX``). ``record_count``
    is the K5 audit lines written THIS run — note the record write is UNCONDITIONAL
    (even a dry-run records the proposals), so repeated previews grow the log; for a
    pure, record-free look at what is drifted use ``custodex_drift`` (K1). ``clean``
    is True only when no drift remains after the run (the K7 healed steady state).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    applied: bool
    clean: bool
    handled_count: int
    remaining_count: int
    applied_count: int
    record_count: int
    by_verdict: dict[str, int]
    items: tuple[RemediationItem, ...]
    truncated: bool
    summary: str


def _fix_preview(
    fix: ProposedFix | None, limit: int
) -> tuple[str | None, str | None, bool]:
    """``(region_id, capped-body-preview, truncated)`` for a fix, else ``(None,...)``.

    Mirrors ``heal.apply_fix``'s precedence — a whole-doc ``new_doc_text`` wins over a
    region ``new_region_body`` — so the preview shows the body that WOULD be applied.
    """
    if fix is None:
        return None, None, False
    body = fix.new_doc_text if fix.new_doc_text is not None else fix.new_region_body
    if body is None:
        return fix.region_id, None, False
    truncated = len(body) > limit
    return fix.region_id, (body[:limit] if truncated else body), truncated


def remediate_drift(
    cfg: MonitorConfig,
    config_dir: Path,
    *,
    repo_id: str,
    now: str,
    apply: bool = False,
    limit: int = _DEFAULT_LIST_CAP,
    fix_preview_limit: int = _DEFAULT_FIX_PREVIEW,
) -> RemediationResult:
    """Drive the remediation pipeline and shape the outcome (K5/K10/K11).

    Builds ``Monitor(cfg, config_dir, now=lambda: now)`` and calls
    ``.run(apply=apply)`` — ``apply`` passed THROUGH EXPLICITLY so a repo's
    ``apply_default: true`` can NEVER be triggered implicitly by a remote agent
    (stricter than ``cdx monitor``, which defaults to the config). ``apply=False``
    (the default) records one ``ReviewRecord`` per handled drift (the K5 audit — the
    proposal made auditable) but mutates NO doc; ``apply=True`` also heals ``FIX``
    verdicts. ``Monitor.run`` appends ``handled`` and ``records`` in lockstep
    (``strict=True``), so ``zip`` pairs each handled drift to its review record;
    NOTE the ``record_id`` is per-review-record, so a doc's simultaneous drifts
    share it (see :class:`RemediationItem`) — ``custodex_resolve`` acts at that
    record grain, matching ``cdx resolve``. Sorted ``(doc_id, region_id,
    drift_kind)`` and capped; totals stay exact. Deterministic under a fixed
    ``now`` (K10).
    """
    result = Monitor(cfg, config_dir, now=lambda: now).run(apply=apply)
    # Monitor.run appends one `handled` and one `record` per drift in lockstep, so
    # they are 1:1 and index-aligned — `strict=True` makes that invariant loud (a
    # mismatch would raise, never silently truncate the pairing).
    paired = [
        (handled, record.record_id)
        for handled, record in zip(result.handled, result.records, strict=True)
    ]
    paired.sort(
        key=lambda pr: (
            pr[0].drift.doc_id,
            pr[0].drift.region_id or "",
            pr[0].drift.kind.value,
        )
    )
    by_verdict: dict[str, int] = {}
    for handled, _rid in paired:
        value = handled.result.verdict.value
        by_verdict[value] = by_verdict.get(value, 0) + 1
    items: list[RemediationItem] = []
    for handled, record_id in paired[:limit]:
        region_id, preview, fix_truncated = _fix_preview(
            handled.result.fix, fix_preview_limit
        )
        items.append(
            RemediationItem(
                doc_id=handled.drift.doc_id,
                doc_path=handled.drift.doc_path,
                drift_kind=handled.drift.kind.value,
                audience=handled.drift.audience.value,
                verdict=handled.result.verdict.value,
                cause=handled.result.cause,
                applied=handled.applied,
                record_id=record_id,
                region_id=region_id,
                rationale=(
                    handled.result.fix.rationale
                    if handled.result.fix is not None
                    else None
                ),
                fix_preview=preview,
                fix_truncated=fix_truncated,
            )
        )
    applied_count = sum(1 for handled, _rid in paired if handled.applied)
    remaining = len(result.remaining)
    summary = (
        f"{len(paired)} drift(s) handled ({applied_count} applied), "
        f"{remaining} remaining as of {now}"
    )
    return RemediationResult(
        repo_id=repo_id,
        applied=apply,
        clean=remaining == 0,
        handled_count=len(paired),
        remaining_count=remaining,
        applied_count=applied_count,
        record_count=len(result.records),
        by_verdict=dict(sorted(by_verdict.items())),
        items=tuple(items),
        truncated=len(paired) > len(items),
        summary=summary,
    )


class ResolutionResult(BaseModel):
    """The ``custodex_resolve`` result: the recorded human outcome (K5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    record_id: str
    resolution: str
    recorded: bool
    resolved_by: str | None
    resolved_at: str
    note: str | None
    resolutions_path: str
    summary: str


def resolve_drift(
    cfg: MonitorConfig,
    config_dir: Path,
    *,
    repo_id: str,
    record_id: str,
    resolution: str,
    now: str,
    resolved_text: str | None = None,
    resolved_by: str | None = None,
    note: str | None = None,
) -> ResolutionResult:
    """Record a human OUTCOME for a handled drift as a separate append-only event.

    Mirrors ``cli.resolve``'s record mode EXACTLY (K5/K8): the ``record_id`` MUST
    exist in the review log (absent → loud ``McpError``), and ``resolution`` MUST be
    one of the four ``Resolution`` values (bad → loud ``McpError`` listing them,
    mirroring ``list_records``' verdict validation). Appends a ``ResolutionRecord``
    to ``.cdmon/resolutions.jsonl``; the review log is NEVER mutated (linked by FK).
    Append-only, LAST-WRITE-WINS: a re-resolution is a correction (a new event), not
    an idempotent no-op. ``resolved_at`` is the INJECTED ``now`` (K10, no clock read).
    """
    _ = cfg  # signature symmetry; the review + resolutions logs live under config_dir
    log_path = config_dir / DEFAULT_LOG_PATH
    if not any(r.record_id == record_id for r in read_all(log_path)):
        raise McpError(
            f"unknown record_id {record_id!r}: not found in the review log ({log_path})"
        )
    try:
        wanted = Resolution(resolution.lower())
    except ValueError as exc:
        choices = ", ".join(r.value for r in Resolution)
        raise McpError(
            f"unknown resolution {resolution!r} (choose from: {choices})"
        ) from exc
    append_resolution(
        config_dir / DEFAULT_RESOLUTIONS_PATH,
        ResolutionRecord(
            record_id=record_id,
            resolution=wanted,
            resolved_text=resolved_text,
            resolved_by=resolved_by,
            resolved_at=now,
            note=note,
        ),
    )
    return ResolutionResult(
        repo_id=repo_id,
        record_id=record_id,
        resolution=wanted.value,
        recorded=True,
        resolved_by=resolved_by,
        resolved_at=now,
        note=note,
        resolutions_path=DEFAULT_RESOLUTIONS_PATH.as_posix(),
        summary=f"recorded {record_id} as {wanted.value}",
    )


class SyncDocsResult(BaseModel):
    """The ``custodex_sync_docs`` result: a healed-docs preview (or applied heal).

    ``apply=False`` → a dry-run: the SAME patch is computed but the doc tree is
    restored byte-for-byte (K1), so ``patch`` shows what WOULD change without leaving
    a file touched. ``apply=True`` heals for real. ``patch`` is capped
    (``patch_truncated`` flags the cut). ``clean`` (empty patch) means no drift (K7).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    applied: bool
    clean: bool
    changed_count: int
    changed_paths: tuple[str, ...]
    patch: str
    patch_truncated: bool
    summary: str


def sync_docs(
    cfg: MonitorConfig,
    config_dir: Path,
    *,
    repo_id: str,
    now: str,
    apply: bool = False,
    patch_limit: int = _DEFAULT_PATCH_CAP,
) -> SyncDocsResult:
    """Preview (or apply) the doc heal as a unified diff (K1/K7/K10).

    Drives ``syncpr.sync_pr(Monitor(cfg, config_dir, now=lambda: now),
    dry_run=not apply)``. ``apply=False`` (the default) restores the tree
    byte-for-byte after computing the patch (K1: the NET effect is untouched — though
    ``sync_pr`` transiently heals-then-restores); ``apply=True`` leaves the heal in
    place. Like ``remediate``, the K5 audit records are written either way. The patch
    is CAPPED at ``patch_limit``.
    """
    monitor = Monitor(cfg, config_dir, now=lambda: now)
    result = sync_pr(monitor, dry_run=not apply)
    patch_truncated = len(result.patch) > patch_limit
    return SyncDocsResult(
        repo_id=repo_id,
        applied=apply,
        clean=result.patch == "",
        changed_count=len(result.changed_paths),
        changed_paths=result.changed_paths,
        patch=result.patch[:patch_limit] if patch_truncated else result.patch,
        patch_truncated=patch_truncated,
        summary=result.summary,
    )
