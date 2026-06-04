# code-doc-monitor — architecture & module contracts

Fixed module boundaries and public signatures. Slices implement these contracts
exactly so they compose without integration drift. Pipeline:

```
config ──> extract ──> drift ──┬─> (clean)  -> exit 0
  │           │          │     └─> backend ─> verdict ─> heal(apply) ─> recheck
  │           │          │                       │
  │           │          │                       └─> ReviewRecord ─> reviewlog (JSONL)
  │           │          │                                              └─> sink (central)
  └── single source of truth: the CODE surface; docs are graded against it ──┘
```

## `errors.py`
`CodeDocMonitorError(Exception)` base; subclasses `ConfigError`,
`ExtractionError`, `DriftError`, `BackendError`, `SchemaError`. Each carries a
human message. (K8)

## `config.py`
```python
class Audience(str, Enum): USER_GUIDE = "user-guide"; ENG_GUIDE = "eng-guide"

class CodeRef(BaseModel):           # a pointer into one code file
    path: str                       # repo-relative
    symbols: tuple[str, ...] = ()   # select named functions/classes (whole-file if empty + no lines/names)
    lines: tuple[tuple[int,int],...] = ()   # 1-based inclusive line ranges
    names: tuple[str, ...] = ()     # select named module-level variables

class BackendConfig(BaseModel):
    kind: Literal["mock","claude-code","api","agent"] = "mock"
    model: str | None = None
    command: tuple[str,...] | None = None   # claude-code argv template
    timeout_s: int = 120
    extra: dict[str, str] = {}

class AgentConfig(BaseModel):              # runtime for backend.kind == "agent"
    driver: Literal["claude-code","api","local"] = "claude-code"
    model: str | None = None
    command: tuple[str,...] | None = None  # claude-code argv template
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str | None = None            # api/local endpoint (required for local)
    prompts_dir: str | None = None         # override the packaged .md artifacts
    use_persona: bool = True               # compose PERSONA.md when present
    max_parse_retries: int = 1             # bounded re-ask on a non-JSON reply
    timeout_s: int = 120

class CentralConfig(BaseModel):
    sink: Literal["none","file","http"] = "none"
    path: str | None = None         # file sink
    url: str | None = None          # http sink
    auth_env: str | None = None     # env var holding a bearer token

class DocumentSpec(BaseModel):
    id: str
    path: str                       # repo-relative doc path
    audience: Audience
    code_refs: tuple[CodeRef,...]
    region_keys: tuple[str,...] = ()  # managed regions this doc carries

class MonitorConfig(BaseModel):
    version: str = "1.0.0"
    root: str = "."                 # repo root, relative to the config file
    documents: tuple[DocumentSpec,...]
    backend: BackendConfig = BackendConfig()
    agent: AgentConfig = AgentConfig()   # runtime for backend.kind == "agent"
    central: CentralConfig = CentralConfig()
    apply_default: bool = False     # monitor auto-applies FIX by default?

def load_config(path: Path) -> MonitorConfig     # yaml|json by suffix; ConfigError on bad input
CONFIG_TEMPLATE: str                             # documented starter config
def write_template(path: Path) -> None
```

## `extract.py`  (audience-aware, AST-only, no imports of target code — K0)
```python
class Symbol(BaseModel):
    name: str; kind: Literal["function","class","method","variable"]
    signature: str; lineno: int; end_lineno: int
    is_public: bool                 # not _-prefixed
    docstring: str | None

class DocumentSurface(BaseModel):
    doc_id: str; audience: Audience
    symbols: tuple[Symbol,...]
    def surface_hash(self) -> str   # sha256[:16] of audience-normalized payload (K10)

def extract_file(path: Path) -> list[Symbol]
def build_document_surface(doc: DocumentSpec, root: Path) -> DocumentSurface
```
Audience filter: `user-guide` keeps only `is_public` symbols and EXCLUDES
docstring/comment text and `variable` locals from the hash; `eng-guide` keeps all
symbols and includes docstrings. Sub-file selection: `symbols`/`names` filter by
name; `lines` keep symbols overlapping a range; empty selectors = whole file.

