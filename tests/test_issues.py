"""H-04 — tests for the coverage-gap issue opener (offline, INJECTED transport, K4).

``plan_coverage_issue`` turns a real ``CoverageReport`` + ``suggest_owners`` output
into a DETERMINISTIC ``IssuePlan`` (title counts the gaps; body groups every
undocumented public symbol under its suggested owner). ``open_coverage_issue``
submits exactly that plan to an INJECTED fake transport, is a no-op (``None``) when
there are no gaps, and never calls the transport under ``dry_run``. The default
GitLab/GitHub transports are exercised only through a stubbed HTTP leaf — no real
network is ever touched (K4); HTTP is stdlib-only (K0); the payload is deterministic
(K10).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from code_doc_monitor import inventory
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.coverage import resolve_coverage, suggest_owners
from code_doc_monitor.errors import TransportError
from code_doc_monitor.issues import (
    GitHubIssueTransport,
    GitLabIssueTransport,
    IssuePlan,
    open_coverage_issue,
    plan_coverage_issue,
)


def _report_and_suggestions(tmp_path: Path, *, with_gaps: bool):
    """A real coverage report over a tiny repo (one documented sym, two gaps)."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        "def alpha():\n    pass\n\n\ndef beta():\n    pass\n",
        encoding="utf-8",
    )
    code_refs: tuple[CodeRef, ...] = ()
    if with_gaps:
        # document only `alpha` -> `beta` is an undocumented PUBLIC gap (sibling-owned).
        code_refs = (CodeRef(path="pkg/mod.py", symbols=("alpha",)),)
    else:
        code_refs = (CodeRef(path="pkg/mod.py"),)  # whole file -> no gaps
    config = MonitorConfig(
        root=".",
        documents=(
            DocumentSpec(
                id="pkg-doc",
                path="docs/pkg.md",
                audience=Audience.ENG_GUIDE,
                code_refs=code_refs,
            ),
        ),
    )
    inv = inventory.discover_files(tmp_path)
    sym = inventory.discover_symbols(inv, tmp_path)
    report = resolve_coverage(config, sym)
    return report, suggest_owners(report, config)


# --- plan_coverage_issue ----------------------------------------------------


def test_plan_lists_gap_under_suggested_owner(tmp_path: Path) -> None:
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=True)
    plan = plan_coverage_issue(report, suggestions)
    assert plan is not None
    # title counts the one gap.
    assert "1 undocumented public symbol" in plan.title
    # the gap symbol appears in the body, grouped under its suggested owner (pkg-doc,
    # a sibling owner of `alpha`).
    assert "pkg-doc" in plan.body
    assert "pkg/mod.py::beta" in plan.body
    assert "beta" in plan.body
    assert plan.labels == ("documentation",)


def test_plan_none_when_no_gaps(tmp_path: Path) -> None:
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=False)
    assert plan_coverage_issue(report, suggestions) is None


def test_plan_is_deterministic(tmp_path: Path) -> None:
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=True)
    a = plan_coverage_issue(report, suggestions)
    b = plan_coverage_issue(report, suggestions)
    assert a == b


def test_plan_is_frozen(tmp_path: Path) -> None:
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=True)
    plan = plan_coverage_issue(report, suggestions)
    assert plan is not None
    with pytest.raises(ValidationError):
        plan.title = "mutated"  # type: ignore[misc]


# --- open_coverage_issue ----------------------------------------------------


class FakeTransport:
    """An injected stand-in for an issue transport: records the plan, no network."""

    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[IssuePlan] = []
        self._response = response or {"web_url": "https://example/issues/1"}

    def submit(self, plan: IssuePlan) -> dict:
        self.calls.append(plan)
        return self._response


def test_open_submits_exact_plan_and_returns_response(tmp_path: Path) -> None:
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=True)
    transport = FakeTransport({"web_url": "https://gl/issues/42"})
    planned = plan_coverage_issue(report, suggestions)

    out = open_coverage_issue(report, suggestions, transport=transport)

    assert out == {"web_url": "https://gl/issues/42"}
    assert len(transport.calls) == 1
    assert transport.calls[0] == planned


def test_open_dry_run_does_not_call_transport(tmp_path: Path) -> None:
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=True)
    transport = FakeTransport()
    out = open_coverage_issue(report, suggestions, transport=transport, dry_run=True)
    assert transport.calls == []
    assert isinstance(out, dict)
    assert "pkg/mod.py::beta" in out["body"]


def test_open_no_gaps_is_noop(tmp_path: Path) -> None:
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=False)
    transport = FakeTransport()
    out = open_coverage_issue(report, suggestions, transport=transport)
    assert out is None
    assert transport.calls == []


# --- GitLab transport (HTTP leaf stubbed — zero network, K4) -----------------


def test_gitlab_from_env_builds_with_required_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI_PROJECT_ID", "123")
    monkeypatch.setenv("CDMON_GITLAB_TOKEN", "s3cret")
    monkeypatch.setenv("CI_API_V4_URL", "https://gitlab.example/api/v4")
    assert isinstance(GitLabIssueTransport.from_env(), GitLabIssueTransport)


