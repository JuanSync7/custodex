"""The deterministic LangGraph remediation workflow (K4, K8, K10).

A compiled :class:`~langgraph.graph.StateGraph` with four nodes and one bounded
loop:

```
START -> select -> compose -> invoke -> parse --done--> END
                      ^                    |
                      └────── retry ───────┤
                                           └──fail──> (raise BackendError)
```

* **select** — decide which ``.md`` artifacts this drift needs (AGENT + PROTOCOL
  always; TOOL only for a healable drift; PERSONA only when enabled and present).
  This is where "load the artifact only when needed" is decided.
* **compose** — read the selected artifacts (lazily, via the
  :class:`~custodex.agent.prompts.PromptLibrary`) and assemble the prompt
  around the drift-specific context. On a re-ask it prepends a strict-JSON nudge.
* **invoke** — the only side-effecting node: call the injected
  :data:`~custodex.agent.runtime.Driver`.
* **parse** — validate the reply into a :class:`BackendResult`; on a malformed
  reply, route back to ``compose`` until ``max_parse_retries`` is spent, then
  fail loudly (K8).

The graph itself is fully deterministic; the only non-determinism is the driver,
which is injected (a fake in tests) so the whole workflow runs offline (K4).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..backends import FixRequest, _render_context_refs, parse_backend_json
from ..blocks import symbol_table
from ..config import AgentConfig
from ..drift import DriftKind
from ..errors import BackendError
from .prompts import Artifact, PromptLibrary
from .runtime import Driver
from .state import RemediationState

__all__ = ["build_graph", "render_context", "select_artifacts"]

_RETRY_NUDGE = (
    "YOUR PREVIOUS REPLY WAS NOT VALID JSON. Reply with ONE JSON object only — "
    "no prose, no markdown fences — exactly as the contract below requires."
)


def select_artifacts(
    req: FixRequest, cfg: AgentConfig, library: PromptLibrary
) -> list[str]:
    """Decide which artifacts this drift needs (the "only when needed" rule).

    AGENT + PROTOCOL are always needed (the recipe and the wire contract). TOOL
    (the fix shapes) is needed only when a fix may be produced — i.e. the drift
    is healable, not ``UNHEALABLE``. PERSONA is composed only when enabled and
    actually present. EXEMPLARS (D-04) is composed only when the request carries
    few-shot exemplars — with none, the selection (and so the prompt) is
    byte-identical to pre-D-04 (additive, K6/K9).
    """
    names = [Artifact.AGENT, Artifact.PROTOCOL]
    if req.drift.healable and req.drift.kind is not DriftKind.UNHEALABLE:
        names.append(Artifact.TOOL)
    if cfg.use_persona and library.exists(Artifact.PERSONA):
        names.append(Artifact.PERSONA)
    if req.exemplars:
        names.append(Artifact.EXEMPLARS)
    return names


def _render_exemplars(req: FixRequest) -> str:
    """Render the retrieved few-shot exemplars, or ``""`` when there are none.

    Returns the empty string for an exemplar-free request so :func:`render_context`
    is BYTE-IDENTICAL to its pre-D-04 output (additive, K9). Each exemplar shows the
    past drift's shape, its human outcome, and — for an ``overridden`` resolution —
    the exact ``resolved_text`` the human committed (the gold answer, K5).
    """
    if not req.exemplars:
        return ""
    blocks: list[str] = []
    for i, ex in enumerate(req.exemplars, start=1):
        rec = ex.record
        res = ex.resolution
        outcome = (
            f"\n  resolved_text (the human's final body):\n<<<RESOLVED\n"
            f"{res.resolved_text}\nRESOLVED"
            if res.resolved_text is not None
            else ""
        )
        fix_body = ""
        if rec.fix is not None:
            fix_body = f"\n  proposed fix rationale: {rec.fix.rationale}"
        blocks.append(
            f"## Exemplar {i} (similarity score {ex.score:g})\n"
            f"- doc_id: {rec.doc_id}\n"
            f"- audience: {rec.audience.value}\n"
            f"- drift kind: {rec.drift_kind}\n"
            f"- drift detail: {rec.drift_detail}\n"
            f"- past verdict: {rec.verdict.value}\n"
            f"- human outcome: {res.resolution.value}"
            f"{fix_body}"
            f"{outcome}"
        )
    return (
        "\nSimilar past drifts a human has already resolved "
        "(precedent — read per EXEMPLARS.md; the surface above still wins, K2):\n"
        + "\n\n".join(blocks)
        + "\n"
    )


def render_context(req: FixRequest) -> str:
    """Render the drift-specific context block appended after the artifacts.

    The artifacts carry the static role/contract/shapes; this carries the one
    thing that changes per drift — the audience, the document, and the code
    surface that is its single source of truth (K2). When the request carries
    few-shot exemplars (D-04), they are appended LAST; with none, the output is
    byte-identical to pre-D-04 (additive, K9).
    """
    drift = req.drift
    region_line = (
        f"- managed region id: {drift.region_id}\n"
        if drift.region_id is not None
        else ""
    )
    diff_line = f"- diff:\n{drift.diff}\n" if drift.diff else ""
    index_line = (
        f"\nPre-rendered index body (use verbatim for the region):\n{req.index_body}\n"
        if req.index_body is not None
        else ""
    )
    # N-05: when a doc-style map is in play, the four selected writing-template
    # bodies are appended LAST so they frame HOW to author the prose. With none
    # (req.style_guidance is None) the output is byte-identical to today (additive,
    # K6) — the seam is the FixRequest field, no global reached into (K10).
    style_block = (
        "\n# Writing guidance (apply when AUTHORING this document's prose)\n"
        f"{req.style_guidance}\n"
        if req.style_guidance is not None
        else ""
    )
    # E-02: the document's glance-through context refs as a reference block,
    # rendered identically to the single-shot prompt (shared helper). Empty for a
    # context-ref-free request ⇒ byte-identical to pre-E-02 (additive, K6).
    context_block = _render_context_refs(req)
    return (
        "# This remediation\n"
        f"Audience: {req.surface.audience.value}\n"
        f"Document id: {req.doc_spec_id}\n"
        f"Document path: {drift.doc_path}\n"
        "\n"
        "Detected drift:\n"
        f"- kind: {drift.kind.value}\n"
        f"- detail: {drift.detail}\n"
        f"{region_line}"
        f"{diff_line}"
        "\n"
        "Current document text:\n"
        "<<<DOC\n"
        f"{req.doc_text}\n"
        "DOC\n"
        "\n"
        "Relevant code surface (the single source of truth):\n"
        "<<<SURFACE\n"
        f"{symbol_table(req.surface)}\n"
        "SURFACE\n"
        f"{index_line}"
        f"{context_block}"
        f"{_render_exemplars(req)}"
        f"{style_block}"
    )


def build_graph(
    driver: Driver, library: PromptLibrary, cfg: AgentConfig
) -> CompiledStateGraph:
    """Compile the remediation graph with its collaborators bound in (K4).

    ``driver``/``library``/``cfg`` are closed over by the nodes, so
    :class:`RemediationState` stays pure data and the graph is reusable across
    drifts.
    """

    def select(state: RemediationState) -> dict:
        return {"selected": select_artifacts(state["req"], cfg, library)}

    def compose(state: RemediationState) -> dict:
        parts = [library.get(name) for name in state["selected"]]
        prompt = "\n\n---\n\n".join([*parts, render_context(state["req"])])
        if state.get("attempts", 0) > 0:
            prompt = f"{_RETRY_NUDGE}\n\n{prompt}"
        return {"prompt": prompt}

    def invoke(state: RemediationState) -> dict:
        raw = driver(state["prompt"])
        return {"raw": raw, "attempts": state.get("attempts", 0) + 1}

    def parse(state: RemediationState) -> dict:
        try:
            return {"result": parse_backend_json(state["raw"])}
        except BackendError as exc:
            return {"result": None, "last_error": str(exc)}

    def fail(state: RemediationState) -> dict:
        raise BackendError(
            state.get("last_error", "agent workflow produced no valid verdict")
        )

    def route(state: RemediationState) -> str:
        if state.get("result") is not None:
            return "done"
        if state.get("attempts", 0) <= cfg.max_parse_retries:
            return "retry"
        return "fail"

    graph: StateGraph = StateGraph(RemediationState)
    graph.add_node("select", select)
    graph.add_node("compose", compose)
    graph.add_node("invoke", invoke)
    graph.add_node("parse", parse)
    graph.add_node("fail", fail)
    graph.add_edge(START, "select")
    graph.add_edge("select", "compose")
    graph.add_edge("compose", "invoke")
    graph.add_edge("invoke", "parse")
    graph.add_conditional_edges(
        "parse", route, {"done": END, "retry": "compose", "fail": "fail"}
    )
    graph.add_edge("fail", END)
    return graph.compile()
