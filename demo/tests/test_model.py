"""Unit tests for the taskflow domain model (Status, Task, TaskGraph)."""

from __future__ import annotations

import pytest

from taskflow.core.model import Status, Task, TaskGraph


def _graph() -> TaskGraph:
    g = TaskGraph()
    g.add(Task("a", "Alpha"))
    g.add(Task("b", "Beta", deps=("a",)))
    g.add(Task("c", "Gamma", deps=("a", "b")))
    return g


def test_status_is_terminal() -> None:
    assert Status.DONE.is_terminal
    assert Status.FAILED.is_terminal
    assert not Status.PENDING.is_terminal
    assert not Status.RUNNING.is_terminal


def test_task_depends_on() -> None:
    t = Task("b", "Beta", deps=("a",))
    assert t.depends_on("a")
    assert not t.depends_on("z")
    assert t.status is Status.PENDING  # default


def test_add_rejects_duplicate_id() -> None:
    g = TaskGraph()
    g.add(Task("a", "Alpha"))
    with pytest.raises(KeyError):
        g.add(Task("a", "Again"))


def test_get_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        TaskGraph().get("missing")


def test_predecessors_and_successors() -> None:
    g = _graph()
    assert g.predecessors("c") == ("a", "b")
    assert g.successors("a") == ("b", "c")
    assert g.successors("c") == ()


def test_roots_are_dependency_free_in_insertion_order() -> None:
    g = _graph()
    assert g.roots() == ("a",)
