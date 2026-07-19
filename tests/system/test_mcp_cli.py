"""System test: the ``cdx mcp-serve`` wiring (MCP-00).

Drives the CLI with the stdio transport leaf (``_run_mcp``) monkeypatched, so the
command builds the server and hands it off WITHOUT ever opening a transport (the
``serve`` / ``_run_uvicorn`` precedent). Also covers the loud K8 refusal of a
config-less repo. Skips when the ``[mcp]`` extra is absent.

Features: FEAT-MCP-001
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the [mcp] extra is not installed")

from typer.testing import CliRunner  # noqa: E402

from custodex import cli  # noqa: E402
from custodex.cli import app  # noqa: E402
from custodex.config import write_template  # noqa: E402

runner = CliRunner()


def test_mcp_serve_builds_and_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_template(tmp_path / "cdmon.yaml")
    launched: list[object] = []
    monkeypatch.setattr(cli, "_run_mcp", lambda server: launched.append(server))
    result = runner.invoke(app, ["mcp-serve", "--repo-root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert len(launched) == 1


def test_mcp_serve_configless_repo_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["mcp-serve", "--repo-root", str(tmp_path)])
    assert result.exit_code == 1
    assert "cdmon" in result.output.lower() or "config" in result.output.lower()


def test_mcp_serve_read_only_omits_write_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The --read-only flag must thread through to build_mcp_server(read_only=True),
    # so the built server mounts the read tools but NOT the write tools (K11).
    import asyncio

    write_template(tmp_path / "cdmon.yaml")
    captured: list[object] = []
    monkeypatch.setattr(cli, "_run_mcp", lambda server: captured.append(server))
    result = runner.invoke(
        app, ["mcp-serve", "--repo-root", str(tmp_path), "--read-only"]
    )
    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    names = {tool.name for tool in asyncio.run(captured[0].list_tools())}
    assert "custodex_status" in names  # read tools present
    assert names.isdisjoint(
        {"custodex_remediate", "custodex_resolve", "custodex_sync_docs"}
    )
