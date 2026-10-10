"""X-GITFACTS — the ONE git work-tree probe git-aware callers share (S1-CITPL D6).

Scope: this module is the single place that asks git "where am I?" (work-tree
facts) and the default runner behind :mod:`custodex.configsync`. It is NOT every
git call in the package: the server's clone-on-demand leaf
(:class:`custodex.gitfetch._GitCloner`) and ``cdx onboard``'s ``user.name`` read
(``custodex.cli._git_user_name``) still run git themselves.

Two layers:

* :func:`default_git_probe` is the probe's subprocess leaf. It runs
  ``git <args>`` under ``LC_ALL=C`` and RETURNS a non-zero exit as a
  :class:`GitOutcome` for the caller to judge. git prints paths as raw bytes, so
  stdout is decoded as UTF-8 with ``surrogateescape``: the same text on every
  host (K10) and lossless (``.encode("utf-8", "surrogateescape")`` gives the
  bytes back). stderr only ever lands in an error message, so it is decoded with
  replacement. An :class:`OSError` becomes a typed
  :class:`SyncError` (K8): "git is required" when the git executable itself could
  not be run, and a message naming the cwd for anything else.
* :func:`git_facts` answers "where am I in git?" for a root + config. A ``.git``
  entry (directory, ``gitdir:`` file or dangling symlink) at the root or any
  physical parent PROMISES a work tree, so any failure to read it is loud and
  carries git's exit code and stderr (dubious ownership, a broken gitdir, a
  missing binary). Only a ``.git`` KNOWN to be absent (ENOENT/ENOTDIR at every
  level) gives the non-git facts, and then git is never run, so an off-repo run
  on an image without git keeps working. An unborn HEAD is PROVEN, not assumed:
  ``rev-parse --verify --quiet HEAD`` exits 1, silently, for a corrupt branch
  ref too, so exit 1 means "no baseline" only when HEAD names a branch whose
  ref does not exist at all.

Every :class:`SyncError` is printable UTF-8 (K8): each path or git-output
field in a message goes through :func:`printable`, so a non-UTF-8 path byte reads
as U+FFFD instead of putting a lone surrogate into a terminal or a JSON body.

Read-only (K7: ``status`` runs with ``--no-optional-locks`` so it never
refreshes ``.git/index``), no clock (K10), and the probe is injectable (K4).
Core-only: stdlib + pydantic (K0).
"""

from __future__ import annotations

import errno
import os
import posixpath
import stat
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict

from .errors import SyncError

__all__ = [
    "GitFacts",
    "GitOutcome",
    "GitProbe",
    "default_git_probe",
    "git_facts",
    "printable",
]

# Protocol constants: the git verbs this probe asks, verbatim.
_TOPLEVEL_ARGS = ("rev-parse", "--show-toplevel", "--show-prefix")
_HEAD_ARGS = ("rev-parse", "--verify", "--quiet", "HEAD")
_STATUS_ARGS = (
    "--no-optional-locks",
    "status",
    "--porcelain",
    "-z",
    "--untracked-files=no",
)
# ``rev-parse --verify --quiet HEAD`` exits 1 (and prints nothing) on an unborn
# HEAD -- and on a corrupt loose branch ref, so exit 1 must be proven unborn.
_UNBORN_HEAD_EXIT = 1
# The unborn proof: the branch HEAD names, then where git keeps its loose ref.
_SYMREF_ARGS = ("symbolic-ref", "-q", "HEAD")
_GIT_PATH_ARGS = ("rev-parse", "--git-path")
# The porcelain v1 entry is ``XY<space><path>``: two status columns + a separator.
_PORCELAIN_PATH_AT = 3
# A rename/copy code in EITHER column means an origin path follows.
_ORIGIN_CODES = frozenset("RC")
# errnos that prove an entry is absent (vs. merely unreadable).
_ABSENT = (FileNotFoundError, NotADirectoryError)


class GitOutcome(NamedTuple):
    """One git invocation's result: a non-zero exit is data, not an exception."""

    returncode: int
    stdout: str
    stderr: str


#: The injectable seam (K4): ``(args, cwd) -> GitOutcome``.
GitProbe = Callable[[Sequence[str], Path], GitOutcome]


