---
cdm:
  audience: eng-guide
  fingerprint: 6dafb6da173d4a99
  fingerprint_tiers:
    composite: 6dafb6da173d4a99
    docstring: 9c4e6ddadc393aa4
    signature: 72778b04ea833c69
  region_anchors:
    symbols:
    - 000f066b671bb0ba
    - 00a7ce0cbacbcf4c
    - 04b3eb1ec27586a1
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0a412344fabd6422
    - 0b0fe3e2145090f0
    - 0ba04f40d95602fe
    - 101c5c19d00d50c7
    - 10af53c00976b733
    - 12c0956234545317
    - 14de115be3e0e2e2
    - 182cb31b005cd1f6
    - 190b2af0b34383b7
    - 1ca29bd3a3b4b625
    - 1d17d141d76bc3bc
    - 1ea7d09f8477a491
    - 1f492dd8d1d03dee
    - 20d1a793870421e1
    - 24693f46e2eb5f98
    - 2e716e21070d739d
    - 2fb4019a35e427e8
    - 310c830c7dcd960a
    - 3450707237dd8d47
    - 35d866910e259e39
    - 36b9c9cb73b79163
    - 3a15c9cb0fa4bc72
    - 3b708fe97f56ac20
    - 3dfa2b7510a5aee9
    - 4063c79b7436b301
    - 41eb1e4d3263285b
    - 4235a38bac272c55
    - 472f53d5ed2d4191
    - 495f8d997abb0827
    - 496ea4e48ea5ee9c
    - 499bd50ef74cffe5
    - 49b30d3ad899537e
    - 4a36f89dafb0a101
    - 4c2e1df4570bebd6
    - 4d7314369ab19a34
    - 4f2cdf9e58e13c11
    - 50eee1f18330d45e
    - 5522738f3007a454
    - 576183587590d09c
    - 591813cff22d653f
    - 5a8d926e4f46ec09
    - 5b3f7f5938d4e853
    - 5bea2c1f3984fd17
    - 5c55d03fd5d5c477
    - 5ca8e2a5128ffc67
    - 5e7f06142e977dfd
    - 5ebe9beb1b4ba494
    - 5f0f67562e85cc5b
    - 63f15dd24f76a485
    - 6aefe06c88cc6aa5
    - 6c452d3a760ba1ad
    - 6dbbdc54ad939e7f
    - 70df2bfd15daec86
    - 71067f90c963ec79
    - 7148c31132fd948d
    - 733988d48829d546
    - 734cd0dc97a71153
    - 736c6068e253c25c
    - 73daeb0abf7030ac
    - 7449bad0723fe283
    - 750a33ca97ad80ca
    - 769ec087fea9c42a
    - 78075ff39fa34460
    - 7a7ba00dda5103af
    - 7ae72b95145f540e
    - 7fcfe074fe821547
    - 8086ff6b242489a7
    - 9084d14f98d22340
    - 90d66183e64d3c8e
    - 940635f16be1e148
    - 96d61d282831ff04
    - 98cf07abfb489c1c
    - 99c81d63635d006a
    - 9ab2707615526b01
    - 9c0fc2cda7817f04
    - a1311a0b2ec8a111
    - a1f9f193ac6ee97c
    - a4edbfd82a2ad5f2
    - a5ea51e88c522b3b
    - aa2bfe52462f5e54
    - aa435b9aa88eb0a1
    - abd4ffb57b0e2dcf
    - ae091177c08a97a0
    - ae2c81c23afc62ef
    - ae524b54d9b5acbe
    - af97b52edf8ed587
    - b08f821c395d4fbe
    - b32d5dbe5299d7e5
    - b57e25e25b34c845
    - b9a532775dff1fb6
    - baa9735317b4aa72
    - bae9264d6d972b80
    - bc10de9bfef9c2cb
    - bc1f12077b34309a
    - bd20edc0c3d6528a
    - bfab8aab7aaf99ef
    - c1ef372c178707e3
    - c3981046dd7878b3
    - c5c229be4c0d7c0a
    - ca120419f251c74b
    - ca79e52557341f36
    - d25352aee0327514
    - d4055fafa3794fa8
    - e45887ebba1b35ff
    - e476fdc0cb20462c
    - e619c1c43ea828e3
    - e9e770dcee78b3c7
    - ec32d5357eb214b6
    - ed9a173a86d743b5
    - eed1b161f8dc56d4
    - ef9183ad431d7457
    - ef97a7d1515b74d6
    - f2b1c8584a68d310
    - f75907b9759399c4
    - f84f756b48f26fd9
    - fa2f6597462ddabd
    - fe9d46d6cc2990f0
  region_hashes:
    symbols: 2b2b0ac83969e611
  schema_version: 1.0.0
