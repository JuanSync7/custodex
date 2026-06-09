"""N-03 — tests for ``ignore.yaml`` + ``.gitignore`` merge + ``source-files-format``
coverage scoping (K0, K8, K10).

Covers the new :class:`IgnoreFile`/:class:`IgnoreFrontmatter` models and
:func:`load_ignore_file`; the hand-rolled :func:`gitignore_to_globs` translation
(MATCHING inventory ``_translate`` ``**`` semantics, deterministic); the
:func:`effective_coverage` derivation (include from dir-covered × source-files-
format, exclude from ignore patterns ∪ translated ``.gitignore`` ∪ defaults,
waive carried from index); the wiring into :func:`load_config_dir`; and the
integration goal test that runs the REAL coverage path
(:func:`discover_files`/:func:`discover_symbols`/:func:`resolve_coverage`) over
the derived include/exclude and asserts the universe is exactly the format-
matched, non-ignored files.

Features: FEAT-CONFIGV2-007, FEAT-CONFIGV2-006, FEAT-CONFIGV2-002, FEAT-CONFIGV2-001
Features: FEAT-COVERAGE-001, FEAT-COVERAGE-002, FEAT-COVERAGE-007
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.config import (
    _DEFAULT_EXCLUDE,
    CoverageConfig,
    IgnoreFile,
    WaiverEntry,
    effective_coverage,
    gitignore_to_globs,
    load_bundle,
    load_config_dir,
    load_ignore_file,
)
from code_doc_monitor.coverage import resolve_coverage
from code_doc_monitor.errors import ConfigError
from code_doc_monitor.inventory import _translate, discover_files, discover_symbols

# --------------------------------------------------------------------------- #
# gitignore_to_globs — translation MATCHES inventory _translate ** semantics.
# --------------------------------------------------------------------------- #


def test_gitignore_skips_comments_and_blanks() -> None:
    text = "# a comment\n\n   \n*.log\n"
    assert gitignore_to_globs(text) == ("**/*.log",)


def test_gitignore_trailing_slash_is_dir_anywhere() -> None:
    # ``__pycache__/`` → a directory named __pycache__ anywhere → its contents.
    assert gitignore_to_globs("__pycache__/\n") == ("**/__pycache__/**",)


def test_gitignore_bare_token_matches_file_or_dir_anywhere() -> None:
    # ``build`` (no slash) → match a file OR dir of that name anywhere, and the
    # contents under it when it is a dir.
    assert gitignore_to_globs("build\n") == ("**/build", "**/build/**")


def test_gitignore_leading_slash_is_root_anchored() -> None:
    # ``/dist`` → root-anchored file/dir + its contents.
    assert gitignore_to_globs("/dist\n") == ("dist", "dist/**")


def test_gitignore_embedded_path_kept_as_is_plus_contents() -> None:
    # An embedded ``/`` is a path relative to repo root; keep it AND its contents.
    assert gitignore_to_globs("docs/build\n") == ("docs/build", "docs/build/**")


def test_gitignore_wildcards_in_path_preserved() -> None:
    assert gitignore_to_globs("docs/**/*.html\n") == ("docs/**/*.html",)


def test_gitignore_star_log_bare() -> None:
    assert gitignore_to_globs("*.log\n") == ("**/*.log",)


def test_gitignore_negation_emits_nothing() -> None:
    assert gitignore_to_globs("*.log\n!keep.log\n") == ("**/*.log",)


def test_gitignore_only_negation_is_empty() -> None:
    assert gitignore_to_globs("!keep.py\n") == ()


def test_gitignore_is_deterministic_sorted_and_deduped() -> None:
    # Same token twice, and tokens out of order: output is sorted + deduped.
    # ``*.log`` is a wildcard file pattern (no contents companion); ``a.log``/
    # ``z.log`` are literal tokens (could be a dir → a contents companion).
    text = "z.log\n*.log\n*.log\na.log\n"
    out = gitignore_to_globs(text)
    assert out == tuple(sorted(set(out)))
    assert out == (
        "**/*.log",
        "**/a.log",
        "**/a.log/**",
        "**/z.log",
        "**/z.log/**",
    )


def test_gitignore_lone_slash_is_inert() -> None:
    # A lone "/" (and a "//") names nothing → emit nothing (no crash).
    assert gitignore_to_globs("/\n//\n") == ()


def test_gitignore_root_anchored_dir() -> None:
    # ``/dist/`` → root-anchored directory contents only.
    assert gitignore_to_globs("/dist/\n") == ("dist/**",)


def test_gitignore_embedded_path_dir() -> None:
    # ``docs/build/`` → that directory's contents (embedded slash).
    assert gitignore_to_globs("docs/build/\n") == ("docs/build/**",)


def test_gitignore_root_anchored_with_slash_inside() -> None:
    # ``/docs/build`` → leading slash stripped, embedded slash → anchored path.
    assert gitignore_to_globs("/docs/build\n") == ("docs/build", "docs/build/**")


def test_gitignore_translations_match_inventory_semantics() -> None:
    """Every emitted glob, run through the REAL inventory ``_translate``, must
    match the file/dir-content paths the .gitignore line intends (K0 parity)."""
    # bare dir token: __pycache__/ should exclude nested cache files.
    globs = gitignore_to_globs("__pycache__/\n")
    assert any(_translate(g).match("pkg/__pycache__/x.pyc") for g in globs)
    # *.log anywhere
    globs = gitignore_to_globs("*.log\n")
    assert any(_translate(g).match("a/b/run.log") for g in globs)
    assert any(_translate(g).match("run.log") for g in globs)
    # /dist root-anchored: matches dist itself and dist contents, NOT a/dist.
    globs = gitignore_to_globs("/dist\n")
    assert any(_translate(g).match("dist") for g in globs)
    assert any(_translate(g).match("dist/x.py") for g in globs)
    assert not any(_translate(g).match("a/dist/x.py") for g in globs)
    # bare token build: matches build anywhere AND its contents.
    globs = gitignore_to_globs("build\n")
    assert any(_translate(g).match("build") for g in globs)
    assert any(_translate(g).match("a/build") for g in globs)
    assert any(_translate(g).match("a/build/x.py") for g in globs)


# --------------------------------------------------------------------------- #
# load_ignore_file — frontmatter + body, loud K8.
# --------------------------------------------------------------------------- #

_IGNORE_YAML = """\
---
cdmon-config-version: "2.0.0"
source: ".gitignore + manual"
updated: "2026-06-07"
---
gitignore: true
patterns:
  - "**/__pycache__/**"
  - "*.rpt"
