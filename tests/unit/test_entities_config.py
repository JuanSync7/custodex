"""AGT-01: the ``entities:`` config block (`EntitiesConfig`, additive K6).

Pins the K6 contract for the mention layer's knobs: defaults (a pre-AGT config
loads unchanged), the single-file parse, and the index.yaml → merged-config
lift in the dir layout. Target noise enters through config, never the engine
(K0).

Features: FEAT-ENTITIES-002
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from custodex.config import (
    Audience,
    DocumentSpec,
    EntitiesConfig,
    MonitorConfig,
    load_bundle,
    load_config,
)


def test_entities_config_defaults() -> None:
    """Defaults: no stoplist, no env prefixes (⇒ no ENV_VAR mentions at all)."""
    cfg = EntitiesConfig()
    assert cfg.ignore == ()
    assert cfg.env_prefixes == ()


def test_entities_config_forbids_extra_keys() -> None:
    """An unknown key is a loud error (K8)."""
    with pytest.raises(ValidationError):
        EntitiesConfig(bogus=True)  # type: ignore[call-arg]


def test_monitor_config_has_default_entities() -> None:
    """``MonitorConfig.entities`` defaults so a pre-AGT config still loads (K6)."""
    cfg = MonitorConfig(
        documents=(DocumentSpec(id="d", path="d.md", audience=Audience.ENG_GUIDE),)
    )
    assert cfg.entities == EntitiesConfig()


def test_entities_block_parses_from_single_file(tmp_path: Path) -> None:
    """The single-file ``entities:`` block round-trips into the model."""
    cfg_text = (
        'version: "1.0.0"\n'
        "root: .\n"
        "entities:\n"
        "  ignore:\n"
        "    - cdx\n"
        "  env_prefixes:\n"
        "    - CDMON_\n"
        "documents:\n"
        "  - id: api\n"
        "    path: docs/api.md\n"
        "    audience: eng-guide\n"
    )
    p = tmp_path / "cdmon.yaml"
    p.write_text(cfg_text, encoding="utf-8")
    cfg = load_config(p)
    assert cfg.entities == EntitiesConfig(ignore=("cdx",), env_prefixes=("CDMON_",))


def test_entities_block_lifts_from_index_yaml(tmp_path: Path) -> None:
    """The dir layout lifts index.yaml's ``entities:`` into the merged config."""
    cfg_dir = tmp_path / "config" / "cdmon"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "index.yaml").write_text(
        '---\ncdmon-config-version: "2.0.0"\nrepo: t\ngenerated-by: cdx\n'
        'updated: "2026-07-02"\n---\nroot: "../.."\nversion: "2.0.0"\n'
        "backend: {kind: mock}\n"
        "entities:\n"
        "  env_prefixes:\n"
        "    - CDMON_\n"
        "units:\n  - file: core.yaml\n",
        encoding="utf-8",
    )
    (cfg_dir / "core.yaml").write_text(
        '---\ncdmon-config-version: "2.0.0"\nunit: core\ntitle: t\nowner: eng\n'
        'created: "2026-07-02"\nupdated: "2026-07-02"\n---\n'
        "dir-covered:\n  - src\n"
        "source-files-format:\n  - .py\n"
        "documents:\n"
        "  - id: api\n"
        "    path: docs/api.md\n"
        "    audience: eng-guide\n",
        encoding="utf-8",
    )
    bundle = load_bundle(cfg_dir)
    assert bundle.config.entities == EntitiesConfig(env_prefixes=("CDMON_",))
