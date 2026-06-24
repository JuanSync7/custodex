"""N-01 — tests for the CONFIG-V2 ``config/cdmon/`` dir layout (K0, K8, K10).

Covers the front-matter splitter, the new alias-bearing models, the per-file
loaders, the merge into one :class:`MonitorConfig`, the :class:`ConfigBundle`
seam, loud typed failures, and CLI back-compat via ``_resolve_config``.

Features: FEAT-CONFIGV2-001, FEAT-CONFIGV2-002, FEAT-CONFIGV2-003
Features: FEAT-CONFIGV2-004, FEAT-CONFIGV2-005, FEAT-CONFIGV2-008
Features: FEAT-CONFIGV2-010
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from custodex.config import (
    Audience,
    ConfigBundle,
    IndexFile,
    MonitorConfig,
    _split_frontmatter,
    load_bundle,
    load_config_dir,
    load_index_file,
    load_unit_file,
    unit_for_path,
)
from custodex.errors import CodeDocMonitorError, ConfigError

# --------------------------------------------------------------------------- #
# Fixture builders: a REAL ``config/cdmon/`` tree under tmp_path.
# --------------------------------------------------------------------------- #

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: custodex
generated-by: cdx
updated: "2026-06-07"
---
root: "../.."
version: "2.0.0"
apply_default: true
backend: {kind: mock}
central: {sink: none}
region_templates:
  api-index:
    source: index
    columns:
      - {header: Doc, field: doc_id}
coverage:
  waive:
    - {path: "custodex/__init__.py", reason: "re-export aggregator"}
units:
  - file: foundation.yaml
  - file: agent-workflow.yaml
"""

_FOUNDATION_YAML = """\
---
cdmon-config-version: "2.0.0"
unit: foundation
title: "Foundation coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - custodex/config.py
source-files-format:
  - ".py"
documents:
  - id: config-guide
    path: docs/api/config.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: custodex/config.py
        symbols: [load_config]
  - id: errors-guide
    path: docs/api/errors.md
    audience: user-guide
    code_refs:
      - path: custodex/errors.py
"""

_AGENT_YAML = """\
---
cdmon-config-version: "2.0.0"
unit: agent-workflow
title: "Remediation agent coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - custodex/agent
source-files-format:
  - ".py"
documents:
  - id: agent-workflow
    path: docs/api/agent-workflow.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: custodex/agent/backend.py
      - path: custodex/agent/graph.py
"""


def _write_tree(
    base: Path,
    *,
    index: str = _INDEX_YAML,
    foundation: str = _FOUNDATION_YAML,
    agent: str = _AGENT_YAML,
) -> Path:
    """Materialize a config/cdmon/ tree and return the config dir."""
    d = base / "config" / "cdmon"
    d.mkdir(parents=True)
    (d / "index.yaml").write_text(index, encoding="utf-8")
    (d / "foundation.yaml").write_text(foundation, encoding="utf-8")
    (d / "agent-workflow.yaml").write_text(agent, encoding="utf-8")
    return d


# --------------------------------------------------------------------------- #
# Unit: front-matter splitter.
# --------------------------------------------------------------------------- #


def test_split_frontmatter_well_formed() -> None:
    """A leading fence yields the parsed mapping and the trailing body."""
    text = "---\na: 1\nb: two\n---\nbody line\nmore\n"
    meta, body = _split_frontmatter(text, Path("x.yaml"))
    assert meta == {"a": 1, "b": "two"}
    assert body == "body line\nmore\n"


def test_split_frontmatter_empty_block_is_empty_mapping() -> None:
    """An empty fence is a valid empty mapping (not an error)."""
    meta, body = _split_frontmatter("---\n---\nbody\n", Path("x.yaml"))
    assert meta == {}
    assert body == "body\n"


def test_split_frontmatter_comment_only_block_is_empty_mapping() -> None:
    """A comment-only fence (yaml -> None) normalizes to an empty mapping."""
    meta, body = _split_frontmatter("---\n# only a comment\n---\nbody\n", Path("x"))
    assert meta == {}
    assert body == "body\n"


def test_split_frontmatter_missing_fence_is_loud() -> None:
    """No fence → loud ConfigError (a dir-layout file MUST carry one)."""
    with pytest.raises(ConfigError, match="front-matter fence"):
        _split_frontmatter("no fence here\n", Path("x.yaml"))


def test_split_frontmatter_malformed_yaml_is_loud() -> None:
    """A malformed YAML block raises ConfigError."""
    with pytest.raises(ConfigError, match="Malformed YAML front matter"):
        _split_frontmatter("---\na: : :\n---\nbody\n", Path("x.yaml"))


