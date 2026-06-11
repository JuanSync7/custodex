"""GIT-04 — server wiring for clone-on-demand sync + the docs-PR route (offline).

Drives the two new EPIC-GIT routes through a FastAPI ``TestClient`` over BOTH
Store backends (parity), with NO network:

* ``POST /repos/{id}/sync`` for a repo with NO ``local_path`` but a
  ``provider``+``remote_url``: the server clones it on demand (a REAL ``file://``
  clone — EDR-safe) and surfaces its documents + coverage.
* ``POST /repos/{id}/docs-pr``: clone → heal (``syncpr.sync_pr``) → plan → open via
  an INJECTED ``pr_transport_factory`` (a ``file://`` URL can't build a real PR
  transport, so the factory is the K4 seam), incl. a ``dry_run`` that never calls it.

Plus: the SSRF host allowlist (bad scheme/host → 400), the sealed-credential
seal-at-register / open-at-sync round-trip (token flows to the cloner; missing KEK
→ 500), and the auth matrix (401/403 like the other writes).

Features: FEAT-SERVER-003, FEAT-SERVER-006, FEAT-CONFIGV2-012
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="the [server] extra is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.registry import RegistrationPayload  # noqa: E402
from code_doc_monitor.server import InMemoryStore, create_app  # noqa: E402
from code_doc_monitor.sinks import RepoIdentity  # noqa: E402

_NOW = "2026-06-10T00:00:00Z"
_REPO = "acme/widget"
_KEY_B64 = base64.b64encode(bytes(range(32))).decode("ascii")

# --- a real dir-layout git repo (mirrors test_configsync / test_gitfetch) ---

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: cloned
generated-by: cdmon
updated: "2026-06-10"
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
_CORE_UNIT_YAML = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "Core coverage"
owner: eng-platform
created: "2026-06-10"
updated: "2026-06-10"
---
dir-covered:
  - pkg
source-files-format:
  - ".py"
documents:
  - id: api-guide
    path: docs/api.md
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
updated: "2026-06-10"
---
gitignore: false
patterns:
  - "*.log"
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


def _seed_docs(config_dir: Path) -> None:
    from typer.testing import CliRunner

    from code_doc_monitor.cli import app

    r = CliRunner().invoke(app, ["monitor", "--config", str(config_dir), "--apply"])
    assert r.exit_code == 0, r.output


def _build_repo(tmp_path: Path, *, heal: bool = True) -> Path:
    """A real dir-layout git repo on ``main``. ``heal=False`` commits the drifted
    PLACEHOLDER doc (so a later ``sync_pr`` on a clone produces a non-empty patch)."""
    repo = tmp_path / "origin"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(_INDEX_YAML, encoding="utf-8")
    (cfg / "core.yaml").write_text(_CORE_UNIT_YAML, encoding="utf-8")
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "calc.py").write_text(_CALC, encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "api.md").write_text(_DOC_STUB, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    if heal:
        _seed_docs(cfg)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


def _file_url(repo: Path) -> str:
    return f"file://{repo}"


@pytest.fixture(params=["memory", "sql"])
def store(request: pytest.FixtureRequest) -> Any:
    if request.param == "memory":
        return InMemoryStore()
    pytest.importorskip("sqlalchemy", reason="the [server] extra is not installed")
    from code_doc_monitor.server.db import SqlStore, create_all, engine_from_url

    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


def _register(
    client: TestClient,
    *,
    remote_url: str | None = None,
    provider: str | None = None,
    provider_kind: str | None = None,
    local_path: str | None = None,
    auth_token: str | None = None,
    provider_secret: str | None = None,
) -> None:
    payload = RegistrationPayload(
        repo=RepoIdentity(
            repo_id=_REPO,
            provider=provider,
            remote_url=remote_url,
            provider_kind=provider_kind,
            local_path=local_path,
            default_branch="main",
        ),
        default_branch="main",
        auth_token=auth_token,
        provider_secret=provider_secret,
    )
    resp = client.post("/repos", json=payload.model_dump(mode="json"))
    assert resp.status_code == 201, resp.text


class _FakeTransport:
    """Records the plan instead of opening a real PR (K4)."""

    def __init__(self) -> None:
        self.plans: list[Any] = []

    def submit(self, plan: Any) -> dict:
        self.plans.append(plan)
        return {"html_url": "https://provider/pr/1", "number": 1}


# --------------------------------------------------------------------------- #
# Remote POST /sync — clone-on-demand over a REAL file:// repo (no network).
# --------------------------------------------------------------------------- #


def test_remote_sync_clones_and_surfaces_docs_and_coverage(
    store: Any, tmp_path: Path
) -> None:
    origin = _build_repo(tmp_path)  # clean (healed) → fully_synced
    client = TestClient(create_app(store, clock=lambda: _NOW))
    _register(client, remote_url=_file_url(origin), provider="github")

    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["fully_synced"] is True
    assert run["document_count"] == 1
    assert run["code_ref_count"] == 1

    # the just-synced clone's documents + coverage are persisted (surfaced to the UI).
    docs = client.get(f"/repos/{_REPO}/documents", params={"sync_kind": "local"}).json()
    assert [d["document"]["doc_id"] for d in docs] == ["api-guide"]
    cov = client.get(f"/repos/{_REPO}/coverage").json()
    assert len(cov) == 1 and cov[0]["captured_at"] == _NOW


def test_sync_without_local_path_or_remote_is_still_400(
    store: Any, tmp_path: Path
) -> None:
    client = TestClient(create_app(store, clock=lambda: _NOW))
    _register(client)  # neither local_path nor provider/remote_url
    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    assert resp.status_code == 400
    assert "local_path" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# SSRF host allowlist.
# --------------------------------------------------------------------------- #


def test_sync_rejects_non_allowlisted_https_host(store: Any) -> None:
    client = TestClient(create_app(store, clock=lambda: _NOW))
    _register(client, remote_url="https://evil.internal/x/y.git", provider="github")
    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    assert resp.status_code == 400
    assert "allowlist" in resp.json()["detail"]


def test_sync_rejects_non_https_scheme(store: Any) -> None:
    client = TestClient(create_app(store, clock=lambda: _NOW))
    _register(client, remote_url="ftp://github.com/x/y", provider="github")
    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    assert resp.status_code == 400
    assert "https" in resp.json()["detail"]


def test_allowlisted_self_hosted_host_passes(
    store: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An env-allowlisted host is accepted; we still clone a real file:// repo, but
    # prove the https-host check itself does not reject an allowlisted name.
    from code_doc_monitor.server import app as app_mod

    monkeypatch.setenv("CDMON_ALLOWED_GIT_HOSTS", "git.corp")
    assert "git.corp" in app_mod._allowed_git_hosts()
    app_mod._check_remote_allowed("https://git.corp/team/proj.git")  # no raise


# --------------------------------------------------------------------------- #
# Sealed-credential round-trip: seal at register, open at sync, flows to cloner.
# --------------------------------------------------------------------------- #


def test_provider_secret_sealed_then_opened_and_passed_to_cloner(
    store: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CDMON_SECRET_KEY", _KEY_B64)
    origin = _build_repo(tmp_path)
    seen: dict[str, str | None] = {}

    class RecordingCloner:
        def clone(self, spec: Any, secret: str | None, dest: Path) -> None:
            seen["secret"] = secret
            subprocess.run(
                ["git", "clone", "-q", _file_url(origin), str(dest)], check=True
            )

    client = TestClient(create_app(store, clock=lambda: _NOW, cloner=RecordingCloner()))
    _register(
        client,
        remote_url="https://github.com/acme/widget.git",
        provider="github",
        provider_secret="ghp_REALTOKEN",
    )
    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    assert resp.status_code == 201, resp.text
    # the route opened the sealed secret and handed the PLAINTEXT to the cloner.
    assert seen["secret"] == "ghp_REALTOKEN"


def test_register_with_secret_but_no_kek_is_500(
    store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CDMON_SECRET_KEY", raising=False)
    client = TestClient(create_app(store, clock=lambda: _NOW))
    payload = RegistrationPayload(
        repo=RepoIdentity(
            repo_id=_REPO, provider="github", remote_url="https://github.com/a/b.git"
        ),
        provider_secret="ghp_x",
    )
    resp = client.post("/repos", json=payload.model_dump(mode="json"))
    assert resp.status_code == 500
    assert "seal" in resp.json()["detail"]


def test_sync_with_sealed_secret_but_missing_kek_is_500(
    store: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seal at register with a KEK, then drop the KEK so open-at-sync fails → 500.
    monkeypatch.setenv("CDMON_SECRET_KEY", _KEY_B64)
    client = TestClient(create_app(store, clock=lambda: _NOW))
    _register(
        client,
        remote_url="https://github.com/a/b.git",
        provider="github",
        provider_secret="ghp_x",
    )
    monkeypatch.delenv("CDMON_SECRET_KEY", raising=False)
    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    assert resp.status_code == 500
    assert "provider secret" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# POST /docs-pr — clone, heal, open via the injected transport factory.
# --------------------------------------------------------------------------- #


def test_docs_pr_clones_heals_and_opens_via_transport(
    store: Any, tmp_path: Path
) -> None:
    origin = _build_repo(tmp_path, heal=False)  # drifted → heal yields a patch
    fake = _FakeTransport()
    client = TestClient(
        create_app(
            store,
            clock=lambda: _NOW,
            pr_transport_factory=lambda provider, url, token: fake,
        )
    )
    _register(client, remote_url=_file_url(origin), provider="github")

    resp = client.post(f"/repos/{_REPO}/docs-pr", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["opened"] is True
    assert body["changed_paths"] == ["docs/api.md"]
    # the transport received a plan carrying the healed doc.
    assert len(fake.plans) == 1
    plan = fake.plans[0]
    assert "docs/api.md" in dict(plan.files)


def test_docs_pr_dry_run_does_not_call_transport(store: Any, tmp_path: Path) -> None:
    origin = _build_repo(tmp_path, heal=False)
    fake = _FakeTransport()
    client = TestClient(
        create_app(
            store,
            clock=lambda: _NOW,
            pr_transport_factory=lambda provider, url, token: fake,
        )
    )
    _register(client, remote_url=_file_url(origin), provider="github")
    resp = client.post(f"/repos/{_REPO}/docs-pr", json={"dry_run": True})
    assert resp.status_code == 201, resp.text
    assert resp.json()["opened"] is True  # a plan WAS produced (dry-run plan dict)
    assert fake.plans == []  # …but the transport was never called


def test_docs_pr_clean_repo_opens_nothing(store: Any, tmp_path: Path) -> None:
    origin = _build_repo(tmp_path, heal=True)  # already in sync → empty patch
    fake = _FakeTransport()
    client = TestClient(
        create_app(
            store,
            clock=lambda: _NOW,
            pr_transport_factory=lambda provider, url, token: fake,
        )
    )
    _register(client, remote_url=_file_url(origin), provider="github")
    resp = client.post(f"/repos/{_REPO}/docs-pr", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["opened"] is False
    assert body["summary"] == "clean"
    assert fake.plans == []


def test_docs_pr_default_transport_factory_dry_run(store: Any, tmp_path: Path) -> None:
    # No pr_transport_factory injected → the route builds the REAL provider transport
    # (GitHubTransport.from_repo, the production path); dry_run avoids any network
    # (open_docs_pr returns the plan dict without calling submit).
    drifted = _build_repo(tmp_path, heal=False)

    class CopyCloner:
        def clone(self, spec: Any, secret: str | None, dest: Path) -> None:
            shutil.copytree(drifted, dest)

    client = TestClient(create_app(store, clock=lambda: _NOW, cloner=CopyCloner()))
    _register(
        client, remote_url="https://github.com/acme/widget.git", provider="github"
    )
    resp = client.post(f"/repos/{_REPO}/docs-pr", json={"dry_run": True})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["opened"] is True
    assert body["changed_paths"] == ["docs/api.md"]


def test_docs_pr_without_provider_is_400(store: Any, tmp_path: Path) -> None:
    client = TestClient(create_app(store, clock=lambda: _NOW))
    _register(client, local_path=str(_build_repo(tmp_path)))  # local-only, no provider
    resp = client.post(f"/repos/{_REPO}/docs-pr", json={})
    assert resp.status_code == 400
    assert "provider+remote_url" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# PHASE 2 — a GitHub App credential mints a SHORT-LIVED token, then clones (GIT-05).
# --------------------------------------------------------------------------- #


def test_phase2_github_app_mints_short_lived_token_then_clones(
    store: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode("ascii")
    )
    monkeypatch.setenv("CDMON_SECRET_KEY", _KEY_B64)
    origin = _build_repo(tmp_path)
    seen: dict[str, str | None] = {}

    class RecordingCloner:
        def clone(self, spec: Any, secret: str | None, dest: Path) -> None:
            seen["secret"] = secret
            subprocess.run(
                ["git", "clone", "-q", _file_url(origin), str(dest)], check=True
            )

    class FakeExchange:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(
            self, method: str, url: str, *, body: dict | None, headers: dict[str, str]
        ) -> dict:
            self.calls.append({"url": url, "headers": headers})
            return {"token": "ghs_minted_install_token"}

    fake_exchange = FakeExchange()
    client = TestClient(
        create_app(
            store,
            clock=lambda: _NOW,
            cloner=RecordingCloner(),
            token_exchange_http=fake_exchange,
        )
    )
    # the sealed credential is a github-app JSON blob (NOT a raw token).
    cred = json.dumps({"app_id": "42", "installation_id": "99", "private_key_pem": pem})
    _register(
        client,
        remote_url="https://github.com/acme/widget.git",
        provider="github",
        provider_kind="github-app",
        provider_secret=cred,
    )

    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    assert resp.status_code == 201, resp.text
    # the MINTED short-lived token reached the cloner — NOT the credential JSON.
    assert seen["secret"] == "ghs_minted_install_token"
    # the App-JWT bearer was exchanged at the installation access-tokens endpoint.
    assert fake_exchange.calls
    assert fake_exchange.calls[0]["url"].endswith("/app/installations/99/access_tokens")
    assert fake_exchange.calls[0]["headers"]["Authorization"].startswith("Bearer ")


# --------------------------------------------------------------------------- #
# Auth matrix (401/403) on both new write routes.
# --------------------------------------------------------------------------- #


def test_remote_sync_and_docs_pr_require_token(store: Any, tmp_path: Path) -> None:
    origin = _build_repo(tmp_path)
    fake = _FakeTransport()
    client = TestClient(
        create_app(store, clock=lambda: _NOW, pr_transport_factory=lambda p, u, t: fake)
    )
    _register(
        client, remote_url=_file_url(origin), provider="github", auth_token="s3cret"
    )

    for path in (f"/repos/{_REPO}/sync", f"/repos/{_REPO}/docs-pr"):
        body = {"mode": "local"} if path.endswith("/sync") else {}
        assert client.post(path, json=body).status_code == 401  # missing
        assert (
            client.post(
                path, json=body, headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 403
        )
    # the correct token proceeds.
    ok = client.post(
        f"/repos/{_REPO}/sync",
        json={"mode": "local"},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert ok.status_code == 201
