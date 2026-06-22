"""The central FastAPI app (E-03 — K0/K4/K6/K10).

:func:`create_app` builds a FastAPI app whose routes validate request bodies
against the SHARED, versioned schemas DIRECTLY — :class:`RegistrationPayload`
(``/repos``) and :class:`IngestEnvelope` (``/ingest``) — so a malformed body is a
422 from pydantic, with NO hand-written DTOs (K6). The :class:`Store` is
dependency-injected (tests pass a fresh :class:`InMemoryStore`; E-04 passes a DB
store behind the same Protocol).

Importing this module requires ``fastapi`` (the ``[server]`` extra); the package
``__init__`` keeps that import lazy so ``import code_doc_monitor`` core needs
nothing from here (K0, mirrors the ``[agent]`` extra).

**Unknown-repo policy (documented):** ingest never auto-registers. Registration is
explicit (``cdmon register``, E-02); an ``/ingest`` (or records read) for an
unregistered ``repo_id`` is a loud 404, not a silent create (K8).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..ownership import (
    EffectiveOwner,
    Identity,
    OwnershipStatus,
    RosterSnapshot,
    detect_orphans,
)
from ..promotion import PromotionCandidate, detect_promotions
from ..registry import RegistrationPayload
from ..schema import Resolution, ResolutionRecord, ReviewRecord, Verdict
from ..settings import GitSettings, Settings, resolve_settings, secret_presence
from ..sinks import IngestEnvelope
from ..staleness import StalenessFinding, StalenessStatus, grade_doc
from ..templates_v2 import V2_TEMPLATES
from .edits import ConfigEdit, StoredConfigEdit
from .store import (
    ConfigCodeRef,
    ConfigDocument,
    InMemoryStore,
    RegisteredRepo,
    Store,
    SyncRun,
    hash_token,
)

__all__ = [
    "create_app",
    "store_from_env",
    "RepoStatus",
    "RepoHealth",
    "RepoTelemetry",
    "ShapeStat",
    "CoverageIngest",
    "EditableConfigTree",
    "EditableDocument",
    "DocStyleOptions",
    "GenerateRequest",
    "GenerateResponse",
    "ApplyFixResponse",
]

# Cap on how many `ignored_files` paths the editable tree returns (E-04). The UI
# renders these in a collapsed details tab; an unbounded ignore set (a giant
# vendored tree) would bloat the payload, so we sort then truncate, logging a
# note when capped. Deterministic (K10): the same prefix every call.
_IGNORED_FILES_CAP = 200

_LOG = logging.getLogger("code_doc_monitor.server")


def _app_version() -> str:
    """The package version (one source of truth — was hardcoded twice as "0.1.0")."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("code-doc-monitor")
    except PackageNotFoundError:  # pragma: no cover - only when run from a non-install
        return "0.1.0"


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """A per-process, per-client fixed-window request cap (EPIC SVR hardening).

    Enabled only when ``server.rate_limit.requests_per_minute`` is set. The window is
    keyed by client host; ``now_epoch`` is injected (derived from the app clock) so the
    limiter is deterministic under test (K10). NOT distributed: with N workers the
    effective limit is N× — documented in DEPLOY.md.
    """

    def __init__(self, app: Any, *, limit: int, now_epoch: Callable[[], int]) -> None:
        super().__init__(app)
        self._limit = limit
        self._now = now_epoch
        self._window = -1  # the current fixed window; counters reset when it advances
        self._hits: dict[str, int] = {}  # client -> count IN the current window

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        client = request.client.host if request.client else "?"
        window = self._now() // 60
        if window != self._window:
            # New window: drop ALL prior counters so the map never grows unbounded
            # over a long-running server (one entry per client only WITHIN a window).
            self._window = window
            self._hits = {}
        count = self._hits.get(client, 0) + 1
        self._hits[client] = count
        if count > self._limit:
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        return await call_next(request)


# The EPIC-R wikis surfaced by `GET /wiki`, in deterministic display order
# (features, traceability, tests, source). Each tuple is
# ``(id, title, <feature-doc/-relative path>)`` — the SINGLE source of the
# section set + order shared by the route and the dashboard Wiki page (R-09).
WIKI_SECTIONS = (
    ("features", "Feature Reference", "FEATURES.md"),
    ("traceability", "Traceability Matrix", "wiki/TRACEABILITY.md"),
    ("tests", "Test Wiki", "wiki/TEST_WIKI.md"),
    ("source", "Source Wiki", "wiki/SOURCE_WIKI.md"),
)


def _wiki_dir() -> Path | None:
    """The committed EPIC-R wikis dir shipped beside the package, if present.

    Looks for ``feature-doc/`` at the repo root (two levels above this package,
    beside ``dashboard/dist`` the SPA loader finds) so a single ``cdmon``-server
    process can serve the rendered wikis on the same port as the API. Returns
    ``None`` when ``feature-doc/`` is absent (a non-cdmon repo) so ``GET /wiki``
    degrades to an empty payload rather than crashing (K8). Mirrors
    :func:`_default_static_dir`.
    """
    root = Path(__file__).resolve().parents[2] / "feature-doc"
    return root if root.is_dir() else None


def _load_wiki_sections(wiki_dir: Path | None) -> list[dict[str, str]]:
    """Render the committed EPIC-R wikis under ``wiki_dir`` to HTML sections (R-09).

    For each ``(id, title, relpath)`` in :data:`WIKI_SECTIONS` (deterministic
    order), if ``wiki_dir/relpath`` is a file, read it and append
    ``{"id", "title", "html"}`` with the body rendered by the engine's OWN
    dependency-free :func:`code_doc_monitor.build.render_markdown` (no new dep,
    K0). A missing file → that section omitted; ``wiki_dir is None`` → ``[]``.
    Pure (no clock, K10): the same bytes in, the same sections out. The renderer
    is imported lazily so ``import app`` (the TestClient path) stays cheap.
    """
    if wiki_dir is None:
        return []
    from ..build import render_markdown

    sections: list[dict[str, str]] = []
    for section_id, title, relpath in WIKI_SECTIONS:
        path = wiki_dir / relpath
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            sections.append(
                {"id": section_id, "title": title, "html": render_markdown(text)}
            )
    return sections


class CoverageIngest(BaseModel):
    """The ``POST /repos/{id}/coverage`` body — a permissive coverage snapshot (T-02).

    Deliberately ``extra="allow"`` (the ONE exception to the repo's stored/wire
    ``extra="forbid"`` rule): the body carries the FULL ``coverage.coverage_snapshot``
    wire dict (``files``, baskets, percents, ``ratio``) whose shape evolves with its
    ``schema_version``, so the server stores it OPAQUELY rather than re-declaring every
    field here. Only ``captured_at`` (the client-injected ISO timestamp, K10) is typed;
    the route persists ``model_dump(mode="json")`` verbatim via the store seam.
    """

    model_config = ConfigDict(extra="allow")

    captured_at: str


class GenerateRequest(BaseModel):
    """The ``POST /repos/{id}/config/generate`` body — which edits to make live (E-06).

    ``edit_ids`` (optional) selects which PENDING edits to apply; ``None`` (the
    default) applies every pending edit for the repo. ``mode`` is the sync mode the
    route re-runs after writing (``"local"`` — the working-tree view — by default,
    since generation just mutated the working tree). Frozen ``extra="forbid"`` so a
    stray field is a loud 422 (K8).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    edit_ids: list[str] | None = None
    mode: str = "local"


class SyncRequest(BaseModel):
    """The ``POST /repos/{id}/sync`` body — which sync to run (Y-02).

    ``mode`` is ``"git"`` (the default-branch baseline) or ``"local"`` (the
    working tree). An unknown mode is rejected as a loud 400 by the route (the
    engine raises :class:`~code_doc_monitor.errors.SyncError`), not a 422 — the
    field itself is a free string so the route owns the (uniform) error message.
    """

    model_config = ConfigDict(extra="forbid")

    mode: str


class DocsPrRequest(BaseModel):
    """The ``POST /repos/{id}/docs-pr`` body — open a docs PR upstream (GIT-04).

    ``dry_run`` heals + plans the PR but does NOT call the provider (returns the
    would-be plan instead of a real MR/PR). The repo must carry ``provider`` +
    ``remote_url`` (and, for a private repo, a sealed credential) — the route
    clones it on demand, so there is no ``mode``/``local_path`` here.
    """

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False


class DocumentTree(BaseModel):
    """One :class:`ConfigDocument` with its nested ``code_refs`` (W-01 view).

    The relationship view the Documents page renders: the SHARED stored
    :class:`ConfigDocument` fields plus its child :class:`ConfigCodeRef` rows
    (stable order, K10). Not a parallel copy of a stored model — a JOIN VIEW over
    two stored models — so K6's "no DTOs for a SHARED schema" does not apply.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document: ConfigDocument
    code_refs: tuple[ConfigCodeRef, ...]


