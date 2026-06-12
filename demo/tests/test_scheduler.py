"""Unit tests for the standalone scheduler helper (priority_order)."""

from __future__ import annotations

from taskflow.core.model import Task, TaskGraph
from taskflow.core.scheduler import priority_order


def test_priority_order_returns_only_roots_sorted_by_name() -> None:
    g = TaskGraph()
    g.add(Task("z", "Zulu"))  # root
    g.add(Task("a", "Alpha"))  # root
    g.add(Task("c", "Charlie", deps=("a",)))  # not a root
    # Only the dependency-free tasks, ordered by (name, id): Alpha < Zulu.
    assert priority_order(g) == ("a", "z")


def test_priority_order_breaks_name_ties_by_id() -> None:
    g = TaskGraph()
    g.add(Task("t2", "Same"))
    g.add(Task("t1", "Same"))
    assert priority_order(g) == ("t1", "t2")


def test_priority_order_empty_graph() -> None:
    assert priority_order(TaskGraph()) == ()
