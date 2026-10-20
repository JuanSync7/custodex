"""PROMO-DISTINCT (idea 21) in ship shape: one human decision counts once.

Every test drives the REAL writers — MCP ``remediate_drift``/``resolve_drift``
(``custodex_remediate``/``custodex_resolve``), a ``Monitor`` run, the hub's
``/ingest`` and ``/repos/{id}/resolutions`` — and reads promotion through its real
consumers (``detect_promotions``, ``cdx promotions``, the ``promote_rule`` worker
suggestion, the hub telemetry).

The fixture is one eng-guide doc with THREE managed regions over one function, so
a public-signature change yields 1 HASH + 3 REGION drifts. Under ONE injected
clock (every MCP call) those four records share ONE ``record_id``
(``schema.new_record_id`` hashes ``(doc_id, surface_hash, detected_at)``). A "code
event" is a distinct signature, so distinct events have distinct surface hashes.

The KNOWN RESIDUAL (not closed by this slice): ONE code event can still mint
SEVERAL ids, and each resolved id counts. Two writers do it:

- a per-record ticking clock (the CLI's ``_default_now``) gives one run's drifts
  distinct ids — pinned by ``test_cli_same_run_resolves_count_per_id_known_residual``;
- repeated runs over an UNCHANGED surface (every ``custodex_remediate`` call
  injects a fresh ``now``) give each run its own id — pinned by
  ``test_repeated_mcp_runs_of_one_code_event_count_per_run_known_residual``.

A run id alone closes only the first; the second needs a code-event unit (e.g.
surface_hash + run, unanimity still per record_id). Whoever changes the unit
(PROMO-RUN, after OKF-RUNID) must flip both pinned residuals and revisit every
test here that counts ids — in particular
``test_repeated_mcp_previews_under_one_clock_stay_one_decision`` (two runs over one
shared id) and the hub tests.

Features: FEAT-LEARN-007, FEAT-LEARN-008
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from custodex.cli import app
from custodex.config import MonitorConfig, load_config
from custodex.mcp.tools import remediate_drift, resolve_drift
from custodex.monitor import DEFAULT_LOG_PATH, Monitor
from custodex.promotion import detect_promotions
from custodex.reviewlog import (
    DEFAULT_RESOLUTIONS_PATH,
    append_resolution,
    read_all,
    read_resolutions,
)
from custodex.schema import Resolution, ResolutionRecord, ReviewRecord
from custodex.workers import SuggestionKind, suggest_fixes_tick

runner = CliRunner()

REGIONS = ("symbols", "sigs", "table")

_CONFIG = """\
version: "1.0.0"
root: "repo"
documents:
  - id: "api"
    path: "docs/api.md"
    audience: "eng-guide"
    code_refs:
      - path: "src/mod.py"
    region_keys: ["symbols", "sigs", "table"]
region_templates:
  sigs:
    source: symbols
    columns:
      - {header: signature, field: signature}
  table:
    source: symbols
    columns:
      - {header: symbol, field: name}
      - {header: signature, field: signature}
backend:
  kind: "mock"
