"""AGT-01 — deterministic entity extraction + mention linking (`entities.py`).

The mention layer of EPIC AGT: parse managed-doc PROSE deterministically and
LINK mentions against a registry built from the code surface + the managed-doc
set + the full repo file tree. Precision beats recall: an ambiguous mention is
unresolved-or-ignored, never guessed (the 2026-07-02 design-review rules).

Features: FEAT-ENTITIES-001, FEAT-ENTITIES-002, FEAT-ENTITIES-003
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.config import (
    Audience,
    CodeRef,
    CoverageConfig,
    DocumentSpec,
    EntitiesConfig,
    MonitorConfig,
)
from custodex.entities import (
    DocEntities,
    EntityKind,
    EntityRegistry,
    Mention,
    build_registry,
    corpus_entities,
    extract_doc_entities,
    render_entities_text,
)
from custodex.errors import DriftError

ALPHA_PY = '''"""Alpha module."""


def solve_widget(x, *, scale=1):
    """Public function."""
    return x * scale


class WidgetFrame:
    """Public class."""

    def clamp_range(self, lo, hi):
        """Public method."""
        return (lo, hi)


def _private_helper():
    return None
'''

# `beta/utils.py` and `gamma/utils.py` share the stem "utils" (stem-collision
# fixture); `beta/unique_mod.py` has a unique stem.
BETA_UTILS_PY = "def beta_only():\n    return 1\n"
GAMMA_UTILS_PY = "def gamma_only():\n    return 2\n"
UNIQUE_MOD_PY = "def lone_func():\n    return 3\n"


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _config(root: Path) -> MonitorConfig:
    return MonitorConfig(
        documents=(
            DocumentSpec(
                id="guide",
                path="docs/guide.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="alpha.py"),),
            ),
            DocumentSpec(
                id="other",
                path="docs/other.md",
                audience=Audience.USER_GUIDE,
                code_refs=(CodeRef(path="alpha.py"),),
            ),
        ),
        coverage=CoverageConfig(include=("**/*.py",), exclude=()),
    )


def _fixture_repo(tmp_path: Path) -> Path:
    _write(tmp_path, "alpha.py", ALPHA_PY)
    _write(tmp_path, "beta/utils.py", BETA_UTILS_PY)
    _write(tmp_path, "gamma/utils.py", GAMMA_UTILS_PY)
    _write(tmp_path, "beta/unique_mod.py", UNIQUE_MOD_PY)
    _write(tmp_path, "notes.txt", "plain\n")
    _write(tmp_path, "docs/other.md", "# Other\n\nProse.\n")
    return tmp_path


def _registry(tmp_path: Path) -> EntityRegistry:
    return build_registry(_config(tmp_path), _fixture_repo(tmp_path))


def _extract(
    registry: EntityRegistry, raw: str, cfg: EntitiesConfig | None = None
) -> DocEntities:
    return extract_doc_entities(
        "guide", "docs/guide.md", raw, registry, entities_cfg=cfg or EntitiesConfig()
    )


def _mentions(result: DocEntities, kind: EntityKind) -> list[Mention]:
    return [m for m in result.mentions if m.kind is kind]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class TestRegistry:
    def test_registry_maps_docs_files_dirs_and_symbols(self, tmp_path: Path) -> None:
        reg = _registry(tmp_path)
        assert reg.doc_by_path["docs/guide.md"] == "guide"
        assert "alpha.py" in reg.file_set
        assert "notes.txt" in reg.file_set  # full tree, not just coverage
        assert "beta" in reg.dir_set and "docs" in reg.dir_set
        assert reg.warnings == ()

    def test_registry_skips_vcs_and_venv_trees(self, tmp_path: Path) -> None:
        _write(tmp_path, ".git/objects/x", "x")
        _write(tmp_path, ".venv/lib/site.py", "x = 1\n")
        _write(tmp_path, "pkg/__pycache__/mod.pyc", "x")
        reg = _registry(tmp_path)
        assert not any(p.startswith((".git", ".venv")) for p in reg.file_set)
        assert not any("__pycache__" in p for p in reg.file_set)

    def test_unparseable_file_warns_and_scan_continues(self, tmp_path: Path) -> None:
        _write(tmp_path, "broken.py", "def broken(:\n")
        reg = _registry(tmp_path)
        assert any("broken.py" in w for w in reg.warnings)
        # the rest of the scan survived: alpha.py symbols still registered
        assert reg.resolve_symbol("solve_widget") is not None

    def test_private_symbols_not_registered(self, tmp_path: Path) -> None:
        reg = _registry(tmp_path)
        assert reg.resolve_symbol("_private_helper") is None


# ---------------------------------------------------------------------------
# Symbol resolution rules
# ---------------------------------------------------------------------------
class TestSymbolResolution:
    def test_qualified_class_method_resolves(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "See `WidgetFrame.clamp_range`.\n")
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert m.resolved and m.entity_id == "symbol alpha.py#WidgetFrame.clamp_range"

    def test_module_qualified_unique_stem_resolves(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "Call `alpha.solve_widget` here.\n")
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert m.resolved and m.entity_id == "symbol alpha.py#solve_widget"

    def test_full_dotted_path_resolves(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "Call `beta.unique_mod.lone_func`.\n")
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert m.resolved and m.entity_id == "symbol beta/unique_mod.py#lone_func"

    def test_colliding_stem_qualifier_is_unresolved(self, tmp_path: Path) -> None:
        # beta/utils.py and gamma/utils.py share the stem "utils" — the
        # stem-qualified form must NOT guess (design-review must-fix).
        result = _extract(_registry(tmp_path), "Call `utils.beta_only` here.\n")
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert not m.resolved and m.entity_id is None

    def test_bare_snake_name_unique_resolves(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "Use `solve_widget` for it.\n")
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert m.resolved and m.entity_id == "symbol alpha.py#solve_widget"

    def test_plain_word_colliding_with_module_stem_mints_nothing(
        self, tmp_path: Path
    ) -> None:
        # A public symbol `alpha` defined in another file collides with the
        # module stem alpha.py — the measured cli.py-command trap. Resolution
        # is BLOCKED (never guess), and a plain word is never surfaced as
        # unresolved (the noise-floor rule) — so the span mints nothing.
        _write(tmp_path, "cmds.py", "def alpha():\n    return 0\n")
        reg = _registry(tmp_path)
        result = _extract(reg, "The `alpha` entry point.\n")
        assert result.mentions == ()

    def test_snake_name_colliding_with_module_stem_is_unresolved(
        self, tmp_path: Path
    ) -> None:
        # Same collision but snake_case: resolution blocked AND the span is
        # unresolved-eligible, so it surfaces as an unresolved SYMBOL.
        _write(tmp_path, "my_util.py", "X = 1\n")
        _write(tmp_path, "cmds.py", "def my_util():\n    return 0\n")
        reg = _registry(tmp_path)
        result = _extract(reg, "The `my_util` helper.\n")
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert not m.resolved and m.entity_id is None

    def test_bare_name_matching_only_unique_stem_is_path_mention(
        self, tmp_path: Path
    ) -> None:
        result = _extract(_registry(tmp_path), "See `unique_mod` for details.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert m.resolved and m.entity_id == "path beta/unique_mod.py"

    def test_unknown_snake_identifier_is_unresolved_symbol(
        self, tmp_path: Path
    ) -> None:
        result = _extract(_registry(tmp_path), "Uses `missing_thing` inside.\n")
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert not m.resolved and m.entity_id is None and m.text == "missing_thing"

    def test_plain_word_resolves_or_is_ignored_never_unresolved(
        self, tmp_path: Path
    ) -> None:
        # `check` matches nothing → IGNORED (not unresolved); WidgetFrame (one
        # hump... two humps) resolves; `Widget` (single-hump, unknown) ignored.
        result = _extract(_registry(tmp_path), "Run `check` on `Widget` now.\n")
        assert result.mentions == ()

    def test_multi_hump_camelcase_unknown_is_unresolved(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "Uses `FooBarBaz` internally.\n")
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert not m.resolved

    def test_known_camelcase_class_resolves(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "The `WidgetFrame` class.\n")
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert m.resolved and m.entity_id == "symbol alpha.py#WidgetFrame"


# ---------------------------------------------------------------------------
# SCREAMING_SNAKE / env vars
# ---------------------------------------------------------------------------
class TestEnvVars:
    def test_prefixed_env_var_resolves_self_evident(self, tmp_path: Path) -> None:
        cfg = EntitiesConfig(env_prefixes=("CDMON_",))
        result = _extract(_registry(tmp_path), "Set `CDMON_SECRET_KEY` first.\n", cfg)
        (m,) = _mentions(result, EntityKind.ENV_VAR)
        assert m.resolved and m.entity_id == "env CDMON_SECRET_KEY"

    def test_unprefixed_screaming_snake_is_ignored(self, tmp_path: Path) -> None:
        # An enum-name-like span with no registry match and no prefix mints
        # NOTHING (the MISSING_REGION noise fix).
        cfg = EntitiesConfig(env_prefixes=("CDMON_",))
        result = _extract(_registry(tmp_path), "Raises `SOME_ENUM_NAME` here.\n", cfg)
        assert result.mentions == ()

    def test_no_prefixes_configured_means_no_env_mentions(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "Set `CDMON_SECRET_KEY` first.\n")
        assert result.mentions == ()

    def test_registry_symbol_wins_over_env_pattern(self, tmp_path: Path) -> None:
        _write(tmp_path, "consts.py", "ALL_CAPS_CONST = 1\n")
        cfg = EntitiesConfig(env_prefixes=("ALL_",))
        result = _extract(_registry(tmp_path), "Uses `ALL_CAPS_CONST`.\n", cfg)
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert m.resolved and m.entity_id == "symbol consts.py#ALL_CAPS_CONST"


# ---------------------------------------------------------------------------
# Paths, links, urls
# ---------------------------------------------------------------------------
class TestPathsAndLinks:
    def test_backtick_path_resolves_against_full_tree(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "Edit `beta/utils.py` there.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert m.resolved and m.entity_id == "path beta/utils.py"

    def test_backtick_directory_with_trailing_slash_resolves(
        self, tmp_path: Path
    ) -> None:
        result = _extract(_registry(tmp_path), "Everything under `docs/` moves.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert m.resolved and m.entity_id == "path docs"

    def test_non_code_file_resolves_via_full_tree(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "See `notes.txt` for details.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert m.resolved and m.entity_id == "path notes.txt"

    def test_unique_basename_resolves(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "Check `unique_mod.py` first.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert m.resolved and m.entity_id == "path beta/unique_mod.py"

    def test_ambiguous_basename_mints_nothing(self, tmp_path: Path) -> None:
        # utils.py exists TWICE — existing-but-ambiguous is not rot, and we
        # never guess: the span mints nothing at all.
        result = _extract(_registry(tmp_path), "Check `utils.py` first.\n")
        assert result.mentions == ()

    def test_missing_path_is_unresolved(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "Check `gone/nowhere.py` first.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert not m.resolved and m.entity_id is None

    def test_route_glob_and_brace_spans_mint_nothing(self, tmp_path: Path) -> None:
        raw = (
            "Call `GET /repos/{id}/status` or `config/cdmon/*.yaml` or\n"
            "`cdx check --json` today.\n"
        )
        result = _extract(_registry(tmp_path), raw)
        assert result.mentions == ()

    def test_colon_absolute_and_degenerate_spans_mint_nothing(
        self, tmp_path: Path
    ) -> None:
        raw = "Use `CDM:BEGIN/END` markers at `/` or `/repos/x` or `../up.py`.\n"
        result = _extract(_registry(tmp_path), raw)
        assert result.mentions == ()

    def test_dotted_package_mention_resolves_as_path(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "The `beta.unique_mod` module.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert m.resolved and m.entity_id == "path beta/unique_mod.py"

    def test_dotted_package_dir_mention_resolves_as_path(self, tmp_path: Path) -> None:
        _write(tmp_path, "beta/sub/mod.py", "Y = 1\n")
        result = _extract(_registry(tmp_path), "Inside `beta.sub` lives it.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert m.resolved and m.entity_id == "path beta/sub"

    def test_relative_link_to_managed_doc_is_doc_mention(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "See [other](other.md) too.\n")
        (m,) = _mentions(result, EntityKind.DOC)
        assert m.resolved and m.entity_id == "doc docs/other.md"

    def test_relative_link_to_existing_file_is_path_mention(
        self, tmp_path: Path
    ) -> None:
        result = _extract(_registry(tmp_path), "See [alpha](../alpha.py) too.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert m.resolved and m.entity_id == "path alpha.py"

    def test_relative_link_to_missing_file_is_unresolved_path(
        self, tmp_path: Path
    ) -> None:
        result = _extract(_registry(tmp_path), "See [gone](missing.md) too.\n")
        (m,) = _mentions(result, EntityKind.PATH)
        assert not m.resolved

    def test_absolute_link_is_url_mention(self, tmp_path: Path) -> None:
        result = _extract(_registry(tmp_path), "See [site](https://x.example/a#b).\n")
        (m,) = _mentions(result, EntityKind.URL)
        assert m.resolved and m.entity_id == "url https://x.example/a"

    def test_image_and_mailto_links_mint_nothing(self, tmp_path: Path) -> None:
        raw = "![shot](other.md)\n[mail](mailto:a@b.c)\n"
        result = _extract(_registry(tmp_path), raw)
        assert result.mentions == ()


# ---------------------------------------------------------------------------
# Exclusions: fences, CDM regions, ignore list
# ---------------------------------------------------------------------------
class TestExclusions:
    def test_fenced_code_mints_nothing(self, tmp_path: Path) -> None:
        raw = "```python\nsolve_widget(1)\n`solve_widget`\n```\nProse.\n"
        result = _extract(_registry(tmp_path), raw)
        assert result.mentions == ()

    def test_cdm_region_mints_nothing(self, tmp_path: Path) -> None:
        raw = (
            "<!-- CDM:BEGIN symbols -->\n"
            "| `solve_widget` | [other](other.md) |\n"
            "<!-- CDM:END symbols -->\n"
            "Prose.\n"
        )
        result = _extract(_registry(tmp_path), raw)
        assert result.mentions == ()

    def test_ignore_list_mints_nothing(self, tmp_path: Path) -> None:
        cfg = EntitiesConfig(ignore=("solve_widget",))
        result = _extract(_registry(tmp_path), "Use `solve_widget` here.\n", cfg)
        assert result.mentions == ()

    def test_tilde_fence_also_excluded(self, tmp_path: Path) -> None:
        raw = "~~~\n`solve_widget`\n~~~\nProse.\n"
        result = _extract(_registry(tmp_path), raw)
        assert result.mentions == ()


# ---------------------------------------------------------------------------
# Sections, line numbers, determinism, rendering
# ---------------------------------------------------------------------------
class TestSectionsAndShape:
    def test_headings_become_section_entities_with_dedup(self, tmp_path: Path) -> None:
        raw = "# Guide\n\n## Usage\n\ntext\n\n## Usage\n"
        result = _extract(_registry(tmp_path), raw)
        ids = [s.id for s in result.sections]
        assert ids == [
            "section docs/guide.md#guide",
            "section docs/guide.md#usage",
            "section docs/guide.md#usage-2",
        ]
        assert [s.name for s in result.sections] == ["guide", "usage", "usage-2"]

    def test_mention_line_is_file_accurate_with_front_matter(
        self, tmp_path: Path
    ) -> None:
        raw = (
            "---\n"
            "cdm:\n"
            "  fingerprint: abc\n"
            "  region_anchors:\n"
            "    x: y\n"
            "---\n"
            "# Guide\n"
            "\n"
            "Use `solve_widget` now.\n"
        )
        result = _extract(_registry(tmp_path), raw)
        (m,) = _mentions(result, EntityKind.SYMBOL)
        assert m.line == 9  # the file line, not the body line

    def test_double_run_is_identical(self, tmp_path: Path) -> None:
        reg = _registry(tmp_path)
        raw = "# T\n\nUse `solve_widget` and [other](other.md) and `beta/utils.py`.\n"
        a = _extract(reg, raw)
        b = _extract(reg, raw)
        assert a == b
        assert [(m.line, m.text) for m in a.mentions] == sorted(
            (m.line, m.text) for m in a.mentions
        )

    def test_render_text_lists_and_filters_unresolved(self, tmp_path: Path) -> None:
        raw = "Use `solve_widget` and `missing_thing`.\n"
        result = _extract(_registry(tmp_path), raw)
        full = render_entities_text((result,))
        assert "solve_widget" in full and "missing_thing" in full
        only = render_entities_text((result,), unresolved_only=True)
        assert "missing_thing" in only and "solve_widget" not in only


# ---------------------------------------------------------------------------
# corpus_entities
# ---------------------------------------------------------------------------
class TestCorpus:
    def test_corpus_over_real_files(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        _write(root, "docs/guide.md", "# G\n\nUse `solve_widget` now.\n")
        results = corpus_entities(_config(root), root)
        assert [r.doc_id for r in results] == ["guide", "other"]
        guide = results[0]
        assert guide.mentions[0].entity_id == "symbol alpha.py#solve_widget"

    def test_corpus_filters_by_doc_id_and_is_loud_on_unknown(
        self, tmp_path: Path
    ) -> None:
        root = _fixture_repo(tmp_path)
        _write(root, "docs/guide.md", "# G\n\nProse.\n")
        results = corpus_entities(_config(root), root, doc_id="guide")
        assert [r.doc_id for r in results] == ["guide"]
        with pytest.raises(DriftError):
            corpus_entities(_config(root), root, doc_id="nope")

    def test_corpus_skips_missing_doc_files(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        # docs/guide.md never written — MISSING_DOC drift covers it elsewhere.
        results = corpus_entities(_config(root), root)
        assert [r.doc_id for r in results] == ["other"]
