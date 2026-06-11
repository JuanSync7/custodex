---
cdm:
  audience: eng-guide
  fingerprint: 85b1d6f795c648dc
  fingerprint_tiers:
    composite: 85b1d6f795c648dc
    docstring: 410fa9c1e4a3f85b
    signature: 485ed02d9070757b
  region_anchors:
    symbols:
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 061e25d0726f9341
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0a4b2d8421fb3e6f
    - 0e93a13c25171bb5
    - 16678eb7552b38fc
    - 1b639558d1e54904
    - 1e24a8bf2afa65f3
    - 2a31d3d22e1381b1
    - 500a887a1af0aaa1
    - 52121a85612dbd18
    - 54c0b178e944fd0f
    - 57c89e54d3f9d785
    - 5e949ab679208e65
    - 67cdec539298769e
    - 68e72b0e03121a2f
    - 69e027fe00218cc8
    - 75e0f149c69a5371
    - 777eb60b7980348c
    - 7c117ec7efc21252
    - 7da3b5d96c549090
    - 7f6cf136a9e76318
    - 7f9624e52ecccfb5
    - 858fb6a6bc250158
    - 86103aa2719b5725
    - 986012dbf28fcfc8
    - 98652e60d0bd4694
    - 98e70b9f66bdea9d
    - 9a4079cf2e55190e
    - 9fe6f381a9d3564c
    - a0ced4799022d5f2
    - a1d199a22b54e131
    - a84f53dd7c219030
    - a8e6f75197cf9a18
    - aaf06fee31348123
    - ad17b68aed2d1623
    - addc40895047fddd
    - afffd6e22916e9dd
    - b33f818fec911bb6
    - b8bc4141d02b5d64
    - bad0711074f2b6ae
    - c0486c1ad2d78921
    - c3981046dd7878b3
    - c40df4844d2a1629
    - c4518bed1d676c57
    - c4b16bde1a138598
    - c71b0a240e53ba5e
    - c9f0735b2ad64292
    - cad4d5ff3a52ea1f
    - d5fadb0acfd7fbb1
    - dc3eab49cb5781a5
    - dfbd6aa309fc7f81
    - e46eda1d7d1531d4
    - e6bb1a9edaaaca7e
    - ee45145bb013f44b
    - f19080767e4f6aa5
    - f1cffdeb5c7f494a
    - f2e94a23e5cbff82
    - f43f8cb24a1add81
    - f90c11e7613a8c7a
  region_hashes:
    symbols: 8e9882d8e961ecfe
  schema_version: 1.0.0
---
# central-client

