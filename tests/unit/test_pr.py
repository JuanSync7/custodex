"""C-03 — tests for the bot-PR opener (offline, INJECTED transport, K4).

`plan_docs_pr` turns a `SyncResult` over a real temp-repo into a deterministic
`MergeRequestPlan` (branch from a hash of the patch, title/description, healed
file contents). `open_docs_pr` submits exactly that plan to an INJECTED fake
transport (and returns its response), is a no-op on an empty sync, and never
calls the transport under `dry_run`. The default `GitLabTransport` is exercised
only through a stubbed HTTP leaf — no real network is ever touched (K4); HTTP is
stdlib-only (K0); the branch name is deterministic (K10).

Features: FEAT-PR-004, FEAT-PR-005, FEAT-PR-006
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from code_doc_monitor.errors import TransportError
from code_doc_monitor.pr import (
    GitLabTransport,
    MergeRequestPlan,
    open_docs_pr,
    plan_docs_pr,
)
from code_doc_monitor.syncpr import SyncResult

# A realistic two-doc patch + the healed contents on disk.
PATCH = (
    "--- a/docs/api/one.md\n"
    "+++ b/docs/api/one.md\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new one\n"
    "--- a/docs/api/two.md\n"
    "+++ b/docs/api/two.md\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new two\n"
)


def _sync(patch: str = PATCH) -> SyncResult:
    if not patch:
        return SyncResult(patch="", changed_paths=(), summary="clean")
    return SyncResult(
        patch=patch,
        changed_paths=("docs/api/one.md", "docs/api/two.md"),
        summary="2 doc(s) updated",
    )


def _repo(tmp_path: Path) -> Path:
    api = tmp_path / "docs" / "api"
    api.mkdir(parents=True)
    (api / "one.md").write_text("# one\nhealed body one\n", encoding="utf-8")
    (api / "two.md").write_text("# two\nhealed body two\n", encoding="utf-8")
    return tmp_path


class FakeTransport:
    """An injected stand-in for a PR transport: records the plan, no network."""

    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[MergeRequestPlan] = []
        self._response = response or {"web_url": "https://example/mr/1"}

    def submit(self, plan: MergeRequestPlan) -> dict:
        self.calls.append(plan)
        return self._response


# --- plan_docs_pr -----------------------------------------------------------


def test_plan_fields_and_deterministic_branch(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = plan_docs_pr(_sync(), root, ref="abc123")
    assert plan is not None

    expected_hash = hashlib.sha256(PATCH.encode("utf-8")).hexdigest()[:12]
    assert plan.source_branch == f"cdmon/docs-sync-{expected_hash}"
    assert plan.target_branch == "main"
    # ref lands in the title (provenance — C-05).
    assert "docs: sync" in plan.title
    assert "abc123" in plan.title
    # every changed path is listed in the description.
    assert "docs/api/one.md" in plan.description
    assert "docs/api/two.md" in plan.description
    assert "abc123" in plan.description
    # files carry the CURRENT (healed) on-disk content, in path order.
    assert plan.files == (
        ("docs/api/one.md", "# one\nhealed body one\n"),
        ("docs/api/two.md", "# two\nhealed body two\n"),
    )


def test_plan_none_on_empty_patch(tmp_path: Path) -> None:
    assert plan_docs_pr(_sync(""), tmp_path) is None


def test_plan_branch_is_deterministic(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    a = plan_docs_pr(_sync(), root)
    b = plan_docs_pr(_sync(), root)
    assert a is not None and b is not None
    assert a.source_branch == b.source_branch


def test_plan_custom_prefix_target_and_labels(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = plan_docs_pr(
        _sync(),
        root,
        target_branch="develop",
        branch_prefix="bot/docs",
        labels=("docs", "automated"),
    )
    assert plan is not None
    assert plan.target_branch == "develop"
    assert plan.source_branch.startswith("bot/docs-")
    assert plan.labels == ("docs", "automated")
    # no ref → plain title.
    assert plan.title == "docs: sync"


def test_plan_is_frozen(tmp_path: Path) -> None:
    plan = plan_docs_pr(_sync(), _repo(tmp_path))
    assert plan is not None
    try:
        plan.title = "mutated"  # type: ignore[misc]
    except Exception:  # pydantic ValidationError on a frozen model
        return
    raise AssertionError("MergeRequestPlan should be frozen")


# --- open_docs_pr -----------------------------------------------------------


def test_open_submits_exact_plan_and_returns_response(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    transport = FakeTransport({"web_url": "https://gl/mr/42"})
    planned = plan_docs_pr(_sync(), root, ref="r1")

    out = open_docs_pr(_sync(), root, transport=transport, ref="r1")

    assert out == {"web_url": "https://gl/mr/42"}
    assert len(transport.calls) == 1
    assert transport.calls[0] == planned


def test_open_dry_run_does_not_call_transport(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    transport = FakeTransport()
    out = open_docs_pr(_sync(), root, transport=transport, dry_run=True)

    assert transport.calls == []
    # dry-run returns the plan as a dict.
    assert isinstance(out, dict)
    assert out["source_branch"].startswith("cdmon/docs-sync-")
    assert out["files"]  # the healed content is in the would-be plan


def test_open_empty_sync_is_noop(tmp_path: Path) -> None:
    transport = FakeTransport()
    out = open_docs_pr(_sync(""), tmp_path, transport=transport)
    assert out is None
    assert transport.calls == []


def test_open_passes_plan_kwargs_through(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    transport = FakeTransport()
    open_docs_pr(
        _sync(),
        root,
        transport=transport,
        target_branch="release",
        labels=("docs",),
    )
    plan = transport.calls[0]
    assert plan.target_branch == "release"
    assert plan.labels == ("docs",)


# --- GitLabTransport (default; HTTP leaf stubbed — zero network, K4) ---------


def test_gitlab_from_env_builds_with_required_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI_PROJECT_ID", "123")
    monkeypatch.setenv("CDMON_GITLAB_TOKEN", "s3cret")
    monkeypatch.setenv("CI_API_V4_URL", "https://gitlab.example/api/v4")
    transport = GitLabTransport.from_env()
    assert isinstance(transport, GitLabTransport)


def test_gitlab_from_env_missing_project_id_is_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI_PROJECT_ID", raising=False)
    monkeypatch.setenv("CDMON_GITLAB_TOKEN", "s3cret")
    with pytest.raises(TransportError, match="CI_PROJECT_ID"):
        GitLabTransport.from_env()


def test_gitlab_from_env_missing_token_is_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI_PROJECT_ID", "123")
    monkeypatch.delenv("CDMON_GITLAB_TOKEN", raising=False)
    with pytest.raises(TransportError, match="CDMON_GITLAB_TOKEN"):
        GitLabTransport.from_env()


def test_gitlab_submit_runs_three_calls_via_injected_http(tmp_path: Path) -> None:
    """The 3-call flow (branch → commit → MR) goes through ONE injected leaf."""
    root = _repo(tmp_path)
    plan = plan_docs_pr(_sync(), root, ref="deadbeef", labels=("docs", "bot"))
    assert plan is not None

    requests: list[dict[str, object]] = []

    class FakeHttp:
        def request(
            self, method: str, url: str, *, body: dict | None, token: str
        ) -> dict:
            requests.append(
                {"method": method, "url": url, "body": body, "token": token}
            )
            if url.endswith("/merge_requests"):
                return {"web_url": "https://gl/mr/7", "iid": 7}
            return {}

    transport = GitLabTransport(
        project_id="123",
        token="s3cret",
        api_url="https://gitlab.example/api/v4",
        http=FakeHttp(),
    )
    out = transport.submit(plan)

    assert out == {"web_url": "https://gl/mr/7", "iid": 7}
    # branch, commit, merge_request — in that order, all with the token.
    assert [r["method"] for r in requests] == ["POST", "POST", "POST"]
    assert all(r["token"] == "s3cret" for r in requests)
    urls = [r["url"] for r in requests]
    assert urls[0].endswith("/repository/branches")
    assert urls[1].endswith("/repository/commits")
    assert urls[2].endswith("/merge_requests")
    # branch creation references the deterministic source branch off the target.
    branch_body = requests[0]["body"]
    assert isinstance(branch_body, dict)
    assert branch_body["branch"] == plan.source_branch
    assert branch_body["ref"] == "main"
    # the commit carries one action per healed file.
    commit_body = requests[1]["body"]
    assert isinstance(commit_body, dict)
    assert len(commit_body["actions"]) == 2
    assert {a["file_path"] for a in commit_body["actions"]} == {
        "docs/api/one.md",
        "docs/api/two.md",
    }
    # the MR points the source branch at the target with the title + labels.
    mr_body = requests[2]["body"]
    assert isinstance(mr_body, dict)
    assert mr_body["source_branch"] == plan.source_branch
    assert mr_body["target_branch"] == "main"
    assert mr_body["title"] == plan.title
    # labels are joined comma-separated for the GitLab API.
    assert mr_body["labels"] == "docs,bot"


def test_gitlab_submit_through_open_docs_pr(tmp_path: Path) -> None:
    """open_docs_pr drives the GitLabTransport end to end (HTTP leaf stubbed)."""
    root = _repo(tmp_path)
    seen: list[str] = []

    class FakeHttp:
        def request(
            self, method: str, url: str, *, body: dict | None, token: str
        ) -> dict:
            seen.append(url)
            return {"web_url": "https://gl/mr/9"}

    transport = GitLabTransport(project_id="1", token="t", http=FakeHttp())
    out = open_docs_pr(_sync(), root, transport=transport)
    assert out == {"web_url": "https://gl/mr/9"}
    assert len(seen) == 3


def test_gitlab_builds_default_http_leaf_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no http is injected, submit builds the stdlib leaf lazily; we stub the
    one real urlopen so the build-default branch runs with NO network (K4)."""
    import code_doc_monitor.pr as pr_mod

    posted: list[tuple[str, str]] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        posted.append((method, url))
        if url.endswith("/merge_requests"):
            return {"web_url": "https://gl/mr/3"}
        return {}

    monkeypatch.setattr(pr_mod._UrllibGitLabHttp, "request", fake_request)
    root = _repo(tmp_path)
    plan = plan_docs_pr(_sync(), root)
    assert plan is not None
    transport = GitLabTransport(project_id="1", token="t")  # no http injected
    out = transport.submit(plan)
    assert out == {"web_url": "https://gl/mr/3"}
    assert len(posted) == 3
