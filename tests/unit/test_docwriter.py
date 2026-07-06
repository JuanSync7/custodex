"""AGT-05 — the doc-writer agent (`docwriter.py`).

draft_document = mechanical scaffold + backend-authored prose (mock =
deterministic, K4/K10); write_and_register = comment-preserving splice into
the unit YAML + the authored file, born in-sync (the next check is green).

Features: FEAT-DOCWRITER-001
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.backends import BackendResult
from custodex.config import Audience, load_bundle
from custodex.docwriter import (
    build_doc_spec,
    draft_document,
    proposed_doc_id,
    unit_snippet,
    write_and_register,
)
from custodex.drift import detect as detect_drift
from custodex.errors import ConfigError
from custodex.extract import build_document_surface
from custodex.manifest import parse_text, regions
from custodex.schema import ProposedFix, Verdict

GAMMA = 'def turbo_boost(x):\n    """Boost."""\n    return x * 2\n'

_UNIT = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "core docs"
owner: eng
created: "2026-07-01"
updated: "2026-07-01"
---
# Hand comment: must survive write-doc registration.
dir-covered:
  - src
source-files-format:
  - .py
documents:
  - id: existing
    path: docs/existing.md
    audience: eng-guide
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


def _setup(tmp_path: Path) -> Path:
    cfg_dir = tmp_path / "config" / "cdmon"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "index.yaml").write_text(_INDEX, encoding="utf-8")
    (cfg_dir / "core.yaml").write_text(_UNIT, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "gamma.py").write_text(GAMMA, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "existing.md").write_text("# E\n\nProse.\n", "utf-8")
    return cfg_dir


def _spec():
    return build_doc_spec(
        doc_id="src-gamma",
        path="docs/src-gamma.md",
        audience=Audience.ENG_GUIDE,
        code_refs=("src/gamma.py",),
    )


def test_proposed_doc_id_from_path() -> None:
    assert proposed_doc_id("pkg/sub/mod.py") == "pkg-sub-mod"
    assert proposed_doc_id("./alpha.py") == "alpha"


def test_draft_has_authored_purpose_and_overview(tmp_path: Path) -> None:
    _setup(tmp_path)
    spec = _spec()
    surface = build_document_surface(spec, tmp_path)
    text = draft_document(spec, surface)
    assert "> TODO" not in text
    assert "1 public symbol(s)" in text
    body_regions = regions(parse_text(text))
    assert "turbo_boost" in body_regions["symbols"]
    # The mock's deterministic authored prose replaced the TODO placeholder.
    assert "TODO" not in body_regions["overview"]
    assert "turbo_boost" in body_regions["overview"]


def test_draft_is_deterministic_on_mock_path(tmp_path: Path) -> None:
    _setup(tmp_path)
    spec = _spec()
    surface = build_document_surface(spec, tmp_path)
    assert draft_document(spec, surface) == draft_document(spec, surface)


def test_non_fix_backend_degrades_to_placeholder(tmp_path: Path) -> None:
    _setup(tmp_path)
    spec = _spec()
    surface = build_document_surface(spec, tmp_path)

    class Escalator:
        def propose(self, req):
            return BackendResult(verdict=Verdict.ESCALATE, cause="no", fix=None)

    text = draft_document(spec, surface, backend=Escalator())
    assert "TODO: content for 'overview'" in text  # degraded, not crashed


def test_region_fix_without_body_also_degrades(tmp_path: Path) -> None:
    _setup(tmp_path)
    spec = _spec()
    surface = build_document_surface(spec, tmp_path)

    class NoBody:
        def propose(self, req):
            return BackendResult(
                verdict=Verdict.FIX,
                cause="x",
                fix=ProposedFix(
                    region_id="overview",
                    new_region_body=None,
                    new_doc_text=None,
                    rationale="r",
                ),
            )

    text = draft_document(spec, surface, backend=NoBody())
    assert "TODO: content for 'overview'" in text


class TestWriteAndRegister:
    def test_registers_writes_and_is_born_in_sync(self, tmp_path: Path) -> None:
        cfg_dir = _setup(tmp_path)
        doc_path = write_and_register(
            cfg_dir, unit="core", spec=_spec(), now="2026-07-02T10:00:00Z"
        )
        assert doc_path.is_file()
        unit_text = (cfg_dir / "core.yaml").read_text(encoding="utf-8")
        assert "# Hand comment: must survive write-doc registration." in unit_text
        assert "id: src-gamma" in unit_text
        assert 'updated: "2026-07-02"' in unit_text
        bundle = load_bundle(cfg_dir)
        # Born in sync: the freshly-written doc has ZERO drift (the other,
        # never-healed fixture doc may drift — filter to ours).
        report = detect_drift(bundle.config, cfg_dir)
        assert [d for d in report.drifts if d.doc_id == "src-gamma"] == []

    def test_duplicate_id_unknown_unit_and_existing_file_are_loud(
        self, tmp_path: Path
    ) -> None:
        cfg_dir = _setup(tmp_path)
        with pytest.raises(ConfigError, match="unknown unit"):
            write_and_register(cfg_dir, unit="ghost", spec=_spec(), now="2026-07-02")
        existing = build_doc_spec(
            doc_id="existing",
            path="docs/x.md",
            audience=Audience.ENG_GUIDE,
            code_refs=("src/gamma.py",),
        )
        with pytest.raises(ConfigError, match="already exists"):
            write_and_register(cfg_dir, unit="core", spec=existing, now="2026-07-02")
        clash = build_doc_spec(
            doc_id="fresh",
            path="docs/existing.md",
            audience=Audience.ENG_GUIDE,
            code_refs=("src/gamma.py",),
        )
        with pytest.raises(ConfigError, match="refusing to overwrite"):
            write_and_register(cfg_dir, unit="core", spec=clash, now="2026-07-02")

    def test_unit_without_documents_block_is_loud(self, tmp_path: Path) -> None:
        cfg_dir = _setup(tmp_path)
        broken = _UNIT.replace("documents:", "docs-wrong:")
        (cfg_dir / "core.yaml").write_text(broken, encoding="utf-8")
        with pytest.raises(ConfigError, match="documents"):
            write_and_register(cfg_dir, unit="core", spec=_spec(), now="2026-07-02")


def test_unit_snippet_shape() -> None:
    snippet = unit_snippet(_spec())
    assert snippet.startswith("  - id: src-gamma")
    assert "      overview: llm" in snippet
    assert "      - path: src/gamma.py" in snippet
