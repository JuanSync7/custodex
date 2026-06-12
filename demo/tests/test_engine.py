"""Unit tests for the scheduling engine (topological order + run)."""

from __future__ import annotations

import pytest

from taskflow.core.engine import CycleError, Engine
from taskflow.core.model import Status, Task, TaskGraph


def _linear() -> TaskGraph:
    g = TaskGraph()
    g.add(Task("a", "Alpha"))
    g.add(Task("b", "Beta", deps=("a",)))
    g.add(Task("c", "Gamma", deps=("b",)))
    return g


def test_topological_order_respects_dependencies() -> None:
    order = Engine(_linear()).topological_order()
    assert order == ("a", "b", "c")


def test_topological_order_is_deterministic_on_ties() -> None:
    g = TaskGraph()
    g.add(Task("a", "Alpha"))
    g.add(Task("b", "Beta"))  # both roots; insertion order breaks the tie
    assert Engine(g).topological_order() == ("a", "b")


def test_cycle_raises_with_unresolved_ids() -> None:
    g = TaskGraph()
    g.add(Task("a", "Alpha", deps=("b",)))
    g.add(Task("b", "Beta", deps=("a",)))
    with pytest.raises(CycleError) as exc:
        Engine(g).topological_order()
    assert set(exc.value.unresolved) == {"a", "b"}


def test_run_marks_all_done_on_success() -> None:
    g = _linear()
    completed = Engine(g).run(lambda task: True)
    assert completed == ("a", "b", "c")
    assert all(t.status is Status.DONE for t in g.tasks.values())


def test_run_cascades_failure_to_dependents() -> None:
    g = _linear()
    # "b" fails → "c" (which depends on b) is skipped and marked FAILED.
    completed = Engine(g).run(lambda task: task.id != "b")
    assert completed == ("a",)
    assert g.get("a").status is Status.DONE
    assert g.get("b").status is Status.FAILED
    assert g.get("c").status is Status.FAILED
