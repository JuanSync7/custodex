"""``AgentBackend`` — the LangGraph workflow behind the :class:`Backend` protocol.

It satisfies the same ``propose(req) -> BackendResult`` contract as the
single-shot backends, so the orchestrator (:class:`~code_doc_monitor.monitor.Monitor`)
is unchanged whether it runs the mock, a one-shot CLI/API call, or this graph
(K4). The driver and prompt library are injected (a fake driver in tests) so the
whole workflow runs offline and deterministically; both default to the
config-resolved runtime, built lazily on first :meth:`propose`.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from ..backends import BackendResult, FixRequest
from ..config import AgentConfig
from ..errors import BackendError
from .graph import build_graph
from .prompts import PromptLibrary
from .runtime import Driver, resolve_driver

__all__ = ["AgentBackend", "make_agent_backend"]


class AgentBackend:
    """Remediation via the deterministic LangGraph workflow."""

    def __init__(
        self,
        cfg: AgentConfig,
        *,
        driver: Driver | None = None,
        library: PromptLibrary | None = None,
    ) -> None:
        self._cfg = cfg
        self._driver = driver
        self._library = library or PromptLibrary(
            Path(cfg.prompts_dir) if cfg.prompts_dir else None
        )
        self._graph: CompiledStateGraph | None = None

    def _ensure_graph(self) -> CompiledStateGraph:
        if self._graph is None:
            driver = self._driver or resolve_driver(self._cfg)
            self._graph = build_graph(driver, self._library, self._cfg)
        return self._graph

    def propose(self, req: FixRequest) -> BackendResult:
        final = self._ensure_graph().invoke({"req": req, "attempts": 0})
        result = final.get("result")
        if result is None:  # pragma: no cover - the fail node raises first (K8)
            raise BackendError("agent workflow produced no verdict")
        return result


def make_agent_backend(
    cfg: AgentConfig, *, driver: Driver | None = None
) -> AgentBackend:
    """Build an :class:`AgentBackend` from config (one factory, K4)."""
    return AgentBackend(cfg, driver=driver)