"""


def _write_ignore(tmp_path: Path, text: str = _IGNORE_YAML) -> Path:
    p = tmp_path / "ignore.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_ignore_file_parses(tmp_path: Path) -> None:
    ig = load_ignore_file(_write_ignore(tmp_path))
    assert isinstance(ig, IgnoreFile)
    assert ig.gitignore is True
    assert ig.patterns == ("**/__pycache__/**", "*.rpt")
    assert ig.frontmatter.cdmon_config_version == "2.0.0"
    assert ig.frontmatter.source == ".gitignore + manual"


def test_load_ignore_file_defaults(tmp_path: Path) -> None:
    text = """\
---
cdmon-config-version: "2.0.0"
source: "manual"
updated: "2026-06-07"
---
"""
    ig = load_ignore_file(_write_ignore(tmp_path, text))
    assert ig.gitignore is False
    assert ig.patterns == ()


def test_load_ignore_file_bad_version(tmp_path: Path) -> None:
    text = _IGNORE_YAML.replace("2.0.0", "1.0.0")
    with pytest.raises(ConfigError):
        load_ignore_file(_write_ignore(tmp_path, text))


def test_load_ignore_file_missing_frontmatter(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_ignore_file(_write_ignore(tmp_path, "gitignore: true\n"))


def test_load_ignore_file_unknown_key(tmp_path: Path) -> None:
    text = _IGNORE_YAML + "bogus: 1\n"
    with pytest.raises(ConfigError):
        load_ignore_file(_write_ignore(tmp_path, text))


def test_load_ignore_file_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_ignore_file(tmp_path / "nope.yaml")


# --------------------------------------------------------------------------- #
# effective_coverage — include from dir-covered × format; exclude = patterns ∪
# gitignore ∪ defaults; waive carried from index.
# --------------------------------------------------------------------------- #

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: demo
generated-by: cdmon
updated: "2026-06-07"
---
root: "../.."
version: "2.0.0"
coverage:
  waive:
    - {path: "agent/_gen.py", reason: "generated"}
units:
  - file: agent.yaml
"""

