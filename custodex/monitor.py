"""The orchestration loop: detect -> backend -> record -> (apply) -> recheck.

:class:`Monitor` wires the pure detector (:func:`drift.detect`, K1) to the
pluggable backend (K4), the append-only review log + central sink (K5), and the
idempotent healer (K7). Every collaborator is INJECTED — the backend, the sink,
and the ``now`` clock — so the whole pipeline runs offline and deterministically
(K4/K10): the default backend is the mock, the default sink comes from config,
and ``now`` defaults to the wall clock but is overridden in tests with a fixed
ISO string.

``run`` never mutates anything unless ``apply`` is true *and* the backend
returns a ``FIX`` (K5: auto-apply is opt-in). Whatever the verdict, a
:class:`~custodex.schema.ReviewRecord` is always written and emitted, so
``INVALIDATE``/``ESCALATE`` are recorded for a human, never silently dropped.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from . import reviewlog
from .backends import Backend, BackendResult, FixRequest, make_backend
from .blocks import expected_region
from .config import DocumentSpec, MonitorConfig, RegionMode, resolve_repo_root
from .docdeps import SuspectStatus, detect_suspect_links, stamp_edges
from .docstyle import DocStyleMap
from .drift import Drift, DriftKind, DriftReport, detect, mechanical_docs
from .extract import DocumentSurface, build_document_surface
from .heal import apply_fix, render_corrected
from .index import render_index
from .promotion import PromotionRule, rule_for
from .schema import ProposedFix, ResolutionRecord, ReviewRecord, Verdict, new_record_id
from .similar import Exemplar, rank_similar
from .sinks import Sink, make_sink
from .ticket import build_ticket

__all__ = [
    "HandledDrift",
    "ClosureRecord",
    "MonitorResult",
    "Monitor",
    "DEFAULT_LOG_PATH",
]

#: Default review-log location, relative to the config directory.
DEFAULT_LOG_PATH = Path(".cdmon") / "review-log.jsonl"

#: Default number of few-shot exemplars to retrieve per drift when retrieval is on.
DEFAULT_EXEMPLAR_TOP_N = 3

#: Prefix on the synthesized ``cause`` of a rule-resolved drift (D-06). It marks the
#: record as RULE-sourced (no backend was consulted) for a human auditor; the
#: machine-readable marker also lands in ``config_snapshot["resolved_by"] = "rule"``.
RULE_CAUSE_PREFIX = "promoted rule"

#: Prefix on the synthesized ``cause`` of an ENGINE-closed drift (RTE-03d). Marks
#: the record as engine-sourced — no backend, no model — for a human auditor; the
#: machine-readable marker lands in ``config_snapshot["resolved_by"] = "engine"``.
ENGINE_CAUSE_PREFIX = "code-derived"

# Frozen + extra="forbid": results are immutable snapshots of one run.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class HandledDrift(BaseModel):
    """One drift that was sent to the backend, with its verdict and outcome."""

    model_config = _MODEL_CONFIG

    drift: Drift
    result: BackendResult
    applied: bool


class ClosureRecord(BaseModel):
    """One DOCUMENT the engine closed (or previewed closing) unattended (RTE-03d).

    The alarm for tiered mode. An unattended write that does not actually close
    the drift is the failure that must never be silent: the document looks handled,
    the next run re-applies forever, and nobody is told.

    Deliberately an in-process ``MonitorResult`` detail, **not** a public schema
    artifact — ``cdx schema`` emits :class:`~custodex.schema.ReviewRecord` alone, so
    nothing here implies a ``schema_version`` bump (K6). The durable audit trail is
    the ``ReviewRecord`` this closure names in ``record_id``.

    ``record_ids`` is a TUPLE, and the reason is the CLOCK.
    :func:`~custodex.schema.new_record_id` hashes ``(doc_id, surface_hash,
    detected_at)`` — no drift kind, no region — so under a FIXED injected clock N
    drifts closed on one document in one run collapse to ONE id, and a singular
    field looks right. Under the production clock (:func:`_default_now`, microsecond
    precision) each ``_record_for`` call stamps a different instant, so the ids are
    DISTINCT and a singular field would silently name only the first — losing the
    audit trail for every other drift on the document. Sorted + deduped, so both
    worlds are correct. Widening ``new_record_id`` itself is NOT the fix: it would
    change every existing record id and break the doc-grain ``cdx resolve`` contract.
    """

    model_config = _MODEL_CONFIG

    doc_id: str
    doc_path: str
    #: The review record(s) this closure is joinable to — sorted + deduped.
    record_ids: tuple[str, ...]
    #: Sorted + deduped drift kinds closed on this document (K10).
    drift_kinds: tuple[str, ...]
    #: Sorted union of the routing evidence across those drifts (K10).
    evidence: tuple[str, ...]
    #: The write path was ENTERED (``apply`` was effectively on). The alarm gates on
    #: this, never on ``wrote``, so that "routing promised mechanical closure and
    #: nothing was written" is still reported.
    #:
    #: ⟨R-CORRECTED⟩ An earlier draft justified this with ``apply_fix`` declining a
    #: preserved id or a B-03 locked region. Those are unreachable HERE, and the
    #: fold is why: a ``human`` or locked ``llm-seeded`` region drift is built
    #: ``healable=False`` and classifies ``NEEDS_INTENT``, so its document is never
    #: mechanical in the first place. The branch IS reachable, by the case that
    #: actually matters — :meth:`Monitor._engine_result` returning ``ESCALATE``
    #: because the ENGINE could not render what routing called mechanical (the
    #: router and the renderer disagreeing). Gating on ``wrote`` would hide it.
    attempted: bool
    #: ``apply_fix`` actually changed bytes.
    wrote: bool
    #: The post-run recheck shows no remaining ACTIONABLE drift on this document.
    verified: bool


class MonitorResult(BaseModel):
    """The outcome of one :meth:`Monitor.run`: handled, remaining, recorded."""

    model_config = _MODEL_CONFIG

    handled: tuple[HandledDrift, ...]
    remaining: tuple[Drift, ...]
    records: tuple[ReviewRecord, ...]
    #: RTE-03d: what tiered mode closed unattended, sorted by ``doc_id`` (K10).
    #: Appended LAST and defaulted, so every pre-RTE-03d construction still
    #: validates (additive, K6). Empty unless ``tiered`` was effectively on.
    closures: tuple[ClosureRecord, ...] = ()


def _default_now() -> str:
    """Return the current UTC time as an ISO-8601 string (injected in tests, K10)."""
    return datetime.now(timezone.utc).isoformat()


class Monitor:
    """Drift orchestration over one config (collaborators injected for K4/K10)."""

    def __init__(
        self,
        config: MonitorConfig,
        config_dir: Path,
        *,
        backend: Backend | None = None,
        sink: Sink | None = None,
        now: Callable[[], str] | None = None,
        log_path: Path | None = None,
        source_sha: str | None = None,
        use_exemplars: bool = False,
        resolutions_path: Path | None = None,
        exemplar_top_n: int = DEFAULT_EXEMPLAR_TOP_N,
        rules: tuple[PromotionRule, ...] = (),
        doc_style: DocStyleMap | None = None,
    ) -> None:
        self.config = config
        self.config_dir = config_dir
        # N-06: the ONE repo-root formula (resolve_repo_root = normpath(config_dir
        # / root)) shared with drift.detect, effective_coverage, doc-style, and
        # rpt. Single-file (config_dir=repo, root=".") still resolves to the repo;
        # the dir layout (config_dir=<repo>/config/cdmon, root="../..") now also
        # resolves to the repo instead of the WRONG <repo>/config.
        self.root = resolve_repo_root(config_dir, config.root)
        # N-05 opt-in writing-style guidance. DEFAULT None ⇒ run() builds a
        # FixRequest whose style_guidance is None, so the composed agent prompt
        # is byte-identical to today (additive, K6). A ``DocStyleMap`` (loaded by
        # load_bundle from doc-style.yaml) supplies the four selected
        # `templates/writing/` bodies for a no-renderer `llm` (authored-prose)
        # region. Concretely typed now the docstyle import is one-way (Z-03).
        self._doc_style = doc_style
        self._backend: Backend = backend or make_backend(config.backend, config.agent)
        self._sink: Sink = sink or make_sink(config.central)
        self._now: Callable[[], str] = now or _default_now
        self._log_path = log_path or (config_dir / DEFAULT_LOG_PATH)
        # C-05 provenance: stamped onto every ReviewRecord (default None keeps
        # today's records valid — K6 additive).
        self._source_sha = source_sha
        # D-04 opt-in few-shot retrieval. DEFAULT OFF ⇒ run() is byte-identical to
        # pre-D-04 (no log/resolutions read, FixRequest.exemplars stays ()).
        self._use_exemplars = use_exemplars
        self._resolutions_path = resolutions_path or (
            config_dir / reviewlog.DEFAULT_RESOLUTIONS_PATH
        )
        self._exemplar_top_n = exemplar_top_n
        # D-06 opt-in promoted rules. DEFAULT () ⇒ run() is byte-identical to today
        # (every drift goes to the backend). A drift matching a rule is resolved by
        # the rule with ZERO backend calls — the learned cost-curve win (K4).
        self._rules = rules

    def check(self) -> DriftReport:
        """Detect drift without mutating anything (pure delegate to drift, K1)."""
        return detect(self.config, self.config_dir)

    def _spec_for(self, doc_id: str) -> DocumentSpec:
        for spec in self.config.documents:
            if spec.id == doc_id:
                return spec
        # detect() only emits drifts for configured docs, so this is unreachable.
        raise KeyError(doc_id)  # pragma: no cover

    def _doc_text(self, drift: Drift, doc_path: Path) -> str:
        """Read the doc body, or ``""`` when it is missing (MISSING_DOC)."""
        if drift.kind is DriftKind.MISSING_DOC or not doc_path.is_file():
            return ""
        return doc_path.read_text(encoding="utf-8")

    def _style_guidance_for(self, drift: Drift, region_mode: RegionMode) -> str | None:
        """The composed writing guidance for an authored-prose region, else None.

        Returns the four selected ``templates/writing/`` bodies (via
        :func:`docstyle.read_style_guidance`) ONLY when a ``DocStyleMap`` is
        configured AND the drift is a no-renderer ``llm`` REGION — the same
        authoring case the backend writes prose for (a REGION-mode-``llm`` drift
        whose region has no mechanical renderer template). In every other case
        (no style map, a ``generated`` region, a renderer-backed region, or a
        whole-doc drift) it returns None, so the FixRequest — and the composed
        agent prompt — is byte-identical to today (additive, K6).
        """
        if self._doc_style is None:
            return None
        if drift.kind is not DriftKind.REGION or region_mode is not RegionMode.LLM:
            return None
        if drift.region_id is None:
            return None
        # A renderer-backed `llm` region is mechanically rendered, not authored —
        # no writing guidance applies there (only a no-renderer region authors).
        if drift.region_id in self.config.region_templates:
            return None

        from .docstyle import read_style_guidance

        selection = self._doc_style.style_for(drift.doc_id)
        # Resolve templates_root via the SAME repo-root convention load_bundle
        # validated against (resolve_repo_root = normpath(config_dir / root)), so
        # validate-time (load_doc_style) and read-time (here) agree on where the
        # four `templates/writing/` files live (N-06: one shared formula).
        repo_root = resolve_repo_root(self.config_dir, self.config.root)
        templates_root = repo_root / "templates" / "writing"
        return read_style_guidance(selection, templates_root)

    def _preserve_for(self, spec: DocumentSpec) -> frozenset[str]:
        """Human-owned region ids the engine must never author (B-02).

        The guarantee is enforced at the heal WRITE boundary, not in the backend,
        so even a whole-doc fix cannot clobber them. Shared by the backend path and
        the RTE-03d engine path — one enforcement point, so a future B-02/B-03/
        RTE-04 guard is added once.
        """
        return frozenset(
            rid for rid in spec.region_keys if spec.mode_for(rid) is RegionMode.HUMAN
        )

    def _modes_for(self, spec: DocumentSpec) -> dict[str, RegionMode]:
        """Per-region authority, carrying the B-03 lock + per-region hash stamping."""
        return {rid: spec.mode_for(rid) for rid in spec.region_keys}

    def _region_body(
        self, region_id: str, spec: DocumentSpec, surface: DocumentSurface
    ) -> str | None:
        """The body a managed region should hold — the SAME selector ``detect`` uses.

        An ``index`` region is a table over the config's OTHER documents, so it is
        not a function of this surface and :func:`~custodex.blocks.expected_region`
        declines it (RTE-03a). Mirroring ``drift.detect``'s branch here is what
        keeps the engine's own close byte-identical to what detect grades against —
        the two renderers must never diverge again.
        """
        template = self.config.region_templates.get(region_id)
        if template is not None and template.source == "index":
            return render_index(template, spec, self.config, self.root)
        return expected_region(region_id, surface, template)

    def _engine_result(
        self,
        drift: Drift,
        spec: DocumentSpec,
        surface: DocumentSurface,
        doc_text: str,
    ) -> BackendResult:
        """Close a CODE_DERIVED drift with the ENGINE — no backend, no model (RTE-03d).

        The fix SHAPES mirror :class:`~custodex.backends.MockBackend` rules 1 and 3
        exactly: region-scoped for a ``REGION``, whole-doc for a ``HASH``. Keeping
        them apart matters — one whole-doc fix per document would make a REGION
        close rewrite front-matter it never touches today (``fingerprint_tiers``,
        ``symbol_sigs``), which on a legacy composite-only doc silently ADDS the
        digests ``classify_change_severity`` needs to move a FUTURE HASH drift from
        ``UNKNOWN`` (NEEDS_INTENT) to ``COSMETIC`` (CODE_DERIVED). The unattended
        write would widen what it may next write unattended.

        A ``None`` body is NOT silently skipped: routing called this mechanical, so
        the engine failing to render it is a contradiction a human must see (K8) —
        it becomes an ESCALATE whose closure trips the alarm.
        """
        if drift.kind is DriftKind.REGION and drift.region_id is not None:
            body = self._region_body(drift.region_id, spec, surface)
            if body is not None:
                return BackendResult(
                    verdict=Verdict.FIX,
                    cause=(
                        f"{ENGINE_CAUSE_PREFIX}: managed region "
                        f"{drift.region_id!r} is a projection of the current code "
                        "surface — regenerated by the engine (no backend consulted)"
                    ),
                    fix=ProposedFix(
                        region_id=drift.region_id,
                        new_region_body=body,
                        new_doc_text=None,
                        rationale=(
                            "regenerated the managed region from the code surface "
                            "(the single source of truth); no model was involved, "
                            "so there is nothing to be confident about"
                        ),
                    ),
                )
        elif drift.kind is DriftKind.HASH:
            return BackendResult(
                verdict=Verdict.FIX,
                cause=(
                    f"{ENGINE_CAUSE_PREFIX}: the code surface changed and the "
                    "severity proves no documented sentence was falsified — "
                    "regenerating regions and fingerprint (no backend consulted)"
                ),
                fix=ProposedFix(
                    region_id=None,
                    new_region_body=None,
                    new_doc_text=render_corrected(
                        doc_text,
                        surface,
                        self.config.region_templates,
                        include_body=self.config.fingerprint_body_tier,
                    ),
                    rationale=(
                        "rewrote the document from the current code surface; "
                        "regions + fingerprint refreshed by the engine itself"
                    ),
                ),
            )
        return BackendResult(
            verdict=Verdict.ESCALATE,
            cause=(
                f"{ENGINE_CAUSE_PREFIX}: routing classified this drift "
                f"{drift.apply_tier.value!r} but the engine could not render it — "
                "the router and the renderer disagree; a human must look"
            ),
            fix=None,
        )

    def _record_for(
        self,
        drift: Drift,
        result: BackendResult,
        surface: DocumentSurface,
        *,
        rule_sourced: bool = False,
        engine_sourced: bool = False,
    ) -> ReviewRecord:
        stamp = self._now()
        surface_hash = surface.surface_hash(
            include_body=self.config.fingerprint_body_tier
        )
        fix: ProposedFix | None = result.fix
        # D-06: a rule-resolved record is marked RULE-sourced (no backend was
        # consulted) so a human auditor (and the central server) can tell it from a
        # backend verdict — additive to config_snapshot, no schema change (K6).
        config_snapshot: dict = {
            "backend": self.config.backend.kind,
            "root": self.config.root,
        }
        if rule_sourced:
            config_snapshot["resolved_by"] = "rule"
        # RTE-03d: an ENGINE close consulted no backend either — same audit marker
        # shape as D-06's "rule" so a human (and the central server) can tell an
        # unattended mechanical close from a model verdict.
        if engine_sourced:
            config_snapshot["resolved_by"] = "engine"
        # P-01: a record self-describes which fingerprint derivation produced its
        # surface_hash, so the body tier is auditable. Only recorded when ON ⇒
        # every pre-P-01 / flag-OFF snapshot is byte-identical (additive, K6).
        if self.config.fingerprint_body_tier:
            config_snapshot["fingerprint_body_tier"] = True
        record_id = new_record_id(drift.doc_id, surface_hash, stamp)
        # T-01: the human-validatable ticket is built FROM this record's
        # drift/verdict/cause/fix and the code surface — pure/deterministic
        # (K1/K10). Its id mirrors the record id so the two are joinable.
        ticket = build_ticket(
            drift=drift,
            verdict=result.verdict,
            cause=result.cause,
            fix=fix,
            surface=surface,
            ticket_id=f"CDM-{record_id}",
        )
        return ReviewRecord(
            record_id=record_id,
            doc_id=drift.doc_id,
            doc_path=drift.doc_path,
            audience=drift.audience,
            drift_kind=drift.kind.value,
            drift_detail=drift.detail,
            cause=result.cause,
            verdict=result.verdict,
            fix=fix,
            surface_hash=surface_hash,
            backend_kind=self.config.backend.kind,
            detected_at=stamp,
            resolved_at=stamp,
            config_snapshot=config_snapshot,
            source_sha=self._source_sha,
            ticket=ticket,
            drifted_tiers=drift.drifted_tiers,  # P2: which tier(s) moved (HASH)
            # P5: breaking/additive/cosmetic severity of the HASH change.
            change_severity=drift.change_severity.value,
        )

    def _target_record(self, drift: Drift, surface_hash: str) -> ReviewRecord:
        """A minimal ReviewRecord carrying only the FEATURES retrieval ranks on.

        :func:`~custodex.similar.rank_similar` scores on ``doc_id`` /
        ``drift_kind`` / ``audience`` / ``surface_hash`` only, so the verdict/cause
        here are placeholders — never persisted, never read by ranking. ``record_id``
        is a deterministic non-colliding sentinel so the target is excluded from its
        own results even if an identical id were ever resolved.
        """
        return ReviewRecord(
            record_id="__target__",
            doc_id=drift.doc_id,
            doc_path=drift.doc_path,
            audience=drift.audience,
            drift_kind=drift.kind.value,
            drift_detail=drift.detail,
            cause="",
            verdict=Verdict.ESCALATE,
            fix=None,
            surface_hash=surface_hash,
            backend_kind=self.config.backend.kind,
            detected_at="",
            resolved_at="",
            config_snapshot={},
        )

    def _retrieve_exemplars(
        self,
        drift: Drift,
        surface_hash: str,
        records: list[ReviewRecord],
        resolutions: list[ResolutionRecord],
    ) -> tuple[Exemplar, ...]:
        """Rank the most-similar past RESOLVED records for one drift (D-04)."""
        target = self._target_record(drift, surface_hash)
        return tuple(
            rank_similar(target, records, resolutions, top_n=self._exemplar_top_n)
        )

    def run(
        self, *, apply: bool | None = None, tiered: bool | None = None
    ) -> MonitorResult:
        """Detect -> per-drift backend verdict -> record + emit -> (apply) -> recheck.

        ``apply`` overrides ``config.apply_default`` (``None`` -> use the config).
        A FIX is applied only when ``apply`` is effectively true (K5). Every
        verdict is recorded and emitted regardless. ``remaining`` is the result
        of a fresh detect after any applies (so FIX'd drift drops out and
        ESCALATE/unapplied drift persists).

        ``tiered`` (RTE-03c) overrides ``config.apply_tiered`` the same way, and is
        a **RESTRAINT on apply, not merely a subset of it**: when it is effectively
        true, only a document the ENGINE alone could close — every actionable drift
        on it ``CODE_DERIVED``, per :func:`~custodex.drift.mechanical_docs` — may be
        written. A document carrying any ``NEEDS_INTENT`` (or, for now,
        ``DELEGATED``) drift is still sent to the backend, so the human receives a
        ``ReviewRecord`` with a proposed fix (K5), but nothing on it is applied.

        On the mechanical path no backend is consulted at all, so ``--tiered`` can
        write a document a declining backend would have left alone — it REPLACES
        the authority there rather than narrowing it. On every other document it is
        strictly narrower than ``apply``.

        That restraint is the point. Applying a document's mechanical HASH fix
        while its sibling prose region is ESCALATED destroys the ONLY staleness
        trigger that region has — ``heal._corrected`` stamps the fingerprint even
        when it skips the region — so ``remaining`` comes back empty, ``cdx check``
        is green forever, and the human is never asked again.
        """
        report = self.check()
        effective_apply = self.config.apply_default if apply is None else apply
        effective_tiered = self.config.apply_tiered if tiered is None else tiered
        # The set an unattended write may touch. Computed ONCE from the opening
        # report so the fold is a property of the run, not of the write order.
        mechanical = mechanical_docs(report) if effective_tiered else None
        if mechanical is not None and self._rules:
            # D-06 holds the WHOLE document, not just its own drift. A rule-matched
            # drift is recorded and never applied — but the engine's HASH close is
            # WHOLE-DOC (`render_corrected`) and regenerates every known region,
            # including the one the rule just held. Reproduced: a rule INVALIDATEd a
            # REGION drift and the sibling HASH write overwrote the body anyway,
            # inverting the learning loop silently. So a rule match withdraws its
            # document from the mechanical set entirely.
            mechanical -= {
                d.doc_id for d in report.drifts if rule_for(d, self._rules) is not None
            }

        # D-04: when retrieval is ON, read the substrate ONCE (the review log + the
        # resolutions log) up front — before any new records are appended — so a
        # drift is never ranked against records produced by this same run. DEFAULT
        # OFF reads nothing (byte-identical to pre-D-04).
        history: list[ReviewRecord] = []
        resolutions: list[ResolutionRecord] = []
        if self._use_exemplars:
            history = reviewlog.read_all(self._log_path)
            resolutions = reviewlog.read_resolutions(self._resolutions_path)

        handled: list[HandledDrift] = []
        records: list[ReviewRecord] = []
        # RTE-03d: per-DOCUMENT facts about what the engine closed unattended.
        # (drift, record_id, attempted, wrote) in drift-encounter order, which is
        # deterministic — `report.drifts` is built in config document order (K10).
        closed: dict[str, list[tuple[Drift, str, bool, bool]]] = {}

        for drift in report.drifts:
            # EPIC B: doc↔doc suspect links never go to the backend (a fix would
            # clobber the downstream prose). They are handled below by a dedicated
            # pass that has the structured upstream id + status.
            if drift.kind is DriftKind.SUSPECT_LINK:
                continue
            spec = self._spec_for(drift.doc_id)
            surface = build_document_surface(spec, self.root)
            doc_path = self.root / spec.path

            # D-06: a drift matching a promoted rule is resolved by the rule with
            # ZERO backend calls — the learned cost-curve win (K4). Still recorded +
            # emitted for human audit (K5), marked RULE-sourced. A FIX is never
            # synthesized (rules carry no fix), so nothing is applied. DEFAULT
            # rules=() never enters this branch ⇒ byte-identical to today.
            rule = rule_for(drift, self._rules)
            if rule is not None:
                result = BackendResult(
                    verdict=rule.verdict,
                    cause=(
                        f"{RULE_CAUSE_PREFIX}: ({drift.doc_id}, {drift.kind.value}, "
                        f"{drift.audience.value}) resolved {rule.verdict.value} by "
                        "humans >=K times — applied deterministically (no backend)"
                    ),
                    fix=None,
                )
                record = self._record_for(drift, result, surface, rule_sourced=True)
                reviewlog.append(self._log_path, record)
                self._sink.emit(record)
                records.append(record)
                handled.append(HandledDrift(drift=drift, result=result, applied=False))
                continue

            doc_text = self._doc_text(drift, doc_path)

            # RTE-03d: the ENGINE closes what the ENGINE projects — ZERO backend
            # calls. Placed BELOW the D-06 rule check on purpose: a promoted rule
            # is a verdict humans reached >=K times, and a CODE_DERIVED HASH drift
            # is exactly the shape a repo promotes an INVALIDATE rule for, so the
            # engine must never overwrite it.
            if mechanical is not None and drift.doc_id in mechanical:
                result = self._engine_result(drift, spec, surface, doc_text)
                record = self._record_for(drift, result, surface, engine_sourced=True)
                reviewlog.append(self._log_path, record)
                self._sink.emit(record)
                records.append(record)
                applied = False
                if effective_apply and result.fix is not None:
                    applied = apply_fix(
                        doc_path,
                        result.fix,
                        preserve=self._preserve_for(spec),
                        modes=self._modes_for(spec),
                    )
                closed.setdefault(drift.doc_id, []).append(
                    (drift, record.record_id, effective_apply, applied)
                )
                handled.append(
                    HandledDrift(drift=drift, result=result, applied=applied)
                )
                continue

            index_body: str | None = None
            if drift.region_id is not None:
                tmpl = self.config.region_templates.get(drift.region_id)
                if tmpl is not None and tmpl.source == "index":
                    index_body = render_index(tmpl, spec, self.config, self.root)

            exemplars: tuple[Exemplar, ...] = ()
            if self._use_exemplars:
                exemplars = self._retrieve_exemplars(
                    drift,
                    surface.surface_hash(
                        include_body=self.config.fingerprint_body_tier
                    ),
                    history,
                    resolutions,
                )

            # B-06: tell the backend the drifted region's authority mode, so a
            # no-renderer `llm` REGION is authored as prose (vs a `generated`
            # region mechanically rendered). Defaults to GENERATED for a whole-doc
            # (no region) drift — additive, K6.
            region_mode = (
                spec.mode_for(drift.region_id)
                if drift.region_id is not None
                else RegionMode.GENERATED
            )

            req = FixRequest(
                drift=drift,
                surface=surface,
                doc_text=doc_text,
                doc_spec_id=spec.id,
                region_templates=self.config.region_templates,
                index_body=index_body,
                exemplars=exemplars,
                region_mode=region_mode,
                style_guidance=self._style_guidance_for(drift, region_mode),
                # E-02: the document's glance-through context refs + the repo
                # root so build_prompt / the agent can render them (and read a
                # source-file ref's public-symbol glance). Additive, K6.
                context_refs=spec.context_refs,
                repo_root=str(self.root),
                fingerprint_body_tier=self.config.fingerprint_body_tier,
            )
            result = self._backend.propose(req)

            record = self._record_for(drift, result, surface)
            reviewlog.append(self._log_path, record)
            self._sink.emit(record)
            records.append(record)

            applied = False
            # RTE-03c/03d: under `--tiered` this is the HELD path — every
            # mechanically-closable document was already closed above without a
            # backend call, so anything reaching here needs human intent. It is
            # still RECORDED for the reviewer (K5) and never written, because
            # applying its mechanical half would destroy the escalation's own
            # staleness trigger (see `mechanical_docs`).
            if (
                effective_apply
                and mechanical is None
                and result.verdict is Verdict.FIX
                and result.fix is not None
            ):
                # Human-owned regions are never authored by the engine (B-02):
                # the guarantee is enforced at the heal write boundary, so even a
                # whole-doc backend FIX cannot clobber them. `modes` additionally
                # carries the B-03 lock (a human-edited llm-seeded region becomes
                # locked) and per-region hash stamping; passing the full
                # region_modes lets apply_fix derive both at the write boundary.
                applied = apply_fix(
                    doc_path,
                    result.fix,
                    preserve=self._preserve_for(spec),
                    modes=self._modes_for(spec),
                )

            handled.append(HandledDrift(drift=drift, result=result, applied=applied))

        # EPIC B — doc↔doc suspect links (no backend; human-in-loop, K5). On
        # ``--apply`` a brand-new UNSTAMPED edge is baselined (establishing a
        # baseline is not "blessing a change" — the downstream was authored against
        # the current upstream), recorded as a FIX. A genuinely SUSPECT edge (the
        # upstream changed) is ESCALATE'd to a human and the downstream is NEVER
        # auto-edited — it is cleared with ``cdx resolve --edge``. A no-op when no
        # edges are declared, so a pre-EPIC-B config is byte-identical (K6).
        self._handle_suspect_links(effective_apply, handled, records)

        remaining = self.check().drifts
        return MonitorResult(
            handled=tuple(handled),
            remaining=remaining,
            records=tuple(records),
            closures=self._closures(closed, remaining),
        )

    @staticmethod
    def _closures(
        closed: dict[str, list[tuple[Drift, str, bool, bool]]],
        remaining: tuple[Drift, ...],
    ) -> tuple[ClosureRecord, ...]:
        """Fold the per-drift closure facts into one record per DOCUMENT (RTE-03d).

        ``verified`` is graded against the post-run recheck and ignores
        ``SUSPECT_LINK``: a doc↔doc edge is handled by a pass that never applies a
        fix, so it can legitimately remain open on a document whose code↔doc drift
        closed cleanly. Sorted by ``doc_id``, with sorted+deduped kinds and evidence
        — nothing here iterates a set into the result (K10).
        """
        unclosed = {d.doc_id for d in remaining if d.kind is not DriftKind.SUSPECT_LINK}
        return tuple(
            ClosureRecord(
                doc_id=doc_id,
                doc_path=facts[0][0].doc_path,
                record_ids=tuple(sorted({rid for _, rid, _, _ in facts})),
                drift_kinds=tuple(sorted({d.kind.value for d, _, _, _ in facts})),
                evidence=tuple(
                    sorted({e for d, _, _, _ in facts for e in d.tier_evidence})
                ),
                attempted=any(attempted for _, _, attempted, _ in facts),
                wrote=any(wrote for _, _, _, wrote in facts),
                verified=doc_id not in unclosed,
            )
            for doc_id, facts in sorted(closed.items())
        )

    def _handle_suspect_links(
        self,
        effective_apply: bool,
        handled: list[HandledDrift],
        records: list[ReviewRecord],
    ) -> None:
        """Record (and on --apply, baseline) doc↔doc suspect links (EPIC B B-06)."""
        for link in detect_suspect_links(self.config, self.root):
            spec = self._spec_for(link.doc_id)
            surface = build_document_surface(spec, self.root)
            applied = False
            if link.status is SuspectStatus.UNSTAMPED and effective_apply:
                stamp_edges(self.config, self.root, link.doc_id, only=link.upstream_id)
                result = BackendResult(
                    verdict=Verdict.FIX,
                    cause=(
                        f"established the doc↔doc baseline for the new edge "
                        f"{link.doc_id} → {link.upstream_id}"
                    ),
                    fix=None,
                )
                applied = True
            else:
                result = BackendResult(
                    verdict=Verdict.ESCALATE, cause=link.detail, fix=None
                )
            drift = Drift(
                kind=DriftKind.SUSPECT_LINK,
                doc_id=link.doc_id,
                doc_path=link.doc_path,
                detail=f"{link.upstream_id}: {link.detail}",
                healable=False,
                audience=link.audience,
            )
            record = self._record_for(drift, result, surface)
            reviewlog.append(self._log_path, record)
            self._sink.emit(record)
            records.append(record)
            handled.append(HandledDrift(drift=drift, result=result, applied=applied))