class EditableDocument(BaseModel):
    """One document in the editable tree (EDITOR E-04) — a JOIN VIEW, not a DTO.

    The same join shape as :class:`DocumentTree` (the SHARED stored
    :class:`ConfigDocument` plus its child :class:`ConfigCodeRef` rows in stable
    K10 order) — but surfaced under the ``document``/``code_refs`` keys the editor
    page reads, with the document's ``context_refs`` already carried on the
    embedded :class:`ConfigDocument` (E-03). Not a parallel copy of a SHARED
    schema, so K6's "no DTOs" rule does not apply.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document: ConfigDocument
    code_refs: tuple[ConfigCodeRef, ...]


class DocStyleOptions(BaseModel):
    """The selectable doc-style options per category (EDITOR E-04).

    The available writing-template STEMS under the repo's
    ``templates/writing/<category>/`` for the four fixed categories
    (:data:`code_doc_monitor.docstyle.STYLE_CATEGORIES`), keyed by the
    selection-model attribute name so the UI maps a dropdown to the field it
    edits. Sorted + deterministic (K10); an absent category dir yields ``()``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_type: tuple[str, ...] = ()
    tone: tuple[str, ...] = ()
    writing_style: tuple[str, ...] = ()
    vocabulary: tuple[str, ...] = ()


class EditableConfigTree(BaseModel):
    """The full editable config tree for one repo (EDITOR E-04) — a COMPUTED VIEW.

    What the editor page needs to render the document↔code mapping and the
    mapping-ticket form (EDITOR §6): the stored ``documents`` (each with its
    ``code_refs`` + ``context_refs``), the in-scope-but-unlinked
    ``undocumented_files`` (the coverage gap, repo-root-relative + sorted), the
    ``ignored_files`` (matched by the ignore/gitignore globs, sorted + capped),
    the on-disk ``unit_files`` stems (which units exist to target), and the
    selectable ``doc_styles`` per category. An AGGREGATE over store reads + the
    repo working tree, NOT a parallel copy of a SHARED schema, so K6's "no DTOs"
    rule does not apply. Robust (K8): a central-only repo (no readable
    ``local_path``) still returns its stored ``documents`` with empty disk-derived
    lists rather than raising.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    sync_kind: str
    documents: tuple[EditableDocument, ...]
    undocumented_files: tuple[str, ...]
    ignored_files: tuple[str, ...]
    unit_files: tuple[str, ...]
    doc_styles: DocStyleOptions


class GenerateResponse(BaseModel):
    """The ``POST /config/generate`` response — what was made live (E-06) — a VIEW.

    ``applied`` is the edit ids that were applied to disk (empty for a no-op
    generate). ``sync_run`` is the FRESH :class:`SyncRun` from the post-generate
    re-sync (the dashboard reads it for the now-live state); ``None`` only for a
    no-op generate that found no prior sync. ``undocumented_files`` is the
    recomputed coverage gap (the editable-tree ``undocumented_files``), so the UI
    can confirm a just-linked file dropped out. An AGGREGATE over store reads + the
    working tree, NOT a parallel copy of a SHARED schema, so K6's "no DTOs" rule
    does not apply. Frozen + ``extra="forbid"`` (K8).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: tuple[str, ...]
    sync_run: SyncRun | None
    undocumented_files: tuple[str, ...]


class ApplyFixResponse(BaseModel):
    """The ``POST /records/{id}/apply-fix`` response — what the LLM fix changed (E-07).

    A computed VIEW (like :class:`GenerateResponse`), NOT a parallel copy of a
    SHARED schema, so K6's "no DTOs" rule does not apply. ``applied`` is ``True``
    only when the doc file changed (an already-applied fix is a no-op, K7);
    ``doc_path`` is the repo-relative document the fix targeted; ``diff`` is the
    unified before→after diff (empty when unchanged). ``sync_run`` is the FRESH
    :class:`SyncRun` from the post-apply re-sync (the dashboard reads it for the
    now-live state). Frozen + ``extra="forbid"`` (K8).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    doc_path: str
    diff: str
    sync_run: SyncRun | None


class RepoStatus(BaseModel):
    """A COMPUTED status view for one repo (E-05) — the one allowed response DTO.

    This is an AGGREGATE over the stored records/resolutions, NOT a parallel copy of a
    stored shared model, so K6's "no DTOs for the SHARED schema" does not apply: the
    record/resolution endpoints still return the SHARED ``ReviewRecord``/
    ``ResolutionRecord`` directly. ``by_verdict`` always carries all three verdict keys
    (zero-filled) so the dashboard renders a stable shape (K10).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    total_records: int
    by_verdict: dict[str, int]
    escalations: int
    unresolved: int
    last_detected_at: str | None = None
    coverage_ratio: float | None = None


def _compute_status(store: Store, repo_id: str) -> RepoStatus:
    """Aggregate a :class:`RepoStatus` from store reads (over the stored schema)."""
    records = store.records_for(repo_id)
    by_verdict = {v.value: 0 for v in Verdict}
    for rec in records:
        by_verdict[rec.verdict.value] += 1
    resolved_ids = {r.record_id for r in store.resolutions_for_repo(repo_id)}
    unresolved = sum(1 for r in records if r.record_id not in resolved_ids)
    last_detected_at = max((r.detected_at for r in records), default=None)
    coverage = store.coverage_for(repo_id)
    coverage_ratio = None
    if coverage:
        latest = coverage[-1]
        ratio = latest.get("ratio")
        if isinstance(ratio, (int, float)):
            coverage_ratio = float(ratio)
    return RepoStatus(
        repo_id=repo_id,
        total_records=len(records),
        by_verdict=by_verdict,
        escalations=by_verdict[Verdict.ESCALATE.value],
        unresolved=unresolved,
        last_detected_at=last_detected_at,
        coverage_ratio=coverage_ratio,
    )


class RepoHealth(BaseModel):
    """A COMPUTED metrics view for one repo (F-05) — like :class:`RepoStatus`, a VIEW.

    This is an AGGREGATE over the stored records/resolutions, NOT a parallel copy of a
    stored shared model, so K6's "no DTOs for the SHARED schema" does not apply (the
    resolution write/read endpoints still carry the SHARED ``ResolutionRecord``). All
    fields are deterministic functions of store reads (K10): ``mttr_seconds`` is the
    mean ``resolved_at - detected_at`` over records that HAVE a resolution (``None`` if
    none), derived from the records'/resolutions' injected ISO timestamps.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    total: int
    escalations: int
    escalation_rate: float
    unresolved: int
    overrides: int
    resolved: int
    mttr_seconds: float | None = None


def _parse_iso(value: str) -> datetime:
    """Parse an injected ISO-8601 timestamp (accepting a trailing ``Z``) (K10)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _compute_health(store: Store, repo_id: str) -> RepoHealth:
    """Aggregate a :class:`RepoHealth` from store reads (over the stored schema)."""
    records = store.records_for(repo_id)
    total = len(records)
    escalations = sum(1 for r in records if r.verdict is Verdict.ESCALATE)
    # First resolution per record wins the MTTR delta (insertion order, K10).
    resolution_by_record: dict[str, ResolutionRecord] = {}
    overrides = 0
    for res in store.resolutions_for_repo(repo_id):
        if res.resolution is Resolution.OVERRIDDEN:
            overrides += 1
        resolution_by_record.setdefault(res.record_id, res)
    deltas: list[float] = []
    for rec in records:
        matched = resolution_by_record.get(rec.record_id)
        if matched is None:
            continue
        deltas.append(
            (
                _parse_iso(matched.resolved_at) - _parse_iso(rec.detected_at)
            ).total_seconds()
        )
    resolved = sum(1 for rec in records if rec.record_id in resolution_by_record)
    mttr_seconds = sum(deltas) / len(deltas) if deltas else None
    return RepoHealth(
        repo_id=repo_id,
        total=total,
        escalations=escalations,
        escalation_rate=(escalations / total) if total else 0.0,
        unresolved=total - resolved,
        overrides=overrides,
        resolved=resolved,
        mttr_seconds=mttr_seconds,
    )


class ShapeStat(BaseModel):
    """Telemetry for ONE ``(drift_kind, audience)`` drift shape (H-01) — a VIEW.

    A computed aggregate (like :class:`RepoHealth`), NOT a stored shared model, so K6's
    "no DTOs for the SHARED schema" does not apply. ``escalation_rate`` /
    ``override_rate`` are fractions of this shape's ``count`` (always >= 1, so no
    zero-division). Deterministic (K10).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    drift_kind: str
    audience: str
    count: int
    escalations: int
    escalation_rate: float
    overrides: int
    override_rate: float


class RepoTelemetry(BaseModel):
    """A COMPUTED underperformer view for one repo (H-01) — like :class:`RepoHealth`.

    Surfaces which drift SHAPES the backend handles poorly (high escalate / high human
    override), worst-first, plus the :func:`detect_promotions` candidates ripe to
    auto-promote. An AGGREGATE over store reads, NOT a parallel copy of a stored shared
    model, so K6's "no DTOs" rule does not apply. Fully deterministic (K10).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    shapes: tuple[ShapeStat, ...]
    promotion_candidates: tuple[PromotionCandidate, ...]


