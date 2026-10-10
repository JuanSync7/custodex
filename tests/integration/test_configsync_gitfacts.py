"""X-GITFACTS — config sync reads git through the forge probe (S1-CITPL D6).

``configsync._git_info`` / ``_open_repo`` delegate the "where am I in git?"
question to :func:`custodex.forge.git_facts`, so config sync inherits its
rules: a missing git binary is a typed :class:`SyncError` (not a raw
``FileNotFoundError`` traceback), every git call runs under ``LC_ALL=C``, a
config that lives in a different (nested / submodule) work tree is refused
loudly instead of silently read, and a non-git ``local_path`` fails on the gate
before any HEAD probe. Each case drives a REAL temp git repo through
:func:`custodex.configsync.run_sync`.

Features: FEAT-PR-012, FEAT-PR-013
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path

import pytest

from custodex.configsync import _default_run_git, run_sync
from custodex.errors import SyncError
from tests.integration.test_configsync import (
    _NOW,
    _build_git_repo,
    _git,
    _no_worktrees,
)


@pytest.fixture(autouse=True)
def _hermetic_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", raising=False)
    for var in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_CEILING_DIRECTORIES",
    ):
        monkeypatch.delenv(var, raising=False)


def _move_into_subdir(tmp_path: Path, subdir: str) -> tuple[Path, Path]:
    """Build the fixture repo, then nest it as ``<outer>/<subdir>`` of a fresh repo."""
    built = _build_git_repo(tmp_path / "build")
    outer = tmp_path / "outer"
    outer.mkdir()
    target = outer / subdir
    shutil.copytree(built, target, ignore=shutil.ignore_patterns(".git"))
    _git(outer, "init", "-q")
    _git(outer, "config", "user.email", "test@example.invalid")
    _git(outer, "config", "user.name", "tester")
    _git(outer, "add", "-A")
    _git(outer, "commit", "-q", "-m", "init")
    _git(outer, "branch", "-M", "main")
    return outer, target


# --------------------------------------------------------------------------- #
# The gate: a work tree is required, and its absence is said plainly
# --------------------------------------------------------------------------- #


def test_run_sync_outside_any_work_tree_says_so_before_any_head_probe(
    tmp_path: Path,
) -> None:
    built = _build_git_repo(tmp_path / "build")
    loose = tmp_path / "loose"
    shutil.copytree(built, loose, ignore=shutil.ignore_patterns(".git"))
    calls: list[list[str]] = []

    def run_git(args: list[str], cwd: Path) -> str:
        calls.append(list(args))
        raise AssertionError(f"no git verb may run before the gate: {args!r}")

    with pytest.raises(SyncError, match="not in a git work tree"):
        run_sync(loose, "r", mode="local", now=_NOW, run_git=run_git)
    assert calls == []


def test_run_sync_without_git_binary_is_a_typed_sync_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Base configsync let ``FileNotFoundError`` escape as a raw traceback."""
    repo = _build_git_repo(tmp_path)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(SyncError, match=r"^git is required.*install git"):
        run_sync(repo, "r", mode="local", now=_NOW)


def test_run_sync_dubious_ownership_is_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _build_git_repo(tmp_path)
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    with pytest.raises(SyncError, match=r"exit 128\).*dubious ownership"):
        run_sync(repo, "r", mode="git", now=_NOW)


# --------------------------------------------------------------------------- #
# One work tree: the config must live in the repo being synced
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["local", "git"])
def test_run_sync_config_in_a_nested_repo_is_loud(tmp_path: Path, mode: str) -> None:
    """Base local mode silently read a config owned by ANOTHER repo."""
    repo = _build_git_repo(tmp_path)
    _git(repo / "config" / "cdmon", "init", "-q")
    with pytest.raises(SyncError, match="different git work trees"):
        run_sync(repo, "r", mode=mode, now=_NOW)
    _no_worktrees(repo)


def test_run_sync_config_from_a_submodule_is_refused(tmp_path: Path) -> None:
    """A config hosted in a submodule is a different work tree: refused, loudly.

    Pinned deliberately (an open question for the owner, not an accident): the
    sync reads one repo's config at one ref, and a submodule pins its own.
    """
    repo = _build_git_repo(tmp_path)
    cfg_src = tmp_path / "cfg-src"
    shutil.copytree(repo / "config" / "cdmon", cfg_src)
    _git(cfg_src, "init", "-q")
    _git(cfg_src, "config", "user.email", "test@example.invalid")
    _git(cfg_src, "config", "user.name", "tester")
    _git(cfg_src, "add", "-A")
    _git(cfg_src, "commit", "-q", "-m", "cfg")
    _git(repo, "rm", "-q", "-r", "config/cdmon")
    _git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(cfg_src),
        "config/cdmon",
    )
    _git(repo, "commit", "-q", "-m", "config as submodule")
    with pytest.raises(SyncError, match="different git work trees"):
        run_sync(repo, "r", mode="local", now=_NOW)


