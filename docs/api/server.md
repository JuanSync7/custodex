---
cdm:
  audience: eng-guide
  fingerprint: 754f5ae255d2a04e
  fingerprint_tiers:
    composite: 754f5ae255d2a04e
    docstring: c84cf5fc44fde0ae
    signature: ccdcf7f2c2d90fdd
  region_anchors:
    symbols:
    - 01235c35a6ca9c5a
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 0771e9c38021847a
    - 078071db111bf8e9
    - 0879b73cbc4b94f3
    - 0a12e5898c92bfc6
    - 0ba9f544b6031399
    - 0cacb8ca5eedea2a
    - 0d6e4079e36703eb
    - 0da26345c95767b0
    - 1103be93877e8ee3
    - 11192a3ac2c801a0
    - 11c8b69ce1ef8fa5
    - 14bee4e49a9e3aac
    - 1749c6d35103f236
    - 1849f8779eeb8a48
    - 1dd91e025bf15c39
    - 1e5bf2178ac0dcee
    - 1f69bc8b615da116
    - 20a7e2c55efbadad
    - 2434559dabc32bfd
    - 28b5e36b04212582
    - 2940596e7459cadb
    - 2ebf4d85ced01b25
    - 2fd1b3982610ecaa
    - 2fe3c356023e3752
    - 300741ad0adeb325
    - 318817d3d5c32a67
    - 31926744a2b193eb
    - 31a3e50b8f5221db
    - 331fcb711b55798f
    - 337ab9db6bad7258
    - 369c045a16e5d732
    - 37be54e1ed20d07e
    - 39af45b6529451c2
    - 3adf537f9d4ef790
    - 3e373817e4dd55ad
    - 3ff4b656757aa5ad
    - 413803e6bb0f7787
    - 4507f4be9071d9ac
    - 466b37ad4e6f8df6
    - 4683b7ff2ad716ef
    - 47060d549acbbd29
    - 47b7ab5158c08602
    - 4859fc3890810652
    - 48e7f4aee970761d
    - 497e2d2cf3d969e0
    - 4a4f3ab2f63a4d70
    - 4a5a5b4f0f371856
    - 4b6efaecc8f7dadc
    - 4e7c579155b8c53d
    - 4e8617b2d6609600
    - 536d95baa30f412c
    - 5469690a8bc40782
    - 550988527d9b6ea0
    - 5832414bab2bf2ab
    - 5975bdeeb9d7dc5f
    - 5b32fe40a1173dc0
    - 60980aca9bc67ef9
    - 60dcd28f23471391
    - 63716b31cca0678a
    - 64cfdd20c9f4e98a
    - 6505cc5091801d16
    - 670deb3ba37e4a33
    - 688b71b0015f2336
    - 691a3bef6d4d3657
    - 69695ff6396b76d1
    - 6d3f69617a6b1d78
    - 6ef2f6eec3cd16ae
    - 6f9b25f7411f15c2
    - 71613e3abdfdcdb1
    - 726858785015ad76
    - 76dafbeb7152f48e
    - 7718c1f874b600bf
    - 77a49c9a8c63382b
    - 7a8eda9f0a5f3bf7
    - 7b47361aad19bb48
    - 7ca05ecd14ba0bc8
    - 8130e983bf38c2e9
    - 83811d5262989de4
    - 849814ce45119715
    - 84e8159b6a779562
    - 85300682e54b5ea1
    - 89e835f3c782a294
    - 8a290d89bd71388a
    - 91e25a1bd843b417
    - 932c919339ac3a6d
    - 95027cf1e5bce55b
    - 9877e4d3ed2473bb
    - 99e2ad2b1f73cdf2
    - 9a3b73a7aaa6fb99
    - 9bac928da4b1f265
    - 9db38499b75f5cf2
    - a0660fe9e34e2695
    - a0926f0073c9c247
    - a2b2bac5098995ec
    - a2bc0adb27fe1fc9
    - a56f31e61f8741ce
    - abb903669fd3f39a
    - b0621470d5ce4290
    - b3127a5e9ffc9535
    - b3248dc191833eee
    - b70299153e99744b
    - bb863595c216b603
    - c00b14bad6d13e8b
    - c130cb9540867907
    - c275ae37d742123c
    - c36455b6a4d33158
    - c3981046dd7878b3
    - c6a7a34908783b74
    - c843a2a6e5815d67
    - ca6c89214a079f51
    - ca7be50c11d11708
    - cbed02dfb39a3bd9
    - cf4613c27c5db0da
    - cfc0082becb20fac
    - d1301a344a55bfa7
    - d402bd229d320919
    - d51df2124b2d643d
    - d5eaad792e2d0e52
    - d862aa06aa10a024
    - d993fe85a189c2e2
    - d9d91a8257975edf
    - da9da02db1d5d5e0
    - db401b971ca3b2f9
    - de106aa8e1278a0c
    - e435b85a94b85b45
    - e8b7003029e54d54
    - e94c061a7001dbd7
    - ee7da936b5cb293e
    - f182307bbd168034
    - f2f3868ff1559642
    - f501838065644127
    - f7e36c5633592985
    - fa2f6597462ddabd
  region_hashes:
    symbols: 3f34e6f88cbc0eb5
  schema_version: 1.0.0
