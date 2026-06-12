"""A small, reusable real-git-repo builder for the test suite (GIT-06).

The EPIC-GIT tests prove the server clones + syncs + docs-PRs a repo it does NOT
hold locally. To exercise that path with NO network (EDR-safe) the tests stand
up a REAL ``git`` repo on disk and hand the server a ``file://`` URL — the
production ``_GitCloner`` then runs a genuine ``git clone`` of it.

Before this helper, every git test re-implemented its own ``_git`` runner and
single-commit ``_build_repo``/``_demo_origin`` (see ``tests/integration/
test_server_gitsync.py`` and ``tests/system/test_demo_gitsync_e2e.py``). This
module consolidates that into one builder that any test (or the
``scripts/demo_as_git.py`` launcher) can drive over ANY tree, and adds what the
ad-hoc helpers lacked: AUTHENTIC multi-commit history, feature branches, and a
bare origin — so a synced repo looks like a real project, not a single squash.

Design notes:

* **Real git, no network (K4).** Everything is local ``git`` over the filesystem;
  :func:`file_url` yields the ``file://`` origin the server clones. The real
  clone leaf (``code_doc_monitor.gitfetch._GitCloner``) is exercised end to end.
* **Deterministic (K10).** Commits are stamped with a FIXED author/committer
  date (:data:`_FIXED_DATE`) via ``GIT_*_DATE`` env, and identity is pinned, so a
  repo built from the same tree + history is byte-stable run to run — no wall
  clock leaks in (mirrors the suite's injected-clock discipline).
* **Stdlib only (K0).** ``subprocess`` + ``shutil``; no new dependency.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "GitRepo",
    "HistoryStep",
    "bare_origin",
    "file_url",
    "init_repo",
    "repo_from_tree",
]

# A fixed commit timestamp so a repo built from the same inputs is reproducible
# (K10). Kept well in the past so "commits-ahead" math is never ambiguous.
_FIXED_DATE = "2026-01-02T03:04:05 +0000"

# A history step: a commit message + the pathspecs to stage for it (relative to
# the repo root). ``git add`` interprets a directory or glob pathspec, so e.g.
# ``("src/**", "pyproject.toml")`` stages a package and its manifest in one
# commit. Anything left unstaged after the last step is swept into a final
# catch-all commit by :func:`repo_from_tree`, so no file is ever dropped.
HistoryStep = tuple[str, Sequence[str]]


@dataclass
class GitRepo:
    """A real on-disk git repo the tests drive (a thin, typed ``git`` façade).

    Holds the working-tree ``path`` and the ``default_branch`` name. Every method
    shells out to the real ``git`` (K4); a non-zero exit raises
    :class:`subprocess.CalledProcessError` with git's captured output, so a
    failing setup is loud, not silently swallowed.
    """

    path: Path
    default_branch: str = "main"

    # --- the one subprocess leaf -------------------------------------------- #

    def git(self, *args: str) -> str:
        """Run ``git <args>`` in this repo and return stdout (deterministic env).

        Identity + commit dates are pinned via the child env so commits are
        reproducible (K10) and never depend on the caller's global git config.
        """
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "cdmon-demo",
            "GIT_AUTHOR_EMAIL": "demo@cdmon.test",
            "GIT_COMMITTER_NAME": "cdmon-demo",
            "GIT_COMMITTER_EMAIL": "demo@cdmon.test",
            "GIT_AUTHOR_DATE": _FIXED_DATE,
            "GIT_COMMITTER_DATE": _FIXED_DATE,
        }
        result = subprocess.run(  # noqa: S603 (fixed git verbs, no shell)
            ["git", *args],
            cwd=str(self.path),
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        return result.stdout

    # --- working-tree mutation ---------------------------------------------- #

    def write(self, relpath: str, content: str) -> Path:
        """Write ``content`` to ``relpath`` (creating parents); return the path."""
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def add(self, *pathspecs: str) -> None:
        """Stage ``pathspecs`` (default ``-A`` — everything)."""
        self.git("add", *(pathspecs or ("-A",)))

    def _has_staged(self) -> bool:
        """True iff the index holds changes to commit (``git diff --cached``)."""
        return (
            subprocess.run(  # noqa: S603 (fixed git verbs, no shell)
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(self.path),
            ).returncode
            != 0
        )

    def commit(self, message: str, *, allow_empty: bool = False) -> str:
        """Commit the staged index with ``message``; return the new HEAD sha."""
        args = ["commit", "-q", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        self.git(*args)
        return self.head()

    def commit_files(self, message: str, files: Mapping[str, str]) -> str:
        """Write ``files`` (relpath → content), stage them, and commit (one step)."""
        for relpath, content in files.items():
            self.write(relpath, content)
            self.add(relpath)
        return self.commit(message)

    # --- branches ----------------------------------------------------------- #

    def checkout_new_branch(self, name: str) -> None:
        """Create and switch to a new branch ``name``."""
        self.git("checkout", "-q", "-b", name)

    def checkout(self, ref: str) -> None:
        """Switch to an existing ``ref`` (branch or commit)."""
        self.git("checkout", "-q", ref)

    # --- reads -------------------------------------------------------------- #

    def head(self) -> str:
        """The current HEAD commit sha."""
        return self.git("rev-parse", "HEAD").strip()

    def current_branch(self) -> str:
        """The current branch name (``HEAD`` when detached)."""
        return self.git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def commit_count(self, rev: str = "HEAD") -> int:
        """How many commits are reachable from ``rev`` (history depth)."""
        return int(self.git("rev-list", "--count", rev).strip())

    def commits_ahead(self, ref: str, base: str | None = None) -> int:
        """Commits ``ref`` is ahead of ``base`` (default: the default branch)."""
        base = base or self.default_branch
        return int(self.git("rev-list", "--count", f"{base}..{ref}").strip())


def file_url(repo: GitRepo | Path) -> str:
    """The ``file://`` clone URL for ``repo`` (what the server is handed, K4)."""
    path = repo.path if isinstance(repo, GitRepo) else repo
    return f"file://{path}"


