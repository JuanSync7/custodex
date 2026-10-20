---
cdm:
  audience: eng-guide
  fingerprint: ba84722ed3edbf6c
  fingerprint_tiers:
    composite: ba84722ed3edbf6c
    docstring: 7634a5aaa9384453
    signature: 0b8d1b6e046f713e
  region_anchors:
    symbols:
    - 0247191d51cafd7f
    - 027e4c49f4e1d412
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 1330b7715fb5a0f3
    - 1cff0aa7c0a7de7f
    - 1ead29e2e5405b9f
    - 220b0075d23e0aa1
    - 28cc12a3f1c6798f
    - 2af0fa60e7ab3339
    - 2caa3e173d500bf0
    - 2de3aa88b03e711a
    - 4081136a4f593dce
    - 4fafcec771a36087
    - 528c5684192526b7
    - 52f102a034066b82
    - 540b5a026cb27ddf
    - 5772addc46fcf4f6
    - 78a1573ecd190045
    - 7a03d1d0f11713f3
    - 843c46978afc9ccf
    - 84c5b87c21604832
    - 85e92c372a6c9acd
    - 8738625d988e3545
    - 903f81980499eaf1
    - 9fe4c68ec20dda7c
    - ac3fbcfdc359f960
    - b0593a1dbc57ae8a
    - b3f3615f85b6bd80
    - b7cdd949d66fef0a
    - c0c02e5d79ef467f
    - c9a9718c14002f1c
    - ce2d59707a35a7b1
    - d1cc125fd5ea86cf
    - de078b94f90dd39a
    - e043ecfbbfc064cf
    - e06171a1c467f2d4
    - ea93a1e9080e2992
    - ef33c5909772e307
  region_hashes:
    symbols: 9c5d80d275fa7b26
  schema_version: 1.0.0
  symbol_sigs:
    0247191d51cafd7f: 4e132d4c1b35b61a
    027e4c49f4e1d412: 3146d57b9901de9c
    051af376199dec21: e7ddc1e5f8554f01
    1330b7715fb5a0f3: 6d79951019730f88
    1cff0aa7c0a7de7f: a256ee875cb5dcdf
    1ead29e2e5405b9f: fd0597c77178ec3d
    220b0075d23e0aa1: 9acd9ea249bee14e
    28cc12a3f1c6798f: fff7cc1e03267fc6
    2af0fa60e7ab3339: 55fa0d892751fc98
    2caa3e173d500bf0: fd5e001fead1679a
    2de3aa88b03e711a: 3a00962b421a299d
    4081136a4f593dce: c202ec48432132cd
    4fafcec771a36087: 99e61efc6d9cc9f9
    528c5684192526b7: 85752572796288c1
    52f102a034066b82: 6df8b3fa304dd1fa
    540b5a026cb27ddf: abe0978745f35b5b
    5772addc46fcf4f6: 9e09c07200e4ef29
    78a1573ecd190045: 8797a64d10972abf
    7a03d1d0f11713f3: 5a06b299aca471fb
    843c46978afc9ccf: 7c4ba6a3d0957f52
    84c5b87c21604832: 2c5703e88164d479
    85e92c372a6c9acd: a9beafa1e553cce6
    8738625d988e3545: e0039871d49f16a3
    903f81980499eaf1: 2f8e80afa8492192
    9fe4c68ec20dda7c: ed5d415d6f04d6ba
    ac3fbcfdc359f960: c78c0cc595765cf3
    b0593a1dbc57ae8a: 7542365f3f484016
    b3f3615f85b6bd80: ffd5d7efd775a7e9
    b7cdd949d66fef0a: 6ba8d304bc3de7e3
    c0c02e5d79ef467f: b1a9a588aa2d4d24
    c9a9718c14002f1c: 6ab331005c40c818
    ce2d59707a35a7b1: 4e6e9d8b7413f774
    d1cc125fd5ea86cf: 2e24611ab51366b2
    de078b94f90dd39a: 3487c0de7d90b458
    e043ecfbbfc064cf: 4609e246338c82c1
    e06171a1c467f2d4: d98e94c8f802ee23
    ea93a1e9080e2992: dcf1506d33ede15a
    ef33c5909772e307: 5514f6ff1e3a6826
