"""Tests for custodex.sinks (CDM-04).

The central sink is offline by default (K4): NullSink/FileSink need no network
and FileSink is the offline stand-in for the central system. HttpSink is
exercised ONLY through an injected fake client — no real network is ever
touched (K4) and HTTP uses the stdlib (K0). TDD (K9).

Features: FEAT-RECORD-010, FEAT-RECORD-011, FEAT-RECORD-012, FEAT-RECORD-013
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.config import Audience, CentralConfig
from custodex.errors import SchemaError
from custodex.reviewlog import read_all
from custodex.schema import ProposedFix, ReviewRecord, Verdict
from custodex.sinks import (
    FileSink,
    HttpSink,
    IngestEnvelope,
    NullSink,
    RepoIdentity,
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


class FlakyClient:
    """A client whose POST fails ``fail_first`` times, optionally per-URL never.

    ``down`` makes every POST raise (network down). ``fail_for`` is a set of
    1-based call ordinals that raise; all others succeed. Records every accepted
    POST in ``calls`` (the bytes), so flush ORDER can be asserted.
    """

    def __init__(
        self,
        *,
        down: bool = False,
        fail_for: set[int] | None = None,
    ) -> None:
        self.down = down
        self.fail_for = fail_for or set()
        self.attempts = 0
        self.calls: list[bytes] = []

    def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None:
        self.attempts += 1
        if self.down or self.attempts in self.fail_for:
            raise OSError("network down")
        self.calls.append(data)


def _repo() -> RepoIdentity:
    return RepoIdentity(
        repo_id="acme/widget",
        repo_name="widget",
        repo_url="https://git.example/acme/widget",
        commit="deadbeef",
    )


def _envelopes(client: FlakyClient | FakeClient) -> list[IngestEnvelope]:
    raw = client.calls
    datas = raw if raw and isinstance(raw[0], bytes) else [c["data"] for c in raw]  # type: ignore[index]
    return [IngestEnvelope.model_validate_json(d) for d in datas]


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


def test_http_sink_posts_repo_identified_envelope() -> None:
    client = FakeClient()
    sink = HttpSink("https://central.example/ingest", repo=_repo(), client=client)
    rec = _record()
    sink.emit(rec)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://central.example/ingest"
    # Body decodes to an IngestEnvelope carrying the repo identity + the record.
    env = IngestEnvelope.model_validate_json(call["data"])  # type: ignore[arg-type]
    assert env.schema_version == "1.0.0"
    assert env.repo.repo_id == "acme/widget"
    assert env.repo.commit == "deadbeef"
    assert env.record.record_id == rec.record_id
    headers = call["headers"]
    assert headers["Content-Type"] == "application/json"
    assert "Authorization" not in headers


def test_http_sink_adds_bearer_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDM_TOKEN", "s3cret")
    client = FakeClient()
    sink = HttpSink(
        "https://central.example/ingest",
        auth_env="CDM_TOKEN",
        repo=_repo(),
        client=client,
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
        "https://central.example/ingest",
        auth_env="CDM_TOKEN",
        repo=_repo(),
        client=client,
    )
    sink.emit(_record())
    assert "Authorization" not in client.calls[0]["headers"]


def test_http_sink_lazily_builds_stdlib_client_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When no client is injected, emit() builds a stdlib _UrllibClient lazily.
    # We stub its post() so the lazy-build branch runs with NO real network (K4).
    import custodex.sinks as sinks_mod

    posted: list[tuple[str, bytes]] = []

    def fake_post(self: object, url: str, *, data: bytes, headers: dict) -> None:
        posted.append((url, data))

    monkeypatch.setattr(sinks_mod._UrllibClient, "post", fake_post)
    sink = HttpSink("https://central.example/ingest", repo=_repo())
    sink.emit(_record())
    assert posted and posted[0][0] == "https://central.example/ingest"


# --- E-01: offline queue + retry -------------------------------------------


def test_emit_while_down_queues_to_outbox_and_never_raises(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    client = FlakyClient(down=True)
    sink = HttpSink(
        "https://central.example/ingest",
        repo=_repo(),
        outbox=outbox,
        max_retries=2,
        client=client,
    )
    # Three emits while the network is down — none raise.
    sink.emit(_record("r1"))
    sink.emit(_record("r2"))
    sink.emit(_record("r3"))
    assert client.calls == []  # nothing accepted
    lines = outbox.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    queued = [IngestEnvelope.model_validate_json(line) for line in lines]
    assert [e.record.record_id for e in queued] == ["r1", "r2", "r3"]


def test_recovery_flushes_outbox_oldest_first_then_new(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    # Queue r1, r2 while down.
    down = FlakyClient(down=True)
    sink = HttpSink(
        "https://central.example/ingest",
        repo=_repo(),
        outbox=outbox,
        client=down,
    )
    sink.emit(_record("r1"))
    sink.emit(_record("r2"))

    # Now the network is up: emitting r3 drains r1, r2 (oldest-first) THEN r3.
    up = FlakyClient()
    sink._client = up  # swap the injected transport
    sink.emit(_record("r3"))

    sent = [e.record.record_id for e in _envelopes(up)]
    assert sent == ["r1", "r2", "r3"]
    assert not outbox.exists() or outbox.read_text(encoding="utf-8").strip() == ""


def test_partial_flush_requeues_remainder_in_order(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    down = FlakyClient(down=True)
    sink = HttpSink(
        "https://central.example/ingest",
        repo=_repo(),
        outbox=outbox,
        max_retries=1,
        client=down,
    )
    sink.emit(_record("r1"))
    sink.emit(_record("r2"))
    sink.emit(_record("r3"))

    # Recovery client accepts the 1st drained item, FAILS on the 2nd (call #2).
    flaky = FlakyClient(fail_for={2})
    sink._client = flaky
    sink.emit(_record("r4"))

    # r1 sent; r2 failed -> r2, r3 re-queued; r4 (new) also queued behind them.
    assert [e.record.record_id for e in _envelopes(flaky)] == ["r1"]
    lines = outbox.read_text(encoding="utf-8").splitlines()
    queued = [IngestEnvelope.model_validate_json(line) for line in lines]
    assert [e.record.record_id for e in queued] == ["r2", "r3", "r4"]


def test_retry_succeeds_within_max_retries_no_queue(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    # Fail the 1st attempt, succeed the 2nd (max_retries=2 => 2 attempts).
    client = FlakyClient(fail_for={1})
    sink = HttpSink(
        "https://central.example/ingest",
        repo=_repo(),
        outbox=outbox,
        max_retries=2,
        client=client,
    )
    sink.emit(_record("r1"))
    assert client.attempts == 2  # one failed, one succeeded
    assert [e.record.record_id for e in _envelopes(client)] == ["r1"]
    assert not outbox.exists()


def test_emit_with_no_outbox_configured_never_raises_when_down() -> None:
    # outbox=None: a down network must still not raise (reporting is best-effort).
    client = FlakyClient(down=True)
    sink = HttpSink(
        "https://central.example/ingest",
        repo=_repo(),
        outbox=None,
        max_retries=1,
        client=client,
    )
    sink.emit(_record("r1"))  # no raise, nothing to assert beyond that


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
    cfg = CentralConfig(
        sink="http", url="https://central.example/ingest", repo_id="acme/widget"
    )
    sink = make_sink(cfg)
    assert isinstance(sink, HttpSink)


def test_make_sink_http_missing_url_raises() -> None:
    with pytest.raises(SchemaError):
        make_sink(CentralConfig(sink="http", repo_id="acme/widget"))


def test_make_sink_http_missing_repo_id_raises() -> None:
    # K8: http sink with no repo_id is a loud, typed error — not a silent pass.
    with pytest.raises(SchemaError):
        make_sink(CentralConfig(sink="http", url="https://central.example/ingest"))


def test_make_sink_http_commit_from_config(tmp_path: Path) -> None:
    cfg = CentralConfig(
        sink="http",
        url="https://central.example/ingest",
        repo_id="acme/widget",
        repo_commit="cafef00d",
        outbox=str(tmp_path / "ob.jsonl"),
    )
    sink = make_sink(cfg)
    assert isinstance(sink, HttpSink)
    client = FakeClient()
    sink._client = client
    sink.emit(_record())
    env = IngestEnvelope.model_validate_json(client.calls[0]["data"])  # type: ignore[arg-type]
    assert env.repo.commit == "cafef00d"


def test_make_sink_http_commit_falls_back_to_ci_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI_COMMIT_SHA", "abc123")
    cfg = CentralConfig(
        sink="http", url="https://central.example/ingest", repo_id="acme/widget"
    )
    sink = make_sink(cfg)
    client = FakeClient()
    sink._client = client  # type: ignore[attr-defined]
    sink.emit(_record())
    env = IngestEnvelope.model_validate_json(client.calls[0]["data"])  # type: ignore[arg-type]
    assert env.repo.commit == "abc123"
