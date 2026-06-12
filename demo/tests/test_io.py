"""Unit tests for the io adapters (JSON persistence + the text report)."""

from __future__ import annotations

from pathlib import Path

import pytest

from taskflow.core.model import Status, Task, TaskGraph
from taskflow.io.report import render_report
from taskflow.io.storage import load_graph, save_graph


def _graph() -> TaskGraph:
    g = TaskGraph()
    g.add(Task("a", "Alpha", status=Status.DONE))
    g.add(Task("b", "Beta", deps=("a",)))
    return g


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    g = _graph()
    path = tmp_path / "graph.json"
    save_graph(g, path)
    back = load_graph(path)
    assert list(back.tasks) == ["a", "b"]
    assert back.get("a").status is Status.DONE
    assert back.get("b").deps == ("a",)


def test_save_is_stable_across_repeated_writes(tmp_path: Path) -> None:
    g = _graph()
    p1, p2 = tmp_path / "1.json", tmp_path / "2.json"
    save_graph(g, p1)
    save_graph(g, p2)
    assert p1.read_text() == p2.read_text()


def test_load_rejects_malformed_payload(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"not_tasks": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_graph(bad)


def test_render_report_lists_tasks_and_summary() -> None:
    report = render_report(_graph())
    assert "Alpha" in report
    assert "Beta" in report
    assert "summary:" in report
    assert "done=1" in report
    assert "pending=1" in report