def test_split_frontmatter_non_mapping_is_loud() -> None:
    """A non-mapping front matter (a list) raises ConfigError."""
    with pytest.raises(ConfigError, match="must be a mapping"):
        _split_frontmatter("---\n- a\n- b\n---\nbody\n", Path("x.yaml"))


# --------------------------------------------------------------------------- #
# Unit: model alias round-trip + field validation.
# --------------------------------------------------------------------------- #


def test_unit_file_alias_round_trip(tmp_path: Path) -> None:
    """Hyphenated YAML keys load into snake_case attrs (populate_by_name)."""
    d = _write_tree(tmp_path)
    unit = load_unit_file(d / "agent-workflow.yaml")
    assert unit.frontmatter.cdmon_config_version == "2.0.0"
    assert unit.frontmatter.unit == "agent-workflow"
    assert unit.dir_covered == ("custodex/agent",)
    assert unit.source_files_format == (".py",)
    assert unit.documents[0].id == "agent-workflow"


def test_index_file_alias_round_trip(tmp_path: Path) -> None:
    """index.yaml hyphenated keys + defaults load correctly."""
    d = _write_tree(tmp_path)
    index = load_index_file(d / "index.yaml")
    assert index.frontmatter.generated_by == "cdx"
    assert index.root == "../.."
    assert index.apply_default is True
    assert index.doc_style == "doc-style.yaml"  # default alias
    assert tuple(u.file for u in index.units) == (
        "foundation.yaml",
        "agent-workflow.yaml",
    )


def test_unit_bad_version_is_loud(tmp_path: Path) -> None:
    """cdmon-config-version != 2.0.0 → loud ConfigError."""
    bad = _FOUNDATION_YAML.replace('"2.0.0"', '"1.0.0"', 1)
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="cdmon-config-version"):
        load_unit_file(d / "foundation.yaml")


def test_index_bad_version_is_loud(tmp_path: Path) -> None:
    """index frontmatter version != 2.0.0 → loud ConfigError."""
    bad = _INDEX_YAML.replace('"2.0.0"', '"3.0.0"', 1)
    d = _write_tree(tmp_path, index=bad)
    with pytest.raises(ConfigError, match="cdmon-config-version"):
        load_index_file(d / "index.yaml")


def test_unit_bad_extension_no_dot_is_loud(tmp_path: Path) -> None:
    """A source-files-format entry without a leading dot → loud."""
    bad = _FOUNDATION_YAML.replace('  - ".py"', '  - "py"', 1)
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="start with"):
        load_unit_file(d / "foundation.yaml")


def test_unit_name_mismatch_is_loud(tmp_path: Path) -> None:
    """unit != filename stem → loud ConfigError."""
    bad = _FOUNDATION_YAML.replace("unit: foundation", "unit: wrong-name", 1)
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="must equal the filename stem"):
        load_unit_file(d / "foundation.yaml")


def test_unit_empty_dir_covered_is_loud(tmp_path: Path) -> None:
    """An empty dir-covered list → loud ConfigError."""
    bad = textwrap.dedent(
        """\
        ---
        cdmon-config-version: "2.0.0"
        unit: foundation
        title: "t"
        owner: o
        created: "2026-06-07"
        updated: "2026-06-07"
        ---
        dir-covered: []
        source-files-format:
          - ".py"
        documents:
          - id: d1
            path: docs/d1.md
            audience: eng-guide
        """
    )
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="dir-covered"):
        load_unit_file(d / "foundation.yaml")


def test_unit_unknown_key_is_loud(tmp_path: Path) -> None:
    """extra='forbid': a stray top-level key in a unit is loud."""
    bad = _FOUNDATION_YAML + "stray-key: oops\n"
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError):
        load_unit_file(d / "foundation.yaml")


def test_unit_body_not_a_mapping_is_loud(tmp_path: Path) -> None:
    """A unit body that is a list, not a mapping, is loud."""
    bad = (
        '---\ncdmon-config-version: "2.0.0"\nunit: foundation\n'
        "title: t\nowner: o\ncreated: x\nupdated: y\n---\n- a\n- b\n"
    )
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_unit_file(d / "foundation.yaml")


# --------------------------------------------------------------------------- #
# Integration: real fixture → merged MonitorConfig.
# --------------------------------------------------------------------------- #


