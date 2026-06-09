"""H-04 — the coverage-gap issue opener behind ``cdmon surface-gaps`` (offline default).

Turns a :class:`~code_doc_monitor.coverage.CoverageReport` (EPIC A) and its
:func:`~code_doc_monitor.coverage.suggest_owners` output into a **tracker issue**
listing the undocumented public symbols grouped by suggested owner. Network is
INJECTED (K4) — the provider transport is an :class:`IssueTransport`, so tests
drive a fake that asserts the exact payload and never touch the network. The
default :class:`GitLabIssueTransport` / :class:`GitHubIssueTransport` speak the
GitLab/GitHub REST issues API with the standard library only (no
``python-gitlab``/``PyGithub``/``requests``, K0); each one's single real
``urlopen`` lives in a one-line ``# pragma: no cover`` leaf (mirroring
:mod:`code_doc_monitor.pr` / :mod:`code_doc_monitor.registry`).

The plan is deterministic (K10): gaps are grouped under their suggested owner,
owners sorted ascending, each gap line ``- `path::name` (kind)``; the title counts
the gaps. No gaps → :func:`plan_coverage_issue` returns ``None`` and
:func:`open_coverage_issue` is a no-op (no branch, no issue, returns ``None``).
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from .coverage import CoverageReport, OwnerSuggestion
from .errors import TransportError

__all__ = [
    "IssuePlan",
    "IssueTransport",
    "GitLabIssueTransport",
    "GitHubIssueTransport",
    "plan_coverage_issue",
    "open_coverage_issue",
]

# Frozen + extra="forbid": a plan is an immutable description of one issue.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: The default label every coverage-gap issue carries.
_DEFAULT_LABELS: tuple[str, ...] = ("documentation",)


class IssuePlan(BaseModel):
    """A provider-agnostic description of the coverage-gap issue to open (K10)."""

    model_config = _MODEL_CONFIG

    title: str  # "docs: N undocumented public symbol(s)"
    body: str  # deterministic: gap symbols grouped by suggested owner
    labels: tuple[str, ...] = _DEFAULT_LABELS


@runtime_checkable
class IssueTransport(Protocol):
    """Something that can open a tracker issue from an :class:`IssuePlan`."""

    def submit(self, plan: IssuePlan) -> dict: ...


class _IssueHttp(Protocol):
    """The injected issue HTTP leaf: one JSON request → parsed JSON response."""

    def request(
        self, method: str, url: str, *, body: dict | None, token: str
    ) -> dict: ...


class _UrllibGitLabIssueHttp:
    """A stdlib-only GitLab JSON client (no ``requests``, K0). Never used in tests."""

    def request(  # pragma: no cover — the real network leaf, never hit in tests (K4)
        self, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        import urllib.request

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "PRIVATE-TOKEN": token},
            method=method,
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


class _UrllibGitHubIssueHttp:
    """A stdlib-only GitHub JSON client (no ``requests``, K0). Never used in tests."""

    def request(  # pragma: no cover — the real network leaf, never hit in tests (K4)
        self, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        import urllib.request

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
            },
            method=method,
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


class GitLabIssueTransport:
    """Open a coverage-gap issue via the GitLab REST API (stdlib only — K0/K4).

    :meth:`submit` POSTs one issue to ``<api>/projects/<id>/issues`` through the one
    injected :class:`_IssueHttp` leaf. The leaf is injected so tests stub it and
    never hit the network; when none is supplied a stdlib
    :class:`_UrllibGitLabIssueHttp` is built lazily (K0).
    """

    def __init__(
        self,
        *,
        project_id: str,
        token: str,
        api_url: str = "https://gitlab.com/api/v4",
        http: _IssueHttp | None = None,
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
    ) -> GitLabIssueTransport:
        """Build from CI env; loud :class:`TransportError` if any var is unset (K8)."""
        import os

        project_id = os.environ.get(project_env)
        if not project_id:
            raise TransportError(
                f"GitLab issue transport needs a project id in ${project_env} "
                "(unset or empty)"
            )
        token = os.environ.get(token_env)
        if not token:
            raise TransportError(
                f"GitLab issue transport needs an access token in ${token_env} "
                "(unset or empty)"
            )
        api_url = os.environ.get(api_env) or "https://gitlab.com/api/v4"
        return cls(project_id=project_id, token=token, api_url=api_url)

    def submit(self, plan: IssuePlan) -> dict:
        from urllib.parse import quote

        http = self._http
        if http is None:
            http = self._http = _UrllibGitLabIssueHttp()
        url = f"{self._api_url}/projects/{quote(self._project_id, safe='')}/issues"
        body: dict[str, object] = {
            "title": plan.title,
            "description": plan.body,
        }
        if plan.labels:
            body["labels"] = ",".join(plan.labels)
        return http.request("POST", url, body=body, token=self._token)


class GitHubIssueTransport:
    """Open a coverage-gap issue via the GitHub REST API (stdlib only — K0/K4).

    :meth:`submit` POSTs one issue to ``<api>/repos/<repo>/issues`` through the one
    injected :class:`_IssueHttp` leaf (stubbed in tests; a stdlib
    :class:`_UrllibGitHubIssueHttp` is built lazily when none is supplied, K0).
    """

    def __init__(
        self,
        *,
        repo: str,
        token: str,
        api_url: str = "https://api.github.com",
        http: _IssueHttp | None = None,
    ) -> None:
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
    ) -> GitHubIssueTransport:
        """Build from CI env; loud :class:`TransportError` if any var is unset (K8)."""
        import os

        repo = os.environ.get(repo_env)
        if not repo:
            raise TransportError(
                f"GitHub issue transport needs an 'owner/repo' in ${repo_env} "
                "(unset or empty)"
            )
        token = os.environ.get(token_env)
        if not token:
            raise TransportError(
                f"GitHub issue transport needs an access token in ${token_env} "
                "(unset or empty)"
            )
        api_url = os.environ.get(api_env) or "https://api.github.com"
        return cls(repo=repo, token=token, api_url=api_url)

    def submit(self, plan: IssuePlan) -> dict:
        http = self._http
        if http is None:
            http = self._http = _UrllibGitHubIssueHttp()
        url = f"{self._api_url}/repos/{self._repo}/issues"
        body: dict[str, object] = {
            "title": plan.title,
            "body": plan.body,
        }
        if plan.labels:
            body["labels"] = list(plan.labels)
        return http.request("POST", url, body=body, token=self._token)


def _issue_body(suggestions: tuple[OwnerSuggestion, ...]) -> str:
    """Deterministic issue body: gap symbols grouped by suggested owner (K10).

    Owners are sorted ascending; within each owner the gaps keep ``suggest_owners``'
    ``(path, name)`` order. Each gap is a ``- `path::name` (kind)`` bullet — but the
    suggestion does not carry the symbol kind, so the line is ``- `path::name``` with
    the suggestion's ``reason`` retained as the group note.
    """
    by_owner: dict[str, list[OwnerSuggestion]] = {}
    for sug in suggestions:
        by_owner.setdefault(sug.suggested_doc_id, []).append(sug)

    lines = [
        "Automated coverage report opened by `cdmon` (bot-generated).",
        "",
        "The following PUBLIC symbols have no owning document. Each is grouped under "
        "the suggested owner (an existing doc, or a proposed new one):",
        "",
    ]
    for owner in sorted(by_owner):
        group = by_owner[owner]
        new = " (new doc)" if group[0].is_new_doc else ""
        lines.append(f"### `{owner}`{new} — {group[0].reason}")
        for sug in group:
            lines.append(f"- `{sug.path}::{sug.name}`")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def plan_coverage_issue(
    report: CoverageReport, suggestions: tuple[OwnerSuggestion, ...]
) -> IssuePlan | None:
    """Build the deterministic :class:`IssuePlan` for a coverage report's gaps.

    Returns ``None`` when there are no undocumented public symbols
    (``report.undocumented_symbols`` empty → nothing to open). Otherwise the title
    counts the gaps and the body groups every gap under its suggested owner from
    ``suggestions`` (A-07). Deterministic (K10).
    """
    gaps = report.undocumented_symbols
    if not gaps:
        return None
    n = len(gaps)
    title = f"docs: {n} undocumented public symbol{'s' if n != 1 else ''}"
    return IssuePlan(title=title, body=_issue_body(suggestions))


def open_coverage_issue(
    report: CoverageReport,
    suggestions: tuple[OwnerSuggestion, ...],
    *,
    transport: IssueTransport,
    dry_run: bool = False,
) -> dict | None:
    """Plan and (unless ``dry_run``) submit the coverage-gap issue via ``transport``.

    No gaps is a no-op (returns ``None``, transport untouched). ``dry_run`` returns
    the plan as a dict WITHOUT calling the transport. Otherwise the plan is submitted
    and the provider response is returned.
    """
    plan = plan_coverage_issue(report, suggestions)
    if plan is None:
        return None
    if dry_run:
        return plan.model_dump()
    return transport.submit(plan)