class GitFacts(BaseModel):
    """Where a root and its config sit in git.

    * ``in_work_tree`` — a ``.git`` was found at the root or a parent.
    * ``prefix`` — git's ``--show-prefix`` of the physical root (``""`` at the
      toplevel, ``"demo/"`` in a subdir); UTF-8 + surrogateescape text. A caller
      building a filesystem path re-encodes it first:
      ``Path(os.fsdecode(prefix.encode("utf-8", "surrogateescape")))``.
    * ``config_id`` — the config's toplevel-relative POSIX path (root-relative
      when not in a work tree).
    * ``head`` — the baseline HEAD: kept only while every tracked change is a
      managed doc; ``None`` otherwise, for an unborn HEAD, or with
      ``baseline=False``.

    ``prefix`` and ``config_id`` are filesystem-lossless, NOT JSON-safe: a
    non-UTF-8 path byte is a lone surrogate, so ``model_dump_json()`` or a plain
    ``.encode()`` raises. A consumer that serialises or hashes them encodes with
    ``("utf-8", "surrogateescape")`` (hash the bytes) or shows them through
    :func:`printable`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    in_work_tree: bool
    prefix: str
    config_id: str
    head: str | None


def _command(args: Sequence[str]) -> str:
    return "git " + " ".join(args)


def printable(value: object) -> str:
    """``value`` as printable UTF-8 for an error message or a JSON body (K8).

    A path, or git's surrogateescape-decoded output, carries a non-UTF-8 byte
    as a lone surrogate, which no UTF-8 terminal or JSON body can encode; it is
    shown as U+FFFD instead. Valid text passes through unchanged.
    """
    return str(value).encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _oserror(args: Sequence[str], cwd: Path, exc: OSError) -> SyncError:
    """Map a failure to START git: blame the binary only when subprocess did."""
    where = printable(cwd)
    if exc.filename == "git":
        return SyncError(
            f"git is required: could not run `{_command(args)}` in {where} "
            f"({exc}); install git in the job image"
        )
    return SyncError(f"could not run `{_command(args)}` in {where}: {exc}")


def default_git_probe(args: Sequence[str], cwd: Path) -> GitOutcome:
    """Run ``git <args>`` in ``cwd`` under ``LC_ALL=C`` (the probe's leaf)."""
    try:
        proc = subprocess.run(  # noqa: S603 (argv is fixed git verbs, no shell)
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            env={**os.environ, "LC_ALL": "C"},
            check=False,
        )
    except OSError as exc:
        raise _oserror(args, cwd, exc) from exc
    return GitOutcome(
        proc.returncode,
        proc.stdout.decode("utf-8", "surrogateescape"),
        proc.stderr.decode("utf-8", "replace"),
    )


def _run(probe: GitProbe, args: Sequence[str], cwd: Path) -> GitOutcome:
    """Call ``probe``; an injected probe's OSError follows the leaf's rule."""
    try:
        return probe(args, cwd)
    except OSError as exc:
        raise _oserror(args, cwd, exc) from exc


def _failed(
    label: str, cwd: Path, outcome: GitOutcome, exists: Path | None = None
) -> SyncError:
    err = printable(outcome.stderr.strip()) or "(no stderr)"
    note = "" if exists is None else f" ({printable(exists)} exists)"
    return SyncError(
        f"{printable(label)} failed in {printable(cwd)}{note} "
        f"(exit {outcome.returncode}): {err}"
    )


def _unexpected(label: str, cwd: Path, detail: str, stdout: str) -> SyncError:
    return SyncError(
        f"{printable(label)} in {printable(cwd)} gave unexpected output ({detail}): "
        f"{printable(stdout)!r}"
    )


def _one_line(label: str, cwd: Path, stdout: str) -> str:
    """git's one-line answer without its newline; anything else is loud."""
    line = stdout.removesuffix("\n")
    if not line or line == stdout or "\n" in line:
        raise _unexpected(label, cwd, "expected one line", stdout)
    return line


def _fs_path(text: str) -> str:
    """git's (UTF-8 + surrogateescape) text as a filesystem str for this host."""
    return os.fsdecode(text.encode("utf-8", "surrogateescape"))


def _physical(path: Path, what: str) -> Path:
    """Resolve ``path`` physically; a symlink loop is typed on every Python.

    3.10–3.12 raise ``RuntimeError`` from ``resolve()``; 3.13+ return the loop
    path, so the result is stat'ed and ``ELOOP`` mapped. Any other stat failure
    (absent, unsearchable) is left to the caller's typed checks.
    """
    try:
        resolved = path.resolve()
    except (RuntimeError, OSError) as exc:
        raise SyncError(f"cannot resolve the {what} {printable(path)}: {exc}") from exc
    try:
        os.stat(resolved)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SyncError(
                f"cannot resolve the {what} {printable(path)}: {exc}"
            ) from exc
    return resolved


def _is_dir(path: Path) -> bool:
    """True for a directory, False when KNOWN absent; anything else is loud."""
    try:
        st = os.stat(path)
    except _ABSENT:
        return False
    except OSError as exc:
        raise SyncError(f"cannot inspect {printable(path)}: {exc}") from exc
    return stat.S_ISDIR(st.st_mode)


def _nearest_dot_git(directory: Path) -> Path | None:
    """The nearest ``.git`` entry at ``directory`` or a parent (git's walk).

    ``lstat`` so a dangling ``.git`` symlink counts as present (a broken repo, not
    no repo). Only ENOENT/ENOTDIR prove absence; EACCES etc. are loud.
    """
    for candidate in (directory, *directory.parents):
        dot_git = candidate / ".git"
        try:
            os.lstat(dot_git)
        except _ABSENT:
            continue
        except OSError as exc:
            raise SyncError(f"cannot inspect {printable(dot_git)}: {exc}") from exc
        return dot_git
    return None


def _work_tree(directory: Path, probe: GitProbe) -> tuple[str, str] | None:
    """``(toplevel, prefix)`` of ``directory``, or ``None`` when no ``.git`` exists."""
    dot_git = _nearest_dot_git(directory)
    if dot_git is None:
        return None
    label = _command(_TOPLEVEL_ARGS)
    outcome = _run(probe, _TOPLEVEL_ARGS, directory)
    if outcome.returncode != 0:
        raise _failed(label, directory, outcome, exists=dot_git)
    fields = outcome.stdout.split("\n")
    if len(fields) != 3 or fields[2] or not fields[0]:  # noqa: PLR2004 ("top\nprefix\n")
        raise _unexpected(
            label, directory, "expected toplevel and prefix lines", outcome.stdout
        )
    return fields[0], fields[1]


def _fs_text(rel: str) -> str:
    """A filesystem str in the same (UTF-8 + surrogateescape) form git's output is."""
    return os.fsencode(rel).decode("utf-8", "surrogateescape")


def _config_id(top: str, config: Path, probe: GitProbe) -> str:
    """The config's toplevel-relative POSIX path; loud if it is in another tree.

    Asked of git at the config's nearest existing directory (however many levels
    are not on disk yet), so a nested / vendored / submodule repo, or no work
    tree at all, is caught by comparing toplevels.
    """
    anchor = config
    while not _is_dir(anchor):
        anchor = anchor.parent
    tail = _fs_text(config.relative_to(anchor).as_posix())
    found = _work_tree(anchor, probe)
    if found is None or found[0] != top:
        config_top = "no work tree" if found is None else printable(found[0])
        raise SyncError(
            f"the repo root and its config are in different git work trees "
            f"(root: {printable(top)}; config: {config_top}): "
            f"config {printable(config)}"
        )
    return posixpath.normpath(found[1] + tail)


def _status_paths(stdout: str, cwd: Path) -> list[str]:
    """Parse ``status --porcelain -z`` exactly: ``(XY SP path NUL [origin NUL])*``."""
    label = "git status --porcelain"
    if not stdout:
        return []
    if not stdout.endswith("\0"):
        raise _unexpected(label, cwd, "unterminated entry", stdout)
    fields = stdout[:-1].split("\0")
    paths: list[str] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) <= _PORCELAIN_PATH_AT or entry[_PORCELAIN_PATH_AT - 1] != " ":
            raise _unexpected(label, cwd, f"malformed entry {entry!r}", stdout)
        paths.append(entry[_PORCELAIN_PATH_AT:])
        if _ORIGIN_CODES.intersection(entry[: _PORCELAIN_PATH_AT - 1]):
            if index >= len(fields) or not fields[index]:
                raise _unexpected(
                    label, cwd, f"rename/copy without origin {entry!r}", stdout
                )
            paths.append(fields[index])
            index += 1
    return paths