---
# server

> EPIC G central server (engineering reference): the FastAPI ingest/query app
> (`app`), the persistence service over review records (`store`), and the
> SQLAlchemy schema + session/engine layer it sits on (`db`).

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| AddCodeRefEdit | class | class AddCodeRefEdit(BaseModel) |
| ApplyFixResponse | class | class ApplyFixResponse(BaseModel) |
| Base | class | class Base(DeclarativeBase) |
| ConfigCodeRef | class | class ConfigCodeRef(BaseModel) |
| ConfigCodeRefRow | class | class ConfigCodeRefRow(Base) |
| ConfigContextRef | class | class ConfigContextRef(BaseModel) |
| ConfigDocument | class | class ConfigDocument(BaseModel) |
| ConfigDocumentRow | class | class ConfigDocumentRow(Base) |
| ConfigEdit | variable | ConfigEdit = ... |
| ConfigEditRow | class | class ConfigEditRow(Base) |
| CoverageIngest | class | class CoverageIngest(BaseModel) |
| CoverageSnapshotRow | class | class CoverageSnapshotRow(Base) |
| CreateDocEdit | class | class CreateDocEdit(BaseModel) |
| DocStyleOptions | class | class DocStyleOptions(BaseModel) |
| DocumentTree | class | class DocumentTree(BaseModel) |
| EditCodeRef | class | class EditCodeRef(BaseModel) |
| EditContextRef | class | class EditContextRef(BaseModel) |
| EditDocStyle | class | class EditDocStyle(BaseModel) |
| EditableConfigTree | class | class EditableConfigTree(BaseModel) |
| EditableDocument | class | class EditableDocument(BaseModel) |
| GenerateRequest | class | class GenerateRequest(BaseModel) |
| GenerateResponse | class | class GenerateResponse(BaseModel) |
| InMemoryStore | class | class InMemoryStore |
| InMemoryStore.__init__ | method | def __init__(self) -> None |
| InMemoryStore.add_config_edit | method | def add_config_edit(self, repo_id: str, edit: ConfigEdit, *, edit_id: str, created_at: str) -> None |
| InMemoryStore.add_coverage_snapshot | method | def add_coverage_snapshot(self, repo_id: str, captured_at: str, snapshot: dict) -> None |
| InMemoryStore.add_record | method | def add_record(self, repo_id: str, record: ReviewRecord) -> None |
| InMemoryStore.add_repo | method | def add_repo(self, payload: RegistrationPayload) -> None |
| InMemoryStore.add_resolution | method | def add_resolution(self, resolution: ResolutionRecord) -> None |
| InMemoryStore.add_sync_run | method | def add_sync_run(self, run: SyncRun) -> None |
| InMemoryStore.code_refs_for | method | def code_refs_for(self, repo_id: str, doc_id: str \| None = None, sync_kind: str \| None = None) -> list[ConfigCodeRef] |
| InMemoryStore.config_documents_for | method | def config_documents_for(self, repo_id: str, sync_kind: str \| None = None) -> list[ConfigDocument] |
| InMemoryStore.config_edits_for | method | def config_edits_for(self, repo_id: str, status: str \| None = None) -> list[StoredConfigEdit] |
| InMemoryStore.coverage_for | method | def coverage_for(self, repo_id: str) -> list[dict] |
| InMemoryStore.get_repo | method | def get_repo(self, repo_id: str) -> RegisteredRepo \| None |
| InMemoryStore.latest_sync_run | method | def latest_sync_run(self, repo_id: str, sync_kind: str \| None = None) -> SyncRun \| None |
| InMemoryStore.list_repos | method | def list_repos(self) -> list[RegisteredRepo] |
| InMemoryStore.mark_config_edits | method | def mark_config_edits(self, repo_id: str, edit_ids: list[str], status: str, *, at: str) -> None |
| InMemoryStore.records_for | method | def records_for(self, repo_id: str, *, verdict: str \| None = None, drift_kind: str \| None = None, audience: str \| None = None, doc_id: str \| None = None, limit: int \| None = None, offset: int = 0) -> list[ReviewRecord] |
| InMemoryStore.replace_config | method | def replace_config(self, repo_id: str, sync_kind: str, documents: list[ConfigDocument], code_refs: list[ConfigCodeRef]) -> None |
| InMemoryStore.repo_token_hash | method | def repo_token_hash(self, repo_id: str) -> str \| None |
| InMemoryStore.resolutions_for_repo | method | def resolutions_for_repo(self, repo_id: str, record_id: str \| None = None) -> list[ResolutionRecord] |
| InMemoryStore.sync_runs_for | method | def sync_runs_for(self, repo_id: str, sync_kind: str \| None = None) -> list[SyncRun] |
| RecordRow | class | class RecordRow(Base) |
| RegisteredRepo | class | class RegisteredRepo(BaseModel) |
| RemoveCodeRefEdit | class | class RemoveCodeRefEdit(BaseModel) |
| RepoHealth | class | class RepoHealth(BaseModel) |
| RepoRow | class | class RepoRow(Base) |
| RepoStatus | class | class RepoStatus(BaseModel) |
| RepoTelemetry | class | class RepoTelemetry(BaseModel) |
| ResolutionRow | class | class ResolutionRow(Base) |
| SetContextRefsEdit | class | class SetContextRefsEdit(BaseModel) |
| SetDocStyleEdit | class | class SetDocStyleEdit(BaseModel) |
| ShapeStat | class | class ShapeStat(BaseModel) |
| SqlStore | class | class SqlStore |
| SqlStore.__init__ | method | def __init__(self, engine: Engine) -> None |
| SqlStore._session | method | def _session(self) -> Session |
| SqlStore.add_config_edit | method | def add_config_edit(self, repo_id: str, edit: ConfigEdit, *, edit_id: str, created_at: str) -> None |
| SqlStore.add_coverage_snapshot | method | def add_coverage_snapshot(self, repo_id: str, captured_at: str, snapshot: dict) -> None |
| SqlStore.add_record | method | def add_record(self, repo_id: str, record: ReviewRecord) -> None |
| SqlStore.add_repo | method | def add_repo(self, payload: RegistrationPayload) -> None |
| SqlStore.add_resolution | method | def add_resolution(self, resolution: ResolutionRecord) -> None |
| SqlStore.add_sync_run | method | def add_sync_run(self, run: SyncRun) -> None |
| SqlStore.code_refs_for | method | def code_refs_for(self, repo_id: str, doc_id: str \| None = None, sync_kind: str \| None = None) -> list[ConfigCodeRef] |
| SqlStore.config_documents_for | method | def config_documents_for(self, repo_id: str, sync_kind: str \| None = None) -> list[ConfigDocument] |
| SqlStore.config_edits_for | method | def config_edits_for(self, repo_id: str, status: str \| None = None) -> list[StoredConfigEdit] |
| SqlStore.coverage_for | method | def coverage_for(self, repo_id: str) -> list[dict] |
| SqlStore.coverage_snapshots_for | method | def coverage_snapshots_for(self, repo_id: str) -> list[dict] |
| SqlStore.get_repo | method | def get_repo(self, repo_id: str) -> RegisteredRepo \| None |
| SqlStore.latest_sync_run | method | def latest_sync_run(self, repo_id: str, sync_kind: str \| None = None) -> SyncRun \| None |
| SqlStore.list_repos | method | def list_repos(self) -> list[RegisteredRepo] |
| SqlStore.mark_config_edits | method | def mark_config_edits(self, repo_id: str, edit_ids: list[str], status: str, *, at: str) -> None |
| SqlStore.records_for | method | def records_for(self, repo_id: str, *, verdict: str \| None = None, drift_kind: str \| None = None, audience: str \| None = None, doc_id: str \| None = None, limit: int \| None = None, offset: int = 0) -> list[ReviewRecord] |
| SqlStore.replace_config | method | def replace_config(self, repo_id: str, sync_kind: str, documents: list[ConfigDocument], code_refs: list[ConfigCodeRef]) -> None |
| SqlStore.repo_token_hash | method | def repo_token_hash(self, repo_id: str) -> str \| None |
| SqlStore.resolutions_for | method | def resolutions_for(self, record_id: str) -> list[ResolutionRecord] |
| SqlStore.resolutions_for_repo | method | def resolutions_for_repo(self, repo_id: str, record_id: str \| None = None) -> list[ResolutionRecord] |
| SqlStore.sync_runs_for | method | def sync_runs_for(self, repo_id: str, sync_kind: str \| None = None) -> list[SyncRun] |
| Store | class | class Store(Protocol) |
| Store.add_config_edit | method | def add_config_edit(self, repo_id: str, edit: ConfigEdit, *, edit_id: str, created_at: str) -> None |
| Store.add_coverage_snapshot | method | def add_coverage_snapshot(self, repo_id: str, captured_at: str, snapshot: dict) -> None |
| Store.add_record | method | def add_record(self, repo_id: str, record: ReviewRecord) -> None |
| Store.add_repo | method | def add_repo(self, payload: RegistrationPayload) -> None |
| Store.add_resolution | method | def add_resolution(self, resolution: ResolutionRecord) -> None |
| Store.add_sync_run | method | def add_sync_run(self, run: SyncRun) -> None |
| Store.code_refs_for | method | def code_refs_for(self, repo_id: str, doc_id: str \| None = None, sync_kind: str \| None = None) -> list[ConfigCodeRef] |
| Store.config_documents_for | method | def config_documents_for(self, repo_id: str, sync_kind: str \| None = None) -> list[ConfigDocument] |
| Store.config_edits_for | method | def config_edits_for(self, repo_id: str, status: str \| None = None) -> list[StoredConfigEdit] |
| Store.coverage_for | method | def coverage_for(self, repo_id: str) -> list[dict] |
| Store.get_repo | method | def get_repo(self, repo_id: str) -> RegisteredRepo \| None |
| Store.latest_sync_run | method | def latest_sync_run(self, repo_id: str, sync_kind: str \| None = None) -> SyncRun \| None |
| Store.list_repos | method | def list_repos(self) -> list[RegisteredRepo] |
| Store.mark_config_edits | method | def mark_config_edits(self, repo_id: str, edit_ids: list[str], status: str, *, at: str) -> None |
| Store.records_for | method | def records_for(self, repo_id: str, *, verdict: str \| None = None, drift_kind: str \| None = None, audience: str \| None = None, doc_id: str \| None = None, limit: int \| None = None, offset: int = 0) -> list[ReviewRecord] |
| Store.replace_config | method | def replace_config(self, repo_id: str, sync_kind: str, documents: list[ConfigDocument], code_refs: list[ConfigCodeRef]) -> None |
| Store.repo_token_hash | method | def repo_token_hash(self, repo_id: str) -> str \| None |
| Store.resolutions_for_repo | method | def resolutions_for_repo(self, repo_id: str, record_id: str \| None = None) -> list[ResolutionRecord] |
| Store.sync_runs_for | method | def sync_runs_for(self, repo_id: str, sync_kind: str \| None = None) -> list[SyncRun] |
| StoredConfigEdit | class | class StoredConfigEdit(BaseModel) |
| SyncRequest | class | class SyncRequest(BaseModel) |
| SyncRun | class | class SyncRun(BaseModel) |
| SyncRunRow | class | class SyncRunRow(Base) |
| WIKI_SECTIONS | variable | WIKI_SECTIONS = ... |
| _CONFIG_EDIT_ADAPTER | variable | _CONFIG_EDIT_ADAPTER: TypeAdapter[ConfigEdit] = TypeAdapter(ConfigEdit) |
| _CONFIG_SUBDIR | variable | _CONFIG_SUBDIR = ('config', 'cdmon') |
| _DEFAULT_BRANCH | variable | _DEFAULT_BRANCH = 'main' |
| _EDIT_CONFIG | variable | _EDIT_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _IGNORED_FILES_CAP | variable | _IGNORED_FILES_CAP = 200 |
| _LOG | variable | _LOG = logging.getLogger('code_doc_monitor.server') |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| _compute_health | function | def _compute_health(store: Store, repo_id: str) -> RepoHealth |
| _compute_status | function | def _compute_status(store: Store, repo_id: str) -> RepoStatus |
| _compute_telemetry | function | def _compute_telemetry(store: Store, repo_id: str) -> RepoTelemetry |
| _default_now | function | def _default_now() -> str |
| _default_static_dir | function | def _default_static_dir() -> Path \| None |
| _disk_editable_parts | function | def _disk_editable_parts(local_path: str \| None) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], DocStyleOptions] |
| _json_type | function | def _json_type() -> TypeEngine[dict] |
| _load_wiki_sections | function | def _load_wiki_sections(wiki_dir: Path \| None) -> list[dict[str, str]] |
| _new_edit_id | function | def _new_edit_id(repo_id: str, edit: ConfigEdit, now: str) -> str |
| _parse_iso | function | def _parse_iso(value: str) -> datetime |
| _registered_repo | function | def _registered_repo(row: RepoRow) -> RegisteredRepo |
| _run_migrations | function | def _run_migrations(url: str) -> None |
| _scan_doc_styles | function | def _scan_doc_styles(templates_root: Path) -> DocStyleOptions |
| _wiki_dir | function | def _wiki_dir() -> Path \| None |
| build_standalone_app | function | def build_standalone_app(repo_root: Path, *, repo_id: str \| None = None, now: str) -> object |
| build_standalone_store | function | def build_standalone_store(repo_root: Path, *, repo_id: str \| None = None, now: str) -> InMemoryStore |
| create_all | function | def create_all(engine: Engine) -> None |
| create_app | function | def create_app(store: Store \| None = None, *, static_dir: Path \| None = None, wiki_dir: Path \| None = None, clock: Callable[[], str] = _default_now) -> FastAPI |
| effective_identity | function | def effective_identity(payload: RegistrationPayload) -> RepoIdentity |
| engine_from_url | function | def engine_from_url(url: str) -> Engine |
| hash_token | function | def hash_token(token: str) -> str |
| main | function | def main() -> None |
| resolve_repo_id | function | def resolve_repo_id(repo_root: Path, repo_id: str \| None) -> str |
| store_from_env | function | def store_from_env() -> Store |
<!-- CDM:END symbols -->
