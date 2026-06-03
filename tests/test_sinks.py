"""Tests for code_doc_monitor.sinks (CDM-04).

The central sink is offline by default (K4): NullSink/FileSink need no network
and FileSink is the offline stand-in for the central system. HttpSink is
exercised ONLY through an injected fake client — no real network is ever
touched (K4) and HTTP uses the stdlib (K0). TDD (K9).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.config import Audience, CentralConfig
from code_doc_monitor.errors import SchemaError
from code_doc_monitor.reviewlog import read_all
from code_doc_monitor.schema import ProposedFix, ReviewRecord, Verdict
from code_doc_monitor.sinks import (
    FileSink,
    HttpSink,
    NullSink,
    make_sink,
)


def _record(record_id: str = "r1") -> ReviewRecord:
    return ReviewRecord(
        record_id=record_id,
        doc_id="user-guide",
        doc_path="docs/user-guide.md",
        audience=Audience.USER_GUIDE,
        drift_kind="HASH",
        drift_detail="moved",
        cause="changed",
        verdict=Verdict.FIX,
        fix=ProposedFix(
            region_id="symbols",
            new_region_body="body",
            new_doc_text=None,
            rationale="r",
        ),
        surface_hash="hash",
        backend_kind="mock",
        detected_at="2026-06-01T00:00:00Z",
        resolved_at="2026-06-01T00:00:01Z",
        config_snapshot={},
    )


class FakeClient:
    """An injected stand-in for an HTTP client: records calls, no network."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None:
        self.calls.append({"url": url, "data": data, "headers": headers})


def test_null_sink_does_nothing() -> None:
    # No exception, no side effect — just proves the protocol shape.
    NullSink().emit(_record())


def test_file_sink_writes_one_line_per_emit(tmp_path: Path) -> None:
    path = tmp_path / "central.jsonl"
    sink = FileSink(path)
    sink.emit(_record("r1"))
    sink.emit(_record("r2"))
    # Round-trips back through the review-record parser.
    out = read_all(path)
    assert [r.record_id for r in out] == ["r1", "r2"]


def test_http_sink_uses_injected_client_with_url_body_and_no_auth() -> None:
    client = FakeClient()
    sink = HttpSink("https://central.example/ingest", client=client)
    rec = _record()
    sink.emit(rec)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://central.example/ingest"
    # Body is the exact record JSON.
    assert call["data"] == rec.model_dump_json().encode("utf-8")
    headers = call["headers"]
    assert headers["Content-Type"] == "application/json"
    assert "Authorization" not in headers


def test_http_sink_adds_bearer_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDM_TOKEN", "s3cret")
    client = FakeClient()
    sink = HttpSink(
        "https://central.example/ingest", auth_env="CDM_TOKEN", client=client
    )
    sink.emit(_record())
    headers = client.calls[0]["headers"]
    assert headers["Authorization"] == "Bearer s3cret"


def test_http_sink_no_header_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CDM_TOKEN", raising=False)
    client = FakeClient()
    sink = HttpSink(
        "https://central.example/ingest", auth_env="CDM_TOKEN", client=client
    )
    sink.emit(_record())
    assert "Authorization" not in client.calls[0]["headers"]


def test_http_sink_lazily_builds_stdlib_client_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When no client is injected, emit() builds a stdlib _UrllibClient lazily.
    # We stub its post() so the lazy-build branch runs with NO real network (K4).
    import code_doc_monitor.sinks as sinks_mod

    posted: list[tuple[str, bytes]] = []

    def fake_post(self: object, url: str, *, data: bytes, headers: dict) -> None:
        posted.append((url, data))

    monkeypatch.setattr(sinks_mod._UrllibClient, "post", fake_post)
    sink = HttpSink("https://central.example/ingest")
    sink.emit(_record())
    assert posted and posted[0][0] == "https://central.example/ingest"


def test_make_sink_none() -> None:
    sink = make_sink(CentralConfig(sink="none"))
    assert isinstance(sink, NullSink)


def test_make_sink_file(tmp_path: Path) -> None:
    cfg = CentralConfig(sink="file", path=str(tmp_path / "c.jsonl"))
    sink = make_sink(cfg)
    assert isinstance(sink, FileSink)


def test_make_sink_file_missing_path_raises() -> None:
    with pytest.raises(SchemaError):
        make_sink(CentralConfig(sink="file"))


def test_make_sink_http() -> None:
    cfg = CentralConfig(sink="http", url="https://central.example/ingest")
    sink = make_sink(cfg)
    assert isinstance(sink, HttpSink)


def test_make_sink_http_missing_url_raises() -> None:
    with pytest.raises(SchemaError):
        make_sink(CentralConfig(sink="http"))
