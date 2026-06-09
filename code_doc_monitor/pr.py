"""C-03 — the bot-PR opener behind ``cdmon open-docs-pr`` (offline by default).

Turns a :class:`~code_doc_monitor.syncpr.SyncResult` (C-02) into a **docs merge
request**: a branch + a commit of the healed doc files + an MR. Network is
INJECTED (K4) — the provider transport is a :class:`PRTransport`, so tests drive
a fake that asserts the exact plan and never touch the network. The default
:class:`GitLabTransport` speaks the GitLab REST API with the standard library
only (no ``python-gitlab``/``requests``, K0); its single real ``urlopen`` lives
in the one-line :class:`_GitLabHttp` leaf — the only ``# pragma: no cover`` line
(mirroring :mod:`code_doc_monitor.sinks` / :mod:`code_doc_monitor.backends`).

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


def _branch_name(patch: str, prefix: str) -> str:
    """Deterministic branch from a patch hash (stable + unique-per-change, K10)."""
    digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _description(changed_paths: tuple[str, ...], ref: str | None) -> str:
    """A bot-generated MR body listing every changed doc path."""
    lines = [
        "Automated docs sync opened by `cdmon` (bot-generated).",
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
