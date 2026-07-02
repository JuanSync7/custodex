"""AGT-04 — the config-authoring onboarding agent (`onboard.py`).

analyze_repo → RepoMap (deterministic, resilient — one unparseable file is a
warning, never an abort), propose_config → real UnitFile models with the
pinned owner precedence, render_plan_text → the Renovate-style plan body,
apply_plan → a load_bundle-green config/cdmon bundle.

Features: FEAT-ONBOARD-001, FEAT-ONBOARD-002
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.config import Audience, load_bundle
from custodex.errors import ConfigError
from custodex.onboard import (
    analyze_repo,
    apply_plan,
    propose_config,
    render_plan_text,
)

ALPHA = (
    'def solve(x):\n    """Doc."""\n    return x\n\n\ndef _hidden():\n    return 0\n'
)
BETA = "class Engine:\n    def run(self):\n        return 1\n"


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fixture_repo(tmp_path: Path) -> Path:
    _write(tmp_path, "alpha/core.py", ALPHA)
    _write(tmp_path, "alpha/util.py", "X = 1\n")
    _write(tmp_path, "beta/engine.py", BETA)
    _write(tmp_path, "README.md", "# Widget\n\nA thing.\n")
    _write(tmp_path, "docs/design.md", "# Design\n\nNotes.\n")
    _write(tmp_path, "AGENTS.md", "build: make\n")
    return tmp_path


class TestAnalyzeRepo:
    def test_packages_docs_and_signals(self, tmp_path: Path) -> None:
        m = analyze_repo(_fixture_repo(tmp_path))
        assert [p.name for p in m.packages] == ["alpha", "beta"]
        alpha = m.packages[0]
        assert alpha.files == ("alpha/core.py", "alpha/util.py")
        assert alpha.public_symbols == 2  # solve + X (not _hidden)
        assert {d.path for d in m.docs} == {"README.md", "docs/design.md"}
        readme = next(d for d in m.docs if d.path == "README.md")
        assert readme.guessed_audience is Audience.USER_GUIDE
        assert readme.title == "Widget"
        design = next(d for d in m.docs if d.path == "docs/design.md")
        assert design.guessed_audience is Audience.ENG_GUIDE
        assert m.signals["readme"] == "README.md"
        assert m.signals["agents_md"] == "AGENTS.md"
        assert m.signals["docs_dir"] == "docs"
        assert "existing_config" not in m.signals

    def test_unparseable_file_warns_never_aborts(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        _write(root, "alpha/broken.py", "def broken(:\n")
        m = analyze_repo(root)
        assert any("broken.py" in w for w in m.warnings)
        assert [p.name for p in m.packages] == ["alpha", "beta"]

    def test_loose_top_level_py_files_warn(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        _write(root, "setup.py", "X = 1\n")
        m = analyze_repo(root)
        assert any("top-level .py" in w for w in m.warnings)

    def test_existing_config_is_signalled(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        _write(root, "config/cdmon/index.yaml", "x: 1\n")
        m = analyze_repo(root)
        assert m.signals["existing_config"] == "config/cdmon"

    def test_missing_root_is_loud(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError):
            analyze_repo(tmp_path / "nope")

    def test_deterministic_double_run(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        assert analyze_repo(root) == analyze_repo(root)


class TestProposeConfig:
    def test_one_unit_per_package_plus_readme(self, tmp_path: Path) -> None:
        m = analyze_repo(_fixture_repo(tmp_path))
        plan = propose_config(m, repo="widget", now="2026-07-02T10:00:00Z")
        assert [u.frontmatter.unit for u in plan.units] == ["alpha", "beta"]
        alpha = plan.units[0]
        assert alpha.dir_covered == ("alpha",)
        ids = [d.id for d in alpha.documents]
        assert ids == ["alpha-api", "readme"]
        api = alpha.documents[0]
        assert api.audience is Audience.ENG_GUIDE
        assert [r.path for r in api.code_refs] == ["alpha/core.py", "alpha/util.py"]
        readme = alpha.documents[1]
        assert readme.audience is Audience.USER_GUIDE
        assert readme.code_refs == ()
        assert plan.docs_to_scaffold == ("alpha-api", "beta-api")
        assert "  - file: alpha.yaml" in plan.index_text

    def test_owner_precedence_and_unassigned_note(self, tmp_path: Path) -> None:
        m = analyze_repo(_fixture_repo(tmp_path))
        named = propose_config(
            m, repo="w", now="2026-07-02T10:00:00Z", owner="platform"
        )
        assert all(u.frontmatter.owner == "platform" for u in named.units)
        assert not any("unassigned" in n for n in named.notes)
        anon = propose_config(m, repo="w", now="2026-07-02T10:00:00Z")
        assert all(u.frontmatter.owner == "unassigned" for u in anon.units)
        assert any("unassigned" in n for n in anon.notes)

    def test_reserved_stem_package_is_skipped_with_note(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        _write(root, "index/mod.py", "Y = 1\n")
        plan = propose_config(analyze_repo(root), repo="w", now="2026-07-02T10:00:00Z")
        assert [u.frontmatter.unit for u in plan.units] == ["alpha", "beta"]
        assert any("reserved" in n for n in plan.notes)

    def test_no_packages_is_loud(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", "# Empty\n")
        with pytest.raises(ConfigError, match="nothing to onboard"):
            propose_config(analyze_repo(tmp_path), repo="w", now="2026-07-02T10:00:00Z")

    def test_render_plan_sections(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        _write(root, "alpha/broken.py", "def broken(:\n")
        plan = propose_config(
            analyze_repo(root), repo="widget", now="2026-07-02T10:00:00Z"
        )
        text = render_plan_text(plan)
        assert "## Detected surfaces" in text
        assert "## Proposed mapping" in text
        assert "## What to expect on --apply" in text
        assert "package alpha/" in text
        assert "warning:" in text  # the unparseable file is VISIBLE


class TestApplyPlan:
    def test_apply_yields_load_bundle_green_config(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        plan = propose_config(
            analyze_repo(root), repo="widget", now="2026-07-02T10:00:00Z"
        )
        config_dir = root / "config" / "cdmon"
        written = apply_plan(plan, config_dir, now="2026-07-02T10:00:00Z")
        assert (config_dir / "index.yaml").is_file()
        assert (config_dir / "alpha.yaml").is_file()
        assert (config_dir / "doc-style.yaml").is_file()
        # The DOA fix: the referenced writing templates were materialized.
        assert (root / "templates" / "writing" / "tone" / "precise.md") in written or (
            root / "templates" / "writing" / "tone" / "precise.md"
        ).is_file()
        bundle = load_bundle(config_dir)  # the arrive-green core assertion
        assert {d.id for d in bundle.config.documents} == {
            "alpha-api",
            "beta-api",
            "readme",
        }

    def test_apply_refuses_nonempty_config_dir(self, tmp_path: Path) -> None:
        root = _fixture_repo(tmp_path)
        plan = propose_config(analyze_repo(root), repo="w", now="2026-07-02T10:00:00Z")
        config_dir = root / "config" / "cdmon"
        _write(root, "config/cdmon/index.yaml", "x: 1\n")
        with pytest.raises(ConfigError, match="refusing"):
            apply_plan(plan, config_dir, now="2026-07-02T10:00:00Z")
