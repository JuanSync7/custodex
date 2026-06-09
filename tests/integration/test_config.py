"""CDM-01 — tests for config models, loader, and template (K0, K8, K10).

Features: FEAT-CONFIG-001, FEAT-CONFIG-002, FEAT-CONFIG-004, FEAT-CONFIG-005
Features: FEAT-CONFIG-007, FEAT-CONFIG-008, FEAT-CONFIG-009
Features: FEAT-CONFIG-010, FEAT-CONFIG-012
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from code_doc_monitor import inventory
from code_doc_monitor.config import (
    CONFIG_TEMPLATE,
    Audience,
    BackendConfig,
    CentralConfig,
    CoverageConfig,
    DocumentSpec,
    MonitorConfig,
    RegionMode,
    WaiverEntry,
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


# --------------------------------------------------------------------------
# A-04 — coverage: section + waivers
# --------------------------------------------------------------------------


def test_coverage_defaults_match_inventory() -> None:
    # config inlines the scan-scope defaults (to avoid an import cycle); they
    # must stay in lock-step with inventory's own defaults.
    assert CoverageConfig().include == inventory.DEFAULT_INCLUDE
    assert CoverageConfig().exclude == inventory.DEFAULT_EXCLUDE


def test_coverage_defaults_when_section_absent(tmp_path: Path) -> None:
    # An old config WITHOUT a coverage: block still loads (additive — K6).
    cfg = load_config(_write_yaml(tmp_path, VALID_CONFIG))
    assert cfg.coverage == CoverageConfig()
    assert cfg.coverage.include == inventory.DEFAULT_INCLUDE
    assert cfg.coverage.exclude == inventory.DEFAULT_EXCLUDE
    assert cfg.coverage.waive == ()


def test_coverage_section_round_trips_yaml(tmp_path: Path) -> None:
    data = dict(
        VALID_CONFIG,
        coverage={
            "include": ["src/**/*.py"],
            "exclude": ["**/tests/**"],
            "waive": [
                {"path": "src/legacy/*.py", "reason": "deprecated, scheduled removal"},
                {
                    "path": "src/app.py",
                    "symbol": "_internal",
                    "reason": "internal helper",
                },
            ],
        },
    )
    cfg = load_config(_write_yaml(tmp_path, data))
    cov = cfg.coverage
    assert cov.include == ("src/**/*.py",)
    assert cov.exclude == ("**/tests/**",)
    assert cov.waive == (
        WaiverEntry(path="src/legacy/*.py", reason="deprecated, scheduled removal"),
        WaiverEntry(path="src/app.py", symbol="_internal", reason="internal helper"),
    )
    # whole-file waiver has symbol=None
    assert cov.waive[0].symbol is None


def test_coverage_section_round_trips_json(tmp_path: Path) -> None:
    data = dict(
        VALID_CONFIG,
        coverage={
            "waive": [{"path": "x/*.py", "reason": "r"}],
        },
    )
    cfg = load_config(_write_json(tmp_path, data))
    assert cfg.coverage.waive == (WaiverEntry(path="x/*.py", reason="r"),)
    # include/exclude fall back to the inventory defaults
    assert cfg.coverage.include == inventory.DEFAULT_INCLUDE


def test_waiver_missing_reason_raises_config_error(tmp_path: Path) -> None:
    bad = dict(VALID_CONFIG, coverage={"waive": [{"path": "x/*.py"}]})
    with pytest.raises(ConfigError):
        load_config(_write_yaml(tmp_path, bad))


def test_unknown_key_under_coverage_raises_config_error(tmp_path: Path) -> None:
    bad = dict(VALID_CONFIG, coverage={"waive": [], "surprise": 1})
    with pytest.raises(ConfigError):
        load_config(_write_yaml(tmp_path, bad))


def test_unknown_key_under_waiver_raises_config_error(tmp_path: Path) -> None:
    bad = dict(
        VALID_CONFIG,
        coverage={"waive": [{"path": "x/*.py", "reason": "r", "wat": 1}]},
    )
    with pytest.raises(ConfigError):
        load_config(_write_yaml(tmp_path, bad))


def test_coverage_models_frozen() -> None:
    w = WaiverEntry(path="x/*.py", reason="r")
    with pytest.raises(ValidationError):
        w.reason = "z"  # type: ignore[misc]
    c = CoverageConfig()
    with pytest.raises(ValidationError):
        c.waive = ()  # type: ignore[misc]


def test_template_round_trips_with_coverage_section(tmp_path: Path) -> None:
    # The commented coverage: example in the template still round-trips, and the
    # defaulted coverage config is present.
    p = tmp_path / "cdmon.yaml"
    write_template(p)
    cfg = load_config(p)
    assert isinstance(cfg.coverage, CoverageConfig)
    assert "coverage:" in CONFIG_TEMPLATE
    assert "waive:" in CONFIG_TEMPLATE


# --------------------------------------------------------------------------
# B-01 — region authority modes (schema + validation + accessor)
# --------------------------------------------------------------------------


def test_region_mode_enum_values() -> None:
    # The four declared authority modes (str-valued for clean YAML/JSON).
    assert RegionMode.GENERATED == "generated"
    assert RegionMode.LLM == "llm"
    assert RegionMode.HUMAN == "human"
    assert RegionMode.LLM_SEEDED == "llm-seeded"
    assert {m.value for m in RegionMode} == {
        "generated",
        "llm",
        "human",
        "llm-seeded",
    }


def test_region_modes_round_trips_yaml(tmp_path: Path) -> None:
    data = json.loads(json.dumps(VALID_CONFIG))
    data["documents"][0]["region_keys"] = ["symbols", "intro"]
    data["documents"][0]["region_modes"] = {"symbols": "generated", "intro": "human"}
    cfg = load_config(_write_yaml(tmp_path, data))
    ug = cfg.documents[0]
    assert ug.region_modes == {
        "symbols": RegionMode.GENERATED,
        "intro": RegionMode.HUMAN,
    }


def test_region_modes_round_trips_json(tmp_path: Path) -> None:
    data = json.loads(json.dumps(VALID_CONFIG))
    data["documents"][0]["region_keys"] = ["symbols", "notes"]
    data["documents"][0]["region_modes"] = {"notes": "llm-seeded"}
    cfg = load_config(_write_json(tmp_path, data))
    assert cfg.documents[0].region_modes == {"notes": RegionMode.LLM_SEEDED}


def test_region_modes_absent_defaults_to_generated(tmp_path: Path) -> None:
    # An old config WITHOUT region_modes still loads (additive — K6).
    cfg = load_config(_write_yaml(tmp_path, VALID_CONFIG))
    ug = cfg.documents[0]
    assert ug.region_modes == {}
    # mode_for returns GENERATED for any region when unspecified.
    assert ug.mode_for("symbols") is RegionMode.GENERATED
    assert ug.mode_for("anything") is RegionMode.GENERATED


def test_mode_for_returns_declared_mode() -> None:
    spec = DocumentSpec(
        id="d",
        path="docs/d.md",
        audience=Audience.ENG_GUIDE,
        region_keys=("a", "b"),
        region_modes={"a": RegionMode.HUMAN},
    )
    assert spec.mode_for("a") is RegionMode.HUMAN
    # a declared region with no mode falls back to GENERATED.
    assert spec.mode_for("b") is RegionMode.GENERATED


def test_unknown_region_mode_raises_config_error(tmp_path: Path) -> None:
    bad = json.loads(json.dumps(VALID_CONFIG))
    bad["documents"][0]["region_modes"] = {"symbols": "telepathy"}
    with pytest.raises(ConfigError):
        load_config(_write_yaml(tmp_path, bad))


def test_region_mode_for_undeclared_region_raises_config_error(
    tmp_path: Path,
) -> None:
    # K8: a region_modes key naming a region not in region_keys is loud.
    bad = json.loads(json.dumps(VALID_CONFIG))
    bad["documents"][0]["region_keys"] = ["symbols"]
    bad["documents"][0]["region_modes"] = {"ghost": "human"}
    with pytest.raises(ConfigError):
        load_config(_write_yaml(tmp_path, bad))


def test_region_modes_frozen() -> None:
    spec = DocumentSpec(
        id="d",
        path="docs/d.md",
        audience=Audience.ENG_GUIDE,
        region_keys=("a",),
        region_modes={"a": RegionMode.HUMAN},
    )
    with pytest.raises(ValidationError):
        spec.region_modes = {}  # type: ignore[misc]


def test_template_round_trips_with_region_modes_example(tmp_path: Path) -> None:
    p = tmp_path / "cdmon.yaml"
    write_template(p)
    cfg = load_config(p)
    assert isinstance(cfg, MonitorConfig)
    assert "region_modes:" in CONFIG_TEMPLATE