def test_run_sync_with_a_broken_submodule_elsewhere_still_syncs(tmp_path: Path) -> None:
    """``git status`` dies on a broken submodule; config sync pins its own ref
    and never asks for the dirty-tree baseline, so it must not care."""
    repo = _build_git_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},vendor/sub")
    (repo / ".gitmodules").write_text(
        '[submodule "vendor/sub"]\n\tpath = vendor/sub\n\turl = ./nowhere\n',
        encoding="utf-8",
    )
    _git(repo, "add", ".gitmodules")
    _git(repo, "commit", "-q", "-m", "submodule")
    sub = repo / "vendor" / "sub"
    sub.mkdir(parents=True)
    (sub / ".git").write_text(f"gitdir: {tmp_path / 'gone'}\n", encoding="utf-8")
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, check=False
    )
    assert status.returncode != 0  # precondition: the submodule really is broken

    for mode in ("local", "git"):
        result = run_sync(repo, "r", mode=mode, now=_NOW)
        assert result.run.document_count == 1
    _no_worktrees(repo)


# --------------------------------------------------------------------------- #
# Subdir configs: the git prefix, not a re-derived toplevel
# --------------------------------------------------------------------------- #


def test_git_mode_subdir_reached_through_a_symlink_reads_that_config(
    tmp_path: Path,
) -> None:
    outer, target = _move_into_subdir(tmp_path, "demo")
    link = tmp_path / "demo-link"
    link.symlink_to(target, target_is_directory=True)
    result = run_sync(link, "r", mode="git", now=_NOW)
    assert result.run.fully_synced is True
    assert result.run.document_count == 1
    _no_worktrees(outer)


