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
:class:`~code_doc_monitor.schema.ReviewRecord` is always written and emitted, so
``INVALIDATE``/``ESCALATE`` are recorded for a human, never silently dropped.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from . import reviewlog
from .backends import Backend, BackendResult, FixRequest, make_backend
from .config import DocumentSpec, MonitorConfig
from .drift import Drift, DriftKind, DriftReport, detect
from .extract import DocumentSurface, build_document_surface
from .heal import apply_fix
from .index import render_index
from .schema import ProposedFix, ReviewRecord, Verdict, new_record_id
from .sinks import Sink, make_sink

__all__ = ["HandledDrift", "MonitorResult", "Monitor", "DEFAULT_LOG_PATH"]

#: Default review-log location, relative to the config directory.
DEFAULT_LOG_PATH = Path(".cdmon") / "review-log.jsonl"

# Frozen + extra="forbid": results are immutable snapshots of one run.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class HandledDrift(BaseModel):
    """One drift that was sent to the backend, with its verdict and outcome."""

    model_config = _MODEL_CONFIG

    drift: Drift
    result: BackendResult
    applied: bool


class MonitorResult(BaseModel):
    """The outcome of one :meth:`Monitor.run`: handled, remaining, recorded."""

    model_config = _MODEL_CONFIG

    handled: tuple[HandledDrift, ...]
    remaining: tuple[Drift, ...]
    records: tuple[ReviewRecord, ...]


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
    ) -> None:
        self.config = config
        self.config_dir = config_dir
        self.root = config_dir / config.root
        self._backend: Backend = backend or make_backend(config.backend, config.agent)
        self._sink: Sink = sink or make_sink(config.central)
        self._now: Callable[[], str] = now or _default_now
        self._log_path = log_path or (config_dir / DEFAULT_LOG_PATH)

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

    def _record_for(
        self,
        drift: Drift,
        result: BackendResult,
        surface: DocumentSurface,
    ) -> ReviewRecord:
        stamp = self._now()
        surface_hash = surface.surface_hash()
        fix: ProposedFix | None = result.fix
        return ReviewRecord(
            record_id=new_record_id(drift.doc_id, surface_hash, stamp),
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
            config_snapshot={
                "backend": self.config.backend.kind,
                "root": self.config.root,
            },
        )

    def run(self, *, apply: bool | None = None) -> MonitorResult:
        """Detect -> per-drift backend verdict -> record + emit -> (apply) -> recheck.

        ``apply`` overrides ``config.apply_default`` (``None`` -> use the config).
        A FIX is applied only when ``apply`` is effectively true (K5). Every
        verdict is recorded and emitted regardless. ``remaining`` is the result
        of a fresh detect after any applies (so FIX'd drift drops out and
        ESCALATE/unapplied drift persists).
        """
        report = self.check()
        effective_apply = self.config.apply_default if apply is None else apply

        handled: list[HandledDrift] = []
        records: list[ReviewRecord] = []

        for drift in report.drifts:
            spec = self._spec_for(drift.doc_id)
            surface = build_document_surface(spec, self.root)
            doc_path = self.root / spec.path
            doc_text = self._doc_text(drift, doc_path)

            index_body: str | None = None
            if drift.region_id is not None:
                tmpl = self.config.region_templates.get(drift.region_id)
                if tmpl is not None and tmpl.source == "index":
                    index_body = render_index(tmpl, spec, self.config, self.root)

            req = FixRequest(
                drift=drift,
                surface=surface,
                doc_text=doc_text,
                doc_spec_id=spec.id,
                region_templates=self.config.region_templates,
                index_body=index_body,
            )
            result = self._backend.propose(req)

            record = self._record_for(drift, result, surface)
            reviewlog.append(self._log_path, record)
            self._sink.emit(record)
            records.append(record)

            applied = False
            if (
                effective_apply
                and result.verdict is Verdict.FIX
                and result.fix is not None
            ):
                applied = apply_fix(doc_path, result.fix)

            handled.append(HandledDrift(drift=drift, result=result, applied=applied))

        remaining = self.check().drifts
        return MonitorResult(
            handled=tuple(handled),
            remaining=remaining,
            records=tuple(records),
        )
