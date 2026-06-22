"""EPIC SLA (SLA-02) — the ``cdmon staleness`` CLI (offline, read-only, K1/K3/K4).

Grades each document's ``reviewed`` date against an injected ``--now`` and the
audience-aware SLA; the table shows only docs needing review, ``--json`` shows all,
``--fail-on-stale`` is the CI gate.

Features: FEAT-STALENESS-004
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from code_doc_monitor.cli import app

runner = CliRunner()

_NOW = "2026-06-22T00:00:00Z"


def _cfg(tmp_path: Path, documents: list[dict], staleness: dict | None = None) -> Path:
    body: dict = {"documents": documents}
    if staleness is not None:
        body["staleness"] = staleness
    p = tmp_path / "cdmon.yaml"
    p.write_text(yaml.safe_dump(body), encoding="utf-8")
    return p


_DOCS = [
    {
        "id": "stale",
        "path": "docs/stale.md",
        "audience": "eng-guide",
        "reviewed": "2026-01-01",
    },
    {
        "id": "fresh",
        "path": "docs/fresh.md",
        "audience": "eng-guide",
        "reviewed": "2026-06-20",
    },
    {"id": "never", "path": "docs/never.md", "audience": "eng-guide"},
]


def test_staleness_table_shows_only_docs_needing_review(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _DOCS)
    res = runner.invoke(app, ["staleness", "--config", str(cfg), "--now", _NOW])
    assert res.exit_code == 0, res.output
    assert "2 document(s) need a review" in res.output
    assert "stale" in res.output and "never" in res.output
    # the fresh doc is NOT listed in the table
    assert "[fresh]" not in res.output


def test_staleness_json_includes_all_docs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _DOCS)
    res = runner.invoke(
        app, ["staleness", "--config", str(cfg), "--now", _NOW, "--json"]
    )
    assert res.exit_code == 0, res.output
    findings = json.loads(res.output)["findings"]
    by_id = {f["doc_id"]: f["status"] for f in findings}
    assert by_id == {"stale": "stale", "fresh": "fresh", "never": "never_reviewed"}


def test_fail_on_stale_trips_on_stale_or_never(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _DOCS)
    res = runner.invoke(
        app, ["staleness", "--config", str(cfg), "--now", _NOW, "--fail-on-stale"]
    )
    assert res.exit_code == 1


def test_fail_on_stale_passes_when_all_fresh(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, [_DOCS[1]])  # only the fresh doc
    res = runner.invoke(
        app, ["staleness", "--config", str(cfg), "--now", _NOW, "--fail-on-stale"]
    )
    assert res.exit_code == 0, res.output
    assert "all documents are fresh" in res.output


def test_audience_sla_changes_the_verdict(tmp_path: Path) -> None:
    # the SAME old review date is stale for an eng-guide (90d) but fresh for a
    # user-guide given a 365-day audience SLA (K3).
    docs = [
        {
            "id": "guide",
            "path": "docs/g.md",
            "audience": "user-guide",
            "reviewed": "2026-01-01",
        },
        {
            "id": "api",
            "path": "docs/a.md",
            "audience": "eng-guide",
            "reviewed": "2026-01-01",
        },
    ]
    cfg = _cfg(
        tmp_path,
        docs,
        staleness={"default_days": 90, "audience_days": {"user-guide": 365}},
    )
    res = runner.invoke(
        app, ["staleness", "--config", str(cfg), "--now", _NOW, "--json"]
    )
    assert res.exit_code == 0, res.output
    by_id = {f["doc_id"]: f["status"] for f in json.loads(res.output)["findings"]}
    assert by_id == {"guide": "fresh", "api": "stale"}


def test_staleness_loud_on_bad_config(tmp_path: Path) -> None:
    bad = tmp_path / "cdmon.yaml"
    bad.write_text("documents: [{id: x}]\n", encoding="utf-8")  # missing path/audience
    res = runner.invoke(app, ["staleness", "--config", str(bad)])
    assert res.exit_code != 0


def test_staleness_loud_on_bad_staleness_block(tmp_path: Path) -> None:
    # a non-positive SLA is malformed config → a loud nonzero exit (K8).
    cfg = _cfg(tmp_path, _DOCS, staleness={"default_days": 0})
    res = runner.invoke(app, ["staleness", "--config", str(cfg), "--now", _NOW])
    assert res.exit_code != 0
