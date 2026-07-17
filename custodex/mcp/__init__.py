"""The Custodex Model Context Protocol server (optional ``[mcp]`` extra — EPIC MCP).

The read/write surface an external agent (Claude Code / any MCP client) uses to
query and act on Custodex through the standard tool protocol, instead of shelling
out to ``cdx`` or hitting raw HTTP. ⟨MCP⟩ MCP is the transport/discovery layer;
Custodex's own (non-conversational, single-turn) agents are exposed AS curated
tools — the orchestrating client IS the chain.

The engine never imports the ``mcp`` SDK (``import custodex`` pulls in nothing
from here), keeping the core dependency surface minimal (K0, the ``[server]``
extra precedent). Both layers are import-safe — the SDK is imported LAZILY at
build time (the ``make_backend`` precedent), so nothing here requires the
``[mcp]`` extra just to IMPORT:

* :mod:`custodex.mcp.tools` is PURE — core deps only, no SDK — so its projection
  logic imports and tests even in a core-only install.
* :mod:`custodex.mcp.server` is also import-safe: ``build_mcp_server`` imports the
  SDK lazily and wraps a missing one in a loud, typed
  :class:`~custodex.errors.McpError` (K8) — so *calling* it is what requires the
  ``[mcp]`` extra, and both the CLI and the ``cdx-mcp`` entry point get the SAME
  actionable ``install custodex[mcp]`` guard.

This ``__init__`` imports NEITHER layer, so ``import custodex.mcp`` /
``custodex.mcp.tools`` never drags in the SDK; the CLI + ``cdx-mcp`` entry point
reach the builder via the full ``custodex.mcp.server`` path.
"""

from __future__ import annotations

__all__: list[str] = []
