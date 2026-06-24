"""The external-repo adopter example, proven end-to-end (G-04 — capstone).

``examples/external-repo/`` is a SMALL self-contained stand-in for "some other
team's repo" that ADOPTS cdx: its own ``src/widget.py`` + ``docs/api.md``
(managed ``symbols`` region) + ``cdmon.yaml`` (an http ``central:`` block). This
test drives the WHOLE adopter loop offline (K4):

    client config -> heal (check -> monitor --apply) -> report -> server stores
    -> query

It copies the fixture under ``tmp_path``, mutates ``src/widget.py`` so ``cdx
check`` reports drift, heals it with ``monitor --apply``, then registers the repo
and reports the healed records to an IN-PROCESS central server (FastAPI
``TestClient``) — wiring the ``HttpSink``'s injected ``client`` to call the
TestClient — WITH a bearer token (E-06). It asserts ``GET /repos`` +
``GET /repos/{id}/records`` show the repo + the healed records, and that a WRONG
bearer token is rejected server-side (the bearer write path proven, no socket).

The fixture's OWN code is not scanned by the dogfood config (a different tree), so
this is insulated from the package's source churn (mirrors test_example_multilang).

Features: FEAT-CONFIG-008, FEAT-CONFIG-009, FEAT-DRIFT-001, FEAT-MONITOR-001
Features: FEAT-MONITOR-003, FEAT-MONITOR-004, FEAT-HEAL-001, FEAT-RECORD-001
Features: FEAT-RECORD-010, FEAT-RECORD-012, FEAT-SERVER-001, FEAT-SERVER-002
Features: FEAT-SERVER-003, FEAT-SERVER-004, FEAT-SERVER-017
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests._repo import REPO_ROOT

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from custodex.config import load_config  # noqa: E402
from custodex.monitor import Monitor  # noqa: E402
from custodex.registry import (  # noqa: E402
    HttpRegisterTransport,
    register_repo,
    repo_identity_from_config,
)
from custodex.schema import ReviewRecord  # noqa: E402
from custodex.server import InMemoryStore, create_app  # noqa: E402
from custodex.sinks import HttpSink, RepoIdentity  # noqa: E402

_EXAMPLE = REPO_ROOT / "examples" / "external-repo"
_TOKEN = "adopter-s3cret"


# --------------------------------------------------------------------------- #
# Test-only adapters wiring HttpSink/register transport to an in-process server.
# Kept in the TEST so the PACKAGE stays clean (no TestClient knowledge leaks in).
# --------------------------------------------------------------------------- #


class _TestClientPostClient:
    """Adapt the ``HttpSink`` injected client shape onto a FastAPI ``TestClient``.

    ``HttpSink`` posts via ``post(url, *, data, headers)`` and treats ANY raised
    exception as "transport down" (K4). So a non-2xx response (e.g. a 401/403 from
    a wrong bearer token) must RAISE here for the sink's retry/outbox path to fire
    — exactly as a real HTTP client raising on an error status would.
    """

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None:
        resp = self._client.post(url, content=data, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"central server returned {resp.status_code}: {resp.text}"
            )


class _TestClientRegisterHttp:
    """Adapt the register transport's HTTP leaf (``_RegisterHttp``) onto a TestClient.

    ``HttpRegisterTransport`` calls ``request(method, url, *, body, token)``; we route
    it to the in-process server (TestClient resolves the URL by path).
    """

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def request(self, method: str, url: str, *, body: dict | None, token: str) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = self._client.request(method, url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json() if resp.content else {}


def _register_transport(client: TestClient) -> HttpRegisterTransport:
    """A register transport that POSTs `<url>/repos` to the in-process server."""
    return HttpRegisterTransport("http://central", http=_TestClientRegisterHttp(client))


@pytest.fixture
def example(tmp_path: Path) -> Path:
    """Copy the committed fixture under tmp_path so the repo is never mutated."""
    dst = tmp_path / "external-repo"
    shutil.copytree(_EXAMPLE, dst)
    return dst


def _http_sink(client: TestClient, identity: RepoIdentity, outbox: Path) -> HttpSink:
    """An HttpSink wired to the in-process server, with the example's ingest URL."""
    cfg = load_config(_EXAMPLE / "cdmon.yaml")
    return HttpSink(
        cfg.central.url or "",
        cfg.central.auth_env,
        repo=identity,
        outbox=outbox,
        client=_TestClientPostClient(client),
    )


