"""EPIC B (B-04): SUSPECT_LINK surfaces through the normal drift.detect() path.

``detect()`` appends doc↔doc suspect links as ordinary ``Drift`` data (healable=
False — they are resolved by ``cdx resolve --edge``, never auto-edited), so
``cdx check`` and ``cdx monitor`` see them with zero extra wiring. Detection
stays K1 (no stamp is written here); the ``docdeps.enabled`` knob gates whether
they are computed at all.

Features: FEAT-DOCDEPS-004
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
from custodex.drift import DriftKind, detect
from custodex.extract import build_document_surface
from custodex.manifest import render_doc, set_fingerprint

_OVERVIEW = DocumentSpec(id="overview", path="overview.md", audience=Audience.ENG_GUIDE)
_API = DocumentSpec(
    id="api",
    path="api.md",
    audience=Audience.USER_GUIDE,
    depends_on=(DocEdge(doc="overview"),),
)


def _cfg(*, enabled: bool = True) -> MonitorConfig:
    return MonitorConfig(
        root=".",
        documents=(_OVERVIEW, _API),
        docdeps=DocDepsConfig(enabled=enabled),
    )


def _managed(root: Path, spec: DocumentSpec, body: str) -> None:
    """Write a doc whose code↔doc fingerprint matches its (empty) surface, so the
    only thing that can drift it is a doc↔doc suspect link."""
    surface = build_document_surface(spec, root)
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")


def test_detect_reports_suspect_link_after_upstream_change(tmp_path: Path) -> None:
    _managed(tmp_path, _OVERVIEW, "# Overview\nupstream content\n")
    _managed(tmp_path, _API, "# API\ndownstream content\n")
    cfg = _cfg()
    stamp_edges(cfg, tmp_path, "api")  # baseline so the edge starts OK
    assert detect(cfg, tmp_path).ok  # code↔doc clean AND edge stamped

    _managed(tmp_path, _OVERVIEW, "# Overview\nUPSTREAM CHANGED\n")  # body moved
    report = detect(cfg, tmp_path)
    suspects = [d for d in report.drifts if d.kind is DriftKind.SUSPECT_LINK]
    assert len(suspects) == 1
    d = suspects[0]
    assert d.doc_id == "api"
    assert d.healable is False  # resolved by a human ack, never auto-edited
    assert d.audience is Audience.USER_GUIDE  # the downstream's audience (K3)
    assert "overview" in d.detail
    assert "SUSPECT_LINK" in report.summary()


def test_unstamped_edge_is_a_suspect_link(tmp_path: Path) -> None:
    """A freshly-declared, never-stamped edge shows up as a SUSPECT_LINK drift."""
    _managed(tmp_path, _OVERVIEW, "# Overview\nx\n")
    _managed(tmp_path, _API, "# API\ny\n")
    report = detect(_cfg(), tmp_path)
    assert any(d.kind is DriftKind.SUSPECT_LINK for d in report.drifts)


def test_disabled_docdeps_suppresses_suspect_links(tmp_path: Path) -> None:
    _managed(tmp_path, _OVERVIEW, "# Overview\nx\n")
    _managed(tmp_path, _API, "# API\ny\n")
    report = detect(_cfg(enabled=False), tmp_path)
    assert all(d.kind is not DriftKind.SUSPECT_LINK for d in report.drifts)