---
# agent-workflow

> The deterministic LangGraph remediation agent: the `Backend`-shaped entry
> (`backend`), the graph wiring + artifact selection/context (`graph`), the
> prompt library (`prompts`), the runtime/driver leaf (`runtime`), and the
> graph's shared state (`state`).

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| AgentBackend | class | class AgentBackend |
| AgentBackend.__init__ | method | def __init__(self, cfg: AgentConfig, *, driver: Driver \| None = None, library: PromptLibrary \| None = None) -> None |
| AgentBackend._ensure_graph | method | def _ensure_graph(self) -> CompiledStateGraph |
| AgentBackend.propose | method | def propose(self, req: FixRequest) -> BackendResult |
| Artifact | class | class Artifact |
| Artifact.AGENT | variable | AGENT = 'AGENT' |
| Artifact.EXEMPLARS | variable | EXEMPLARS = 'EXEMPLARS' |
| Artifact.PERSONA | variable | PERSONA = 'PERSONA' |
| Artifact.PROTOCOL | variable | PROTOCOL = 'PROTOCOL' |
| Artifact.TOOL | variable | TOOL = 'TOOL' |
| Driver | variable | Driver = Callable[[str], str] |
| PACKAGED_PROMPTS_DIR | variable | PACKAGED_PROMPTS_DIR = Path(__file__).parent / 'prompts' |
| PromptLibrary | class | class PromptLibrary |
| PromptLibrary.__init__ | method | def __init__(self, prompts_dir: Path \| None = None) -> None |
| PromptLibrary.directory | method | @property def directory(self) -> Path |
| PromptLibrary.exists | method | def exists(self, name: str) -> bool |
| PromptLibrary.get | method | def get(self, name: str) -> str |
| RemediationState | class | class RemediationState(TypedDict, total=False) |
| RemediationState.attempts | variable | attempts: int |
| RemediationState.last_error | variable | last_error: str |
| RemediationState.prompt | variable | prompt: str |
| RemediationState.raw | variable | raw: str |
| RemediationState.req | variable | req: FixRequest |
| RemediationState.result | variable | result: BackendResult \| None |
| RemediationState.selected | variable | selected: list[str] |
| _DEFAULT_MODEL | variable | _DEFAULT_MODEL = 'claude-sonnet-4-20250514' |
| _RETRY_NUDGE | variable | _RETRY_NUDGE = ... |
| __all__ | variable | __all__ = ['RemediationState'] |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ['AgentBackend', 'make_agent_backend'] |
| __all__ | variable | __all__ = ['Driver', 'resolve_driver'] |
| __all__ | variable | __all__ = ... |
| _claude_code_argv | function | def _claude_code_argv(cfg: AgentConfig, prompt: str) -> list[str] |
| _openai_chat_call | function | def _openai_chat_call(base_url: str, model: str, prompt: str, timeout: int, api_key: str \| None) -> str |
| _render_exemplars | function | def _render_exemplars(req: FixRequest) -> str |
| _strip_front_matter | function | def _strip_front_matter(text: str) -> str |
| _wrap | function | def _wrap(driver: Driver, label: str) -> Driver |
| build_graph | function | def build_graph(driver: Driver, library: PromptLibrary, cfg: AgentConfig) -> CompiledStateGraph |
| make_agent_backend | function | def make_agent_backend(cfg: AgentConfig, *, driver: Driver \| None = None) -> AgentBackend |
| render_context | function | def render_context(req: FixRequest) -> str |
| resolve_driver | function | def resolve_driver(cfg: AgentConfig) -> Driver |
| select_artifacts | function | def select_artifacts(req: FixRequest, cfg: AgentConfig, library: PromptLibrary) -> list[str] |
<!-- CDM:END symbols -->
