---
cdm:
  audience: eng-guide
  fingerprint: 85a1f1925416f0ad
  schema_version: 1.0.0
---
# code-doc-monitor — remediation (engineering reference)

> Auto-maintained by code-doc-monitor itself (dogfood). The prose is human;
> the symbol table below is generated from the code and kept in sync.

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| ApiBackend | class | class ApiBackend |
| ApiBackend.__init__ | method | def __init__(self, *, model: str, api_key_env: str = 'ANTHROPIC_API_KEY', timeout_s: int = 120, client: ApiClient \| None = None) -> None |
| ApiBackend._build_default_client | method | def _build_default_client(self) -> ApiClient |
| ApiBackend.propose | method | def propose(self, req: FixRequest) -> BackendResult |
| ApiClient | variable | ApiClient = Callable[..., str] |
| Backend | class | class Backend(Protocol) |
| Backend.propose | method | def propose(self, req: FixRequest) -> BackendResult |
| BackendResult | class | class BackendResult(BaseModel) |
| ClaudeCodeBackend | class | class ClaudeCodeBackend |
| ClaudeCodeBackend.__init__ | method | def __init__(self, *, command: tuple[str, ...] \| None = None, model: str \| None = None, timeout_s: int = 120, runner: ProcessRunner \| None = None) -> None |
| ClaudeCodeBackend._build_argv | method | def _build_argv(self, prompt: str) -> list[str] |
| ClaudeCodeBackend.propose | method | def propose(self, req: FixRequest) -> BackendResult |
| DEFAULT_LOG_PATH | variable | DEFAULT_LOG_PATH = Path('.cdmon') / 'review-log.jsonl' |
| FileSink | class | class FileSink |
| FileSink.__init__ | method | def __init__(self, path: Path) -> None |
| FileSink.emit | method | def emit(self, record: ReviewRecord) -> None |
| FixRequest | class | class FixRequest(BaseModel) |
| HandledDrift | class | class HandledDrift(BaseModel) |
| HttpSink | class | class HttpSink |
| HttpSink.__init__ | method | def __init__(self, url: str, auth_env: str \| None = None, *, client: _PostClient \| None = None) -> None |
| HttpSink.emit | method | def emit(self, record: ReviewRecord) -> None |
| MockBackend | class | class MockBackend |
| MockBackend.propose | method | def propose(self, req: FixRequest) -> BackendResult |
| Monitor | class | class Monitor |
| Monitor.__init__ | method | def __init__(self, config: MonitorConfig, config_dir: Path, *, backend: Backend \| None = None, sink: Sink \| None = None, now: Callable[[], str] \| None = None, log_path: Path \| None = None) -> None |
| Monitor._doc_text | method | def _doc_text(self, drift: Drift, doc_path: Path) -> str |
| Monitor._record_for | method | def _record_for(self, drift: Drift, result: BackendResult, surface: DocumentSurface) -> ReviewRecord |
| Monitor._spec_for | method | def _spec_for(self, doc_id: str) -> DocumentSpec |
| Monitor.check | method | def check(self) -> DriftReport |
| Monitor.run | method | def run(self, *, apply: bool \| None = None) -> MonitorResult |
| MonitorResult | class | class MonitorResult(BaseModel) |
| NullSink | class | class NullSink |
| NullSink.emit | method | def emit(self, record: ReviewRecord) -> None |
| ProcessRunner | variable | ProcessRunner = Callable[[list[str], str, int], str] |
| ProposedFix | class | class ProposedFix(BaseModel) |
| ProposedFixLike | class | class ProposedFixLike(Protocol) |
| ReviewRecord | class | class ReviewRecord(BaseModel) |
| Sink | class | class Sink(Protocol) |
| Sink.emit | method | def emit(self, record: ReviewRecord) -> None |
| Verdict | class | class Verdict(str, Enum) |
| _DEFAULT_API_MODEL | variable | _DEFAULT_API_MODEL = 'claude-sonnet-4-20250514' |
| _INVALIDATE_MARKERS | variable | _INVALIDATE_MARKERS = ('docstring', 'comment', 'private') |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _PROMPT_TOKEN | variable | _PROMPT_TOKEN = '{prompt}' |
| _PostClient | class | class _PostClient(Protocol) |
| _PostClient.post | method | def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None |
| _Templates | variable | _Templates = Mapping[str, RegionTemplate] \| None |
| _UrllibClient | class | class _UrllibClient |
| _UrllibClient.post | method | def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None |
| __all__ | variable | __all__ = ['append', 'read_all', 'summarize'] |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| _anthropic_messages_call | function | def _anthropic_messages_call(model: str, prompt: str, timeout: int, api_key: str) -> str |
| _corrected | function | def _corrected(doc: Doc, surface: DocumentSurface, templates: _Templates = None) -> str |
| _default_now | function | def _default_now() -> str |
| _default_process_runner | function | def _default_process_runner(argv: list[str], stdin: str, timeout_s: int) -> str |
| _extract_json_object | function | def _extract_json_object(text: str) -> str |
| append | function | def append(path: Path, record: ReviewRecord) -> None |
| apply_fix | function | def apply_fix(doc_path: Path, fix: ProposedFixLike) -> bool |
| build_prompt | function | def build_prompt(req: FixRequest) -> str |
| make_backend | function | def make_backend(cfg: BackendConfig) -> Backend |
| make_sink | function | def make_sink(cfg: CentralConfig) -> Sink |
| new_record_id | function | def new_record_id(doc_id: str, surface_hash: str, detected_at: str) -> str |
| parse_backend_json | function | def parse_backend_json(text: str) -> BackendResult |
| read_all | function | def read_all(path: Path) -> list[ReviewRecord] |
| regenerate_regions | function | def regenerate_regions(doc_path: Path, surface: DocumentSurface, templates: _Templates = None) -> bool |
| render_corrected | function | def render_corrected(doc_text: str, surface: DocumentSurface, templates: _Templates = None) -> str |
| review_record_schema | function | def review_record_schema() -> dict |
| summarize | function | def summarize(records: list[ReviewRecord]) -> dict |
<!-- CDM:END symbols -->
