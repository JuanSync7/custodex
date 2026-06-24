"""C-03 — the bot-PR opener behind ``cdx open-docs-pr`` (offline by default).

Turns a :class:`~custodex.syncpr.SyncResult` (C-02) into a **docs merge
request**: a branch + a commit of the healed doc files + an MR. Network is
INJECTED (K4) — the provider transport is a :class:`PRTransport`, so tests drive
a fake that asserts the exact plan and never touch the network. The default
:class:`GitLabTransport` speaks the GitLab REST API with the standard library
only (no ``python-gitlab``/``requests``, K0); its single real ``urlopen`` lives
in the one-line :class:`_GitLabHttp` leaf — the only ``# pragma: no cover`` line
(mirroring :mod:`custodex.sinks` / :mod:`custodex.backends`).

The plan is deterministic (K10): the source branch is
``f"{branch_prefix}-{sha256(sync.patch)[:12]}"`` — stable for an unchanged patch,
unique per change — so re-opening the same docs sync is idempotent at the branch
level. An empty sync (nothing healed) is a no-op: no branch, no MR, returns
``None``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from .errors import TransportError
from .syncpr import SyncResult

__all__ = [
    "MergeRequestPlan",
    "PRTransport",
    "GitLabTransport",
    "GitHubTransport",
    "plan_docs_pr",
    "open_docs_pr",
]

# Frozen + extra="forbid": a plan is an immutable description of one MR.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class MergeRequestPlan(BaseModel):
    """A provider-agnostic description of the docs MR to open (deterministic)."""

    model_config = _MODEL_CONFIG

    source_branch: str  # f"{branch_prefix}-{sha256(patch)[:12]}" (deterministic, K10)
    target_branch: str = "main"
    title: str  # "docs: sync" (+ " to <ref>" when a ref is supplied)
    description: str  # bot-generated note + a bullet per changed path
    files: tuple[tuple[str, str], ...]  # (repo-relative POSIX path, NEW content)
    labels: tuple[str, ...] = ()


@runtime_checkable
class PRTransport(Protocol):
    """Something that can open a merge request from a :class:`MergeRequestPlan`."""

    def submit(self, plan: MergeRequestPlan) -> dict: ...


class _GitLabHttp(Protocol):
    """The injected GitLab HTTP leaf: one JSON request → parsed JSON response."""

    def request(
        self, method: str, url: str, *, body: dict | None, token: str
    ) -> dict: ...


class _UrllibGitLabHttp:
    """A stdlib-only GitLab JSON client (no ``requests``, K0). Never used in tests."""

    def request(self, method: str, url: str, *, body: dict | None, token: str) -> dict:
        import urllib.request  # pragma: no cover

        data = (  # pragma: no cover
            json.dumps(body).encode("utf-8") if body is not None else None
        )
        req = urllib.request.Request(  # pragma: no cover
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "PRIVATE-TOKEN": token,
            },
            method=method,
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310  # pragma: no cover
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}  # pragma: no cover


class GitLabTransport:
    """Open a docs MR via the GitLab REST API (stdlib only, INJECTED leaf — K0/K4).

    :meth:`submit` performs the canonical 3-call flow — create the source branch
    off the target, create a single commit carrying every file action, then open
    the merge request — each through the one injected :class:`_GitLabHttp` leaf.
    The leaf is injected so tests stub it and never hit the network; when none is
    supplied a stdlib :class:`_UrllibGitLabHttp` is built lazily (K0).
    """

    def __init__(
        self,
        *,
        project_id: str,
        token: str,
        api_url: str = "https://gitlab.com/api/v4",
        http: _GitLabHttp | None = None,
    ) -> None:
        self._project_id = project_id
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._http = http

    @classmethod
    def from_env(
        cls,
        *,
        project_env: str = "CI_PROJECT_ID",
        token_env: str = "CDMON_GITLAB_TOKEN",
        api_env: str = "CI_API_V4_URL",
    ) -> GitLabTransport:
        """Build from CI env; loud :class:`TransportError` if any var is unset (K8)."""
        import os

        project_id = os.environ.get(project_env)
        if not project_id:
            raise TransportError(
                f"GitLab transport needs a project id in ${project_env} "
                "(unset or empty)"
            )
        token = os.environ.get(token_env)
        if not token:
            raise TransportError(
                f"GitLab transport needs an access token in ${token_env} "
                "(unset or empty)"
            )
        api_url = os.environ.get(api_env) or "https://gitlab.com/api/v4"
        return cls(project_id=project_id, token=token, api_url=api_url)

    @classmethod
    def from_repo(
        cls,
        remote_url: str,
        token: str,
        *,
        api_url: str | None = None,
        http: _GitLabHttp | None = None,
    ) -> GitLabTransport:
        """Build from a repo's ``remote_url`` (GIT-03 — the central server path).

        The whole project path (``group/sub/proj``) becomes the ``project_id`` (the
        transport URL-encodes it). ``api_url`` defaults to ``gitlab.com`` for a
        gitlab.com remote, else ``https://<host>/api/v4`` (self-hosted). A
        non-provider URL is a loud :class:`TransportError` (K8 — the SSRF allowlist
        hook). Unlike :meth:`from_env` (CI), the server passes the per-repo token it
        opened from the sealed credential.
        """
        host, path = _parse_remote(remote_url)
        if api_url is None:
            api_url = (
                "https://gitlab.com/api/v4"
                if host == "gitlab.com"
                else f"https://{host}/api/v4"
            )
        return cls(project_id=path, token=token, api_url=api_url, http=http)

    def _project_url(self) -> str:
        from urllib.parse import quote

        return f"{self._api_url}/projects/{quote(self._project_id, safe='')}"

    def submit(self, plan: MergeRequestPlan) -> dict:
        http = self._http
        if http is None:
            http = self._http = _UrllibGitLabHttp()
        base = self._project_url()
        # 1) create the source branch off the target.
        http.request(
            "POST",
            f"{base}/repository/branches",
            body={"branch": plan.source_branch, "ref": plan.target_branch},
            token=self._token,
        )
        # 2) one commit carrying every healed file as an "update" action.
        actions = [
            {"action": "update", "file_path": path, "content": content}
            for path, content in plan.files
        ]
        http.request(
            "POST",
            f"{base}/repository/commits",
            body={
                "branch": plan.source_branch,
                "commit_message": plan.title,
                "actions": actions,
            },
            token=self._token,
        )
        # 3) open the merge request and return its JSON.
        mr_body: dict[str, object] = {
            "source_branch": plan.source_branch,
            "target_branch": plan.target_branch,
            "title": plan.title,
            "description": plan.description,
        }
        if plan.labels:
            mr_body["labels"] = ",".join(plan.labels)
        return http.request(
            "POST",
            f"{base}/merge_requests",
            body=mr_body,
            token=self._token,
        )


def _parse_remote(remote_url: str) -> tuple[str, str]:
    """Split a provider remote URL into ``(host, path)`` (GIT-03; loud on garbage).

    ``path`` is the repo path with a trailing ``.git`` stripped — ``owner/repo``
    for GitHub, the full ``group/.../proj`` for GitLab. A URL with no host or no
    ``/``-bearing path is a loud :class:`TransportError` (K8) — the single place an
    adopter-supplied ``remote_url`` is validated (the SSRF/host allowlist hook).
    """
    from urllib.parse import urlparse

    parsed = urlparse(remote_url)
    host = parsed.netloc
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    if not host or "/" not in path:
        raise TransportError(f"not a recognizable git remote URL: {remote_url!r}")
    return host, path


class _GitHubHttp(Protocol):
    """The injected GitHub HTTP leaf: one JSON request → parsed JSON response."""

    def request(
        self, method: str, url: str, *, body: dict | None, token: str
    ) -> dict: ...


class _UrllibGitHubHttp:
    """A stdlib-only GitHub JSON client (no ``requests``, K0). Never used in tests."""

    def request(self, method: str, url: str, *, body: dict | None, token: str) -> dict:
        import urllib.request  # pragma: no cover

        data = (  # pragma: no cover
            json.dumps(body).encode("utf-8") if body is not None else None
        )
        req = urllib.request.Request(  # pragma: no cover
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method=method,
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310  # pragma: no cover
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}  # pragma: no cover


class GitHubTransport:
    """Open a docs PR via the GitHub REST API (stdlib only, INJECTED leaf — K0/K4).

    :meth:`submit` performs the canonical ATOMIC git-data flow with NO local
    checkout — read the target branch's base commit + tree, build a new tree
    carrying every healed file inline, create a commit on it, create the source
    branch ref, then open the pull request — each through the one injected
    :class:`_GitHubHttp` leaf (a stdlib :class:`_UrllibGitHubHttp` built lazily
    when none is supplied, K0). Sibling of :class:`GitLabTransport`; the same
    :class:`PRTransport` shape, so ``open_docs_pr`` drives either by ``provider``.
    """

    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        token: str,
        api_url: str = "https://api.github.com",
        http: _GitHubHttp | None = None,
    ) -> None:
        self._owner = owner
        self._repo = repo
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._http = http

    @classmethod
    def from_env(
        cls,
        *,
        repo_env: str = "GITHUB_REPOSITORY",
        token_env: str = "CDMON_GITHUB_TOKEN",
        api_env: str = "GITHUB_API_URL",
    ) -> GitHubTransport:
        """Build from CI env; loud :class:`TransportError` if any var is unset (K8)."""
        import os

        slug = os.environ.get(repo_env)
        if not slug or "/" not in slug:
            raise TransportError(
                f"GitHub transport needs '<owner>/<repo>' in ${repo_env} "
                "(unset or malformed)"
            )
        token = os.environ.get(token_env)
        if not token:
            raise TransportError(
                f"GitHub transport needs an access token in ${token_env} "
                "(unset or empty)"
            )
        owner, repo = slug.split("/", 1)
        api_url = os.environ.get(api_env) or "https://api.github.com"
        return cls(owner=owner, repo=repo, token=token, api_url=api_url)

    @classmethod
    def from_repo(
        cls,
        remote_url: str,
        token: str,
        *,
        api_url: str | None = None,
        http: _GitHubHttp | None = None,
    ) -> GitHubTransport:
        """Build from a repo's ``remote_url`` (GIT-03 — the central server path).

        ``api_url`` defaults to ``https://api.github.com`` for a github.com remote,
        else ``https://<host>/api/v3`` (GitHub Enterprise). A URL that is not a
        ``<owner>/<repo>`` GitHub path is a loud :class:`TransportError` (K8).
        """
        host, path = _parse_remote(remote_url)
        parts = path.split("/")
        if len(parts) != 2:
            raise TransportError(f"not a GitHub '<owner>/<repo>' URL: {remote_url!r}")
        owner, repo = parts
        if api_url is None:
            api_url = (
                "https://api.github.com"
                if host == "github.com"
                else f"https://{host}/api/v3"
            )
        return cls(owner=owner, repo=repo, token=token, api_url=api_url, http=http)

    def _repo_url(self) -> str:
        return f"{self._api_url}/repos/{self._owner}/{self._repo}"

    def submit(self, plan: MergeRequestPlan) -> dict:
        http = self._http
        if http is None:
            http = self._http = _UrllibGitHubHttp()
        base = self._repo_url()
        # 1) the target branch's current commit sha.
        ref = http.request(
            "GET",
            f"{base}/git/ref/heads/{plan.target_branch}",
            body=None,
            token=self._token,
        )
        base_sha = ref["object"]["sha"]
        # 2) that commit's tree sha.
        base_commit = http.request(
            "GET", f"{base}/git/commits/{base_sha}", body=None, token=self._token
        )
        base_tree = base_commit["tree"]["sha"]
        # 3) a new tree carrying every healed file inline (blobs created implicitly).
        tree = http.request(
            "POST",
            f"{base}/git/trees",
            body={
                "base_tree": base_tree,
                "tree": [
                    {"path": path, "mode": "100644", "type": "blob", "content": content}
                    for path, content in plan.files
                ],
            },
            token=self._token,
        )
        # 4) a commit on the new tree, parented on the base commit.
        commit = http.request(
            "POST",
            f"{base}/git/commits",
            body={
                "message": plan.title,
                "tree": tree["sha"],
                "parents": [base_sha],
            },
            token=self._token,
        )
        # 5) the source branch ref → the new commit.
        http.request(
            "POST",
            f"{base}/git/refs",
            body={"ref": f"refs/heads/{plan.source_branch}", "sha": commit["sha"]},
            token=self._token,
        )
        # 6) open the pull request and return its JSON.
        return http.request(
            "POST",
            f"{base}/pulls",
            body={
                "title": plan.title,
                "head": plan.source_branch,
                "base": plan.target_branch,
                "body": plan.description,
            },
            token=self._token,
        )


def _branch_name(patch: str, prefix: str) -> str:
    """Deterministic branch from a patch hash (stable + unique-per-change, K10)."""
    digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _description(changed_paths: tuple[str, ...], ref: str | None) -> str:
    """A bot-generated MR body listing every changed doc path."""
    lines = [
        "Automated docs sync opened by `cdx` (bot-generated).",
        "",
    ]
    if ref is not None:
        lines.append(f"Source ref: `{ref}`.")
        lines.append("")
    lines.append("Changed documents:")
    lines.extend(f"- `{path}`" for path in changed_paths)
    return "\n".join(lines) + "\n"


def plan_docs_pr(
    sync: SyncResult,
    root: Path,
    *,
    target_branch: str = "main",
    ref: str | None = None,
    branch_prefix: str = "cdmon/docs-sync",
    labels: tuple[str, ...] = (),
) -> MergeRequestPlan | None:
    """Build the deterministic :class:`MergeRequestPlan` for one docs sync.

    Returns ``None`` when ``sync.patch`` is empty (nothing healed → no MR). The
    healed file contents are read from their CURRENT on-disk state under ``root``
    (the caller heals first via ``sync_pr``), so the commit carries exactly what a
    reviewer will see. The branch name is derived from a hash of the patch (K10).
    """
    if not sync.patch:
        return None
    files = tuple(
        (rel, (root / rel).read_text(encoding="utf-8")) for rel in sync.changed_paths
    )
    title = "docs: sync" if ref is None else f"docs: sync to {ref}"
    return MergeRequestPlan(
        source_branch=_branch_name(sync.patch, branch_prefix),
        target_branch=target_branch,
        title=title,
        description=_description(sync.changed_paths, ref),
        files=files,
        labels=labels,
    )


def open_docs_pr(
    sync: SyncResult,
    root: Path,
    *,
    transport: PRTransport,
    dry_run: bool = False,
    **plan_kw: object,
) -> dict | None:
    """Plan and (unless ``dry_run``) submit the docs MR through ``transport``.

    An empty sync is a no-op (returns ``None``, transport untouched). ``dry_run``
    returns the plan as a dict WITHOUT calling the transport. Otherwise the plan
    is submitted and the provider response is returned.
    """
    plan = plan_docs_pr(sync, root, **plan_kw)  # type: ignore[arg-type]
    if plan is None:
        return None
    if dry_run:
        return plan.model_dump()
    return transport.submit(plan)
