---
cdm:
  audience: eng-guide
  fingerprint: 866148f0ba080337
  fingerprint_tiers:
    composite: 866148f0ba080337
    docstring: a4b1826e346520b8
    signature: 45119db59f1f3f0c
  region_anchors:
    symbols:
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 05b5625a2235fd61
    - 0899f288831e2a48
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0c1acdb65319c1cf
    - 0e6361b0f8e17a44
    - 12e167b4acb03c9c
    - 152ad2920754aef6
    - 18dee28b09f32434
    - 1d539c9c1426cdd6
    - 2098bdc93474afa1
    - 2a53b0a29f3353d4
    - 2de0cc13e822319a
    - 2ea3d6a69164579e
    - 349fc5f94ca496fd
    - 368330bafb8fc8ae
    - 3712c22594d8a610
    - 4ac558fed54a3be3
    - 52e42c68e462e12b
    - 5557598d631a8880
    - 5569764ee224aa28
    - 56e1ca780be2dea3
    - 608684ecfde9565d
    - 6b2a60b7f2eebd39
    - 7164313e59ad9fcf
    - 71b76153b152f19d
    - 7a3c72fee1bcc02d
    - 7c5e6146fbbfcfc8
    - 8dd9d6363a143b02
    - 9313bceecb1275aa
    - 935cb926affdb452
    - 9b83bdbdaef030af
    - 9c261b4eaa8d4ba2
    - a65988c076a62671
    - aa47518c6da91cbb
    - acba51bfb0141e23
    - b26642ed60aa3bd3
    - b41b13565c55a6fd
    - b836f9d9804e7e15
    - b96dca84642de78c
    - c33627d364a6fab6
    - c36c8d077f308623
    - c5c006ac41a792c9
    - c9c35fa8b87ea3bb
    - cad4d5ff3a52ea1f
    - cb4b9b83943e4426
    - d49b35ad14ad312c
    - da3ebf449f6b07f3
    - e0487cd70266d7b3
    - e2536d6379009f0c
    - ed1c625f4eb531c2
    - ed32c4657a1d14a9
    - ed91e26d119f65f7
    - f09fc085ccb6b19e
    - fe0848f424f5ef4a
    - ffea283de3f43422
  region_hashes:
    symbols: e166645cf810a3f4
  schema_version: 1.0.0
---
# pr-loop

