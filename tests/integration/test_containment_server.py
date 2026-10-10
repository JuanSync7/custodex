"""X-CONTAIN — the server's docs-PR route on a DOTDOT-spelled doc path.

The route heals a CLONED, untrusted repo and opens a PR with the healed files.
A committed symlink ``link -> <host>/hub/sub`` plus a doc spelled
``link/../token.txt`` made the raw ``root / path`` join resolve PHYSICALLY to
``<host>/hub/token.txt`` — a host file the server can read. The heal,
``sync_pr`` and the PR plan now name the doc ``doc_path(root, path)`` = the
clone's own ``token.txt``, so the PR carries only the clone's healed doc and
the host secret never leaves.

This slice closes the DOTDOT spelling only. A committed symlink the path
traverses WITHOUT ``..`` (``link/token.txt``, ``link -> <host>/hub``) still
reaches the host file until CI-TRUST gates the clone's doc paths on
:func:`custodex.config.resolve_within`; the strict xfail below pins that gap
so it flips loudly when CI-TRUST lands.

Features: FEAT-CONFIGV2-019
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="the [server] extra is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from custodex.registry import RegistrationPayload  # noqa: E402
from custodex.server import InMemoryStore, create_app  # noqa: E402
from custodex.sinks import RepoIdentity  # noqa: E402

_NOW = "2026-10-10T00:00:00Z"
_REPO = "acme/contain"
_SECRET = "HUB_KEK=super-secret-key"

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: cloned
generated-by: cdx
updated: "2026-10-10"
---
root: "../.."
version: "2.0.0"
apply_default: false
backend: {kind: mock}
central: {sink: none}
units:
  - file: core.yaml
ignore: ignore.yaml
"""
_CORE_UNIT_YAML_TMPL = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "Core"
owner: eng-platform
created: "2026-10-10"
updated: "2026-10-10"
---
dir-covered:
  - pkg
source-files-format:
  - ".py"
documents:
  - id: api-guide
    path: {path}
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: pkg/calc.py
        symbols: [add]
"""
_IGNORE_YAML = """\
---
cdmon-config-version: "2.0.0"
source: "manual"
updated: "2026-10-10"
---
gitignore: false
patterns: []
"""
_CALC = 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n'
_DOC_STUB = (
    "# API guide\n\nProse.\n\n<!-- CDM:BEGIN symbols -->\nPLACEHOLDER\n"
    "<!-- CDM:END symbols -->\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    )


def _build(
    tmp_path: Path, *, doc: str = "link/../token.txt", link_to: str = "sub"
) -> Path:
    """A cloneable origin whose ``link`` points into a host-side ``hub``."""
    hub = tmp_path / "hub"
    (hub / "sub").mkdir(parents=True)
    secret = hub / "token.txt"
    secret.write_text(_SECRET + "\n", encoding="utf-8")
    secret.chmod(0o400)

    repo = tmp_path / "origin"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(_INDEX_YAML, encoding="utf-8")
    (cfg / "core.yaml").write_text(
        _CORE_UNIT_YAML_TMPL.replace("{path}", doc), encoding="utf-8"
    )
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "calc.py").write_text(_CALC, encoding="utf-8")
    (repo / "token.txt").write_text(_DOC_STUB, encoding="utf-8")
    (repo / "link").symlink_to(hub / link_to, target_is_directory=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


class _FakeTransport:
    def __init__(self) -> None:
        self.plans: list[Any] = []

    def submit(self, plan: Any) -> dict:
        self.plans.append(plan)
        return {"html_url": "https://provider/pr/1", "number": 1}


def _client(fake: _FakeTransport, origin: Path) -> TestClient:
    client = TestClient(
        create_app(
            InMemoryStore(),
            clock=lambda: _NOW,
            pr_transport_factory=lambda provider, url, token: fake,
        )
    )
    payload = RegistrationPayload(
        repo=RepoIdentity(
            repo_id=_REPO,
            provider="github",
            remote_url=f"file://{origin}",
            default_branch="main",
        ),
        default_branch="main",
    )
    resp = client.post("/repos", json=payload.model_dump(mode="json"))
    assert resp.status_code == 201, resp.text
    return client


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry", "real"])
def test_docs_pr_commits_only_the_clones_own_doc(tmp_path: Path, dry_run: bool) -> None:
    # Feature: FEAT-CONFIGV2-019
    origin = _build(tmp_path)
    fake = _FakeTransport()
    client = _client(fake, origin)

    resp = client.post(f"/repos/{_REPO}/docs-pr", json={"dry_run": dry_run})
    assert resp.status_code == 201, resp.text
    assert _SECRET not in resp.text
    body = resp.json()
    assert body["opened"] is True

    if dry_run:
        assert fake.plans == []
        files = [tuple(f) for f in body["response"]["files"]]
    else:
        (plan,) = fake.plans
        files = list(plan.files)
    assert [path for path, _ in files] == ["token.txt"]
    (healed,) = (text for _, text in files)
    assert "Prose." in healed and "add" in healed and "PLACEHOLDER" not in healed
    assert _SECRET not in repr(fake.plans)
    assert (tmp_path / "hub" / "token.txt").read_text(encoding="utf-8") == (
        _SECRET + "\n"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "known gap, not closed by X-CONTAIN: a committed symlink traversed "
        "WITHOUT '..' still reaches a host file; CI-TRUST gates the clone's doc "
        "paths on resolve_within"
    ),
)
@pytest.mark.parametrize("dry_run", [True, False], ids=["dry", "real"])
def test_docs_pr_never_follows_a_committed_symlink_without_dotdot(
    tmp_path: Path, dry_run: bool
) -> None:
    """``link/token.txt`` with ``link -> <host>/hub``: no ``..`` to normalise,
    so ``doc_path`` names the hub file. The route must neither ship nor rewrite
    it. Today it does both (the xfail); CI-TRUST flips this to a pass."""
    # Feature: FEAT-CONFIGV2-019
    origin = _build(tmp_path, doc="link/token.txt", link_to=".")
    hub_file = tmp_path / "hub" / "token.txt"
    hub_file.chmod(0o600)
    hub_file.write_text(_DOC_STUB + "\n" + _SECRET + "\n", encoding="utf-8")
    hub_before = hub_file.read_bytes()
    fake = _FakeTransport()
    client = _client(fake, origin)

    resp = client.post(f"/repos/{_REPO}/docs-pr", json={"dry_run": dry_run})
    assert _SECRET not in resp.text
    assert _SECRET not in repr(fake.plans)
    assert hub_file.read_bytes() == hub_before