def test_load_config_dir_merges_documents_in_index_order(tmp_path: Path) -> None:
    """documents = concat of unit docs in index order then in-file order."""
    d = _write_tree(tmp_path)
    cfg = load_config_dir(d)
    assert isinstance(cfg, MonitorConfig)
    assert [doc.id for doc in cfg.documents] == [
        "config-guide",
        "errors-guide",
        "agent-workflow",
    ]
    # spot-check paths, audiences, code_refs survived the merge intact.
    config_guide = cfg.documents[0]
    assert config_guide.path == "docs/api/config.md"
    assert config_guide.audience is Audience.ENG_GUIDE
    assert config_guide.code_refs[0].path == "custodex/config.py"
    assert config_guide.code_refs[0].symbols == ("load_config",)
    assert cfg.documents[1].audience is Audience.USER_GUIDE
    assert cfg.documents[2].code_refs[1].path == "custodex/agent/graph.py"


def test_load_config_dir_globals_from_index(tmp_path: Path) -> None:
    """version/root/backend/region_templates/coverage come from index.yaml."""
    d = _write_tree(tmp_path)
    cfg = load_config_dir(d)
    assert cfg.version == "2.0.0"
    assert cfg.root == "../.."
    assert cfg.apply_default is True
    assert cfg.backend.kind == "mock"
    assert "api-index" in cfg.region_templates
    assert cfg.region_templates["api-index"].source == "index"
    assert cfg.coverage.waive[0].path == "custodex/__init__.py"
    assert cfg.coverage.waive[0].reason == "re-export aggregator"


def test_load_config_dir_equals_load_bundle_config(tmp_path: Path) -> None:
    """load_config_dir(d) == load_bundle(d).config (the documented identity)."""
    d = _write_tree(tmp_path)
    assert load_config_dir(d) == load_bundle(d).config


# --------------------------------------------------------------------------- #
# Loud cross-file failures.
# --------------------------------------------------------------------------- #


def test_missing_index_is_loud(tmp_path: Path) -> None:
    """No index.yaml in the dir → loud ConfigError."""
    empty = tmp_path / "config" / "cdmon"
    empty.mkdir(parents=True)
    with pytest.raises(ConfigError, match="requires an index.yaml"):
        load_config_dir(empty)


def test_indexed_unit_file_missing_is_loud(tmp_path: Path) -> None:
    """A unit listed in index but absent on disk → loud ConfigError."""
    d = _write_tree(tmp_path)
    (d / "agent-workflow.yaml").unlink()
    with pytest.raises(ConfigError, match="is missing"):
        load_config_dir(d)


def test_duplicate_document_id_across_units_is_loud(tmp_path: Path) -> None:
    """The same document id in two units → loud ConfigError."""
    dup_agent = _AGENT_YAML.replace("id: agent-workflow", "id: config-guide", 1)
    d = _write_tree(tmp_path, agent=dup_agent)
    with pytest.raises(ConfigError, match="duplicate document id"):
        load_config_dir(d)


def test_identical_dir_covered_across_units_is_loud(tmp_path: Path) -> None:
    """Two units sharing an IDENTICAL dir-covered path → loud ConfigError (Z-01a).

    Nesting is now allowed; only an identical (normalized) directory in two units
    genuinely conflicts (neither could win the deepest-match tie).
    """
    # foundation owns 'custodex/agent'; agent-workflow owns the same.
    identical = _FOUNDATION_YAML.replace(
        "  - custodex/config.py",
        "  - custodex/agent",
        1,
    )
    d = _write_tree(tmp_path, foundation=identical)
    with pytest.raises(ConfigError, match="duplicate dir-covered"):
        load_config_dir(d)


def test_identical_dir_covered_normalized_spelling_is_loud(tmp_path: Path) -> None:
    """An equivalent spelling (trailing slash / ./) of the same dir is still loud."""
    identical = _FOUNDATION_YAML.replace(
        "  - custodex/config.py",
        # same dir as agent-workflow, spelled differently
        "  - ./custodex/agent/",
        1,
    )
    d = _write_tree(tmp_path, foundation=identical)
    with pytest.raises(ConfigError, match="duplicate dir-covered"):
        load_config_dir(d)


def test_nested_dir_covered_across_units_is_ok(tmp_path: Path) -> None:
    """A parent + child dir-covered across two units now LOADS (Z-01a nesting)."""
    # foundation owns the parent 'custodex'; agent-workflow owns the
    # child 'custodex/agent' under it — nesting, not a conflict.
    nested = _FOUNDATION_YAML.replace(
        "  - custodex/config.py",
        "  - custodex",
        1,
    )
    d = _write_tree(tmp_path, foundation=nested)
    cfg = load_config_dir(d)  # no raise
    assert len(cfg.documents) == 3


