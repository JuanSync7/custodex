"""The ``cdx`` the executed-CI harness puts on a job's PATH (S1-CITPL CI-HARNESS).

A CI template calls ``cdx`` (or ``.venv/bin/cdx``). In the harness that name is a
tiny ``/bin/sh`` wrapper that runs :func:`main` here with this checkout's Python,
so the REAL ``custodex.cli`` runs — with exactly these seams bound:

* **forge** — the provider transports' HTTP leaves (``pr._Urllib*Http.request``)
  go to :class:`tests._fake_forge.FakeForge` on ``$CDX_FAKE_FORGE_STATE``. A job
  run without a forge state that reaches a provider call fails loudly ("has no
  fake forge"), never silently.
* **central** — the register/sync leaf and the ingest sink leaf append JSONL to
  ``$CDX_FAKE_CENTRAL_LOG`` (``{kind, method, url, body, authorized}``; the token
  itself is never written). The sink swallows a leaf failure into its outbox, so
  this recorder must ALWAYS be bound — an unset log path is an AssertionError.
* **tripwires** — every other way out is an ``AssertionError`` carrying
  :data:`TRIPWIRE_MARK`: ``urllib.request.urlopen``, ``spmirror._urlopen``,
  ``socket`` connects to AF_INET/AF_INET6 (AF_UNIX stays usable), name lookups
  other than localhost, and the headless-LLM process runner (``backends`` and its
  ``agent.runtime`` alias).
* **clock** — ``$CDX_FAKE_NOW`` pins ``monitor._default_now`` (and ``cli._now`` /
  ``config._now``) so record timestamps are reproducible (K10).
* **write seam** — ``monitor.apply_fix`` is wrapped: ``$CDX_FAKE_DECLINE_WRITE``
  (``*``, or a comma list of repo-relative doc paths) makes the write boundary
  decline; ``$CDX_FAKE_NONDET_SALT`` appends one salted line to a doc ONLY after
  the real write changed bytes (a stand-in for a nondeterministic backend).
* **origin** — before and after the CLI runs, every ``custodex`` module must come
  from this checkout (a stale installed copy would make the test meaningless).
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

TRIPWIRE_MARK = "executed-CI shim tripwire"

ENV_FORGE_STATE = "CDX_FAKE_FORGE_STATE"
ENV_HTTP_LOG = "CDX_FAKE_HTTP_LOG"
ENV_CENTRAL_LOG = "CDX_FAKE_CENTRAL_LOG"
ENV_NOW = "CDX_FAKE_NOW"
ENV_DECLINE = "CDX_FAKE_DECLINE_WRITE"
ENV_SALT = "CDX_FAKE_NONDET_SALT"

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

__all__ = [
    "ENV_CENTRAL_LOG",
    "ENV_DECLINE",
    "ENV_FORGE_STATE",
    "ENV_HTTP_LOG",
    "ENV_NOW",
    "ENV_SALT",
    "TRIPWIRE_MARK",
    "assert_custodex_origin",
    "declined",
    "install",
    "installed",
    "main",
    "salt_line",
]


def _trip(what: str) -> AssertionError:
    """The tripwire error; also written to stderr as ONE unwrapped line.

    The stderr line is what an executed job is checked against: a rich
    traceback wraps long messages, and a product ``except Exception`` could
    swallow the AssertionError itself — the line survives both.
    """
    line = f"{TRIPWIRE_MARK}: {what}"
    print(line, file=sys.stderr, flush=True)
    return AssertionError(
        f"{line} — an unpatched network/LLM call reached the "
        "executed-CI harness (bind it to a fake, or the test is not offline)"
    )


def salt_line(salt: str) -> str:
    """The line ``CDX_FAKE_NONDET_SALT`` appends after a real write."""
    return f"\nNondeterministic backend prose ({salt}).\n"


def declined(doc_path: Path, spec: str) -> bool:
    """True iff ``doc_path`` is named by a ``CDX_FAKE_DECLINE_WRITE`` spec.

    ``*`` declines every write. Otherwise each comma-separated item is a
    repo-relative POSIX path: a relative ``doc_path`` must equal it, an absolute
    one must end with ``/<item>`` (the CLI passes absolute paths when the config
    path was absolute).
    """
    items = [x.strip() for x in spec.split(",") if x.strip()]
    posix = PurePosixPath(doc_path.as_posix())
    text = str(posix)
    for item in items:
        if item == "*":
            return True
        want = str(PurePosixPath(item))
        if posix.is_absolute():
            if text.endswith("/" + want):
                return True
        elif text == want:
            return True
    return False


def assert_custodex_origin(modules: Mapping[str, Any] | None = None) -> None:
    """Every loaded ``custodex`` module must live under this checkout."""
    mods = sys.modules if modules is None else modules
    root = str(REPO_ROOT) + os.sep
    bad = []
    for name, mod in sorted(mods.items()):
        if name != "custodex" and not name.startswith("custodex."):
            continue
        origin = getattr(mod, "__file__", None)
        if origin is None:
            continue  # namespace packages carry no file
        if not os.path.realpath(origin).startswith(
            os.path.realpath(root[:-1]) + os.sep
        ):
            bad.append(f"{name} -> {origin}")
    if "custodex" in mods and getattr(mods["custodex"], "__file__", None) is None:
        bad.append("custodex -> <no __file__>")
    if bad:
        raise AssertionError(
            f"custodex imported from outside {REPO_ROOT}: " + "; ".join(bad)
        )


def _append_jsonl(path_env: str, env: Mapping[str, str], entry: dict) -> None:
    path = env.get(path_env)
    if not path:
        raise AssertionError(
            f"executed-CI shim: central traffic but ${path_env} is unset — the "
            "harness must always bind the central recorder"
        )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def install(env: Mapping[str, str]) -> Callable[[], None]:
    """Bind every seam described in the module docstring; return a restore()."""
    from custodex import backends, cli, config, monitor, pr, registry, sinks, spmirror
    from tests._fake_forge import FakeForge

    saved: list[tuple[object, str, object]] = []

    def patch(owner: object, name: str, value: object) -> None:
        saved.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    # --- forge ---------------------------------------------------------------
    def forge_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> Any:
        state = env.get(ENV_FORGE_STATE)
        if not state:
            raise AssertionError(
                f"executed-CI shim: provider call {method} {url} but the job has no "
                f"fake forge (${ENV_FORGE_STATE} unset — pass forge_state=)"
            )
        log = env.get(ENV_HTTP_LOG)
        forge = FakeForge(Path(state), log_path=Path(log) if log else None)
        return forge.request(method, url, body=body, token=token)

    patch(pr._UrllibGitLabHttp, "request", forge_request)
    patch(pr._UrllibGitHubHttp, "request", forge_request)

    # --- central -------------------------------------------------------------
    def register_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        kind = "sync" if url.rstrip("/").endswith("/sync") else "register"
        _append_jsonl(
            ENV_CENTRAL_LOG,
            env,
            {
                "kind": kind,
                "method": method,
                "url": url,
                "body": body,
                "authorized": bool(token),
            },
        )
        return {}

    def sink_post(
        self: object, url: str, *, data: bytes, headers: dict[str, str]
    ) -> None:
        _append_jsonl(
            ENV_CENTRAL_LOG,
            env,
            {
                "kind": "ingest",
                "method": "POST",
                "url": url,
                "body": json.loads(data.decode("utf-8")),
                "authorized": "Authorization" in headers,
            },
        )

    patch(registry._UrllibRegisterHttp, "request", register_request)
    patch(sinks._UrllibClient, "post", sink_post)

    # --- tripwires -----------------------------------------------------------
    def no_urlopen(*args: object, **kwargs: object) -> object:
        target = args[0] if args else kwargs.get("url")
        url = getattr(target, "full_url", target)
        raise _trip(f"urllib.request.urlopen({url!r})")

    patch(urllib.request, "urlopen", no_urlopen)
    patch(spmirror, "_urlopen", no_urlopen)

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise _trip(f"socket.connect({address!r})")
        real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise _trip(f"socket.connect_ex({address!r})")
        return real_connect_ex(self, address)

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else host
        if name not in _LOCAL_HOSTS:
            raise _trip(f"socket.getaddrinfo({host!r})")
        return real_getaddrinfo(host, *args, **kwargs)

    patch(socket.socket, "connect", guarded_connect)
    patch(socket.socket, "connect_ex", guarded_connect_ex)
    patch(socket, "getaddrinfo", guarded_getaddrinfo)

    def no_llm(argv: list[str], stdin: str, timeout_s: int) -> str:
        raise _trip(f"LLM process runner {argv[:1]!r}")

    patch(backends, "_default_process_runner", no_llm)
    runtime = sys.modules.get("custodex.agent.runtime")
    if runtime is not None:
        patch(runtime, "_default_process_runner", no_llm)

    # --- clock ---------------------------------------------------------------
    now = env.get(ENV_NOW)
    if now:

        def fixed_now() -> str:
            return now

        patch(monitor, "_default_now", fixed_now)
        patch(cli, "_now", fixed_now)
        patch(config, "_now", fixed_now)

    # --- write seam ----------------------------------------------------------
    real_apply_fix = monitor.apply_fix
    decline_spec = env.get(ENV_DECLINE, "")
    salt = env.get(ENV_SALT, "")

    def seam_apply_fix(doc_path: Path, fix: Any, **kwargs: Any) -> bool:
        if decline_spec and declined(Path(doc_path), decline_spec):
            return False
        changed: bool = real_apply_fix(doc_path, fix, **kwargs)
        if changed and salt:
            with open(doc_path, "a", encoding="utf-8") as fh:
                fh.write(salt_line(salt))
        return changed

    patch(monitor, "apply_fix", seam_apply_fix)

    def restore() -> None:
        for owner, name, value in reversed(saved):
            setattr(owner, name, value)
        saved.clear()

    return restore


@contextmanager
def installed(env: Mapping[str, str]) -> Iterator[None]:
    """``install(env)`` for the duration of a ``with`` block."""
    restore = install(env)
    try:
        yield
    finally:
        restore()


def main(argv: list[str] | None = None) -> int:
    """Run the real ``cdx`` CLI with every seam bound; return its exit code."""
    args = sys.argv[1:] if argv is None else argv
    prog = (
        Path(sys.argv[0]).name if sys.argv and sys.argv[0] not in ("", "-c") else "cdx"
    )
    assert_custodex_origin()
    install(os.environ)
    from custodex.cli import app

    assert_custodex_origin()
    code: int
    try:
        app(args=args, prog_name=prog, standalone_mode=True)
        code = 0
    except SystemExit as exc:
        if exc.code is None:
            code = 0
        elif isinstance(exc.code, int):
            code = exc.code
        else:
            print(exc.code, file=sys.stderr)
            code = 1
    assert_custodex_origin()
    return code