def test_gitlab_from_env_missing_project_is_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI_PROJECT_ID", raising=False)
    monkeypatch.setenv("CDMON_GITLAB_TOKEN", "s3cret")
    with pytest.raises(TransportError, match="CI_PROJECT_ID"):
        GitLabIssueTransport.from_env()


def test_gitlab_from_env_missing_token_is_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI_PROJECT_ID", "123")
    monkeypatch.delenv("CDMON_GITLAB_TOKEN", raising=False)
    with pytest.raises(TransportError, match="CDMON_GITLAB_TOKEN"):
        GitLabIssueTransport.from_env()


def test_gitlab_submit_posts_issue_via_injected_http(tmp_path: Path) -> None:
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=True)
    plan = plan_coverage_issue(report, suggestions)
    assert plan is not None
    requests: list[dict[str, object]] = []

    class FakeHttp:
        def request(
            self, method: str, url: str, *, body: dict | None, token: str
        ) -> dict:
            requests.append(
                {"method": method, "url": url, "body": body, "token": token}
            )
            return {"web_url": "https://gl/issues/7", "iid": 7}

    transport = GitLabIssueTransport(
        project_id="123",
        token="s3cret",
        api_url="https://gitlab.example/api/v4",
        http=FakeHttp(),
    )
    out = transport.submit(plan)
    assert out == {"web_url": "https://gl/issues/7", "iid": 7}
    assert len(requests) == 1
    r = requests[0]
    assert r["method"] == "POST"
    assert isinstance(r["url"], str) and r["url"].endswith("/issues")
    assert "projects/123" in r["url"]
    assert r["token"] == "s3cret"
    body = r["body"]
    assert isinstance(body, dict)
    assert body["title"] == plan.title
    assert body["description"] == plan.body
    assert body["labels"] == "documentation"


def test_gitlab_builds_default_http_leaf_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import code_doc_monitor.issues as issues_mod

    posted: list[str] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        posted.append(url)
        return {"web_url": "https://gl/issues/3"}

    monkeypatch.setattr(issues_mod._UrllibGitLabIssueHttp, "request", fake_request)
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=True)
    plan = plan_coverage_issue(report, suggestions)
    assert plan is not None
    transport = GitLabIssueTransport(project_id="1", token="t")  # no http injected
    out = transport.submit(plan)
    assert out == {"web_url": "https://gl/issues/3"}
    assert len(posted) == 1


# --- GitHub transport (HTTP leaf stubbed) -----------------------------------


def test_github_from_env_builds_with_required_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widget")
    monkeypatch.setenv("CDMON_GITHUB_TOKEN", "ghtok")
    assert isinstance(GitHubIssueTransport.from_env(), GitHubIssueTransport)


def test_github_from_env_missing_repo_is_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setenv("CDMON_GITHUB_TOKEN", "ghtok")
    with pytest.raises(TransportError, match="GITHUB_REPOSITORY"):
        GitHubIssueTransport.from_env()


def test_github_from_env_missing_token_is_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widget")
    monkeypatch.delenv("CDMON_GITHUB_TOKEN", raising=False)
    with pytest.raises(TransportError, match="CDMON_GITHUB_TOKEN"):
        GitHubIssueTransport.from_env()


def test_github_submit_posts_issue_via_injected_http(tmp_path: Path) -> None:
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=True)
    plan = plan_coverage_issue(report, suggestions)
    assert plan is not None
    requests: list[dict[str, object]] = []

    class FakeHttp:
        def request(
            self, method: str, url: str, *, body: dict | None, token: str
        ) -> dict:
            requests.append(
                {"method": method, "url": url, "body": body, "token": token}
            )
            return {"html_url": "https://github.com/acme/widget/issues/5"}

    transport = GitHubIssueTransport(
        repo="acme/widget",
        token="ghtok",
        api_url="https://api.github.test",
        http=FakeHttp(),
    )
    out = transport.submit(plan)
    assert out == {"html_url": "https://github.com/acme/widget/issues/5"}
    r = requests[0]
    assert isinstance(r["url"], str)
    assert r["url"] == "https://api.github.test/repos/acme/widget/issues"
    assert r["token"] == "ghtok"
    body = r["body"]
    assert isinstance(body, dict)
    assert body["title"] == plan.title
    assert body["body"] == plan.body
    assert body["labels"] == ["documentation"]


def test_github_builds_default_http_leaf_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import code_doc_monitor.issues as issues_mod

    posted: list[str] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        posted.append(url)
        return {"html_url": "https://github/issues/9"}

    monkeypatch.setattr(issues_mod._UrllibGitHubIssueHttp, "request", fake_request)
    report, suggestions = _report_and_suggestions(tmp_path, with_gaps=True)
    plan = plan_coverage_issue(report, suggestions)
    assert plan is not None
    transport = GitHubIssueTransport(repo="a/b", token="t")
    out = transport.submit(plan)
    assert out == {"html_url": "https://github/issues/9"}
    assert len(posted) == 1