## `manifest.py`  (managed regions in docs — mirrors docsync)
Markers `<!-- CDM:BEGIN <id> -->` … `<!-- CDM:END <id> -->`; optional YAML front
matter holding `cdm: {fingerprint: <hash>}`.
```python
class Doc(BaseModel): path: Path; meta: dict; body: str; raw: str
def parse_doc(path: Path) -> Doc
def regions(doc: Doc) -> dict[str,str]          # id -> body
def set_region(body: str, id: str, new: str) -> tuple[str,bool]
def stored_fingerprint(doc: Doc) -> str | None
def set_fingerprint(meta: dict, value: str) -> dict
```

## `blocks.py`  (render a managed region from a surface — K2)
```python
def symbol_table(surface: DocumentSurface) -> str
def expected_region(region_id: str, surface: DocumentSurface) -> str | None
REGION_KEYS: frozenset[str]   # e.g. {"symbols"}
```

## `drift.py`  (detect-only — K1)
```python
class DriftKind(str, Enum):
    MISSING_DOC="MISSING_DOC"; HASH="HASH"; REGION="REGION"; UNHEALABLE="UNHEALABLE"
class Drift(BaseModel):
    kind: DriftKind; doc_id: str; doc_path: str; detail: str
    region_id: str | None = None; healable: bool = True
    audience: Audience; diff: str = ""
class DriftReport(BaseModel):
    drifts: tuple[Drift,...]
    @property
    def ok(self) -> bool
    def summary(self) -> str
def detect(config: MonitorConfig, config_dir: Path) -> DriftReport
```
Audience rule (K3): a HASH drift whose only change is in docstrings/comments or
private/local symbols is reported for `eng-guide` but suppressed for
`user-guide` (the surface filter already excludes those for user-guide, so the
hash simply won't move — the rule is enforced by extraction + asserted here).

## `schema.py`  (public, versioned — K6)
```python
class Verdict(str, Enum): FIX="FIX"; INVALIDATE="INVALIDATE"; ESCALATE="ESCALATE"
class ProposedFix(BaseModel):
    region_id: str | None; new_region_body: str | None
    new_doc_text: str | None; rationale: str
class ReviewRecord(BaseModel):
    schema_version: str = "1.0.0"
    record_id: str; doc_id: str; doc_path: str; audience: Audience
    drift_kind: str; drift_detail: str
    cause: str                       # LLM's explanation
    verdict: Verdict
    fix: ProposedFix | None
    surface_hash: str; backend_kind: str
    detected_at: str; resolved_at: str    # ISO strings, injected (K10)
    config_snapshot: dict
def review_record_schema() -> dict       # ReviewRecord.model_json_schema()
```

## `reviewlog.py`  (append-only JSONL — K5)
```python
def append(path: Path, record: ReviewRecord) -> None
def read_all(path: Path) -> list[ReviewRecord]
def summarize(records: list[ReviewRecord]) -> dict   # counts by verdict/audience/doc
```

## `sinks.py`  (central system — offline default)
```python
class Sink(Protocol): def emit(self, record: ReviewRecord) -> None
class NullSink: ...        # default
class FileSink: ...        # appends JSON to a file (offline-testable central)
class HttpSink: ...        # POST to url with bearer from auth_env (never hit in tests)
def make_sink(cfg: CentralConfig) -> Sink
```

## `backends.py`  (pluggable LLM — K4)
```python
class FixRequest(BaseModel):
    drift: Drift; surface: DocumentSurface
    doc_text: str; doc_spec_id: str
class BackendResult(BaseModel):
    verdict: Verdict; cause: str; fix: ProposedFix | None
class Backend(Protocol): def propose(self, req: FixRequest) -> BackendResult
class MockBackend:        # deterministic: user-guide+comment-only -> INVALIDATE;
                          # healable region drift -> FIX (regenerate region);
                          # else ESCALATE
class ClaudeCodeBackend:  # builds a prompt, runs `claude -p <prompt>` (argv from
                          # config.command), parses a JSON verdict from stdout
class ApiBackend:         # Anthropic Messages API; key from env; same JSON contract
class AgentBackend:       # the LangGraph workflow (see agent/) behind the same Protocol
def make_backend(cfg: BackendConfig, agent: AgentConfig | None = None) -> Backend
def build_prompt(req: FixRequest) -> str        # shared, audience-aware (single-shot)
```
Backends return the SAME `BackendResult` JSON contract, so the orchestrator is
backend-agnostic. Subprocess/HTTP are injected (a `runner`/`client` param) so
tests mock them without monkeypatching globals. `make_backend` resolves
`kind == "agent"` via a lazy import of the `agent` subpackage (the optional
`langgraph` extra, K0); `Monitor` passes `config.agent` through to it.

## `agent/`  (LangGraph remediation workflow — optional `[agent]` extra, K0/K4/K10)
A deterministic LangGraph `StateGraph` whose prompt is composed from **separated
Markdown artifacts** loaded only when needed, behind the same `Backend` Protocol.
```python
# agent/prompts/{AGENT,PROTOCOL,TOOL,PERSONA}.md   the composable prompt artifacts
class PromptLibrary:                       # lazy, cached loader; loud on missing (K8)
    def get(self, name: str) -> str        # body (front matter stripped)
    def exists(self, name: str) -> bool
Driver = Callable[[str], str]              # prompt -> raw reply; the only side effect
def resolve_driver(cfg: AgentConfig) -> Driver   # claude-code | api | local (K4)
def select_artifacts(req, cfg, library) -> list[str]   # "only when needed"
def render_context(req: FixRequest) -> str             # the per-drift context block
def build_graph(driver, library, cfg) -> CompiledStateGraph
class AgentBackend:  def propose(self, req: FixRequest) -> BackendResult
def make_agent_backend(cfg: AgentConfig, *, driver: Driver | None = None) -> AgentBackend
```
Graph: `START -> select -> compose -> invoke -> parse -[done]-> END`, with a
bounded `parse -[retry]-> compose` loop (≤ `max_parse_retries`) and a
`parse -[fail]->` node that raises `BackendError` (K8). The graph is fully
deterministic; only the injected `Driver` touches a process/socket, so the whole
workflow runs offline in tests (K4). The driver leaf is the single uncovered
syscall (subprocess / urllib), mirroring the `backends.py` inject-the-leaf rule.

## `monitor.py`  (orchestration)
```python
class HandledDrift(BaseModel): drift: Drift; result: BackendResult; applied: bool
class MonitorResult(BaseModel):
    handled: tuple[HandledDrift,...]; remaining: tuple[Drift,...]
    records: tuple[ReviewRecord,...]
class Monitor:
    def __init__(self, config: MonitorConfig, config_dir: Path, *,
                 backend: Backend | None = None, sink: Sink | None = None,
                 now: Callable[[], str] | None = None): ...
    def check(self) -> DriftReport
    def run(self, *, apply: bool | None = None) -> MonitorResult
```
`run`: detect → per drift call backend → build ReviewRecord → append log + emit
sink → if `apply` and verdict==FIX, heal the doc → finally re-detect; `remaining`
= drift still present (ESCALATE, or FIX not applied). `now` injected for K10.

## `heal.py`
```python
def apply_fix(doc_path: Path, fix: ProposedFix) -> bool   # region or whole-doc; idempotent (K7)
def regenerate_regions(doc_path: Path, surface: DocumentSurface) -> bool
```

## `cli.py`  (`cdmon`)
`init | surface | check | monitor | report | schema` per SPEC. `check` exits 1 on
drift; `monitor` exits 0 unless drift `remaining`. Uses `make_backend`/`make_sink`
from config; `--apply/--no-apply` overrides `apply_default`.