def test_committed_example_is_in_sync() -> None:
    """The checked-in fixture is clean: cdx check finds no drift (read-only K1)."""
    cfg = load_config(_EXAMPLE / "cdmon.yaml")
    assert Monitor(cfg, _EXAMPLE).check().ok


def test_adopter_loop_heals_reports_and_queries(
    example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_config(example / "cdmon.yaml")

    # 1. The copy starts in sync; mutate the source so `check` now sees drift.
    assert Monitor(cfg, example).check().ok
    widget = example / "src" / "widget.py"
    widget.write_text(
        widget.read_text(encoding="utf-8")
        + "\n\ndef widget_label(prefix: str, n: int) -> str:\n"
        '    return f"{prefix}-{n}"\n',
        encoding="utf-8",
    )
    assert not Monitor(cfg, example).check().ok  # drift detected

    # 2. Stand up the in-process central server and register the repo (bearer auth).
    store = InMemoryStore()
    server = TestClient(create_app(store))
    identity = repo_identity_from_config(cfg.central)
    reg = register_repo(
        identity,
        url="http://central",
        transport=_register_transport(server),
        auth_token=_TOKEN,
    )
    assert reg == {"repo_id": "acme/widget"}
    assert [r["repo"]["repo_id"] for r in server.get("/repos").json()] == [
        "acme/widget"
    ]

    # 3. Heal the docs AND report each review record to the server via HttpSink,
    #    wired to the TestClient with the correct bearer token.
    monkeypatch.setenv(cfg.central.auth_env or "CDMON_CENTRAL_TOKEN", _TOKEN)
    sink = _http_sink(server, identity, example / ".cdmon" / "outbox.jsonl")
    result = Monitor(cfg, example, sink=sink, now=lambda: "2026-06-05T00:00:00Z").run(
        apply=True
    )
    assert result.records  # at least one verdict recorded + emitted
    assert Monitor(cfg, example).check().ok  # fully self-healed

    # 4. Query the server: the healed records landed under the right repo_id and
    #    round-trip byte-for-byte through the SHARED schema (K6).
    got = server.get("/repos/acme%2Fwidget/records").json()
    assert len(got) == len(result.records)
    server_ids = {r["record_id"] for r in got}
    assert server_ids == {rec.record_id for rec in result.records}
    for body in got:
        ReviewRecord.model_validate(body)  # valid shared-schema records

    # The outbox drained cleanly (every record sent, queue empty / absent).
    outbox = example / ".cdmon" / "outbox.jsonl"
    assert not outbox.exists() or outbox.read_text(encoding="utf-8").strip() == ""


def test_wrong_bearer_token_is_rejected_server_side(
    example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A WRONG token is rejected by the server (the bearer write path, E-06)."""
    cfg = load_config(example / "cdmon.yaml")
    store = InMemoryStore()
    server = TestClient(create_app(store))
    identity = repo_identity_from_config(cfg.central)
    register_repo(
        identity,
        url="http://central",
        transport=_register_transport(server),
        auth_token=_TOKEN,
    )

    # Heal-and-report with the WRONG token: the server rejects every ingest, so the
    # sink (K4: never raises) queues the records to its outbox instead.
    widget = example / "src" / "widget.py"
    widget.write_text(
        widget.read_text(encoding="utf-8")
        + "\n\ndef widget_tag(name: str) -> str:\n    return name.upper()\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(cfg.central.auth_env or "CDMON_CENTRAL_TOKEN", "WRONG-token")
    outbox = example / ".cdmon" / "outbox.jsonl"
    sink = _http_sink(server, identity, outbox)
    result = Monitor(cfg, example, sink=sink, now=lambda: "2026-06-05T00:00:00Z").run(
        apply=True
    )
    assert result.records

    # Nothing landed server-side (every write was 403'd), and the records queued.
    assert server.get("/repos/acme%2Fwidget/records").json() == []
    assert outbox.exists() and outbox.read_text(encoding="utf-8").strip()

    # Prove the rejection directly: a raw ingest with the wrong token -> 403.
    envelope_line = outbox.read_text(encoding="utf-8").splitlines()[0]
    json_ct = {"Content-Type": "application/json"}
    bad = server.post(
        cfg.central.url or "",
        content=envelope_line.encode("utf-8"),
        headers={**json_ct, "Authorization": "Bearer WRONG-token"},
    )
    assert bad.status_code == 403
    # And the SAME envelope with the RIGHT token is accepted (202) — bearer proven.
    ok = server.post(
        cfg.central.url or "",
        content=envelope_line.encode("utf-8"),
        headers={**json_ct, "Authorization": f"Bearer {_TOKEN}"},
    )
    assert ok.status_code == 202
