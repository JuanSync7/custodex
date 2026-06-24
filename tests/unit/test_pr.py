"""C-03 — tests for the bot-PR opener (offline, INJECTED transport, K4).

`plan_docs_pr` turns a `SyncResult` over a real temp-repo into a deterministic
`MergeRequestPlan` (branch from a hash of the patch, title/description, healed
file contents). `open_docs_pr` submits exactly that plan to an INJECTED fake
transport (and returns its response), is a no-op on an empty sync, and never
calls the transport under `dry_run`. The default `GitLabTransport` is exercised
only through a stubbed HTTP leaf — no real network is ever touched (K4); HTTP is
stdlib-only (K0); the branch name is deterministic (K10).

Features: FEAT-PR-004, FEAT-PR-005, FEAT-PR-006, FEAT-GITSYNC-004
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from custodex.errors import TransportError
from custodex.pr import (
    GitHubTransport,
    GitLabTransport,
    MergeRequestPlan,
    _parse_remote,
    open_docs_pr,
    plan_docs_pr,
)
from custodex.syncpr import SyncResult

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
    import custodex.pr as pr_mod

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


# --- _parse_remote + from_repo (GIT-03) -------------------------------------


def test_parse_remote_strips_dot_git_and_returns_host_path() -> None:
    assert _parse_remote("https://github.com/owner/repo.git") == (
        "github.com",
        "owner/repo",
    )
    assert _parse_remote("https://gitlab.com/g/sub/proj") == (
        "gitlab.com",
        "g/sub/proj",
    )


def test_parse_remote_loud_on_non_provider_url() -> None:
    with pytest.raises(TransportError, match="not a recognizable git remote URL"):
        _parse_remote("not-a-url")
    with pytest.raises(TransportError):
        _parse_remote("https://github.com/owner")  # no repo segment → no '/'


def test_gitlab_from_repo_uses_full_project_path(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = plan_docs_pr(_sync(), root)
    assert plan is not None
    urls: list[str] = []

    class FakeHttp:
        def request(
            self, method: str, url: str, *, body: dict | None, token: str
        ) -> dict:
            urls.append(url)
            return {"web_url": "https://gl/mr/1"}

    transport = GitLabTransport.from_repo(
        "https://gitlab.com/group/sub/proj.git", "t", http=FakeHttp()
    )
    transport.submit(plan)
    # the URL-encoded full project path is in the project URL (gitlab.com default api).
    assert urls[0].startswith("https://gitlab.com/api/v4/projects/group%2Fsub%2Fproj/")


# --- GitHubTransport (GIT-03; HTTP leaf stubbed — zero network, K4) ----------


def test_github_submit_runs_atomic_git_data_flow_via_injected_http(
    tmp_path: Path,
) -> None:
    """ref → base commit → tree → commit → branch ref → PR, all via ONE leaf."""
    root = _repo(tmp_path)
    plan = plan_docs_pr(_sync(), root, ref="deadbeef")
    assert plan is not None

    requests: list[dict[str, object]] = []

    class FakeHttp:
        def request(
            self, method: str, url: str, *, body: dict | None, token: str
        ) -> dict:
            requests.append(
                {"method": method, "url": url, "body": body, "token": token}
            )
            if url.endswith(f"/git/ref/heads/{plan.target_branch}"):
                return {"object": {"sha": "BASE_SHA"}}
            if url.endswith("/git/commits/BASE_SHA"):
                return {"tree": {"sha": "BASE_TREE"}}
            if url.endswith("/git/trees"):
                return {"sha": "NEW_TREE"}
            if url.endswith("/git/commits"):
                return {"sha": "NEW_COMMIT"}
            if url.endswith("/git/refs"):
                return {}
            if url.endswith("/pulls"):
                return {"html_url": "https://gh/pr/7", "number": 7}
            raise AssertionError(f"unexpected url {url}")  # pragma: no cover

    transport = GitHubTransport(
        owner="acme", repo="widget", token="ghp_x", http=FakeHttp()
    )
    out = transport.submit(plan)

    assert out == {"html_url": "https://gh/pr/7", "number": 7}
    assert [r["method"] for r in requests] == [
        "GET",
        "GET",
        "POST",
        "POST",
        "POST",
        "POST",
    ]
    assert all(r["token"] == "ghp_x" for r in requests)
    urls = [r["url"] for r in requests]
    base = "https://api.github.com/repos/acme/widget"
    assert urls[0] == f"{base}/git/ref/heads/main"
    assert urls[1] == f"{base}/git/commits/BASE_SHA"
    assert urls[2] == f"{base}/git/trees"
    assert urls[3] == f"{base}/git/commits"
    assert urls[4] == f"{base}/git/refs"
    assert urls[5] == f"{base}/pulls"
    # the new tree carries one inline blob per healed file, parented on the base tree.
    tree_body = requests[2]["body"]
    assert isinstance(tree_body, dict)
    assert tree_body["base_tree"] == "BASE_TREE"
    assert {e["path"] for e in tree_body["tree"]} == {
        "docs/api/one.md",
        "docs/api/two.md",
    }
    assert all(e["mode"] == "100644" and e["type"] == "blob" for e in tree_body["tree"])
    assert all("content" in e for e in tree_body["tree"])
    # the commit is parented on the base sha and points at the new tree.
    commit_body = requests[3]["body"]
    assert isinstance(commit_body, dict)
    assert commit_body["tree"] == "NEW_TREE"
    assert commit_body["parents"] == ["BASE_SHA"]
    # the branch ref → the new commit.
    ref_body = requests[4]["body"]
    assert isinstance(ref_body, dict)
    assert ref_body["ref"] == f"refs/heads/{plan.source_branch}"
    assert ref_body["sha"] == "NEW_COMMIT"
    # the PR points the source branch at the target.
    pr_body = requests[5]["body"]
    assert isinstance(pr_body, dict)
    assert pr_body["head"] == plan.source_branch
    assert pr_body["base"] == "main"
    assert pr_body["title"] == plan.title


def test_github_from_env_builds_with_required_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widget")
    monkeypatch.setenv("CDMON_GITHUB_TOKEN", "ghp_x")
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    transport = GitHubTransport.from_env()
    assert isinstance(transport, GitHubTransport)


def test_github_from_env_missing_repo_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setenv("CDMON_GITHUB_TOKEN", "ghp_x")
    with pytest.raises(TransportError, match="GITHUB_REPOSITORY"):
        GitHubTransport.from_env()


def test_github_from_env_missing_token_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widget")
    monkeypatch.delenv("CDMON_GITHUB_TOKEN", raising=False)
    with pytest.raises(TransportError, match="CDMON_GITHUB_TOKEN"):
        GitHubTransport.from_env()


def test_github_from_repo_parses_github_com(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = plan_docs_pr(_sync(), root)
    assert plan is not None
    urls: list[str] = []

    class FakeHttp:
        def request(
            self, method: str, url: str, *, body: dict | None, token: str
        ) -> dict:
            urls.append(url)
            return {"object": {"sha": "S"}, "tree": {"sha": "T"}, "sha": "C"}

    transport = GitHubTransport.from_repo(
        "https://github.com/acme/widget.git", "ghp_x", http=FakeHttp()
    )
    transport.submit(plan)
    assert urls[0] == "https://api.github.com/repos/acme/widget/git/ref/heads/main"


def test_github_from_repo_enterprise_host_derives_api_v3(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = plan_docs_pr(_sync(), root)
    assert plan is not None
    urls: list[str] = []

    class FakeHttp:
        def request(
            self, method: str, url: str, *, body: dict | None, token: str
        ) -> dict:
            urls.append(url)
            return {"object": {"sha": "S"}, "tree": {"sha": "T"}, "sha": "C"}

    transport = GitHubTransport.from_repo(
        "https://ghe.corp/org/proj", "ghp_x", http=FakeHttp()
    )
    transport.submit(plan)
    assert urls[0].startswith("https://ghe.corp/api/v3/repos/org/proj/")


def test_github_from_repo_non_github_path_is_loud() -> None:
    with pytest.raises(TransportError, match="owner.*repo"):
        GitHubTransport.from_repo("https://github.com/group/sub/proj", "t")


def test_from_repo_api_url_derivation_and_override() -> None:
    # GitLab: a self-hosted host derives /api/v4; an explicit api_url overrides it.
    gl = GitLabTransport.from_repo("https://gitlab.corp/g/p", "t")
    assert gl._api_url == "https://gitlab.corp/api/v4"
    assert gl._project_id == "g/p"
    gl2 = GitLabTransport.from_repo(
        "https://gitlab.com/g/p", "t", api_url="https://x/api/v4"
    )
    assert gl2._api_url == "https://x/api/v4"
    # GitHub: an explicit api_url overrides the github.com / GHE default.
    gh = GitHubTransport.from_repo(
        "https://github.com/a/b", "t", api_url="https://gh.internal/api/v3"
    )
    assert gh._api_url == "https://gh.internal/api/v3"
    assert (gh._owner, gh._repo) == ("a", "b")


def test_github_through_open_docs_pr(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    seen: list[str] = []

    class FakeHttp:
        def request(
            self, method: str, url: str, *, body: dict | None, token: str
        ) -> dict:
            seen.append(url)
            return {
                "object": {"sha": "S"},
                "tree": {"sha": "T"},
                "sha": "C",
                "html_url": "https://gh/pr/9",
            }

    transport = GitHubTransport(owner="a", repo="b", token="t", http=FakeHttp())
    out = open_docs_pr(_sync(), root, transport=transport)
    assert out == {
        "object": {"sha": "S"},
        "tree": {"sha": "T"},
        "sha": "C",
        "html_url": "https://gh/pr/9",
    }
    assert len(seen) == 6  # the 6-call atomic flow


def test_github_builds_default_http_leaf_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No http injected → submit builds the stdlib leaf lazily; stub the one real
    urlopen so the build-default branch runs with NO network (K4)."""
    import custodex.pr as pr_mod

    posted: list[tuple[str, str]] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        posted.append((method, url))
        return {
            "object": {"sha": "S"},
            "tree": {"sha": "T"},
            "sha": "C",
            "html_url": "https://gh/pr/3",
        }

    monkeypatch.setattr(pr_mod._UrllibGitHubHttp, "request", fake_request)
    root = _repo(tmp_path)
    plan = plan_docs_pr(_sync(), root)
    assert plan is not None
    transport = GitHubTransport(owner="a", repo="b", token="t")  # no http injected
    out = transport.submit(plan)
    assert out["html_url"] == "https://gh/pr/3"
    assert len(posted) == 6
