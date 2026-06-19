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


def _dir_cfg(tmp_path: Path) -> Path:
    """A minimal config/cdmon DIR layout: a unit whose frontmatter declares an
    owner, plus a document that declares NO owner of its own — so its accountable
    must INHERIT the unit owner. Exercises the dir-layout branch of _unit_owner_map.
    """
    d = tmp_path / "cdmon"
    d.mkdir()
    (d / "index.yaml").write_text(
        "---\n"
        'cdmon-config-version: "2.0.0"\n'
        "repo: probe\n"
        "generated-by: cdmon\n"
        'updated: "2026-06-07"\n'
        "---\n"
        'root: "."\n'
        'version: "2.0.0"\n'
        "units:\n"
        "  - file: core.yaml\n",
        encoding="utf-8",
    )
    (d / "core.yaml").write_text(
        "---\n"
        'cdmon-config-version: "2.0.0"\n'
        "unit: core\n"
        'title: "Core unit"\n'
        "owner: team-x\n"
        'created: "2026-06-07"\n'
        'updated: "2026-06-07"\n'
        "---\n"
        "dir-covered:\n"
        "  - src\n"
        "source-files-format:\n"
        '  - ".py"\n'
        "documents:\n"
        "  - id: d-inherit\n"
        "    path: docs/d-inherit.md\n"
        "    audience: eng-guide\n",  # no owner/team/dri → inherits the unit owner
        encoding="utf-8",
    )
    return d


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


def test_ownership_dir_layout_inherits_unit_owner(tmp_path: Path) -> None:
    """A dir-layout doc with no owner of its own inherits its unit's frontmatter
    owner — drives _unit_owner_map's index.yaml/load_bundle branch through the CLI.
    """
    res = runner.invoke(
        app, ["ownership", "--config", str(_dir_cfg(tmp_path)), "--json"]
    )
    assert res.exit_code == 0, res.output
    owners = {o["doc_id"]: o for o in json.loads(res.output)["owners"]}
    # The doc declares no owner, so accountable + durable inherit the unit owner.
    assert owners["d-inherit"]["accountable"] == "team-x"
    assert owners["d-inherit"]["durable"] == "team-x"
    assert owners["d-inherit"]["owner"] is None  # nothing declared on the doc itself


def test_fail_on_orphan_without_roster_is_loud(tmp_path: Path) -> None:
    """--fail-on-orphan without --roster has no departure data, so the gate could
    only pass vacuously — it is refused with a nonzero exit, not silently green (K8).
    """
    res = runner.invoke(
        app, ["ownership", "--config", str(_cfg(tmp_path)), "--fail-on-orphan"]
    )
    assert res.exit_code == 2, res.output
    assert "--roster" in res.output