def _compute_telemetry(store: Store, repo_id: str) -> RepoTelemetry:
    """Aggregate a :class:`RepoTelemetry` from store reads (over the stored schema).

    Shape key = ``(drift_kind, audience)``. ``escalations`` counts ESCALATE verdicts;
    ``overrides`` counts records whose FIRST resolution (insertion order, mirroring
    :func:`_compute_health`) is ``OVERRIDDEN``. Shapes are sorted WORST-FIRST:
    ``escalation_rate`` desc, then ``override_rate`` desc, then ``(drift_kind,
    audience)`` asc as the deterministic tie-break (K10).
    """
    records = store.records_for(repo_id)
    resolutions = store.resolutions_for_repo(repo_id)
    # First resolution per record wins (insertion order, K10).
    resolution_by_record: dict[str, ResolutionRecord] = {}
    for res in resolutions:
        resolution_by_record.setdefault(res.record_id, res)

    counts: dict[tuple[str, str], dict[str, int]] = {}
    for rec in records:
        key = (rec.drift_kind, rec.audience.value)
        bucket = counts.setdefault(key, {"count": 0, "escalations": 0, "overrides": 0})
        bucket["count"] += 1
        if rec.verdict is Verdict.ESCALATE:
            bucket["escalations"] += 1
        matched = resolution_by_record.get(rec.record_id)
        if matched is not None and matched.resolution is Resolution.OVERRIDDEN:
            bucket["overrides"] += 1

    shapes = [
        ShapeStat(
            drift_kind=drift_kind,
            audience=audience,
            count=b["count"],
            escalations=b["escalations"],
            escalation_rate=b["escalations"] / b["count"],
            overrides=b["overrides"],
            override_rate=b["overrides"] / b["count"],
        )
        for (drift_kind, audience), b in counts.items()
    ]
    shapes.sort(
        key=lambda s: (
            -s.escalation_rate,
            -s.override_rate,
            s.drift_kind,
            s.audience,
        )
    )
    candidates = detect_promotions(list(records), list(resolutions))
    return RepoTelemetry(
        repo_id=repo_id,
        shapes=tuple(shapes),
        promotion_candidates=tuple(candidates),
    )


def _default_now() -> str:
    """The server clock seam (ISO-8601 UTC) — injected so syncs are deterministic.

    Mirrors :func:`code_doc_monitor.config._now`. The config-sync route stamps
    ``synced_at`` / ``started_at`` / ``finished_at`` from this ONE seam; tests
    pass a fixed ``clock`` to :func:`create_app` so the persisted run rows are
    deterministic (K10). Records ingested over ``/ingest`` carry their OWN
    client-injected timestamps, so they do not use this seam.
    """
    return datetime.now(timezone.utc).isoformat()


def _new_edit_id(repo_id: str, edit: ConfigEdit, now: str) -> str:
    """Derive a deterministic 12-char edit id from the staged edit (EDITOR E-05, K10).

    Mirrors :func:`code_doc_monitor.schema.new_record_id`: a sha1 prefix over the
    repo id, the edit's canonical JSON (pydantic ``model_dump_json`` is stable for a
    frozen ``extra="forbid"`` model) and the injected ``now``. With a fixed clock the
    SAME edit body always yields the SAME id, so staging is reproducible and the
    route never reaches for a wall-clock or a counter.
    """
    # ``edit`` is a member of the discriminated union, not the Annotated alias
    # itself, so it always exposes ``model_dump_json`` at runtime.
    canonical = edit.model_dump_json()
    joined = "\x00".join((repo_id, canonical, now))
    return "edit-" + hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def _scan_doc_styles(templates_root: Path) -> DocStyleOptions:
    """List the available writing-template stems per category (EDITOR E-04).

    For each of the four fixed style categories
    (:data:`~code_doc_monitor.docstyle.STYLE_CATEGORIES`), collect the ``*.md``
    stems under ``templates_root/<category>/`` — the values the mapping-ticket
    form offers as dropdown options. Sorted + deterministic (K10); a missing
    category dir contributes ``()``. Reuses the docstyle module's category list
    (no re-declaring the names).
    """
    from ..docstyle import STYLE_CATEGORIES

    by_attr: dict[str, tuple[str, ...]] = {}
    for attr, subdir in STYLE_CATEGORIES:
        category_dir = templates_root / subdir
        if category_dir.is_dir():
            stems = sorted(p.stem for p in category_dir.glob("*.md") if p.is_file())
        else:
            stems = []
        by_attr[attr] = tuple(stems)
    return DocStyleOptions(**by_attr)


def _disk_editable_parts(
    local_path: str | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], DocStyleOptions]:
    """Compute the working-tree-derived editable-tree fields (EDITOR E-04).

    Returns ``(undocumented_files, ignored_files, unit_files, doc_styles)`` for a
    repo whose working tree is at ``local_path``:

    * ``undocumented_files`` — the coverage gap: in-scope ``.py``/format files
      under the unit ``dir-covered`` not referenced by ANY ``code_ref``. Reuses
      the REAL coverage engine (:func:`effective_coverage` → ``discover_files`` →
      ``discover_symbols`` → ``resolve_coverage``) — the same path
      :func:`code_doc_monitor.report.build_coverage_rpt` walks — never a re-scan.
    * ``ignored_files`` — the files the ignore/gitignore globs removed from the
      in-scope universe: the dir×format includes scanned with ONLY the default
      excludes, minus the post-ignore universe (the set form of
      :func:`code_doc_monitor.report._count_ignored`'s count). Sorted + capped to
      :data:`_IGNORED_FILES_CAP` (a note is logged when truncated).
    * ``unit_files`` — the on-disk unit STEMS (reusing
      :func:`code_doc_monitor.config._scan_unit_files`'s glob, minus the reserved
      pointers), e.g. ``("core", "io")``.
    * ``doc_styles`` — :func:`_scan_doc_styles` over the repo's templates root.

    Robust (K8): a repo with NO readable ``local_path`` or NO
    ``config/cdmon/index.yaml`` yields all-empty parts WITHOUT raising, so the
    OPEN route still serves the stored documents for a central-only repo. The
    heavy config/coverage stack is imported lazily (K0).
    """
    empty: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], DocStyleOptions]
    empty = ((), (), (), DocStyleOptions())
    if not local_path:
        return empty
    repo_dir = Path(local_path)
    config_dir = repo_dir / "config" / "cdmon"
    if not (config_dir / "index.yaml").is_file():
        return empty

    from .. import inventory
    from ..config import (
        _DEFAULT_EXCLUDE,
        RESERVED_UNIT_STEMS,
        effective_coverage,
        gitignore_to_globs,
        load_bundle,
        load_ignore_file,
        resolve_repo_root,
    )
    from ..coverage import resolve_coverage
    from ..errors import CodeDocMonitorError
    from ..inventory import _matches_any, _translate

    try:
        bundle = load_bundle(config_dir)
        repo_root = resolve_repo_root(config_dir, bundle.index.root)
        cov = effective_coverage(bundle, repo_root)
        inv = inventory.discover_files(
            repo_root, include=cov.include, exclude=cov.exclude
        )
        sym = inventory.discover_symbols(inv, repo_root)
        report = resolve_coverage(bundle.config, sym)
        undocumented = tuple(sorted(f.path for f in report.undocumented_files))

        # ignored_files: files UNDER the unit dir-covered dirs (ANY extension —
        # not just the source formats, so a sibling notes.log counts) that the
        # effective IGNORE set matches. Build the ignore globs the same way
        # effective_coverage does (ignore.patterns ∪ translated .gitignore), scan
        # the unit dirs with default excludes only, then keep ignore-matched
        # files. Sorted + capped (K10).
        ignore_globs: list[str] = []
        ignore_path = config_dir / bundle.index.ignore
        if ignore_path.is_file():
            ignore_cfg = load_ignore_file(ignore_path)
            ignore_globs.extend(ignore_cfg.patterns)
            if ignore_cfg.gitignore:
                gitignore_path = repo_root / ".gitignore"
                if gitignore_path.is_file():
                    ignore_globs.extend(
                        gitignore_to_globs(gitignore_path.read_text(encoding="utf-8"))
                    )

        def _dir_glob(d: str) -> str:
            return d.replace("\\", "/").strip("/") + "/**"

        unit_dir_globs = tuple(
            _dir_glob(d) for unit in bundle.units for d in unit.dir_covered
        )
        ignore_patterns = tuple(_translate(p) for p in ignore_globs)
        if unit_dir_globs and ignore_patterns:
            under_units = inventory.discover_files(
                repo_root, include=unit_dir_globs, exclude=_DEFAULT_EXCLUDE
            )
            ignored_all = sorted(
                f.path
                for f in under_units.files
                if _matches_any(f.path, ignore_patterns)
            )
        else:
            ignored_all = []
        if len(ignored_all) > _IGNORED_FILES_CAP:
            _LOG.info(
                "editable tree: %d ignored files for %s exceeds cap %d; truncating",
                len(ignored_all),
                local_path,
                _IGNORED_FILES_CAP,
            )
        ignored = tuple(ignored_all[:_IGNORED_FILES_CAP])

        unit_files = tuple(
            sorted(
                p.stem
                for p in config_dir.glob("*.yaml")
                if p.is_file() and p.stem not in RESERVED_UNIT_STEMS
            )
        )
        doc_styles = _scan_doc_styles(repo_root / "templates" / "writing")
    except CodeDocMonitorError:
        # A malformed config / unreadable tree must not 500 an OPEN read route
        # (K8): fall back to the stored documents with empty disk parts.
        return empty
    return undocumented, ignored, unit_files, doc_styles


def _allowed_git_hosts(git: GitSettings | None = None) -> set[str]:
    """The clone/PR host allowlist (SSRF guard, GIT-04 + EPIC SVR).

    With ``git`` settings (EPIC SVR) the allowlist is ``allowed_hosts`` +
    ``extra_allowed_hosts`` (``$CDMON_ALLOWED_GIT_HOSTS`` is already folded into the
    latter by ``settings_from_env``). Without it (back-compat callers) it is the two
    public providers plus ``$CDMON_ALLOWED_GIT_HOSTS`` read directly from the env.
    """
    if git is not None:
        return set(git.allowed_hosts) | set(git.extra_allowed_hosts)
    hosts = {"github.com", "gitlab.com"}
    extra = os.environ.get("CDMON_ALLOWED_GIT_HOSTS", "")
    return hosts | {h.strip() for h in extra.split(",") if h.strip()}