def _prove_unborn(root: Path, probe: GitProbe) -> None:
    """Return only if HEAD names a branch with NO ref; anything else is loud (K8).

    Two proofs, because git does not tell an unborn branch from a corrupt one on
    ``rev-parse --verify --quiet HEAD`` (exit 1, no stderr, either way):

    1. ``symbolic-ref -q HEAD`` names the branch (git 2.43 already refuses here,
       exit 128, when that branch's ref is corrupt; a detached HEAD exits 1).
    2. Its loose ref file (``rev-parse --git-path``: relative to ``root``, or
       absolute in a linked worktree's common dir) is KNOWN absent. A real
       directory there (an orphan ``feat`` beside a branch ``feat/x``) is a
       branch namespace, not a ref file, so it proves absence too -- git itself
       calls that branch unborn. ``lstat``: a symlink there is still a ref file.

    A packed-refs entry needs no check: a malformed line is already exit 128 and
    a well-formed one resolves.
    """
    sym_label = f"{_command(_SYMREF_ARGS)} (HEAD does not resolve to a commit)"
    sym = _run(probe, _SYMREF_ARGS, root)
    if sym.returncode != 0:
        raise _failed(sym_label, root, sym)
    ref = _one_line(sym_label, root, sym.stdout)
    args = (*_GIT_PATH_ARGS, _fs_path(ref))
    where = _run(probe, args, root)
    if where.returncode != 0:
        raise _failed(_command(args), root, where)
    loose = root / _fs_path(_one_line(_command(args), root, where.stdout))
    try:
        st = os.lstat(loose)
    except _ABSENT:
        return
    except OSError as exc:
        raise SyncError(f"cannot inspect {printable(loose)}: {exc}") from exc
    if stat.S_ISDIR(st.st_mode):
        return
    raise SyncError(
        f"HEAD in {printable(root)} names {printable(ref)}, whose ref "
        f"{printable(loose)} exists but does not resolve to a commit: a corrupt "
        "ref, not an unborn branch"
    )


