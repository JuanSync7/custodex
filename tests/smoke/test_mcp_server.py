"""Smoke test: the MCP server builds + registers the curated tools (MCP-00).

Drives :func:`custodex.mcp.server.build_mcp_server` in-process — no transport, no
socket (the ``build_standalone_app`` precedent) — and asserts the
``custodex_status`` tool is registered and a config-less repo is refused. Skips
cleanly when the ``[mcp]`` extra is absent (the doc2md / live_llm precedent).

Features: FEAT-MCP-001
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the [mcp] extra is not installed")

from custodex.config import write_template  # noqa: E402
from custodex.errors import McpError  # noqa: E402
from custodex.mcp.server import build_mcp_server  # noqa: E402

# A minimal, self-contained config that resolves (no code_refs → no extraction),
# so the tool executes end-to-end and returns a clean summary.
_EMPTY_CONFIG = 'version: "2.0.0"\nroot: "."\nbackend:\n  kind: mock\ndocuments: []\n'


def _repo(tmp_path: Path) -> Path:
    write_template(tmp_path / "cdmon.yaml")
    return tmp_path


def test_build_mcp_server_registers_status_tool(tmp_path: Path) -> None:
    server = build_mcp_server(_repo(tmp_path))
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "custodex_status" in names


def test_custodex_status_tool_returns_shaped_summary(tmp_path: Path) -> None:
    (tmp_path / "cdmon.yaml").write_text(_EMPTY_CONFIG, encoding="utf-8")
    server = build_mcp_server(tmp_path)
    # FastMCP.call_tool returns (content, structured_result); assert the shaped dict.
    _content, structured = asyncio.run(server.call_tool("custodex_status", {}))
    assert structured["repo_id"] == tmp_path.name
    assert structured["clean"] is True
    assert structured["doc_count"] == 0
    assert structured["drift_total"] == 0
    assert set(structured) == {
        "repo_id",
        "clean",
        "doc_count",
        "drift_total",
        "code_doc_drift",
        "suspect_link_drift",
        "summary",
    }


def test_build_mcp_server_refuses_configless_repo(tmp_path: Path) -> None:
    with pytest.raises(McpError):
        build_mcp_server(tmp_path)
