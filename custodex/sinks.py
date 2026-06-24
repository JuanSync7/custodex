"""Central-system sinks — offline by default (K0, K4).

A sink emits a :class:`ReviewRecord` to "the central monitoring system". The
default is :class:`NullSink` (does nothing) and :class:`FileSink` is an offline
stand-in (append JSON to a file) — both run in CI with zero network (K4).
:class:`HttpSink` POSTs to a URL, but its HTTP client is *injected* so tests
exercise it with a fake and never touch the network (K4); when no client is
injected it lazily builds one from the standard library only (no ``requests``,
K0). :func:`make_sink` resolves a :class:`CentralConfig` to one of these.

E-01 makes :class:`HttpSink` a robust multi-repo reporter. Every record is
wrapped in a versioned, repo-identified :class:`IngestEnvelope` — the SHARED
client↔server wire format (K6): the E-03 server's ``/ingest`` consumes this very
model (ONE schema, no DTOs). ``emit`` first drains a local outbox (oldest-first,
re-queueing on the first failure), then sends the new envelope with bounded
retry, and on final failure queues it to the outbox JSONL — it NEVER raises, so
a flaky network or down central system can never break a heal run (K4).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from .config import CentralConfig
from .errors import SchemaError
from .schema import ReviewRecord

__all__ = [
    "Sink",
    "NullSink",
    "FileSink",
    "HttpSink",
    "RepoIdentity",
    "IngestEnvelope",
    "make_sink",
]

# Frozen + extra="forbid": the wire envelope is an immutable, audited artifact
# and an unexpected key is a loud error, not a silent pass (K8, mirrors schema.py).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class RepoIdentity(BaseModel):
    """Which repo a review record came from (E-01).

    Part of the shared :class:`IngestEnvelope` wire format. ``repo_id`` is the
    stable identifier the central system keys on; ``commit`` pins the source
    revision (from config or ``$CI_COMMIT_SHA``).
    """

    model_config = _MODEL_CONFIG

    repo_id: str
    repo_name: str | None = None
    repo_url: str | None = None
    commit: str | None = None
    # Y-02 (ADDITIVE, K6): where the central server reads this repo from on a
    # local filesystem, and which branch is its baseline. Both default ``None``
    # so every pre-Y-02 identity still validates; the config-sync route requires
    # ``local_path`` to be set (loud 400 otherwise). Appended LAST so field order
    # is untouched.
    local_path: str | None = None
    default_branch: str | None = None
    # GIT-02 (ADDITIVE, K6): how the central server fetches this repo when it does
    # NOT hold it locally (EPIC GIT, clone-on-demand). ``provider`` selects the
    # git host (and its auth/transport conventions); ``remote_url`` is the
    # CLONE/API url. NOTE: this is distinct from ``repo_url`` above, which is the
    # inert *browse* URL (a link surfaced in the UI) — ``remote_url`` is the one
    # :class:`~custodex.gitfetch.RemoteSpec`/the PR transports act on.
    # Both default ``None`` (a local-only repo carries neither) and ride in the
    # stored payload JSON, so no DB migration is needed. Appended LAST.
    provider: Literal["github", "gitlab"] | None = None
    remote_url: str | None = None
    # GIT-05 (ADDITIVE, K6): HOW the sealed ``provider_secret`` is used (EPIC GIT
    # PHASE 2). ``None``/``"token"`` (the default) = the opened secret IS the
    # credential, replayed as-is (PHASE 1). ``"github-app"``/``"gitlab-oauth"`` = the
    # opened secret is a JSON credential the server mints a SHORT-LIVED access token
    # from on each op (the hot token is never stored). Default ``None`` keeps every
    # pre-GIT-05 identity valid. Appended LAST.
    provider_kind: Literal["token", "github-app", "gitlab-oauth"] | None = None


class IngestEnvelope(BaseModel):
    """The versioned client↔server wire format for one reported record (K6).

    Wraps a :class:`ReviewRecord` with its :class:`RepoIdentity`. This is the ONE
    schema both the :class:`HttpSink` client and the E-03 ``/ingest`` server use —
    no separate DTOs. ``schema_version`` is additive across versions (K6).
    """

    model_config = _MODEL_CONFIG

    schema_version: str = "1.0.0"
    repo: RepoIdentity
    record: ReviewRecord


@runtime_checkable
class Sink(Protocol):
    """Something that can emit a review record to a central system."""

    def emit(self, record: ReviewRecord) -> None: ...


class _PostClient(Protocol):
    """The injected HTTP client shape: a single ``post`` method."""

    def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None: ...


class NullSink:
    """The default sink — emits nowhere (offline, K4)."""

    def emit(self, record: ReviewRecord) -> None:
        return None


class FileSink:
    """Append each record's JSON to a file — the offline central stand-in (K4).

    Lines are written in the same JSONL shape as the review log, so they can be
    read back with :func:`reviewlog.read_all`.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def emit(self, record: ReviewRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json())
            fh.write("\n")


class _UrllibClient:
    """A stdlib-only POST client (no ``requests``, K0). Never used in tests."""

    def post(  # pragma: no cover — the real network leaf, never hit in tests (K4)
        self, url: str, *, data: bytes, headers: dict[str, str]
    ) -> None:
        import urllib.request

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req):  # noqa: S310 (url comes from trusted config)
            pass


