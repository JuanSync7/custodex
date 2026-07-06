"""AGT-06 — the two background suggesters (`workers.py`): pure ticks + keys.

The "two running parallel in Custodex": `suggest_fixes_tick` (FIX_DRIFT /
RESOLVE_EDGE / PROMOTE_RULE — what's broken, suspect or promotable NOW) and
`suggest_docs_tick` (DOCUMENT_GAP / ADD_EDGE — what to document and map next).
Pure in the K1 sense (read-only FS, no clock in any key), deterministic (K10),
advisory-only (K11: every detail embeds the next HUMAN command).

Key discipline (the ⟨R⟩ pin): EVENT kinds embed the occurrence (surface hash /
upstream fingerprint) so a recurrence after a heal is a NEW key; STANDING kinds
are occurrence-free so a dismiss is a durable opt-out. detail/evidence/severity
/now are NEVER hashed.

Features: FEAT-WORKERS-001
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import load_bundle
from custodex.monitor import DEFAULT_LOG_PATH
from custodex.reviewlog import DEFAULT_RESOLUTIONS_PATH, append, append_resolution
from custodex.schema import Resolution, ResolutionRecord, ReviewRecord, Verdict
from custodex.workers import (
    Suggestion,
    SuggestionKind,
    render_suggestions_text,
    suggest_docs_tick,
    suggest_fixes_tick,
)
from custodex.worklist import WorkSeverity

_UNIT = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "core docs"
owner: eng
created: "2026-07-01"
updated: "2026-07-01"
---
dir-covered:
  - src
source-files-format:
  - .py
documents:
  - id: guide
    path: docs/guide.md
    audience: eng-guide
    code_refs:
      - path: src/alpha.py
  - id: api
    path: docs/api.md
    audience: eng-guide
    region_keys: []
  - id: notes
    path: docs/notes.md
    audience: eng-guide
    region_keys: []
    depends_on:
      - doc: api
"""

_INDEX = """\
---
cdmon-config-version: "2.0.0"
repo: t
generated-by: cdx
updated: "2026-07-01"
---
root: "../.."
version: "2.0.0"
backend: {kind: mock}
units:
  - file: core.yaml
"""

_NOW = "2026-07-06T12:00:00+00:00"


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _setup(tmp_path: Path) -> Path:
    """A HEALED bundle, then one drifted doc + one suspect edge + one gap."""
    from custodex.monitor import Monitor

    cfg_dir = tmp_path / "config" / "cdmon"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "index.yaml").write_text(_INDEX, encoding="utf-8")
    (cfg_dir / "core.yaml").write_text(_UNIT, encoding="utf-8")
    _write(
        tmp_path,
        "src/alpha.py",
        'def solve_widget(x):\n    """Doc."""\n    return x\n',
    )
    # `hot_gap` is mentioned by prose but covered by NO doc → DOCUMENT_GAP.
    _write(tmp_path, "src/gamma.py", "def hot_gap(z):\n    return z\n")
    # guide's prose mentions the gap symbol and `solve_widget` (covered by
    # guide itself → no self ADD_EDGE).
    _write(
        tmp_path,
        "docs/guide.md",
        "# Guide\n\nCall `hot_gap` before `solve_widget`.\n",
    )
    # notes depends_on api; notes' prose mentions `solve_widget`, which ONLY
    # guide covers → ADD_EDGE notes→guide.
    _write(tmp_path, "docs/api.md", "# API\n\nReference.\n")
    _write(tmp_path, "docs/notes.md", "# Notes\n\nUses `solve_widget` too.\n")

    # Heal everything (mock backend, offline): regions + fingerprints stamped
    # and the declared edge baselined — the tick's job is CURRENT reality, so
    # start clean, then introduce exactly one of each problem class.
    bundle = load_bundle(cfg_dir)
    Monitor(bundle.config, cfg_dir, now=lambda: _NOW).run(apply=True)
    # 1) FIX_DRIFT: alpha's surface changes → guide drifts.
    _write(
        tmp_path,
        "src/alpha.py",
        'def solve_widget(x, *, scale=1):\n    """Doc."""\n    return x * scale\n',
    )
    # 2) RESOLVE_EDGE: api's PROSE changes AFTER the stamp (frontmatter kept —
    # a whole-file rewrite would drop the healed cdm stamp) → the edge is
    # SUSPECT until a human re-confirms it.
    _edit_body(tmp_path / "docs" / "api.md", "Reference.", "Reference, revised.")
    return cfg_dir


