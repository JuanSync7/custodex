"""X-GITFACTS — the ONE git work-tree probe: loud when a repo is expected (S1-CITPL D6).

:func:`custodex.forge.git_facts` answers "where am I in git?" for every
git-aware caller. The rule under test: a ``.git`` entry at the root or any
physical parent PROMISES a work tree, so any failure to read it (no binary,
dubious ownership, a broken gitdir, any non-zero exit) is a typed
:class:`SyncError` carrying git's exit code and stderr. Only a ``.git`` that is
KNOWN absent gives the non-git facts, and then git is never run.

Most cases run REAL git on a temp repo (ship-shaped); the exit-code and
porcelain-grammar edges go through the injectable probe seam (K4), because real
git cannot be made to exit 129 or -9 on demand. Every test is hermetic against
the developer's ``~/.gitconfig`` (``status.renames=false`` there would change the
porcelain under test).

Features: FEAT-PR-012, FEAT-PR-013
"""

from __future__ import annotations

import errno
import json
import os
import stat
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from custodex.errors import SyncError
from custodex.forge import (
    GitFacts,
    GitOutcome,
    default_git_probe,
    git_facts,
    printable,
)
from tests._gitrepo import GitRepo, init_repo

_TOPLEVEL = ("rev-parse", "--show-toplevel", "--show-prefix")
_HEAD = ("rev-parse", "--verify", "--quiet", "HEAD")
_STATUS = ("--no-optional-locks", "status", "--porcelain", "-z", "--untracked-files=no")
_SHA = "a" * 40
_SYMREF = ("symbolic-ref", "-q", "HEAD")


def _git_path(ref: str) -> tuple[str, ...]:
    return ("rev-parse", "--git-path", ref)


_IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
# The real-permission twins need a non-root uid (root bypasses directory modes);
# each has an ``*-emulated`` twin that raises the same errno at the same syscall,
# so the behaviour is pinned in EVERY environment (a CI image running as root
# included) and only the ship-shaped duplicate is environment-gated, visibly.
_NEEDS_NON_ROOT = pytest.mark.skipif(
    _IS_ROOT, reason="root bypasses directory permissions; the -emulated twin pins it"
)


@pytest.fixture(autouse=True)
def _hermetic_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real-git tests never read the developer's global/system git config."""
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


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _committed(path: Path, files: dict[str, str]) -> GitRepo:
    repo = init_repo(path)
    repo.commit_files("init", files)
    return repo


def _fake_probe(
    answers: dict[tuple[str, ...], GitOutcome],
    calls: list[tuple[tuple[str, ...], Path]] | None = None,
) -> Callable[[Sequence[str], Path], GitOutcome]:
    def probe(args: Sequence[str], cwd: Path) -> GitOutcome:
        key = tuple(args)
        if calls is not None:
            calls.append((key, cwd))
        assert key in answers, f"unexpected git call {key!r} in {cwd}"
        return answers[key]

    return probe


def _never_called(args: Sequence[str], cwd: Path) -> GitOutcome:
    raise AssertionError(f"git must not run here: {list(args)!r} in {cwd}")


def _no_git_above(path: Path) -> None:
    """Fail (never skip) when a test that needs 'no .git anywhere' cannot have it."""
    for directory in (path.resolve(), *path.resolve().parents):
        assert not os.path.lexists(directory / ".git"), (
            f"{directory / '.git'} exists: pytest's basetemp must be outside any "
            "git checkout for the non-git cases to mean anything"
        )


def _strip_git_from_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))


