"""AGT-05 — `cdx write-doc` end to end: dry-run draft → --apply → born in sync.

One command takes an undocumented fixture module to a registered, conformant,
`cdx check`-green document with authored (mock-deterministic) prose; the unit
YAML's hand comments survive the registration splice; unit attribution uses
deepest-wins dir-covered when --unit is omitted. Offline, no network (K4).

Features: FEAT-DOCWRITER-001
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from custodex.cli import app

runner = CliRunner()

_UNIT = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "core docs"
owner: eng
created: "2026-07-01"
updated: "2026-07-01"
---
# Hand comment: survives write-doc.
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
    (tmp_path / "src" / "gamma.py").write_text(
        'def turbo_boost(x):\n    """Boost."""\n    return x * 2\n', encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "existing.md").write_text("# E\n\nProse.\n", "utf-8")
    return cfg_dir


def test_dry_run_prints_draft_and_writes_nothing(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    result = runner.invoke(app, ["write-doc", "src/gamma.py", "--config", str(cfg_dir)])
    assert result.exit_code == 0, result.output
    assert "would register 'src-gamma' in core.yaml" in result.output
    assert "turbo_boost" in result.output
    assert "dry-run — nothing written" in result.output
    assert not (tmp_path / "docs" / "src-gamma.md").exists()
    assert "src-gamma" not in (cfg_dir / "core.yaml").read_text(encoding="utf-8")


def test_apply_registers_writes_and_next_check_covers_it(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    result = runner.invoke(
        app, ["write-doc", "src/gamma.py", "--apply", "--config", str(cfg_dir)]
    )
    assert result.exit_code == 0, result.output
    assert "self-check: 0 drift(s) on the new doc" in result.output

    doc = (tmp_path / "docs" / "src-gamma.md").read_text(encoding="utf-8")
    assert "turbo_boost" in doc and "> TODO" not in doc
    unit_text = (cfg_dir / "core.yaml").read_text(encoding="utf-8")
    assert "# Hand comment: survives write-doc." in unit_text
    assert "id: src-gamma" in unit_text

    # The new doc participates in the standing drift loop: change the source
    # and the doc is flagged; heal closes it (the B-06 llm region re-authors).
    (tmp_path / "src" / "gamma.py").write_text(
        "def turbo_boost(x, y):\n    return x * y\n\n\ndef extra():\n    return 1\n",
        encoding="utf-8",
    )
    check = runner.invoke(app, ["check", "--config", str(cfg_dir)])
    assert check.exit_code == 1
    assert "src-gamma" in check.output
    heal = runner.invoke(app, ["monitor", "--apply", "--config", str(cfg_dir)])
    assert heal.exit_code == 0, heal.output
    healed = (tmp_path / "docs" / "src-gamma.md").read_text(encoding="utf-8")
    assert "extra" in healed  # the authored overview re-authored with the surface


def test_write_doc_loud_paths(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    missing = runner.invoke(app, ["write-doc", "src/nope.py", "--config", str(cfg_dir)])
    assert missing.exit_code == 1 and "not a file" in missing.output

    bad_aud = runner.invoke(
        app,
        [
            "write-doc",
            "src/gamma.py",
            "--audience",
            "bogus",
            "--config",
            str(cfg_dir),
        ],
    )
    assert bad_aud.exit_code == 1 and "bogus" in bad_aud.output

    # A target outside every unit's dir-covered needs an explicit --unit.
    (tmp_path / "loose.py").write_text("X = 1\n", encoding="utf-8")
    no_unit = runner.invoke(app, ["write-doc", "loose.py", "--config", str(cfg_dir)])
    assert no_unit.exit_code == 1 and "--unit" in no_unit.output

    # Single-file config: loud.
    single = tmp_path / "single"
    single.mkdir()
    (single / "a.py").write_text("X = 1\n", encoding="utf-8")
    (single / "cdmon.yaml").write_text(
        'version: "1.0.0"\nroot: .\ndocuments:\n'
        "  - id: a\n    path: a.md\n    audience: eng-guide\n",
        encoding="utf-8",
    )
    sf = runner.invoke(
        app, ["write-doc", "a.py", "--config", str(single / "cdmon.yaml")]
    )
    assert sf.exit_code == 1 and "single file" in sf.output


def test_onboard_then_write_doc_composes(
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001 - pytest fixture
) -> None:
    """PR #20 fresh-review must-fix: the epic's flagship flow must COMPOSE.

    `cdx onboard --apply` emits dump_unit_file-style unit YAML (0-indent block
    sequences); `cdx write-doc --apply` must register into that exact style —
    it used to splice invalid YAML and abort on every onboarded repo (the very
    command the AGT-06 DOCUMENT_GAP suggestion embeds).
    """
    import custodex.cli as cli_mod

    monkeypatch.setattr(cli_mod, "_git_user_name", lambda root: "you")
    repo = tmp_path / "adopter"
    pkg = repo / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "alpha.py").write_text(
        'def start(x):\n    """Start."""\n    return x\n', encoding="utf-8"
    )
    (repo / "README.md").write_text("# Adopter\n\nHello.\n", encoding="utf-8")

    onboarded = runner.invoke(
        app, ["onboard", "--path", str(repo), "--apply", "--owner", "you"]
    )
    assert onboarded.exit_code == 0, onboarded.output

    (pkg / "gamma.py").write_text(
        'def turbo_boost(x):\n    """Boost."""\n    return x * 2\n', encoding="utf-8"
    )
    cfg_dir = repo / "config" / "cdmon"
    written = runner.invoke(
        app,
        ["write-doc", "mypkg/gamma.py", "--apply", "--config", str(cfg_dir)],
    )
    assert written.exit_code == 0, written.output

    check = runner.invoke(app, ["check", "--config", str(cfg_dir)])
    assert check.exit_code == 0, check.output
