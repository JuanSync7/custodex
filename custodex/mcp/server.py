"""The Custodex MCP server over FastMCP (the ``[mcp]`` extra — EPIC MCP, MCP-00).

Importing THIS module requires the ``mcp`` SDK. The core engine never imports it
(``import custodex`` pulls in nothing from here), keeping the core dependency
surface minimal (K0, mirrors ``server/app.py`` importing fastapi). All projection
logic lives in the pure :mod:`custodex.mcp.tools` module (no SDK); this module
only maps those functions onto FastMCP tools and runs the stdio transport.

The tool set is CURATED and its output is SHAPED (pydantic → ``model_dump``),
not a 1:1 wrap of the 37 ``cdx`` verbs. MCP-00 registers the ``custodex_status``
overview (progressive disclosure); MCP-01/02 add the per-domain read tools and
the gated write/agentic tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import tools

__all__ = ["build_mcp_server", "main"]


def build_mcp_server(repo_root: Path) -> Any:
    """Build the Custodex MCP server over ``repo_root`` (import-safe; no transport).

    Fails fast (K8) if ``repo_root`` has no resolvable Custodex config, then
    registers the curated tools as thin wrappers over the pure :mod:`tools`
    functions. Each tool RELOADS the config bundle per call so it reflects live
    repo state, and returns ``model_dump(mode="json")`` (shaped output). Returns
    the :class:`FastMCP` server WITHOUT binding a transport, so tests drive it
    directly (the :func:`custodex.server.standalone.build_standalone_app`
    precedent — all logic here, the socket/stdio launch stays a thin leaf).
    """
    # Fail fast (K8): refuse to serve a repo with no resolvable config, so the
    # error surfaces at launch, not on the first tool call.
    tools.load_repo_bundle(repo_root)

    server = FastMCP("custodex")

    @server.tool()
    def custodex_status() -> dict[str, Any]:
        """Is this repo in sync? Drift totals (code↔doc vs doc↔doc) + doc count.

        The progressive-disclosure entrypoint: call this first to see whether the
        repo's docs match its code, then drill into the per-domain tools.
        """
        cfg, config_dir = tools.load_repo_bundle(repo_root)
        repo_id = tools.resolve_repo_id(repo_root, config_dir)
        return tools.status_summary(cfg, config_dir, repo_id=repo_id).model_dump(
            mode="json"
        )

    return server


def main() -> None:  # pragma: no cover — the `cdx-mcp` entry point (stdio leaf, K4)
    """The ``cdx-mcp`` console entry point: serve the cwd repo over stdio."""
    build_mcp_server(Path.cwd()).run()