def test_disjoint_dir_covered_is_ok(tmp_path: Path) -> None:
    """Sibling dirs that share a prefix component but are disjoint are fine."""
    foundation = _FOUNDATION_YAML.replace(
        "  - custodex/config.py",
        "  - custodex/agentry",  # NOT under custodex/agent
        1,
    )
    d = _write_tree(tmp_path, foundation=foundation)
    cfg = load_config_dir(d)  # no raise
    assert len(cfg.documents) == 3


# --------------------------------------------------------------------------- #
# Bundle seam.
# --------------------------------------------------------------------------- #


def test_bundle_unit_for_document(tmp_path: Path) -> None:
    """unit_for_document maps a doc id back to its owning unit."""
    d = _write_tree(tmp_path)
    bundle = load_bundle(d)
    assert isinstance(bundle, ConfigBundle)
    unit = bundle.unit_for_document("agent-workflow")
    assert unit is not None
    assert unit.frontmatter.unit == "agent-workflow"
    assert unit.source_files_format == (".py",)
    assert bundle.unit_for_document("config-guide").frontmatter.unit == "foundation"
    assert bundle.unit_for_document("nope") is None
    assert bundle.config_dir == str(d)
    assert isinstance(bundle.index, IndexFile)
    assert len(bundle.units) == 2


# --------------------------------------------------------------------------- #
# Z-01a — deepest-wins unit_for_path attribution.
# --------------------------------------------------------------------------- #

# A nested layout: ``core`` owns the parent ``custodex``; ``agent-workflow``
# owns the child ``custodex/agent`` under it.
_NESTED_FOUNDATION = _FOUNDATION_YAML.replace(
    "  - custodex/config.py",
    "  - custodex",
    1,
)


def test_unit_for_path_child_file_attributes_to_child(tmp_path: Path) -> None:
    """A file under the child dir attributes to the CHILD unit, not the parent."""
    d = _write_tree(tmp_path, foundation=_NESTED_FOUNDATION)
    bundle = load_bundle(d)
    unit = unit_for_path(bundle, "custodex/agent/backend.py")
    assert unit is not None
    assert unit.frontmatter.unit == "agent-workflow"
    # The ConfigBundle method form agrees.
    assert bundle.unit_for_path("custodex/agent/backend.py") is unit


def test_unit_for_path_parent_file_attributes_to_parent(tmp_path: Path) -> None:
    """A file directly in the parent dir (not under the child) → the PARENT unit."""
    d = _write_tree(tmp_path, foundation=_NESTED_FOUNDATION)
    bundle = load_bundle(d)
    unit = unit_for_path(bundle, "custodex/config.py")
    assert unit is not None
    assert unit.frontmatter.unit == "foundation"


def test_unit_for_path_unrelated_is_none(tmp_path: Path) -> None:
    """A file under no unit's dir-covered → None."""
    d = _write_tree(tmp_path, foundation=_NESTED_FOUNDATION)
    bundle = load_bundle(d)
    assert unit_for_path(bundle, "docs/elsewhere/thing.py") is None


def test_unit_for_path_sibling_prefix_not_nested(tmp_path: Path) -> None:
    """Component-wise match: a file under ``.../agentry`` is NOT attributed to the
    unit owning ``.../agent`` (string-prefix would wrongly match)."""
    foundation = _FOUNDATION_YAML.replace(
        "  - custodex/config.py",
        "  - custodex/agentry",
        1,
    )
    d = _write_tree(tmp_path, foundation=foundation)
    bundle = load_bundle(d)
    # agentry file → the foundation unit (owns custodex/agentry).
    f = unit_for_path(bundle, "custodex/agentry/x.py")
    assert f is not None and f.frontmatter.unit == "foundation"
    # agent file → the agent-workflow unit; agentry's owner must NOT claim it.
    a = unit_for_path(bundle, "custodex/agent/backend.py")
    assert a is not None and a.frontmatter.unit == "agent-workflow"


# --------------------------------------------------------------------------- #
# CLI back-compat via _resolve_config.
# --------------------------------------------------------------------------- #


def test_resolve_config_single_file_unchanged(tmp_path: Path) -> None:
    """A single-file --config still loads via _resolve_config (back-compat)."""
    from custodex.cli import _resolve_config

    cfg_path = tmp_path / "cdmon.yaml"
    cfg_path.write_text(
        textwrap.dedent(
            """\
            version: "1.0.0"
            root: "."
            documents:
              - id: g
                path: docs/g.md
                audience: eng-guide
            """
        ),
        encoding="utf-8",
    )
    cfg, config_dir = _resolve_config(cfg_path)
    assert cfg.documents[0].id == "g"
    assert config_dir == cfg_path.parent


