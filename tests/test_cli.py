"""CDM-06 — tests for the full `cdmon` CLI (offline, via CliRunner)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from code_doc_monitor.blocks import symbol_table
from code_doc_monitor.cli import app
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.extract import build_document_surface

runner = CliRunner()

CODE = '''\
"""A tiny module."""


def public_fn(x: int) -> int:
    """Double x."""
    return x * 2
'''


def _write_config(tmp_path: Path) -> Path:
    cfg = (
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "eng-guide"\n'
        "    code_refs:\n"
        '      - path: "code.py"\n'
        '    region_keys: ["symbols"]\n'
        "backend:\n"
        '  kind: "mock"\n'
    )
    config_path = tmp_path / "cdmon.yaml"
    config_path.write_text(cfg, encoding="utf-8")
    return config_path


def _spec() -> DocumentSpec:
    return DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )


def _make_fixture(tmp_path: Path, *, clean: bool) -> Path:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    config_path = _write_config(tmp_path)
    spec = _spec()
    config = MonitorConfig(root=".", documents=(spec,))
    surface = build_document_surface(spec, tmp_path)
    body = symbol_table(surface) if clean else "OUT OF DATE"
    (tmp_path / "guide.md").write_text(
        f"---\ncdm:\n  fingerprint: {surface.surface_hash()}\n---\n"
        "# Guide\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        f"{body}\n"
        "<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    _ = config
    return config_path


def test_check_exit_1_on_drift(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "drift" in result.stdout.lower()


def test_check_exit_0_when_clean(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.stdout
    assert "clean" in result.stdout.lower()


def test_monitor_apply_closes_drift(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["monitor", "--apply"])
    assert result.exit_code == 0, result.stdout
    assert "FIX" in result.stdout
    # The review log was written under the default location.
    assert (tmp_path / ".cdmon" / "review-log.jsonl").is_file()
    # A re-check is now clean.
    assert runner.invoke(app, ["check"]).exit_code == 0


def test_monitor_no_apply_leaves_drift(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["monitor", "--no-apply"])
    assert result.exit_code == 1
    assert "remaining" in result.output.lower()


def test_surface_lists_docs(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["surface"])
    assert result.exit_code == 0, result.stdout
    assert "guide" in result.stdout
    assert "eng-guide" in result.stdout


def test_surface_json(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["surface", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload[0]["doc_id"] == "guide"
    assert "symbols" in payload[0]


def test_report_prints_counts_after_monitor(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0, result.stdout
    summary = json.loads(result.stdout)
    assert summary["total"] >= 1
    assert "FIX" in summary["by_verdict"]


def test_report_empty_log(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["total"] == 0


def test_report_verdict_lists_matching_records(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report", "--verdict", "FIX"])
    assert result.exit_code == 0, result.stdout
    assert "FIX record(s)" in result.stdout
    assert "guide" in result.stdout
    assert "cause:" in result.stdout


def test_report_verdict_is_case_insensitive(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report", "--verdict", "fix"])
    assert result.exit_code == 0, result.stdout
    assert "FIX record(s)" in result.stdout


def test_report_verdict_no_match_is_clean(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report", "--verdict", "ESCALATE"])
    assert result.exit_code == 0, result.stdout
    assert "no ESCALATE records" in result.stdout


def test_report_verdict_json_emits_full_records(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report", "--verdict", "FIX", "--json"])
    assert result.exit_code == 0, result.stdout
    records = json.loads(result.stdout)
    assert records and records[0]["verdict"] == "FIX"
    assert records[0]["doc_id"] == "guide"


def test_report_bad_verdict_clean_error(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["report", "--verdict", "BOGUS"])
    assert result.exit_code == 1
    assert "unknown verdict" in result.output
    assert "Traceback" not in result.output


def test_schema_prints_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert "schema_version" in parsed["properties"]


def test_schema_out_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "schema.json"
    result = runner.invoke(app, ["schema", "--out", str(out)])
    assert result.exit_code == 0, result.stdout
    assert out.is_file()
    assert "schema_version" in json.loads(out.read_text(encoding="utf-8"))["properties"]


def test_bad_config_path_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output
    # A clean message, not a traceback (K8).
    assert "Traceback" not in result.output


def test_surface_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["surface", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output


def test_monitor_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["monitor", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output


def test_report_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["report", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output


# --- CDM-08: layout lint + new-doc scaffolding -------------------------------


def test_new_doc_scaffolds_conformant_in_sync_doc(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["new-doc", "guide"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "guide.md").is_file()
    # The scaffold passes both gates immediately.
    assert runner.invoke(app, ["lint"]).exit_code == 0
    assert runner.invoke(app, ["check"]).exit_code == 0


def test_new_doc_unknown_id_clean_error(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["new-doc", "nope"])
    assert result.exit_code == 1
    assert "no document with id" in result.output
    assert "Traceback" not in result.output


def test_new_doc_refuses_to_clobber(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["new-doc", "guide"]).exit_code == 0
    again = runner.invoke(app, ["new-doc", "guide"])
    assert again.exit_code == 1
    assert "Refusing to overwrite" in again.output
    assert runner.invoke(app, ["new-doc", "guide", "--force"]).exit_code == 0


def test_lint_flags_legacy_doc_then_clean_after_scaffold(
    tmp_path: Path, monkeypatch
) -> None:
    # The legacy fixture lacks the standard front matter + purpose blockquote.
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    bad = runner.invoke(app, ["lint"])
    assert bad.exit_code == 1
    assert "MISSING_SCHEMA_VERSION" in bad.output
    # Re-scaffolding makes it conform.
    assert runner.invoke(app, ["new-doc", "guide", "--force"]).exit_code == 0
    assert runner.invoke(app, ["lint"]).exit_code == 0


def test_lint_fix_stamps_front_matter(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(
        tmp_path, clean=True
    )  # has fingerprint + title, no sv/audience/purpose
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["lint", "--fix"])
    # Front matter is stamped (reported), but the missing purpose remains.
    assert "fixed front matter" in result.output
    assert result.exit_code == 1
    assert "MISSING_PURPOSE" in result.output
    assert "MISSING_SCHEMA_VERSION" not in result.output


def test_lint_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["lint", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output
