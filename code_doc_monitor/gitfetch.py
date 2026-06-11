"""Clone-on-demand — sync a repo the server does NOT hold locally (GIT-00, STEP 0).

The central server's :func:`code_doc_monitor.configsync.run_sync` only reads a
repo that is already on disk. :func:`cloned_repo` closes that gap: it materializes
a remote repo into a throwaway temp tree, yields the tree, and tears it down on
the way out — so the caller does ``run_sync(tree, mode="local", ...)`` over the
clone with the engine UNCHANGED (K9: ``configsync.py`` is not touched).

Design (verified against ``configsync._open_repo``): ``run_sync`` checks
``local_path.is_dir()`` and runs ``git rev-parse HEAD`` BEFORE any injected runner
fires, so a "lazy clone on first git call" runner would have to forge a sentinel
path. Instead we clone FULLY up front (a normal shallow ``git clone`` of the
default branch, which is exactly the working tree drift/coverage need) and hand
``run_sync`` a real checked-out repo with the default runner. Simpler, less
coupled, and zero engine change.

Security + safety:

* **The token never enters argv or the URL.** A secret is supplied to git only
  through an ephemeral ``GIT_ASKPASS`` helper (read from an env var); the clone
  URL carries at most the provider *username* (``x-access-token`` / ``oauth2``),
  never the token (asserted by :func:`_build_clone_argv`'s unit tests).
* **K1** — the clone lands ONLY in a ``tempfile.mkdtemp`` dir, never the caller's
  tree; teardown (``rmtree``) runs in a ``finally`` on success AND error.
* **K4** — the real ``git`` subprocess is behind the injected :class:`_Cloner`
  leaf; tests drive a fake OR a real ``file://`` clone (no network).
* **K8** — a clone failure is a loud :class:`~code_doc_monitor.errors.SyncError`
  with the secret SCRUBBED from git's stderr.
* **K0** — stdlib only (``subprocess``/``tempfile``/``shutil``/``os``); no new dep.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .errors import SyncError

__all__ = ["RemoteSpec", "cloned_repo"]

# Frozen + extra="forbid": a remote spec is an immutable description of one fetch.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

# The provider's git-over-https USERNAME (never the token — the token goes to
# GIT_ASKPASS). GitHub accepts any non-empty user with a token as the password;
# the conventional sentinels are these.
_PROVIDER_USERS: dict[str, str] = {"github": "x-access-token", "gitlab": "oauth2"}


class RemoteSpec(BaseModel):
    """Where + how to fetch a repo the server does not hold locally (STEP 0).

    ``remote_url`` is the CLONE/API url (``https://github.com/owner/repo(.git)``
    or, in tests, a ``file://`` path — exercised with no network). ``provider``
    selects the https username convention; ``default_branch`` is the single
    branch cloned (the central baseline the sync reads).
    """

    model_config = _MODEL_CONFIG

    remote_url: str
    provider: Literal["github", "gitlab"]
    default_branch: str = "main"


class _Cloner(Protocol):
    """The ONE network leaf (K4): clone ``spec`` into ``dest`` using ``secret``.

    Implementations MUST NOT put ``secret`` in the process argv or the clone URL.
    Tests inject a fake; production uses :class:`_GitCloner`.
    """

    def clone(self, spec: RemoteSpec, secret: str | None, dest: Path) -> None: ...


def _clone_url(spec: RemoteSpec, secret: str | None) -> str:
    """The clone URL with the provider USERNAME injected (never the token).

    Only ``https://`` URLs get a userinfo (``https://<user>@host/...``); the token
    itself travels via ``GIT_ASKPASS``. A tokenless fetch, or any non-https URL
    (``file://`` in tests), is returned verbatim.
    """
    if secret is None or not spec.remote_url.startswith("https://"):
        return spec.remote_url
    user = _PROVIDER_USERS[spec.provider]
    rest = spec.remote_url[len("https://") :]
    return f"https://{user}@{rest}"


def _build_clone_argv(spec: RemoteSpec, dest: Path, *, secret: str | None) -> list[str]:
    """The exact ``git`` argv for a shallow single-branch clone (token-free).

    Pure + secret-free by construction (the token is never an argv element — only
    the provider username may appear in the URL); the security guarantee is
    unit-asserted directly on this function.
    """
    return [
        "clone",
        "--depth=1",
        "--single-branch",
        "--branch",
        spec.default_branch,
        _clone_url(spec, secret),
        str(dest),
    ]


def _scrub(text: str, secret: str | None) -> str:
    """Redact ``secret`` from ``text`` (defensive: it should never appear there)."""
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


class _GitCloner:
    """The real clone leaf — ``git clone`` via stdlib ``subprocess`` (K0/K4/K8).

    The token is handed to git ONLY through an ephemeral ``GIT_ASKPASS`` helper
    (it reads ``$CDMON_GIT_TOKEN`` from the child env — never argv, never the URL)
    written into a private temp dir that is removed in a ``finally``. A non-zero
    exit is a loud :class:`SyncError` with the secret scrubbed from stderr.
    """

    def clone(self, spec: RemoteSpec, secret: str | None, dest: Path) -> None:
        argv = ["git", *_build_clone_argv(spec, dest, secret=secret)]
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        askpass_dir: str | None = None
        try:
            if secret is not None:
                askpass_dir = tempfile.mkdtemp(prefix="cdmon-askpass-")
                script = Path(askpass_dir) / "askpass.sh"
                script.write_text(
                    '#!/bin/sh\nexec printf "%s" "$CDMON_GIT_TOKEN"\n', encoding="utf-8"
                )
                script.chmod(0o700)
                env["GIT_ASKPASS"] = str(script)
                env["CDMON_GIT_TOKEN"] = secret
            result = subprocess.run(  # noqa: S603 (argv is fixed git verbs, no shell)
                argv, capture_output=True, text=True, env=env
            )
            if result.returncode != 0:
                raise SyncError(
                    f"git clone failed (exit {result.returncode}): "
                    f"{_scrub(result.stderr.strip(), secret)}"
                )
        finally:
            if askpass_dir is not None:
                shutil.rmtree(askpass_dir, ignore_errors=True)


@contextmanager
def cloned_repo(
    spec: RemoteSpec, secret: str | None, *, cloner: _Cloner | None = None
) -> Iterator[Path]:
    """Clone ``spec`` into a throwaway temp tree and yield it; tear it down after.

    The yielded path is a freshly checked-out clone of ``spec.default_branch`` — a
    real git working tree the caller drives :func:`run_sync` over in ``local``
    mode. On exit (success OR exception) the entire temp dir is removed (K1), so
    the server's own filesystem is never left holding a clone. ``cloner`` is the
    injected network leaf (K4); production builds a :class:`_GitCloner`.
    """
    active: _Cloner = cloner if cloner is not None else _GitCloner()
    tmp = Path(tempfile.mkdtemp(prefix="cdmon-fetch-"))
    dest = tmp / "repo"
    try:
        active.clone(spec, secret, dest)
        yield dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
