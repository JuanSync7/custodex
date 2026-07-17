"""The Custodex Model Context Protocol server (optional ``[mcp]`` extra — EPIC MCP).

The read/write surface an external agent (Claude Code / any MCP client) uses to
query and act on Custodex through the standard tool protocol, instead of shelling
out to ``cdx`` or hitting raw HTTP. ⟨MCP⟩ MCP is the transport/discovery layer;
Custodex's own (non-conversational, single-turn) agents are exposed AS curated
tools — the orchestrating client IS the chain.

The engine never imports the ``mcp`` SDK (``import custodex`` pulls in nothing
from here), keeping the core dependency surface minimal (K0, the ``[server]``
extra precedent). Two-layer split, tighter than ``[server]``'s:

* :mod:`custodex.mcp.tools` is PURE — core deps only, no SDK — so its projection
  logic imports and tests even in a core-only install.
* :mod:`custodex.mcp.server` (``build_mcp_server``) imports the SDK; importing it
  is what requires the ``[mcp]`` extra.

This ``__init__`` deliberately imports NEITHER, so ``import custodex.mcp.tools``
never drags in the SDK; the CLI + ``cdx-mcp`` entry point reach the builder via
the full ``custodex.mcp.server`` path.
"""

from __future__ import annotations

__all__: list[str] = []