> EPIC C docs-PR loop: the structural `should-sync` loop-breaker decides whether
> a change warrants a heal (`syncpr`), and the host-agnostic PR client opens or
> updates the resulting docs pull/merge request (`pr`).

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| GitHubIssueTransport | class | class GitHubIssueTransport |
| GitHubIssueTransport.__init__ | method | def __init__(self, *, repo: str, token: str, api_url: str = 'https://api.github.com', http: _IssueHttp \| None = None) -> None |
| GitHubIssueTransport.from_env | method | def from_env(cls, *, repo_env: str = 'GITHUB_REPOSITORY', token_env: str = 'CDMON_GITHUB_TOKEN', api_env: str = 'GITHUB_API_URL') -> GitHubIssueTransport |
| GitHubIssueTransport.submit | method | def submit(self, plan: IssuePlan) -> dict |
| GitHubTransport | class | class GitHubTransport |
| GitHubTransport.__init__ | method | def __init__(self, *, owner: str, repo: str, token: str, api_url: str = 'https://api.github.com', http: _GitHubHttp \| None = None) -> None |
| GitHubTransport._repo_url | method | def _repo_url(self) -> str |
| GitHubTransport.from_env | method | def from_env(cls, *, repo_env: str = 'GITHUB_REPOSITORY', token_env: str = 'CDMON_GITHUB_TOKEN', api_env: str = 'GITHUB_API_URL') -> GitHubTransport |
| GitHubTransport.from_repo | method | def from_repo(cls, remote_url: str, token: str, *, api_url: str \| None = None, http: _GitHubHttp \| None = None) -> GitHubTransport |
| GitHubTransport.submit | method | def submit(self, plan: MergeRequestPlan) -> dict |
| GitLabIssueTransport | class | class GitLabIssueTransport |
| GitLabIssueTransport.__init__ | method | def __init__(self, *, project_id: str, token: str, api_url: str = 'https://gitlab.com/api/v4', http: _IssueHttp \| None = None) -> None |
| GitLabIssueTransport.from_env | method | def from_env(cls, *, project_env: str = 'CI_PROJECT_ID', token_env: str = 'CDMON_GITLAB_TOKEN', api_env: str = 'CI_API_V4_URL') -> GitLabIssueTransport |
| GitLabIssueTransport.submit | method | def submit(self, plan: IssuePlan) -> dict |
| GitLabTransport | class | class GitLabTransport |
| GitLabTransport.__init__ | method | def __init__(self, *, project_id: str, token: str, api_url: str = 'https://gitlab.com/api/v4', http: _GitLabHttp \| None = None) -> None |
| GitLabTransport._project_url | method | def _project_url(self) -> str |
| GitLabTransport.from_env | method | def from_env(cls, *, project_env: str = 'CI_PROJECT_ID', token_env: str = 'CDMON_GITLAB_TOKEN', api_env: str = 'CI_API_V4_URL') -> GitLabTransport |
| GitLabTransport.from_repo | method | def from_repo(cls, remote_url: str, token: str, *, api_url: str \| None = None, http: _GitLabHttp \| None = None) -> GitLabTransport |
| GitLabTransport.submit | method | def submit(self, plan: MergeRequestPlan) -> dict |
| IssuePlan | class | class IssuePlan(BaseModel) |
| IssueTransport | class | class IssueTransport(Protocol) |
| IssueTransport.submit | method | def submit(self, plan: IssuePlan) -> dict |
| MergeRequestPlan | class | class MergeRequestPlan(BaseModel) |
| PRTransport | class | class PRTransport(Protocol) |
| PRTransport.submit | method | def submit(self, plan: MergeRequestPlan) -> dict |
| SyncResult | class | class SyncResult(BaseModel) |
| _DEFAULT_LABELS | variable | _DEFAULT_LABELS: tuple[str, ...] = ('documentation',) |
| _GitHubHttp | class | class _GitHubHttp(Protocol) |
| _GitHubHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _GitLabHttp | class | class _GitLabHttp(Protocol) |
| _GitLabHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _IssueHttp | class | class _IssueHttp(Protocol) |
| _IssueHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _UrllibGitHubHttp | class | class _UrllibGitHubHttp |
| _UrllibGitHubHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _UrllibGitHubIssueHttp | class | class _UrllibGitHubIssueHttp |
| _UrllibGitHubIssueHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _UrllibGitLabHttp | class | class _UrllibGitLabHttp |
| _UrllibGitLabHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _UrllibGitLabIssueHttp | class | class _UrllibGitLabIssueHttp |
| _UrllibGitLabIssueHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ['SyncResult', 'sync_pr', 'should_sync'] |
| _branch_name | function | def _branch_name(patch: str, prefix: str) -> str |
| _description | function | def _description(changed_paths: tuple[str, ...], ref: str \| None) -> str |
| _diff_one | function | def _diff_one(path: str, before: str, after: str) -> str |
| _issue_body | function | def _issue_body(suggestions: tuple[OwnerSuggestion, ...]) -> str |
| _norm | function | def _norm(path: str) -> str |
| _parse_remote | function | def _parse_remote(remote_url: str) -> tuple[str, str] |
| open_coverage_issue | function | def open_coverage_issue(report: CoverageReport, suggestions: tuple[OwnerSuggestion, ...], *, transport: IssueTransport, dry_run: bool = False) -> dict \| None |
| open_docs_pr | function | def open_docs_pr(sync: SyncResult, root: Path, *, transport: PRTransport, dry_run: bool = False, **plan_kw: object) -> dict \| None |
| plan_coverage_issue | function | def plan_coverage_issue(report: CoverageReport, suggestions: tuple[OwnerSuggestion, ...]) -> IssuePlan \| None |
| plan_docs_pr | function | def plan_docs_pr(sync: SyncResult, root: Path, *, target_branch: str = 'main', ref: str \| None = None, branch_prefix: str = 'cdmon/docs-sync', labels: tuple[str, ...] = ()) -> MergeRequestPlan \| None |
| should_sync | function | def should_sync(changed_files: Iterable[str], config: MonitorConfig) -> bool |
| sync_pr | function | def sync_pr(monitor: Monitor, *, dry_run: bool = False) -> SyncResult |
<!-- CDM:END symbols -->