---
# custodex — remediation (engineering reference)

> Auto-maintained by custodex itself (dogfood). The prose is human;
> the symbol table below is generated from the code and kept in sync.

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| AcceptanceCheck | class | class AcceptanceCheck(BaseModel) |
| ApiBackend | class | class ApiBackend |
| ApiBackend.__init__ | method | def __init__(self, *, model: str, api_key_env: str = 'ANTHROPIC_API_KEY', timeout_s: int = 120, client: ApiClient \| None = None) -> None |
| ApiBackend._build_default_client | method | def _build_default_client(self) -> ApiClient |
| ApiBackend.propose | method | def propose(self, req: FixRequest) -> BackendResult |
| ApiClient | variable | ApiClient = Callable[..., str] |
| ApplyFixResult | class | class ApplyFixResult(BaseModel) |
| Backend | class | class Backend(Protocol) |
| Backend.propose | method | def propose(self, req: FixRequest) -> BackendResult |
| BackendResult | class | class BackendResult(BaseModel) |
| ClaudeCodeBackend | class | class ClaudeCodeBackend |
| ClaudeCodeBackend.__init__ | method | def __init__(self, *, command: tuple[str, ...] \| None = None, model: str \| None = None, timeout_s: int = 120, runner: ProcessRunner \| None = None) -> None |
| ClaudeCodeBackend._build_argv | method | def _build_argv(self, prompt: str) -> list[str] |
| ClaudeCodeBackend.propose | method | def propose(self, req: FixRequest) -> BackendResult |
| DEFAULT_EXEMPLAR_TOP_N | variable | DEFAULT_EXEMPLAR_TOP_N = 3 |
| DEFAULT_LOG_PATH | variable | DEFAULT_LOG_PATH = Path('.cdmon') / 'review-log.jsonl' |
| DEFAULT_RESOLUTIONS_PATH | variable | DEFAULT_RESOLUTIONS_PATH = Path('.cdmon') / 'resolutions.jsonl' |
| DriftTicket | class | class DriftTicket(BaseModel) |
| FileSink | class | class FileSink |
| FileSink.__init__ | method | def __init__(self, path: Path) -> None |
| FileSink.emit | method | def emit(self, record: ReviewRecord) -> None |
| FixRequest | class | class FixRequest(BaseModel) |
| GenerateResult | class | class GenerateResult(BaseModel) |
| HandledDrift | class | class HandledDrift(BaseModel) |
| HttpSink | class | class HttpSink |
| HttpSink.__init__ | method | def __init__(self, url: str, auth_env: str \| None = None, *, repo: RepoIdentity, outbox: Path \| None = None, max_retries: int = 2, client: _PostClient \| None = None) -> None |
| HttpSink._drain | method | def _drain(self, client: _PostClient) -> bool |
| HttpSink._enqueue | method | def _enqueue(self, envelope: IngestEnvelope) -> None |
| HttpSink._headers | method | def _headers(self) -> dict[str, str] |
| HttpSink._read_outbox | method | def _read_outbox(self) -> list[IngestEnvelope] |
| HttpSink._try_send | method | def _try_send(self, client: _PostClient, envelope: IngestEnvelope) -> bool |
| HttpSink._write_outbox | method | def _write_outbox(self, envelopes: list[IngestEnvelope]) -> None |
| HttpSink.emit | method | def emit(self, record: ReviewRecord) -> None |
| IngestEnvelope | class | class IngestEnvelope(BaseModel) |
| MockBackend | class | class MockBackend |
| MockBackend.propose | method | def propose(self, req: FixRequest) -> BackendResult |
| Monitor | class | class Monitor |
| Monitor.__init__ | method | def __init__(self, config: MonitorConfig, config_dir: Path, *, backend: Backend \| None = None, sink: Sink \| None = None, now: Callable[[], str] \| None = None, log_path: Path \| None = None, source_sha: str \| None = None, use_exemplars: bool = False, resolutions_path: Path \| None = None, exemplar_top_n: int = DEFAULT_EXEMPLAR_TOP_N, rules: tuple[PromotionRule, ...] = (), doc_style: DocStyleMap \| None = None) -> None |
| Monitor._doc_text | method | def _doc_text(self, drift: Drift, doc_path: Path) -> str |
| Monitor._record_for | method | def _record_for(self, drift: Drift, result: BackendResult, surface: DocumentSurface, *, rule_sourced: bool = False) -> ReviewRecord |
| Monitor._retrieve_exemplars | method | def _retrieve_exemplars(self, drift: Drift, surface_hash: str, records: list[ReviewRecord], resolutions: list[ResolutionRecord]) -> tuple[Exemplar, ...] |
| Monitor._spec_for | method | def _spec_for(self, doc_id: str) -> DocumentSpec |
| Monitor._style_guidance_for | method | def _style_guidance_for(self, drift: Drift, region_mode: RegionMode) -> str \| None |
| Monitor._target_record | method | def _target_record(self, drift: Drift, surface_hash: str) -> ReviewRecord |
| Monitor.check | method | def check(self) -> DriftReport |
| Monitor.run | method | def run(self, *, apply: bool \| None = None) -> MonitorResult |
| MonitorResult | class | class MonitorResult(BaseModel) |
| NullSink | class | class NullSink |
| NullSink.emit | method | def emit(self, record: ReviewRecord) -> None |
| ProcessRunner | variable | ProcessRunner = Callable[[list[str], str, int], str] |
| ProposedFix | class | class ProposedFix(BaseModel) |
| ProposedFixLike | class | class ProposedFixLike(Protocol) |
| RULE_CAUSE_PREFIX | variable | RULE_CAUSE_PREFIX = 'promoted rule' |
| RepoIdentity | class | class RepoIdentity(BaseModel) |
| Resolution | class | class Resolution(str, Enum) |
| ResolutionRecord | class | class ResolutionRecord(BaseModel) |
| ReviewRecord | class | class ReviewRecord(BaseModel) |
| Sink | class | class Sink(Protocol) |
| Sink.emit | method | def emit(self, record: ReviewRecord) -> None |
| TicketSeverity | class | class TicketSeverity(str, Enum) |
| TicketStatus | class | class TicketStatus(str, Enum) |
| Verdict | class | class Verdict(str, Enum) |
| _CONFIG_SUBDIR | variable | _CONFIG_SUBDIR = ('config', 'cdmon') |
| _CONTEXT_REFS_HEADER | variable | _CONTEXT_REFS_HEADER = ... |
| _DEFAULT_API_MODEL | variable | _DEFAULT_API_MODEL = 'claude-sonnet-4-20250514' |
| _FIX_VERDICTS | variable | _FIX_VERDICTS = frozenset({Verdict.FIX}) |
| _INDEX_UPDATED_RE | variable | _INDEX_UPDATED_RE = re.compile('^updated:[^\\\\n]*$', re.MULTILINE) |
| _INVALIDATE_MARKERS | variable | _INVALIDATE_MARKERS = ('docstring', 'comment', 'private') |
| _LLM_PROSE_CLAUSE | variable | _LLM_PROSE_CLAUSE = ... |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _Modes | variable | _Modes = Mapping[str, RegionMode] \| None |
| _PROMPT_TOKEN | variable | _PROMPT_TOKEN = '{prompt}' |
| _PostClient | class | class _PostClient(Protocol) |
| _PostClient.post | method | def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None |
| _Templates | variable | _Templates = Mapping[str, RegionTemplate] \| None |
| _UrllibClient | class | class _UrllibClient |
| _UrllibClient.post | method | def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| _acceptance_criteria | function | def _acceptance_criteria(verdict: Verdict) -> tuple[AcceptanceCheck, ...] |
| _anthropic_messages_call | function | def _anthropic_messages_call(model: str, prompt: str, timeout: int, api_key: str) -> str |
| _apply_doc_style | function | def _apply_doc_style(config_dir: Path, repo_root: Path, doc_id: str, override: EditDocStyle, *, doc_style_pointer: str, now: str) -> None |
| _apply_unit_edit | function | def _apply_unit_edit(unit: UnitFile, edit: ConfigEdit) -> UnitFile |
| _authored_prose | function | def _authored_prose(surface: DocumentSurface) -> str |
| _change_kind | function | def _change_kind(fix: ProposedFix \| None) -> str |
| _code_ref_from_edit | function | def _code_ref_from_edit(ref: EditCodeRef) -> CodeRef |
| _coerce_audience | function | def _coerce_audience(value: str) -> Audience |
| _context_ref_symbol_glance | function | def _context_ref_symbol_glance(path: str, repo_root: str \| None) -> str |
| _context_refs_from_edit | function | def _context_refs_from_edit(refs: tuple[EditContextRef, ...]) -> tuple[ContextRef, ...] |
| _corrected | function | def _corrected(doc: Doc, surface: DocumentSurface, templates: _Templates = None, preserve: frozenset[str] = frozenset(), modes: _Modes = None, *, include_body: bool = False) -> str |
| _default_now | function | def _default_now() -> str |
| _default_process_runner | function | def _default_process_runner(argv: list[str], stdin: str, timeout_s: int) -> str |
| _extract_json_object | function | def _extract_json_object(text: str) -> str |
| _proposed_change | function | def _proposed_change(verdict: Verdict, cause: str, fix: ProposedFix \| None) -> str |
| _recommended_action | function | def _recommended_action(verdict: Verdict) -> str |
| _render_context_refs | function | def _render_context_refs(req: FixRequest) -> str |
| _selection_with_overrides | function | def _selection_with_overrides(base: DocStyleSelection, override: EditDocStyle) -> DocStyleSelection |
| _severity | function | def _severity(drift: Drift, verdict: Verdict) -> TicketSeverity |
| _stamp_index_updated | function | def _stamp_index_updated(text: str, now: str) -> str |
| _stamp_region_hashes | function | def _stamp_region_hashes(text: str, modes: _Modes) -> str |
| append | function | def append(path: Path, record: ReviewRecord) -> None |
| append_resolution | function | def append_resolution(path: Path, record: ResolutionRecord) -> None |
| apply_edits_to_disk | function | def apply_edits_to_disk(local_path: Path, edits: list[ConfigEdit], *, now: str, backend: object \| None = None) -> GenerateResult |
| apply_fix | function | def apply_fix(doc_path: Path, fix: ProposedFixLike, *, preserve: frozenset[str] = frozenset(), modes: _Modes = None) -> bool |
| apply_record_fix | function | def apply_record_fix(local_path: Path, record: ReviewRecord, *, now: str) -> ApplyFixResult |
| build_prompt | function | def build_prompt(req: FixRequest) -> str |
| build_ticket | function | def build_ticket(*, drift: Drift, verdict: Verdict, cause: str, fix: ProposedFix \| None, surface: DocumentSurface, ticket_id: str) -> DriftTicket |
| locked_region_ids | function | def locked_region_ids(doc: Doc, modes: _Modes) -> frozenset[str] |
| make_backend | function | def make_backend(cfg: BackendConfig, agent: AgentConfig \| None = None) -> Backend |
| make_sink | function | def make_sink(cfg: CentralConfig) -> Sink |
| new_record_id | function | def new_record_id(doc_id: str, surface_hash: str, detected_at: str) -> str |
| parse_backend_json | function | def parse_backend_json(text: str) -> BackendResult |
| read_all | function | def read_all(path: Path) -> list[ReviewRecord] |
| read_resolutions | function | def read_resolutions(path: Path) -> list[ResolutionRecord] |
| regenerate_regions | function | def regenerate_regions(doc_path: Path, surface: DocumentSurface, templates: _Templates = None, preserve: frozenset[str] = frozenset(), modes: _Modes = None, *, include_body: bool = False) -> bool |
| render_corrected | function | def render_corrected(doc_text: str, surface: DocumentSurface, templates: _Templates = None, preserve: frozenset[str] = frozenset(), modes: _Modes = None, *, include_body: bool = False) -> str |
| resolution_record_schema | function | def resolution_record_schema() -> dict |
| resolved_index | function | def resolved_index(resolutions: list[ResolutionRecord]) -> dict[str, ResolutionRecord] |
| review_record_schema | function | def review_record_schema() -> dict |
| select_by_verdict | function | def select_by_verdict(records: list[ReviewRecord], verdict: Verdict) -> list[ReviewRecord] |
| summarize | function | def summarize(records: list[ReviewRecord]) -> dict |
| summarize_with_resolutions | function | def summarize_with_resolutions(records: list[ReviewRecord], resolutions: list[ResolutionRecord]) -> dict |
| ticket_status | function | def ticket_status(resolution: ResolutionRecord \| None) -> TicketStatus |
<!-- CDM:END symbols -->