def test_every_configsync_git_call_runs_through_the_forge_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrapper ``git`` on PATH logs LC_ALL for every call: all must be C."""
    outer, target = _move_into_subdir(tmp_path, "demo")
    real_git = shutil.which("git")
    assert real_git is not None
    log = tmp_path / "git.log"
    bin_dir = tmp_path / "wrap-bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "git"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent(
            f"""
            import os, sys
            with open({str(log)!r}, "a", encoding="utf-8") as fh:
                lc_all = os.environ.get("LC_ALL", "<unset>")
                fh.write(lc_all + " " + " ".join(sys.argv[1:]) + "\\n")
            os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])
            """
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")

    for mode in ("local", "git"):
        run_sync(target, "r", mode=mode, now=_NOW)

    lines = log.read_text(encoding="utf-8").splitlines()
    assert any(" worktree add " in f" {line} " for line in lines)
    assert lines and all(line.startswith("C ") for line in lines), lines
    _no_worktrees(outer)


def test_git_mode_utf8_subdir_under_a_non_utf8_locale(tmp_path: Path) -> None:
    """The prefix git prints is raw UTF-8; the filesystem path must be rebuilt
    from those bytes (``os.fsdecode``), not from a locale-dependent str.

    The child runs in the legacy POSIX locale with UTF-8 mode and coercion off
    (an ASCII filesystem encoding), which every libc provides: no named locale
    has to be generated in a slim CI image.
    """
    outer, target = _move_into_subdir(tmp_path, "café")
    script = textwrap.dedent(
        f"""
        import os, sys
        from pathlib import Path
        from custodex.configsync import run_sync
        assert sys.getfilesystemencoding() != "utf-8", sys.getfilesystemencoding()
        target = Path(os.fsdecode({os.fsencode(target)!r}))
        result = run_sync(target, "r", mode="git", now={_NOW!r})
        print(result.run.fully_synced, result.run.document_count)
        """
    )
    env = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    env.pop("PYTHONIOENCODING", None)
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, env=env, check=False
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.decode().split() == ["True", "1"]
    _no_worktrees(outer)


def test_non_utf8_branch_name_stays_json_safe(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    subprocess.run(
        [b"git", b"checkout", b"-q", b"-b", b"caf\xe9"], cwd=repo, check=True
    )
    result = run_sync(repo, "r", mode="local", now=_NOW)
    assert result.run.branch == "caf�"
    result.model_dump_json()  # no lone surrogate reaches the wire


def test_injected_run_git_sees_no_toplevel_probe(tmp_path: Path) -> None:
    """git mode no longer re-derives the toplevel; worktree verbs run at local_path."""
    outer, target = _move_into_subdir(tmp_path, "demo")
    seen: list[tuple[tuple[str, ...], Path]] = []

    def run_git(args: list[str], cwd: Path) -> str:
        seen.append((tuple(args), cwd))
        return _default_run_git(args, cwd)

    result = run_sync(target, "r", mode="git", now=_NOW, run_git=run_git)
    assert result.run.fully_synced is True
    verbs: Sequence[tuple[str, ...]] = [args for args, _ in seen]
    assert ("rev-parse", "--show-toplevel") not in verbs
    worktree_cwds = {cwd for args, cwd in seen if args[0] == "worktree"}
    assert worktree_cwds == {target}
    _no_worktrees(outer)


# --------------------------------------------------------------------------- #
# Messages: configsync's own SyncErrors name what failed, printably (K8)
# --------------------------------------------------------------------------- #

_NON_UTF8 = b"caf\xe9"


def _json_safe(message: str) -> str:
    message.encode("utf-8")  # a lone surrogate raises UnicodeEncodeError
    json.dumps({"detail": message}, ensure_ascii=False).encode("utf-8")
    assert "caf�" in message, message
    return message


def test_default_run_git_failure_carries_git_stderr(tmp_path: Path) -> None:
    """N14: the runner's failure names the verb, the exit code and git's stderr."""
    repo = _build_git_repo(tmp_path)
    with pytest.raises(SyncError) as info:
        _default_run_git(["rev-parse", "--verify", "no-such-ref"], repo)
    message = str(info.value)
    assert message.startswith("git rev-parse --verify no-such-ref failed in ")
    assert "(exit 128)" in message and "fatal:" in message, message
    assert message == message.rstrip()


def test_default_run_git_failure_is_printable_for_a_non_utf8_cwd_and_arg(
    tmp_path: Path,
) -> None:
    """A non-UTF-8 cwd and a non-UTF-8 ref argument both show as U+FFFD."""
    repo = _build_git_repo(tmp_path / os.fsdecode(_NON_UTF8))
    bad_ref = os.fsdecode(b"no-such-" + _NON_UTF8)
    with pytest.raises(SyncError, match=r"\(exit 128\)") as info:
        _default_run_git(["rev-parse", "--verify", bad_ref], repo)
    message = _json_safe(str(info.value))
    assert "no-such-caf�" in message and f"{os.sep}caf�{os.sep}" in message


def test_run_sync_gate_names_the_local_path(tmp_path: Path) -> None:
    """N26: the gate's refusal names the local_path it refused."""
    built = _build_git_repo(tmp_path / "build")
    loose = tmp_path / "loose"
    shutil.copytree(built, loose, ignore=shutil.ignore_patterns(".git"))
    with pytest.raises(SyncError, match="not in a git work tree") as info:
        run_sync(loose, "r", mode="local", now=_NOW)
    assert f"repo local_path {loose} is not in a git work tree" in str(info.value)


def test_run_sync_gate_message_is_printable_for_a_non_utf8_local_path(
    tmp_path: Path,
) -> None:
    built = _build_git_repo(tmp_path / "build")
    loose = tmp_path / os.fsdecode(_NON_UTF8)
    shutil.copytree(built, loose, ignore=shutil.ignore_patterns(".git"))
    with pytest.raises(SyncError, match="not in a git work tree") as info:
        run_sync(loose, "r", mode="local", now=_NOW)
    _json_safe(str(info.value))


@pytest.mark.parametrize("mode", ["local", "git"])
def test_run_sync_config_symlinked_out_of_any_repo_is_refused(
    tmp_path: Path, mode: str
) -> None:
    """A ``config/cdmon`` symlinked to a NON-git directory outside the repo (a
    shared config on a network share) is refused: the config must live in the
    repo being synced. Base local mode synced it; pinned deliberately so the
    owner ratifies (or reverses) the change, not by accident."""
    repo = _build_git_repo(tmp_path)
    shared = tmp_path / "shared-cfg"
    shutil.move(str(repo / "config" / "cdmon"), str(shared))
    (repo / "config" / "cdmon").symlink_to(shared, target_is_directory=True)
    with pytest.raises(
        SyncError, match=r"different git work trees .*config: no work tree"
    ):
        run_sync(repo, "r", mode=mode, now=_NOW)
    _no_worktrees(repo)