def _fake_git(tmp_path: Path, body: str) -> Path:
    """Put an executable ``git`` (a Python script) first on a fresh bin dir."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "git"
    script.write_text(f"#!{sys.executable}\n{textwrap.dedent(body)}", encoding="utf-8")
    script.chmod(0o755)
    return bin_dir


def _eacces_at(monkeypatch: pytest.MonkeyPatch, call: str, target: Path) -> None:
    """``os.<call>(target)`` raises EACCES, exactly as an unsearchable parent
    makes it; every other path goes to the real syscall."""
    real = getattr(os, call)

    def fake(path: object, *args: object, **kwargs: object) -> object:
        if os.fspath(path) == os.fspath(target):  # type: ignore[arg-type]
            raise PermissionError(errno.EACCES, "Permission denied", os.fspath(path))  # type: ignore[arg-type]
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, call, fake)


@pytest.fixture
def _restore_modes() -> Iterator[list[Path]]:
    """Paths whose mode a test drops; restored so tmp cleanup still works."""
    paths: list[Path] = []
    yield paths
    for path in paths:
        path.chmod(0o755)


def _git_layout(top: Path, prefix: str) -> dict[tuple[str, ...], GitOutcome]:
    return {_TOPLEVEL: GitOutcome(0, f"{top}\n{prefix}\n", "")}


# --------------------------------------------------------------------------- #
# F17 — the ancestor rule is sensitive to where tests run
# --------------------------------------------------------------------------- #


def test_pytest_basetemp_is_outside_any_work_tree(tmp_path: Path) -> None:
    """Every non-git case below relies on this; pin it once, loudly."""
    _no_git_above(tmp_path)


# --------------------------------------------------------------------------- #
# default_git_probe — the probe's subprocess leaf
# --------------------------------------------------------------------------- #


def test_default_git_probe_runs_git_under_lc_all_c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LC_ALL=C on top of the inherited env; a non-zero exit is RETURNED."""
    bin_dir = _fake_git(
        tmp_path,
        """
        import os, sys
        lc_all = os.environ.get("LC_ALL", "<unset>")
        sys.stdout.write(lc_all + "|" + " ".join(sys.argv[1:]))
        sys.stderr.write("cwd=" + os.getcwd())
        sys.exit(3)
        """,
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    work = tmp_path / "work"
    work.mkdir()

    outcome = default_git_probe(["rev-parse", "HEAD"], work)

    assert outcome == GitOutcome(3, "C|rev-parse HEAD", f"cwd={work.resolve()}")


def test_default_git_probe_without_the_binary_is_a_sync_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strip_git_from_path(monkeypatch, tmp_path)
    with pytest.raises(SyncError) as info:
        default_git_probe(["rev-parse", "HEAD"], tmp_path)
    message = str(info.value)
    assert message.startswith("git is required")
    assert "install git in the job image" in message
    assert f"in {tmp_path} (" in message
    assert "No such file or directory" in message


def test_non_executable_git_on_path_is_a_sync_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``git`` that cannot be exec'd (EACCES) is the same typed error as a
    missing one — never a raw PermissionError — in the leaf AND in git_facts."""
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    bin_dir = tmp_path / "noexec-bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (bin_dir / "git").chmod(0o644)
    monkeypatch.setenv("PATH", str(bin_dir))
    with pytest.raises(SyncError, match=r"^git is required.*install git"):
        default_git_probe(["--version"], tmp_path)
    with pytest.raises(SyncError, match=r"^git is required.*install git"):
        git_facts(repo.path, config_path=repo.path / "cdmon.yaml")


@pytest.mark.parametrize(
    "how",
    [
        "vanished",
        pytest.param("unsearchable", marks=_NEEDS_NON_ROOT),
        "unsearchable-emulated",
    ],
)
def test_default_git_probe_cwd_failure_is_not_blamed_on_the_binary(
    tmp_path: Path,
    how: str,
    _restore_modes: list[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """subprocess names the cwd (not ``git``) when chdir fails: say so, and do
    not send the operator to reinstall a binary that is fine."""
    cwd = tmp_path / "cwd"
    if how == "unsearchable":
        cwd.mkdir()
        cwd.chmod(0o000)
        _restore_modes.append(cwd)
    elif how == "unsearchable-emulated":
        cwd.mkdir()

        def run(*args: object, **kwargs: object) -> object:
            # What subprocess raises when the child's chdir(cwd) gets EACCES.
            raise PermissionError(errno.EACCES, "Permission denied", str(cwd))

        monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SyncError) as info:
        default_git_probe(["rev-parse", "HEAD"], cwd)
    message = str(info.value)
    assert message.startswith(f"could not run `git rev-parse HEAD` in {cwd}: ")
    assert "install git" not in message


def test_default_git_probe_stdout_is_lossless_and_stderr_is_printable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stdout carries git's raw path bytes: decoded UTF-8 + surrogateescape it
    re-encodes to the exact bytes. stderr lands in error text: always printable."""
    bin_dir = _fake_git(
        tmp_path,
        """
        import sys
        sys.stdout.buffer.write(b"caf\\xe9")
        sys.stderr.buffer.write(b"caf\\xe9")
        """,
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    outcome = default_git_probe(["x"], tmp_path)

    assert outcome.stdout.encode("utf-8", "surrogateescape") == b"caf\xe9"
    assert outcome.stderr == "caf�"
    outcome.stderr.encode("utf-8")  # no lone surrogate can reach a SyncError


# --------------------------------------------------------------------------- #
# M49 — `.git` present but git unusable is LOUD, never non-git
# --------------------------------------------------------------------------- #


def test_dubious_ownership_is_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ship-shaped: real git refuses the repo (a container checkout owned by
    another uid). The SyncError carries git's own exit code and safe.directory
    hint; it never degrades to 'not a repo'."""
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    with pytest.raises(SyncError) as info:
        git_facts(repo.path, config_path=repo.path / "cdmon.yaml")
    message = str(info.value)
    assert "exit 128" in message
    assert "dubious ownership" in message
    assert "safe.directory" in message
    assert f"({repo.path.resolve() / '.git'} exists)" in message


def test_git_present_and_rev_parse_says_dubious_ownership_is_loud(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    probe = _fake_probe(
        {_TOPLEVEL: GitOutcome(128, "", "fatal: detected dubious ownership\n")}
    )
    with pytest.raises(SyncError, match=r"exit 128\): fatal: detected dubious"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError(2, "No such file or directory", "git"),
        PermissionError(13, "Permission denied", "git"),
    ],
    ids=["enoent", "eacces"],
)
def test_git_present_but_the_probe_raises_oserror_is_loud(
    tmp_path: Path, exc: OSError
) -> None:
    """An injected probe's OSError follows the leaf's rule (K4 seam, K8)."""
    (tmp_path / ".git").mkdir()

    def probe(args: Sequence[str], cwd: Path) -> GitOutcome:
        raise exc

    with pytest.raises(SyncError, match="^git is required"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


def test_injected_probe_cwd_oserror_names_the_cwd(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    def probe(args: Sequence[str], cwd: Path) -> GitOutcome:
        raise FileNotFoundError(2, "No such file or directory", str(cwd))

    with pytest.raises(SyncError, match="^could not run `git rev-parse"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


def test_dangling_git_symlink_is_loud(tmp_path: Path) -> None:
    """A ``.git`` symlink to nowhere is a BROKEN repo, not no repo (lstat)."""
    root = tmp_path / "root"
    root.mkdir()
    (root / ".git").symlink_to(tmp_path / "nowhere")
    with pytest.raises(SyncError, match="exists"):
        git_facts(root, config_path=root / "cdmon.yaml")


def test_broken_gitdir_file_is_loud(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / ".git").write_text(f"gitdir: {tmp_path / 'gone'}\n", encoding="utf-8")
    with pytest.raises(SyncError, match=r"exit 128\): fatal: not a git repository"):
        git_facts(root, config_path=root / "cdmon.yaml")


def test_broken_nested_gitdir_names_the_nearest_git(tmp_path: Path) -> None:
    outer = _committed(tmp_path / "outer", {"readme.md": "r\n"})
    inner = outer.path / "vendor" / "lib"
    inner.mkdir(parents=True)
    (inner / ".git").write_text(f"gitdir: {tmp_path / 'gone'}\n", encoding="utf-8")
    with pytest.raises(SyncError) as info:
        git_facts(inner, config_path=inner / "cdmon.yaml")
    assert f"({inner.resolve() / '.git'} exists)" in str(info.value)


@pytest.mark.parametrize(
    "where",
    [
        pytest.param("dot-git", marks=_NEEDS_NON_ROOT),
        pytest.param("root-stat", marks=_NEEDS_NON_ROOT),
        "dot-git-emulated",
        "root-stat-emulated",
    ],
)
def test_unsearchable_root_is_loud_never_non_git(
    tmp_path: Path,
    where: str,
    _restore_modes: list[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``os.path.lexists`` says False on EACCES; "absent" must be KNOWN."""
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    if where == "dot-git":
        root = repo.path
        repo.path.chmod(0o644)  # readable listing, but not searchable
        _restore_modes.append(repo.path)
    elif where == "root-stat":
        root = repo.path / "sub"
        root.mkdir()
        repo.path.chmod(0o000)
        _restore_modes.append(repo.path)
    elif where == "dot-git-emulated":
        root = repo.path
        _eacces_at(monkeypatch, "lstat", repo.path.resolve() / ".git")
    else:
        root = repo.path / "sub"
        root.mkdir()
        _eacces_at(monkeypatch, "stat", root.resolve())
    with pytest.raises(SyncError, match="^cannot inspect "):
        git_facts(root, config_path=root / "cdmon.yaml", probe=_never_called)


# --------------------------------------------------------------------------- #
# Known absent — non-git facts, git never run
# --------------------------------------------------------------------------- #


def test_no_git_and_no_binary_is_non_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off-repo on an image without git keeps working: git is never run."""
    root = tmp_path / "proj"
    (root / "config" / "cdmon").mkdir(parents=True)
    _no_git_above(root)
    _strip_git_from_path(monkeypatch, tmp_path)

    facts = git_facts(root, config_path=root / "config" / "cdmon")

    assert facts == GitFacts(
        in_work_tree=False, prefix="", config_id="config/cdmon", head=None
    )


@pytest.mark.parametrize("spell", ["link", "real"])
def test_non_git_config_id_through_a_symlinked_root(tmp_path: Path, spell: str) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "cdmon.yaml").write_text("x: 1\n", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    _no_git_above(real)
    config = (link if spell == "link" else real) / "cdmon.yaml"

    facts = git_facts(link, config_path=config, probe=_never_called)

    assert facts.config_id == "cdmon.yaml"


# --------------------------------------------------------------------------- #
# Paths — the root and config must resolve
# --------------------------------------------------------------------------- #


def test_missing_root_is_loud(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    with pytest.raises(SyncError, match="^repo root is not a directory"):
        git_facts(root, config_path=root / "cdmon.yaml", probe=_never_called)


def test_root_that_is_a_regular_file_is_loud(tmp_path: Path) -> None:
    root = tmp_path / "cdmon.yaml"
    root.write_text("x: 1\n", encoding="utf-8")
    _no_git_above(tmp_path)
    with pytest.raises(SyncError, match="^repo root is not a directory"):
        git_facts(root, config_path=root, probe=_never_called)


def test_root_beneath_a_file_is_loud(tmp_path: Path) -> None:
    afile = tmp_path / "afile"
    afile.write_text("x\n", encoding="utf-8")
    root = afile / "sub"
    with pytest.raises(SyncError, match="^repo root is not a directory"):
        git_facts(root, config_path=root / "cdmon.yaml", probe=_never_called)


def _emulate_py313_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Python 3.13+ ``Path.resolve()`` RETURNS a loop path instead of raising."""

    def resolve(self: Path, strict: bool = False) -> Path:
        return Path(os.path.realpath(self))

    monkeypatch.setattr(Path, "resolve", resolve)


@pytest.mark.parametrize("flavour", ["native", "py313"])
@pytest.mark.parametrize("which", ["root", "config"])
def test_symlink_loop_root_or_config_is_a_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: str, flavour: str
) -> None:
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    loop_a = repo.path / "loop-a"
    loop_b = repo.path / "loop-b"
    loop_a.symlink_to(loop_b)
    loop_b.symlink_to(loop_a)
    if flavour == "py313":
        _emulate_py313_resolve(monkeypatch)
    root = loop_a if which == "root" else repo.path
    config = repo.path / "cdmon.yaml" if which == "root" else loop_a
    with pytest.raises(SyncError, match=rf"^cannot resolve the {which} .*loop-a"):
        git_facts(root, config_path=config)


def test_relative_root_with_a_vanished_process_cwd_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    gone.rmdir()
    with pytest.raises(SyncError, match="^cannot resolve the root repo"):
        git_facts(Path("repo"), config_path=Path("repo/cdmon.yaml"))


# --------------------------------------------------------------------------- #
# rev-parse --show-toplevel --show-prefix: any failure is loud and carries stderr
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rc", [1, 128, 129, -9])
def test_rev_parse_failure_with_any_nonzero_exit_carries_stderr(
    tmp_path: Path, rc: int
) -> None:
    (tmp_path / ".git").mkdir()
    probe = _fake_probe(
        {_TOPLEVEL: GitOutcome(rc, f"{tmp_path}\n\n", "error: unknown option\n")}
    )
    with pytest.raises(SyncError, match=rf"exit {rc}\): error: unknown option$"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


@pytest.mark.parametrize(
    "stdout",
    ["", "/top\n", "\n\n", "/top\n\n\n", "/top\nsub/", "/top\nsub/\nextra"],
    ids=[
        "empty",
        "one-line",
        "empty-toplevel",
        "four-fields",
        "unterminated",
        "unterminated-third-field",
    ],
)
def test_rev_parse_unexpected_output_is_loud(tmp_path: Path, stdout: str) -> None:
    (tmp_path / ".git").mkdir()
    probe = _fake_probe({_TOPLEVEL: GitOutcome(0, stdout, "")})
    with pytest.raises(SyncError, match="unexpected output"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


def test_newline_in_the_repo_path_is_loud_not_misparsed(tmp_path: Path) -> None:
    """Ship-shaped: git prints a newline in the toplevel raw."""
    repo = _committed(tmp_path / "a\nb" / "repo", {"cdmon.yaml": "x: 1\n"})
    with pytest.raises(SyncError, match="unexpected output"):
        git_facts(repo.path, config_path=repo.path / "cdmon.yaml")


# --------------------------------------------------------------------------- #
# Fields — prefix, config_id, head (T47 rows)
# --------------------------------------------------------------------------- #


def test_zero_commit_repo_facts(tmp_path: Path) -> None:
    """A brand-new repo: a work tree with an unborn HEAD — head None, no error."""
    repo = init_repo(tmp_path / "repo")
    demo = repo.path / "demo"
    (demo / "config" / "cdmon").mkdir(parents=True)

    facts = git_facts(demo, config_path=demo / "config" / "cdmon")

    assert facts == GitFacts(
        in_work_tree=True, prefix="demo/", config_id="demo/config/cdmon", head=None
    )


# T47 rows (X-GITFACTS): the git_facts half of T47. RTE-05 pins its
# ``is_ancestor`` half as a SIBLING table + test under the same T47 id (an
# ancestry row needs commits and an expected bool, not these columns).
# (root, config, dirty, doc_paths) -> (prefix, config_id, head kept?)
_T47_ROWS = [
    pytest.param(
        ".", "config/cdmon", (), (), "", "config/cdmon", True, id="toplevel-dir"
    ),
    pytest.param(".", "cdmon.yaml", (), (), "", "cdmon.yaml", True, id="toplevel-file"),
    pytest.param(
        "demo",
        "demo/config/cdmon",
        (),
        (),
        "demo/",
        "demo/config/cdmon",
        True,
        id="subdir",
    ),
    pytest.param(
        ".",
        "cdmon.yaml",
        ("src.py",),
        ("docs/a.md",),
        "",
        "cdmon.yaml",
        False,
        id="dirty-non-doc",
    ),
    pytest.param(
        ".",
        "cdmon.yaml",
        ("src.py",),
        (),
        "",
        "cdmon.yaml",
        False,
        id="dirty-no-managed-docs",
    ),
    pytest.param(
        ".",
        "cdmon.yaml",
        ("docs/a.md",),
        ("docs/a.md",),
        "",
        "cdmon.yaml",
        True,
        id="dirty-managed-doc",
    ),
    pytest.param(
        "demo",
        "demo/config/cdmon",
        ("demo/docs/b.md",),
        ("docs/b.md",),
        "demo/",
        "demo/config/cdmon",
        True,
        id="subdir-dirty-managed-doc",
    ),
    pytest.param(
        "demo",
        "demo/config/cdmon",
        ("docs/a.md",),
        ("docs/a.md",),
        "demo/",
        "demo/config/cdmon",
        False,
        id="subdir-doc-path-is-root-relative",
    ),
]


@pytest.mark.parametrize(
    ("root_rel", "config_rel", "dirty", "doc_paths", "prefix", "config_id", "kept"),
    _T47_ROWS,
)
def test_git_facts_prefix_head_anchor_and_ancestry(
    tmp_path: Path,
    root_rel: str,
    config_rel: str,
    dirty: tuple[str, ...],
    doc_paths: tuple[str, ...],
    prefix: str,
    config_id: str,
    kept: bool,
) -> None:
    repo = _committed(
        tmp_path / "repo",
        {
            "cdmon.yaml": "x: 1\n",
            "config/cdmon/index.yaml": "x: 1\n",
            "src.py": "x = 1\n",
            "docs/a.md": "a\n",
            "demo/config/cdmon/index.yaml": "x: 1\n",
            "demo/docs/b.md": "b\n",
        },
    )
    for rel in dirty:
        (repo.path / rel).write_text("edited\n", encoding="utf-8")

    facts = git_facts(
        repo.path / root_rel,
        config_path=repo.path / config_rel,
        doc_paths=doc_paths,
    )

    assert facts == GitFacts(
        in_work_tree=True,
        prefix=prefix,
        config_id=config_id,
        head=repo.head() if kept else None,
    )


def test_clean_repo_head_is_rev_parse_head(tmp_path: Path) -> None:
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    facts = git_facts(repo.path, config_path=repo.path / "cdmon.yaml")
    assert facts.head == repo.head()
    assert len(facts.head) == 40


def test_untracked_files_do_not_cost_the_baseline(tmp_path: Path) -> None:
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    (repo.path / "scratch.txt").write_text("new\n", encoding="utf-8")
    facts = git_facts(repo.path, config_path=repo.path / "cdmon.yaml")
    assert facts.head == repo.head()


@pytest.mark.parametrize(
    ("root_rel", "doc_path", "dirty"),
    [
        (".", "./docs/a.md", "docs/a.md"),
        (".", "docs//a.md", "docs/a.md"),
        (".", "docs/x/../a.md", "docs/a.md"),
        ("demo", "../README.md", "README.md"),
    ],
)
def test_unnormalised_managed_doc_path_still_keeps_head(
    tmp_path: Path, root_rel: str, doc_path: str, dirty: str
) -> None:
    """DocumentSpec.path is a free str; git prints the normalised path."""
    repo = _committed(
        tmp_path / "repo",
        {
            "cdmon.yaml": "x: 1\n",
            "docs/a.md": "a\n",
            "README.md": "r\n",
            "demo/x": "x\n",
        },
    )
    (repo.path / dirty).write_text("healed\n", encoding="utf-8")

    facts = git_facts(
        repo.path / root_rel,
        config_path=repo.path / "cdmon.yaml",
        doc_paths=(doc_path,),
    )

    assert facts.head == repo.head()


def test_staged_rename_of_a_managed_doc_keeps_head_only_if_both_paths_managed(
    tmp_path: Path,
) -> None:
    repo = _committed(
        tmp_path / "repo",
        {"cdmon.yaml": "x: 1\n", "docs/a.md": "a\n", "src.py": "x = 1\n"},
    )
    repo.git("config", "status.renames", "true")
    repo.git("mv", "docs/a.md", "docs/b.md")
    config = repo.path / "cdmon.yaml"

    both = git_facts(
        repo.path, config_path=config, doc_paths=("docs/a.md", "docs/b.md")
    )
    only_new = git_facts(repo.path, config_path=config, doc_paths=("docs/b.md",))

    assert both.head == repo.head()
    assert only_new.head is None


def test_worktree_rename_column_is_parsed_too(tmp_path: Path) -> None:
    """An intent-to-add rename shows ' R new\\0old\\0': R in the Y column."""
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n", "docs/a.md": "a\n"})
    repo.git("config", "status.renames", "true")
    (repo.path / "docs" / "a.md").rename(repo.path / "docs" / "b.md")
    repo.git("add", "-N", "docs/b.md")
    porcelain = repo.git(*_STATUS)
    assert porcelain == " R docs/b.md\0docs/a.md\0"  # precondition: real git shape
    config = repo.path / "cdmon.yaml"

    both = git_facts(
        repo.path, config_path=config, doc_paths=("docs/a.md", "docs/b.md")
    )
    only_new = git_facts(repo.path, config_path=config, doc_paths=("docs/b.md",))

    assert both.head == repo.head()
    assert only_new.head is None


def test_copy_origin_is_counted(tmp_path: Path) -> None:
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n", "src.py": "x = 1\n"})
    repo.git("config", "status.renames", "copies")
    (repo.path / "docs").mkdir()
    (repo.path / "docs" / "copy.md").write_text("x = 1\n", encoding="utf-8")
    (repo.path / "src.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    repo.add("docs/copy.md", "src.py")
    porcelain = repo.git(*_STATUS)
    assert "C  docs/copy.md\0src.py\0" in porcelain  # precondition: real git shape
    facts = git_facts(
        repo.path, config_path=repo.path / "cdmon.yaml", doc_paths=("docs/copy.md",)
    )
    assert facts.head is None


@pytest.mark.parametrize(
    "porcelain",
    [
        "M  docs/a.md",  # unterminated
        "R  docs/a.md",  # rename, no terminator, no origin
        "R  docs/a.md\0",  # rename, no origin at all
        "R  docs/a.md\0\0",  # rename, empty origin
        " R docs/a.md\0",  # worktree rename, no origin
        "M  \0",  # empty path
        "\0M  docs/a.md\0",  # empty field mid-stream
        "M  docs/a.md\0\0",  # empty field after a full record
        "M\0",  # short entry
        "MMxdocs/a.md\0",  # no separator space
    ],
    ids=[
        "unterminated",
        "rename-no-terminator",
        "rename-no-origin",
        "rename-empty-origin",
        "worktree-rename-no-origin",
        "empty-path-entry",
        "leading-empty-field",
        "trailing-extra-empty-field",
        "short-entry",
        "no-separator",
    ],
)
def test_malformed_status_is_a_typed_sync_error(tmp_path: Path, porcelain: str) -> None:
    (tmp_path / ".git").mkdir()
    probe = _fake_probe(
        {
            **_git_layout(tmp_path.resolve(), ""),
            _HEAD: GitOutcome(0, f"{_SHA}\n", ""),
            _STATUS: GitOutcome(0, porcelain, ""),
        }
    )
    with pytest.raises(SyncError, match="git status"):
        git_facts(
            tmp_path,
            config_path=tmp_path / "cdmon.yaml",
            doc_paths=("docs/a.md",),
            probe=probe,
        )


@pytest.mark.parametrize("rc", [1, 128, 129, -9])
def test_status_failure_with_any_nonzero_exit_is_loud(tmp_path: Path, rc: int) -> None:
    """129 (an old git without --no-optional-locks) and -9 (SIGKILL) print
    nothing: tolerated, that reads as a CLEAN tree and keeps a wrong HEAD."""
    (tmp_path / ".git").mkdir()
    probe = _fake_probe(
        {
            **_git_layout(tmp_path.resolve(), ""),
            _HEAD: GitOutcome(0, f"{_SHA}\n", ""),
            _STATUS: GitOutcome(rc, "", "Unknown option: --no-optional-locks\n"),
        }
    )
    with pytest.raises(SyncError, match=rf"git status.*exit {rc}\): Unknown option"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


@pytest.mark.parametrize("rc", [128, 129, -9])
def test_head_probe_failure_is_loud(tmp_path: Path, rc: int) -> None:
    """Any exit but 0 (a sha) or 1 (unborn) is loud, even after printing a sha."""
    (tmp_path / ".git").mkdir()
    probe = _fake_probe(
        {
            **_git_layout(tmp_path.resolve(), ""),
            _HEAD: GitOutcome(rc, f"{_SHA}\n", "fatal: bad object\n"),
        }
    )
    with pytest.raises(SyncError, match=rf"HEAD.*exit {rc}\): fatal: bad object"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


def test_head_probe_empty_output_is_loud(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    probe = _fake_probe(
        {**_git_layout(tmp_path.resolve(), ""), _HEAD: GitOutcome(0, "\n", "")}
    )
    with pytest.raises(SyncError, match="HEAD.*unexpected output"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


def _unborn_answers(top: Path, loose: str) -> dict[tuple[str, ...], GitOutcome]:
    """An exit-1 HEAD naming ``refs/heads/main``; its loose ref is at ``loose``."""
    return {
        **_git_layout(top, ""),
        _HEAD: GitOutcome(1, "", ""),
        _SYMREF: GitOutcome(0, "refs/heads/main\n", ""),
        _git_path("refs/heads/main"): GitOutcome(0, f"{loose}\n", ""),
    }


def test_unborn_head_skips_status(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    calls: list[tuple[tuple[str, ...], Path]] = []
    probe = _fake_probe(
        _unborn_answers(tmp_path.resolve(), ".git/refs/heads/main"), calls
    )
    facts = git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)
    assert facts.head is None
    assert _STATUS not in [args for args, _ in calls]


def test_git_facts_without_baseline_never_runs_head_or_status(tmp_path: Path) -> None:
    """A caller that pins its own ref (config sync) asks for the tree facts only."""
    (tmp_path / ".git").mkdir()
    calls: list[tuple[tuple[str, ...], Path]] = []
    probe = _fake_probe(_git_layout(tmp_path.resolve(), ""), calls)

    facts = git_facts(
        tmp_path, config_path=tmp_path / "cdmon.yaml", baseline=False, probe=probe
    )

    assert facts == GitFacts(
        in_work_tree=True, prefix="", config_id="cdmon.yaml", head=None
    )
    assert {args for args, _ in calls} == {_TOPLEVEL}


def test_baseline_defaults_on(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    probe = _fake_probe(
        {
            **_git_layout(tmp_path.resolve(), ""),
            _HEAD: GitOutcome(0, f"{_SHA}\n", ""),
            _STATUS: GitOutcome(0, "", ""),
        }
    )
    facts = git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)
    assert facts.head == _SHA


# --------------------------------------------------------------------------- #
# config_id and the one-work-tree rule
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("config_rel", "expected"),
    [("config/cdmon", "config/cdmon"), ("a/b/cdmon", "a/b/cdmon")],
    ids=["one-level-missing", "two-levels-missing"],
)
def test_config_not_yet_on_disk_is_named_lexically(
    tmp_path: Path, config_rel: str, expected: str
) -> None:
    repo = _committed(tmp_path / "repo", {"src.py": "x = 1\n"})
    facts = git_facts(repo.path, config_path=repo.path / config_rel)
    assert facts.config_id == expected


def test_config_in_another_repo_is_loud(tmp_path: Path) -> None:
    root = _committed(tmp_path / "code", {"src.py": "x = 1\n"})
    other = _committed(tmp_path / "cfg", {"cdmon.yaml": "x: 1\n"})
    with pytest.raises(SyncError, match="different git work trees") as info:
        git_facts(root.path, config_path=other.path / "cdmon.yaml")
    message = str(info.value)
    assert f"root: {root.path.resolve()}" in message
    assert f"config: {other.path.resolve()}" in message


def test_config_in_a_nested_repo_is_loud(tmp_path: Path) -> None:
    outer = _committed(tmp_path / "outer", {"src.py": "x = 1\n"})
    nested = init_repo(outer.path / "config" / "cdmon")
    nested.commit_files("cfg", {"index.yaml": "x: 1\n"})
    with pytest.raises(SyncError, match="different git work trees"):
        git_facts(outer.path, config_path=outer.path / "config" / "cdmon")


def test_config_outside_any_work_tree_is_loud(tmp_path: Path) -> None:
    root = _committed(tmp_path / "code", {"src.py": "x = 1\n"})
    loose = tmp_path / "loose"
    loose.mkdir()
    _no_git_above(loose)
    with pytest.raises(
        SyncError, match=r"different git work trees.*config: no work tree"
    ):
        git_facts(root.path, config_path=loose / "cdmon.yaml")


def test_config_symlinked_into_another_repo_is_loud(tmp_path: Path) -> None:
    root = _committed(tmp_path / "code", {"src.py": "x = 1\n"})
    other = _committed(tmp_path / "cfg", {"cdmon/index.yaml": "x: 1\n"})
    (root.path / "config").mkdir()
    (root.path / "config" / "cdmon").symlink_to(other.path / "cdmon")
    with pytest.raises(SyncError, match="different git work trees"):
        git_facts(root.path, config_path=root.path / "config" / "cdmon")


def test_root_reached_through_a_symlink_uses_git_prefix(tmp_path: Path) -> None:
    repo = _committed(tmp_path / "repo", {"demo/cdmon.yaml": "x: 1\n"})
    link = tmp_path / "demo-link"
    link.symlink_to(repo.path / "demo", target_is_directory=True)
    facts = git_facts(link, config_path=link / "cdmon.yaml")
    assert (facts.prefix, facts.config_id) == ("demo/", "demo/cdmon.yaml")


# --------------------------------------------------------------------------- #
# Encoding (K10) — lossless and locale-free
# --------------------------------------------------------------------------- #


def test_git_prefix_of_a_non_utf8_subdir_round_trips_to_the_filesystem(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "top")
    sub = Path(os.fsdecode(os.fsencode(repo.path) + b"/caf\xe9"))
    sub.mkdir()
    (sub / "cdmon.yaml").write_text("x: 1\n", encoding="utf-8")
    repo.add()
    repo.commit("init")

    facts = git_facts(sub, config_path=sub / "cdmon.yaml")

    assert facts.prefix.encode("utf-8", "surrogateescape") == b"caf\xe9/"


def _non_utf8_host_env() -> dict[str, str]:
    """A child-process env whose filesystem encoding is NOT UTF-8 on any host.

    The legacy POSIX locale with UTF-8 mode and locale coercion both off gives
    Python an ASCII filesystem encoding. ``C`` exists on every libc, so this
    needs no ``localedef`` in a slim CI image (a named latin-1 locale did).
    """
    env = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    env.pop("PYTHONIOENCODING", None)
    return env


def test_utf8_doc_path_matches_under_a_non_utf8_host_locale(tmp_path: Path) -> None:
    """The doc path comes from UTF-8 YAML; git prints raw UTF-8 bytes. A
    locale-dependent decode (``text=True``/``os.fsdecode``) would stop matching
    under a non-UTF-8 host and silently cost the baseline."""
    repo = _committed(
        tmp_path / "repo", {"cdmon.yaml": "x: 1\n", "docs/café.md": "a\n"}
    )
    (repo.path / "docs" / "café.md").write_text("healed\n", encoding="utf-8")
    script = textwrap.dedent(
        f"""
        import os, sys
        from pathlib import Path
        from custodex.forge import git_facts
        assert sys.getfilesystemencoding() != "utf-8", sys.getfilesystemencoding()
        root = Path(os.fsdecode({os.fsencode(repo.path)!r}))
        facts = git_facts(root, config_path=root / "cdmon.yaml",
                          doc_paths=("docs/caf\\u00e9.md",))
        print(facts.head)
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        env=_non_utf8_host_env(),
        check=False,
    )
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert out.stdout.decode().strip() == repo.head()


@pytest.mark.parametrize("in_git", [True, False], ids=["git", "non-git"])
def test_config_id_is_locale_free_under_a_non_utf8_host_locale(
    tmp_path: Path, in_git: bool
) -> None:
    """config_id is the same text git would print, whatever the host locale.

    The tail below the config's nearest directory comes from the filesystem
    (``fsdecode``: locale-dependent), the prefix from git (UTF-8). Without the
    re-decode a non-UTF-8 host names ``cdmon-café.yaml`` something else
    (``cdmon-cafÃ©.yaml`` under latin-1, lone surrogates under ASCII).
    """
    root = tmp_path / "repo"
    root.mkdir()
    (root / "cdmon-café.yaml").write_text("x: 1\n", encoding="utf-8")
    if in_git:
        _committed(root, {"src.py": "x = 1\n"})
    else:
        _no_git_above(root)
    script = textwrap.dedent(
        f"""
        import os, sys
        from pathlib import Path
        from custodex.forge import git_facts
        assert sys.getfilesystemencoding() != "utf-8", sys.getfilesystemencoding()
        root = Path(os.fsdecode({os.fsencode(root)!r}))
        config = Path(os.fsdecode({os.fsencode(root / "cdmon-café.yaml")!r}))
        facts = git_facts(root, config_path=config, baseline=False)
        print(ascii(facts.config_id))
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        env=_non_utf8_host_env(),
        check=False,
    )
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert out.stdout.decode().strip() == ascii("cdmon-café.yaml")


# --------------------------------------------------------------------------- #
# Message hygiene (K8) — every SyncError is printable, JSON-safe UTF-8
# --------------------------------------------------------------------------- #
#
# A SyncError reaches a terminal and the server's JSON error body. Git prints
# paths as raw bytes and Python spells an undecodable path byte as a lone
# surrogate, so EVERY path or git-output field interpolated into a message is
# shown replacement-decoded (``caf\xe9`` -> ``caf\ufffd``).

_NON_UTF8 = b"caf\xe9"


def _non_utf8(parent: Path, tag: str = "") -> Path:
    return parent / os.fsdecode(_NON_UTF8 + tag.encode("ascii"))


def _printable(exc: BaseException) -> str:
    message = str(exc)
    message.encode("utf-8")  # a lone surrogate raises UnicodeEncodeError
    json.dumps({"detail": message}, ensure_ascii=False).encode("utf-8")
    assert "caf\ufffd" in message, message
    return message


def test_unexpected_output_error_never_carries_a_lone_surrogate(tmp_path: Path) -> None:
    """X10: git's raw non-UTF-8 bytes in a malformed answer stay printable."""
    (tmp_path / ".git").mkdir()
    probe = _fake_probe({_TOPLEVEL: GitOutcome(0, "/r/caf\udce9\n", "")})
    with pytest.raises(SyncError, match="unexpected output") as info:
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)
    _printable(info.value)


def test_unexpected_output_from_a_non_utf8_newline_path_is_printable(
    tmp_path: Path,
) -> None:
    """X10, ship-shaped: real git on a ``caf\\xe9\\nb`` path (4 fields, raw
    bytes). The WHOLE message is printable: the cwd as well as git's output."""
    repo = _committed(_non_utf8(tmp_path, "\nb") / "repo", {"cdmon.yaml": "x: 1\n"})
    with pytest.raises(SyncError, match="unexpected output") as info:
        git_facts(repo.path, config_path=repo.path / "cdmon.yaml")
    message = _printable(info.value)
    assert "caf\ufffd" in message.split("gave unexpected output", 1)[1]


@pytest.mark.parametrize("rc", [1, 129, -9])
def test_failure_with_empty_stderr_says_so(tmp_path: Path, rc: int) -> None:
    """X13: a silent git failure (e.g. SIGKILL'd by EDR) still reads as a sentence."""
    (tmp_path / ".git").mkdir()
    probe = _fake_probe({_TOPLEVEL: GitOutcome(rc, "", "")})
    with pytest.raises(SyncError, match=rf"\(exit {rc}\): \(no stderr\)$"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


def _raise_oserror_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    default_git_probe(["rev-parse", "HEAD"], _non_utf8(tmp_path) / "gone")


def _raise_oserror_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = _non_utf8(tmp_path)
    cwd.mkdir()
    _strip_git_from_path(monkeypatch, tmp_path)
    default_git_probe(["--version"], cwd)


def _raise_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _non_utf8(tmp_path)
    (root / ".git").mkdir(parents=True)
    probe = _fake_probe({_TOPLEVEL: GitOutcome(128, "", "fatal: nope\n")})
    git_facts(root, config_path=root / "cdmon.yaml", probe=probe)


def _raise_failed_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # An injected probe (K4) may hand back stderr that was never replace-decoded.
    (tmp_path / ".git").mkdir()
    probe = _fake_probe({_TOPLEVEL: GitOutcome(128, "", "fatal: caf\udce9\n")})
    git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


def _raise_unexpected_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _non_utf8(tmp_path)
    (root / ".git").mkdir(parents=True)
    probe = _fake_probe({_TOPLEVEL: GitOutcome(0, "one-line", "")})
    git_facts(root, config_path=root / "cdmon.yaml", probe=probe)


def _raise_resolve_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _non_utf8(tmp_path)
    loop.symlink_to(loop)
    git_facts(loop, config_path=tmp_path / "cdmon.yaml", probe=_never_called)


def _raise_resolve_loop_py313(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _emulate_py313_resolve(monkeypatch)
    _raise_resolve_loop(tmp_path, monkeypatch)


def _raise_not_a_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _non_utf8(tmp_path)
    git_facts(root, config_path=root / "cdmon.yaml", probe=_never_called)


def _raise_cannot_stat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _non_utf8(tmp_path)
    root.mkdir()
    _eacces_at(monkeypatch, "stat", root.resolve())
    git_facts(root, config_path=root / "cdmon.yaml", probe=_never_called)


def _raise_cannot_lstat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _non_utf8(tmp_path)
    root.mkdir()
    _eacces_at(monkeypatch, "lstat", root.resolve() / ".git")
    git_facts(root, config_path=root / "cdmon.yaml", probe=_never_called)


def _raise_other_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _committed(_non_utf8(tmp_path, "-a"), {"src.py": "x = 1\n"}).path
    other = _committed(_non_utf8(tmp_path, "-b"), {"cdmon.yaml": "x: 1\n"}).path
    git_facts(root, config_path=other / "cdmon.yaml", baseline=False)


def _raise_no_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _committed(_non_utf8(tmp_path, "-a"), {"src.py": "x = 1\n"}).path
    loose = _non_utf8(tmp_path, "-c")
    loose.mkdir()
    git_facts(root, config_path=loose / "cdmon.yaml", baseline=False)


def _raise_corrupt_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _committed(_non_utf8(tmp_path) / "repo", {"cdmon.yaml": "x: 1\n"})
    _corrupt_head_ref(repo, "garbage\n")
    git_facts(repo.path, config_path=repo.path / "cdmon.yaml")


def _non_utf8_ref_answers(
    top: Path, git_path: GitOutcome
) -> dict[tuple[str, ...], GitOutcome]:
    """An exit-1 HEAD naming the non-UTF-8 branch ``caf\\xe9`` (git's text form)."""
    return {
        **_git_layout(top, ""),
        _HEAD: GitOutcome(1, "", ""),
        _SYMREF: GitOutcome(0, "refs/heads/caf\udce9\n", ""),
        _git_path(os.fsdecode(b"refs/heads/" + _NON_UTF8)): git_path,
    }


def _raise_corrupt_ref_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A non-UTF-8 root AND branch: the root, the ref and its path all show.
    root = _non_utf8(tmp_path)
    (root / ".git" / "refs" / "heads").mkdir(parents=True)
    (root / ".git" / "refs" / "heads" / os.fsdecode(_NON_UTF8)).write_bytes(b"x\n")
    loose = GitOutcome(0, ".git/refs/heads/caf\udce9\n", "")
    probe = _fake_probe(_non_utf8_ref_answers(root.resolve(), loose))
    git_facts(root, config_path=root / "cdmon.yaml", probe=probe)


def _raise_git_path_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the LABEL (``git rev-parse --git-path <ref>``) carries the byte.
    (tmp_path / ".git").mkdir()
    failed = GitOutcome(128, "", "fatal: odd\n")
    probe = _fake_probe(_non_utf8_ref_answers(tmp_path.resolve(), failed))
    git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


def _raise_cannot_lstat_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The unborn proof cannot inspect the loose ref under a non-UTF-8 root.
    root = _non_utf8(tmp_path)
    (root / ".git").mkdir(parents=True)
    top = root.resolve()
    _eacces_at(monkeypatch, "lstat", top / ".git" / "refs" / "heads" / "main")
    probe = _fake_probe(_unborn_answers(top, ".git/refs/heads/main"))
    git_facts(root, config_path=root / "cdmon.yaml", probe=probe)


def _raise_git_path_unexpected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    odd = GitOutcome(0, ".git/unterminated", "")
    probe = _fake_probe(_non_utf8_ref_answers(tmp_path.resolve(), odd))
    git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


@pytest.mark.parametrize(
    "raise_it",
    [
        _raise_oserror_cwd,
        _raise_oserror_binary,
        _raise_failed,
        _raise_failed_stderr,
        _raise_unexpected_cwd,
        _raise_resolve_loop,
        _raise_resolve_loop_py313,
        _raise_not_a_dir,
        _raise_cannot_stat,
        _raise_cannot_lstat,
        _raise_other_tree,
        _raise_no_tree,
        _raise_corrupt_ref,
        _raise_corrupt_ref_on_disk,
        _raise_git_path_failed,
        _raise_git_path_unexpected,
        _raise_cannot_lstat_ref,
    ],
    ids=lambda fn: fn.__name__.removeprefix("_raise_"),
)
def test_every_sync_error_shows_a_non_utf8_path_printably(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raise_it: Callable[[Path, pytest.MonkeyPatch], None],
) -> None:
    """Each message site, reached with a non-UTF-8 path (or git output), gives
    a SyncError whose text encodes as UTF-8 and survives a JSON body."""
    with pytest.raises(SyncError) as info:
        raise_it(tmp_path, monkeypatch)
    _printable(info.value)


def test_printable_is_identity_on_valid_text_and_idempotent() -> None:
    assert printable("demo/café") == "demo/café"
    shown = printable(os.fsdecode(b"caf\xe9"))
    assert shown == "caf�"
    assert printable(shown) == shown
    assert printable(Path("a") / "b") == "a/b"


# --------------------------------------------------------------------------- #
# Unborn vs corrupt HEAD — an exit-1 HEAD probe must PROVE it is unborn (K8)
# --------------------------------------------------------------------------- #
#
# ``rev-parse --verify --quiet HEAD`` exits 1 with no stderr both for an unborn
# branch AND for a corrupt loose ref (garbage or an empty file). Only the first
# means "no baseline"; the second is malformed input and must be loud. (A
# malformed packed-refs line is already exit 128, and a well-formed ref to a
# missing object exits 0, so neither reaches the exit-1 path.)


def _corrupt_head_ref(repo: GitRepo, content: str) -> Path:
    """Overwrite the checked-out branch's LOOSE ref file with ``content``."""
    ref = repo.git("symbolic-ref", "HEAD").strip()
    path = repo.path / ".git" / ref
    assert path.is_file(), f"{path} is not a loose ref"  # init_repo never packs
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize("content", ["garbage\n", ""], ids=["garbage", "empty"])
def test_corrupt_branch_ref_is_loud_not_unborn(tmp_path: Path, content: str) -> None:
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    assert git_facts(repo.path, config_path=repo.path / "cdmon.yaml").head == (
        repo.head()
    )
    _corrupt_head_ref(repo, content)
    with pytest.raises(SyncError, match="HEAD does not resolve"):
        git_facts(repo.path, config_path=repo.path / "cdmon.yaml")


@pytest.mark.parametrize("spell", ["relative", "absolute", "subdir-relative"])
def test_exit_1_head_whose_ref_file_exists_is_loud(tmp_path: Path, spell: str) -> None:
    """The second proof: even when ``symbolic-ref`` names the branch (a git that
    does not refuse a corrupt target), an existing loose ref file is corrupt.
    ``--git-path`` is relative to the cwd (the root, maybe a subdir) or absolute
    (a linked worktree's common dir)."""
    top = tmp_path.resolve()
    ref_file = top / ".git" / "refs" / "heads" / "main"
    ref_file.parent.mkdir(parents=True)
    ref_file.write_text("garbage\n", encoding="utf-8")
    root = top / "demo" if spell == "subdir-relative" else top
    root.mkdir(exist_ok=True)
    loose = {
        "relative": ".git/refs/heads/main",
        "absolute": str(ref_file),
        "subdir-relative": "../.git/refs/heads/main",
    }[spell]
    prefix = "demo/" if spell == "subdir-relative" else ""
    answers = {**_unborn_answers(top, loose), **_git_layout(top, prefix)}
    with pytest.raises(
        SyncError, match=r"refs/heads/main.*exists but does not resolve"
    ):
        git_facts(root, config_path=root / "cdmon.yaml", probe=_fake_probe(answers))


def test_exit_1_head_whose_ref_cannot_be_inspected_is_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    top = tmp_path.resolve()
    _eacces_at(monkeypatch, "lstat", top / ".git" / "refs" / "heads" / "main")
    probe = _fake_probe(_unborn_answers(top, ".git/refs/heads/main"))
    with pytest.raises(SyncError, match=r"cannot inspect .*refs/heads/main"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


@pytest.mark.parametrize("rc", [1, 128])
def test_exit_1_head_that_symbolic_ref_refuses_is_loud(tmp_path: Path, rc: int) -> None:
    """git 2.43 refuses a HEAD whose branch ref is corrupt (exit 128); a
    detached HEAD exits 1. Neither is an unborn branch."""
    (tmp_path / ".git").mkdir()
    stderr = "fatal: No such ref: HEAD\n" if rc == 128 else ""  # noqa: PLR2004
    probe = _fake_probe(
        {
            **_git_layout(tmp_path.resolve(), ""),
            _HEAD: GitOutcome(1, "", ""),
            _SYMREF: GitOutcome(rc, "", stderr),
        }
    )
    with pytest.raises(SyncError, match=rf"symbolic-ref.*\(exit {rc}\)"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


@pytest.mark.parametrize("rc", [1, 128])
def test_exit_1_head_whose_git_path_fails_is_loud(tmp_path: Path, rc: int) -> None:
    """Any non-zero ``--git-path`` is loud, even one (exit 1) whose stdout
    names a path that is absent and would otherwise read as unborn."""
    (tmp_path / ".git").mkdir()
    answers = _unborn_answers(tmp_path.resolve(), "unused")
    answers[_git_path("refs/heads/main")] = GitOutcome(
        rc, ".git/refs/heads/main\n", "fatal: odd\n" if rc != 1 else ""
    )
    with pytest.raises(SyncError, match=rf"--git-path refs/heads/main.*exit {rc}\)"):
        git_facts(
            tmp_path, config_path=tmp_path / "cdmon.yaml", probe=_fake_probe(answers)
        )


@pytest.mark.parametrize(
    ("which", "stdout"),
    [
        ("symref", ""),
        ("symref", "\n"),
        ("symref", "refs/heads/main"),
        ("symref", "refs/heads/a\nrefs/heads/b\n"),
        ("git-path", "\n"),
        ("git-path", ".git/refs/heads/main"),
    ],
    ids=[
        "symref-empty",
        "symref-blank-line",
        "symref-unterminated",
        "symref-two-lines",
        "git-path-blank-line",
        "git-path-unterminated",
    ],
)
def test_unborn_proof_unexpected_output_is_loud(
    tmp_path: Path, which: str, stdout: str
) -> None:
    (tmp_path / ".git").mkdir()
    answers = _unborn_answers(tmp_path.resolve(), ".git/refs/heads/main")
    key = _SYMREF if which == "symref" else _git_path("refs/heads/main")
    answers[key] = GitOutcome(0, stdout, "")
    with pytest.raises(SyncError, match="unexpected output") as info:
        git_facts(
            tmp_path, config_path=tmp_path / "cdmon.yaml", probe=_fake_probe(answers)
        )
    assert "\n" not in str(info.value)


def test_unborn_branch_in_a_linked_worktree_is_unborn(tmp_path: Path) -> None:
    """Ship-shaped absolute ``--git-path``: a linked worktree's branch refs live
    in the COMMON git dir, so the proof must take git's path, not ``.git/<ref>``."""
    repo = _committed(tmp_path / "main", {"cdmon.yaml": "x: 1\n"})
    linked = tmp_path / "linked"
    repo.git("worktree", "add", "-q", "--detach", str(linked))
    subprocess.run(
        ["git", "checkout", "-q", "--orphan", "fresh"],
        cwd=linked,
        check=True,
        capture_output=True,
    )
    facts = git_facts(linked, config_path=linked / "cdmon.yaml")
    assert facts == GitFacts(
        in_work_tree=True, prefix="", config_id="cdmon.yaml", head=None
    )


def test_unborn_branch_named_below_an_existing_branch_is_unborn(tmp_path: Path) -> None:
    """``HEAD -> refs/heads/main/x`` while ``main`` exists: the loose ref path
    runs through a FILE (ENOTDIR), which proves absence just as ENOENT does."""
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    repo.git("symbolic-ref", "HEAD", "refs/heads/main/x")
    facts = git_facts(repo.path, config_path=repo.path / "cdmon.yaml")
    assert facts.in_work_tree is True
    assert facts.head is None


@pytest.mark.parametrize("packed", [False, True], ids=["loose", "packed"])
def test_orphan_branch_that_prefixes_an_existing_branch_is_unborn(
    tmp_path: Path, packed: bool
) -> None:
    """``git checkout --orphan feat`` beside a branch ``feat/x``: git calls the
    orphan unborn ("On branch feat"). Its loose-ref path is the DIRECTORY that
    holds a loose ``feat/x`` -- a directory is not a ref file, so the proof holds
    whether ``feat/x`` is loose or packed (the two must not disagree)."""
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    repo.git("branch", "feat/x")
    if packed:
        repo.git("pack-refs", "--all")
    assert (repo.path / ".git/refs/heads/feat").is_dir() is not packed
    repo.git("checkout", "-q", "--orphan", "feat")
    facts = git_facts(repo.path, config_path=repo.path / "cdmon.yaml")
    assert facts.in_work_tree is True
    assert facts.head is None


def test_exit_1_head_whose_ref_path_is_a_directory_is_unborn(tmp_path: Path) -> None:
    """Emulated twin: the loose-ref path exists but is a directory (a branch
    namespace), which is no loose ref, so an exit-1 HEAD is unborn."""
    (tmp_path / ".git" / "refs" / "heads" / "main").mkdir(parents=True)
    probe = _fake_probe(_unborn_answers(tmp_path.resolve(), ".git/refs/heads/main"))
    facts = git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)
    assert facts.head is None


def test_exit_1_head_whose_ref_path_is_a_symlink_to_a_directory_is_loud(
    tmp_path: Path,
) -> None:
    """Only a real directory is exempt: a symlink at the ref path is a ref file
    git could not resolve, even when it points at a directory (lstat, not stat)."""
    heads = tmp_path / ".git" / "refs" / "heads"
    (heads / "elsewhere").mkdir(parents=True)
    (heads / "main").symlink_to(heads / "elsewhere")
    probe = _fake_probe(_unborn_answers(tmp_path.resolve(), ".git/refs/heads/main"))
    with pytest.raises(SyncError, match="corrupt ref, not an unborn branch"):
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)


def test_unborn_non_ascii_branch_under_a_non_utf8_host_locale(tmp_path: Path) -> None:
    """The ref git names is UTF-8 text; handing it back to git (``--git-path``)
    and to ``lstat`` must re-encode it through the filesystem encoding, or an
    ASCII-locale host crashes with a raw UnicodeEncodeError."""
    repo = init_repo(tmp_path / "repo")
    subprocess.run(
        [b"git", b"symbolic-ref", b"HEAD", "refs/heads/café".encode()],
        cwd=repo.path,
        check=True,
    )
    script = textwrap.dedent(
        f"""
        import os, sys
        from pathlib import Path
        from custodex.forge import git_facts
        assert sys.getfilesystemencoding() != "utf-8", sys.getfilesystemencoding()
        root = Path(os.fsdecode({os.fsencode(repo.path)!r}))
        print(git_facts(root, config_path=root / "cdmon.yaml").head)
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        env=_non_utf8_host_env(),
        check=False,
    )
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert out.stdout.decode().strip() == "None"


# --------------------------------------------------------------------------- #
# Round-2 mutation gaps (N3, N5, N13, N23): each test kills its mutant alone
# --------------------------------------------------------------------------- #


def test_whitespace_only_stderr_reads_as_no_stderr(tmp_path: Path) -> None:
    """N3: git's stderr is stripped before the "(no stderr)" fallback."""
    (tmp_path / ".git").mkdir()
    probe = _fake_probe({_TOPLEVEL: GitOutcome(1, "", " \n")})
    with pytest.raises(SyncError) as info:
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)
    assert str(info.value).endswith("(exit 1): (no stderr)")


def test_real_git_failure_message_has_no_trailing_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N3, ship-shaped: real git ends stderr with a newline; the message does not."""
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    with pytest.raises(SyncError, match="dubious ownership") as info:
        git_facts(repo.path, config_path=repo.path / "cdmon.yaml")
    assert str(info.value) == str(info.value).rstrip()


@pytest.mark.parametrize("case", ["toplevel-4-fields", "status-nul"])
def test_unexpected_output_is_quoted_on_one_line(tmp_path: Path, case: str) -> None:
    """N5: git's answer is shown quoted, so a multi-line / NUL answer stays one line."""
    (tmp_path / ".git").mkdir()
    if case == "toplevel-4-fields":
        answers = {_TOPLEVEL: GitOutcome(0, "/r\nx\ny\n", "")}
    else:
        answers = {
            **_git_layout(tmp_path.resolve(), ""),
            _HEAD: GitOutcome(0, f"{_SHA}\n", ""),
            _STATUS: GitOutcome(0, "?\0", ""),
        }
    with pytest.raises(SyncError, match="unexpected output") as info:
        git_facts(
            tmp_path, config_path=tmp_path / "cdmon.yaml", probe=_fake_probe(answers)
        )
    message = str(info.value)
    assert "\n" not in message and "\x00" not in message, repr(message)


def test_non_git_config_id_is_lossless_for_a_non_utf8_name(tmp_path: Path) -> None:
    """N13: config_id is git's text form (UTF-8 + surrogateescape) of the raw bytes."""
    root = tmp_path / "root"
    root.mkdir()
    _no_git_above(root)
    config = root / os.fsdecode(b"cdmon-caf\xe9.yaml")
    facts = git_facts(root, config_path=config, probe=_never_called)
    assert facts.config_id.encode("utf-8", "surrogateescape") == b"cdmon-caf\xe9.yaml"


def test_git_config_id_tail_is_lossless_for_a_non_utf8_name(tmp_path: Path) -> None:
    """N13: the not-yet-on-disk tail below the config's nearest directory too."""
    repo = _committed(tmp_path / "repo", {"x.txt": "x\n"})
    config = repo.path / os.fsdecode(b"caf\xe9") / "cdmon"
    facts = git_facts(repo.path, config_path=config, baseline=False)
    assert facts.config_id.encode("utf-8", "surrogateescape") == b"caf\xe9/cdmon"


def test_injected_probe_filenameless_oserror_is_not_git_is_required(
    tmp_path: Path,
) -> None:
    """N23: only an OSError NAMING the git binary blames the image."""
    (tmp_path / ".git").mkdir()

    def probe(args: Sequence[str], cwd: Path) -> GitOutcome:
        raise PermissionError(errno.EACCES, "Permission denied")

    with pytest.raises(SyncError, match="^could not run `git rev-parse") as info:
        git_facts(tmp_path, config_path=tmp_path / "cdmon.yaml", probe=probe)
    assert "git is required" not in str(info.value)


# --------------------------------------------------------------------------- #
# Properties — read-only (K7), deterministic (K10), typed model (K8)
# --------------------------------------------------------------------------- #


def test_git_facts_never_writes_the_index(tmp_path: Path) -> None:
    """Plain ``git status`` refreshes a stale stat cache into .git/index."""
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n", "src.py": "x = 1\n"})
    src = repo.path / "src.py"
    st = src.stat()
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    index = repo.path / ".git" / "index"
    before = index.read_bytes()

    facts = git_facts(repo.path, config_path=repo.path / "cdmon.yaml")

    assert facts.head == repo.head()
    assert index.read_bytes() == before


def test_git_facts_is_deterministic_and_read_only(tmp_path: Path) -> None:
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n", "docs/a.md": "a\n"})
    (repo.path / "docs" / "a.md").write_text("edited\n", encoding="utf-8")
    before = repo.git("status", "--porcelain")
    args = {"config_path": repo.path / "cdmon.yaml", "doc_paths": ("docs/a.md",)}

    first = git_facts(repo.path, **args)  # type: ignore[arg-type]
    second = git_facts(repo.path, **args)  # type: ignore[arg-type]

    assert first == second
    assert repo.git("status", "--porcelain") == before


def test_git_facts_model_is_frozen_and_closed() -> None:
    facts = GitFacts(in_work_tree=False, prefix="", config_id="x", head=None)
    with pytest.raises(ValidationError):
        facts.prefix = "y"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        GitFacts(in_work_tree=False, prefix="", config_id="x", head=None, extra=1)  # type: ignore[call-arg]


def test_root_stat_mode_is_untouched(tmp_path: Path) -> None:
    """Belt and braces for K7: the probe changes no permission bits."""
    repo = _committed(tmp_path / "repo", {"cdmon.yaml": "x: 1\n"})
    mode = stat.S_IMODE(repo.path.stat().st_mode)
    git_facts(repo.path, config_path=repo.path / "cdmon.yaml")
    assert stat.S_IMODE(repo.path.stat().st_mode) == mode