def _check_remote_allowed(remote_url: str, *, git: GitSettings | None = None) -> None:
    """Reject a ``remote_url`` not on the https allowlist (nor a ``file://``) (K8).

    The server clones an ADOPTER-supplied URL, so it must not be coaxed into
    reaching an arbitrary internal host (SSRF). ``https`` is allowed only to a host
    on :func:`_allowed_git_hosts`; ``file://`` (a local path/mirror — no network
    egress) is allowed UNLESS ``git.allow_file_scheme`` is False (EPIC SVR — a
    shared deployment may forbid it); any other scheme/host is a loud 400.
    """
    from urllib.parse import urlparse

    parsed = urlparse(remote_url)
    if parsed.scheme == "file":
        if git is not None and not git.allow_file_scheme:
            raise HTTPException(
                status_code=400,
                detail="file:// remote urls are disabled by server settings",
            )
        return
    if parsed.scheme != "https":
        raise HTTPException(
            status_code=400,
            detail=f"remote_url must be https:// or file://, got {parsed.scheme or '?'}://",
        )
    if parsed.hostname not in _allowed_git_hosts(git):
        raise HTTPException(
            status_code=400,
            detail=(
                f"remote_url host {parsed.hostname!r} is not on the git host "
                "allowlist (set server.git.extra_allowed_hosts / "
                "$CDMON_ALLOWED_GIT_HOSTS for self-hosted providers)"
            ),
        )


def _iso_to_epoch(iso: str) -> int:
    """Epoch seconds from the injected ISO clock string (for the PHASE-2 JWT, K10)."""
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _resolve_provider_token(
    store: Store, repo: RegisteredRepo, *, now: str, token_exchange_http: Any
) -> str | None:
    """The EFFECTIVE git token for a repo, or ``None`` for a public clone (GIT-04/05).

    Opens the sealed credential with the KEK (``$CDMON_SECRET_KEY``; a missing/wrong
    KEK raises :class:`~code_doc_monitor.errors.SecretError` → the route's 500). Then,
    by ``provider_kind``: ``None``/``"token"`` (PHASE 1) → the opened secret IS the
    token, replayed as-is; ``"github-app"``/``"gitlab-oauth"`` (PHASE 2) → the opened
    secret is a JSON credential and a SHORT-LIVED access token is minted from it via
    :func:`code_doc_monitor.gitauth.mint_provider_token` (the hot token is never
    stored). A mint failure is a loud :class:`~code_doc_monitor.errors.TransportError`.
    """
    sealed = store.repo_provider_secret(repo.repo.repo_id)
    if sealed is None:
        return None
    from ..secrets import secret_box_from_env

    material = secret_box_from_env().open_secret(sealed)
    kind = repo.repo.provider_kind
    if kind in ("github-app", "gitlab-oauth"):
        from ..gitauth import mint_provider_token

        return mint_provider_token(
            kind, material, now=_iso_to_epoch(now), http=token_exchange_http
        )
    return material


