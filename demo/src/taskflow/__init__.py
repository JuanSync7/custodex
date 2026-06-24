"""Taskflow — a tiny task-dependency engine (cdx demo adopter app).

Re-export aggregator: the package's public surface is assembled from the
``core`` and ``io`` subpackages so an adopter can ``from taskflow import
Task, Engine``. This module is waived in ``config/cdmon/index.yaml`` (it is a
pure re-export with no behavior of its own).
"""

from __future__ import annotations

from .core.engine import CycleError, Engine
from .core.model import Status, Task, TaskGraph
from .io.report import render_report
from .io.storage import load_graph, save_graph

__all__ = [
    "Engine",
    "CycleError",
    "Status",
    "Task",
    "TaskGraph",
    "render_report",
    "load_graph",
    "save_graph",
]
