"""CDM-01 — tests for config models, loader, and template (K0, K8, K10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from code_doc_monitor.config import (
    CONFIG_TEMPLATE,
    Audience,
    BackendConfig,
    CentralConfig,
    MonitorConfig,
    load_config,
    write_template,
)
from code_doc_monitor.errors import CodeDocMonitorError, ConfigError

# A minimal but complete config dict used across loader tests.
VALID_CONFIG: dict = {
    "version": "1.0.0",
    "root": "src",
    "documents": [
        {
            "id": "user-guide",
            "path": "docs/user.md",
            "audience": "user-guide",
            "code_refs": [
                {"path": "src/app.py"},
                {"path": "src/api.py", "symbols": ["run", "Client"]},
                {"path": "src/util.py", "lines": [[10, 20], [30, 40]]},
            ],
            "region_keys": ["symbols"],
        },
        {
            "id": "eng-guide",
            "path": "docs/eng.md",
            "audience": "eng-guide",
            "code_refs": [
                {"path": "src/api.py", "names": ["DEFAULT_TIMEOUT"]},
            ],
        },
    ],
    "backend": {"kind": "claude-code", "timeout_s": 60},
    "central": {"sink": "file", "path": "central.jsonl"},
    "apply_default": True,
}


def _write_yaml(tmp_path: Path, data: dict, name: str = "cdmon.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _write_json(tmp_path: Path, data: dict, name: str = "cdmon.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_valid_yaml_loads(tmp_path: Path) -> None:
    cfg = load_config(_write_yaml(tmp_path, VALID_CONFIG))
    assert isinstance(cfg, MonitorConfig)
    assert cfg.version == "1.0.0"
    assert cfg.root == "src"
    assert len(cfg.documents) == 2
    ug = cfg.documents[0]
    assert ug.id == "user-guide"
    assert ug.audience is Audience.USER_GUIDE
    assert ug.path == "docs/user.md"
    assert ug.region_keys == ("symbols",)
    # whole-file ref has empty selectors
    assert ug.code_refs[0].path == "src/app.py"
    assert ug.code_refs[0].symbols == ()
    assert ug.code_refs[0].lines == ()
    assert ug.code_refs[0].names == ()
    # symbols selector
    assert ug.code_refs[1].symbols == ("run", "Client")
    # lines selector is a tuple of tuples
    assert ug.code_refs[2].lines == ((10, 20), (30, 40))
    # eng-guide doc + names selector
    eg = cfg.documents[1]
    assert eg.audience is Audience.ENG_GUIDE
    assert eg.code_refs[0].names == ("DEFAULT_TIMEOUT",)
    # backend/central overrides
    assert cfg.backend.kind == "claude-code"
    assert cfg.backend.timeout_s == 60
    assert cfg.central.sink == "file"
    assert cfg.central.path == "central.jsonl"
    assert cfg.apply_default is True


def test_valid_json_loads_same_as_yaml(tmp_path: Path) -> None:
    cfg = load_config(_write_json(tmp_path, VALID_CONFIG))
    assert isinstance(cfg, MonitorConfig)
    assert len(cfg.documents) == 2
    assert cfg.documents[0].audience is Audience.USER_GUIDE
    assert cfg.documents[1].code_refs[0].names == ("DEFAULT_TIMEOUT",)


def test_yml_suffix_is_accepted(tmp_path: Path) -> None:
    cfg = load_config(_write_yaml(tmp_path, VALID_CONFIG, name="cdmon.yml"))
    assert isinstance(cfg, MonitorConfig)


def test_defaults_applied(tmp_path: Path) -> None:
    minimal = {
        "documents": [
            {
                "id": "d",
                "path": "docs/d.md",
                "audience": "eng-guide",
                "code_refs": [{"path": "a.py"}],
            }
        ]
    }
    cfg = load_config(_write_yaml(tmp_path, minimal))
    assert cfg.version == "1.0.0"
    assert cfg.root == "."
    assert cfg.backend == BackendConfig()
    assert cfg.backend.kind == "mock"
    assert cfg.backend.timeout_s == 120
    assert cfg.backend.model is None
    assert cfg.backend.command is None
    assert cfg.backend.extra == {}
    assert cfg.central == CentralConfig()
    assert cfg.central.sink == "none"
    assert cfg.apply_default is False
    assert cfg.documents[0].region_keys == ()


def test_unknown_top_level_key_raises_config_error(tmp_path: Path) -> None:
    bad = dict(VALID_CONFIG, surprise="boom")
    with pytest.raises(ConfigError):
        load_config(_write_yaml(tmp_path, bad))


def test_unknown_nested_key_raises_config_error(tmp_path: Path) -> None:
    bad = json.loads(json.dumps(VALID_CONFIG))
    bad["documents"][0]["code_refs"][0]["wat"] = 1
    with pytest.raises(ConfigError):
        load_config(_write_yaml(tmp_path, bad))


def test_invalid_audience_raises_config_error(tmp_path: Path) -> None:
    bad = json.loads(json.dumps(VALID_CONFIG))
    bad["documents"][0]["audience"] = "marketing"
    with pytest.raises(ConfigError):
        load_config(_write_yaml(tmp_path, bad))


def test_invalid_backend_kind_raises_config_error(tmp_path: Path) -> None:
    bad = json.loads(json.dumps(VALID_CONFIG))
    bad["backend"]["kind"] = "telepathy"
    with pytest.raises(ConfigError):
        load_config(_write_yaml(tmp_path, bad))


def test_malformed_yaml_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "broken.yaml"
    p.write_text("documents: [unterminated\n  - : :\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_malformed_json_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_non_mapping_top_level_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_unknown_suffix_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "cdmon.toml"
    p.write_text("documents = []\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_config_error_is_subclass_of_base() -> None:
    assert issubclass(ConfigError, CodeDocMonitorError)


def test_config_is_frozen(tmp_path: Path) -> None:
    cfg = load_config(_write_yaml(tmp_path, VALID_CONFIG))
    with pytest.raises(ValidationError):
        cfg.version = "9.9.9"  # type: ignore[misc]


def test_template_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "cdmon.yaml"
    write_template(p)
    assert p.exists()
    cfg = load_config(p)
    assert isinstance(cfg, MonitorConfig)
    # at least two documents covering both audiences
    assert len(cfg.documents) >= 2
    audiences = {d.audience for d in cfg.documents}
    assert Audience.USER_GUIDE in audiences
    assert Audience.ENG_GUIDE in audiences
    # template demonstrates whole-file, symbols, and lines selectors
    all_refs = [r for d in cfg.documents for r in d.code_refs]
    assert any(r.symbols == () and r.lines == () and r.names == () for r in all_refs)
    assert any(r.symbols for r in all_refs)
    assert any(r.lines for r in all_refs)


def test_write_template_unwritable_path_raises_config_error(tmp_path: Path) -> None:
    # writing into a path whose parent is a file (not a dir) fails at the OS level
    not_a_dir = tmp_path / "afile"
    not_a_dir.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError):
        write_template(not_a_dir / "cdmon.yaml")


def test_template_is_documented_yaml() -> None:
    # comments make it a *documented* starter config
    assert "#" in CONFIG_TEMPLATE
    assert "user-guide" in CONFIG_TEMPLATE
    assert "eng-guide" in CONFIG_TEMPLATE
