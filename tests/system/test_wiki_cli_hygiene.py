"""Hygiene guards for the ``cdx wiki`` system tests (TEST-WIKI-HYGIENE).

``tests/system/test_wiki_cli.py`` runs ``cdx wiki`` in WRITE mode. Those tests run
on a private copy of the repo (:func:`tests._wikirepo.copy_wiki_repo`), never on
the real tree. A write-then-restore fixture is still a write: while the test runs,
a concurrent reader, an editor or a killed run sees a corrupted wiki, and a
byte-identical restore (or one that also restores mtime, as ``shutil.copy2`` does)
hides that the write ever happened.

This module pins that contract four ways:

* the copy helper's own contract (refuses an existing destination, copies files
  instead of linking them, skips a dangling symlink);
* the copy is FAITHFUL: every :data:`custodex.wiki.WIKI_TARGETS` render on the copy
  equals the render on the real tree, so the copy-based tests still test the repo;
* the snapshot diff the guard relies on sees a restored, a created, a removed and
  a transient (created then deleted) file;
* the stale-repo guard: ``test_wiki_cli.py`` runs in a child pytest whose repo root
  is a scratch copy with deliberately STALE wikis. Any write-mode run against that
  root regenerates them, so the guard sees it whatever the state of the real wikis
  (on a fresh real tree a write-mode run writes nothing and would go unseen).

Features: FEAT-REFERENCE-007
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from custodex.wiki import WIKI_TARGETS
from tests._repo import REPO_ROOT
from tests._wikirepo import WIKI_REPO_DIRS, _wiki_repo_dirs, copy_wiki_repo

# The module under guard, repo-relative (also its pytest nodeid prefix).
_MODULE = "tests/system/test_wiki_cli.py"
# The one test in _MODULE that MUST fail on a stale repo: the freshness gate.
_FRESHNESS_GATE = "test_committed_wikis_are_fresh_through_the_cli"
# Appended to every wiki in the scratch repo so it is stale on purpose.
_STALE_MARK = "\n<!-- stale on purpose: TEST-WIKI-HYGIENE guard -->\n"
# The only parent variables the child inherits. Everything else (PYTEST_ADDOPTS,
# PY_COLORS, FORCE_COLOR, COVERAGE_*, ...) would change the child's options or
# output format, so the guard would test the developer's shell, not the module.
# The child's output is captured, not a terminal, so with PY_COLORS and
# FORCE_COLOR gone it is never coloured and every summary line parses.
_CHILD_ENV_ALLOWLIST = ("HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "TMPDIR")
# A generous ceiling for the child run (it takes about 10 s) so a hang fails loudly.
_CHILD_TIMEOUT_S = 600
# One line of pytest's -rA short summary: the outcome word, then the nodeid. Only
# PASSED/FAILED matter for detection: the exact-outcome map already fails any
# other result, because its nodeid is then missing or maps to the wrong word. The
# other words are parsed so the failure diff names them (a SKIPPED line carries
# "[n]" instead of a nodeid and is recorded as-is).
_SUMMARY_LINE = re.compile(
    r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) (\S+)", re.MULTILINE
)

Snapshot = dict[str, tuple[int, int, str]]


def _snapshot(root: Path) -> Snapshot:
    """Record every directory and file under ``root``: (mtime_ns, ctime_ns, sha256).

    ctime is the write detector: user space cannot set it, and every write,
    rename or ``os.utime`` call bumps it, so a restore that puts back both bytes and
    mtime (``shutil.copy2``) still shows. mtime and sha256 are defence in depth and
    diagnostics. Directories are recorded too (key ``rel/``, empty digest): adding
    or removing an entry bumps the directory's ctime, so a file created and deleted
    within the run still shows.
    """
    snap: Snapshot = {}
    for path in [root, *sorted(root.rglob("*"))]:
        st = path.stat()
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            snap[rel + "/"] = (st.st_mtime_ns, st.st_ctime_ns, "")
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snap[rel] = (st.st_mtime_ns, st.st_ctime_ns, digest)
    return snap


def _touched(before: Snapshot, after: Snapshot) -> list[str]:
    """Every key whose record changed, appeared or disappeared, sorted (K10)."""
    return sorted(
        k for k in before.keys() | after.keys() if before.get(k) != after.get(k)
    )


def _wait_for_ctime_tick(probe: Path, snap: Snapshot) -> None:
    """Block until the filesystem clock is past every ctime in ``snap``.

    File ctime comes from the kernel's coarse clock (one jiffy), not a nanosecond
    clock, so a write that lands in the same tick as the snapshot keeps the same
    ctime, and without this wait the snapshot-diff tests below miss a restore
    about a third of the time (92 of 300, measured). It is anti-flake code, so a
    mutant that weakens it is killed statistically, not on every run. ``probe``
    must live on the same filesystem as the snapshotted tree.
    """
    newest = max(ctime for _, ctime, _ in snap.values())
    while True:
        probe.write_text("tick", encoding="utf-8")
        if probe.stat().st_ctime_ns > newest:
            return


def _child_env(root: Path) -> dict[str, str]:
    """The child's environment: the allowlist, plus what points it at ``root``."""
    env = {k: os.environ[k] for k in _CHILD_ENV_ALLOWLIST if k in os.environ}
    env["PYTHONPATH"] = str(root)
    # No __pycache__ in the snapshotted tree: only the module's own writes count.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _stale_repo(dst: Path) -> Path:
    """A scratch repo at ``dst`` whose committed wikis are deliberately stale.

    ``pyproject.toml`` is what makes ``tests._repo.REPO_ROOT`` (and pytest's
    rootdir) resolve to ``dst`` in the child, so every repo path the module uses
    lands in the scratch copy.
    """
    root = copy_wiki_repo(dst)
    shutil.copy2(REPO_ROOT / "pyproject.toml", root / "pyproject.toml")
    for rel in WIKI_TARGETS:
        target = root / rel
        target.write_text(
            target.read_text(encoding="utf-8") + _STALE_MARK, encoding="utf-8"
        )
    return root


