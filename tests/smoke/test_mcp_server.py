"""Smoke test: the MCP server builds + registers + invokes the curated tools.

Drives :func:`custodex.mcp.server.build_mcp_server` in-process — no transport, no
socket (the ``build_standalone_app`` precedent) — and asserts the eight
``custodex_*`` tools register and each returns its shaped payload. Skips cleanly
when the ``[mcp]`` extra is absent (the doc2md / live_llm precedent).

Features: FEAT-MCP-001
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="the [mcp] extra is not installed")

from custodex.config import write_template  # noqa: E402
from custodex.errors import McpError  # noqa: E402
from custodex.mcp.server import build_mcp_server  # noqa: E402

# A minimal, self-contained config that resolves (no code_refs → no extraction),
# so every tool executes end-to-end and returns a clean summary.
_EMPTY_CONFIG = 'version: "2.0.0"\nroot: "."\nbackend:\n  kind: mock\ndocuments: []\n'

# The full curated surface (MCP-00 status + the seven MCP-01 read tools).
_EXPECTED_TOOLS = {
    "custodex_status",
    "custodex_drift",
    "custodex_coverage",
    "custodex_ownership",
    "custodex_staleness",
    "custodex_worklist",
    "custodex_doc_graph",
    "custodex_records",
}


def _repo(tmp_path: Path) -> Path:
    write_template(tmp_path / "cdmon.yaml")
    return tmp_path


def _empty_repo(tmp_path: Path) -> Path:
    (tmp_path / "cdmon.yaml").write_text(_EMPTY_CONFIG, encoding="utf-8")
    return tmp_path


def _call(server: Any, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke a tool and return its structured payload, tolerant of SDK shape.

    FastMCP.call_tool's return shape varies across the ``>=1.8,<2`` range: SDKs
    with structured output return a ``(content, structured_dict)`` tuple; older
    ones a bare content list. Accept both so the assertions test the PAYLOAD, not
    the SDK's return shape.
    """
    result = asyncio.run(server.call_tool(name, args or {}))
    structured = result[1] if isinstance(result, tuple) else json.loads(result[0].text)
    return structured


def test_build_mcp_server_registers_all_tools(tmp_path: Path) -> None:
    server = build_mcp_server(_repo(tmp_path))
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names >= _EXPECTED_TOOLS


def test_custodex_status_tool_returns_enriched_summary(tmp_path: Path) -> None:
    server = build_mcp_server(_empty_repo(tmp_path))
    structured = _call(server, "custodex_status")
    assert structured["repo_id"] == tmp_path.name
    assert structured["clean"] is True
    assert structured["doc_count"] == 0
    assert structured["drift_total"] == 0
    # The MCP-01 enrichment fields are present (additive over the MCP-00 shape).
    assert set(structured) == {
        "repo_id",
        "clean",
        "doc_count",
        "drift_total",
        "code_doc_drift",
        "suspect_link_drift",
        "coverage_file_pct",
        "coverage_symbol_pct",
        "docs_unowned",
        "docs_needing_review",
        "summary",
    }


def test_custodex_drift_tool_returns_shaped_list(tmp_path: Path) -> None:
    server = build_mcp_server(_empty_repo(tmp_path))
    structured = _call(server, "custodex_drift")
    assert structured["repo_id"] == tmp_path.name
    assert structured["clean"] is True
    assert structured["items"] == []


def test_custodex_coverage_tool_returns_percentages(tmp_path: Path) -> None:
    server = build_mcp_server(_empty_repo(tmp_path))
    structured = _call(server, "custodex_coverage")
    assert structured["repo_id"] == tmp_path.name
    assert "percent_public_symbols" in structured
    assert structured["top_gaps"] == []


def test_custodex_ownership_tool_reports_no_roster(tmp_path: Path) -> None:
    server = build_mcp_server(_empty_repo(tmp_path))
    structured = _call(server, "custodex_ownership")
    assert structured["repo_id"] == tmp_path.name
    assert structured["roster_checked"] is False
    assert structured["unowned_count"] == 0


def test_custodex_staleness_tool_echoes_now(tmp_path: Path) -> None:
    server = build_mcp_server(_empty_repo(tmp_path))
    structured = _call(server, "custodex_staleness")
    assert structured["repo_id"] == tmp_path.name
    assert structured["fresh"] is True
    assert isinstance(structured["now"], str) and structured["now"]


def test_custodex_worklist_tool_returns_queue(tmp_path: Path) -> None:
    server = build_mcp_server(_empty_repo(tmp_path))
    structured = _call(server, "custodex_worklist")
    assert structured["repo_id"] == tmp_path.name
    assert structured["item_count"] == 0
    assert structured["orphans_included"] is False


def test_custodex_doc_graph_tool_returns_graph(tmp_path: Path) -> None:
    server = build_mcp_server(_empty_repo(tmp_path))
    structured = _call(server, "custodex_doc_graph")
    assert structured["repo_id"] == tmp_path.name
    assert structured["edge_count"] == 0
    assert "enabled" in structured


def test_custodex_records_tool_empty_log(tmp_path: Path) -> None:
    server = build_mcp_server(_empty_repo(tmp_path))
    structured = _call(server, "custodex_records")
    assert structured["repo_id"] == tmp_path.name
    assert structured["total"] == 0
    assert structured["records"] == []


def test_build_mcp_server_refuses_configless_repo(tmp_path: Path) -> None:
    with pytest.raises(McpError):
        build_mcp_server(tmp_path)
