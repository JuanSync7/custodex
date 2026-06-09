"""The per-repo STANDALONE app — ``cdmon serve`` (L-01, no central access).

A user runs this inside THEIR own repo and gets the SAME Documents /
relationship / Sync dashboard the central server shows — scoped to ONLY that one
repo, with no registration, no token, and no network (CONFIG-V2 §5).

The mechanism mirrors :mod:`scripts.seed_demo`:

* :func:`build_standalone_store` builds an :class:`InMemoryStore` in which ONLY
  the current repo is auto-registered (``local_path = <repo-root>``,
  ``default_branch = "main"``, registered OPEN — NO ``auth_token`` — so its
  writes/sync need no bearer token). It then runs
  :func:`code_doc_monitor.configsync.run_sync` for BOTH modes (local always; git
  best-effort — a brand-new repo with no ``main``/commits skips git gracefully)
  and persists the rows via ``replace_config`` + ``add_sync_run``, so the
  Documents relationship view + sync-state are populated on FIRST load. It is
  IMPORT-SAFE (no server launch, no socket) like
  :func:`scripts.seed_demo.build_seeded_store`, so a test drives it directly.
* :func:`build_standalone_app` wraps that store in :func:`create_app` and mounts
  the built dashboard SPA via the SAME locator the central launch + seed_demo use
  (:func:`code_doc_monitor.server.app._default_static_dir`) — the static-serving
  logic is NOT duplicated, just reused.

The clock is injected (``now``) so every persisted ``synced_at`` / ``started_at``
/ ``finished_at`` is deterministic (K10). Reading the repo is READ-ONLY (K1 — the
git mode uses configsync's read-only worktree path). All logic lives here in the
import-safe builders; the ``cdmon serve`` CLI keeps the uvicorn launch thin so
tests never bind a socket.
"""

from __future__ import annotations

from pathlib import Path

from ..configsync import run_sync
from ..errors import CodeDocMonitorError
from ..registry import RegistrationPayload
from ..sinks import RepoIdentity
from .store import InMemoryStore

__all__ = ["build_standalone_store", "build_standalone_app", "resolve_repo_id"]

# Where a repo's dir-layout config lives, relative to the repo root (CONFIG-V2 §1).
_CONFIG_SUBDIR = ("config", "cdmon")

# The two syncs a standalone view pre-populates: local always works (the working
# tree); git is best-effort (a repo with no `main`/commits is skipped gracefully).
_DEFAULT_BRANCH = "main"


def resolve_repo_id(repo_root: Path, repo_id: str | None) -> str:
    """Resolve the repo id: an explicit ``repo_id`` wins, else the bundle index
    ``repo`` field, else the directory name (never invented).

    Reads the ``config/cdmon/index.yaml`` ``repo`` frontmatter when present (the
    same field ``cdmon sync`` defaults from), falling back to the repo directory
    name. A malformed/absent bundle never raises here — the dir name is the safe
    default so the launch is robust (K8 surfaces config errors during the sync).
    """
    if repo_id:
        return repo_id
    config_dir = repo_root.joinpath(*_CONFIG_SUBDIR)
    if (config_dir / "index.yaml").is_file():
        try:
            from ..config import load_bundle

            return load_bundle(config_dir).index.frontmatter.repo
        except CodeDocMonitorError:
            # A malformed index still launches under the dir name; the sync that
            # follows surfaces the real config error loudly (K8).
            pass
    return repo_root.name


def build_standalone_store(
    repo_root: Path,
    *,
    repo_id: str | None = None,
    now: str,
) -> InMemoryStore:
    """Build an :class:`InMemoryStore` holding ONLY ``repo_root``, pre-synced (L-01).

    Registers the repo OPEN — a :class:`RegistrationPayload` whose
    :class:`RepoIdentity` carries ``local_path=str(repo_root)`` and
    ``default_branch="main"``, with NO ``auth_token`` so its sync/writes need no
    bearer token. Then runs :func:`run_sync` for BOTH modes and persists the rows
    (``replace_config`` + ``add_sync_run``) so the Documents relationship view +
    sync-state render on first load:

    * **local** — always run (the working tree); a config error is LOUD (K8).
    * **git** — best-effort: a brand-new repo with no ``main`` (or no commits)
      raises a :class:`~code_doc_monitor.errors.SyncError`, which is swallowed so
      the standalone view still launches with just the local view populated.

    Import-safe (no server launch, no socket) and deterministic (``now`` stamps
    every persisted row, K10), mirroring
    :func:`scripts.seed_demo.build_seeded_store`.
    """
    resolved_id = resolve_repo_id(repo_root, repo_id)
    store = InMemoryStore()
    store.add_repo(
        RegistrationPayload(
            repo=RepoIdentity(
                repo_id=resolved_id,
                repo_name=repo_root.name,
                local_path=str(repo_root),
                default_branch=_DEFAULT_BRANCH,
            ),
            description=f"Standalone per-repo view of {repo_root.name}",
            # NO auth_token: the standalone repo's writes/sync are OPEN.
        )
    )

    # local: the working tree — always populated. A config error is loud (K8): if
    # the repo has no readable config/cdmon/ there is nothing to serve, so let it
    # raise out of the builder.
    local = run_sync(
        repo_root,
        resolved_id,
        mode="local",
        default_branch=_DEFAULT_BRANCH,
        now=now,
    )
    store.replace_config(
        resolved_id, "local", list(local.documents), list(local.code_refs)
    )
    store.add_sync_run(local.run)

    # git: the default-branch baseline — best-effort. A repo with no `main`/commits
    # cannot materialize the read-only worktree, so skip it gracefully (the local
    # view alone still drives the dashboard).
    try:
        git = run_sync(
            repo_root,
            resolved_id,
            mode="git",
            default_branch=_DEFAULT_BRANCH,
            now=now,
        )
    except CodeDocMonitorError:
        return store
    store.replace_config(resolved_id, "git", list(git.documents), list(git.code_refs))
    store.add_sync_run(git.run)
    return store


def build_standalone_app(
    repo_root: Path,
    *,
    repo_id: str | None = None,
    now: str,
) -> object:
    """The FastAPI app over a freshly built standalone store, SPA mounted (L-01).

    Wraps :func:`build_standalone_store` in :func:`create_app` and mounts the
    built dashboard SPA via the SAME locator the central launch + ``seed_demo``
    use (:func:`code_doc_monitor.server.app._default_static_dir`) — so ``GET /``
    serves the console when ``dashboard/dist`` is built, and the friendly landing
    JSON otherwise. The static-serving logic is REUSED, never duplicated. ``now``
    is the injected clock for the pre-populated rows (K10).

    Returns ``object`` (not ``FastAPI``) so importing this module does not require
    the ``[server]`` extra until the app is actually built (K0); ``create_app`` is
    imported lazily for the same reason.
    """
    from .app import _default_static_dir, create_app

    store = build_standalone_store(repo_root, repo_id=repo_id, now=now)
    return create_app(store, static_dir=_default_static_dir())
