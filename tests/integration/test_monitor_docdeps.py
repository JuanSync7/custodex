"""EPIC B (B-06): the Monitor handles doc↔doc suspect links (offline, K4/K5/K7).

A SUSPECT_LINK never goes to the backend for an auto-fix (it would clobber the
downstream); instead the Monitor records it as an auditable ReviewRecord and,
only on ``--apply``, establishes the baseline for a brand-new UNSTAMPED edge.
A genuinely SUSPECT edge (the upstream changed) is ESCALATE'd to a human and the
downstream is NEVER auto-edited. Idempotent (K7): a re-run with no change is a
no-op.

Features: FEAT-DOCDEPS-006
Features: FEAT-MONITOR-010
Features: FEAT-RECORD-014
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import (
    Audience,
    DocDepsConfig,
    DocEdge,
    DocumentSpec,
    MonitorConfig,
    RegionMode,
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


# --- RTE-03c: the ONE write that still touches a HELD document --------------


def test_tiered_still_baselines_a_new_edge_on_a_held_document(tmp_path: Path) -> None:
    """[RTE-03c] The edge baseline is a deliberate carve-out from `--tiered`.

    `--tiered` promises "no managed-region or fingerprint write on a document that
    needs human intent". `_handle_suspect_links` -> `stamp_edges` writes such a
    document anyway, because establishing a baseline is not blessing a change: it
    touches ONLY `cdm.upstream_hashes` — never a managed region, never
    `cdm.fingerprint` — and so destroys no code↔doc staleness trigger. The RTE-01
    rationale says that pass "never calls `apply_fix`", which is true but is NOT
    the same as "never writes"; this test is what makes the difference explicit
    rather than accidental.
    """
    _managed(tmp_path, _OVERVIEW, "# Overview\nupstream\n")
    # A downstream carrying an UNHEALABLE region -> NEEDS_INTENT -> the doc is HELD.
    (tmp_path / _API.path).write_text(
        "# API\n\n<!-- CDM:BEGIN prose -->\nhand-written\n<!-- CDM:END prose -->\n",
        encoding="utf-8",
    )
    held = DocumentSpec(
        id="api",
        path="api.md",
        audience=Audience.ENG_GUIDE,
        region_keys=("prose",),
        depends_on=(DocEdge(doc="overview"),),
    )
    cfg = MonitorConfig(root=".", documents=(_OVERVIEW, held), docdeps=DocDepsConfig())
    before = (tmp_path / _API.path).read_text(encoding="utf-8")

    result = _monitor(cfg, tmp_path, tmp_path / "log.jsonl").run(
        apply=True, tiered=True
    )

    after = (tmp_path / _API.path).read_text(encoding="utf-8")
    assert after != before  # the edge WAS baselined
    assert "upstream_hashes" in after  # and that is the only thing that moved
    assert "<!-- CDM:BEGIN prose -->\nhand-written\n" in after  # region untouched
    assert "fingerprint" not in after  # no code↔doc trigger was consumed
    # The held region is still reported, so the human is still asked.
    assert any(
        d.doc_id == "api" and d.kind is DriftKind.UNHEALABLE for d in result.remaining
    )


def test_a_closed_document_stays_verified_with_an_open_suspect_link(
    tmp_path: Path,
) -> None:
    """[RTE-03d] `verified` ignores SUSPECT_LINK — a doc↔doc edge is not a closure.

    Suspect links are handled by a pass that never calls `apply_fix`, so one can
    legitimately remain open on a document whose code↔doc drift closed cleanly.
    Counting it would mark every mechanically-closed downstream unverified and fire
    the alarm on a healthy run — the alarm would then be noise, and noise is how an
    alarm stops being read.
    """
    from custodex.blocks import symbol_table
    from custodex.config import CodeRef
    from custodex.extract import build_document_surface
    from custodex.heal import regenerate_regions

    (tmp_path / "code.py").write_text(
        '"""M."""\n\n\ndef alpha(x: int) -> int:\n    """Alpha."""\n    return x\n',
        encoding="utf-8",
    )
    up = DocumentSpec(id="overview", path="overview.md", audience=Audience.ENG_GUIDE)
    down = DocumentSpec(
        id="api",
        path="api.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
        depends_on=(DocEdge(doc="overview"),),
    )
    cfg = MonitorConfig(root=".", documents=(up, down), docdeps=DocDepsConfig())
    _managed(tmp_path, up, "# Overview\nupstream\n")
    (tmp_path / down.path).write_text(
        "# API\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    regenerate_regions(
        tmp_path / down.path,
        build_document_surface(down, tmp_path),
        modes={"symbols": RegionMode.GENERATED},
    )
    # Baseline the edge, then move the UPSTREAM so the edge becomes SUSPECT...
    stamp_edges(cfg, tmp_path, "api")
    _managed(tmp_path, up, "# Overview\nupstream CHANGED\n")
    # ...while the downstream's own symbol table goes mechanically stale.
    text = (tmp_path / down.path).read_text(encoding="utf-8")
    (tmp_path / down.path).write_text(
        text.replace(symbol_table(build_document_surface(down, tmp_path)), "STALE"),
        encoding="utf-8",
    )

    result = _monitor(cfg, tmp_path, tmp_path / "log.jsonl").run(
        apply=True, tiered=True
    )

    assert any(d.kind is DriftKind.SUSPECT_LINK for d in result.remaining)
    closure = next(c for c in result.closures if c.doc_id == "api")
    assert closure.verified  # the code↔doc close DID converge
