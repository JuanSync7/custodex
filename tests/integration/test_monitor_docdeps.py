"""EPIC B (B-06): the Monitor handles doc↔doc suspect links (offline, K4/K5/K7).

A SUSPECT_LINK never goes to the backend for an auto-fix (it would clobber the
downstream); instead the Monitor records it as an auditable ReviewRecord and,
only on ``--apply``, establishes the baseline for a brand-new UNSTAMPED edge.
A genuinely SUSPECT edge (the upstream changed) is ESCALATE'd to a human and the
downstream is NEVER auto-edited. Idempotent (K7): a re-run with no change is a
no-op.

Features: FEAT-DOCDEPS-006
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import (
    Audience,
    DocDepsConfig,
    DocEdge,
    DocumentSpec,
    MonitorConfig,
)
from custodex.docdeps import stamp_edges
from custodex.drift import DriftKind
from custodex.extract import build_document_surface
from custodex.manifest import render_doc, set_fingerprint
from custodex.monitor import Monitor
from custodex.reviewlog import read_all
from custodex.schema import Verdict
from custodex.sinks import NullSink

FIXED_NOW = "2026-06-01T00:00:00+00:00"


def _now() -> str:
    return FIXED_NOW


_OVERVIEW = DocumentSpec(id="overview", path="overview.md", audience=Audience.ENG_GUIDE)
_API = DocumentSpec(
    id="api",
    path="api.md",
    audience=Audience.ENG_GUIDE,
    depends_on=(DocEdge(doc="overview"),),
)


def _cfg() -> MonitorConfig:
    return MonitorConfig(root=".", documents=(_OVERVIEW, _API), docdeps=DocDepsConfig())


def _managed(root: Path, spec: DocumentSpec, body: str) -> None:
    surface = build_document_surface(spec, root)
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")


def _monitor(cfg: MonitorConfig, root: Path, log: Path) -> Monitor:
    return Monitor(cfg, root, now=_now, sink=NullSink(), log_path=log)


def test_apply_establishes_baseline_for_new_edge(tmp_path: Path) -> None:
    _managed(tmp_path, _OVERVIEW, "# Overview\nupstream\n")
    _managed(tmp_path, _API, "# API\ndown\n")
    cfg = _cfg()
    log = tmp_path / "log.jsonl"

    result = _monitor(cfg, tmp_path, log).run(apply=True)
    # The unstamped edge was baselined and recorded.
    link_records = [r for r in result.records if r.drift_kind == "SUSPECT_LINK"]
    assert len(link_records) == 1
    assert result.remaining == ()  # recheck clean after baselining

    # K7: a second run with no change writes nothing new.
    again = _monitor(cfg, tmp_path, log).run(apply=True)
    assert again.records == ()
    assert again.remaining == ()


def test_suspect_link_escalates_and_never_auto_edits(tmp_path: Path) -> None:
    _managed(tmp_path, _OVERVIEW, "# Overview\nupstream\n")
    _managed(tmp_path, _API, "# API\ndown\n")
    cfg = _cfg()
    log = tmp_path / "log.jsonl"
    stamp_edges(cfg, tmp_path, "api")  # baseline first

    # Upstream changes -> the edge is now genuinely SUSPECT.
    _managed(tmp_path, _OVERVIEW, "# Overview\nUPSTREAM CHANGED\n")
    api_before = (tmp_path / "api.md").read_bytes()

    result = _monitor(cfg, tmp_path, log).run(apply=True)
    link_records = [r for r in result.records if r.drift_kind == "SUSPECT_LINK"]
    assert len(link_records) == 1
    # ESCALATE'd to a human — never auto-fixed.
    assert link_records[0].verdict is Verdict.ESCALATE
    assert link_records[0].fix is None
    # The downstream doc was NOT auto-edited.
    assert (tmp_path / "api.md").read_bytes() == api_before
    # Still suspect after the run (a human must `cdx resolve --edge`).
    assert any(d.kind is DriftKind.SUSPECT_LINK for d in result.remaining)


def test_no_apply_records_but_does_not_stamp(tmp_path: Path) -> None:
    _managed(tmp_path, _OVERVIEW, "# Overview\nupstream\n")
    _managed(tmp_path, _API, "# API\ndown\n")
    cfg = _cfg()
    log = tmp_path / "log.jsonl"

    result = _monitor(cfg, tmp_path, log).run(apply=False)
    # Recorded for audit, but not baselined (still unstamped/suspect).
    assert [r.drift_kind for r in result.records] == ["SUSPECT_LINK"]
    assert any(d.kind is DriftKind.SUSPECT_LINK for d in result.remaining)
    assert read_all(log)[0].verdict is Verdict.ESCALATE