def init_repo(path: Path, *, default_branch: str = "main") -> GitRepo:
    """``git init`` an empty repo at ``path`` on ``default_branch`` (no commits yet)."""
    path.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(path=path, default_branch=default_branch)
    repo.git("init", "-q")
    # Pin the branch name regardless of the host's init.defaultBranch.
    repo.git("symbolic-ref", "HEAD", f"refs/heads/{default_branch}")
    return repo


def _copy_tree(src: Path, dest: Path) -> None:
    """Copy ``src`` into a fresh ``dest``, never carrying a nested ``.git`` over."""
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))


def repo_from_tree(
    src_tree: Path,
    dest: Path,
    *,
    history: Sequence[HistoryStep] | None = None,
    default_branch: str = "main",
) -> GitRepo:
    """Materialize ``src_tree`` into a REAL git repo at ``dest`` and return it.

    The whole tree is copied (minus any stray ``.git``), then committed:

    * ``history`` ``None`` — one ``import`` commit of the entire tree (the simple
      single-snapshot origin the older tests used).
    * ``history`` given — each :data:`HistoryStep` stages its pathspecs and makes
      one commit, building an AUTHENTIC multi-commit history; whatever is left
      unstaged after the final step is swept into one catch-all commit, so the
      working tree is always fully committed and clean regardless of the step
      list. The end state on ``default_branch`` is byte-identical to ``src_tree``.

    The repo is left checked out on ``default_branch`` with a clean working tree,
    ready to be handed to the server as a ``file://`` origin (:func:`file_url`).
    """
    _copy_tree(src_tree, dest)
    repo = init_repo(dest, default_branch=default_branch)

    if history is None:
        repo.add("-A")
        repo.commit("import project")
        return repo

    for message, pathspecs in history:
        # Stage only the paths that exist (a step may name optional files).
        existing = [p for p in pathspecs if (dest / p).exists()]
        if existing:
            repo.add(*existing)
        if repo._has_staged():
            repo.commit(message)
    # Catch-all: commit anything the history steps did not cover, so the final
    # tree always matches src_tree exactly (no file silently dropped).
    repo.add("-A")
    if repo._has_staged():
        repo.commit("chore: add remaining project files")
    return repo


def bare_origin(repo: GitRepo, dest: Path) -> Path:
    """Clone ``repo`` into a BARE repo at ``dest`` and return it (a push target).

    A bare clone is what a real hosting provider holds — it has no working tree,
    so it is the right shape for a docs-PR target. Returned as a plain ``Path``
    (a bare repo has no working tree for a :class:`GitRepo` to operate on).
    """
    subprocess.run(  # noqa: S603 (fixed git verbs, no shell)
        ["git", "clone", "-q", "--bare", str(repo.path), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest
