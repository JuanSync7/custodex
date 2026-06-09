---
cdm:
  audience: eng-guide
  fingerprint: 8df8c1968d4ae1d6
  region_hashes:
    symbols: 6a2a00e0ff873747
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
| GitLabIssueTransport | class | class GitLabIssueTransport |
| GitLabIssueTransport.__init__ | method | def __init__(self, *, project_id: str, token: str, api_url: str = 'https://gitlab.com/api/v4', http: _IssueHttp \| None = None) -> None |
| GitLabIssueTransport.from_env | method | def from_env(cls, *, project_env: str = 'CI_PROJECT_ID', token_env: str = 'CDMON_GITLAB_TOKEN', api_env: str = 'CI_API_V4_URL') -> GitLabIssueTransport |
| GitLabIssueTransport.submit | method | def submit(self, plan: IssuePlan) -> dict |
| GitLabTransport | class | class GitLabTransport |
| GitLabTransport.__init__ | method | def __init__(self, *, project_id: str, token: str, api_url: str = 'https://gitlab.com/api/v4', http: _GitLabHttp \| None = None) -> None |
| GitLabTransport._project_url | method | def _project_url(self) -> str |
| GitLabTransport.from_env | method | def from_env(cls, *, project_env: str = 'CI_PROJECT_ID', token_env: str = 'CDMON_GITLAB_TOKEN', api_env: str = 'CI_API_V4_URL') -> GitLabTransport |
| GitLabTransport.submit | method | def submit(self, plan: MergeRequestPlan) -> dict |
| IssuePlan | class | class IssuePlan(BaseModel) |
| IssueTransport | class | class IssueTransport(Protocol) |
| IssueTransport.submit | method | def submit(self, plan: IssuePlan) -> dict |
| MergeRequestPlan | class | class MergeRequestPlan(BaseModel) |
| PRTransport | class | class PRTransport(Protocol) |
| PRTransport.submit | method | def submit(self, plan: MergeRequestPlan) -> dict |
| SyncResult | class | class SyncResult(BaseModel) |
| _DEFAULT_LABELS | variable | _DEFAULT_LABELS: tuple[str, ...] = ('documentation',) |
| _GitLabHttp | class | class _GitLabHttp(Protocol) |
| _GitLabHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _IssueHttp | class | class _IssueHttp(Protocol) |
| _IssueHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
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
| open_coverage_issue | function | def open_coverage_issue(report: CoverageReport, suggestions: tuple[OwnerSuggestion, ...], *, transport: IssueTransport, dry_run: bool = False) -> dict \| None |
| open_docs_pr | function | def open_docs_pr(sync: SyncResult, root: Path, *, transport: PRTransport, dry_run: bool = False, **plan_kw: object) -> dict \| None |
| plan_coverage_issue | function | def plan_coverage_issue(report: CoverageReport, suggestions: tuple[OwnerSuggestion, ...]) -> IssuePlan \| None |
| plan_docs_pr | function | def plan_docs_pr(sync: SyncResult, root: Path, *, target_branch: str = 'main', ref: str \| None = None, branch_prefix: str = 'cdmon/docs-sync', labels: tuple[str, ...] = ()) -> MergeRequestPlan \| None |
| should_sync | function | def should_sync(changed_files: Iterable[str], config: MonitorConfig) -> bool |
| sync_pr | function | def sync_pr(monitor: Monitor, *, dry_run: bool = False) -> SyncResult |
<!-- CDM:END symbols -->