def _edit_body(path: Path, old: str, new: str) -> None:
    """Replace prose in a HEALED doc without touching its cdm frontmatter."""
    text = path.read_text(encoding="utf-8")
    assert old in text, f"fixture drift: {old!r} not in {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def _ticks(cfg_dir: Path) -> tuple[tuple[Suggestion, ...], tuple[Suggestion, ...]]:
    bundle = load_bundle(cfg_dir)
    fixes = suggest_fixes_tick(bundle.config, cfg_dir, now=_NOW)
    docs = suggest_docs_tick(bundle.config, cfg_dir, now=_NOW)
    return fixes, docs


def _by_kind(suggestions: tuple[Suggestion, ...], kind: SuggestionKind):
    return [s for s in suggestions if s.kind is kind]


class TestFixesTick:
    def test_fix_drift_fires_per_drifted_doc(self, tmp_path: Path) -> None:
        fixes, _ = _ticks(_setup(tmp_path))
        (fix,) = _by_kind(fixes, SuggestionKind.FIX_DRIFT)
        assert fix.doc_id == "guide"
        assert "cdx monitor --apply" in fix.detail  # the exact next command
        assert fix.severity is WorkSeverity.HIGH
        assert fix.evidence  # the drift kinds ride along

    def test_resolve_edge_fires_per_non_ok_link(self, tmp_path: Path) -> None:
        fixes, _ = _ticks(_setup(tmp_path))
        (edge,) = _by_kind(fixes, SuggestionKind.RESOLVE_EDGE)
        assert edge.doc_id == "notes" and edge.target == "api"
        assert "cdx resolve --edge notes api" in edge.detail
        assert edge.severity is WorkSeverity.MEDIUM

    def test_suspect_link_drift_is_owned_by_resolve_edge(self, tmp_path: Path) -> None:
        # No FIX_DRIFT suggestion may cite the edge docs' SUSPECT_LINK — the
        # RESOLVE_EDGE kind owns edges (no double-billing one problem). The
        # fixture HAS a suspect edge (notes → api), so `notes` must not
        # surface as a drifted doc at all.
        from custodex.drift import DriftKind

        fixes, _ = _ticks(_setup(tmp_path))
        drifted = _by_kind(fixes, SuggestionKind.FIX_DRIFT)
        assert all(f.doc_id != "notes" for f in drifted)
        for fix in drifted:
            kinds = {e.split(":", 1)[0] for e in fix.evidence}
            assert DriftKind.SUSPECT_LINK.value not in kinds

    def test_promote_rule_fires_on_unanimous_shape(self, tmp_path: Path) -> None:
        cfg_dir = _setup(tmp_path)
        log = cfg_dir / DEFAULT_LOG_PATH
        res = cfg_dir / DEFAULT_RESOLUTIONS_PATH
        log.parent.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            rid = f"r-{i}"
            append(
                log,
                ReviewRecord(
                    record_id=rid,
                    doc_id="guide",
                    doc_path="docs/guide.md",
                    audience="eng-guide",
                    drift_kind="hash",
                    drift_detail="d",
                    cause="c",
                    verdict=Verdict.INVALIDATE,
                    fix=None,
                    surface_hash=f"h{i}",
                    backend_kind="mock",
                    detected_at=_NOW,
                    resolved_at=_NOW,
                    config_snapshot={},
                ),
            )
            append_resolution(
                res,
                ResolutionRecord(
                    record_id=rid,
                    resolution=Resolution.INVALIDATED,
                    resolved_at=_NOW,
                ),
            )
        fixes, _ = _ticks(cfg_dir)
        (promo,) = _by_kind(fixes, SuggestionKind.PROMOTE_RULE)
        assert promo.doc_id == "guide"
        assert "invalidated" in promo.detail
        assert promo.severity is WorkSeverity.LOW

    def test_fix_drift_key_is_event_scoped(self, tmp_path: Path) -> None:
        # Same doc, same surface: MORE drifts of the same kind (a second
        # missing region) keep the SAME key (detail/evidence never hashed)...
        cfg_dir = _setup(tmp_path)
        fixes1, _ = _ticks(cfg_dir)
        (fix1,) = _by_kind(fixes1, SuggestionKind.FIX_DRIFT)
        # ...but a SOURCE change (new occurrence: the surface hash moves)
        # mints a NEW key — a recurrence after a heal is new work.
        _write(
            tmp_path,
            "src/alpha.py",
            'def solve_widget(x, y):\n    """Doc."""\n    return x + y\n',
        )
        fixes2, _ = _ticks(cfg_dir)
        (fix2,) = _by_kind(fixes2, SuggestionKind.FIX_DRIFT)
        assert fix1.key != fix2.key

    def test_resolve_edge_key_tracks_upstream_occurrence(self, tmp_path: Path) -> None:
        cfg_dir = _setup(tmp_path)
        fixes1, _ = _ticks(cfg_dir)
        (edge1,) = _by_kind(fixes1, SuggestionKind.RESOLVE_EDGE)
        _edit_body(
            tmp_path / "docs" / "api.md", "Reference, revised.", "Reference, AGAIN."
        )
        fixes2, _ = _ticks(cfg_dir)
        (edge2,) = _by_kind(fixes2, SuggestionKind.RESOLVE_EDGE)
        assert edge1.key != edge2.key


