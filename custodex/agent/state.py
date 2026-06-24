"""The LangGraph remediation workflow's state (K10).

A plain ``TypedDict`` whose keys flow between nodes; LangGraph merges each node's
returned partial dict into it. Kept minimal — collaborators (driver, prompt
library, config) are bound into the node closures by :func:`graph.build_graph`,
not carried in state — so the state is just the data of one remediation.
"""

from __future__ import annotations

from typing import TypedDict

from ..backends import BackendResult, FixRequest

__all__ = ["RemediationState"]


class RemediationState(TypedDict, total=False):
    """The data threaded through ``select -> compose -> invoke -> parse``."""

    req: FixRequest  # the drift to remediate (input)
    selected: list[str]  # artifact names chosen for this drift
    prompt: str  # the composed prompt
    raw: str  # the driver's raw reply
    attempts: int  # how many times the driver has been invoked
    result: BackendResult | None  # the parsed verdict (output)
    last_error: str  # most recent parse failure, for the fail node
