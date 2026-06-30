"""WL-01 — the ``cdx worklist`` CLI: the per-owner accountability JOIN (K1/K4).

Drives the command over a self-contained single-file config: a stale doc (past its
review SLA) owned by alice, and a doc with an unstamped doc↔doc edge owned by bob, so
the worklist buckets a STALE item under alice and a SUSPECT item under bob. ``--owner``
filters, ``--no-include-suspect`` drops the repo-local suspect items, ``--roster`` adds
ownership orphans, and ``--fail-on-work`` is the gate. Offline, no backend (K4).

Features: FEAT-WORKLIST-001
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from custodex.cli import app

runner = CliRunner()

_NOW = "2026-06-30T00:00:00Z"

_DOCS = [
    {
        "id": "d1",
        "path": "docs/d1.md",
        "audience": "eng-guide",
        "owner": "alice",
        "team": "platform",  # the durable owner — survives alice's departure
        "dri": "alice",
        "reviewed": "2020-01-01",  # long past any SLA → STALE
    },
    {
        "id": "d2",
        "path": "docs/d2.md",
        "audience": "eng-guide",
        "owner": "bob",
        "reviewed": "2026-06-20",  # fresh → bob's ONLY item is the suspect edge
        "depends_on": [{"doc": "d1"}],  # unstamped edge → SUSPECT
    },
]


def _setup(tmp_path: Path) -> Path:
    cfg = {"version": "1.0.0", "root": ".", "documents": _DOCS}
    p = tmp_path / "cdmon.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "d1.md").write_text("# D1\nupstream body\n", encoding="utf-8")
    (tmp_path / "docs" / "d2.md").write_text("# D2\ndownstream\n", encoding="utf-8")
    return p


def _roster(tmp_path: Path, *, alice_active: bool) -> Path:
    p = tmp_path / "roster.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "identities": [
                    {"name": "alice", "active": alice_active},
                    {"name": "bob", "active": True},
                    # the durable team stays active, so d1's departure is DRI-vacant.
                    {"name": "platform", "kind": "team", "active": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    return p


def test_worklist_groups_by_owner(tmp_path: Path) -> None:
    res = runner.invoke(
        app, ["worklist", "--config", str(_setup(tmp_path)), "--now", _NOW]
    )
    assert res.exit_code == 0, res.output
    assert "alice" in res.output and "bob" in res.output
    assert "stale" in res.output and "suspect" in res.output


def test_worklist_json_shape(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    res = runner.invoke(
        app, ["worklist", "--config", str(cfg), "--now", _NOW, "--json"]
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["includes_suspect"] is True
    owners = {o["accountable"]: o for o in payload["owners"]}
    assert {"alice", "bob"} <= owners.keys()
    # bob's single item is the suspect edge d2 → d1.
    assert any(
        i["reason"] == "suspect" and i["upstream_id"] == "d1"
        for i in owners["bob"]["items"]
    )
    # counts are item-derived (one doc, one item here for each owner).
    assert owners["alice"]["doc_count"] == 1


def test_worklist_owner_filter(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    res = runner.invoke(
        app,
        ["worklist", "--config", str(cfg), "--now", _NOW, "--owner", "alice", "--json"],
    )
    owners = {o["accountable"] for o in json.loads(res.output)["owners"]}
    assert owners == {"alice"}


def test_worklist_fail_on_work_exits_one(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    # default exits 0 even with work...
    assert (
        runner.invoke(app, ["worklist", "--config", str(cfg), "--now", _NOW]).exit_code
        == 0
    )
    # ...the gate opts in to exit 1.
    res = runner.invoke(
        app, ["worklist", "--config", str(cfg), "--now", _NOW, "--fail-on-work"]
    )
    assert res.exit_code == 1


def test_worklist_no_include_suspect_drops_suspect_items(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    res = runner.invoke(
        app,
        [
            "worklist",
            "--config",
            str(cfg),
            "--now",
            _NOW,
            "--no-include-suspect",
            "--json",
        ],
    )
    payload = json.loads(res.output)
    assert payload["includes_suspect"] is False
    # bob had ONLY a suspect item → gone; alice (stale) remains.
    assert {o["accountable"] for o in payload["owners"]} == {"alice"}


def test_worklist_roster_adds_orphan_items(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    roster = _roster(tmp_path, alice_active=False)  # alice departed
    res = runner.invoke(
        app,
        [
            "worklist",
            "--config",
            str(cfg),
            "--now",
            _NOW,
            "--roster",
            str(roster),
            "--json",
        ],
    )
    payload = json.loads(res.output)
    owners = {o["accountable"]: o for o in payload["owners"]}
    # alice DEPARTED → her work is NOT parked in her queue; d1 is DRI-vacant, so BOTH
    # its orphan and its stale review re-route to the still-active durable team.
    assert "alice" not in owners
    platform = owners["platform"]
    assert {i["reason"] for i in platform["items"]} == {"orphan", "stale"}
    assert platform["doc_count"] == 1  # both items are the same doc d1
