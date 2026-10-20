"""DEPLOY-MANAGED: the runbook's shell blocks do what the runbook says, run for real.

The content tests (``tests/unit/test_deploy_runbook.py``) read the blocks word by
word. These run them in ``bash`` instead, so a block that reads right but behaves
wrong still fails:

* the TL;DR writes the secrets every compose interpolation needs into ``.env``
  ONCE, private to the owner, and a second run keeps the same values (re-running
  the quick start must not rotate a database password or a KEK); a secret that
  cannot be generated leaves no ``.env`` and starts nothing, and the repo's
  ignore files keep ``.env`` out of git and out of the Docker build context;
* the upgrade block, run against a throwaway release repo with real ``git`` and
  the real ``cdx settings``, moves HEAD to the tag and carries a local edit of
  the tracked settings file across; a conflicting edit stops the block before
  the console build, and the recovery the prose gives lets it finish; a failed
  step stops every step after it.

Only the commands that would touch the network or the host are stubbed on PATH
(``openssl``, ``docker``, ``pip``, ``npm``); each stub logs its working directory
and arguments. Everything happens under ``tmp_path``: no network, no clock in an
assertion (K4, K10).

Features: FEAT-QUALITY-011
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from custodex.settings import DEFAULT_SETTINGS_PATH, Settings, load_settings
from tests._repo import REPO_ROOT
from tests.unit.test_deploy_runbook import (
    _compose_names,
    _doc,
    _fenced,
    _one_line,
    _section,
)

_PLACEHOLDER = "vX.Y.Z"
_OLD, _NEW = "v0.1.0", "v0.2.0"


def _tool(name: str) -> str:
    found = shutil.which(name)
    assert found, f"{name} is required to run the runbook's shell blocks"
    return found


def _stub(bin_dir: Path, name: str, body: str = "") -> None:
    path = bin_dir / name
    path.write_text(
        f'#!/bin/sh\necho "{name}|$PWD|$*" >> "$STUB_LOG"\n{body}\n', encoding="utf-8"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _env(tmp_path: Path, bin_dir: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(home),
        "LC_ALL": "C",
        "STUB_LOG": str(tmp_path / "stub.log"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "probe",
        "GIT_AUTHOR_EMAIL": "probe@example.invalid",
        "GIT_COMMITTER_NAME": "probe",
        "GIT_COMMITTER_EMAIL": "probe@example.invalid",
        "GIT_TERMINAL_PROMPT": "0",
    }
    if "PYTHONPATH" in os.environ:
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    return env


def _log(tmp_path: Path) -> list[tuple[str, str, str]]:
    path = tmp_path / "stub.log"
    if not path.exists():
        return []
    rows = [ln.split("|", 2) for ln in path.read_text("utf-8").splitlines()]
    return [(r[0], r[1], r[2]) for r in rows]


def _bash(block: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_tool("bash"), "-c", block],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


# ── the TL;DR's secrets ──────────────────────────────────────────────────────


def test_the_tldr_writes_the_secrets_once_and_keeps_them(tmp_path: Path) -> None:
    blocks = _fenced(_section(_doc(), "TL;DR"), "bash")
    assert len(blocks) == 1
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "openssl.count"
    # A fresh value on every call, so a regenerated secret cannot look reused.
    _stub(
        bin_dir,
        "openssl",
        f'n=$(( $(cat "{counter}" 2>/dev/null || echo 0) + 1 ))\n'
        f'echo "$n" > "{counter}"\necho "generated-$n"',
    )
    _stub(bin_dir, "docker")
    env = _env(tmp_path, bin_dir)
    deploy = tmp_path / "deploy"
    deploy.mkdir()

    first = _bash(blocks[0], deploy, env)
    assert first.returncode == 0, first.stderr
    dotenv = deploy / ".env"
    written = dotenv.read_bytes()
    pairs = dict(
        ln.split("=", 1) for ln in written.decode("utf-8").splitlines() if ln.strip()
    )
    assert set(pairs) == _compose_names(), sorted(pairs)
    assert all(pairs.values()) and len(set(pairs.values())) == len(pairs), pairs
    assert stat.S_IMODE(dotenv.stat().st_mode) & 0o077 == 0, oct(dotenv.stat().st_mode)

    second = _bash(blocks[0], deploy, env)
    assert second.returncode == 0, second.stderr
    assert dotenv.read_bytes() == written, "re-running the TL;DR rotated a secret"
    assert counter.read_text("utf-8").strip() == str(len(pairs))
    ups = [args for tool, _cwd, args in _log(tmp_path) if tool == "docker"]
    assert ups == ["compose up --build"] * 2, ups
    assert "generate" in _one_line(_section(_doc(), "TL;DR")).lower()


def _openssl_failing_on(bin_dir: Path, counter: Path, fails_on: int) -> None:
    """An ``openssl`` that works except on call ``fails_on``, where it behaves
    like a missing command (no output, status 127)."""
    _stub(
        bin_dir,
        "openssl",
        f'n=$(( $(cat "{counter}" 2>/dev/null || echo 0) + 1 ))\n'
        f'echo "$n" > "{counter}"\n'
        f'if [ "$n" -eq {fails_on} ]; then\n'
        '  echo "openssl: not found" >&2; exit 127\nfi\n'
        'echo "generated-$n"',
    )


@pytest.mark.parametrize("fails_on", [1, 3])
def test_a_failed_secret_generation_writes_no_env_and_starts_nothing(
    tmp_path: Path, fails_on: int
) -> None:
    """A secret that cannot be generated must not leave a ``.env`` behind: the
    TL;DR keeps an existing ``.env`` forever, so an empty or partial one would
    never be repaired. The block fails, starts nothing, and a re-run once the
    cause is fixed generates the file (the recovery the prose states)."""
    blocks = _fenced(_section(_doc(), "TL;DR"), "bash")
    assert len(blocks) == 1
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "openssl.count"
    _openssl_failing_on(bin_dir, counter, fails_on)
    _stub(bin_dir, "docker")
    env = _env(tmp_path, bin_dir)
    deploy = tmp_path / "deploy"
    deploy.mkdir()

    failed = _bash(blocks[0], deploy, env)
    assert failed.returncode != 0, "the TL;DR succeeded although a secret failed"
    assert sorted(p.name for p in deploy.iterdir()) == [], "a secrets file was left"
    assert [t for t, _c, _a in _log(tmp_path) if t == "docker"] == []

    prose = _one_line(_section(_doc(), "TL;DR"))
    assert re.search(r"no `\.env` is written[^.]*run it again", prose), prose
    counter.unlink()
    _openssl_failing_on(bin_dir, counter, 0)  # the cause is fixed
    again = _bash(blocks[0], deploy, env)
    assert again.returncode == 0, again.stderr
    pairs = dict(
        ln.split("=", 1)
        for ln in (deploy / ".env").read_text("utf-8").splitlines()
        if ln.strip()
    )
    assert set(pairs) == _compose_names() and all(pairs.values()), pairs
    assert [t for t, _c, _a in _log(tmp_path)].count("docker") == 1


def _secret_files(block: str) -> set[str]:
    """Every ``.env``-family file name the TL;DR block writes or moves."""
    return set(re.findall(r"(?<![\w$/])\.env(?:\.\w+)?(?![\w/])", block))


def test_the_secrets_files_are_ignored_by_git_and_the_docker_build(
    tmp_path: Path,
) -> None:
    """The TL;DR writes the secrets inside the checkout, so ``git add -A`` must
    not stage them and the Docker build context must not carry them: "never
    commit it" is enforced by the repo's ignore files, not by prose alone."""
    names = _secret_files(_fenced(_section(_doc(), "TL;DR"), "bash")[0])
    assert ".env" in names, names
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = _env(tmp_path, bin_dir)  # HOME isolated: no global excludes file
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, env, "init", "-q")
    shutil.copy2(REPO_ROOT / ".gitignore", repo / ".gitignore")
    for name in sorted(names):
        (repo / name).write_text("SECRET=probe\n", encoding="utf-8")
    _git(repo, env, "add", "-A")
    staged = set(_git(repo, env, "ls-files").splitlines())
    assert staged == {".gitignore"}, f"git add -A staged {sorted(staged)}"

    patterns = [
        ln.strip().lstrip("/")
        for ln in (REPO_ROOT / ".dockerignore").read_text("utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", "!"))
    ]
    for name in sorted(names):
        assert any(fnmatch.fnmatchcase(name, p) for p in patterns), (
            f"{name} enters the Docker build context"
        )


