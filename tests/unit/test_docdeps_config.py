"""EPIC B (B-01): doc↔doc dependency config models (config.py, additive K6).

Pins the K6 contract for Pillar B's *declaration* layer (the edge lives in config,
the source of truth K2): ``DocEdge`` / ``DocEdgeType`` / ``DocDepsConfig``, the
``DocumentSpec.depends_on`` field, the loud validators (self-edge, duplicate
upstream, unknown upstream id), and the unit-file round-trip. No detection here —
that is B-03/B-04.

Features: FEAT-DOCDEPS-001
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from custodex.config import (
    Audience,
    DocDepsConfig,
    DocEdge,
    DocEdgeType,
    DocumentSpec,
    MonitorConfig,
    UnitFile,
    UnitFrontmatter,
    dump_unit_file,
    load_config,
    load_unit_file,
)
from custodex.errors import ConfigError

_FM = (
    "---\n"
    'cdmon-config-version: "2.0.0"\n'
    "unit: core\n"
    'title: "t"\n'
    "owner: o\n"
    'created: "2026-06-07"\n'
    'updated: "2026-06-07"\n'
    "---\n"
)


def _write_unit(tmp_path: Path, body: str, stem: str = "core") -> Path:
    p = tmp_path / f"{stem}.yaml"
    p.write_text(_FM + body, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# DocEdge / DocEdgeType / DocDepsConfig
# --------------------------------------------------------------------------- #
def test_doc_edge_defaults_to_depends() -> None:
    """A ``DocEdge`` defaults ``type`` to ``depends`` and ``note`` to None."""
    edge = DocEdge(doc="upstream")
    assert edge.type is DocEdgeType.DEPENDS
    assert edge.note is None


def test_doc_edge_forbids_extra_keys() -> None:
    """An unknown key on a ``DocEdge`` is a loud error (K8)."""
    with pytest.raises(ValidationError):
        DocEdge(doc="u", bogus="x")  # type: ignore[call-arg]


def test_docdeps_config_defaults() -> None:
    """``DocDepsConfig`` defaults: enabled + gating on, depends type, no auto-infer."""
    cfg = DocDepsConfig()
    assert cfg.enabled is True
    assert cfg.gate is True
    assert cfg.default_type is DocEdgeType.DEPENDS
    assert cfg.infer_from_links is False


def test_monitor_config_has_default_docdeps() -> None:
    """``MonitorConfig.docdeps`` defaults so a pre-EPIC-B config still loads (K6)."""
    cfg = MonitorConfig(
        documents=(DocumentSpec(id="d", path="d.md", audience=Audience.ENG_GUIDE),)
    )
    assert cfg.docdeps == DocDepsConfig()


# --------------------------------------------------------------------------- #
# DocumentSpec.depends_on — default + parse + per-doc validators
# --------------------------------------------------------------------------- #
def test_depends_on_defaults_empty() -> None:
    """``depends_on`` defaults to the empty tuple (additive, K6)."""
    doc = DocumentSpec(id="d", path="d.md", audience=Audience.ENG_GUIDE)
    assert doc.depends_on == ()


def test_depends_on_loads_from_unit_file(tmp_path: Path) -> None:
    """A ``documents[].depends_on`` list parses into ``DocumentSpec.depends_on``."""
    body = (
        "dir-covered:\n  - custodex\n"
        "source-files-format:\n  - .py\n"
        "documents:\n"
        "  - id: overview\n"
        "    path: docs/overview.md\n"
        "    audience: eng-guide\n"
        "  - id: glossary\n"
        "    path: docs/glossary.md\n"
        "    audience: eng-guide\n"
        "  - id: api\n"
        "    path: docs/api.md\n"
        "    audience: eng-guide\n"
        "    depends_on:\n"
        "      - doc: overview\n"
        "        type: refines\n"
        "      - doc: glossary\n"
        '        note: "terms"\n'
    )
    unit = load_unit_file(_write_unit(tmp_path, body))
    api = next(d for d in unit.documents if d.id == "api")
    assert api.depends_on == (
        DocEdge(doc="overview", type=DocEdgeType.REFINES),
        DocEdge(doc="glossary", note="terms"),
    )


def test_self_edge_is_loud(tmp_path: Path) -> None:
    """A document declaring it depends on itself is a ConfigError (K8)."""
    body = (
        "dir-covered:\n  - custodex\n"
        "source-files-format:\n  - .py\n"
        "documents:\n"
        "  - id: api\n"
        "    path: docs/api.md\n"
        "    audience: eng-guide\n"
        "    depends_on:\n"
        "      - doc: api\n"
    )
    with pytest.raises(ConfigError) as exc:
        load_unit_file(_write_unit(tmp_path, body))
    assert "itself" in str(exc.value) or "self" in str(exc.value).lower()


def test_duplicate_upstream_edge_is_loud(tmp_path: Path) -> None:
    """Two edges to the same upstream id in one document → ConfigError (K8)."""
    body = (
        "dir-covered:\n  - custodex\n"
        "source-files-format:\n  - .py\n"
        "documents:\n"
        "  - id: overview\n"
        "    path: docs/overview.md\n"
        "    audience: eng-guide\n"
        "  - id: api\n"
        "    path: docs/api.md\n"
        "    audience: eng-guide\n"
        "    depends_on:\n"
        "      - doc: overview\n"
        "      - doc: overview\n"
    )
    with pytest.raises(ConfigError) as exc:
        load_unit_file(_write_unit(tmp_path, body))
    assert "overview" in str(exc.value)


# --------------------------------------------------------------------------- #
# Cross-reference validation — the upstream id must name a real document
# --------------------------------------------------------------------------- #
def test_unknown_upstream_id_is_loud(tmp_path: Path) -> None:
    """``depends_on`` naming a doc id that does not exist → ConfigError (K8)."""
    cfg_text = (
        'version: "1.0.0"\n'
        "root: .\n"
        "documents:\n"
        "  - id: api\n"
        "    path: docs/api.md\n"
        "    audience: eng-guide\n"
        "    depends_on:\n"
        "      - doc: nope\n"
    )
    p = tmp_path / "cdmon.yaml"
    p.write_text(cfg_text, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert "nope" in str(exc.value)


def test_known_upstream_id_loads(tmp_path: Path) -> None:
    """A ``depends_on`` to a real sibling document loads cleanly."""
    cfg_text = (
        'version: "1.0.0"\n'
        "root: .\n"
        "documents:\n"
        "  - id: overview\n"
        "    path: docs/overview.md\n"
        "    audience: eng-guide\n"
        "  - id: api\n"
        "    path: docs/api.md\n"
        "    audience: eng-guide\n"
        "    depends_on:\n"
        "      - doc: overview\n"
    )
    p = tmp_path / "cdmon.yaml"
    p.write_text(cfg_text, encoding="utf-8")
    cfg = load_config(p)
    api = next(d for d in cfg.documents if d.id == "api")
    assert api.depends_on == (DocEdge(doc="overview"),)


# --------------------------------------------------------------------------- #
# Round-trip through the unit serializer (dump → load == identity)
# --------------------------------------------------------------------------- #
def test_depends_on_round_trips(tmp_path: Path) -> None:
    """``load_unit_file(dump_unit_file(u)) == u`` with depends_on present (K7)."""
    fm = UnitFrontmatter(
        **{
            "cdmon-config-version": "2.0.0",
            "unit": "core",
            "title": "core",
            "owner": "team",
            "created": "2026-06-07",
            "updated": "2026-06-08",
        }
    )
    docs = (
        DocumentSpec(
            id="overview", path="docs/overview.md", audience=Audience.ENG_GUIDE
        ),
        DocumentSpec(
            id="api",
            path="docs/api.md",
            audience=Audience.ENG_GUIDE,
            depends_on=(
                DocEdge(doc="overview", type=DocEdgeType.REFINES, note="elaborates"),
            ),
        ),
    )
    unit = UnitFile(
        frontmatter=fm,
        dir_covered=("custodex",),
        source_files_format=(".py",),
        documents=docs,
    )
    text = dump_unit_file(unit, now="2026-06-08")
    reloaded = load_unit_file_from_text(tmp_path, text)
    assert reloaded.documents == docs


def load_unit_file_from_text(tmp_path: Path, text: str) -> UnitFile:
    p = tmp_path / "core.yaml"
    p.write_text(text, encoding="utf-8")
    return load_unit_file(p)
