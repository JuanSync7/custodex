"""CDM-09 — the ``source='index'`` layer: collection/landing-page regions.

Covers the pure renderer (rows = other docs, linked titles, summaries, audience
filter, self-exclusion), drift detection when a sibling changes, and the full
``monitor --apply`` self-heal of an index region (via the threaded index_body).
Offline throughout (mock backend). TDD (K9).

Features: FEAT-CONFIGV2-015, FEAT-MONITOR-001, FEAT-MONITOR-002
Features: FEAT-MONITOR-003, FEAT-MONITOR-004
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import (
    Audience,
    DocumentSpec,
    MonitorConfig,
    RegionColumn,
    RegionTemplate,
)
from custodex.index import render_index
from custodex.monitor import Monitor

_TEMPLATE = RegionTemplate(
    source="index",
    columns=(
        RegionColumn(header="Document", field="title"),
        RegionColumn(header="What it covers", field="summary"),
    ),
)


def _doc(stage: str, title: str, purpose: str) -> str:
    return f"# {title}\n\n> {purpose}\n"


def _config(*, kind: str | None = None) -> MonitorConfig:
    tmpl = _TEMPLATE.model_copy(update={"kind": kind})
    return MonitorConfig(
        documents=(
            DocumentSpec(
                id="index",
                path="docs/index.md",
                audience=Audience.ENG_GUIDE,
                region_keys=("idx",),
            ),
            DocumentSpec(
                id="alpha",
                path="docs/alpha.md",
                audience=Audience.USER_GUIDE,
                code_refs=(),
                html=True,
            ),
            DocumentSpec(
                id="beta",
                path="docs/beta.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(),
            ),
        ),
        region_templates={"idx": tmpl},
    )


def _write_targets(root: Path, cfg: MonitorConfig | None = None) -> None:
    """Write the alpha/beta target guides; if ``cfg`` is given, stamp them in-sync."""
    (root / "docs").mkdir(parents=True, exist_ok=True)
    contents = {
        "alpha": ("Alpha Guide", "How to do alpha things."),
        "beta": ("Beta Guide", "The beta internals."),
    }
    specs = {d.id: d for d in cfg.documents} if cfg else {}
    for stage, (title, purpose) in contents.items():
        body = _doc(stage, title, purpose)
        if stage in specs:
            from custodex.extract import build_document_surface
            from custodex.layout import LAYOUT_VERSION
            from custodex.manifest import (
                render_doc,
                set_fingerprint,
                stamp_standard_meta,
            )

            spec = specs[stage]
            surface = build_document_surface(spec, root)
            meta = stamp_standard_meta(
                {}, schema_version=LAYOUT_VERSION, audience=spec.audience.value
            )
            meta = set_fingerprint(meta, surface.surface_hash())
            body = render_doc(meta, body)
        (root / "docs" / f"{stage}.md").write_text(body, encoding="utf-8")


# --- pure renderer ------------------------------------------------------------


def test_render_index_lists_other_docs_with_linked_titles(tmp_path: Path) -> None:
    cfg = _config()
    _write_targets(tmp_path)
    index_spec = cfg.documents[0]
    body = render_index(cfg.region_templates["idx"], index_spec, cfg, tmp_path)

    assert "| Document | What it covers |" in body
    # alpha is html:true -> link to the .html twin; beta -> its .md
    assert "[Alpha Guide](alpha.html)" in body
    assert "[Beta Guide](beta.md)" in body
    assert "How to do alpha things." in body
    # the index never lists itself
    assert "index.md" not in body and "index.html" not in body


def test_render_index_audience_filter_via_kind(tmp_path: Path) -> None:
    cfg = _config(kind="user-guide")
    _write_targets(tmp_path)
    body = render_index(cfg.region_templates["idx"], cfg.documents[0], cfg, tmp_path)
    assert "Alpha Guide" in body  # user-guide kept
    assert "Beta Guide" not in body  # eng-guide filtered out


def test_render_index_empty_collection_uses_empty_text(tmp_path: Path) -> None:
    tmpl = _TEMPLATE.model_copy(update={"empty_text": "_No docs._"})
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(
                id="index",
                path="docs/index.md",
                audience=Audience.ENG_GUIDE,
                region_keys=("idx",),
            ),
        ),
        region_templates={"idx": tmpl},
    )
    body = render_index(tmpl, cfg.documents[0], cfg, tmp_path)
    assert body == "_No docs._"


# --- detect + heal end to end -------------------------------------------------


def _seed_in_sync(tmp_path: Path) -> MonitorConfig:
    """Write the targets + a fully in-sync index doc; return the config."""
    from custodex.extract import build_document_surface
    from custodex.layout import LAYOUT_VERSION
    from custodex.manifest import (
        render_doc,
        set_fingerprint,
        stamp_standard_meta,
    )

    cfg = _config()
    _write_targets(tmp_path, cfg)
    index_spec = cfg.documents[0]
    region = render_index(cfg.region_templates["idx"], index_spec, cfg, tmp_path)
    surface = build_document_surface(index_spec, tmp_path)
    meta = stamp_standard_meta({}, schema_version=LAYOUT_VERSION, audience="eng-guide")
    meta = set_fingerprint(meta, surface.surface_hash())
    body = (
        "# Docs index\n\n> The collection.\n\n"
        f"<!-- CDM:BEGIN idx -->\n{region}\n<!-- CDM:END idx -->\n"
    )
    (tmp_path / "docs/index.md").write_text(render_doc(meta, body), encoding="utf-8")
    return cfg


def test_index_region_starts_clean(tmp_path: Path) -> None:
    cfg = _seed_in_sync(tmp_path)
    assert Monitor(cfg, tmp_path).check().ok


def test_index_drifts_when_a_sibling_is_repurposed(tmp_path: Path) -> None:
    cfg = _seed_in_sync(tmp_path)
    # Change a sibling's purpose -> the index table row is now stale.
    (tmp_path / "docs/alpha.md").write_text(
        _doc("alpha", "Alpha Guide", "A COMPLETELY different purpose."),
        encoding="utf-8",
    )
    report = Monitor(cfg, tmp_path).check()
    assert not report.ok
    assert any(d.region_id == "idx" for d in report.drifts)


def test_monitor_apply_self_heals_the_index(tmp_path: Path) -> None:
    cfg = _seed_in_sync(tmp_path)
    (tmp_path / "docs/alpha.md").write_text(
        _doc("alpha", "Alpha Guide", "A COMPLETELY different purpose."),
        encoding="utf-8",
    )
    mon = Monitor(cfg, tmp_path, now=lambda: "2026-06-02T00:00:00+00:00")
    result = mon.run(apply=True)
    assert result.records  # a verdict was recorded for review
    assert mon.check().ok  # fully self-healed
    assert "different purpose" in (tmp_path / "docs/index.md").read_text()


def test_render_index_handles_missing_file_and_no_title(tmp_path: Path) -> None:
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(
                id="index",
                path="index.md",
                audience=Audience.ENG_GUIDE,
                region_keys=("idx",),
            ),
            DocumentSpec(id="ghost", path="ghost.md", audience=Audience.ENG_GUIDE),
            DocumentSpec(id="plain", path="plain.md", audience=Audience.ENG_GUIDE),
        ),
        region_templates={"idx": _TEMPLATE},
    )
    (tmp_path / "plain.md").write_text("no heading here\njust text\n", encoding="utf-8")
    body = render_index(_TEMPLATE, cfg.documents[0], cfg, tmp_path)
    assert "[ghost](ghost.md)" in body  # missing file -> title falls back to doc_id
    assert "[plain](plain.md)" in body  # no H1 -> title falls back to doc_id