# ── the upgrade block against a throwaway release repo ───────────────────────


def _git(cwd: Path, env: dict[str, str], *args: str) -> str:
    out = subprocess.run(
        [_tool("git"), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, (args, out.stderr)
    return out.stdout.strip()


def _replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new)


class _Release:
    """An origin with two release tags that change a settings default, and a
    deployment cloned at the older tag (the hub's checkout)."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for tool in ("pip", "npm"):
            _stub(self.bin, tool)
        # The real `cdx settings`, logged like a stub, run by this interpreter.
        _stub(
            self.bin,
            "cdx",
            f'exec "{sys.executable}" -c '
            '"import sys; from custodex.cli import app; '
            'sys.exit(app(prog_name=\'cdx\'))" "$@"',
        )
        self.env = _env(tmp_path, self.bin)
        self.port = Settings().server.port
        self.base = (REPO_ROOT / DEFAULT_SETTINGS_PATH).read_text("utf-8")
        origin = tmp_path / "origin"
        (origin / DEFAULT_SETTINGS_PATH).parent.mkdir(parents=True)
        (origin / "frontend").mkdir()
        (origin / "frontend" / "package.json").write_text("{}\n", encoding="utf-8")
        _git(origin, self.env, "init", "-q")
        self._commit(origin, self.base, _OLD)
        self.released = self._port_line(self.base, self.port + 1)
        self._commit(origin, self.released, _NEW)
        self.hub = tmp_path / "hub"
        _git(tmp_path, self.env, "clone", "-q", str(origin), str(self.hub))
        _git(self.hub, self.env, "checkout", "-q", _OLD)
        self.settings = self.hub / DEFAULT_SETTINGS_PATH

    def _port_line(self, text: str, port: int) -> str:
        return _replace_once(text, f"port: {self.port}\n", f"port: {port}\n")

    def _commit(self, origin: Path, settings: str, tag: str) -> None:
        (origin / DEFAULT_SETTINGS_PATH).write_text(settings, encoding="utf-8")
        _git(origin, self.env, "add", "-A")
        _git(origin, self.env, "commit", "-q", "-m", tag)
        _git(origin, self.env, "tag", tag)

    def upgrade(self, tag: str) -> subprocess.CompletedProcess:
        blocks = _fenced(_section(_doc(), "Upgrading"), "bash")
        assert len(blocks) == 1 and _PLACEHOLDER in blocks[0]
        return _bash(blocks[0].replace(_PLACEHOLDER, tag), self.hub, self.env)

    def head_is(self, tag: str) -> bool:
        head = _git(self.hub, self.env, "rev-parse", "HEAD")
        return head == _git(self.hub, self.env, "rev-parse", f"{tag}^{{commit}}")

    def ran(self) -> list[tuple[str, str, str]]:
        return _log(self.tmp)


def test_the_upgrade_carries_a_local_settings_edit_to_the_release(
    tmp_path: Path,
) -> None:
    rel = _Release(tmp_path)
    # An operator edit far from the line the release changes (no conflict).
    edited = _replace_once(
        rel.base, "requests_per_minute: null\n", "requests_per_minute: 120\n"
    )
    rel.settings.write_text(edited, encoding="utf-8")

    done = rel.upgrade(_NEW)
    assert done.returncode == 0, done.stderr
    assert rel.head_is(_NEW), "the upgrade did not move HEAD to the release tag"
    loaded = load_settings(rel.settings)
    assert loaded.server.port == rel.port + 1, "the release's new default was lost"
    assert loaded.server.rate_limit.requests_per_minute == 120, "the edit was lost"
    tools = [tool for tool, _cwd, _args in rel.ran()]
    assert tools == ["pip", "cdx", "npm", "npm"], rel.ran()
    npm_dirs = {Path(cwd) for tool, cwd, _a in rel.ran() if tool == "npm"}
    assert npm_dirs == {(rel.hub / "frontend").resolve()}, npm_dirs


def test_a_conflicting_edit_stops_the_upgrade_and_the_stated_recovery_finishes_it(
    tmp_path: Path,
) -> None:
    rel = _Release(tmp_path)
    mine = rel.port + 2
    rel.settings.write_text(rel._port_line(rel.base, mine), encoding="utf-8")

    stopped = rel.upgrade(_NEW)
    assert stopped.returncode != 0
    assert "npm" not in [tool for tool, _c, _a in rel.ran()], rel.ran()

    prose = _one_line(_section(_doc(), "Upgrading"))
    resets = re.findall(r"`(git reset [^`]+)`", prose)
    assert len(resets) == 1, resets
    assert str(DEFAULT_SETTINGS_PATH.as_posix()) in resets[0]
    # "edit the file to keep the value you want": the release's file, my port.
    rel.settings.write_text(rel._port_line(rel.base, mine), encoding="utf-8")
    fixed = _bash(resets[0], rel.hub, rel.env)
    assert fixed.returncode == 0, fixed.stderr

    again = rel.upgrade(_NEW)
    assert again.returncode == 0, again.stderr
    assert rel.head_is(_NEW)
    assert load_settings(rel.settings).server.port == mine
    assert _git(rel.hub, rel.env, "ls-files", "--unmerged") == ""
    assert [t for t, _c, _a in rel.ran()].count("npm") == 2, rel.ran()


def test_a_failed_step_stops_every_step_after_it(tmp_path: Path) -> None:
    rel = _Release(tmp_path)
    failed = rel.upgrade("v9.9.9-probe-not-a-tag")
    assert failed.returncode != 0
    assert rel.ran() == [], "a step ran after the checkout failed"
    assert rel.head_is(_OLD)
    assert re.search(r"Each step runs only if the one before it succeeded", _doc())


@pytest.mark.parametrize("tool", ["bash", "git"])
def test_the_shell_tools_these_checks_run_are_present(tool: str) -> None:
    assert _tool(tool)