class TestDocsTick:
    def test_document_gap_fires_per_undocumented_symbol(self, tmp_path: Path) -> None:
        _, docs = _ticks(_setup(tmp_path))
        gaps = _by_kind(docs, SuggestionKind.DOCUMENT_GAP)
        assert [g.target for g in gaps] == ["symbol src/gamma.py#hot_gap"]
        assert "cdx write-doc src/gamma.py" in gaps[0].detail  # the next verb
        assert gaps[0].doc_id is None
        assert gaps[0].severity is WorkSeverity.LOW

    def test_add_edge_fires_and_honors_rejections(self, tmp_path: Path) -> None:
        from custodex.docmap import reject_edge

        cfg_dir = _setup(tmp_path)
        _, docs = _ticks(cfg_dir)
        edges = _by_kind(docs, SuggestionKind.ADD_EDGE)
        assert [(e.doc_id, e.target) for e in edges] == [("notes", "guide")]
        assert "cdx link notes guide" in edges[0].detail
        # A durable human 'no' silences the pair for the worker too (K11).
        reject_edge(cfg_dir / ".cdmon", "notes", "guide", now=_NOW)
        _, docs2 = _ticks(cfg_dir)
        assert _by_kind(docs2, SuggestionKind.ADD_EDGE) == []

    def test_standing_keys_are_occurrence_free(self, tmp_path: Path) -> None:
        # DOCUMENT_GAP: a second mentioning doc changes the evidence, never
        # the key; ADD_EDGE: an upstream body edit never moves the key.
        cfg_dir = _setup(tmp_path)
        _, docs1 = _ticks(cfg_dir)
        (gap1,) = _by_kind(docs1, SuggestionKind.DOCUMENT_GAP)
        (edge1,) = _by_kind(docs1, SuggestionKind.ADD_EDGE)
        _edit_body(
            tmp_path / "docs" / "api.md",
            "Reference, revised.",
            "Reference, revised — now also calls `hot_gap` in prose.",
        )
        _, docs2 = _ticks(cfg_dir)
        (gap2,) = _by_kind(docs2, SuggestionKind.DOCUMENT_GAP)
        (edge2,) = _by_kind(docs2, SuggestionKind.ADD_EDGE)
        assert gap1.key == gap2.key
        assert edge1.key == edge2.key


class TestShape:
    def test_ticks_are_deterministic_and_sorted_by_key(self, tmp_path: Path) -> None:
        cfg_dir = _setup(tmp_path)
        fixes_a, docs_a = _ticks(cfg_dir)
        fixes_b, docs_b = _ticks(cfg_dir)
        assert fixes_a == fixes_b and docs_a == docs_b
        assert [s.key for s in fixes_a] == sorted(s.key for s in fixes_a)
        assert [s.key for s in docs_a] == sorted(s.key for s in docs_a)

    def test_keys_are_16_hex_and_unique(self, tmp_path: Path) -> None:
        fixes, docs = _ticks(_setup(tmp_path))
        keys = [s.key for s in (*fixes, *docs)]
        assert len(set(keys)) == len(keys)
        assert all(len(k) == 16 and int(k, 16) >= 0 for k in keys)

    def test_render_text_lists_kinds_and_commands(self, tmp_path: Path) -> None:
        fixes, docs = _ticks(_setup(tmp_path))
        text = render_suggestions_text((*fixes, *docs))
        assert "fix_drift" in text and "document_gap" in text
        assert "cdx monitor --apply" in text
        assert render_suggestions_text(()) == "# no suggestions — all clear"
