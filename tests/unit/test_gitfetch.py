"""GIT-00 — clone-on-demand orchestration (pure + fake-cloner unit tests).

These exercise :mod:`code_doc_monitor.gitfetch` WITHOUT a real git or network:

* ``_build_clone_argv`` is a pure function — the security-critical guarantee is
  asserted here (the token NEVER lands in argv; only the provider *username* is
  injected into an https URL's userinfo, never the token).
* ``cloned_repo`` orchestration + teardown is proven with an INJECTED fake
  ``_Cloner`` (K4) so no subprocess runs: teardown happens on success AND on a
  cloner error, and the yielded path is the dest the cloner was handed.

The REAL ``git clone`` (over a local ``file://`` repo, no network) lives in
``tests/integration/test_gitfetch.py``.

Features: FEAT-CONFIGV2-012, FEAT-GITSYNC-001
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.errors import SyncError
from code_doc_monitor.gitfetch import (
    RemoteSpec,
    _build_clone_argv,
    _scrub,
    cloned_repo,
)

# --------------------------------------------------------------------------- #
# _scrub — defensive token redaction from any surfaced error text (K8).
# --------------------------------------------------------------------------- #


def test_scrub_redacts_secret_when_present() -> None:
    assert _scrub("auth for tok123 failed", "tok123") == "auth for *** failed"


def test_scrub_is_noop_when_secret_absent_or_none() -> None:
    assert _scrub("plain error", "tok123") == "plain error"
    assert _scrub("plain error", None) == "plain error"


# --------------------------------------------------------------------------- #
# _build_clone_argv — pure; the token-never-in-argv guarantee.
# --------------------------------------------------------------------------- #


def test_build_clone_argv_is_shallow_single_branch() -> None:
    spec = RemoteSpec(remote_url="file:///srv/repo", provider="github")
    argv = _build_clone_argv(spec, Path("/tmp/dest"), secret=None)
    assert argv[0] == "clone"
    assert "--depth=1" in argv
    assert "--single-branch" in argv
    assert argv[argv.index("--branch") + 1] == "main"
    assert "file:///srv/repo" in argv
    assert str(Path("/tmp/dest")) == argv[-1]


def test_build_clone_argv_injects_github_username_never_token() -> None:
    spec = RemoteSpec(remote_url="https://github.com/owner/repo.git", provider="github")
    argv = _build_clone_argv(spec, Path("/tmp/d"), secret="ghp_SUPERSECRET")
    joined = " ".join(argv)
    assert "ghp_SUPERSECRET" not in joined  # the token is NEVER in argv (K8 design)
    assert "https://x-access-token@github.com/owner/repo.git" in argv


def test_build_clone_argv_injects_gitlab_username_never_token() -> None:
    spec = RemoteSpec(remote_url="https://gitlab.com/group/proj.git", provider="gitlab")
    argv = _build_clone_argv(spec, Path("/tmp/d"), secret="glpat-SECRET")
    joined = " ".join(argv)
    assert "glpat-SECRET" not in joined
    assert "https://oauth2@gitlab.com/group/proj.git" in argv


def test_build_clone_argv_no_secret_leaves_url_plain() -> None:
    spec = RemoteSpec(remote_url="https://github.com/owner/repo.git", provider="github")
    argv = _build_clone_argv(spec, Path("/tmp/d"), secret=None)
    assert "https://github.com/owner/repo.git" in argv
    assert not any("@" in part for part in argv)


def test_build_clone_argv_secret_on_non_https_url_stays_plain() -> None:
    # A file:// (or ssh) URL never carries an https userinfo, even with a secret.
    spec = RemoteSpec(remote_url="file:///srv/repo", provider="github")
    argv = _build_clone_argv(spec, Path("/tmp/d"), secret="tok")
    assert "file:///srv/repo" in argv
    assert "tok" not in " ".join(argv)


def test_build_clone_argv_honors_default_branch() -> None:
    spec = RemoteSpec(
        remote_url="file:///srv/repo", provider="gitlab", default_branch="trunk"
    )
    argv = _build_clone_argv(spec, Path("/tmp/d"), secret=None)
    assert argv[argv.index("--branch") + 1] == "trunk"


# --------------------------------------------------------------------------- #
# cloned_repo — orchestration + teardown via an INJECTED fake cloner (K1/K4).
# --------------------------------------------------------------------------- #


class _FakeCloner:
    """Records its calls; optionally materializes a dir or raises (no subprocess)."""

    def __init__(self, *, boom: bool = False) -> None:
        self.calls: list[tuple[RemoteSpec, str | None, Path]] = []
        self._boom = boom

    def clone(self, spec: RemoteSpec, secret: str | None, dest: Path) -> None:
        self.calls.append((spec, secret, dest))
        if self._boom:
            raise SyncError("clone blew up")
        dest.mkdir(parents=True)  # stand in for a checked-out tree


_SPEC = RemoteSpec(remote_url="file:///srv/repo", provider="github")


def test_cloned_repo_yields_cloner_dest_and_tears_down_on_success() -> None:
    fake = _FakeCloner()
    captured: dict[str, Path] = {}
    with cloned_repo(_SPEC, None, cloner=fake) as tree:
        assert tree.is_dir()
        captured["tree"] = tree
        # the cloner was handed the SAME dest the context manager yields.
        assert fake.calls == [(_SPEC, None, tree)]
    # the whole throwaway temp dir is gone after the block (K1).
    assert not captured["tree"].exists()
    assert not captured["tree"].parent.exists()


def test_cloned_repo_tears_down_on_cloner_error() -> None:
    fake = _FakeCloner(boom=True)
    with (
        pytest.raises(SyncError, match="clone blew up"),
        cloned_repo(_SPEC, "tok", cloner=fake),
    ):
        pass  # pragma: no cover — never reached (clone raised)
    # the cloner recorded its dest before raising; assert its temp parent is gone.
    dest = fake.calls[0][2]
    assert not dest.parent.exists()


def test_cloned_repo_passes_secret_through_to_cloner() -> None:
    fake = _FakeCloner()
    with cloned_repo(_SPEC, "shh", cloner=fake):
        pass
    assert fake.calls[0][1] == "shh"
