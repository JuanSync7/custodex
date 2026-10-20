"""Smoke test: ``custodex_status`` degrades over the real FastMCP server (MCP-STATUS).

The same contract as ``tests/unit/test_mcp_status_degrade.py``, driven through
:func:`custodex.mcp.server.build_mcp_server` in-process (no transport, no socket):
with a code ref the extractor cannot read, the status tool still answers with
the drift pillar marked unavailable, and the ``custodex_drift`` tool fails with
the same message. Skips cleanly when the ``[mcp]`` extra is absent.

Features: FEAT-MCP-002
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="the [mcp] extra is not installed")

from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

from custodex.mcp.server import build_mcp_server  # noqa: E402

# One doc citing a code ref that does not exist on disk.
_DEAD_REF_CONFIG = """\
version: "2.0.0"
root: "."
backend:
  kind: mock
documents:
  - id: api
    path: docs/api.md
    audience: eng-guide
    code_refs:
      - path: src/gone.py
"""


def _dead_ref_repo(tmp_path: Path) -> Path:
    (tmp_path / "cdmon.yaml").write_text(_DEAD_REF_CONFIG, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text("# API\n", encoding="utf-8")
    return tmp_path


def _call(server: Any, name: str) -> dict[str, Any]:
    """Invoke a tool and return its structured payload, tolerant of SDK shape."""
    result = asyncio.run(server.call_tool(name, {}))
    structured: dict[str, Any] = (
        result[1] if isinstance(result, tuple) else json.loads(result[0].text)
    )
    return structured


def test_custodex_status_tool_degrades_over_an_unextractable_ref(
    tmp_path: Path,
) -> None:
    server = build_mcp_server(_dead_ref_repo(tmp_path))

    structured = _call(server, "custodex_status")

    assert structured["drift_available"] is False
    assert structured["drift_error"].startswith("Code reference not found")
    assert structured["drift_total"] == -1
    assert structured["code_doc_drift"] == -1
    assert structured["suspect_link_drift"] == -1
    assert structured["clean"] is False
    assert structured["summary"] == f"drift unavailable — {structured['drift_error']}"
    # The other pillars still answer.
    assert structured["doc_count"] == 1
    assert structured["docs_unowned"] == 1
    assert structured["coverage_available"] is True


def test_custodex_drift_tool_still_raises_loudly(tmp_path: Path) -> None:
    server = build_mcp_server(_dead_ref_repo(tmp_path))
    drift_error = _call(server, "custodex_status")["drift_error"]

    with pytest.raises(ToolError, match=re.escape(drift_error)):
        _call(server, "custodex_drift")