def _outcomes(output: str) -> dict[str, str]:
    """Map each -rA summary line's nodeid (or ``[n]`` for a skip) to its outcome."""
    return {m.group(2): m.group(1) for m in _SUMMARY_LINE.finditer(output)}


def _expected_outcomes(module: Path) -> dict[str, str]:
    """Every top-level test in ``module`` PASSES, except the freshness gate FAILS.

    A test defined any other way (in a class, say) shows up as an unexpected
    outcome, so the guard fails loudly and must be taught about it.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test")
    ]
    assert _FRESHNESS_GATE in names, f"{_FRESHNESS_GATE} missing from {module}: {names}"
    return {
        f"{_MODULE}::{name}": "FAILED" if name == _FRESHNESS_GATE else "PASSED"
        for name in names
    }


# --- the copy helper's contract ----------------------------------------------


def test_copy_wiki_repo_refuses_an_existing_destination(tmp_path: Path) -> None:
    """A copy never merges into or overwrites an existing tree (fail closed).

    Features: FEAT-REFERENCE-007
    """
    with pytest.raises(FileExistsError):
        copy_wiki_repo(tmp_path)


def _fake_src(src: Path) -> Path:
    """A minimal source repo holding one file in each of the copied dirs."""
    for name in WIKI_REPO_DIRS:
        (src / name).mkdir(parents=True)
        (src / name / "keep.md").write_text(name, encoding="utf-8")
    return src


def test_copy_wiki_repo_copies_files_instead_of_linking_them(tmp_path: Path) -> None:
    """A symlink in the source becomes a plain file, so no write leaks back.

    Features: FEAT-REFERENCE-007
    """
    src = _fake_src(tmp_path / "src")
    first = WIKI_REPO_DIRS[0]
    (src / first / "link.md").symlink_to(src / first / "keep.md")

    dst = copy_wiki_repo(tmp_path / "dst", src=src)

    assert dst == tmp_path / "dst"
    for name in WIKI_REPO_DIRS:
        assert (dst / name / "keep.md").read_text(encoding="utf-8") == name
        assert not (dst / name).is_symlink()
    copied = dst / first / "link.md"
    assert copied.is_file() and not copied.is_symlink()


def test_copy_wiki_repo_skips_a_dangling_symlink(tmp_path: Path) -> None:
    """An editor lock file (a dangling link such as ``.#x.py``) never breaks a copy.

    Features: FEAT-REFERENCE-007
    """
    src = _fake_src(tmp_path / "src")
    first = WIKI_REPO_DIRS[0]
    (src / first / ".#lock.py").symlink_to(src / "does-not-exist")

    dst = copy_wiki_repo(tmp_path / "dst", src=src)

    assert (dst / first / "keep.md").is_file()
    assert not os.path.lexists(dst / first / ".#lock.py")


def test_copy_wiki_repo_defaults_to_the_repo_root_whatever_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ``src``, the copy comes from the repo root, not from the cwd.

    Features: FEAT-REFERENCE-007
    """
    monkeypatch.chdir(tmp_path)

    root = copy_wiki_repo(tmp_path / "repo")

    for name in WIKI_REPO_DIRS:
        assert (root / name).is_dir(), name
    assert (root / "custodex" / "wiki.py").is_file()


def test_wiki_repo_dirs_picks_up_every_source_dir_constant() -> None:
    """A new ``_*_DIR`` render input in custodex.wiki is copied with no edit here.

    Only module-level ``_<NAME>_DIR`` constants and the WIKI_TARGETS keys count;
    other names (``_OTHER``, ``_DIRS``, ``_CACHE_DIR_NAME``, a lowercase
    ``_x_dir``) are not inputs.

    Features: FEAT-REFERENCE-007
    """
    module = SimpleNamespace(
        _CATALOG_DIR=Path("feature-doc") / "catalog",
        _DOCS_DIR=Path("docs"),
        _OTHER=Path("not-an-input"),
        _DIRS=Path("not-an-input-either"),
        _CACHE_DIR_NAME=Path("not-a-dir-constant"),
        _lower_dir=Path("nor-this"),
        WIKI_TARGETS={Path("out/wiki/X.md"): str},
    )

    assert _wiki_repo_dirs(module) == ("docs", "feature-doc", "out")


@pytest.mark.parametrize(
    "bad",
    [
        "docs",
        Path("/abs/docs"),
        Path("."),
        Path("../outside"),
        Path("feature-doc/../../outside"),
    ],
)
def test_wiki_repo_dirs_rejects_a_dir_constant_it_cannot_copy(bad: object) -> None:
    """A ``_*_DIR`` that is not a relative Path inside the repo fails loudly (K8).

    Silently dropping it would leave a render input out of the copy.

    Features: FEAT-REFERENCE-007
    """
    # A valid target too, so dropping the bad constant cannot hide behind the
    # "no render inputs" refusal (whose message would also name _BAD_DIR).
    module = SimpleNamespace(_BAD_DIR=bad, WIKI_TARGETS={Path("out/X.md"): str})

    with pytest.raises(ValueError, match=r"^_BAD_DIR=.* is not a relative Path"):
        _wiki_repo_dirs(module)


def test_wiki_repo_dirs_refuses_a_module_with_no_inputs() -> None:
    """Deriving zero dirs is a failure, never an empty copy (fail closed).

    Features: FEAT-REFERENCE-007
    """
    with pytest.raises(ValueError, match="no render inputs"):
        _wiki_repo_dirs(SimpleNamespace(WIKI_TARGETS={}))


@pytest.mark.parametrize("bad", [Path("/abs/X.md"), Path("../X.md")])
def test_wiki_repo_dirs_rejects_a_target_outside_the_repo(bad: Path) -> None:
    """A WIKI_TARGETS key outside the repo fails loudly (K8).

    Its top dir would otherwise be copied: an absolute key turns the copy into a
    ``copytree`` of ``/`` (across every network mount), and ``..`` escapes the repo.

    Features: FEAT-REFERENCE-007
    """
    module = SimpleNamespace(_OK_DIR=Path("docs"), WIKI_TARGETS={bad: str})

    with pytest.raises(ValueError, match=r"^WIKI_TARGETS\[.* is not a relative Path"):
        _wiki_repo_dirs(module)


def test_wiki_repo_dirs_is_sorted() -> None:
    """The derived dirs come back sorted, whatever the namespace order (K10).

    27 names make it practically impossible for set order to equal sorted order
    by chance, so an unsorted result fails on every run, not just some hash seeds.

    Features: FEAT-REFERENCE-007
    """
    letters = "QWERTYUIOPASDFGHJKLZXCVBNM"
    module = SimpleNamespace(
        **{f"_{c}_DIR": Path(c.lower()) for c in letters},
        WIKI_TARGETS={Path("out/X.md"): str},
    )

    assert _wiki_repo_dirs(module) == tuple(sorted({*letters.lower(), "out"}))


def test_copy_wiki_repo_is_faithful_to_the_real_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every wiki renders byte-identically on the copy and on the real tree.

    An incomplete copy fails quietly otherwise (a missing ``demo/`` yields a matrix
    with every demo missing), so this is what lets the copy-based write tests
    stand in for the real repo. Each side renders from its own cwd, as the
    copy-based tests run (``wiki_repo`` makes the copy the cwd), so an input read
    relative to the cwd instead of the repo root is compared too.

    Features: FEAT-REFERENCE-007
    """
    root = copy_wiki_repo(tmp_path / "repo")
    assert root.resolve() != REPO_ROOT.resolve()
    for rel, render in sorted(WIKI_TARGETS.items(), key=lambda kv: kv[0].as_posix()):
        monkeypatch.chdir(root)
        on_copy = render(root)
        monkeypatch.chdir(REPO_ROOT)
        assert on_copy == render(REPO_ROOT), rel


# --- the snapshot diff the guard relies on -----------------------------------


def _wiki_tree(root: Path) -> list[str]:
    """Write every wiki target under ``root``; return their repo-relative paths."""
    rels = sorted(rel.as_posix() for rel in WIKI_TARGETS)
    for rel in rels:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(rel, encoding="utf-8")
    return rels


def test_snapshot_diff_sees_a_restore_a_created_and_a_removed_file(
    tmp_path: Path,
) -> None:
    """A copy2 restore (same bytes and mtime), a new file and a gone file all show.

    Features: FEAT-REFERENCE-007
    """
    root = tmp_path / "repo"
    restored, removed, *_ = _wiki_tree(root)
    aside = tmp_path / "aside.md"
    shutil.copy2(root / restored, aside)
    before = _snapshot(root)
    _wait_for_ctime_tick(tmp_path / "probe", before)

    (root / restored).write_text("corrupted", encoding="utf-8")
    shutil.copy2(aside, root / restored)
    (root / removed).unlink()
    (root / "feature-doc" / "new.lock").touch()

    assert _touched(before, _snapshot(root)) == sorted(
        [
            restored,
            removed,
            "feature-doc/new.lock",
            "feature-doc/",
            Path(removed).parent.as_posix() + "/",
        ]
    )


def test_snapshot_diff_sees_a_transient_file(tmp_path: Path) -> None:
    """A file created and deleted between snapshots still shows, via its directory.

    Features: FEAT-REFERENCE-007
    """
    root = tmp_path / "repo"
    _wiki_tree(root)
    before = _snapshot(root)
    _wait_for_ctime_tick(tmp_path / "probe", before)

    scratch = root / "feature-doc" / "wiki" / "SCRATCH.md"
    scratch.write_text("x", encoding="utf-8")
    scratch.unlink()

    assert _touched(before, _snapshot(root)) == ["feature-doc/wiki/"]


def test_snapshot_diff_sees_a_transient_entry_at_the_root(tmp_path: Path) -> None:
    """An entry created and removed directly under the root shows via the root itself.

    A directory, not a file: on an NFS basetemp a file write+unlink can leave a
    short-lived ``.nfsXXXX`` silly-rename entry that the snapshot races.

    Features: FEAT-REFERENCE-007
    """
    root = tmp_path / "repo"
    _wiki_tree(root)
    before = _snapshot(root)
    _wait_for_ctime_tick(tmp_path / "probe", before)

    lock = root / "x.lock.d"
    lock.mkdir()
    lock.rmdir()

    assert _touched(before, _snapshot(root)) == ["./"]


def test_snapshot_diff_of_an_untouched_tree_is_empty(tmp_path: Path) -> None:
    """Reading a tree (as the copy helper does) is not a write.

    Features: FEAT-REFERENCE-007
    """
    root = tmp_path / "repo"
    _wiki_tree(root)
    before = _snapshot(root)
    _wait_for_ctime_tick(tmp_path / "probe", before)

    for path in root.rglob("*"):
        if path.is_file():
            path.read_bytes()

    assert _touched(before, _snapshot(root)) == []


# --- the child environment ---------------------------------------------------


def test_child_env_drops_everything_outside_the_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PYTEST_ADDOPTS, colour and coverage settings never reach the child.

    Features: FEAT-REFERENCE-007
    """
    for name in (
        "PYTEST_ADDOPTS",
        "PY_COLORS",
        "FORCE_COLOR",
        "COVERAGE_PROCESS_START",
    ):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = _child_env(tmp_path)

    assert set(env) <= {*_CHILD_ENV_ALLOWLIST, "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}
    assert env["PATH"] == "/usr/bin"
    assert env["PYTHONPATH"] == str(tmp_path)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


# --- the stale-repo guard ----------------------------------------------------


def test_expected_outcomes_requires_the_freshness_gate(tmp_path: Path) -> None:
    """A module without the freshness gate is refused, not guarded with one detector.

    The gate flipping from FAILED to PASSED is the guard's second write detector.
    If the gate were renamed or deleted, the guard would lose it silently.

    Features: FEAT-REFERENCE-007
    """
    module = tmp_path / "m.py"
    module.write_text("def test_a():\n    pass\n", encoding="utf-8")

    with pytest.raises(AssertionError, match=_FRESHNESS_GATE):
        _expected_outcomes(module)


def test_expected_outcomes_maps_the_gate_to_failed_and_the_rest_to_passed(
    tmp_path: Path,
) -> None:
    """Top-level tests PASS, the freshness gate FAILS; helpers and classes are skipped.

    Features: FEAT-REFERENCE-007
    """
    module = tmp_path / "m.py"
    module.write_text(
        "def test_a():\n    pass\n"
        f"def {_FRESHNESS_GATE}():\n    pass\n"
        "def helper():\n    pass\n"
        "class TestK:\n    def test_m(self):\n        pass\n",
        encoding="utf-8",
    )

    assert _expected_outcomes(module) == {
        f"{_MODULE}::test_a": "PASSED",
        f"{_MODULE}::{_FRESHNESS_GATE}": "FAILED",
    }


def test_wiki_cli_tests_leave_a_stale_repo_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``test_wiki_cli.py`` never writes the repo it runs in, whatever its state.

    The child runs the module against a scratch repo whose wikis are stale on
    purpose. Expected: nothing under that repo changes (no file or directory is
    written, created or removed); every test PASSES except the freshness gate,
    which FAILS because the wikis are stale. A write-mode test drifting back to
    the repo root regenerates the wikis, so the snapshot changes and the gate
    flips to PASSED. A skipped or deselected test shows as a wrong outcome, and a
    run that never got going (a usage error, nothing collected) prints no summary
    lines at all, so the exact-outcomes check is the run check too. The parent
    environment is made hostile first, to prove none of it reaches the child.

    Features: FEAT-REFERENCE-007
    """
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ff")
    monkeypatch.setenv("PY_COLORS", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    root = _stale_repo(tmp_path / "repo")
    before = _snapshot(root)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            _MODULE,
            "-rA",
            "-p",
            "no:cacheprovider",
            # Tidiness, not detection: the child's tmp dirs land under this test's
            # tmp_path (outside the snapshotted root), instead of adding and
            # rotating numbered dirs in the shared pytest-of-<user> basetemp.
            f"--basetemp={tmp_path / 'child-tmp'}",
        ],
        cwd=root,
        env=_child_env(root),
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_S,
        check=False,
    )
    output = proc.stdout + proc.stderr

    touched = _touched(before, _snapshot(root))
    assert touched == [], f"{_MODULE} wrote the repo it ran in: {touched}\n{output}"
    assert _outcomes(output) == _expected_outcomes(root / _MODULE), output


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