def _baseline_head(
    root: Path, prefix: str, doc_paths: tuple[str, ...], probe: GitProbe
) -> str | None:
    """HEAD while every tracked change is a managed doc, else ``None``."""
    head_label = _command(_HEAD_ARGS)
    outcome = _run(probe, _HEAD_ARGS, root)
    if outcome.returncode == _UNBORN_HEAD_EXIT:
        _prove_unborn(root, probe)
        return None
    if outcome.returncode != 0:
        raise _failed(head_label, root, outcome)
    sha = outcome.stdout.strip()
    if not sha:
        raise _unexpected(head_label, root, "no commit id", outcome.stdout)
    status = _run(probe, _STATUS_ARGS, root)
    if status.returncode != 0:
        raise _failed(f"git status ({_command(_STATUS_ARGS)})", root, status)
    managed = {posixpath.normpath(prefix + path) for path in doc_paths}
    changed = set(_status_paths(status.stdout, root))
    return sha if changed <= managed else None


def git_facts(
    root: Path,
    *,
    config_path: Path,
    doc_paths: tuple[str, ...] = (),
    baseline: bool = True,
    probe: GitProbe = default_git_probe,
) -> GitFacts:
    """Answer "where am I in git?" for ``root`` and its config (S1-CITPL D6).

    Loud whenever a work tree is expected (a ``.git`` at the root or a parent)
    and git cannot answer; silent (non-git facts, git never run) only when no
    ``.git`` exists. ``doc_paths`` are the managed docs, root-relative; a tracked
    change to anything else costs the baseline ``head``. ``baseline=False`` skips
    the HEAD and status probes for a caller that pins its own ref.
    """
    phys_root = _physical(root, "root")
    phys_config = _physical(config_path, "config")
    if not _is_dir(phys_root):
        raise SyncError(f"repo root is not a directory: {printable(root)}")
    found = _work_tree(phys_root, probe)
    if found is None:
        rel = os.path.relpath(phys_config, phys_root)
        return GitFacts(
            in_work_tree=False,
            prefix="",
            config_id=_fs_text(Path(rel).as_posix()),
            head=None,
        )
    top, prefix = found
    config_id = _config_id(top, phys_config, probe)
    head = _baseline_head(phys_root, prefix, doc_paths, probe) if baseline else None
    return GitFacts(in_work_tree=True, prefix=prefix, config_id=config_id, head=head)