_UNIT_YAML = """\
---
cdmon-config-version: "2.0.0"
unit: agent
title: "Agent coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - agent
source-files-format:
  - ".py"
documents:
  - id: agent-doc
    path: docs/agent.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: agent/backend.py
"""

_IGNORE_GITIGNORE_ON = """\
---
cdmon-config-version: "2.0.0"
source: ".gitignore + manual"
updated: "2026-06-07"
---
gitignore: true
patterns:
  - "*.rpt"
"""

_IGNORE_GITIGNORE_OFF = """\
---
cdmon-config-version: "2.0.0"
source: "manual"
updated: "2026-06-07"
---
gitignore: false
patterns:
  - "*.rpt"
"""


def _build_repo(
    tmp_path: Path,
    *,
    ignore_text: str = _IGNORE_GITIGNORE_ON,
    gitignore_text: str | None = "*.log\n",
    index_text: str = _INDEX_YAML,
    unit_text: str = _UNIT_YAML,
) -> tuple[Path, Path]:
    """Lay out a real repo: ``config/cdmon/`` under a repo root with an ``agent/``
    source tree. Returns ``(repo_root, config_dir)``."""
    repo = tmp_path / "repo"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(index_text, encoding="utf-8")
    (cfg / "agent.yaml").write_text(unit_text, encoding="utf-8")
    (cfg / "ignore.yaml").write_text(ignore_text, encoding="utf-8")
    # Source tree under dir-covered ``agent``.
    agent = repo / "agent"
    (agent / "__pycache__").mkdir(parents=True)
    (agent / "backend.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (agent / "sub").mkdir()
    (agent / "sub" / "deep.py").write_text(
        "def deep():\n    return 2\n", encoding="utf-8"
    )
    (agent / "run.log").write_text("log\n", encoding="utf-8")
    (agent / "build.rpt").write_text("rpt\n", encoding="utf-8")
    (agent / "__pycache__" / "x.pyc").write_text("bytecode\n", encoding="utf-8")
    if gitignore_text is not None:
        (repo / ".gitignore").write_text(gitignore_text, encoding="utf-8")
    return repo, cfg


def test_effective_coverage_include_dir_times_format(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    bundle = load_bundle(cfg)
    cov = effective_coverage(bundle, repo)
    # The include glob(s) for dir ``agent`` × ext ``.py`` must match BOTH a file
    # directly under agent AND a nested one, via the real inventory _translate.
    direct = "agent/backend.py"
    nested = "agent/sub/deep.py"
    assert any(_translate(g).match(direct) for g in cov.include)
    assert any(_translate(g).match(nested) for g in cov.include)
    # A non-.py file directly under agent is NOT matched by any include.
    assert not any(_translate(g).match("agent/run.log") for g in cov.include)
    # Determinism.
    assert cov.include == tuple(sorted(set(cov.include)))


def test_effective_coverage_exclude_union(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    bundle = load_bundle(cfg)
    cov = effective_coverage(bundle, repo)
    # patterns from ignore.yaml.
    assert "*.rpt" in cov.exclude
    # translated .gitignore (gitignore: true and file exists).
    assert "**/*.log" in cov.exclude
    # the existing default excludes.
    for d in _DEFAULT_EXCLUDE:
        assert d in cov.exclude
    # Determinism.
    assert cov.exclude == tuple(sorted(set(cov.exclude)))


def test_effective_coverage_waive_carried_from_index(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    bundle = load_bundle(cfg)
    cov = effective_coverage(bundle, repo)
    assert cov.waive == (WaiverEntry(path="agent/_gen.py", reason="generated"),)


def test_effective_coverage_returns_coverageconfig(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    bundle = load_bundle(cfg)
    assert isinstance(effective_coverage(bundle, repo), CoverageConfig)


def test_effective_coverage_no_ignore_file_ok(tmp_path: Path) -> None:
    """When there is no ignore.yaml, exclude is just the defaults (no crash)."""
    repo, cfg = _build_repo(tmp_path, gitignore_text=None)
    (cfg / "ignore.yaml").unlink()
    bundle = load_bundle(cfg)
    cov = effective_coverage(bundle, repo)
    assert cov.exclude == tuple(sorted(set(_DEFAULT_EXCLUDE)))


# --------------------------------------------------------------------------- #
# gitignore on/off — the .gitignore-only pattern is honored only when gitignore: true.
# --------------------------------------------------------------------------- #


def test_gitignore_true_excludes(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path, ignore_text=_IGNORE_GITIGNORE_ON)
    cov = effective_coverage(load_bundle(cfg), repo)
    assert "**/*.log" in cov.exclude


def test_gitignore_false_does_not_exclude(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path, ignore_text=_IGNORE_GITIGNORE_OFF)
    cov = effective_coverage(load_bundle(cfg), repo)
    assert "**/*.log" not in cov.exclude


def test_gitignore_true_but_no_file(tmp_path: Path) -> None:
    """gitignore: true but no .gitignore on disk → no crash, nothing added."""
    repo, cfg = _build_repo(
        tmp_path, ignore_text=_IGNORE_GITIGNORE_ON, gitignore_text=None
    )
    cov = effective_coverage(load_bundle(cfg), repo)
    assert "**/*.log" not in cov.exclude


def test_gitignore_unreadable_is_loud(tmp_path: Path, monkeypatch) -> None:
    """An OSError reading the .gitignore is a loud, typed ConfigError (K8)."""
    repo, cfg = _build_repo(tmp_path, ignore_text=_IGNORE_GITIGNORE_ON)
    bundle = load_bundle(cfg)
    # load_bundle already derived coverage once (reading .gitignore fine); now
    # make the read fail and re-derive to exercise the error path.

    orig_read = Path.read_text

    def boom(self, *a, **k):  # type: ignore[no-untyped-def]
        if self.name == ".gitignore":
            raise OSError("disk gone")
        return orig_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(ConfigError):
        effective_coverage(bundle, repo)


# --------------------------------------------------------------------------- #
# load_config_dir wiring — MonitorConfig.coverage IS effective_coverage(...).
# --------------------------------------------------------------------------- #


def test_load_config_dir_coverage_is_effective(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    config = load_config_dir(cfg)
    bundle = load_bundle(cfg)
    assert config.coverage == effective_coverage(bundle, repo)
    # And it is NOT the raw index coverage (which had no include/exclude derived).
    assert any(_translate(g).match("agent/backend.py") for g in config.coverage.include)


def test_load_bundle_still_returns_bundle(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    bundle = load_bundle(cfg)
    # load_bundle's config.coverage is the derived one too (wired in one place).
    assert bundle.config.coverage == effective_coverage(bundle, repo)


# --------------------------------------------------------------------------- #
# Integration GOAL test — run the REAL coverage path over the derived globs and
# assert the universe is EXACTLY {agent/backend.py, agent/sub/deep.py}; the
# .log/.rpt/.pyc are absent, and the percent denominator excludes them.
# --------------------------------------------------------------------------- #


def test_integration_universe_is_format_matched_non_ignored(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    config = load_config_dir(cfg)

    inv = discover_files(
        repo, include=config.coverage.include, exclude=config.coverage.exclude
    )
    discovered = {f.path for f in inv.files}
    # EXACTLY the .py files under agent (direct + nested), nothing else.
    assert discovered == {"agent/backend.py", "agent/sub/deep.py"}
    # The non-.py and ignored artifacts are absent.
    assert "agent/run.log" not in discovered
    assert "agent/build.rpt" not in discovered
    assert "agent/__pycache__/x.pyc" not in discovered

    sym_inv = discover_symbols(inv, repo)
    report = resolve_coverage(config, sym_inv)
    universe = {f.path for f in report.files}
    assert universe == {"agent/backend.py", "agent/sub/deep.py"}
    # backend.py is documented (a code_ref names it); deep.py is the gap.
    documented = {f.path for f in report.documented_files}
    undocumented = {f.path for f in report.undocumented_files}
    assert documented == {"agent/backend.py"}
    assert undocumented == {"agent/sub/deep.py"}
    # The file-% denominator is the 2-file universe (no .log/.rpt/.pyc inflate it).
    assert report.percent_files == pytest.approx(50.0)


# --------------------------------------------------------------------------- #
# Z-01a — nested units: deepest-wins format scoping in effective_coverage.
# --------------------------------------------------------------------------- #

# Parent unit ``core`` owns ``agent`` and scopes ``.py``; child unit ``deep`` owns
# the nested ``agent/sub`` and scopes ONLY ``.log``. A ``.py`` file under the child
# dir is the parent's format but NOT the child's: deepest-wins must EXCLUDE it.
_NEST_INDEX = """\
---
cdmon-config-version: "2.0.0"
repo: demo
generated-by: cdmon
updated: "2026-06-07"
---
root: "../.."
version: "2.0.0"
units:
  - file: agent.yaml
  - file: deep.yaml
"""

_NEST_PARENT_UNIT = """\
---
cdmon-config-version: "2.0.0"
unit: agent
title: "Agent coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - agent
source-files-format:
  - ".py"
documents:
  - id: agent-doc
    path: docs/agent.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: agent/backend.py
"""

_NEST_CHILD_UNIT = """\
---
cdmon-config-version: "2.0.0"
unit: deep
title: "Deep (logs only) coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - agent/sub
source-files-format:
  - ".log"
documents:
  - id: deep-doc
    path: docs/deep.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: agent/sub/deep.log
"""


def test_effective_coverage_child_format_mismatch_excluded(tmp_path: Path) -> None:
    """A ``.py`` file under a CHILD unit dir whose format is ``.log`` is EXCLUDED
    from the coverage universe though the PARENT (``.py``) would have kept it —
    deepest-wins format scoping (Z-01a)."""
    repo, cfg = _build_repo(
        tmp_path,
        index_text=_NEST_INDEX,
        unit_text=_NEST_PARENT_UNIT,
        ignore_text=_IGNORE_GITIGNORE_OFF,
        gitignore_text=None,
    )
    (cfg / "deep.yaml").write_text(_NEST_CHILD_UNIT, encoding="utf-8")
    # Add a .log under the child so the child has something it DOES scope.
    (repo / "agent" / "sub" / "deep.log").write_text("log\n", encoding="utf-8")

    bundle = load_bundle(cfg)
    config = bundle.config
    inv = discover_files(
        repo, include=config.coverage.include, exclude=config.coverage.exclude
    )
    discovered = {f.path for f in inv.files}

    # The parent .py file (directly under agent) IS in the universe.
    assert "agent/backend.py" in discovered
    # The child's .log file IS in the universe (child scopes .log).
    assert "agent/sub/deep.log" in discovered
    # The .py file under the CHILD dir is EXCLUDED — the parent format would have
    # kept it, but deepest-wins gives the child (.log-only) the say.
    assert "agent/sub/deep.py" not in discovered


def test_effective_coverage_child_rescopes_same_ext_kept(tmp_path: Path) -> None:
    """Reverse of the mismatch: parent scopes ``.log`` only, child re-scopes
    ``.py`` — a ``.py`` file under the child is KEPT (the deeper unit wins)."""
    parent = _NEST_PARENT_UNIT.replace('  - ".py"', '  - ".log"', 1)
    child = _NEST_CHILD_UNIT.replace('  - ".log"', '  - ".py"', 1)
    repo, cfg = _build_repo(
        tmp_path,
        index_text=_NEST_INDEX,
        unit_text=parent,
        ignore_text=_IGNORE_GITIGNORE_OFF,
        gitignore_text=None,
    )
    (cfg / "deep.yaml").write_text(child, encoding="utf-8")

    bundle = load_bundle(cfg)
    config = bundle.config
    inv = discover_files(
        repo, include=config.coverage.include, exclude=config.coverage.exclude
    )
    discovered = {f.path for f in inv.files}
    # Child .py kept (child re-scopes .py); parent .log kept; parent .py NOT
    # scoped by parent (parent is .log-only) so absent.
    assert "agent/sub/deep.py" in discovered
    assert "agent/run.log" in discovered
    assert "agent/backend.py" not in discovered


def test_integration_log_only_in_format_is_covered(tmp_path: Path) -> None:
    """If a unit's source-files-format is ['.log'], the .log files ARE the
    universe and the .py files are NOT (scoping is per-unit, format-driven)."""
    unit = _UNIT_YAML.replace('  - ".py"', '  - ".log"')
    # gitignore off + no .gitignore so the *.log line does not re-exclude the
    # .log files we are now scoping IN via source-files-format.
    repo, cfg = _build_repo(
        tmp_path,
        unit_text=unit,
        ignore_text=_IGNORE_GITIGNORE_OFF,
        gitignore_text=None,
    )
    config = load_config_dir(cfg)
    inv = discover_files(
        repo, include=config.coverage.include, exclude=config.coverage.exclude
    )
    discovered = {f.path for f in inv.files}
    assert discovered == {"agent/run.log"}
