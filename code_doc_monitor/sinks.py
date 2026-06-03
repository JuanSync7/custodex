"""Central-system sinks — offline by default (K0, K4).

A sink emits a :class:`ReviewRecord` to "the central monitoring system". The
default is :class:`NullSink` (does nothing) and :class:`FileSink` is an offline
stand-in (append JSON to a file) — both run in CI with zero network (K4).
:class:`HttpSink` POSTs to a URL, but its HTTP client is *injected* so tests
exercise it with a fake and never touch the network (K4); when no client is
injected it lazily builds one from the standard library only (no ``requests``,
K0). :func:`make_sink` resolves a :class:`CentralConfig` to one of these.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from .config import CentralConfig
from .errors import SchemaError
from .schema import ReviewRecord

__all__ = ["Sink", "NullSink", "FileSink", "HttpSink", "make_sink"]


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

    def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None:
        import urllib.request

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req):  # noqa: S310 (url comes from trusted config)
            pass


class HttpSink:
    """POST each record's JSON to ``url`` with an optional bearer token (K4).

    The HTTP ``client`` is injected (any object with a ``post(url, *, data,
    headers)`` method) so tests never hit the network. If ``client is None`` at
    emit time a stdlib-only :class:`_UrllibClient` is built lazily (K0). The
    bearer token, when ``auth_env`` is set and present in the environment, is
    read at emit time so a rotated token is picked up without rebuilding.
    """

    def __init__(
        self,
        url: str,
        auth_env: str | None = None,
        *,
        client: _PostClient | None = None,
    ) -> None:
        self._url = url
        self._auth_env = auth_env
        self._client = client

    def emit(self, record: ReviewRecord) -> None:
        client = self._client
        if client is None:
            client = self._client = _UrllibClient()
        headers = {"Content-Type": "application/json"}
        if self._auth_env:
            token = os.environ.get(self._auth_env)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        client.post(
            self._url,
            data=record.model_dump_json().encode("utf-8"),
            headers=headers,
        )


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
        return HttpSink(cfg.url, cfg.auth_env)
    raise SchemaError(f"unknown central sink kind {cfg.sink!r}")  # pragma: no cover
