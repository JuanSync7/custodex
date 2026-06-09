"""The golden multi-language example stays in sync (examples/multilang/).

A self-contained "greeter" tool written in five languages — Python library,
argparse CLI, JSON flag rules, shell getopts, tcl regexp switches — each mapped
onto a managed doc. This proves, end-to-end against the real CLI engine, that
one config keeps documents honest across languages. It references only static
example code, so it is insulated from the package's own source churn.

Features: FEAT-CONFIG-002, FEAT-CONFIG-009, FEAT-EXTRACT-001, FEAT-EXTRACT-003
Features: FEAT-EXTRACT-006, FEAT-DRIFT-001, FEAT-MONITOR-002, FEAT-LAYOUT-001
Features: FEAT-LAYOUT-002, FEAT-LAYOUT-005
"""

from __future__ import annotations

import pytest

from code_doc_monitor.config import load_config
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.layout import lint_config
from code_doc_monitor.monitor import Monitor
from tests._repo import REPO_ROOT

_EXAMPLE = REPO_ROOT / "examples" / "multilang"
_CONFIG = _EXAMPLE / "cdmon.yaml"


@pytest.fixture(scope="module")
def cfg():
    return load_config(_CONFIG)


def test_each_language_extracts_its_surface(cfg):
    by_id = {d.id: build_document_surface(d, _EXAMPLE) for d in cfg.documents}

    # Python library -> symbols (eng-guide)
    assert {s.name for s in by_id["library"].symbols} >= {
        "greet",
        "Greeter",
        "DEFAULT_GREETING",
    }

    # argparse CLI -> option records
    cli = {r.name: dict(r.fields) for r in by_id["cli"].records}
    assert set(cli) == {"--name", "--repeat", "--shout"}
    assert cli["--name"]["help"] == "who to greet"
    assert all(r.kind == "option" for r in by_id["cli"].records)

    # JSON flag rules -> records with replacement/action/comment
    flags = {r.name: dict(r.fields) for r in by_id["flags"].records}
    assert set(flags) == {"--loud", "--silent"}
    assert flags["--loud"]["flag name replacement"] == "--shout"

    # shell getopts + tcl regexp -> a combined switch table from TWO languages
    switches = {r.name for r in by_id["tools"].records}
    assert {"-f", "-n", "-v", "-h"} <= switches  # from batch.sh (shell)
    assert {"-t", "-T", "-g", "-G", "-q", "-Q"} <= switches  # from gui.tcl (tcl)
    assert all(r.kind == "switch" for r in by_id["tools"].records)


def test_example_docs_are_in_sync(cfg):
    """The committed example docs match the committed example code (read-only)."""
    report = Monitor(cfg, _EXAMPLE).check()
    assert report.ok, report.summary()


def test_example_docs_conform_and_twins_current(cfg):
    """Layout standard holds and every declared .html twin is derived + current."""
    issues = lint_config(cfg, _EXAMPLE)
    assert issues == [], [f"{i.doc_id}: {i.code.value} — {i.detail}" for i in issues]
