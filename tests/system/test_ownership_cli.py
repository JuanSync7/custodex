"""EPIC OWN (OWN-03) — the ``cdmon ownership`` CLI (offline, read-only, K1/K4).

Drives the command via CliRunner over a self-contained single-file config + an
offline roster YAML: lists per-document ownership, cross-checks against the roster
to flag orphans, and ``--fail-on-orphan`` turns a departed-owner orphan into a
nonzero exit (a CI/accountability gate). No network, no backend.

Features: FEAT-OWNERSHIP-004
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from code_doc_monitor.cli import app

runner = CliRunner()


def _cfg(tmp_path: Path) -> Path:
    cfg = {
        "documents": [
            {
                "id": "d1",
                "path": "docs/d1.md",
                "audience": "eng-guide",
                "owner": "platform",
                "team": "platform",
                "dri": "alice",
            },
            {"id": "d2", "path": "docs/d2.md", "audience": "user-guide"},
        ]
    }
    p = tmp_path / "cdmon.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def _roster(tmp_path: Path, *, alice_active: bool) -> Path:
    p = tmp_path / "roster.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "identities": [
                    {"name": "alice", "active": alice_active},
                    {"name": "platform", "kind": "team", "active": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    return p


def test_ownership_lists_without_roster(tmp_path: Path) -> None:
    res = runner.invoke(app, ["ownership", "--config", str(_cfg(tmp_path))])
    assert res.exit_code == 0, res.output
    assert "d1" in res.output and "d2" in res.output
    assert "alice" in res.output


def test_ownership_json_shape(tmp_path: Path) -> None:
    res = runner.invoke(app, ["ownership", "--config", str(_cfg(tmp_path)), "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert {"owners", "findings"} <= payload.keys()
    assert {o["doc_id"] for o in payload["owners"]} == {"d1", "d2"}


def test_ownership_flags_departed_dri_and_fails(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    roster = _roster(
        tmp_path, alice_active=False
    )  # alice gone, team active → DRI vacant
    res = runner.invoke(
        app, ["ownership", "--config", str(cfg), "--roster", str(roster)]
    )
    assert res.exit_code == 0, res.output
    assert "vacant" in res.output.lower()
    res2 = runner.invoke(
        app,
        [
            "ownership",
            "--config",
            str(cfg),
            "--roster",
            str(roster),
            "--fail-on-orphan",
        ],
    )
    assert res2.exit_code == 1


def test_ownership_clean_when_owner_active(tmp_path: Path) -> None:
    # alice active → d1 OK; d2 is UNOWNED but that is NOT a departed-owner orphan,
    # so --fail-on-orphan still passes (the gate is about departures, not coverage).
    cfg = _cfg(tmp_path)
    roster = _roster(tmp_path, alice_active=True)
    res = runner.invoke(
        app,
        [
            "ownership",
            "--config",
            str(cfg),
            "--roster",
            str(roster),
            "--fail-on-orphan",
        ],
    )
    assert res.exit_code == 0, res.output


def test_ownership_loud_on_bad_config(tmp_path: Path) -> None:
    bad = tmp_path / "cdmon.yaml"
    bad.write_text("documents: [{id: x}]\n", encoding="utf-8")  # missing path/audience
    res = runner.invoke(app, ["ownership", "--config", str(bad)])
    assert res.exit_code != 0