> The central-system client side (EPIC E/G): the per-repo registry/identity that
> stamps which repo a review record came from before it is shipped to the
> central ingest endpoint.

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| GitInfo | class | class GitInfo(BaseModel) |
| HttpRegisterTransport | class | class HttpRegisterTransport |
| HttpRegisterTransport.__init__ | method | def __init__(self, url: str, auth_env: str \| None = None, *, http: _RegisterHttp \| None = None) -> None |
| HttpRegisterTransport.register | method | def register(self, payload: RegistrationPayload) -> dict |
| HttpSyncTransport | class | class HttpSyncTransport |
| HttpSyncTransport.__init__ | method | def __init__(self, url: str, auth_env: str \| None = None, *, http: _RegisterHttp \| None = None) -> None |
| HttpSyncTransport.sync | method | def sync(self, repo_id: str, *, mode: str) -> dict |
| RegisterTransport | class | class RegisterTransport(Protocol) |
| RegisterTransport.register | method | def register(self, payload: RegistrationPayload) -> dict |
| RegistrationPayload | class | class RegistrationPayload(BaseModel) |
| RemoteSpec | class | class RemoteSpec(BaseModel) |
| SecretBox | class | class SecretBox |
| SecretBox.__init__ | method | def __init__(self, key: bytes) -> None |
| SecretBox.open_secret | method | def open_secret(self, sealed: bytes) -> str |
| SecretBox.seal | method | def seal(self, plaintext: str) -> bytes |
| SyncResult | class | class SyncResult(BaseModel) |
| _CONFIG_SUBDIR | variable | _CONFIG_SUBDIR = ('config', 'cdmon') |
| _Cloner | class | class _Cloner(Protocol) |
| _Cloner.clone | method | def clone(self, spec: RemoteSpec, secret: str \| None, dest: Path) -> None |
| _ENV_VAR | variable | _ENV_VAR = 'CDMON_SECRET_KEY' |
| _GitCloner | class | class _GitCloner |
| _GitCloner.clone | method | def clone(self, spec: RemoteSpec, secret: str \| None, dest: Path) -> None |
| _GitRunner | variable | _GitRunner = Callable[[list[str], Path], str] |
| _JWT_BACKDATE_SECONDS | variable | _JWT_BACKDATE_SECONDS = 60 |
| _JWT_TTL_SECONDS | variable | _JWT_TTL_SECONDS = 540 |
| _KEY_BYTES | variable | _KEY_BYTES = 32 |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODES | variable | _MODES = ('git', 'local') |
| _NONCE_BYTES | variable | _NONCE_BYTES = 12 |
| _PROVIDER_USERS | variable | _PROVIDER_USERS: dict[str, str] = {'github': 'x-access-token', 'gitlab': 'oauth2'} |
| _RegisterHttp | class | class _RegisterHttp(Protocol) |
| _RegisterHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _TokenExchangeHttp | class | class _TokenExchangeHttp(Protocol) |
| _TokenExchangeHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, headers: dict[str, str]) -> dict |
| _UrllibRegisterHttp | class | class _UrllibRegisterHttp |
| _UrllibRegisterHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, token: str) -> dict |
| _UrllibTokenExchangeHttp | class | class _UrllibTokenExchangeHttp |
| _UrllibTokenExchangeHttp.request | method | def request(self, method: str, url: str, *, body: dict \| None, headers: dict[str, str]) -> dict |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ['SecretBox', 'secret_box_from_env'] |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ['RemoteSpec', 'cloned_repo'] |
| __all__ | variable | __all__ = ... |
| _b64url | function | def _b64url(raw: bytes) -> str |
| _build_clone_argv | function | def _build_clone_argv(spec: RemoteSpec, dest: Path, *, secret: str \| None) -> list[str] |
| _build_rows | function | def _build_rows(bundle: object, repo_id: str, *, mode: str, ref: str \| None, now: str) -> tuple[tuple[ConfigDocument, ...], tuple[ConfigCodeRef, ...]] |
| _clone_url | function | def _clone_url(spec: RemoteSpec, secret: str \| None) -> str |
| _coverage_report | function | def _coverage_report(bundle: object, config_dir: Path) -> coverage_mod.CoverageReport |
| _default_run_git | function | def _default_run_git(args: list[str], cwd: Path) -> str |
| _drift_summary | function | def _drift_summary(report: DriftReport, coverage_percent: float) -> dict |
| _git_info | function | def _git_info(local_path: Path, default_branch: str, *, run_git: _GitRunner) -> GitInfo |
| _open_repo | function | def _open_repo(local_path: Path, *, mode: str, branch: str, run_git: _GitRunner) -> Iterator[tuple[object, Path, GitInfo]] |
| _scrub | function | def _scrub(text: str, secret: str \| None) -> str |
| cloned_repo | function | def cloned_repo(spec: RemoteSpec, secret: str \| None, *, cloner: _Cloner \| None = None) -> Iterator[Path] |
| github_app_jwt | function | def github_app_jwt(app_id: str, private_key_pem: str, *, now: int) -> str |
| mint_github_installation_token | function | def mint_github_installation_token(app_id: str, private_key_pem: str, installation_id: str, *, now: int, http: _TokenExchangeHttp \| None = None, api_url: str = 'https://api.github.com') -> str |
| mint_gitlab_oauth_token | function | def mint_gitlab_oauth_token(token_url: str, *, client_id: str, client_secret: str, refresh_token: str, http: _TokenExchangeHttp \| None = None) -> str |
| mint_provider_token | function | def mint_provider_token(provider_kind: str, secret_material: str, *, now: int, http: _TokenExchangeHttp \| None = None) -> str |
| read_config_at | function | def read_config_at(local_path: Path, *, mode: str, branch: str, now: str, run_git: _GitRunner = _default_run_git) -> tuple[object, Path, GitInfo] |
| register_repo | function | def register_repo(identity: RepoIdentity, *, url: str, auth_env: str \| None = None, transport: RegisterTransport \| None = None, dry_run: bool = False, default_branch: str \| None = None, description: str \| None = None, auth_token: str \| None = None) -> dict \| None |
| repo_identity_from_config | function | def repo_identity_from_config(cfg: CentralConfig) -> RepoIdentity |
| run_sync | function | def run_sync(local_path: Path, repo_id: str, *, mode: str, default_branch: str = 'main', now: str, run_git: _GitRunner = _default_run_git) -> SyncResult |
| secret_box_from_env | function | def secret_box_from_env(env: Mapping[str, str] \| None = None) -> SecretBox |
| sync_repo_remote | function | def sync_repo_remote(repo_id: str, *, mode: str, url: str, auth_env: str \| None = None, transport: HttpSyncTransport \| None = None) -> dict |
<!-- CDM:END symbols -->
