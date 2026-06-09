"""W-02 Part A — canonical config/cdmon v2 templates + scaffolder + endpoint.

Each canonical template ROUND-TRIPS through its N-01..N-05 loader; the scaffolder
produces a ``load_bundle``-valid directory; ``cdmon init --v2`` scaffolds (and is
loud on an existing dir without ``--force``); and ``GET /config/templates`` serves
all four. Offline (K4), deterministic (K10).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from code_doc_monitor import cli
from code_doc_monitor.cli import app
from code_doc_monitor.config import (
    load_bundle,
    load_ignore_file,
    load_index_file,
    load_unit_file,
)
from code_doc_monitor.docstyle import load_doc_style
from code_doc_monitor.errors import ConfigError
from code_doc_monitor.templates_v2 import (
    DOC_STYLE_TEMPLATE,
    EXAMPLE_UNIT_STEM,
    IGNORE_TEMPLATE,
    INDEX_TEMPLATE,
    UNIT_TEMPLATE,
    V2_TEMPLATES,
    scaffold_config_dir,
)

runner = CliRunner()

# The doc-style template references these writing templates (CONFIG-V2 §1.4/§2).
_REQUIRED_WRITING_TEMPLATES = (
    ("document-type", "api-reference"),
    ("tone", "precise"),
    ("writing-style", "reference-dense"),
    ("vocabulary", "engine-domain"),
)


def _write_writing_templates(repo_root: Path) -> Path:
    """Materialize the writing templates the doc-style map names; return the root."""
    templates_root = repo_root / "templates" / "writing"
    for category, name in _REQUIRED_WRITING_TEMPLATES:
        d = templates_root / category
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    return templates_root


def _fill(template: str) -> str:
    return template.format(repo="my-repo", now="2026-06-07")


# --------------------------------------------------------------------------- #
# Round-trip: each template loads + validates via its loader.
# --------------------------------------------------------------------------- #


def test_unit_template_round_trips(tmp_path: Path) -> None:
    # The unit frontmatter `unit:` must equal the filename stem.
    path = tmp_path / f"{EXAMPLE_UNIT_STEM}.yaml"
    path.write_text(_fill(UNIT_TEMPLATE), encoding="utf-8")
    unit = load_unit_file(path)
    assert unit.frontmatter.unit == EXAMPLE_UNIT_STEM
    assert unit.dir_covered  # >= 1
    assert all(ext.startswith(".") for ext in unit.source_files_format)
    assert unit.documents


def test_unit_template_raw_is_loadable(tmp_path: Path) -> None:
    # Even WITHOUT placeholder substitution the raw template is valid YAML that
    # round-trips (placeholders are quoted strings).
    path = tmp_path / f"{EXAMPLE_UNIT_STEM}.yaml"
    path.write_text(UNIT_TEMPLATE, encoding="utf-8")
    unit = load_unit_file(path)
    assert unit.frontmatter.unit == EXAMPLE_UNIT_STEM


def test_index_template_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "index.yaml"
    path.write_text(_fill(INDEX_TEMPLATE), encoding="utf-8")
    index = load_index_file(path)
    assert index.frontmatter.repo == "my-repo"
    assert index.root == "../.."  # the canonical root convention
    assert [u.file for u in index.units] == [f"{EXAMPLE_UNIT_STEM}.yaml"]
    assert index.ignore == "ignore.yaml"
    assert index.doc_style == "doc-style.yaml"


def test_ignore_template_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "ignore.yaml"
    path.write_text(_fill(IGNORE_TEMPLATE), encoding="utf-8")
    ignore = load_ignore_file(path)
    assert ignore.gitignore is True
    assert "*.rpt" in ignore.patterns


def test_doc_style_template_round_trips(tmp_path: Path) -> None:
    templates_root = _write_writing_templates(tmp_path)
    path = tmp_path / "doc-style.yaml"
    path.write_text(_fill(DOC_STYLE_TEMPLATE), encoding="utf-8")
    doc_style = load_doc_style(path, templates_root=templates_root)
    assert doc_style.frontmatter.kind == "doc-style-map"
    sel = doc_style.style_for("example-guide")
    assert sel.document_type == "api-reference"
    assert sel.vocabulary == "engine-domain"


# --------------------------------------------------------------------------- #
# scaffold_config_dir -> a load_bundle-valid directory.
# --------------------------------------------------------------------------- #


def test_scaffold_config_dir_is_load_bundle_valid(tmp_path: Path) -> None:
    repo_root = tmp_path
    _write_writing_templates(repo_root)
    config_dir = repo_root / "config" / "cdmon"

    scaffold_config_dir(config_dir, repo="my-repo", now="2026-06-07")

    # All four files exist.
    for name in (
        "index.yaml",
        f"{EXAMPLE_UNIT_STEM}.yaml",
        "ignore.yaml",
        "doc-style.yaml",
    ):
        assert (config_dir / name).is_file()

    # Each individual loader accepts its scaffolded file.
    index = load_index_file(config_dir / "index.yaml")
    assert index.frontmatter.repo == "my-repo"
    load_unit_file(config_dir / f"{EXAMPLE_UNIT_STEM}.yaml")
    load_ignore_file(config_dir / "ignore.yaml")
    load_doc_style(
        config_dir / "doc-style.yaml",
        templates_root=repo_root / "templates" / "writing",
    )

    # The whole bundle loads + merges (root "../.." resolves to the repo root, so
    # the doc-style templates_root finds the writing templates).
    bundle = load_bundle(config_dir)
    assert bundle.index.frontmatter.repo == "my-repo"
    assert [d.id for d in bundle.config.documents] == ["example-guide"]
    assert bundle.doc_style is not None


def test_scaffold_substitutes_repo_and_now(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "cdmon"
    scaffold_config_dir(config_dir, repo="acme-svc", now="2030-01-02")
    index_text = (config_dir / "index.yaml").read_text(encoding="utf-8")
    assert "acme-svc" in index_text
    assert "2030-01-02" in index_text
    assert "{repo}" not in index_text and "{now}" not in index_text


def test_scaffold_wraps_oserror(tmp_path: Path) -> None:
    # A file where the config dir should be makes mkdir fail -> loud ConfigError.
    clash = tmp_path / "config"
    clash.write_text("not a dir", encoding="utf-8")
    with pytest.raises(ConfigError):
        scaffold_config_dir(clash / "cdmon", repo="x", now="2026-06-07")


# --------------------------------------------------------------------------- #
# cdmon init --v2.
# --------------------------------------------------------------------------- #


def test_init_v2_scaffolds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_now", lambda: "2026-06-07")
    monkeypatch.chdir(tmp_path)
    _write_writing_templates(tmp_path)

    result = runner.invoke(app, ["init", "--v2", "--repo", "demo-repo"])
    assert result.exit_code == 0, result.output
    config_dir = tmp_path / "config" / "cdmon"
    assert (config_dir / "index.yaml").is_file()

    bundle = load_bundle(config_dir)
    assert bundle.index.frontmatter.repo == "demo-repo"


def test_init_v2_custom_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_now", lambda: "2026-06-07")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["init", "--v2", "--config-dir", "cfg/here", "--repo", "r"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "cfg" / "here" / "index.yaml").is_file()


def test_init_v2_loud_on_existing_dir_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_now", lambda: "2026-06-07")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "cdmon").mkdir(parents=True)

    result = runner.invoke(app, ["init", "--v2"])
    assert result.exit_code == 1
    assert "Refusing to overwrite" in result.output


def test_init_v2_force_overwrites_existing_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_now", lambda: "2026-06-07")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "cdmon").mkdir(parents=True)

    result = runner.invoke(app, ["init", "--v2", "--force", "--repo", "r"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "config" / "cdmon" / "index.yaml").is_file()


def test_init_without_v2_writes_single_file_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The single-file behavior is unchanged: --path still writes the one template.
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--path", "cdmon.yaml"])
    assert result.exit_code == 0, result.output
    text = (tmp_path / "cdmon.yaml").read_text(encoding="utf-8")
    assert "code-doc-monitor configuration" in text
    assert not (tmp_path / "config" / "cdmon").exists()


# --------------------------------------------------------------------------- #
# GET /config/templates endpoint.
# --------------------------------------------------------------------------- #


def test_config_templates_endpoint_returns_all_four() -> None:
    pytest.importorskip("fastapi", reason="the [server] extra is not installed")
    from fastapi.testclient import TestClient

    from code_doc_monitor.server import InMemoryStore, create_app

    client = TestClient(create_app(InMemoryStore()))
    resp = client.get("/config/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"unit", "index", "ignore", "doc_style"}
    assert body == V2_TEMPLATES  # deterministic, raw templates
    # No auth header required (public reference).
    assert "cdmon-config-version" in body["unit"]
