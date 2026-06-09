"""H-03 regression corpus — schema/transport/learning contracts.

Durable, cross-cutting invariants that protect the public schema's back-compat,
the report transport's never-raise guarantee, and the learned-rule cost win.
Each case names the lesson id it guards. See ``tests/regression/README.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

from code_doc_monitor.config import Audience
from code_doc_monitor.drift import DriftKind
from code_doc_monitor.schema import (
    ProposedFix,
    ResolutionRecord,
    ReviewRecord,
    Verdict,
    review_record_schema,
)

# ---------------------------------------------------------------------------
# [C-05 / D-01 / K6] Additive schema back-compat: a PRE-FIELD JSONL record still
# parses, with the new field defaulting.
# ---------------------------------------------------------------------------

_LEGACY_REVIEW_RECORD = {
    "schema_version": "1.0.0",
    "record_id": "abc123",
    "doc_id": "user-guide",
    "doc_path": "docs/user-guide.md",
    "audience": "user-guide",
    "drift_kind": "HASH",
    "drift_detail": "fingerprint moved",
    "cause": "public signature changed",
    "verdict": "FIX",
    "fix": None,
    "surface_hash": "deadbeef",
    "backend_kind": "mock",
    "detected_at": "2026-06-01T00:00:00Z",
    "resolved_at": "2026-06-01T00:00:01Z",
    "config_snapshot": {"version": "1.0.0"},
}


def test_pre_field_review_record_still_parses() -> None:
    """[C-05] A pre-`source_sha` JSONL line validates, field defaults to None.

    The K6 contract: an additive field is appended last WITH a default so an OLD
    line predating it still `model_validate_json`s. Guards ReviewRecord's
    additive back-compat — the most likely place a "harmless" refactor would make
    a field silently required.

    BREAK-IT (confirmed bites): making `source_sha` required (drop the `= None`
    default on ReviewRecord) raises ValidationError on the legacy line → this reds.
    """
    rec = ReviewRecord.model_validate_json(json.dumps(_LEGACY_REVIEW_RECORD))
    assert rec.source_sha is None


def test_pre_field_resolution_record_still_parses() -> None:
    """[D-01] A pre-`note` ResolutionRecord line validates (same K6 pattern)."""
    legacy = json.dumps(
        {
            "schema_version": "1.0.0",
            "record_id": "abc123",
            "resolution": "accepted",
            "resolved_by": "alice",
            "resolved_at": "2026-06-02T00:00:00Z",
        }
    )
    rec = ResolutionRecord.model_validate_json(legacy)
    assert rec.note is None


def test_emitted_schema_is_versioned_and_additive() -> None:
    """[C-05 / D-01] The emitted JSON Schema carries the additive `source_sha`.

    Proves the public schema export stays a superset (back-compat additive), so a
    downstream consumer generated from it keeps reading older records.
    """
    props = review_record_schema()["properties"]
    assert "source_sha" in props
    assert "schema_version" in props


def test_review_record_round_trips_with_set_field() -> None:
    """[C-05] A SET additive field round-trips losslessly (the forward half)."""
    rec = ReviewRecord(
        record_id="r1",
        doc_id="d",
        doc_path="docs/d.md",
        audience=Audience.ENG_GUIDE,
        drift_kind=DriftKind.HASH.value,
        drift_detail="x",
        cause="y",
        verdict=Verdict.FIX,
        fix=ProposedFix(
            region_id="symbols",
            new_region_body="body",
            new_doc_text=None,
            rationale="r",
        ),
        surface_hash="hash",
        backend_kind="mock",
        detected_at="2026-06-01T00:00:00Z",
        resolved_at="2026-06-01T00:00:01Z",
        config_snapshot={},
        source_sha="abc123",
    )
    again = ReviewRecord.model_validate_json(rec.model_dump_json())
    assert again == rec
    assert again.source_sha == "abc123"


# ---------------------------------------------------------------------------
# [E-01] Reporting is best-effort and NEVER raises into the heal loop: a down
# transport queues to the outbox instead of throwing.
# ---------------------------------------------------------------------------


class _DownClient:
    """An injected HTTP client whose POST always fails (network down)."""

    def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None:
        raise OSError("network down")


def test_reporting_never_raises_when_transport_down(tmp_path: Path) -> None:
    """[E-01] A down central transport queues, it does not throw.

    HttpSink.emit swallows every transport exception and falls back to the
    outbox, so a flaky/down central system can never crash `monitor --apply`.
    Guards the never-raise + queue-to-outbox contract.

    BREAK-IT (confirmed bites): narrowing HttpSink.emit's `except Exception` to a
    type the fake client doesn't raise (or removing the try/except) makes
    `emit` propagate the OSError → this reds.
    """
    from code_doc_monitor.sinks import HttpSink, RepoIdentity

    outbox = tmp_path / "outbox.jsonl"
    repo = RepoIdentity(
        repo_id="acme/widget",
        repo_name="widget",
        repo_url="https://git.example/acme/widget",
        commit="deadbeef",
    )
    sink = HttpSink(
        "https://central.example/ingest",
        repo=repo,
        outbox=outbox,
        client=_DownClient(),
    )
    rec = ReviewRecord.model_validate(_LEGACY_REVIEW_RECORD)

    # Three emits while down — NONE raise.
    sink.emit(rec)
    sink.emit(rec)
    sink.emit(rec)

    # All three were queued to the outbox instead of being lost or thrown.
    lines = [ln for ln in outbox.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# [D-06] A matched promoted rule resolves a drift with ZERO backend calls
# (the cost curve bends DOWN as the system learns); default rules=() is additive.
# ---------------------------------------------------------------------------


class _SpyBackend:
    """Counts `propose` calls; a matched-rule drift must NEVER reach it."""

    def __init__(self) -> None:
        from code_doc_monitor.backends import MockBackend

        self._inner = MockBackend()
        self.calls = 0

    def propose(self, req: object) -> object:
        self.calls += 1
        return self._inner.propose(req)  # type: ignore[arg-type]


def test_matched_rule_resolves_with_zero_backend_calls(tmp_path: Path) -> None:
    """[D-06] A matched rule resolves the drift WITHOUT consulting the backend.

    The validable goal is not the verdict but that `spy.calls == 0` — the rule
    path `continue`s before building the FixRequest. Guards the learned-rule cost
    win and its audit marker (`resolved_by="rule"`).

    BREAK-IT (confirmed bites): moving the rule check AFTER `backend.propose` in
    `monitor.run` makes `spy.calls == 1` for a matched drift → this reds.
    """
    from code_doc_monitor.monitor import Monitor
    from code_doc_monitor.promotion import PromotionRule
    from code_doc_monitor.reviewlog import read_all
    from code_doc_monitor.sinks import NullSink

    root, cfg = make_repo_with_region_drift(tmp_path)
    spy = _SpyBackend()
    rule = PromotionRule(
        doc_id="eng",
        drift_kind=DriftKind.REGION.value,
        audience=Audience.ENG_GUIDE,
        verdict=Verdict.INVALIDATE,
    )
    result = Monitor(
        cfg,
        root,
        now=lambda: "2026-06-01T00:00:00Z",
        sink=NullSink(),
        backend=spy,
        rules=(rule,),
    ).run(apply=True)

    assert spy.calls == 0  # the validable goal
    handled = [h for h in result.handled if h.result.verdict is Verdict.INVALIDATE]
    assert handled
    # Recorded for human audit (K5) with the rule-sourced marker (additive, K6).
    records = read_all(root / ".cdmon" / "review-log.jsonl")
    rule_records = [
        r for r in records if r.config_snapshot.get("resolved_by") == "rule"
    ]
    assert rule_records


def test_default_no_rules_is_additive_backend_for_everything(tmp_path: Path) -> None:
    """[D-06] Default `rules=()` keeps run() byte-identical: backend handles all.

    The additivity proof — the learned-rule feature is OFF by default, so every
    prior behaviour is unchanged (the backend is still consulted for each drift).
    """
    from code_doc_monitor.monitor import Monitor
    from code_doc_monitor.sinks import NullSink

    root, cfg = make_repo_with_region_drift(tmp_path)
    spy = _SpyBackend()
    Monitor(
        cfg,
        root,
        now=lambda: "2026-06-01T00:00:00Z",
        sink=NullSink(),
        backend=spy,
    ).run(apply=False)
    assert spy.calls >= 1  # default-empty rules: every drift still hits the backend


def make_repo_with_region_drift(tmp_path: Path) -> tuple[Path, object]:
    """A repo whose eng doc has EXACTLY ONE REGION drift the rule can match.

    Mirrors test_monitor._make_fixture (CDM-06: match the fixture's drift kind to
    what the chosen path resolves): a CORRECT fingerprint + a STALE region body →
    a single REGION drift, no co-occurring HASH drift to muddy the spy count.
    """
    from code_doc_monitor.config import CodeRef, DocumentSpec, MonitorConfig
    from code_doc_monitor.extract import build_document_surface

    from ._fixtures import SHARED_V1

    (tmp_path / "shared.py").write_text(SHARED_V1, encoding="utf-8")
    spec = DocumentSpec(
        id="eng",
        path="eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
    )
    surface = build_document_surface(spec, tmp_path)
    # Correct fingerprint (no HASH drift) but a stale region body (one REGION drift).
    (tmp_path / "eng.md").write_text(
        f"---\ncdm:\n  fingerprint: {surface.surface_hash()}\n---\n# Guide\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        "OUT OF DATE\n"
        "<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    return tmp_path, MonitorConfig(root=".", documents=(spec,))