def create_app(
    store: Store | None = None,
    *,
    static_dir: Path | None = None,
    wiki_dir: Path | None = None,
    clock: Callable[[], str] = _default_now,
    cloner: Any = None,
    pr_transport_factory: Callable[[str, str, str | None], Any] | None = None,
    token_exchange_http: Any = None,
    admin_token: str | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Build the central FastAPI app over ``store`` (DI; defaults to in-memory).

    The store is resolved through a FastAPI dependency so routes stay
    store-agnostic and tests/E-04 can override it. ``store is None`` -> a default
    :class:`InMemoryStore` (so prod can omit it until E-04 wires the DB store).

    ``clock`` is the server time seam (Y-02): the config-sync route stamps its
    persisted rows from it, so tests inject a fixed clock for determinism (K10).

    ``static_dir`` (optional) is a built dashboard SPA (``dashboard/dist``): when
    given and it holds an ``index.html``, the app serves the console at ``/`` and
    its assets at ``/assets`` on the SAME port as the API — a single-origin
    deploy. The SPA uses a hash router, so its client routes never shadow the
    API's ``/repos/...`` paths. Omitted (the default, and in tests) -> ``/`` is a
    JSON landing payload instead.

    ``wiki_dir`` (optional) is the committed EPIC-R wikis dir (``feature-doc/``)
    served, rendered to HTML, by the public ``GET /wiki`` (R-09). ``None`` (the
    default) auto-resolves to :func:`_wiki_dir` (the repo's ``feature-doc/``), so
    the live ``cdmon serve`` path serves the wikis with no extra wiring; a tmp dir
    is injected in tests. An absent dir → an empty ``/wiki`` payload (K8).

    ``cloner`` / ``pr_transport_factory`` (optional, GIT-04) are the clone + PR
    seams behind the remote ``POST /sync`` and ``POST /docs-pr`` routes. Both
    default to the real implementations (a :class:`~code_doc_monitor.gitfetch`
    git-clone leaf and ``{GitHub,GitLab}Transport.from_repo``); tests inject a fake
    cloner (copies a fixture tree) and a fake transport factory so the routes run
    fully offline (K4). ``pr_transport_factory(provider, remote_url, token)``
    returns a :class:`~code_doc_monitor.pr.PRTransport`. ``token_exchange_http``
    (GIT-05, PHASE 2) is the injected leaf the App/OAuth short-lived-token mint uses
    (:mod:`code_doc_monitor.gitauth`); default real, faked in tests so minting is
    offline.

    ``settings`` (optional, EPIC SVR) are the operator runtime settings; ``None``
    resolves them from ``config/settings.yaml`` + env + defaults. They drive the
    CORS / TrustedHost / rate-limit middleware (each added only when configured, so
    the default is byte-identical to the un-hardened app), the git SSRF allowlist,
    and (via :func:`main`) the uvicorn host/port/log level.
    """
    resolved: Store = store if store is not None else InMemoryStore()
    resolved_wiki_dir: Path | None = wiki_dir if wiki_dir is not None else _wiki_dir()
    # EPIC SVR: the operator runtime settings (host/port + the CORS/TrustedHost/
    # rate-limit/git-allowlist hardening knobs). ``None`` ⇒ resolve from
    # config/settings.yaml + env + defaults (defaults reproduce today's behavior).
    app_settings: Settings = settings if settings is not None else resolve_settings()
    srv = app_settings.server
    # EPIC OWN: the GLOBAL admin token gating cross-repo roster mutations. From the
    # param or $CDMON_ADMIN_TOKEN; held only as a sha256 hash (never plaintext). None
    # ⇒ the roster routes stay open (offline/dev), exactly like a token-less repo.
    effective_admin = (
        admin_token if admin_token is not None else os.environ.get("CDMON_ADMIN_TOKEN")
    )
    admin_hash: str | None = hash_token(effective_admin) if effective_admin else None
    if admin_hash is None:
        # Loud on an insecure prod default (K8 spirit, mirrors store_from_env's
        # missing-DATABASE_URL warning): a roster mutation is GLOBAL — it re-flags
        # orphans in EVERY repo — so an unset admin token leaves cross-repo
        # ownership writable by anyone. Stay quiet for the offline/dev InMemoryStore
        # (the warning would spam the test suite); warn only for a PERSISTENT,
        # real-deployment store.
        from .db import SqlStore

        if isinstance(resolved, SqlStore):
            _LOG.warning(
                "CDMON_ADMIN_TOKEN is not set — the GLOBAL admin roster routes "
                "(POST /admin/roster, POST /admin/roster/{name}/departed) are "
                "UNPROTECTED. A roster mutation cascades to flag orphans in EVERY "
                "repo, so an unauthenticated caller can poison ownership "
                "server-wide. Set CDMON_ADMIN_TOKEN in any shared/prod deployment."
            )
    app = FastAPI(title="code-doc-monitor central server", version=_app_version())

    # EPIC SVR hardening middleware — each added ONLY when the operator configures it,
    # so an un-tuned deployment is byte-identical to the pre-SVR app (back-compat).
    # add_middleware applies LAST-added-outermost; the SPA catch-all mount (registered
    # last, far below) is wrapped by all of these, so they guard the whole app.
    if srv.cors.allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(srv.cors.allow_origins),
            allow_credentials=srv.cors.allow_credentials,
            allow_methods=list(srv.cors.allow_methods),
            allow_headers=list(srv.cors.allow_headers),
        )
    if srv.rate_limit.requests_per_minute is not None:
        app.add_middleware(
            _RateLimitMiddleware,
            limit=srv.rate_limit.requests_per_minute,
            now_epoch=lambda: _iso_to_epoch(clock()),
        )
    if srv.trusted_hosts != ("*",):  # ["*"] is a no-op (accept any Host) — today
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(srv.trusted_hosts))

    spa_index: Path | None = None
    if static_dir is not None:
        candidate = Path(static_dir) / "index.html"
        if candidate.is_file():
            spa_index = candidate
            # The built site is mounted as a single catch-all at the END of
            # create_app (after every API route), so the API always wins and the
            # whole `dist/` — index.html, native `/wiki/*` pages, `/_astro/*`
            # assets — is served. See the `app.mount("/", ...)` before `return`.

    def get_store() -> Store:
        return resolved

    def _make_transport(provider: str, remote_url: str, token: str | None) -> Any:
        """Build the provider PR transport (GIT-04) — injectable for tests (K4)."""
        if pr_transport_factory is not None:
            return pr_transport_factory(provider, remote_url, token)
        from ..pr import GitHubTransport, GitLabTransport

        if provider == "github":
            return GitHubTransport.from_repo(remote_url, token or "")
        return GitLabTransport.from_repo(remote_url, token or "")

    def _require_known_repo(store: Store, repo_id: str) -> None:
        if store.get_repo(repo_id) is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"unknown repo_id {repo_id!r}; register it first "
                    "(cdmon register / POST /repos)"
                ),
            )

    def _verify_token(store: Store, repo_id: str, authorization: str | None) -> None:
        """E-06 per-repo bearer auth on WRITES (404 unknown / 401 missing / 403 wrong).

        A repo with NO stored token hash stays open (back-compat). Otherwise the
        ``Authorization: Bearer <t>`` header is required (401 if missing/not-Bearer) and
        its sha256 must equal the stored hash (403 if not). Reads do not call this.
        """
        token_hash = store.repo_token_hash(repo_id)
        if token_hash is None:
            return  # repo registered without a token -> writes are open
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="missing bearer token for a token-protected repo",
            )
        presented = authorization.removeprefix("Bearer ").strip()
        # Constant-time compare (defense-in-depth): the operands are sha256 hex
        # digests, not the raw secret, so no token can be forged, but a uniform
        # compare avoids leaking even a digest-match timing signal.
        if not hmac.compare_digest(hash_token(presented), token_hash):
            raise HTTPException(status_code=403, detail="invalid bearer token")

    def _verify_admin(authorization: str | None) -> None:
        """Admin-token auth for cross-repo roster mutations (OWN-04).

        A roster change is GLOBAL (it re-flags orphans in EVERY repo), so it is gated
        by a SEPARATE admin token ($CDMON_ADMIN_TOKEN / the ``admin_token`` param),
        never a per-repo token — a leaked repo token must not grant roster access.
        With no admin token configured the routes stay open (offline/dev, like a
        token-less repo). 401 missing / 403 wrong.
        """
        if admin_hash is None:
            return
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing admin bearer token")
        presented = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(hash_token(presented), admin_hash):
            raise HTTPException(status_code=403, detail="invalid admin token")

    @app.get("/")
    def root() -> object:
        """Serve the dashboard SPA when a build is mounted, else a JSON landing.

        With ``static_dir`` configured ``/`` returns the console's ``index.html``
        (single-origin deploy); otherwise it returns a friendly landing payload
        pointing a human at the docs — never the confusing ``{"detail":"Not
        Found"}`` FastAPI gives a bare ``/``.
        """
        if spa_index is not None:
            return FileResponse(str(spa_index))
        return {
            "service": "code-doc-monitor central server",
            "version": _app_version(),
            "docs": "/docs",
            "openapi": "/openapi.json",
            "endpoints": ["/health", "/repos", "/repos/{repo_id}/status"],
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        """Unauthenticated liveness probe (200 ``{"status": "ok"}``) for ops/k8s."""
        return {"status": "ok"}

    @app.get("/settings")
    def server_settings() -> dict[str, object]:
        """The effective operator runtime settings + secret PRESENCE (EPIC SVR).

        GLOBAL + public read (the console Settings page renders it). SECRETS are
        REDACTED: the model carries no secret values, and the env secrets
        ($CDMON_ADMIN_TOKEN / $CDMON_DATABASE_URL / $CDMON_SECRET_KEY) are reported
        only as presence booleans — never their values (K8). Deterministic (K10).
        """
        return {
            "settings": app_settings.model_dump(mode="json"),
            "secrets": secret_presence(),
        }

    @app.get("/config/templates")
    def config_templates() -> dict[str, str]:
        """The canonical ``config/cdmon/`` v2 templates as JSON (W-02, public).

        Returns ``{"unit", "index", "ignore", "doc_style"}`` — the four canonical
        template strings (CONFIG-V2 §1.1–§1.4) the dashboard Config page renders
        and adopters copy. No auth (public reference) and deterministic (K10): the
        same bytes every call.
        """
        return dict(V2_TEMPLATES)

    @app.get("/wiki")
    def wiki() -> dict:
        """The committed EPIC-R wikis rendered to HTML (R-09, GLOBAL + public).

        Returns ``{"sections": [{"id", "title", "html"}, ...]}`` — the four
        committed wikis (Feature Reference / Traceability / Test / Source) in the
        deterministic :data:`WIKI_SECTIONS` order, each body rendered by the
        engine's OWN dependency-free :func:`code_doc_monitor.build.render_markdown`
        (no new dep, K0). No auth (a public reference like ``/config/templates``,
        no ``_verify_token``). A missing section file is OMITTED; an absent
        ``feature-doc/`` (a non-cdmon repo) → ``{"sections": []}`` — a graceful
        empty payload, never a 500 (K8). Pure / deterministic (K10).
        """
        return {"sections": _load_wiki_sections(resolved_wiki_dir)}

    @app.post("/repos", status_code=201)
    def register_repo(
        payload: RegistrationPayload,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        # First-time register is open (a repo mints its token); re-registering an
        # EXISTING token-protected repo requires that token (so rotation is authorized).
        if store.get_repo(payload.repo.repo_id) is not None:
            _verify_token(store, payload.repo.repo_id, authorization)
        store.add_repo(payload)
        # GIT-02/04: a write-only git provider credential is SEALED at rest and
        # stored separately (the store never sees plaintext). A re-register that
        # omits it leaves the prior sealed secret; one that carries it rotates it.
        if payload.provider_secret is not None:
            from ..errors import SecretError
            from ..secrets import secret_box_from_env

            try:
                sealed = secret_box_from_env().seal(payload.provider_secret)
            except SecretError as exc:
                # The server has no/invalid KEK ($CDMON_SECRET_KEY) — a server
                # misconfiguration, not a client error (K8).
                raise HTTPException(
                    status_code=500,
                    detail=f"cannot seal the provider secret: {exc}",
                ) from exc
            store.set_provider_secret(payload.repo.repo_id, sealed)
        return {"repo_id": payload.repo.repo_id}

    @app.post("/ingest", status_code=202)
    def ingest(
        envelope: IngestEnvelope,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        repo_id = envelope.repo.repo_id
        _require_known_repo(store, repo_id)
        _verify_token(store, repo_id, authorization)
        store.add_record(repo_id, envelope.record)
        return {"record_id": envelope.record.record_id}

    @app.post("/repos/{repo_id:path}/resolutions", status_code=202)
    def resolve(
        repo_id: str,
        resolution: ResolutionRecord,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        # The FIRST dashboard write path (F-04). Token-protected like /ingest; the
        # resolution must reference a record of THIS repo (loud 404 otherwise, K8).
        _require_known_repo(store, repo_id)
        _verify_token(store, repo_id, authorization)
        known = {r.record_id for r in store.records_for(repo_id)}
        if resolution.record_id not in known:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"unknown record_id {resolution.record_id!r} for repo {repo_id!r}; "
                    "a resolution must reference one of the repo's records"
                ),
            )
        store.add_resolution(resolution)
        return {"record_id": resolution.record_id}

    @app.get("/repos")
    def list_repos(store: Store = Depends(get_store)) -> list[RegisteredRepo]:
        return store.list_repos()

    # --- EPIC OWN: the central roster + per-repo ownership view --------------

    @app.post("/admin/roster", status_code=201)
    def upsert_identity(
        identity: Identity,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        """Add or update a central roster identity (admin-token write, OWN-04)."""
        _verify_admin(authorization)
        store.upsert_identity(identity)
        return {"name": identity.name}

    @app.post("/admin/roster/{name:path}/departed", status_code=200)
    def mark_departed(
        name: str,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """Mark a roster identity departed (admin-token write, OWN-04).

        Cascades: every repo's ``GET /ownership`` recomputes orphans against the
        live roster on READ, so this one write flips every document the identity is
        accountable for, across every repo. 404 if the name is unknown (K8).
        """
        _verify_admin(authorization)
        if not any(i.name == name for i in store.list_roster()):
            raise HTTPException(
                status_code=404, detail=f"unknown roster identity {name!r}"
            )
        store.mark_identity_departed(name, at=clock())
        return {"name": name, "departed": True}

    @app.get("/roster")
    def list_roster(store: Store = Depends(get_store)) -> list[Identity]:
        # READS ARE OPEN (E-06): the dashboard shows the roster freely.
        return store.list_roster()

    @app.get("/repos/{repo_id:path}/ownership")
    def ownership_for(
        repo_id: str,
        store: Store = Depends(get_store),
        sync_kind: str | None = None,
    ) -> dict[str, object]:
        """Per-document ownership + orphan findings vs the LIVE roster (OWN-04).

        Reads the synced config documents (which carry the resolved accountable/
        durable owner) and crosses them against the live roster through
        :func:`code_doc_monitor.ownership.detect_orphans` — so marking someone
        departed flips every document they own across every repo on the NEXT read
        (the cross-repo cascade). Open read.
        """
        from ..config import Audience

        _require_known_repo(store, repo_id)
        # Ownership is a property of the CONFIG (identical across sync_kinds), so a
        # doc mirrored under both "git" and "local" must appear ONCE — dedup by
        # doc_id (first wins) when no sync_kind narrows it.
        owners: list[EffectiveOwner] = []
        seen: set[str] = set()
        for d in store.config_documents_for(repo_id, sync_kind):
            if d.doc_id in seen:
                continue
            seen.add(d.doc_id)
            owners.append(
                EffectiveOwner(
                    doc_id=d.doc_id,
                    doc_path=d.path,
                    audience=Audience(d.audience),
                    owner=d.owner,
                    team=d.team,
                    dri=d.dri,
                    accountable=d.accountable,
                    durable=d.durable,
                )
            )
        roster = RosterSnapshot(identities=tuple(store.list_roster()))
        findings = detect_orphans(owners, roster)
        orphan_count = sum(
            1
            for f in findings
            if f.status
            in (
                OwnershipStatus.ORPHAN_OWNER_DEPARTED,
                OwnershipStatus.ORPHAN_DRI_VACANT,
            )
        )
        return {
            "owners": [o.model_dump(mode="json") for o in owners],
            "findings": [f.model_dump(mode="json") for f in findings],
            "orphan_count": orphan_count,
        }

    @app.get("/repos/{repo_id:path}/staleness")
    def staleness_for(
        repo_id: str,
        store: Store = Depends(get_store),
        sync_kind: str | None = None,
        include_fresh: bool = False,
    ) -> dict[str, object]:
        """Per-document staleness vs the review SLA, graded at READ time (EPIC SLA).

        Reads the synced documents (which carry ``reviewed`` + the resolved, audience-
        aware ``sla_days``) and grades each against the app clock — so a doc goes stale
        on the NEXT read with no re-sync (mirrors the ``/ownership`` read-time model).
        Open read; deduped by ``doc_id`` (one config across sync_kinds); the table omits
        FRESH docs unless ``include_fresh``.
        """
        from ..config import Audience, StalenessConfig

        _require_known_repo(store, repo_id)
        now = clock()
        # A pre-SLA mirror row carries no sla_days — fall back to the canonical default
        # (so it grades exactly like a default-config CLI run; one source of truth).
        default_sla = StalenessConfig().default_days
        findings: list[StalenessFinding] = []
        seen: set[str] = set()
        for d in store.config_documents_for(repo_id, sync_kind):
            if d.doc_id in seen:
                continue
            seen.add(d.doc_id)
            sla = d.sla_days if d.sla_days is not None else default_sla
            status, age, detail = grade_doc(d.reviewed, now, sla)
            if status is StalenessStatus.FRESH and not include_fresh:
                continue
            findings.append(
                StalenessFinding(
                    doc_id=d.doc_id,
                    doc_path=d.path,
                    audience=Audience(d.audience),
                    status=status,
                    reviewed=d.reviewed,
                    sla_days=sla,
                    age_days=age,
                    detail=detail,
                )
            )
        findings.sort(key=lambda f: f.doc_id)
        stale_count = sum(
            1
            for f in findings
            if f.status in (StalenessStatus.STALE, StalenessStatus.NEVER_REVIEWED)
        )
        return {
            "findings": [f.model_dump(mode="json") for f in findings],
            "stale_count": stale_count,
            "now": now,
        }

    # `{repo_id:path}` so a repo_id containing slashes (e.g. "acme/widget", the
    # org/name form) is captured whole rather than splitting path segments.
    @app.get("/repos/{repo_id:path}/records")
    def records_for(
        repo_id: str,
        store: Store = Depends(get_store),
        verdict: str | None = None,
        drift_kind: str | None = None,
        audience: str | None = None,
        doc_id: str | None = None,
        limit: int | None = Query(default=None, gt=0),
        offset: int = Query(default=0, ge=0),
    ) -> list[ReviewRecord]:
        # READS ARE OPEN (E-06): no token required so the dashboard can display freely.
        _require_known_repo(store, repo_id)
        return store.records_for(
            repo_id,
            verdict=verdict,
            drift_kind=drift_kind,
            audience=audience,
            doc_id=doc_id,
            limit=limit,
            offset=offset,
        )

    @app.get("/repos/{repo_id:path}/resolutions")
    def resolutions_for(
        repo_id: str,
        store: Store = Depends(get_store),
        record_id: str | None = None,
    ) -> list[ResolutionRecord]:
        _require_known_repo(store, repo_id)
        return store.resolutions_for_repo(repo_id, record_id=record_id)

    @app.get("/repos/{repo_id:path}/coverage")
    def coverage_for(repo_id: str, store: Store = Depends(get_store)) -> list[dict]:
        _require_known_repo(store, repo_id)
        return store.coverage_for(repo_id)

    @app.post("/repos/{repo_id:path}/coverage", status_code=202)
    def post_coverage(
        repo_id: str,
        payload: CoverageIngest,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        # The config-driven coverage ingest (T-02). Token-protected like /resolutions;
        # the FULL snapshot dict is stored opaquely through the seam (K6).
        _require_known_repo(store, repo_id)
        _verify_token(store, repo_id, authorization)
        store.add_coverage_snapshot(
            repo_id, payload.captured_at, payload.model_dump(mode="json")
        )
        return {"repo_id": repo_id}

    @app.get("/repos/{repo_id:path}/status")
    def status_for(repo_id: str, store: Store = Depends(get_store)) -> RepoStatus:
        _require_known_repo(store, repo_id)
        return _compute_status(store, repo_id)

    @app.get("/repos/{repo_id:path}/health")
    def health_for(repo_id: str, store: Store = Depends(get_store)) -> RepoHealth:
        # READS ARE OPEN (E-06): a computed metrics VIEW (F-05), no token required.
        _require_known_repo(store, repo_id)
        return _compute_health(store, repo_id)

    @app.get("/repos/{repo_id:path}/telemetry")
    def telemetry_for(repo_id: str, store: Store = Depends(get_store)) -> RepoTelemetry:
        # READS ARE OPEN (E-06): a computed underperformer VIEW (H-01), no token.
        _require_known_repo(store, repo_id)
        return _compute_telemetry(store, repo_id)

    @app.post("/repos/{repo_id:path}/sync", status_code=201)
    def sync_repo(
        repo_id: str,
        body: SyncRequest,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> SyncRun:
        """Run a git/local config sync for the repo, persist it, return the run (Y-02).

        Token-protected like the other writes. 404 if the repo is unknown; 400 if
        the mode is invalid OR the repo has no ``local_path`` on file. On success
        it runs :func:`run_sync` (READ-ONLY against the repo, K1), REPLACES the
        ``(repo_id, mode)`` config rows, appends the :class:`SyncRun`, and returns
        the run summary. The server ``clock`` stamps every persisted row (K10).
        """
        _require_known_repo(store, repo_id)
        _verify_token(store, repo_id, authorization)
        repo = store.get_repo(repo_id)
        assert repo is not None  # _require_known_repo guarantees it
        local_path = repo.repo.local_path
        remote_url = repo.repo.remote_url
        provider = repo.repo.provider
        default_branch = repo.default_branch or repo.repo.default_branch or "main"
        # Lazy import: the engine pulls in the config/drift/coverage stack; keeping
        # it out of module load avoids a server↔configsync import cycle (configsync
        # imports the pure store models) and keeps `import app` cheap (K0).
        from ..configsync import run_sync
        from ..errors import SecretError, SyncError, TransportError

        now = clock()
        try:
            if local_path:
                # A repo on the server's disk: sync its working tree directly (Y-02).
                result = run_sync(
                    Path(local_path),
                    repo_id,
                    mode=body.mode,
                    default_branch=default_branch,
                    now=now,
                )
            elif remote_url and provider:
                # GIT-04 clone-on-demand: the server does NOT hold this repo locally.
                # Fetch it read-only into a throwaway tree (K1) and sync that. The
                # token is the opened PAT (PHASE 1) or a freshly minted short-lived
                # App/OAuth token (PHASE 2) — both resolved the same way.
                _check_remote_allowed(remote_url, git=srv.git)
                from ..gitfetch import RemoteSpec, cloned_repo

                token = _resolve_provider_token(
                    store, repo, now=now, token_exchange_http=token_exchange_http
                )
                spec = RemoteSpec(
                    remote_url=remote_url,
                    provider=provider,
                    default_branch=default_branch,
                )
                with cloned_repo(
                    spec,
                    token,
                    cloner=cloner,
                    clone_timeout=srv.git.clone_timeout_seconds,
                ) as tree:
                    result = run_sync(
                        tree,
                        repo_id,
                        mode=body.mode,
                        default_branch=default_branch,
                        now=now,
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"repo {repo_id!r} has no local_path and no "
                        "provider+remote_url on file; re-register it with one to "
                        "enable sync"
                    ),
                )
        except SecretError as exc:
            # The server can't open the sealed credential (KEK missing/wrong) — a
            # server misconfiguration, not a client error (K8).
            raise HTTPException(
                status_code=500, detail=f"cannot open the provider secret: {exc}"
            ) from exc
        except (SyncError, TransportError) as exc:
            # A bad mode / missing-tree / git/clone failure OR a failed PHASE-2 token
            # mint is a client-actionable 400 (token scrubbed by gitfetch) (K8).
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.replace_config(
            repo_id,
            body.mode,
            list(result.documents),
            list(result.code_refs),
        )
        store.add_sync_run(result.run)
        # Refresh the Coverage page from the just-synced tree: the sync already
        # walked the real coverage engine, so persist its snapshot here (same
        # ``captured_at`` clock) instead of waiting for the next POST /coverage
        # ingest. ``coverage`` is always set by run_sync; the None-guard keeps the
        # route robust if a future caller opts out (K6/K8).
        if result.coverage is not None:
            store.add_coverage_snapshot(repo_id, now, result.coverage)
        return result.run

    @app.post("/repos/{repo_id:path}/docs-pr", status_code=201)
    def docs_pr(
        repo_id: str,
        body: DocsPrRequest,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Clone the repo, heal its docs, and open a docs PR upstream (GIT-04).

        Token-protected like the other writes (404 unknown / 401 missing / 403
        wrong). Requires the repo to carry ``provider`` + ``remote_url`` (else 400).
        Clones read-only into a throwaway tree (K1), heals via the SAME monitor
        pipeline (:func:`syncpr.sync_pr` — region authority honored, offline mock
        backend), plans the PR from the healed docs, and opens it through the
        provider transport (:meth:`from_repo`). ``dry_run`` heals + plans but does
        NOT call the provider. Returns the heal summary, the changed doc paths,
        whether a PR was opened, and the provider/plan response. A clone/transport
        failure is a loud 400 (token scrubbed); a missing/wrong KEK is a 500.
        """
        _require_known_repo(store, repo_id)
        _verify_token(store, repo_id, authorization)
        repo = store.get_repo(repo_id)
        assert repo is not None
        provider = repo.repo.provider
        remote_url = repo.repo.remote_url
        if not (provider and remote_url):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"repo {repo_id!r} has no provider+remote_url on file; cannot "
                    "open a docs PR (re-register it with a github/gitlab remote_url)"
                ),
            )
        _check_remote_allowed(remote_url, git=srv.git)
        default_branch = repo.default_branch or repo.repo.default_branch or "main"
        from ..config import load_bundle
        from ..errors import SecretError, SyncError, TransportError
        from ..gitfetch import RemoteSpec, cloned_repo
        from ..monitor import Monitor
        from ..pr import open_docs_pr
        from ..syncpr import sync_pr

        stamp = clock()
        try:
            # PHASE 1 PAT or a freshly minted PHASE 2 short-lived token (same resolver).
            token = _resolve_provider_token(
                store, repo, now=stamp, token_exchange_http=token_exchange_http
            )
        except SecretError as exc:
            raise HTTPException(
                status_code=500, detail=f"cannot open the provider secret: {exc}"
            ) from exc
        except TransportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        spec = RemoteSpec(
            remote_url=remote_url, provider=provider, default_branch=default_branch
        )
        try:
            with cloned_repo(
                spec, token, cloner=cloner, clone_timeout=srv.git.clone_timeout_seconds
            ) as tree:
                bundle = load_bundle(tree.joinpath("config", "cdmon"))
                monitor = Monitor(
                    bundle.config, tree / "config" / "cdmon", now=lambda: stamp
                )
                sync = sync_pr(monitor, dry_run=False)  # heal the cloned docs
                transport = _make_transport(provider, remote_url, token)
                response = open_docs_pr(
                    sync,
                    monitor.root,
                    transport=transport,
                    target_branch=default_branch,
                    dry_run=body.dry_run,
                )
        except (SyncError, TransportError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "summary": sync.summary,
            "changed_paths": list(sync.changed_paths),
            "opened": response is not None,
            "response": response,
        }

    @app.get("/repos/{repo_id:path}/documents")
    def documents_for(
        repo_id: str,
        store: Store = Depends(get_store),
        sync_kind: str | None = None,
    ) -> list[DocumentTree]:
        """The document→code_refs relationship tree (W-01 view). READ, open.

        Joins :meth:`Store.config_documents_for` with
        :meth:`Store.code_refs_for`, nesting each document's code_refs under it in
        the store's stable insertion order (K10). Optional ``sync_kind`` scopes to
        the git or local view.
        """
        _require_known_repo(store, repo_id)
        documents = store.config_documents_for(repo_id, sync_kind)
        refs = store.code_refs_for(repo_id, sync_kind=sync_kind)
        by_doc: dict[str, list[ConfigCodeRef]] = {}
        for ref in refs:
            by_doc.setdefault(ref.doc_id, []).append(ref)
        return [
            DocumentTree(document=doc, code_refs=tuple(by_doc.get(doc.doc_id, [])))
            for doc in documents
        ]

    @app.get("/repos/{repo_id:path}/config/editable")
    def editable_config_tree(
        repo_id: str,
        store: Store = Depends(get_store),
        sync_kind: str | None = None,
    ) -> EditableConfigTree:
        """The editable config tree the editor page renders (EDITOR E-04). READ, open.

        Joins the stored ``documents`` (each with its ``code_refs`` and the
        ``context_refs`` already carried on :class:`ConfigDocument`, mirroring the
        ``GET /documents`` assembly) with the working-tree-derived
        ``undocumented_files`` / ``ignored_files`` / ``unit_files`` / ``doc_styles``
        computed by :func:`_disk_editable_parts` over the repo's ``local_path``.

        ``sync_kind`` defaults to ``"local"`` (the working-tree view convention) so
        the documents and the disk-derived gap describe the SAME tree. A
        central-only repo (no readable ``local_path``) still returns its stored
        documents with empty disk parts (K8 — no traceback on the OPEN route).
        Unknown repo → 404 like the other routes. Deterministic (K10).
        """
        _require_known_repo(store, repo_id)
        resolved_kind = sync_kind or "local"
        documents = store.config_documents_for(repo_id, resolved_kind)
        refs = store.code_refs_for(repo_id, sync_kind=resolved_kind)
        by_doc: dict[str, list[ConfigCodeRef]] = {}
        for ref in refs:
            by_doc.setdefault(ref.doc_id, []).append(ref)
        editable_docs = tuple(
            EditableDocument(document=doc, code_refs=tuple(by_doc.get(doc.doc_id, [])))
            for doc in documents
        )
        repo = store.get_repo(repo_id)
        assert repo is not None  # _require_known_repo guarantees it
        undocumented, ignored, unit_files, doc_styles = _disk_editable_parts(
            repo.repo.local_path
        )
        return EditableConfigTree(
            repo_id=repo_id,
            sync_kind=resolved_kind,
            documents=editable_docs,
            undocumented_files=undocumented,
            ignored_files=ignored,
            unit_files=unit_files,
            doc_styles=doc_styles,
        )

    @app.post("/repos/{repo_id:path}/config/edits", status_code=201)
    def stage_config_edit(
        repo_id: str,
        edit: ConfigEdit,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        """Stage one mapping "ticket" as a ``pending`` config edit (EDITOR E-05). WRITE.

        Token-protected like the other writes (``/sync`` / ``/resolutions``): 401 if
        the header is missing on a token-protected repo, 403 if it is wrong, open for
        an OPEN/standalone repo with no stored token hash. The body validates against
        the :data:`ConfigEdit` discriminated union, so an unknown ``action`` or a stray
        field is a loud 422 (K8), never a 500. The ``edit_id`` is derived
        deterministically from the edit + the injected ``clock`` (K10) and the row is
        stamped ``created_at = clock()``. Unknown repo → 404.
        """
        _require_known_repo(store, repo_id)
        _verify_token(store, repo_id, authorization)
        now = clock()
        edit_id = _new_edit_id(repo_id, edit, now)
        store.add_config_edit(repo_id, edit, edit_id=edit_id, created_at=now)
        return {"edit_id": edit_id}

    @app.get("/repos/{repo_id:path}/config/edits")
    def list_config_edits(
        repo_id: str,
        store: Store = Depends(get_store),
        status: str | None = None,
    ) -> list[StoredConfigEdit]:
        """List this repo's staged config edits, newest-last (EDITOR E-05). READ, open.

        Returns the persisted :class:`StoredConfigEdit` envelopes in insertion order
        (K10), optionally filtered by ``status`` (``pending``/``applied``/
        ``discarded``). Unknown repo → 404 like the other routes.
        """
        _require_known_repo(store, repo_id)
        return store.config_edits_for(repo_id, status)

    @app.post("/repos/{repo_id:path}/config/generate", status_code=201)
    def generate_config(
        repo_id: str,
        body: GenerateRequest,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> GenerateResponse:
        """Make staged edits LIVE: write disk, scaffold/heal docs, re-sync (E-06).

        Token-protected like ``/sync`` (401 missing / 403 wrong / open for an
        OPEN repo). 404 if the repo is unknown; **409** (NOT 500) if it has no
        ``local_path`` (a central-only repo cannot be generated server-side).

        Selects this repo's ``pending`` edits (filtered to ``edit_ids`` when given);
        with none selected it is a 200-style no-op (``applied=[]``, idempotent
        friendliness). Otherwise it applies them to disk via
        :func:`~code_doc_monitor.generate.apply_edits_to_disk` (the offline,
        deterministic, NO-LLM engine), re-runs ``run_sync`` and REPROJECTS the DB
        exactly like ``POST /sync`` (replace_config + add_sync_run), marks the edits
        ``applied``, and returns the applied ids + the fresh :class:`SyncRun` + the
        recomputed ``undocumented_files`` (the editable-tree coverage gap). The
        server ``clock`` stamps every persisted row (K10).
        """
        _require_known_repo(store, repo_id)
        _verify_token(store, repo_id, authorization)
        repo = store.get_repo(repo_id)
        assert repo is not None  # _require_known_repo guarantees it
        local_path = repo.repo.local_path
        if not local_path:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"repo {repo_id!r} has no local_path; cannot generate "
                    "server-side (a central-only repo has no working tree to write)"
                ),
            )

        pending = store.config_edits_for(repo_id, status="pending")
        if body.edit_ids is not None:
            wanted = set(body.edit_ids)
            selected = [e for e in pending if e.edit_id in wanted]
        else:
            selected = list(pending)

        if not selected:
            # No-op (idempotent friendliness): nothing pending to make live. The
            # caller still gets the current undocumented gap + latest sync run.
            undocumented, _ignored, _units, _styles = _disk_editable_parts(local_path)
            return GenerateResponse(
                applied=(),
                sync_run=store.latest_sync_run(repo_id, body.mode),
                undocumented_files=undocumented,
            )

        from ..errors import CodeDocMonitorError
        from ..generate import apply_edits_to_disk

        try:
            apply_edits_to_disk(
                Path(local_path),
                [e.edit for e in selected],
                now=clock(),
            )
        except CodeDocMonitorError as exc:
            # A scoped-write failure (missing config, bad audience/lines, unknown
            # unit) is a client-actionable 400 with the loud engine message (K8).
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        default_branch = repo.default_branch or repo.repo.default_branch or "main"
        from ..configsync import run_sync
        from ..errors import SyncError

        try:
            result = run_sync(
                Path(local_path),
                repo_id,
                mode=body.mode,
                default_branch=default_branch,
                now=clock(),
            )
        except SyncError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.replace_config(
            repo_id,
            body.mode,
            list(result.documents),
            list(result.code_refs),
        )
        store.add_sync_run(result.run)

        applied_ids = [e.edit_id for e in selected]
        store.mark_config_edits(repo_id, applied_ids, "applied", at=clock())

        undocumented, _ignored, _units, _styles = _disk_editable_parts(local_path)
        return GenerateResponse(
            applied=tuple(applied_ids),
            sync_run=result.run,
            undocumented_files=undocumented,
        )

    @app.post("/repos/{repo_id:path}/records/{record_id}/apply-fix", status_code=201)
    def apply_record_fix_route(
        repo_id: str,
        record_id: str,
        store: Store = Depends(get_store),
        authorization: str | None = Header(default=None),
    ) -> ApplyFixResponse:
        """Apply ONE record's LLM-proposed fix to its doc on disk, then re-sync (E-07).

        The one-click "apply the LLM's proposed fix" path. Token-protected like
        ``/sync`` / ``/config/generate`` (401 missing / 403 wrong / open for an
        OPEN repo). 404 if the repo is unknown; **409** (NOT 500) if it has no
        ``local_path`` (a central-only repo has no working tree to write); 404 if
        no such ``record_id`` for the repo; 409 if that record carries no
        applicable fix (not a FIX verdict, or ``fix is None``).

        On success it applies the fix via
        :func:`~code_doc_monitor.generate.apply_record_fix` (offline, deterministic,
        SCOPED to the record's doc file), appends an ``accepted``
        :class:`ResolutionRecord` linked by ``record_id`` (mirroring ``POST
        /resolutions`` / ``cdmon resolve``), re-runs ``run_sync`` and REPROJECTS the
        DB exactly like ``POST /sync`` (replace_config + add_sync_run), and returns
        the apply outcome (``applied`` / ``doc_path`` / ``diff``) plus the fresh
        :class:`SyncRun`. The server ``clock`` stamps every persisted row (K10).
        """
        _require_known_repo(store, repo_id)
        _verify_token(store, repo_id, authorization)
        repo = store.get_repo(repo_id)
        assert repo is not None  # _require_known_repo guarantees it
        local_path = repo.repo.local_path
        if not local_path:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"repo {repo_id!r} has no local_path; cannot apply a fix "
                    "server-side (a central-only repo has no working tree to write)"
                ),
            )

        record = next(
            (r for r in store.records_for(repo_id) if r.record_id == record_id),
            None,
        )
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"unknown record_id {record_id!r} for repo {repo_id!r}; "
                    "apply-fix must reference one of the repo's records"
                ),
            )
        if record.fix is None or record.verdict is not Verdict.FIX:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"record {record_id!r} has no applicable fix "
                    f"(verdict={record.verdict.value}); only a FIX-verdict record "
                    "carrying a proposed fix can be applied"
                ),
            )

        from ..errors import CodeDocMonitorError
        from ..generate import apply_record_fix

        try:
            outcome = apply_record_fix(Path(local_path), record, now=clock())
        except CodeDocMonitorError as exc:
            # A scoped-write failure (missing config/doc) is a client-actionable
            # 400 with the loud engine message (K8) — never a 500.
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Record the human OUTCOME: the proposed fix was accepted as-is (mirrors
        # `cdmon resolve` / POST /resolutions — the SHARED ResolutionRecord, not a
        # DTO). Linked by record_id; resolved_at from the injected clock (K10).
        store.add_resolution(
            ResolutionRecord(
                record_id=record_id,
                resolution=Resolution.ACCEPTED,
                resolved_at=clock(),
            )
        )

        # Reproject the DB exactly like POST /sync so the dashboard reads the now
        # -live state (the applied fix cleared the drift).
        default_branch = repo.default_branch or repo.repo.default_branch or "main"
        from ..configsync import run_sync
        from ..errors import SyncError

        try:
            result = run_sync(
                Path(local_path),
                repo_id,
                mode="local",
                default_branch=default_branch,
                now=clock(),
            )
        except SyncError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.replace_config(
            repo_id,
            "local",
            list(result.documents),
            list(result.code_refs),
        )
        store.add_sync_run(result.run)

        return ApplyFixResponse(
            applied=outcome.applied,
            doc_path=outcome.doc_path,
            diff=outcome.diff,
            sync_run=result.run,
        )

    @app.get("/repos/{repo_id:path}/sync-state")
    def sync_state_for(
        repo_id: str,
        store: Store = Depends(get_store),
        sync_kind: str | None = None,
    ) -> SyncRun | None:
        """The latest :class:`SyncRun` for the repo (or ``null``). READ, open."""
        _require_known_repo(store, repo_id)
        return store.latest_sync_run(repo_id, sync_kind)

    # Single-origin static site (EPIC ASTRO): serve the built frontend at "/"
    # AFTER every API route above, so the API always wins and any unclaimed path
    # — index.html, the native `/wiki/*` pages, `/_astro/*` assets — falls through
    # to the site. `html=True` serves index.html for "/" and directory paths. The
    # mount is LAST so it can never shadow a route (K8/K10).
    if spa_index is not None:
        app.mount(
            "/",
            StaticFiles(directory=str(spa_index.parent), html=True),
            name="site",
        )

    return app


def _default_static_dir(root: Path | None = None) -> Path | None:
    """The built ``frontend/dist`` Astro app shipped beside the package, if present.

    Returns ``None`` when the frontend has not been built (the server still runs,
    serving the JSON landing at ``/``). ``root`` defaults to the repo root (two
    levels above this package); tests pass a tmp root. (EPIC ASTRO replaced the
    legacy ``dashboard/dist`` SPA with this single Astro build.)
    """
    base = root if root is not None else Path(__file__).resolve().parents[2]
    dist = base / "frontend" / "dist"
    return dist if (dist / "index.html").is_file() else None


def _run_migrations(url: str) -> None:
    """Bring the schema to head via Alembic — the PROD path (``create_all`` is dev).

    Locates the repo's ``alembic.ini`` + ``alembic/`` (two levels above this package,
    beside the dashboard the SPA loader finds) and runs ``upgrade head``. Idempotent
    (K7): re-running against an up-to-date DB is a no-op. SQLite (the offline stand-in)
    and Postgres run the SAME migration scripts (batch mode), so dev/test and prod stay
    in lock-step. Imports Alembic lazily so ``import app`` (the TestClient path) needs
    only fastapi, not the migration tooling.
    """
    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def store_from_env() -> Store:
    """Select the central server's :class:`Store` from the environment (the prod seam).

    With ``$CDMON_DATABASE_URL`` set (a PERSISTENT url — ``postgresql+psycopg://...``
    in prod, or a ``sqlite:///<file>`` stand-in offline), the schema is migrated to
    head and a persistent :class:`~code_doc_monitor.server.db.SqlStore` is returned —
    so records/resolutions/coverage SURVIVE a restart.

    Without it, a transient :class:`InMemoryStore` is returned AND a loud warning is
    logged (K8): the server still runs, but every ingested record is lost on restart,
    so an operator is never silently surprised by vanished data. The DB modules are
    imported lazily so this stays inside the ``[server]`` extra boundary (K0).
    """
    url = os.environ.get("CDMON_DATABASE_URL") or None
    if url is None:
        _LOG.warning(
            "CDMON_DATABASE_URL is not set — using an IN-MEMORY store; all ingested "
            "records, resolutions and coverage are LOST on restart. Set "
            "CDMON_DATABASE_URL (e.g. postgresql+psycopg://user:pw@host/db) to persist."
        )
        return InMemoryStore()

    from .db import SqlStore, engine_from_url

    _run_migrations(url)
    _LOG.info("central store: persistent SqlStore at %s", url)
    return SqlStore(engine_from_url(url))


def main() -> None:  # pragma: no cover - the real uvicorn launch leaf (K4)
    import uvicorn

    # EPIC SVR: bind host/port/log level come from the resolved settings
    # (config/settings.yaml + env), not hardcoded; defaults are 0.0.0.0:33333/info.
    app_settings = resolve_settings()
    uvicorn.run(
        create_app(
            store_from_env(),
            static_dir=_default_static_dir(),
            settings=app_settings,
        ),
        host=app_settings.server.host,
        port=app_settings.server.port,
        log_level=app_settings.server.log_level,
    )


if __name__ == "__main__":  # pragma: no cover - server launch entrypoint
    main()
