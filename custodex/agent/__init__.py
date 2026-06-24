"""The LangGraph remediation agent (optional ``[agent]`` extra).

A deterministic LangGraph workflow that composes its prompt from separated
Markdown artifacts (``AGENT.md`` / ``PROTOCOL.md`` / ``TOOL.md`` / ``PERSONA.md``,
loaded only when needed) and drives a configurable runtime — the headless Claude
Code CLI by default, or the Anthropic API, or a local OpenAI-compatible model.
It plugs into the engine as ``backend.kind: "agent"`` and satisfies the same
:class:`~custodex.backends.Backend` contract as the single-shot backends.

Importing this subpackage requires ``langgraph`` (the ``[agent]`` extra); the
engine's default ``mock`` path does not, keeping the core dependency surface
minimal (K0).
"""

from __future__ import annotations

from .backend import AgentBackend, make_agent_backend
from .graph import build_graph, render_context, select_artifacts
from .prompts import Artifact, PromptLibrary
from .runtime import Driver, resolve_driver

__all__ = [
    "AgentBackend",
    "make_agent_backend",
    "build_graph",
    "render_context",
    "select_artifacts",
    "Artifact",
    "PromptLibrary",
    "Driver",
    "resolve_driver",
]
