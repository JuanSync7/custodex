"""Materialize the ``demo/`` adopter repo as a REAL standalone git repo (GIT-06).

The EPIC-GIT server syncs + opens docs-PRs against a repo it does NOT hold
locally: it is handed a ``provider`` + ``remote_url`` and clones on demand. This
launcher turns the committed ``demo/`` tree into a genuine git repository you can
point the server at — completely OFFLINE (a local ``file://`` origin, no network,
EDR-safe; no ``curl``/``wget``).

Why a script and not just "git init demo/"? The demo lives in a SUBDIR of the
outer code-doc-monitor repo, so it cannot host its own ``.git`` without nesting a
repository inside another. Instead this exports a COPY of the tree to a target
directory and lays down an authentic, multi-commit history (the project's
plausible evolution, mirroring ``demo/CHANGELOG.md``) plus a BARE origin — the
shape a real hosting provider holds.

Run it (from anywhere)::

    python scripts/demo_as_git.py /tmp/demo-as-git
    #   /tmp/demo-as-git/origin.git   <- bare origin (the "remote")
    #   /tmp/demo-as-git/work         <- a working clone you can poke at

It then prints the exact, network-free Python snippet that registers the repo
with the central server (by its ``file://`` URL) and runs a clone-on-demand
``POST /sync`` over it via the in-process FastAPI ``TestClient``.

It is stdlib + ``code_doc_monitor`` only (K0) and DETERMINISTIC (K10: pinned git
identity + a fixed commit date), so the materialized repo is byte-stable. Import
:func:`materialize` to get the repo paths without the prints (the tests do).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

# This repo's root (two levels up from scripts/demo_as_git.py) and the demo tree.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_DIR = _REPO_ROOT / "demo"

# A fixed commit timestamp so the materialized history is reproducible (K10) —
# the same discipline as the suite's injected clocks; no wall clock leaks in.
_FIXED_DATE = "2026-01-02T03:04:05 +0000"

# The authentic project history: an ordered list of (commit message, pathspecs).
# Each step stages the paths that exist and makes one commit; anything not named
# is swept into a final catch-all commit, so the end state always matches the
# demo tree exactly. The arc mirrors demo/CHANGELOG.md — model, then engine, then
# io, then the scheduler helper, then tests, packaging/CI, and finally adopting
# code-doc-monitor (its config + docs + templates).
DEMO_HISTORY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("chore: project scaffolding", (".editorconfig", ".gitignore", "LICENSE")),
    ("feat: domain model — Status, Task, TaskGraph", ("src/taskflow/core/model.py",)),
    ("feat: scheduling engine (Kahn) + CycleError", ("src/taskflow/core/engine.py",)),
    ("feat: io adapters — JSON persistence + text report", ("src/taskflow/io",)),
    (
        # notes.log is intentionally omitted: it is *.log (gitignored) — a
        # working-tree-only artifact, never committed to the remote (faithful to
        # the canonical demo, which does not track it either).
        "feat: package exports + scheduler.priority_order",
        (
            "src/taskflow/__init__.py",
            "src/taskflow/core/__init__.py",
            "src/taskflow/io/__init__.py",
            "src/taskflow/core/scheduler.py",
        ),
    ),
    ("test: unit tests for model/engine/io/scheduler", ("tests",)),
    (
        "build: packaging, CI, contributing guide, changelog",
        ("pyproject.toml", ".github", "CONTRIBUTING.md", "CHANGELOG.md"),
    ),
    (
        "docs: adopt code-doc-monitor (config + docs + templates)",
        ("config", "docs", "templates", "README.md", "DEMOS.md", "walkthrough.py"),
    ),
)


def _git(repo: Path, *args: str) -> str:
    """Run ``git <args>`` in ``repo`` with a pinned, deterministic env (K10)."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "demo-team",
        "GIT_AUTHOR_EMAIL": "demo-team@example.com",
        "GIT_COMMITTER_NAME": "demo-team",
        "GIT_COMMITTER_EMAIL": "demo-team@example.com",
        "GIT_AUTHOR_DATE": _FIXED_DATE,
        "GIT_COMMITTER_DATE": _FIXED_DATE,
    }
    result = subprocess.run(  # noqa: S603 (fixed git verbs, no shell)
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout


def _has_staged(repo: Path) -> bool:
    """True iff the index holds changes to commit."""
    return (
        subprocess.run(  # noqa: S603 (fixed git verbs, no shell)
            ["git", "diff", "--cached", "--quiet"], cwd=str(repo)
        ).returncode
        != 0
    )


def _commit_history(
    work: Path, history: Sequence[tuple[str, Sequence[str]]], *, branch: str
) -> None:
    """Lay down ``history`` over the tree at ``work``, then sweep the remainder."""
    _git(work, "init", "-q")
    _git(work, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    for message, pathspecs in history:
        existing = [p for p in pathspecs if (work / p).exists()]
        if existing:
            _git(work, "add", *existing)
        if _has_staged(work):
            _git(work, "commit", "-q", "-m", message)
    _git(work, "add", "-A")
    if _has_staged(work):
        _git(work, "commit", "-q", "-m", "chore: add remaining project files")


def materialize(
    dest: Path,
    *,
    demo_dir: Path = _DEMO_DIR,
    branch: str = "main",
    history: Sequence[tuple[str, Sequence[str]]] | None = DEMO_HISTORY,
) -> Mapping[str, Path]:
    """Build the demo into a real git repo under ``dest``; return its paths.

    Produces ``dest/work`` — a checked-out clone with the authentic ``history``
    on ``branch`` (its working tree byte-identical to ``demo_dir``) — and
    ``dest/origin.git`` — a BARE origin (the "remote" the server clones). ``dest``
    is created fresh (an existing one is removed first) so the result is
    reproducible. Returns ``{"work": ..., "origin": ..., "file_url": ...}`` where
    ``file_url`` is the ``file://`` URL of the bare origin to register.
    """
    dest = dest.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    work = dest / "work"
    origin = dest / "origin.git"
    shutil.copytree(demo_dir, work, ignore=shutil.ignore_patterns(".git"))
    _commit_history(work, history or (), branch=branch)
    # A bare clone is the right shape for a remote (no working tree).
    subprocess.run(  # noqa: S603 (fixed git verbs, no shell)
        ["git", "clone", "-q", "--bare", str(work), str(origin)],
        check=True,
        capture_output=True,
        text=True,
    )
    return {"work": work, "origin": origin, "file_url": Path(f"file://{origin}")}


def _print_next_steps(paths: Mapping[str, Path], branch: str) -> None:
    """Print the offline, network-free sync recipe over the materialized origin."""
    origin = paths["origin"]
    n_commits = _git(paths["work"], "rev-list", "--count", "HEAD").strip()
    print(f"\nMaterialized the demo as a real git repo ({n_commits} commits):")
    print(f"  bare origin : {origin}")
    print(f"  work clone  : {paths['work']}")
    print(f"  file:// URL : file://{origin}")
    print(
        "\nSync it via the central server — clone-on-demand, fully offline "
        "(no network, no curl):\n"
    )
    snippet = f'''\
python - <<'PY'
from code_doc_monitor.server import InMemoryStore, create_app
from code_doc_monitor.registry import RegistrationPayload
from code_doc_monitor.sinks import RepoIdentity
from fastapi.testclient import TestClient

client = TestClient(create_app(InMemoryStore(), clock=lambda: "2026-06-11T00:00:00Z"))
payload = RegistrationPayload(
    repo=RepoIdentity(
        repo_id="demo-taskflow",
        provider="github",
        remote_url="file://{origin}",   # a repo the server does NOT hold locally
        default_branch="{branch}",
    ),
    default_branch="{branch}",
)
assert client.post("/repos", json=payload.model_dump(mode="json")).status_code == 201
run = client.post("/repos/demo-taskflow/sync", json={{"mode": "local"}}).json()
print("synced:", run["document_count"], "docs,", run["code_ref_count"], "code refs")
cov = client.get("/repos/demo-taskflow/coverage").json()[-1]
print("coverage:", cov["percent_files"], "% files documented")
PY'''
    print(snippet)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: ``demo_as_git.py [DEST] [--branch NAME]`` → materialize + print."""
    args = list(sys.argv[1:] if argv is None else argv)
    branch = "main"
    if "--branch" in args:
        i = args.index("--branch")
        branch = args[i + 1]
        del args[i : i + 2]
    dest = Path(args[0]) if args else _REPO_ROOT / "build" / "demo-as-git"
    paths = materialize(dest, branch=branch, history=DEMO_HISTORY)
    _print_next_steps(paths, branch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