class HttpSink:
    """POST a repo-identified :class:`IngestEnvelope` to ``url`` (K4, K6).

    The HTTP ``client`` is injected (any object with a ``post(url, *, data,
    headers)`` method) so tests never hit the network. If ``client is None`` at
    emit time a stdlib-only :class:`_UrllibClient` is built lazily (K0). The
    bearer token, when ``auth_env`` is set and present in the environment, is
    read at emit time so a rotated token is picked up without rebuilding.

    ``emit`` is best-effort and NEVER raises (K4) — reporting must not break a
    heal run. It (1) wraps the record in an :class:`IngestEnvelope`, (2) drains
    the outbox oldest-first (stopping and re-queueing the remainder on the first
    failure, preserving order), (3) sends the new envelope with up to
    ``max_retries`` attempts, and (4) on final failure appends the new envelope
    to the outbox JSONL. The outbox is a JSONL of envelope lines; draining reads
    all lines then rewrites only the undrained remainder (a simple, deterministic
    read-all/rewrite — this sink is single-process).
    """

    def __init__(
        self,
        url: str,
        auth_env: str | None = None,
        *,
        repo: RepoIdentity,
        outbox: Path | None = None,
        max_retries: int = 2,
        client: _PostClient | None = None,
    ) -> None:
        self._url = url
        self._auth_env = auth_env
        self._repo = repo
        self._outbox = outbox
        self._max_retries = max(1, max_retries)
        self._client = client

    def emit(self, record: ReviewRecord) -> None:
        envelope = IngestEnvelope(repo=self._repo, record=record)
        client = self._client
        if client is None:
            client = self._client = _UrllibClient()

        # 1. Drain the outbox oldest-first. If a queued envelope fails to send,
        #    stop and re-queue it plus everything after it (order preserved).
        drained_cleanly = self._drain(client)

        # 2. Only attempt the new envelope if the backlog is clear — otherwise
        #    it must queue BEHIND the backlog to keep oldest-first ordering.
        if drained_cleanly and self._try_send(client, envelope):
            return

        # 3. Final failure (backlog blocked or new send exhausted): queue it.
        self._enqueue(envelope)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_env:
            token = os.environ.get(self._auth_env)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _try_send(self, client: _PostClient, envelope: IngestEnvelope) -> bool:
        """POST ``envelope`` with up to ``max_retries`` attempts; True on success."""
        for _ in range(self._max_retries):
            try:
                client.post(
                    self._url,
                    data=envelope.model_dump_json().encode("utf-8"),
                    headers=self._headers(),
                )
                return True
            except Exception:  # noqa: BLE001 — any transport error == "down" (K4)
                continue
        return False

    def _read_outbox(self) -> list[IngestEnvelope]:
        if self._outbox is None or not self._outbox.is_file():
            return []
        text = self._outbox.read_text(encoding="utf-8")
        return [
            IngestEnvelope.model_validate_json(line)
            for line in text.splitlines()
            if line.strip()
        ]

    def _write_outbox(self, envelopes: list[IngestEnvelope]) -> None:
        """Rewrite the outbox JSONL to exactly ``envelopes`` (the undrained tail).

        Only ever called when ``self._outbox`` is a real path (callers guard on
        ``None``). An empty list truncates the file to a clean (empty) queue.
        """
        assert self._outbox is not None  # noqa: S101 — callers guard on None
        self._outbox.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(e.model_dump_json() + "\n" for e in envelopes)
        self._outbox.write_text(body, encoding="utf-8")

    def _enqueue(self, envelope: IngestEnvelope) -> None:
        if self._outbox is None:
            return  # no queue configured: best-effort, the record is dropped
        self._write_outbox([*self._read_outbox(), envelope])

    def _drain(self, client: _PostClient) -> bool:
        """Send queued envelopes oldest-first; True iff the outbox emptied.

        Stops on the FIRST failure and rewrites the failed envelope plus all
        remaining ones back to the outbox, preserving order. A single attempt per
        queued envelope here (the per-record retry budget is for the live send);
        the next ``emit`` retries the backlog.
        """
        queued = self._read_outbox()
        if not queued:
            return True
        for i, env in enumerate(queued):
            try:
                client.post(
                    self._url,
                    data=env.model_dump_json().encode("utf-8"),
                    headers=self._headers(),
                )
            except Exception:  # noqa: BLE001 — transport down: re-queue the rest (K4)
                self._write_outbox(queued[i:])
                return False
        self._write_outbox([])  # all sent: truncate to an empty queue
        return True


def make_sink(cfg: CentralConfig) -> Sink:
    """Resolve a central config to a sink; raise on a missing required field (K8)."""
    if cfg.sink == "none":
        return NullSink()
    if cfg.sink == "file":
        if not cfg.path:
            raise SchemaError("central sink 'file' requires a 'path'")
        return FileSink(Path(cfg.path))
    if cfg.sink == "http":
        if not cfg.url:
            raise SchemaError("central sink 'http' requires a 'url'")
        if not cfg.repo_id:
            raise SchemaError(
                "central sink 'http' requires a 'repo_id' (which repo a record "
                "came from) — set central.repo_id in the config"
            )
        # Commit precedence: explicit config wins, else the CI-injected SHA.
        commit = cfg.repo_commit or os.environ.get("CI_COMMIT_SHA")
        repo = RepoIdentity(
            repo_id=cfg.repo_id,
            repo_name=cfg.repo_name,
            repo_url=cfg.repo_url,
            commit=commit,
        )
        outbox = Path(cfg.outbox) if cfg.outbox else Path(".cdmon") / "outbox.jsonl"
        return HttpSink(
            cfg.url,
            cfg.auth_env,
            repo=repo,
            outbox=outbox,
            max_retries=cfg.max_retries,
        )
    raise SchemaError(f"unknown central sink kind {cfg.sink!r}")  # pragma: no cover
