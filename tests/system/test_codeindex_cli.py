"""CIX-01 — `cdx codeindex` end-to-end (offline, via CliRunner).

Read-only summary by default (K1); `--write` is the one mutating mode and is
idempotent + stamp-blind (K7); `--check` gates on staleness against the tree.

Features: FEAT-CODEINDEX-001
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from custodex.cli import app

runner = CliRunner()

_CODE = '''"""A tiny module."""

def doubler(x):
    """Double x."""
    return x * 2
'''


def _fixture(tmp_path: Path) -> Path:
    (tmp_path / "code.py").write_text(_CODE, encoding="utf-8")
    config_path = tmp_path / "cdmon.yaml"
    config_path.write_text(
        'version: "1.0.0"\nroot: "."\ndocuments: []\n', encoding="utf-8"
    )
    return config_path


def test_default_is_a_read_only_summary(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["codeindex"])
    assert result.exit_code == 0, result.output
    assert "1 file(s), 1 symbol(s) (1 public)" in result.output
    assert not (tmp_path / ".cdmon").exists()  # K1: nothing written


def test_write_then_write_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["codeindex", "--write", "--ref", "aaa111"])
    assert first.exit_code == 0, first.output
    assert "wrote" in first.output
    # Same tree, new stamp: unchanged, old stamp survives (stamp-blind, K7).
    second = runner.invoke(app, ["codeindex", "--write", "--ref", "bbb222"])
    assert second.exit_code == 0, second.output
    assert "unchanged" in second.output
    payload = json.loads(
        (tmp_path / ".cdmon" / "code-index.json").read_text(encoding="utf-8")
    )
    assert payload["source_sha"] == "aaa111"


def test_check_missing_stale_and_in_sync(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    missing = runner.invoke(app, ["codeindex", "--check"])
    assert missing.exit_code == 1
    assert "MISSING" in missing.output

    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    clean = runner.invoke(app, ["codeindex", "--check"])
    assert clean.exit_code == 0, clean.output
    assert "in sync" in clean.output

    (tmp_path / "code.py").write_text(_CODE + "\nEXTRA = 1\n", encoding="utf-8")
    stale = runner.invoke(app, ["codeindex", "--check"])
    assert stale.exit_code == 1
    assert "STALE" in stale.output


def test_json_output_round_trips(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["codeindex", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0.0"
    assert [f["path"] for f in payload["files"]] == ["code.py"]
    names = [s["name"] for s in payload["files"][0]["symbols"]]
    assert names == ["doubler"]


def test_missing_config_is_a_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["codeindex"])
    assert result.exit_code == 1
    assert "error:" in result.output


def test_an_unreadable_coverage_file_is_a_clean_error(
    tmp_path: Path, monkeypatch
) -> None:
    """An unreadable coverage file — a dangling ``run.sh`` symlink, which no
    symbol extractor opens first — used to escape `cdx codeindex` as a bare
    FileNotFoundError traceback. It is now the typed ExtractionError (K8):
    a clean ``error:`` line naming the file, exit 1, nothing written."""
    # Feature: FEAT-CODEINDEX-001
    _fixture(tmp_path).write_text(
        'version: "1.0.0"\nroot: "."\ndocuments: []\n'
        'coverage:\n  include: ["**/*.py", "**/*.sh"]\n  exclude: []\n',
        encoding="utf-8",
    )
    (tmp_path / "run.sh").symlink_to("missing-target.sh")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["codeindex", "--write"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)  # handled, not a traceback
    assert "error:" in result.stderr and "run.sh" in result.stderr
    assert not (tmp_path / ".cdmon").exists()


class _Py310Ast:
    """``ast`` as Python 3.10 — the supported floor — behaves: ``parse``
    raises ValueError, not SyntaxError, for a NUL byte. Everything else is
    the real module, so patching the extractor's ``ast`` name is scoped."""

    def __getattr__(self, name: str) -> object:
        import ast

        return getattr(ast, name)

    @staticmethod
    def parse(source: object, *args: object, **kwargs: object) -> object:
        import ast

        if isinstance(source, str) and "\x00" in source:
            raise ValueError("source code string cannot contain null bytes")
        return ast.parse(source, *args, **kwargs)  # type: ignore[call-overload]


def test_a_nul_byte_on_python_3_10_is_a_clean_error(
    tmp_path: Path, monkeypatch
) -> None:
    """On Python 3.10 the extractor's parser raises an untyped ValueError
    for a NUL byte; `cdx codeindex` reports it as the typed ExtractionError
    (K8) — a clean ``error:`` naming the file, exit 1, nothing written."""
    # Feature: FEAT-CODEINDEX-001
    _fixture(tmp_path)
    (tmp_path / "bad.py").write_bytes(b"x = 1\n\x00\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("custodex.extract.ast", _Py310Ast())
    result = runner.invoke(app, ["codeindex", "--write"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)  # handled, not a traceback
    assert "error:" in result.stderr and "bad.py" in result.stderr
    assert not (tmp_path / ".cdmon").exists()


def test_a_value_the_extractor_cannot_render_is_a_clean_error(
    tmp_path: Path, monkeypatch
) -> None:
    """A file that parses can still fail extraction: a hex literal past the
    int-to-str digit limit makes the extractor's ``ast.unparse`` raise
    ValueError. `cdx codeindex` and `cdx impact` report the typed
    ExtractionError (K8) — a clean ``error:`` naming the file, exit 1,
    nothing written — never a ValueError traceback."""
    # Feature: FEAT-CODEINDEX-001
    limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
    if not limit:  # e.g. PYTHONINTMAXSTRDIGITS=0
        pytest.skip("this interpreter has no int-to-str digit limit")
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["codeindex", "--write"]).exit_code == 0
    stored = (tmp_path / ".cdmon" / "code-index.json").read_bytes()
    (tmp_path / "big.py").write_text("X = 0x" + "f" * (limit + 1) + "\n", "utf-8")
    for verb in (["codeindex", "--write"], ["impact"]):
        result = runner.invoke(app, verb)
        assert result.exit_code == 1, verb
        assert isinstance(result.exception, SystemExit), verb  # not a traceback
        assert "error:" in result.stderr and "big.py" in result.stderr, verb
    assert (tmp_path / ".cdmon" / "code-index.json").read_bytes() == stored