"""


def _code(event: int) -> str:
    """Code event ``event``: the public signature gains ``event`` parameters."""
    params = "".join(f", p{i}: int" for i in range(event))
    return (
        f'def greet(name: str{params}) -> str:\n    """Say hello."""\n    return name\n'
    )


def _stamp(event: int, tick: int = 0) -> str:
    return f"2026-06-{event + 1:02d}T00:00:00.{tick:06d}+00:00"


def _repo(tmp_path: Path) -> MonitorConfig:
    """A synced three-region doc (code event 0) with an EMPTY review log."""
    (tmp_path / "cdmon.yaml").write_text(_CONFIG, encoding="utf-8")
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(_code(0), encoding="utf-8")
    (root / "docs" / "api.md").write_text(
        "# API\n\n"
        + "".join(f"<!-- CDM:BEGIN {r} -->\n<!-- CDM:END {r} -->\n\n" for r in REGIONS),
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "cdmon.yaml")
    Monitor(cfg, tmp_path, now=lambda: _stamp(0)).run(apply=True, tiered=False)
    assert Monitor(cfg, tmp_path).check().drifts == ()  # baseline is in sync
    (tmp_path / DEFAULT_LOG_PATH).unlink()  # the baseline heal is not under test
    return cfg


def _change_code(tmp_path: Path, event: int) -> None:
    (tmp_path / "repo" / "src" / "mod.py").write_text(_code(event), encoding="utf-8")


def _mcp_event(cfg: MonitorConfig, tmp_path: Path, event: int) -> str:
    """Code event ``event`` previewed through MCP; returns its ONE shared record_id."""
    _change_code(tmp_path, event)
    result = remediate_drift(cfg, tmp_path, repo_id="demo", now=_stamp(event))
    assert [it.drift_kind for it in result.items] == ["HASH"] + ["REGION"] * 3
    ids = {it.record_id for it in result.items}
    assert len(ids) == 1  # one injected clock -> the doc's 4 drifts share one id
    return ids.pop()


def _ticking_event(
    cfg: MonitorConfig, tmp_path: Path, event: int
) -> tuple[ReviewRecord, list[ReviewRecord]]:
    """Code event ``event`` through a per-record ticking clock (the CLI's grain).

    Returns ``(hash_record, region_records)``; every record has its own id.
    """
    _change_code(tmp_path, event)
    ticks = itertools.count()
    run = Monitor(cfg, tmp_path, now=lambda: _stamp(event, next(ticks))).run(
        apply=False, tiered=False
    )
    (hash_rec,) = [r for r in run.records if r.drift_kind == "HASH"]
    regions = [r for r in run.records if r.drift_kind == "REGION"]
    assert len(regions) == 3
    assert len({r.record_id for r in run.records}) == 4
    return hash_rec, regions


def _resolve(
    cfg: MonitorConfig,
    tmp_path: Path,
    record_id: str,
    resolution: str = "invalidated",
) -> None:
    resolve_drift(
        cfg,
        tmp_path,
        repo_id="demo",
        record_id=record_id,
        resolution=resolution,
        now=_stamp(20),
    )


def _candidates(tmp_path: Path, min_count: int = 3) -> list[tuple[str, int]]:
    cands = detect_promotions(
        read_all(tmp_path / DEFAULT_LOG_PATH),
        read_resolutions(tmp_path / DEFAULT_RESOLUTIONS_PATH),
        min_count=min_count,
    )
    return [(c.drift_kind, c.count) for c in cands]


# --- MCP: one injected clock per call -------------------------------------------


def test_one_mcp_resolve_of_a_three_region_doc_never_promotes(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-007
    # THE BUG: one custodex_resolve of a 3-region doc counted as 3 unanimous
    # REGION decisions and promoted the shape by itself at the default threshold.
    cfg = _repo(tmp_path)
    shared = _mcp_event(cfg, tmp_path, 1)
    _resolve(cfg, tmp_path, shared)
    assert _candidates(tmp_path) == []
    assert _candidates(tmp_path, min_count=1) == [("HASH", 1), ("REGION", 1)]


def test_repeated_mcp_previews_under_one_clock_stay_one_decision(
    tmp_path: Path,
) -> None:
    # Feature: FEAT-LEARN-007
    # Two previews of the SAME code state under the SAME injected `now` write
    # byte-identical lines (the MCP server injects a fresh `now` per call, so in
    # ship shape this comes from any caller that injects one stamp; byte-identical
    # hub lines come from a sink re-POST — see the hub tests below).
    cfg = _repo(tmp_path)
    shared = _mcp_event(cfg, tmp_path, 1)
    again = remediate_drift(cfg, tmp_path, repo_id="demo", now=_stamp(1))
    assert {it.record_id for it in again.items} == {shared}
    assert len(read_all(tmp_path / DEFAULT_LOG_PATH)) == 8
    _resolve(cfg, tmp_path, shared)
    assert _candidates(tmp_path) == []
    assert _candidates(tmp_path, min_count=1) == [("HASH", 1), ("REGION", 1)]


def test_three_code_events_each_resolved_once_promote(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-007
    # The legitimate path still works: three separate code events, each resolved
    # once, are three decisions in each shape.
    cfg = _repo(tmp_path)
    for event in (1, 2, 3):
        _resolve(cfg, tmp_path, _mcp_event(cfg, tmp_path, event))
    assert _candidates(tmp_path) == [("HASH", 3), ("REGION", 3)]


def test_shared_id_and_per_event_ids_count_per_shape(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-008
    # Event 1 through MCP (shared id A, resolved once). Events 2 and 3 through a
    # ticking clock; the human resolves ONE region of each. REGION therefore holds
    # three decisions from three code events; HASH holds only A.
    cfg = _repo(tmp_path)
    shared = _mcp_event(cfg, tmp_path, 1)
    _resolve(cfg, tmp_path, shared)
    decided = [shared]
    for event in (2, 3):
        _hash, regions = _ticking_event(cfg, tmp_path, event)
        _resolve(cfg, tmp_path, regions[0].record_id)
        decided.append(regions[0].record_id)
    records = read_all(tmp_path / DEFAULT_LOG_PATH)
    hashes = {
        r.surface_hash
        for r in records
        if r.record_id in decided and r.drift_kind == "REGION"
    }
    assert len(hashes) == 3  # three separate code events, not one
    assert _candidates(tmp_path) == [("REGION", 3)]
    assert _candidates(tmp_path, min_count=1) == [("HASH", 1), ("REGION", 3)]


def test_a_retried_mcp_resolve_is_still_one_decision(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-007
    # resolve_drift appends; a retry (lost ack, double click) leaves two lines.
    cfg = _repo(tmp_path)
    for event in (1, 2):
        shared = _mcp_event(cfg, tmp_path, event)
        _resolve(cfg, tmp_path, shared)
        _resolve(cfg, tmp_path, shared)
    assert len(read_resolutions(tmp_path / DEFAULT_RESOLUTIONS_PATH)) == 4
    assert _candidates(tmp_path) == []
    assert _candidates(tmp_path, min_count=2) == [("HASH", 2), ("REGION", 2)]


def test_an_unresolved_code_event_never_counts(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-007
    cfg = _repo(tmp_path)
    ids = [_mcp_event(cfg, tmp_path, event) for event in (1, 2, 3)]
    for record_id in ids[:2]:
        _resolve(cfg, tmp_path, record_id)
    assert _candidates(tmp_path) == []
    assert _candidates(tmp_path, min_count=2) == [("HASH", 2), ("REGION", 2)]


def test_a_region_dissent_never_blocks_the_hash_shape(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-008
    # Three MCP events invalidated (HASH 3, REGION 3). A fourth event's REGION ids
    # are REJECTED, its HASH left open: REGION loses unanimity, HASH is untouched.
    cfg = _repo(tmp_path)
    for event in (1, 2, 3):
        _resolve(cfg, tmp_path, _mcp_event(cfg, tmp_path, event))
    _hash, regions = _ticking_event(cfg, tmp_path, 4)
    for rec in regions:
        _resolve(cfg, tmp_path, rec.record_id, "rejected")
    cands = detect_promotions(
        read_all(tmp_path / DEFAULT_LOG_PATH),
        read_resolutions(tmp_path / DEFAULT_RESOLUTIONS_PATH),
    )
    assert [(c.drift_kind, c.resolution, c.count) for c in cands] == [
        ("HASH", Resolution.INVALIDATED, 3)
    ]


# --- The pinned residual: a per-record clock ------------------------------------


def test_cli_same_run_resolves_count_per_id_known_residual(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-008
    # KNOWN RESIDUAL, pinned so a change is deliberate. ONE code event under a
    # per-record clock (what `cdx monitor`'s _default_now produces) gives each
    # region its own id; resolving all three counts 3 and promotes. The same event
    # through MCP counts 1 (test_one_mcp_resolve_...). A run-grain count
    # (PROMO-RUN, after OKF-RUNID) must flip this expectation to [].
    cfg = _repo(tmp_path)
    _hash, regions = _ticking_event(cfg, tmp_path, 1)
    assert len({r.surface_hash for r in regions}) == 1  # ONE code event
    for rec in regions:
        _resolve(cfg, tmp_path, rec.record_id)
    assert _candidates(tmp_path) == [("REGION", 3)]


def test_repeated_mcp_runs_of_one_code_event_count_per_run_known_residual(
    tmp_path: Path,
) -> None:
    # Feature: FEAT-LEARN-008
    # KNOWN RESIDUAL, pinned so a change is deliberate. ONE code event previewed by
    # three custodex_remediate calls (the MCP server injects a fresh `now` per call)
    # mints three ids over one surface; resolving each once counts 3 and promotes.
    # A run-grain count does NOT close this (three runs); the unit must be the code
    # event. Whoever changes the unit must flip this expectation to [].
    cfg = _repo(tmp_path)
    _change_code(tmp_path, 1)  # ONE code event
    ids = []
    for call in range(3):
        result = remediate_drift(cfg, tmp_path, repo_id="demo", now=_stamp(1, call))
        (record_id,) = {it.record_id for it in result.items}
        ids.append(record_id)
    assert len(set(ids)) == 3  # a fresh clock per call -> a fresh id per run
    records = read_all(tmp_path / DEFAULT_LOG_PATH)
    assert len({r.surface_hash for r in records}) == 1  # ...over ONE code event
    for record_id in ids:
        _resolve(cfg, tmp_path, record_id)
    assert _candidates(tmp_path) == [("HASH", 3), ("REGION", 3)]


# --- The user-facing consumers ---------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="cli.promotions calls detect_promotions outside its CodeDocMonitorError "
    "try, so --min-count < 1 escapes as an uncaught ConfigError. cli.py is outside "
    "PROMO-DISTINCT's file set. EITHER fix flips this test (moving the call into "
    "the try, or typer min=1 on --min-count); the slice that fixes it must drop "
    "this marker (strict: an unexpected pass fails).",
)
@pytest.mark.parametrize("min_count", ["0", "-1"])
def test_cdx_promotions_min_count_below_one_is_a_clean_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, min_count: str
) -> None:
    # Feature: FEAT-LEARN-007
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["promotions", "--config", "cdmon.yaml", "--min-count", min_count]
    )
    # Only the behaviour that matters, so ANY clean fix flips it: no uncaught
    # exception, a non-zero exit, and a message naming the option (the CLI's own
    # "error: ... min_count ..." line or Click's "Invalid value for '--min-count'").
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert result.exit_code != 0
    assert re.search(r"min[-_]count", result.output, re.IGNORECASE), result.output


def test_cdx_promotions_counts_distinct_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feature: FEAT-LEARN-007
    cfg = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    _resolve(cfg, tmp_path, _mcp_event(cfg, tmp_path, 1))

    def promotions(*extra: str) -> str:
        result = runner.invoke(app, ["promotions", "--config", "cdmon.yaml", *extra])
        assert result.exit_code == 0, result.output
        return result.stdout

    assert "no promotable shapes" in promotions()
    single = json.loads(promotions("--min-count", "1", "--json"))
    assert [(c["drift_kind"], c["count"]) for c in single] == [
        ("HASH", 1),
        ("REGION", 1),
    ]
    for event in (2, 3):
        _resolve(cfg, tmp_path, _mcp_event(cfg, tmp_path, event))
    three = json.loads(promotions("--json"))
    assert [(c["drift_kind"], c["count"]) for c in three] == [
        ("HASH", 3),
        ("REGION", 3),
    ]


def test_promote_rule_suggestion_counts_distinct_decisions(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-007
    cfg = _repo(tmp_path)
    for event in (1, 2, 3):
        _resolve(cfg, tmp_path, _mcp_event(cfg, tmp_path, event))
    promote = [
        s
        for s in suggest_fixes_tick(cfg, tmp_path, now=_stamp(21))
        if s.kind is SuggestionKind.PROMOTE_RULE
    ]
    assert [(s.target, s.evidence) for s in promote] == [
        ("HASH:eng-guide", ("count: 3",)),
        ("REGION:eng-guide", ("count: 3",)),
    ]


# --- The hub: duplicate rows from retried POSTs ----------------------------------


def _hub(tmp_path: Path, events: tuple[int, ...]) -> tuple[Callable, list, list]:
    """MCP-produce + resolve ``events``; return ``(client_factory, records, res)``."""
    pytest.importorskip("fastapi", reason="the [server] extra is not installed")
    from fastapi.testclient import TestClient

    from custodex.server import InMemoryStore, create_app
    from custodex.sinks import IngestEnvelope, RepoIdentity

    cfg = _repo(tmp_path)
    for event in events:
        _resolve(cfg, tmp_path, _mcp_event(cfg, tmp_path, event))
    records = read_all(tmp_path / DEFAULT_LOG_PATH)
    resolutions = read_resolutions(tmp_path / DEFAULT_RESOLUTIONS_PATH)
    identity = RepoIdentity(
        repo_id="acme/widget",
        repo_name="widget",
        repo_url="https://example.invalid/acme/widget",
        commit="deadbeef",
    )

    def make_client() -> tuple[TestClient, Callable[[ReviewRecord], None]]:
        client = TestClient(create_app(InMemoryStore()))
        reg = {"repo": identity.model_dump(mode="json"), "default_branch": "main"}
        assert client.post("/repos", json=reg).status_code < 300

        def ingest(record: ReviewRecord) -> None:
            env = IngestEnvelope(repo=identity, record=record).model_dump(mode="json")
            assert client.post("/ingest", json=env).status_code < 300

        return client, ingest

    return make_client, records, resolutions


def _post_resolution(client, res: ResolutionRecord) -> None:
    resp = client.post(
        "/repos/acme%2Fwidget/resolutions", json=res.model_dump(mode="json")
    )
    assert resp.status_code == 202, resp.text


def _telemetry_candidates(client) -> list[tuple[str, int]]:
    body = client.get("/repos/acme%2Fwidget/telemetry").json()
    return [(c["drift_kind"], c["count"]) for c in body["promotion_candidates"]]


def test_reingested_records_count_once_in_hub_telemetry(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-007
    # A sink retry re-POSTs a record; the hub stores both rows (no dedupe).
    make_client, records, resolutions = _hub(tmp_path, (1, 2, 3))
    client, ingest = make_client()
    for record in records + records:
        ingest(record)
    for res in resolutions:
        _post_resolution(client, res)
    assert _telemetry_candidates(client) == [("HASH", 3), ("REGION", 3)]


def test_hub_resolution_repost_is_still_one_decision(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-007
    # Every resolution POSTed twice (a retry after a lost ack): still 2 decisions.
    make_client, records, resolutions = _hub(tmp_path, (1, 2))
    client, ingest = make_client()
    for record in records:
        ingest(record)
    for res in resolutions + resolutions:
        _post_resolution(client, res)
    assert _telemetry_candidates(client) == []


def test_resolutions_file_round_trips_a_retry_as_two_lines(tmp_path: Path) -> None:
    # Feature: FEAT-LEARN-007
    # Guard on the premise: the append-only log really does keep both lines of a
    # retried resolve, so the "one decision" tests above are not vacuous.
    path = tmp_path / DEFAULT_RESOLUTIONS_PATH
    res = ResolutionRecord(
        record_id="r1", resolution=Resolution.INVALIDATED, resolved_at=_stamp(0)
    )
    append_resolution(path, res)
    append_resolution(path, res)
    assert len(read_resolutions(path)) == 2