def test_resolve_config_directory_uses_dir_loader(tmp_path: Path) -> None:
    """Passing a directory uses the dir loader and returns it as config_dir."""
    from custodex.cli import _resolve_config

    d = _write_tree(tmp_path)
    cfg, config_dir = _resolve_config(d)
    assert [doc.id for doc in cfg.documents] == [
        "config-guide",
        "errors-guide",
        "agent-workflow",
    ]
    assert config_dir == d


def test_resolve_config_autodetect_when_missing_single_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No --config file present but config/cdmon/index.yaml exists → dir layout."""
    from custodex.cli import _resolve_config

    _write_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    # default --config is cdmon.yaml which does NOT exist here → auto-detect.
    cfg, config_dir = _resolve_config(Path("cdmon.yaml"))
    assert [doc.id for doc in cfg.documents][0] == "config-guide"
    assert config_dir == Path("config") / "cdmon"


def test_resolve_config_explicit_file_wins_over_autodetect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing explicit single file is honored even if a dir layout exists."""
    from custodex.cli import _resolve_config

    _write_tree(tmp_path)
    cfg_path = tmp_path / "cdmon.yaml"
    cfg_path.write_text(
        'version: "1.0.0"\nroot: "."\ndocuments:\n'
        "  - {id: solo, path: docs/s.md, audience: eng-guide}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    cfg, config_dir = _resolve_config(Path("cdmon.yaml"))
    assert [doc.id for doc in cfg.documents] == ["solo"]
    assert config_dir == Path("cdmon.yaml").parent


def test_unit_whitespace_dir_covered_entry_is_loud(tmp_path: Path) -> None:
    """A blank dir-covered entry → loud ConfigError."""
    bad = _FOUNDATION_YAML.replace("  - custodex/config.py", '  - "   "', 1)
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="non-empty"):
        load_unit_file(d / "foundation.yaml")


def test_unit_empty_source_files_format_is_loud(tmp_path: Path) -> None:
    """An empty source-files-format list → loud ConfigError."""
    bad = _FOUNDATION_YAML.replace(
        'source-files-format:\n  - ".py"', "source-files-format: []", 1
    )
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="at least one extension"):
        load_unit_file(d / "foundation.yaml")


def test_unit_empty_documents_is_loud(tmp_path: Path) -> None:
    """An empty documents list → loud ConfigError."""
    head = _FOUNDATION_YAML.split("documents:", 1)[0]
    bad = head + "documents: []\n"
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="at least one document"):
        load_unit_file(d / "foundation.yaml")


def test_unit_unreadable_file_is_loud(tmp_path: Path) -> None:
    """A missing/unreadable file path → loud ConfigError on read."""
    with pytest.raises(ConfigError, match="Cannot read config file"):
        load_unit_file(tmp_path / "does-not-exist.yaml")


def test_unit_malformed_body_yaml_is_loud(tmp_path: Path) -> None:
    """A malformed YAML body (after a valid fence) → loud ConfigError."""
    bad = (
        '---\ncdmon-config-version: "2.0.0"\nunit: foundation\n'
        "title: t\nowner: o\ncreated: x\nupdated: y\n---\n"
        "dir-covered: [a: : b]\n"
    )
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="Malformed config file"):
        load_unit_file(d / "foundation.yaml")


def test_unit_empty_body_is_loud_on_required_fields(tmp_path: Path) -> None:
    """An empty body (no required scope) → loud ConfigError (missing fields)."""
    bad = (
        '---\ncdmon-config-version: "2.0.0"\nunit: foundation\n'
        "title: t\nowner: o\ncreated: x\nupdated: y\n---\n"
    )
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="Invalid unit file"):
        load_unit_file(d / "foundation.yaml")


def test_unit_comment_only_body_normalizes_then_fails_on_fields(
    tmp_path: Path,
) -> None:
    """A comment-only body (yaml -> None) becomes {} then fails validation."""
    bad = (
        '---\ncdmon-config-version: "2.0.0"\nunit: foundation\n'
        "title: t\nowner: o\ncreated: x\nupdated: y\n---\n"
        "# just a comment, no fields\n"
    )
    d = _write_tree(tmp_path, foundation=bad)
    with pytest.raises(ConfigError, match="Invalid unit file"):
        load_unit_file(d / "foundation.yaml")


def test_config_error_is_codedocmonitorerror(tmp_path: Path) -> None:
    """ConfigError remains a CodeDocMonitorError so the CLI catches it (K8)."""
    empty = tmp_path / "config" / "cdmon"
    empty.mkdir(parents=True)
    with pytest.raises(CodeDocMonitorError):
        load_config_dir(empty)
