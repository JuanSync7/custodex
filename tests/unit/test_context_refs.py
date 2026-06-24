"""EDITOR E-01: the additive ``context_refs`` unit-file key (schema only).

These tests pin the K6 contract: ``context_refs`` loads from a unit file into
:class:`DocumentSpec`, a duplicate path within one document is a loud
:class:`ConfigError`, and ``context_refs`` NEVER changes coverage (it is
generation context, not a documented surface).

Features: FEAT-CONFIG-003, FEAT-CONFIGV2-002, FEAT-CONFIGV2-006
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from custodex.config import (
    Audience,
    ContextRef,
    DocumentSpec,
    effective_coverage,
    load_bundle,
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


def test_context_refs_loads_into_document_spec(tmp_path: Path) -> None:
    """A ``documents[].context_refs`` list parses into ``DocumentSpec.context_refs``."""
    body = (
        "dir-covered:\n  - custodex\n"
        "source-files-format:\n  - .py\n"
        "documents:\n"
        "  - id: foundation\n"
        "    path: docs/foundation.md\n"
        "    audience: eng-guide\n"
        "    code_refs:\n      - path: custodex/config.py\n"
        "    context_refs:\n"
        "      - path: docs/api/index.md\n"
        '        note: "the landing page"\n'
        "      - path: custodex/errors.py\n"
    )
    unit = load_unit_file(_write_unit(tmp_path, body))
    doc = unit.documents[0]
    assert doc.context_refs == (
        ContextRef(path="docs/api/index.md", note="the landing page"),
        ContextRef(path="custodex/errors.py", note=None),
    )


def test_context_ref_note_is_optional() -> None:
    """``note`` defaults to None and ``extra`` keys are forbidden (K8)."""
    assert ContextRef(path="x.md").note is None
    with pytest.raises(ValidationError):
        ContextRef(path="x.md", bogus="y")  # type: ignore[call-arg]


def test_default_context_refs_is_empty() -> None:
    """``context_refs`` defaults to the empty tuple (additive, K6)."""
    doc = DocumentSpec(id="d", path="d.md", audience=Audience.ENG_GUIDE)
    assert doc.context_refs == ()


def test_duplicate_context_refs_path_is_loud(tmp_path: Path) -> None:
    """Two ``context_refs`` with the same path in one document → ConfigError (K8)."""
    body = (
        "dir-covered:\n  - custodex\n"
        "source-files-format:\n  - .py\n"
        "documents:\n"
        "  - id: foundation\n"
        "    path: docs/foundation.md\n"
        "    audience: eng-guide\n"
        "    context_refs:\n"
        "      - path: docs/api/index.md\n"
        "      - path: docs/api/index.md\n"
    )
    with pytest.raises(ConfigError) as exc:
        load_unit_file(_write_unit(tmp_path, body))
    assert "context_refs" in str(exc.value)
    assert "docs/api/index.md" in str(exc.value)


def _bundle_dir(tmp_path: Path, unit_body: str) -> Path:
    """Materialize a minimal config/cdmon dir with one unit + index + ignore."""
    cfg = tmp_path / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "core.yaml").write_text(_FM + unit_body, encoding="utf-8")
    (cfg / "index.yaml").write_text(
        "---\n"
        'cdmon-config-version: "2.0.0"\n'
        'repo: "demo"\n'
        "generated-by: cdx\n"
        'updated: "2026-06-07"\n'
        "---\n"
        'root: "../.."\n'
        "units:\n  - file: core.yaml\n",
        encoding="utf-8",
    )
    # Make custodex a real dir under repo root so coverage globs resolve.
    (tmp_path / "custodex").mkdir()
    return cfg


def test_context_refs_do_not_affect_coverage(tmp_path: Path) -> None:
    """A doc WITH context_refs yields the same effective_coverage as one WITHOUT.

    ``context_refs`` is generation context only — never a documented surface, so
    the derived coverage include/exclude/waive must be byte-identical.
    """
    without = (
        "dir-covered:\n  - custodex\n"
        "source-files-format:\n  - .py\n"
        "documents:\n"
        "  - id: foundation\n"
        "    path: docs/foundation.md\n"
        "    audience: eng-guide\n"
        "    code_refs:\n      - path: custodex/config.py\n"
    )
    with_refs = without + (
        "    context_refs:\n"
        "      - path: docs/api/index.md\n"
        "      - path: custodex/errors.py\n"
    )

    cfg_a = _bundle_dir(tmp_path / "a", without)
    cfg_b = _bundle_dir(tmp_path / "b", with_refs)
    bundle_a = load_bundle(cfg_a)
    bundle_b = load_bundle(cfg_b)

    root_a = (tmp_path / "a").resolve()
    root_b = (tmp_path / "b").resolve()
    assert effective_coverage(bundle_a, root_a) == effective_coverage(bundle_b, root_b)
    # And the merged MonitorConfig.coverage is identical too.
    assert bundle_a.config.coverage == bundle_b.config.coverage
