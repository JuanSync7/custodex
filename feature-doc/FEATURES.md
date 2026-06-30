# custodex — feature reference (golden)

Generated from `feature-doc/catalog/*.yaml` — **do not hand-edit**. Run `cdx wiki` (R-08) to regenerate. Each row's Demos/Tests columns trace the feature to its demo case(s) and test(s).

**233 features** across 23 subsystems.

## agent

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-AGENT-001` | LangGraph remediation backend | agent | K0, K4 | — | — | implemented |
| `FEAT-AGENT-002` | Deterministic remediation state graph | agent | K4, K8, K10 | — | — | implemented |
| `FEAT-AGENT-003` | Verdict production with bounded re-ask | agent | K8 | — | — | implemented |
| `FEAT-AGENT-004` | Composable Markdown prompt artifacts | agent | K8 | — | — | implemented |
| `FEAT-AGENT-005` | Load-only-when-needed artifact selection | agent | K6, K8 | — | — | implemented |
| `FEAT-AGENT-006` | Drift-specific prompt context | agent | K2, K6, K9 | — | — | implemented |
| `FEAT-AGENT-007` | Few-shot exemplar framing | agent | K2, K6, K9 | — | — | implemented |
| `FEAT-AGENT-008` | Config-resolved runtime driver | agent | K0, K4, K8 | — | — | implemented |

### `FEAT-AGENT-001` — LangGraph remediation backend

AgentBackend (built by make_agent_backend) drives a deterministic LangGraph workflow behind the same Backend.propose(req) -> BackendResult contract as the single-shot backends, so the Monitor orchestrator is unchanged whether it runs the mock, a one-shot call, or the graph. Lives in the optional [agent] extra (langgraph), keeping the core mock path dependency-free.

### `FEAT-AGENT-002` — Deterministic remediation state graph

build_graph compiles a StateGraph of four nodes plus a bounded re-ask loop (select -> compose -> invoke -> parse, retry back to compose, fail loudly) over a RemediationState TypedDict. The graph itself is fully deterministic; the only non-determinism is the injected Driver, so the whole workflow runs offline with a fake driver in tests.

### `FEAT-AGENT-003` — Verdict production with bounded re-ask

The parse node validates the driver's raw reply into a BackendResult (FIX / INVALIDATE / ESCALATE) via parse_backend_json; a malformed reply routes back to compose with a strict-JSON nudge until max_parse_retries is spent, then the fail node raises a typed BackendError rather than emitting a silent or empty verdict.

### `FEAT-AGENT-004` — Composable Markdown prompt artifacts

PromptLibrary lazily loads and caches the agent's separated prompt artifacts (Artifact.AGENT / PROTOCOL / TOOL / PERSONA / EXEMPLARS) from the packaged prompts/ directory or an agent.prompts_dir override, stripping YAML front matter from each body. A missing required artifact is a loud, typed BackendError, never a silent empty prompt.

### `FEAT-AGENT-005` — Load-only-when-needed artifact selection

select_artifacts decides which artifacts a drift needs — AGENT and PROTOCOL always, TOOL only for a healable (non-UNHEALABLE) drift, PERSONA only when use_persona is enabled and the file exists, and EXEMPLARS only when the request carries few-shot exemplars — so each .md is read from disk only when a node actually composes it.

### `FEAT-AGENT-006` — Drift-specific prompt context

render_context assembles the per-drift block appended after the artifacts — audience, document id/path, detected drift, current document text, and the code surface symbol_table as the single source of truth — and appends optional index body, context refs, few-shot exemplars, and writing guidance LAST so an exemplar-/style-free request is byte-identical to its prior output.

### `FEAT-AGENT-007` — Few-shot exemplar framing

When a FixRequest carries retrieved exemplars, render_context renders each one (past drift shape, human resolution, and the committed resolved_text for an overridden outcome) under the EXEMPLARS.md framing as precedent that the live code surface still overrides; with no exemplars the selection and rendered prompt are byte-identical to pre-exemplar output (additive).

### `FEAT-AGENT-008` — Config-resolved runtime driver

resolve_driver turns an AgentConfig into the single side-effecting Driver (a prompt -> raw-text callable) — the headless Claude Code CLI by default, the Anthropic Messages API, or any OpenAI-compatible local endpoint — so pointing the agent at a different model host is a config edit, never a code change; a misconfigured or failing driver raises a typed BackendError.

## backends

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-BACKENDS-001` | Backend-agnostic verdict contract | backends | K4, K6, K8 | — | — | implemented |
| `FEAT-BACKENDS-002` | One pluggable backend factory | backends | K0, K4, K8 | — | — | implemented |
| `FEAT-BACKENDS-003` | Deterministic offline MockBackend (the default) | backends | K3, K4, K10 | — | — | implemented |
| `FEAT-BACKENDS-004` | Headless ClaudeCodeBackend with injected runner | backends | K0, K4, K8 | — | — | implemented |
| `FEAT-BACKENDS-005` | Anthropic ApiBackend with injected client | backends | K0, K4, K8 | — | — | implemented |
| `FEAT-BACKENDS-006` | Shared audience-aware prompt builder | backends | K3 | — | — | implemented |
| `FEAT-BACKENDS-007` | Robust loud reply parsing | backends | K8 | — | — | implemented |
| `FEAT-BACKENDS-008` | Authoring context refs and writing-style guidance | backends | K3, K6, K10 | — | — | implemented |

### `FEAT-BACKENDS-001` — Backend-agnostic verdict contract

The Backend Protocol (`propose(req: FixRequest) -> BackendResult`) makes every backend return the SAME immutable contract — a FIX/INVALIDATE/ESCALATE Verdict, a cause, and an optional ProposedFix — so the orchestrator is backend-agnostic. FixRequest and BackendResult are frozen, extra-forbid pydantic snapshots.

### `FEAT-BACKENDS-002` — One pluggable backend factory

make_backend resolves a BackendConfig (and optional AgentConfig) to a Backend through a single factory — mock, claude-code, api, or the LangGraph agent — defaulting unknown kinds to a loud BackendError; the agent kind sits behind a lazy import so the optional langgraph dependency is only required when selected.

### `FEAT-BACKENDS-003` — Deterministic offline MockBackend (the default)

MockBackend is the deterministic, offline default that never touches the network or an LLM: it FIXes a healable region from the surface, authors idempotent prose for a no-renderer `llm` region, INVALIDATEs a user-guide docstring/comment/private HASH drift, FIXes a surface HASH drift via a whole-doc render_corrected, and ESCALATEs anything else.

### `FEAT-BACKENDS-004` — Headless ClaudeCodeBackend with injected runner

ClaudeCodeBackend builds the shared prompt, assembles argv (default `claude -p <prompt>` or a configured `{prompt}`-token command template), and runs an INJECTED ProcessRunner so tests never spawn `claude`; when none is given a stdlib subprocess runner is built lazily and any failure/timeout is wrapped in a BackendError.

### `FEAT-BACKENDS-005` — Anthropic ApiBackend with injected client

ApiBackend calls the Anthropic Messages API through an INJECTED ApiClient so tests never hit the network; when none is given a stdlib urllib client is built lazily (no `anthropic` package), requiring an API key from `api_key_env` or raising a loud BackendError, and any client failure is wrapped in a BackendError.

### `FEAT-BACKENDS-006` — Shared audience-aware prompt builder

build_prompt is the single prompt builder shared by the LLM backends: it describes the drift, embeds the document text and the code-surface symbol table, states the audience-specific FIX-vs-INVALIDATE rule, selects a region-shaped or whole-doc fix shape, and demands a JSON-only verdict reply.

### `FEAT-BACKENDS-007` — Robust loud reply parsing

parse_backend_json extracts the first balanced `{...}` object from a possibly prose-wrapped or fenced reply and validates it into a BackendResult/ProposedFix, raising a loud BackendError on no JSON, malformed JSON, an invalid verdict, or a payload that fails the contract.

### `FEAT-BACKENDS-008` — Authoring context refs and writing-style guidance

A FixRequest carries additive authoring inputs — `context_refs` glance-through sub-documents/source-files (rendered with a deterministic public-symbol glance for `.py` refs), `style_guidance`, `exemplars`, and `region_mode` — that enrich the LLM-authored prose prompt while the mock backend ignores them to stay deterministic.

## cli

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-CLI-001` | Config scaffold (cdx init) | cli | K8 | — | — | implemented |
| `FEAT-CLI-002` | Index regeneration (cdx index) | cli | K1, K7 | — | — | implemented |
| `FEAT-CLI-003` | Dir-layout coverage report (cdx rpt) | cli | K1, K7 | — | — | implemented |
| `FEAT-CLI-004` | Surface dump (cdx surface) | cli | K1 | — | — | implemented |
| `FEAT-CLI-005` | Drift gate (cdx check) | cli | K1 | — | — | implemented |
| `FEAT-CLI-006` | HTML twin build (cdx build) | cli | K7 | — | — | implemented |
| `FEAT-CLI-007` | Remediation run (cdx monitor) | cli | K8 | — | — | implemented |
| `FEAT-CLI-008` | Docs heal patch (cdx sync-pr) | cli | K1, K4, K7, K10 | — | — | implemented |
| `FEAT-CLI-009` | Loop-safety guard (cdx should-sync) | cli | K1 | — | — | implemented |
| `FEAT-CLI-010` | Docs merge request (cdx open-docs-pr) | cli | K1, K4, K8, K10 | — | — | implemented |
| `FEAT-CLI-011` | Central registration (cdx register) | cli | K4, K8 | — | — | implemented |
| `FEAT-CLI-012` | Config sync (cdx sync) | cli | K1, K8, K10 | — | — | implemented |
| `FEAT-CLI-013` | Standalone dashboard (cdx serve) | cli | K8 | — | — | implemented |
| `FEAT-CLI-014` | Preflight checks (cdx doctor) | cli | K1, K4, K8, K10 | — | — | implemented |
| `FEAT-CLI-015` | Review-log report (cdx report) | cli | K1, K5 | — | — | implemented |
| `FEAT-CLI-016` | Promotion candidates (cdx promotions) | cli | K1, K10 | — | — | implemented |
| `FEAT-CLI-017` | Doc coverage (cdx coverage) | cli | K1, K7 | — | — | implemented |
| `FEAT-CLI-018` | Coverage-gap issue (cdx surface-gaps) | cli | K4, K8, K10 | — | — | implemented |
| `FEAT-CLI-019` | Resolution recording (cdx resolve) | cli | K5, K8, K10 | — | — | implemented |
| `FEAT-CLI-020` | Layout lint (cdx lint) | cli | K1, K8, K10 | — | — | implemented |
| `FEAT-CLI-021` | Doc scaffold (cdx new-doc) | cli | K8 | — | — | implemented |
| `FEAT-CLI-022` | Schema export (cdx schema) | cli | K6 | — | — | implemented |

### `FEAT-CLI-001` — Config scaffold (cdx init)

`cdx init` writes a documented config template, refusing to clobber unless `--force`. `--central URL` wires the `central:` HTTP-reporting block (`--repo-id`/`--token-env`/`--repo-url`); `--v2` scaffolds the multi-file `config/cdmon/` directory layout (`--config-dir`/`--repo`) instead.

### `FEAT-CLI-002` — Index regeneration (cdx index)

`cdx index` rebuilds `config/cdmon/index.yaml`'s `units:` from the on-disk unit files via `regenerate_index`/`write_index`, preserving every global. `--check` is a read-only CI gate that exits 1 on a real units-list change (ignoring the wall-clock `updated:` stamp via `_blank_updated`, N-06).

### `FEAT-CLI-003` — Dir-layout coverage report (cdx rpt)

`cdx rpt` computes the `config/cdmon/` coverage report via `load_bundle`/`build_coverage_rpt`/`render_rpt` and prints it; `--write` writes a deterministic `config/cdmon/coverage.rpt` (idempotent), `--ref` stamps the report's provenance.

### `FEAT-CLI-004` — Surface dump (cdx surface)

`cdx surface` prints each document's id/audience/symbol-count and surface hash via `build_document_surface` for debugging; `--json` dumps each surface (hash plus every symbol) as a JSON list.

### `FEAT-CLI-005` — Drift gate (cdx check)

`cdx check` runs `Monitor.check()`, prints the report summary, and exits 1 when drift is present and 0 when clean — the read-only CI warning signal.

### `FEAT-CLI-006` — HTML twin build (cdx build)

`cdx build` renders every `html: true` document to its derived `.html` twin via `build` (build_twins), echoing each written path and the twin count.

### `FEAT-CLI-007` — Remediation run (cdx monitor)

`cdx monitor` runs `Monitor.run` (detect → backend verdict → record → optionally apply → recheck), exiting 1 when drift remains. `--apply/--no-apply` overrides the config default; `--ref`/`--source-sha` (else `$CI_COMMIT_SHA`) stamps each record's `source_sha` provenance (C-05).

### `FEAT-CLI-008` — Docs heal patch (cdx sync-pr)

`cdx sync-pr` heals the docs and emits a unified-diff patch of exactly the changed docs via `sync_pr`, printing it (or writing it to `--out`). `--dry-run` computes the same patch with no working-tree mutation; a clean or second run yields an empty patch (idempotent).

### `FEAT-CLI-009` — Loop-safety guard (cdx should-sync)

`cdx should-sync` is a read-only guard (`should_sync`) that exits 0 to proceed with a heal and 1 to skip — skipping when every changed file is a managed doc path (a bot doc-only commit) or the set is empty. Reads file paths from args or newline-separated stdin (C-04).

### `FEAT-CLI-010` — Docs merge request (cdx open-docs-pr)

`cdx open-docs-pr` heals the docs then opens a docs merge request (branch + commit + MR) via the default `GitLabTransport`/`open_docs_pr` (`--target`/`--ref`). A clean repo is a no-op; `--dry-run` prints the MR plan as JSON from a dry sync with no mutation and no transport built.

### `FEAT-CLI-011` — Central registration (cdx register)

`cdx register` announces this repo to the central server by POSTing a `RegistrationPayload` (a `RepoIdentity` from `central.repo_id`) to `<central url>/repos` via `register_repo` (bearer from `central.auth_env`). `--dry-run` prints the payload it would send with no network call (E-02).

### `FEAT-CLI-012` — Config sync (cdx sync)

`cdx sync` runs a `local`/`git` config sync (`--mode`): without `--remote` it runs `configsync.run_sync` read-only against the cwd and prints the summary; with `--remote URL --repo-id ID` it POSTs to `<URL>/repos/{ID}/sync` via `sync_repo_remote`. `--json` emits the SyncRun; the clock is injected (K10).

### `FEAT-CLI-013` — Standalone dashboard (cdx serve)

`cdx serve` launches the FastAPI dashboard for the current repo standalone via `build_standalone_app` — auto-registering and pre-syncing the cwd — on `--host`/`--port`. Loud K8 when the cwd has no `config/cdmon/index.yaml` (L-01).

### `FEAT-CLI-014` — Preflight checks (cdx doctor)

`cdx doctor` is an offline, read-only preflight: it loads the config (malformed → loud K8) then runs `run_checks` (config / documents / backend prereq / central wiring / extras), printing one `STATUS  name — detail` line each and exiting 1 only if any check FAILs (G-02).

### `FEAT-CLI-015` — Review-log report (cdx report)

`cdx report` summarizes the review log via `summarize` plus the `summarize_with_resolutions` resolved/unresolved join; `--verdict V` lists the individual records of that verdict (e.g. the `ESCALATE`s a human must act on) via `select_by_verdict`, with `--json` for machine output.

### `FEAT-CLI-016` — Promotion candidates (cdx promotions)

`cdx promotions` lists read-only promotion CANDIDATES via `detect_promotions`: each `(doc_id, drift_kind, audience)` shape whose resolved records (≥ `--min-count`) unanimously share one decision resolution and could become a deterministic rule. `--json` for machine output.

### `FEAT-CLI-017` — Doc coverage (cdx coverage)

`cdx coverage` reports file/public-symbol coverage percentages plus the documented/undocumented/waived baskets via `discover_files`/`discover_symbols`/ `resolve_coverage`. `--fail-under N` gates on public-symbol coverage; `--write [PATH]` writes a deterministic manifest (idempotent); `--json` dumps the report.

### `FEAT-CLI-018` — Coverage-gap issue (cdx surface-gaps)

`cdx surface-gaps` turns doc coverage gaps into a tracker issue: it runs discover → `resolve_coverage` → `suggest_owners`, builds an `IssuePlan` via `plan_coverage_issue`, and opens it via the `--provider` (gitlab|github) transport. No gaps is a no-op; `--dry-run` prints the plan as JSON (H-04).

### `FEAT-CLI-019` — Resolution recording (cdx resolve)

`cdx resolve RECORD_ID --resolution {accepted|overridden|rejected|invalidated}` records the human outcome of a handled drift as a separate append-only `ResolutionRecord` via `append_resolution`, validating the id exists (loud K8) and leaving the review log immutable. The timestamp is injected (K10).

### `FEAT-CLI-020` — Layout lint (cdx lint)

`cdx lint` validates doc structure against the Layout Standard via `lint_config`, exiting 1 on issues. `--fix` stamps missing static front matter (`stamp_doc_meta`); `--modes` prints each managed region's authority mode/lock/advisory state (informational, never changing the exit code, B-05).

### `FEAT-CLI-021` — Doc scaffold (cdx new-doc)

`cdx new-doc DOC_ID` scaffolds a conformant, in-sync Markdown document for a configured doc id via `build_document_surface`/`scaffold_doc`, refusing to overwrite an existing file unless `--force`.

### `FEAT-CLI-022` — Schema export (cdx schema)

`cdx schema` emits the public review-record JSON schema (`review_record_schema`) to stdout, or to `--out FILE` — one source of truth for the record contract (K6).

## config

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-CONFIG-001` | Frozen, typed config model | config | K0, K8 | — | — | implemented |
| `FEAT-CONFIG-002` | Code reference selectors | config | K0 | — | — | implemented |
| `FEAT-CONFIG-003` | Generation context references | config | K6, K8 | — | — | implemented |
| `FEAT-CONFIG-004` | Document spec with audience policy | config | K0, K10 | — | — | implemented |
| `FEAT-CONFIG-005` | Per-region authority modes | config | K6, K8 | — | — | implemented |
| `FEAT-CONFIG-006` | Declarative region table templates | config | K0, K10 | — | — | implemented |
| `FEAT-CONFIG-007` | Coverage scope and justified waivers | config | K8 | — | — | implemented |
| `FEAT-CONFIG-008` | Backend and central reporting config | config | K4, K6 | — | — | implemented |
| `FEAT-CONFIG-009` | Suffix-dispatched config loading | config | K8 | — | — | implemented |
| `FEAT-CONFIG-010` | Documented starter template | config | K0 | — | — | implemented |
| `FEAT-CONFIG-011` | Opt-in body-tier fingerprint policy | config | K10 | — | — | implemented |
| `FEAT-CONFIG-012` | Typed loud-error hierarchy | errors | K8 | — | — | implemented |

### `FEAT-CONFIG-001` — Frozen, typed config model

MonitorConfig is the single immutable model the whole engine reads a target codebase through; every config model is frozen with extra="forbid", so a typo or stale field is a loud, typed ConfigError rather than a silent pass.

### `FEAT-CONFIG-002` — Code reference selectors

CodeRef points a document at one code file and narrows the surface by symbols, names (module variables), 1-based inclusive lines, or an exact arg_signature; its extract field picks symbols / switches / records and lang selects the parser, with no target codebase hard-coded.

### `FEAT-CONFIG-003` — Generation context references

ContextRef is a glance-through generation reference added to a DocumentSpec via context_refs; it feeds the generation prompt only and never enters code_refs, coverage, or drift, is not resolved for existence at load, and duplicate paths in one document are a loud ConfigError.

### `FEAT-CONFIG-004` — Document spec with audience policy

DocumentSpec binds a doc id and path to an Audience (user-guide vs eng-guide via the Audience enum) plus its code_refs and managed region_keys; the audience drives what counts as a documented surface and what counts as drift.

### `FEAT-CONFIG-005` — Per-region authority modes

RegionMode (generated / llm / human / llm-seeded) plus a document's region_modes map and mode_for accessor declare who owns each managed region and how heal treats it; an absent mode defaults to generated, and a region_modes key not in region_keys is a loud ConfigError.

### `FEAT-CONFIG-006` — Declarative region table templates

RegionTemplate (with RegionColumn) is a config-driven table renderer keyed by region id on MonitorConfig.region_templates; its source (records / symbols / index) and columns project a managed region with nothing target-specific baked into the engine.

### `FEAT-CONFIG-007` — Coverage scope and justified waivers

CoverageConfig is the coverage: block giving include/exclude scan globs (defaulting to the inventory defaults) plus a list of WaiverEntry intentional documentation gaps; each waiver MUST carry a reason or load fails with a loud ConfigError.

### `FEAT-CONFIG-008` — Backend and central reporting config

BackendConfig (mock / claude-code / api / agent) selects which backend produces verdicts, AgentConfig configures the LangGraph remediation runtime when backend.kind is agent, and CentralConfig declares where review records are emitted; all default to offline (mock / none).

### `FEAT-CONFIG-009` — Suffix-dispatched config loading

load_config reads a single YAML or JSON config (chosen by file suffix) and validates it into a MonitorConfig; any unsupported suffix, read error, parse error, non-mapping top level, or validation failure is wrapped in a loud ConfigError with a clear message.

### `FEAT-CONFIG-010` — Documented starter template

CONFIG_TEMPLATE is a documented starter config covering both audiences and all selector kinds that round-trips through load_config; write_template writes it (or supplied content) and central_config_template returns it with the central: block wired for HTTP reporting against DEFAULT_CENTRAL_TOKEN_ENV.

### `FEAT-CONFIG-011` — Opt-in body-tier fingerprint policy

MonitorConfig.fingerprint_body_tier is an opt-in flag, default OFF to keep stored fingerprints valid, that folds function/method bodies into non-user-guide surface hashes so an eng-guide can detect an implementation change that leaves the signature untouched.

### `FEAT-CONFIG-012` — Typed loud-error hierarchy

errors.py defines a single CodeDocMonitorError base carrying a human message plus typed subclasses (ConfigError, ExtractionError, DriftError, BackendError, SchemaError, InventoryError, TransportError, SyncError, CatalogError) so every failure mode is a loud, classifiable exception.

## configv2

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-CONFIGV2-001` | Multi-file config/cdmon directory layout | config | K0, K8, K10 | — | — | implemented |
| `FEAT-CONFIGV2-002` | Frontmatter + dir-covered + source-files-format unit schema | config | K8, K10 | — | — | implemented |
| `FEAT-CONFIGV2-003` | index.yaml globals and ordered unit index | config | K8, K10 | — | — | implemented |
| `FEAT-CONFIGV2-004` | Cross-file bundle validation | config | K8, K10 | — | — | implemented |
| `FEAT-CONFIGV2-005` | Nested deepest-wins unit attribution | config | K10 | — | — | implemented |
| `FEAT-CONFIGV2-006` | Effective coverage derived from the dir layout | config | K10 | — | — | implemented |
| `FEAT-CONFIGV2-007` | ignore.yaml plus .gitignore-to-globs translation | config | K0, K10 | — | — | implemented |
| `FEAT-CONFIGV2-008` | One repo-root resolver | config | K10 | — | — | implemented |
| `FEAT-CONFIGV2-009` | Index regeneration and reverse validation | config | K7, K8, K10 | — | — | implemented |
| `FEAT-CONFIGV2-010` | Cycle-break leaf primitives | _v2base, config | K0, K6, K8 | — | — | implemented |
| `FEAT-CONFIGV2-011` | Canonical templates and dir scaffolder | templates_v2 | K7, K8, K10 | — | — | implemented |
| `FEAT-CONFIGV2-012` | DB-backed git/local config sync | configsync | K1, K8, K10 | — | — | implemented |
| `FEAT-CONFIGV2-013` | Generate-to-disk engine | generate | K1, K7, K8, K10 | — | — | implemented |
| `FEAT-CONFIGV2-014` | Pure unit-file serializers and model editors | config | K7, K8, K10 | — | — | implemented |
| `FEAT-CONFIGV2-015` | Index-source region rendering | index | K0, K2, K10 | — | — | implemented |
| `FEAT-CONFIGV2-016` | README / narrative-document monitoring | config, drift, layout | K0, K2, K3, K5, K10 | — | — | implemented |
| `FEAT-CONFIGV2-017` | Test → test-doc mirror | config, extract, heal | K0, K2, K5, K7, K10 | — | — | implemented |

### `FEAT-CONFIGV2-001` — Multi-file config/cdmon directory layout

load_bundle reads a config/cdmon/ directory — index.yaml plus one <unit>.yaml per coverage unit plus ignore.yaml/doc-style.yaml — and merges it into one MonitorConfig wrapped in a ConfigBundle (config + index + units + doc_style), so downstream modules consume a single config and learn nothing about units; load_config_dir is the thin config-only wrapper.

### `FEAT-CONFIGV2-002` — Frontmatter + dir-covered + source-files-format unit schema

UnitFile (with UnitFrontmatter) models one coverage unit: a fenced ---frontmatter--- of traceability metadata pinned to CDMON_CONFIG_VERSION "2.0.0", then a body declaring dir-covered (>=1 owned directories), source-files-format (>=1 dotted extensions counted toward coverage), and DocumentSpec documents; load_unit_file enforces the frontmatter unit equals the filename stem.

### `FEAT-CONFIGV2-003` — index.yaml globals and ordered unit index

IndexFile (with IndexFrontmatter and IndexUnitRef) models index.yaml: the repo globals that lift straight into MonitorConfig (root, backend, agent, central, coverage, region_templates) plus the ordered units: list and the ignore/doc-style pointers; load_index_file builds it and load_bundle enforces the cross-file rules.

### `FEAT-CONFIGV2-004` — Cross-file bundle validation

load_bundle enforces the dir-layout invariants loudly: every listed unit file must exist, no duplicate document id across units, and no two units may claim an identical normalized dir-covered directory (nesting is allowed, identical is not).

### `FEAT-CONFIGV2-005` — Nested deepest-wins unit attribution

unit_for_path (and ConfigBundle.unit_for_path) attributes a repo-relative path to the unit whose dir-covered is the deepest ancestor by path components, never string prefix, so a file under a nested child unit belongs to the child while a file directly in the parent belongs to the parent; ties on depth break by bundle order.

### `FEAT-CONFIGV2-006` — Effective coverage derived from the dir layout

effective_coverage derives a CoverageConfig purely from the bundle: include = each unit's dir-covered × source-files-format as d/**/*ext globs, exclude = ignore patterns plus translated .gitignore plus defaults, with deepest-wins per-extension scoping expressed as derived excludes, feeding the untouched coverage engine unchanged.

### `FEAT-CONFIGV2-007` — ignore.yaml plus .gitignore-to-globs translation

IgnoreFile (with IgnoreFrontmatter) models ignore.yaml's manual patterns and an opt-in gitignore: flag; gitignore_to_globs is a hand-rolled translation (no new dependency) of .gitignore text into inventory's exact ** glob semantics, deterministically sorted and deduped, merged into the coverage exclude set.

### `FEAT-CONFIGV2-008` — One repo-root resolver

resolve_repo_root is the single normpath(config_dir / root) formula every consumer shares, so the dir layout (config_dir = <repo>/config/cdmon, root "../..") and the single-file layout (config_dir IS the repo, root ".") can never diverge on where the repo root is.

### `FEAT-CONFIGV2-009` — Index regeneration and reverse validation

regenerate_index rescans the on-disk *.yaml units (sorted, RESERVED_UNIT_STEMS excluded) and rewrites only index.yaml's units: block and frontmatter updated: line by textual surgery — preserving every other field byte-for-byte and staying idempotent; write_index persists it, and load_bundle's reverse invariant rejects any on-disk unit absent from the index.

### `FEAT-CONFIGV2-010` — Cycle-break leaf primitives

_v2base is the dependency leaf that breaks the config<->docstyle cycle: it owns CDMON_CONFIG_VERSION, the shared _V2_MODEL_CONFIG, the _FM_RE fence, and the loud _split_frontmatter / _parse_v2_body helpers, which config re-exports under its old paths so existing callers are unchanged.

### `FEAT-CONFIGV2-011` — Canonical templates and dir scaffolder

templates_v2 holds the four canonical, loader-round-tripping templates (UNIT_TEMPLATE, INDEX_TEMPLATE, IGNORE_TEMPLATE, DOC_STYLE_TEMPLATE, aggregated in V2_TEMPLATES); scaffold_config_dir materializes a complete, load_bundle-valid config/cdmon/ by filling the {repo}/{now} placeholders, deterministic and loud on OS error.

### `FEAT-CONFIGV2-012` — DB-backed git/local config sync

configsync.run_sync is the server's POST /repos/{id}/sync engine: in local mode it reads the working tree, in git mode it materializes the default branch in a throwaway worktree (torn down in a finally), then loads the bundle, computes drift and coverage, and projects ConfigDocument / ConfigCodeRef rows plus a SyncRun summary without ever mutating the user's tree; read_config_at is the thin façade and GitInfo carries the git context.

### `FEAT-CONFIGV2-013` — Generate-to-disk engine

generate.apply_edits_to_disk turns staged ConfigEdit tickets into a live, git-tracked change — applying the pure model editors and dump_unit_file to the unit yaml, rewriting doc-style.yaml, regenerating the index, then scaffolding/healing each affected document mechanically (no LLM) — over a SCOPED write surface (only config/cdmon/*.yaml and declared .md docs), offline, deterministic, and idempotent; apply_record_fix is the per-record counterpart returning a unified diff.

### `FEAT-CONFIGV2-014` — Pure unit-file serializers and model editors

dump_unit_file serializes a UnitFile back to canonical ---fenced YAML that round-trips through load_unit_file and re-dumps byte-identically (the updated: field refreshed from an injected now); upsert_document, add_code_ref, remove_code_ref, and set_context_refs are pure editors each returning a new frozen UnitFile so edits can be composed then dumped once.

### `FEAT-CONFIGV2-015` — Index-source region rendering

render_index renders a source='index' managed region as a Markdown table over the config's other documents (excluding the index doc, optionally filtered by audience), one row per doc with synthetic columns (doc_id, title as a link to the HTML twin or .md, summary, link, audience, path) in deterministic config order.

### `FEAT-CONFIGV2-016` — README / narrative-document monitoring

A narrative Markdown document such as README.md is a first-class monitored document: it is declared in a config/cdmon unit with code_refs naming the source files it describes and NO managed region, so the engine tracks it by the whole-doc fingerprint over that code surface and never authors its prose (K2). As a user-guide its drift is audience-gated — a comment/docstring or private change to a referenced source file is a non-event, only a real public-surface change drifts it (K3) — and the drift is recorded as a ReviewRecord for a human, never auto-rewritten (K5); monitor --apply only refreshes its fingerprint. To keep an eng-only api-index from being forced to list such a user-guide README, the INDEX_INCOMPLETE lint honors the index region's audience kind, so an index need only link the documents it renders. cdx dogfoods this on its own README.md.

### `FEAT-CONFIGV2-017` — Test → test-doc mirror

Test files are monitored exactly like source files: a config/cdmon unit whose code_refs point at tests/** and whose documents live under a top-level test-docs/ directory maps each test file 1:1 to a test-doc carrying a managed symbols region that lists the file's test_* functions. It is the SAME engine as source -> docs with no new code — a test file is just a .py file (K0), so the extractor, drift detector, healer, and coverage resolver all work unchanged. The test file is the source of truth and the test-doc is graded against it, never the reverse (K2); editing or renaming a test drifts its test-doc and records a ReviewRecord for a human (K5), and monitor --apply heals it idempotently (K7). The demo maps all four of its test files to test-docs 1:1, and cdx dogfoods the pattern on its own tests/smoke boundary; the console surfaces test-docs in a dedicated Test docs section on the Documents, Drift, and Mapping pages.

## coverage

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-COVERAGE-001` | Repo code-file discovery with glob scoping | inventory | K0, K1, K10 | — | — | implemented |
| `FEAT-COVERAGE-002` | In-house recursive glob translation | inventory | K0, K1 | — | — | implemented |
| `FEAT-COVERAGE-003` | Lossless language tagging | inventory | K1, K10 | — | — | implemented |
| `FEAT-COVERAGE-004` | Loud invalid-root failure | inventory | K8 | — | — | implemented |
| `FEAT-COVERAGE-005` | Symbol-level inventory | inventory | K0, K1, K8, K10 | — | — | implemented |
| `FEAT-COVERAGE-006` | File- and symbol-level ownership resolution | coverage | K0, K1, K10 | — | — | implemented |
| `FEAT-COVERAGE-007` | Three coverage baskets and percentages | coverage | K1, K10 | — | — | implemented |
| `FEAT-COVERAGE-008` | Coverage waivers with justifications | coverage | K0, K1, K10 | — | — | implemented |
| `FEAT-COVERAGE-009` | Gap-to-suggested-owner heuristic | coverage | K0, K10 | — | — | implemented |
| `FEAT-COVERAGE-010` | JSON-safe coverage snapshot | coverage | K0, K1, K10 | — | — | implemented |

### `FEAT-COVERAGE-001` — Repo code-file discovery with glob scoping

discover_files walks a repo root and returns an Inventory of CodeFile entries (repo-relative POSIX path + extension-derived language), keeping a file iff it matches at least one include glob and zero exclude globs over DEFAULT_INCLUDE / DEFAULT_EXCLUDE. Output is sorted by path and deduped.

### `FEAT-COVERAGE-002` — In-house recursive glob translation

A private stdlib-only translator compiles each POSIX include/exclude glob to a regex with true `**` semantics (`**/` = zero-or-more leading segments, `**` crosses `/`, `*`/`?` stay within one segment), so glob scoping needs no new dependency (fnmatch alone cannot express `**`).

### `FEAT-COVERAGE-003` — Lossless language tagging

_language_for maps a file extension via a deliberately small table (.py/.pyi -> python) and labels anything matched-but-unmapped as "unknown", so a discovered file is tracked with a coarse language and never dropped for lack of a mapping.

### `FEAT-COVERAGE-004` — Loud invalid-root failure

discover_files raises a typed InventoryError when root is missing or is not a directory, never returning a silent empty Inventory.

### `FEAT-COVERAGE-005` — Symbol-level inventory

discover_symbols attaches each file's symbol surface as a SymbolInventory of FileSymbols, calling extract.extract_file for every python file (AST parsing reused, never re-implemented) and keeping non-python files with symbols=() (lossless). Inventory file order and extract_file symbol order are preserved; an unparseable file lets ExtractionError propagate loud.

### `FEAT-COVERAGE-006` — File- and symbol-level ownership resolution

resolve_coverage crosses a MonitorConfig's document code_refs against a SymbolInventory to produce a lossless CoverageReport, marking each OwnedFile and OwnedSymbol with the doc ids that own it (a file by path match, a symbol by reusing extract._select). It is pure and ignores audience; output is deterministic (files by path, symbols by path/name/kind).

### `FEAT-COVERAGE-007` — Three coverage baskets and percentages

CoverageReport derives documented / undocumented / waived baskets at file and symbol granularity, with percent_files and percent_public_symbols. The gap-percentage universe is PUBLIC symbols only (private symbols are tracked but never a documentation target), and an empty universe is vacuously 100% (no zero-division).

### `FEAT-COVERAGE-008` — Coverage waivers with justifications

resolve_coverage folds config.coverage.waive entries: an unowned file or unowned public symbol whose path (and, for a symbol, name) matches a waiver is stamped with that entry's reason and reclassified out of the gap basket into waived_files / waived_symbols. Waived items leave both the numerator and denominator of the percentages.

### `FEAT-COVERAGE-009` — Gap-to-suggested-owner heuristic

suggest_owners emits a deterministic OwnerSuggestion for every public, unowned, non-waived symbol gap with no LLM or I/O: it reuses an existing doc id when a document already owns a sibling symbol in the file, or proposes a new path-derived doc id (drop .py/.pyi, "/" -> "-") for a fully-unowned file. Output is sorted by (path, name).

### `FEAT-COVERAGE-010` — JSON-safe coverage snapshot

coverage_snapshot projects a CoverageReport into the deterministic, JSON-safe wire shape the central server stores and the dashboard reads — the file/symbol percentages, file basket counts, a per-file list with documented/undocumented/waived status and owners, plus a back-compat `ratio` (percent_public_symbols / 100).

## docdeps

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-DOCDEPS-001` | Doc↔doc edge config models (declaration = config, K2) | config | K0, K2, K6, K8 | — | — | implemented |
| `FEAT-DOCDEPS-002` | Pure suspect-link detection (the two-fingerprint model) | docdeps, manifest | K1, K2, K10 | — | — | implemented |
| `FEAT-DOCDEPS-003` | Link inference + the per-edge baseline writer | docdeps | K1, K7, K10 | — | — | implemented |
| `FEAT-DOCDEPS-004` | SUSPECT_LINK surfaces through drift.detect (audience-scoped) | drift, docdeps | K1, K3 | — | — | implemented |
| `FEAT-DOCDEPS-005` | cdx deps + cdx resolve --edge + the configurable gate | cli, docdeps | K1, K4, K8 | — | — | implemented |
| `FEAT-DOCDEPS-006` | Monitor records suspect links + baselines new edges (human-in-loop) | monitor, docdeps | K5, K6, K7 | — | — | implemented |
| `FEAT-DOCDEPS-007` | Central hub mirrors the doc↔doc graph (GET /doc-graph) | configsync, server | K2, K6 | — | — | implemented |
| `FEAT-DOCDEPS-008` | Indexed reverse-dependency lookup (config_doc_edges + GET /doc-graph/reverse) | configsync, server | K2, K6, K10 | — | — | implemented |
| `FEAT-DOCDEPS-009` | Proactive blast radius (cdx deps --impact) | docdeps, cli | K1, K4, K10 | — | — | implemented |
| `FEAT-DOCDEPS-010` | Transitive suspect-propagation advisory (HYBRID — never gates) | docdeps, config, cli, server | K1, K2, K7, K10 | — | — | implemented |

### `FEAT-DOCDEPS-001` — Doc↔doc edge config models (declaration = config, K2)

DocumentSpec gains an additive `depends_on` list of DocEdge (upstream doc id + typed role: depends/refines/implements/verifies), and MonitorConfig gains a `docdeps` policy block (enabled/gate/default_type/infer_from_links) so NOTHING about Pillar B is hardcoded (K0). Loud validators (K8): a self-edge, a duplicate upstream, or an edge to an unknown document id is a ConfigError; the edge round-trips byte-stable through dump_unit_file (K7). A pre-EPIC-B config with no `depends_on` loads unchanged (additive, K6).

### `FEAT-DOCDEPS-002` — Pure suspect-link detection (the two-fingerprint model)

docdeps.detect_suspect_links projects config + the downstream's stored baseline stamps into one verdict per edge — OK / SUSPECT / UNSTAMPED / MISSING_UPSTREAM — by recomputing each upstream's `upstream_fingerprint` (a normalized hash of the upstream BODY only, so the upstream's own `cdm.fingerprint` re-stamp never trips a suspect link) and comparing it to `cdm.upstream_hashes`. Pure + offline (K1), no clock, sorted by (doc_id, upstream_id) (K10) — the doc↔doc analogue of ownership.detect_orphans. Manifest stores the per-edge stamps additively under `cdm.upstream_hashes`, surviving a code↔doc heal.

### `FEAT-DOCDEPS-003` — Link inference + the per-edge baseline writer

docdeps.infer_edges_from_links scans each managed doc for relative Markdown cross-links that resolve to another managed doc and suggests them as edges (the low-tedium "suggest" — a human approves a graph rather than authoring one; external links, anchors, self-links and already-declared edges are skipped). stamp_edges is the one isolated impure writer — it (re)writes a downstream's baseline stamps, idempotently (K7) and per-edge — used only by the mutation commands, never by the detect-only check (K1).

### `FEAT-DOCDEPS-004` — SUSPECT_LINK surfaces through drift.detect (audience-scoped)

drift.detect appends doc↔doc suspect links as ordinary Drift data with a new DriftKind.SUSPECT_LINK (healable=False — resolved by a human ack, never auto-edited), carrying the DOWNSTREAM doc's audience (K3), so `cdx check` and `cdx monitor` see them with zero extra wiring. Detection writes nothing (K1); the `docdeps.enabled` knob gates whether they are computed at all.

### `FEAT-DOCDEPS-005` — cdx deps + cdx resolve --edge + the configurable gate

`cdx deps` shows the dependency graph + suspect status (read-only, K1/K4); `cdx deps --suggest` prints paste-ready `depends_on` config inferred from Markdown links; `cdx resolve --edge DOWN UP` re-stamps exactly that one edge after review (the finer-grained Doorstop `clear`, never re-blessing a whole doc) and is loud (K8) on an undeclared edge. `cdx check`'s nonzero exit honours the `docdeps.gate` knob — Custodex gates on a suspect link by default (unlike Doorstop, which exits 0) but a team can make it advisory.

### `FEAT-DOCDEPS-006` — Monitor records suspect links + baselines new edges (human-in-loop)

The Monitor never sends a SUSPECT_LINK to the backend (a fix would clobber the downstream prose). On `--apply` it establishes the baseline for a brand-new UNSTAMPED edge (recorded as a FIX — establishing a baseline is not blessing a change); a genuinely SUSPECT edge (the upstream changed) is ESCALATE'd to a human as an auditable ReviewRecord and the downstream is NEVER auto-edited (K5). A re-run with no change writes nothing (K7); a config with no edges is byte-identical (K6).

### `FEAT-DOCDEPS-007` — Central hub mirrors the doc↔doc graph (GET /doc-graph)

configsync._build_rows projects each document's declared `depends_on` edges into the synced ConfigDocument as an additive field — it rides in the full JSON blob, so NO migration and it round-trips through BOTH the in-memory and the SQL store. The read-time `GET /repos/{id}/doc-graph` route serves the cross-repo dependency GRAPH (who-depends-on-what, deduped + sorted) so a reverse query is answerable centrally; suspect STATUS stays repo-local because the doc files needed to hash an upstream's body live in the repo (K2). The central DB stays a rebuildable mirror, not truth.

### `FEAT-DOCDEPS-008` — Indexed reverse-dependency lookup (config_doc_edges + GET /doc-graph/reverse)

The hub FLATTENS every document's `depends_on` into a standalone, indexable `config_doc_edges` row (a StoredDocEdge — the SqlStore writes it on replace_config under Alembic 0007; the in-memory store derives the SAME list on read), so "which docs depend on X" is an indexed `WHERE upstream_id = X` instead of a JSON scan over every document. `GET /repos/{id}/doc-graph/reverse?doc=X` serves the direct dependents (deduped by downstream id, sorted, K10) — a required `doc` query (422 if omitted, K8); the table is a DERIVED index re-projected on every sync, so the central DB stays a rebuildable mirror (K2/K6), not truth.

### `FEAT-DOCDEPS-009` — Proactive blast radius (cdx deps --impact)

docdeps.impacted_by is the PROACTIVE complement to detect_suspect_links: before editing a document, walk the dependents reverse-reachable from it to answer "what must I review if I change DOC". Pure over the declared config graph (no file reads, no clock, K1/K10), transitive by default and cycle-safe, sorted, loud (K8) on an unknown id, and independent of `docdeps.enabled` (the graph exists either way). `cdx deps --impact DOC` surfaces it read-only (no backend, no network, K4) — an empty radius reads as an explicit "safe to change"; `--json` emits the machine form.

### `FEAT-DOCDEPS-010` — Transitive suspect-propagation advisory (HYBRID — never gates)

docdeps.propagate_suspect surfaces the EAGER transitive blast radius of the direct suspect links as an ADVISORY. Detection stays the pure Doorstop direct wavefront — only a changed-upstream edge is SUSPECT and only that gates `cdx check` — while a document whose upstream is itself pending review is reported as a SUSPECT_TRANSITIVE link, NEVER a drift: a transitive edge has no changed upstream body to stamp, so it must not gate (K1/K7). Pure over the direct verdicts + the declared graph via a shared cycle-safe reverse-reachable BFS (`_reverse_reachable`, extracted from and still backing impacted_by — characterized identical), sorted (K10). Surfaced read-only in `cdx deps --transitive` (opt-in `--json` shape) and an opt-in `cdx monitor` summary line gated by the additive `docdeps.transitive` knob (default OFF); the hub's `GET /doc-graph/reverse?transitive=true` returns the SAME closure as pure GRAPH reachability over the indexed edge table — never a suspect verdict, since the bodies needed to hash an upstream live in the repo, not the hub (K2).

## drift

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-DRIFT-001` | Detect-only drift grading | drift | K1, K2 | — | — | implemented |
| `FEAT-DRIFT-002` | Drift kind taxonomy | drift | K1 | — | — | implemented |
| `FEAT-DRIFT-003` | Drift as data, never an exception | drift | K1 | — | — | implemented |
| `FEAT-DRIFT-004` | Audience-aware drift suppression | drift | K3 | — | — | implemented |
| `FEAT-DRIFT-005` | Which-tier-moved HASH reporting | drift | K6 | — | — | implemented |
| `FEAT-DRIFT-006` | Anchor-identity change classification | drift | K2 | — | — | implemented |
| `FEAT-DRIFT-007` | Region ownership and lockability | drift | K1 | — | — | implemented |
| `FEAT-DRIFT-008` | Persistent human-review advisory | drift | K1 | — | — | implemented |
| `FEAT-DRIFT-009` | LLM-authored region staleness | drift | K1, K4 | — | — | implemented |
| `FEAT-DRIFT-010` | Report aggregation and human summary | drift | K1 | — | — | implemented |
| `FEAT-DRIFT-011` | Breaking-change severity classification | drift, schema, monitor | K6, K10 | — | — | implemented |

### `FEAT-DRIFT-001` — Detect-only drift grading

detect(config, config_dir) grades every document in a MonitorConfig against its freshly built code surface and returns a DriftReport — pure and side-effect free (K1): it never writes a file and never calls a backend. The repo root is the one shared resolve_repo_root(config_dir, root) formula.

### `FEAT-DRIFT-002` — Drift kind taxonomy

DriftKind enumerates the four discrepancy classes — MISSING_DOC (the doc file is absent, a stub can be created), HASH (the stored fingerprint differs from the surface hash), REGION (a managed region body is stale), and UNHEALABLE (a managed region with no known renderer the engine cannot regenerate).

### `FEAT-DRIFT-003` — Drift as data, never an exception

Each finding is a frozen Drift model carrying kind, doc_id, doc_path, detail, optional region_id, a healable flag, the doc's audience and an optional unified diff — drift is reported as data, distinct from the DriftError raised only for operational failures.

### `FEAT-DRIFT-004` — Audience-aware drift suppression

Every Drift carries the document's audience and the audience rule (K3) is honored: a docstring/comment- or private-symbol-only change does not move a user-guide surface hash (the extraction filter already excludes those) so it produces no HASH drift for a user-guide, while it does for an eng-guide.

### `FEAT-DRIFT-005` — Which-tier-moved HASH reporting

On a HASH drift, when the doc carries stored per-tier digests, detect names which surface tier(s) moved (signature / docstring / body) via SurfaceFingerprint.drifted_against, recorded on Drift.drifted_tiers; an old doc with only a composite fingerprint falls back to a composite-only message with empty drifted_tiers.

### `FEAT-DRIFT-006` — Anchor-identity change classification

On a HASH drift, detect compares the documented symbol anchor_ids against the stamped region anchor set and records Drift.anchors_added / anchors_removed — both empty means the SAME symbols changed internally (a re-bind/move), while a nonempty delta means a symbol was added, removed or renamed (a structural change). Empty when the doc predates anchor stamping.

### `FEAT-DRIFT-007` — Region ownership and lockability

detect grades only regions the spec declares: a human (or an llm-seeded region locked once a human edited it, via the shared region_is_locked predicate) region whose code moved is reported for manual review but marked healable=False so the engine never auto-edits it, while a stale rendered region is a healable REGION drift.

### `FEAT-DRIFT-008` — Persistent human-review advisory

A human-owned region carries a stored per-region hash stamped when last reviewed; while the body still matches that stamp the advisory keeps firing across a fingerprint heal until the human acknowledges, and with no stamp yet detect falls back to the code-moved fingerprint signal.

### `FEAT-DRIFT-009` — LLM-authored region staleness

A pure-llm region (no mechanical renderer) is backend-authored prose, not graded against a render: its body stands while the surface is unchanged and is surfaced as a healable REGION drift only when the whole-doc fingerprint diverges, so the backend re-authors it from the current surface.

### `FEAT-DRIFT-010` — Report aggregation and human summary

DriftReport bundles the tuple of drifts with an ok property (true when no drift) and a summary() that renders one human-readable line per drift — doc_id, optional region, kind, an UNHEALABLE marker and detail.

### `FEAT-DRIFT-011` — Breaking-change severity classification

On a HASH drift, detect classifies a Griffe-style ChangeSeverity purely from the P2 drifted_tiers + the P4 anchor deltas already computed (no new analysis): classify_change_severity returns BREAKING for a removed/renamed symbol or an in-place signature change (same symbol set, signature tier moved), ADDITIVE for a purely added symbol (additions are non-breaking even though they move the signature tier), COSMETIC for a docstring/body-only move, and UNKNOWN for a composite-only old doc with no structural signal. It rides on Drift.change_severity, is annotated in DriftReport.summary() for a HASH drift (UNKNOWN stays silent), and is mirrored onto the ReviewRecord as the additive 1.2.0 `change_severity` field so the audit log and central hub see breaking vs additive vs cosmetic at a glance.

## extract

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-EXTRACT-001` | Audience-aware code surface | extract | K0, K1, K3, K10 | — | — | implemented |
| `FEAT-EXTRACT-002` | Deterministic surface fingerprint | extract | K6, K10 | — | — | implemented |
| `FEAT-EXTRACT-003` | Pluggable extractor seam | extract | K0, K8 | — | — | implemented |
| `FEAT-EXTRACT-004` | Tiered fingerprint (signature / docstring / body) | extract | K6, K10 | — | — | implemented |
| `FEAT-EXTRACT-005` | Symbol anchor identity | extract | K10 | — | — | implemented |
| `FEAT-EXTRACT-006` | Shell extractor (sh/bash) | extract | K0, K1, K3, K4 | — | — | implemented |

### `FEAT-EXTRACT-001` — Audience-aware code surface

build_document_surface derives a per-document DocumentSurface from a code ref's symbols, filtered by audience: a user-guide surface drops private (`_`-prefixed) symbols and excludes docstrings; an eng-guide surface keeps all symbols and folds docstrings into the hash.

### `FEAT-EXTRACT-002` — Deterministic surface fingerprint

DocumentSurface.surface_hash() returns a stable sha256[:16] over the audience-filtered symbols (sorted keys, normalized whitespace, no wall-clock), so an unchanged surface always hashes identically.

### `FEAT-EXTRACT-003` — Pluggable extractor seam

An Extractor Protocol + language-keyed registry (register_extractor / get_extractor) lets a new language be a registration, not an engine edit; get_extractor is loud on an unknown language. The Python AST extractor is the default registration.

### `FEAT-EXTRACT-004` — Tiered fingerprint (signature / docstring / body)

SurfaceFingerprint decomposes the surface into per-tier digests plus a composite, so drift can report which tier moved; an opt-in body-AST tier lets an eng-guide detect an implementation change that leaves the signature untouched.

### `FEAT-EXTRACT-005` — Symbol anchor identity

anchor_id(name) is a lineno-free sha256[:16] of a symbol's qualified name, stable across a code move, recorded per region so drift can tell a structural symbol add/remove/rename from a purely internal change.

### `FEAT-EXTRACT-006` — Shell extractor (sh/bash)

ShellExtractor statically parses sh/bash function definitions (`name() {…}` and `function name {…}`) via the stdlib re module only, registered by default for .sh/.bash — proving a new language is a registration, never an engine edit. Never sources or executes the script.

## gitsync

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-GITSYNC-001` | Clone-on-demand for a not-local repo | gitfetch | K0, K1, K4, K8 | — | — | implemented |
| `FEAT-GITSYNC-002` | At-rest sealing of per-repo provider credentials | secrets | K0, K6, K8 | — | — | implemented |
| `FEAT-GITSYNC-003` | Short-lived GitHub App / GitLab OAuth token minting | gitauth | K0, K4, K8, K10 | — | — | implemented |
| `FEAT-GITSYNC-004` | GitHub docs-PR transport (atomic git-data flow) | pr | K0, K4, K8, K10 | — | — | implemented |
| `FEAT-GITSYNC-005` | Repo-agnostic clone-on-demand sync over a real git origin | gitfetch, configsync | K0, K1, K4, K10 | — | — | implemented |

### `FEAT-GITSYNC-001` — Clone-on-demand for a not-local repo

gitfetch.cloned_repo(spec, secret) materializes a remote repo into a throwaway temp tree (a shallow single-branch git clone via one injected _Cloner leaf) and yields it for run_sync(mode="local"), then tears the temp tree down on success OR error — so the server syncs a repo it does not hold locally without ever touching configsync. RemoteSpec carries the remote_url/provider/default_branch; the token reaches git only via an ephemeral GIT_ASKPASS env helper, never argv or the URL (_build_clone_argv is asserted secret-free); a clone failure is a loud SyncError with the secret scrubbed.

### `FEAT-GITSYNC-002` — At-rest sealing of per-repo provider credentials

secrets.SecretBox seals a per-repo git provider credential with AES-256-GCM (random-nonce; seal/open_secret round-trip) under a base64 32-byte KEK read from $CDMON_SECRET_KEY (secret_box_from_env). A git credential must be REPLAYED, so — unlike the E-06 bearer token's one-way sha256 — it is encrypted (reversible), the conscious at-rest fork. The store persists OPAQUE sealed bytes (set_provider_secret/repo_provider_secret) and never imports cryptography; sealing/opening happen at the route. A missing/short/non-base64 KEK or a tampered ciphertext is a loud SecretError.

### `FEAT-GITSYNC-003` — Short-lived GitHub App / GitLab OAuth token minting

gitauth mints a SHORT-LIVED provider token from a longer-lived credential so the hot token is never stored: github_app_jwt signs a 9-minute RS256 JWT (cryptography) which mint_github_installation_token exchanges at POST /app/installations/{id}/access_tokens; mint_gitlab_oauth_token exchanges a refresh token at the OAuth token endpoint; mint_provider_token dispatches by provider_kind over the opened credential JSON. The HTTP exchange is one injected leaf (K4); a bad PEM/non-RSA key/failed exchange/unknown kind is a loud TransportError.

### `FEAT-GITSYNC-004` — GitHub docs-PR transport (atomic git-data flow)

pr.GitHubTransport is the PRTransport sibling of GitLabTransport: submit opens a docs PR through the canonical ATOMIC GitHub git-data flow with no local checkout — read the target ref + base tree, POST a new tree carrying every healed file inline, POST a commit, create the source branch ref, then open the pull request — each through one injected _GitHubHttp leaf (stdlib urllib, K0/K4). from_repo(remote_url, token) builds either transport from a repo URL (the shared _parse_remote is the SSRF/host chokepoint).

### `FEAT-GITSYNC-005` — Repo-agnostic clone-on-demand sync over a real git origin

The clone-on-demand sync + docs-PR flow is repo-agnostic — it works against ANY real git repository, not just one fixture. The committed demo tree (and synthetic one- and two-unit repos, including one whose default branch is trunk, not main) are materialized into genuine MULTI-COMMIT git repos served as file:// origins — via the reproducible scripts/demo_as_git.py launcher (pinned git identity + a fixed commit date, K10) and the shared tests _gitrepo builder — and the server clones each on demand (gitfetch), surfaces its documents + a coverage snapshot off the REAL default-branch tip (configsync.run_sync), sees a newly committed undocumented file on re-sync, and opens a healed docs-PR. All over stdlib git on the local filesystem with NO network (K4); git-mode sync reads the default-branch baseline even when HEAD is on a feature branch ahead of it.

## heal

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-HEAL-001` | Idempotent region-only heal | heal | K2, K7 | — | — | implemented |
| `FEAT-HEAL-002` | Region body rendered from the code surface | blocks | K2, K10 | — | — | implemented |
| `FEAT-HEAL-003` | Config-template region extensibility | blocks | K0 | — | — | implemented |
| `FEAT-HEAL-004` | Human regions never authored (write-boundary preserve) | heal | K2, K5 | — | — | implemented |
| `FEAT-HEAL-005` | Authority-mode locking (llm-seeded fill-then-lock) | heal | K2, K5 | — | — | implemented |
| `FEAT-HEAL-006` | Per-region hash and symbol-anchor stamping | heal | K6, K10 | — | — | implemented |
| `FEAT-HEAL-007` | One-shared-truth fingerprint stamping | heal | K6, K10 | — | — | implemented |
| `FEAT-HEAL-008` | Structurally-typed proposed fix with whole-doc precedence | heal | K7 | — | — | implemented |
| `FEAT-HEAL-009` | Pure whole-doc correction for backend FIX parity | heal | K2, K10 | — | — | implemented |

### `FEAT-HEAL-001` — Idempotent region-only heal

regenerate_regions rewrites every known managed region from the code surface and refreshes the front-matter fingerprint, touching nothing else; it returns True only when the file's bytes actually change, so a second run with no underlying change writes nothing and returns False (K7).

### `FEAT-HEAL-002` — Region body rendered from the code surface

blocks.symbol_table renders the built-in deterministic symbol/kind/signature table and render_template renders a config-declared symbols/records table; expected_region resolves a region id (config template first, then the built-in "symbols") to the body it should hold, returning None when the id is unhealable. The body is always derived from the DocumentSurface, never the other way round (K2, K10).

### `FEAT-HEAL-003` — Config-template region extensibility

known_region_ids returns REGION_KEYS (the built-in "symbols") plus any config-declared template ids, so a new managed table (genbuild flags, switches, options) is a registered RegionTemplate rather than engine code, keeping the heal engine reusable (K0).

### `FEAT-HEAL-004` — Human regions never authored (write-boundary preserve)

A region id in preserve is never regenerated and a region-shaped fix targeting it is a no-op; for a whole-doc fix, apply_fix re-injects the document's current body for every preserved region before writing, so the B-02 guarantee that the engine never authors a human-owned region is enforced at the write boundary even against a backend that returned clobbering whole-doc text (K5).

### `FEAT-HEAL-005` — Authority-mode locking (llm-seeded fill-then-lock)

locked_region_ids derives, from the per-region modes map, the ids the engine must not author: every human region, plus any llm-seeded region a human has since edited (the shared manifest.region_is_locked predicate). regenerate_regions and apply_fix auto-add these locked ids to preserve, so an unlocked llm-seeded region is still filled by the engine while a locked one is left untouched (B-03).

### `FEAT-HEAL-006` — Per-region hash and symbol-anchor stamping

When the engine authors a region it stamps cdm.region_hashes[id] with the written body's hash so a later human edit is detectable, and a human region is stamped with its current body so its review advisory persists across a fingerprint heal; symbol-table regions additionally get cdm.region_anchors stamped with the surface's lineno-free anchor ids. A locked llm-seeded region keeps its existing stamp so re-stamping cannot falsely unlock it.

### `FEAT-HEAL-007` — One-shared-truth fingerprint stamping

_corrected computes the tiered surface fingerprint once and stamps both the composite identity (cdm.fingerprint) and the per-tier digests (cdm.fingerprint_tiers); heal, drift, layout and monitor pass the same include_body flag so heal never stamps a fingerprint that detect will not match (P2).

### `FEAT-HEAL-008` — Structurally-typed proposed fix with whole-doc precedence

apply_fix accepts any ProposedFixLike (a Protocol exposing region_id / new_region_body / new_doc_text, so schema.ProposedFix need not be imported): a region-shaped fix replaces one region, a whole-doc fix overwrites the file, an empty fix is a no-op, and re-applying an applied fix returns False (K7). When a fix carries both shapes the whole-doc text wins, since it is the only shape that also refreshes the fingerprint and closes the drift in one pass.

### `FEAT-HEAL-009` — Pure whole-doc correction for backend FIX parity

render_corrected returns the corrected full document text (regions plus fingerprint) from a document string without any I/O, reusing the same region and fingerprint logic as regenerate_regions so a backend's whole-doc FIX for a HASH drift and an in-engine heal agree byte-for-byte; preserve and modes drive the same B-02 lock and B-03 hash stamping.

## layout

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-LAYOUT-001` | Document Layout Standard conformance lint | layout | K1, K7, K8, K10 | — | — | implemented |
| `FEAT-LAYOUT-002` | Config-wide structural lint driver | layout | K1, K8, K10 | — | — | implemented |
| `FEAT-LAYOUT-003` | Conformant document scaffolding | layout | K2, K7, K10 | — | — | implemented |
| `FEAT-LAYOUT-004` | Front-matter auto-fix stamp | layout | K1, K7, K10 | — | — | implemented |
| `FEAT-LAYOUT-005` | HTML-twin pairing check | layout | K1, K10 | — | — | implemented |
| `FEAT-LAYOUT-006` | Index landing-page coverage check | layout | K0, K8 | — | — | implemented |
| `FEAT-LAYOUT-007` | Per-region authority state surface | layout | K1, K10 | — | — | implemented |
| `FEAT-LAYOUT-008` | Dependency-free Markdown renderer | build | K0, K10 | — | — | implemented |
| `FEAT-LAYOUT-009` | HTML-twin build orchestration | build, layout | K0, K10 | — | — | implemented |

### `FEAT-LAYOUT-001` — Document Layout Standard conformance lint

lint_doc grades one parsed Doc's SHAPE against the Layout Standard — the managed front-matter schema (cdm.schema_version pinned to LAYOUT_VERSION, audience, fingerprint), the title/purpose anchor order, and the region grammar/declaration consistency — emitting one LayoutIssue (a LayoutCode data value, never an exception) per violation. It is pure: string/Doc in, issues out.

### `FEAT-LAYOUT-002` — Config-wide structural lint driver

lint_config reads every existing document under config_dir/config.root and runs lint_doc on each, reporting malformed front matter as a MALFORMED_STRUCTURE issue rather than raising; a missing doc file is left to `cdx check`. It also lints declared HTML twins and runs the index-coverage check, returning the full LayoutIssue list.

### `FEAT-LAYOUT-003` — Conformant document scaffolding

scaffold_doc renders a fully-conformant, in-sync Markdown document for a DocumentSpec from a DocumentSurface — standard front matter (schema_version, audience, the composite fingerprint plus per-tier digests and symbol-table region anchors) and a body with title, placeholder purpose, and every declared region filled from the surface. The include_body flag must match MonitorConfig.fingerprint_body_tier so the stamp agrees with `cdx check`.

### `FEAT-LAYOUT-004` — Front-matter auto-fix stamp

stamp_doc_meta rewrites a Doc's front matter with the standard's static keys (cdm.schema_version and cdm.audience), preserving the existing fingerprint and body — the auto-fix behind `cdx lint --fix`. It cannot repair structural issues (title/purpose/regions/html), which require authoring.

### `FEAT-LAYOUT-005` — HTML-twin pairing check

lint_html_twin validates a declared HTML twin against the current Markdown body, flagging HTML_MISSING (no file), HTML_NOT_DERIVED (no embedded source hash), or HTML_STALE (embedded hash != current body hash). md_source_hash gives the deterministic CRLF-normalized sha256[:16] of Markdown (matching helium's algorithm) and embedded_md_hash reads the *-md-sha256 meta tag back out of the HTML; html_twin_path maps an X.md path to its X.html twin.

### `FEAT-LAYOUT-006` — Index landing-page coverage check

The index-coverage rule (folded into lint_config) is a target-agnostic structural check that every `index: true` document links every other document — by its .md source or its .html twin — so adding a doc to the config without linking it from the landing page raises an INDEX_INCOMPLETE LayoutIssue.

### `FEAT-LAYOUT-007` — Per-region authority state surface

region_states returns one read-only RegionState per region present in a Doc and declared in spec.region_keys (in region_keys order), reporting each region's RegionMode, whether the engine can render it (has_renderer), whether an llm-seeded region is locked by human edits, and whether it is advisory (heal never authors it). config_region_states is the file-reading driver behind `cdx lint --modes`; both are pure and never re-validate the modes map.

### `FEAT-LAYOUT-008` — Dependency-free Markdown renderer

render_markdown turns a managed doc body into an HTML fragment with no third-party dependency, covering the constructs managed docs use (headings with slugged anchor ids, paragraphs, GFM tables, ordered/unordered lists, blockquotes, fenced code, inline code/bold/links, rules); it strips CDM region markers, keeps the generated region tables, and rewrites intra-guide X.md links to their X.html twins. Same Markdown in, same HTML out.

### `FEAT-LAYOUT-009` — HTML-twin build orchestration

build renders every `html: true` document under config_dir/config.root to its .html twin, wrapping render_markdown output in a styled page with a sidebar nav (grouped by nav_section, labelled by nav_label/title) and embedding the body's md_source_hash in a code-doc-md-sha256 meta tag so lint_html_twin recognises the twin as derived and current. Missing source docs are skipped; it returns the written paths.

## learn

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-LEARN-001` | Deterministic similarity retrieval over resolved drifts | similar | K0, K10 | — | — | implemented |
| `FEAT-LEARN-002` | Embedding-free weighted feature-match score | similar | K0, K10 | — | — | implemented |
| `FEAT-LEARN-003` | Few-shot exemplar payload for the agent | similar | K8, K10 | — | — | implemented |
| `FEAT-LEARN-004` | Promotion detector for recurring resolved drift shapes | promotion | K0, K10 | — | — | implemented |
| `FEAT-LEARN-005` | Decision-only auto-promotion guard | promotion | K10 | — | — | implemented |
| `FEAT-LEARN-006` | Deterministic rule synthesis and matching | promotion | K4, K10 | — | — | implemented |

### `FEAT-LEARN-001` — Deterministic similarity retrieval over resolved drifts

rank_similar mines the review log joined to the resolutions log and returns the top_n most-similar PAST RESOLVED records to a target ReviewRecord as Exemplars; the population is resolved-only (via resolved_index, last-write-wins) with the target excluded by record_id, and the result is a stable total order over (score, recency, record_id).

### `FEAT-LEARN-002` — Embedding-free weighted feature-match score

The Exemplar score is a deterministic weighted sum of equal-attribute matches defined by FEATURE_WEIGHTS (surface_hash 5.0, doc_id 3.0, drift_kind 2.0, audience 1.0; max 11.0) — no embeddings and no new dependency, so retrieval is offline and fully reproducible (vector retrieval is a documented future option).

### `FEAT-LEARN-003` — Few-shot exemplar payload for the agent

The frozen Exemplar model pairs a past resolved ReviewRecord with its ResolutionRecord human outcome and the match score, so the agent backend can feed "here is a drift like this one and how a human resolved it" few-shot examples; it is extra="forbid" so an unexpected key is a loud error.

### `FEAT-LEARN-004` — Promotion detector for recurring resolved drift shapes

detect_promotions groups resolved records by the generalizable shape (doc_id, drift_kind, audience) — NOT surface_hash — and emits a PromotionCandidate per shape whose resolved records unanimously share one decision >= min_count times; orphan resolutions are ignored and output is deterministically sorted. Pure, no I/O, no wall-clock.

### `FEAT-LEARN-005` — Decision-only auto-promotion guard

Only the content-free DECISION resolutions in PROMOTABLE_RESOLUTIONS (invalidated, rejected) auto-promote; overridden (human prose) and accepted (already LLM-free mechanical fix) are deliberately excluded, so an automated rule only ever reproduces a content-free human judgement.

### `FEAT-LEARN-006` — Deterministic rule synthesis and matching

rule_from_candidate maps a PromotionCandidate to a frozen PromotionRule (both promotable decisions yield the INVALIDATE verdict), and rule_for returns the first rule whose (doc_id, drift_kind, audience) shape matches a Drift (else None) — enabling opt-in, additive rule application that resolves a matched drift with zero backend calls.

## manifest

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-MANIFEST-001` | Front-matter document parse | manifest | K7, K8 | — | — | implemented |
| `FEAT-MANIFEST-002` | Managed-region model | manifest | K8 | — | — | implemented |
| `FEAT-MANIFEST-003` | Byte-exact region edit | manifest | K7, K8 | — | — | implemented |
| `FEAT-MANIFEST-004` | Composite fingerprint storage | manifest | K10 | — | — | implemented |
| `FEAT-MANIFEST-005` | Tiered fingerprint storage | manifest, extract | K6, K10 | — | — | implemented |
| `FEAT-MANIFEST-006` | Per-region content hash | manifest | K10 | — | — | implemented |
| `FEAT-MANIFEST-007` | Shared region-lock predicate | manifest | K10 | — | — | implemented |
| `FEAT-MANIFEST-008` | Region anchor storage | manifest | K10 | — | — | implemented |
| `FEAT-MANIFEST-009` | Standard-meta stamp and re-render | manifest | K7, K10 | — | — | implemented |

### `FEAT-MANIFEST-001` — Front-matter document parse

parse_doc reads a file and parse_text (its file-I/O-free twin) split an optional leading YAML front-matter fence from the body into a frozen Doc (path, meta, body, raw); malformed or non-mapping front matter raises a loud DriftError.

### `FEAT-MANIFEST-002` — Managed-region model

regions maps each CDM:BEGIN/CDM:END managed-region id to its body text, raising a loud DriftError on malformed structure (unterminated, duplicate, nested, orphan END, or mismatched END id).

### `FEAT-MANIFEST-003` — Byte-exact region edit

set_region replaces one region's body and returns (text, changed), preserving every byte outside the markers exactly and reporting changed=False when the id is absent or its body already equals the new text.

### `FEAT-MANIFEST-004` — Composite fingerprint storage

stored_fingerprint reads cdm.fingerprint from a Doc's meta and set_fingerprint returns a copy of meta with cdm.fingerprint set, copying the whole cdm map forward so sibling keys survive.

### `FEAT-MANIFEST-005` — Tiered fingerprint storage

stored_fingerprint_tiers decodes the additive cdm.fingerprint_tiers block back into a SurfaceFingerprint (None on a pre-P2 doc) and set_fingerprint_tiers stamps it beside the composite, omitting None sub-tiers for a faithful round-trip.

### `FEAT-MANIFEST-006` — Per-region content hash

region_body_hash returns a CRLF-normalized sha256[:16] of a region body (mirroring layout.md_source_hash); stored_region_hash and set_region_hash read and additively stamp cdm.region_hashes[region_id] so a stamped hash survives a later heal.

### `FEAT-MANIFEST-007` — Shared region-lock predicate

region_is_locked is the single shared lock truth consumed by drift and heal: a region is locked iff it has a stored region hash AND the current body's hash differs from it (a human edited it since the engine stamped it); no stored hash means never locked.

### `FEAT-MANIFEST-008` — Region anchor storage

stored_region_anchors reads cdm.region_anchors[region_id] as a tuple (None on a pre-P4 doc) and set_region_anchors additively stamps the sorted anchor_ids of the symbols a region documents, so drift can tell a symbol add/remove/rename from a purely internal change.

### `FEAT-MANIFEST-009` — Standard-meta stamp and re-render

stamp_standard_meta sets the Layout Standard static keys cdm.schema_version and cdm.audience while preserving every other cdm key, and render_doc re-emits front matter plus body to one string (body verbatim when meta is empty, sorted-key YAML fence otherwise).

## monitor

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-MONITOR-001` | End-to-end drift orchestration loop | monitor | K1, K4, K10 | — | — | implemented |
| `FEAT-MONITOR-002` | Pure detect delegate | monitor | K1 | — | — | implemented |
| `FEAT-MONITOR-003` | Opt-in auto-apply heal path | monitor | K5, K7 | — | — | implemented |
| `FEAT-MONITOR-004` | Every verdict is always recorded and emitted | monitor | K5 | — | — | implemented |
| `FEAT-MONITOR-005` | Self-describing record provenance snapshot | monitor | K6, K10 | — | — | implemented |
| `FEAT-MONITOR-006` | Recheck-after-apply remaining set | monitor | K7, K10 | — | — | implemented |
| `FEAT-MONITOR-007` | Opt-in promoted-rule resolution (zero backend calls) | monitor | K4, K5, K6 | — | — | implemented |
| `FEAT-MONITOR-008` | Opt-in few-shot exemplar retrieval | monitor | K4, K6 | — | — | implemented |
| `FEAT-MONITOR-009` | Region-authority-aware fix request | monitor | K6 | — | — | implemented |

### `FEAT-MONITOR-001` — End-to-end drift orchestration loop

Monitor.run runs the full pipeline per detected drift: detect (check) -> per-drift backend verdict -> build + record a ReviewRecord -> optionally apply a FIX -> re-detect, returning a MonitorResult of handled drifts, remaining drifts, and records. Every collaborator (backend, sink, now clock) is injected so the loop runs offline and deterministically.

### `FEAT-MONITOR-002` — Pure detect delegate

Monitor.check returns a DriftReport by delegating to drift.detect over the config and config_dir, mutating nothing — the read-only detection step the run loop opens and closes with.

### `FEAT-MONITOR-003` — Opt-in auto-apply heal path

run applies a fix only when apply is effectively true (overriding config.apply_default) AND the backend returned a FIX with a non-null fix, calling heal.apply_fix at the write boundary; otherwise it mutates nothing. It computes the human-owned preserve set and per-region modes from the spec so apply_fix cannot clobber human regions.

### `FEAT-MONITOR-004` — Every verdict is always recorded and emitted

For every drift, run builds a ReviewRecord via _record_for, appends it to the review log, and emits it to the central sink — regardless of verdict — so INVALIDATE/ESCALATE are surfaced for a human and never silently dropped.

### `FEAT-MONITOR-005` — Self-describing record provenance snapshot

Each ReviewRecord carries a config_snapshot (backend kind, root) plus an optional source_sha, a deterministic record_id, and a joinable ticket (CDM-<record_id>); a rule-resolved record additionally stamps resolved_by="rule" and a body-tier run records fingerprint_body_tier=True, both additively.

### `FEAT-MONITOR-006` — Recheck-after-apply remaining set

After processing all drifts, run performs a fresh check() and returns its drifts as remaining, so a FIX'd drift drops out while ESCALATE or unapplied drift persists — the idempotent recheck that proves a heal converged.

### `FEAT-MONITOR-007` — Opt-in promoted-rule resolution (zero backend calls)

When rules are supplied, run resolves a matching drift via promotion.rule_for with ZERO backend calls — the learned cost-curve win — synthesizing a RULE_CAUSE_PREFIX cause, recording and emitting it marked RULE-sourced, and applying nothing (rules carry no fix). The default empty rules tuple keeps every drift going to the backend.

### `FEAT-MONITOR-008` — Opt-in few-shot exemplar retrieval

When use_exemplars is on, run reads the review log and resolutions log ONCE up front and, per drift, ranks the most-similar past RESOLVED records via similar.rank_similar (top_n) to attach as exemplars on the FixRequest; the default OFF reads nothing and leaves exemplars empty.

### `FEAT-MONITOR-009` — Region-authority-aware fix request

run builds each FixRequest with the drifted region's authority mode (RegionMode, defaulting to GENERATED for a whole-doc drift), an index_body for an index-sourced region, opt-in writing style_guidance for a no-renderer llm region via _style_guidance_for, and the document's context_refs + repo_root — so a backend authors prose vs renders mechanically as the region dictates.

## ownership

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-OWNERSHIP-001` | Per-document ownership-of-record | config | K0, K2, K6, K7 | — | — | implemented |
| `FEAT-OWNERSHIP-002` | Pure ownership resolver + roster snapshot | ownership | K0, K1, K10 | — | — | implemented |
| `FEAT-OWNERSHIP-003` | Orphan & DRI-vacant detection (pure) | ownership | K1, K5, K8, K10 | — | — | implemented |
| `FEAT-OWNERSHIP-004` | cdx ownership CLI (read-only accountability gate) | cli, ownership | K1, K4, K8, K10 | — | — | implemented |
| `FEAT-OWNERSHIP-005` | Central roster mirror (persisted, both stores) | server, ownership | K0, K4, K6, K10 | — | — | implemented |
| `FEAT-OWNERSHIP-006` | Admin-token roster routes (global, not per-repo) | server | K0, K8 | — | — | implemented |
| `FEAT-OWNERSHIP-007` | Per-repo /ownership view + cross-repo departure cascade | server, ownership | K0, K5, K10 | — | — | implemented |
| `FEAT-OWNERSHIP-008` | Reassign-owner edit (the orphan fix, config = truth) | config, generate, server | K5, K6, K7, K8 | — | — | implemented |
| `FEAT-OWNERSHIP-009` | Live demo ownership (seeded departure → visible orphan) | server, ownership | K4, K5, K10 | — | — | implemented |

### `FEAT-OWNERSHIP-001` — Per-document ownership-of-record

DocumentSpec carries optional owner/team/dri keys (additive, K6) so a document declares its accountable identity in config — the single source of truth for ownership (K0, never inferred from code). Own by team with a person as the current DRI, so a departure demotes to "DRI vacant" rather than orphaning the doc; the keys round-trip byte-identically through dump_unit_file (K7) and a doc that declares none inherits its unit's frontmatter owner.

### `FEAT-OWNERSHIP-002` — Pure ownership resolver + roster snapshot

ownership.resolve_ownership projects a loaded config into one EffectiveOwner per document — accountable = dri→owner→team→inherited unit owner, durable = team→owner→inherited — sorted and clock-free (K1/K10). The Identity / RosterSnapshot models are the offline, injected central mirror an unknown-or-departed name reads as inactive against (is_active(None) and an unknown name are both False — an owner the roster cannot vouch for is not an active accountable party).

### `FEAT-OWNERSHIP-003` — Orphan & DRI-vacant detection (pure)

ownership.detect_orphans classifies each resolved document against the injected roster snapshot — UNOWNED (no identity named), ORPHAN_OWNER_DEPARTED (the accountable owner is departed/unknown with no active fallback), or ORPHAN_DRI_VACANT (the DRI left but the durable team still owns it — a soft orphan resolved by assigning a new DRI). An orphan is never healable (no code change fixes it); OK docs are omitted by default so the result is exactly what needs a human (K5). Pure, sorted, clock-free (K1/K10).

### `FEAT-OWNERSHIP-004` — cdx ownership CLI (read-only accountability gate)

cdx ownership lists every document's accountable/durable owner from config and, given an offline --roster YAML, cross-checks it to flag orphaned (departed-owner) documents — pure, offline (K1/K4), no backend. --json emits {owners, findings}; --fail-on-orphan turns a departed-owner orphan into a nonzero exit (an accountability CI gate), while an UNOWNED doc (a coverage gap, not a departure) does not trip it. load_roster is loud on a malformed roster (K8).

### `FEAT-OWNERSHIP-005` — Central roster mirror (persisted, both stores)

The central server persists a roster of identities (people/teams) as the accountability MIRROR — upsert_identity / list_roster / mark_identity_departed on the Store Protocol, implemented identically over InMemoryStore AND SqlStore (Postgres-first; SQLite offline twin + pg) and created by Alembic migration 0006. The per-document owner/team/dri + resolved accountable/durable ride in the existing config_documents JSON column (additive, K6 — NO column migration). Insertion-ordered, injected timestamps (K10).

### `FEAT-OWNERSHIP-006` — Admin-token roster routes (global, not per-repo)

POST /admin/roster (upsert) and POST /admin/roster/{name}/departed gate cross-repo roster mutations behind a SEPARATE global admin token ($CDMON_ADMIN_TOKEN), never a per-repo token — a leaked repo token must not grant roster access (401 missing / 403 wrong; open when unset, for dev). GET /roster is an open read. A departed mark on an unknown name is a loud 404 (K8).

### `FEAT-OWNERSHIP-007` — Per-repo /ownership view + cross-repo departure cascade

GET /repos/{id}/ownership reads the synced config documents (which carry the resolved accountable/durable owner) and crosses them against the LIVE roster through ownership.detect_orphans, returning {owners, findings, orphan_count}. Because the orphan check runs on READ, marking one identity departed cascades — every document that identity is accountable for, across EVERY repo, flips to an orphan on the next read with no re-sync. Open read; deterministic (K5/K10).

### `FEAT-OWNERSHIP-008` — Reassign-owner edit (the orphan fix, config = truth)

ReassignOwnerEdit (a new ConfigEdit discriminated-union action) + the pure config.set_document_owner editor reassign a document's owner/team/dri through the EDITOR generate-to-disk flow: a provided value sets that field, None leaves it (a partial reassignment keeps the rest). apply_edits_to_disk rewrites config/cdmon/<unit>.yaml (byte-stable, idempotent K7) and the re-sync re-mirrors — the human fix that clears an orphan, with config as the single source of truth.

### `FEAT-OWNERSHIP-009` — Live demo ownership (seeded departure → visible orphan)

The live demo (scripts/seed_demo.py → :33333) seeds the central roster with the teams that own the demo + dogfood configs (active) and ONE departed person (dana, the DRI of the demo's core-api doc), so GET /repos/demo-taskflow/ownership shows a real soft orphan (core-api orphan_dri_vacant) out of the box while the dogfood repo (cdmon-team active) stays clean — the accountability feature is visible and clickable, not an empty state.

## pr

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-PR-001` | Doc-patch producer (sync_pr) | syncpr | K4, K5, K7, K10 | — | — | implemented |
| `FEAT-PR-002` | dry-run patch with byte-for-byte tree restore | syncpr | K1, K10 | — | — | implemented |
| `FEAT-PR-003` | Structural loop-breaker (should_sync) | syncpr | K1, K10 | — | — | implemented |
| `FEAT-PR-004` | Deterministic merge-request plan | pr | K7, K10 | — | — | implemented |
| `FEAT-PR-005` | Injected PR transport seam | pr | K4, K10 | — | — | implemented |
| `FEAT-PR-006` | GitLab docs-MR transport (stdlib-only, env-built) | pr | K0, K4, K8 | — | — | implemented |
| `FEAT-PR-007` | Coverage-gap issue plan | issues | K10 | — | — | implemented |
| `FEAT-PR-008` | GitLab and GitHub issue transports | issues | K0, K4, K8, K10 | — | — | implemented |
| `FEAT-PR-009` | Jira-style DriftTicket artifact | ticket | K6, K8, K10 | — | — | implemented |
| `FEAT-PR-010` | Pure deterministic ticket builder | ticket | K1, K10 | — | — | implemented |
| `FEAT-PR-011` | Ticket status from human resolution | ticket | K1 | — | — | implemented |

### `FEAT-PR-001` — Doc-patch producer (sync_pr)

sync_pr orchestrates around a Monitor to answer "what would healing the docs change?": it snapshots each document before, heals in place via the existing apply pipeline, and returns a SyncResult carrying a deterministic per-file difflib unified-diff patch plus the sorted changed_paths. It adds no heal/backend logic of its own.

### `FEAT-PR-002` — dry-run patch with byte-for-byte tree restore

sync_pr(dry_run=True) computes the same patch but restores the document tree to its starting bytes — rewriting each pre-existing doc to its before-text and DELETING any file the run newly created (e.g. a missing-doc stub) — so the working tree is untouched.

### `FEAT-PR-003` — Structural loop-breaker (should_sync)

should_sync is a pure, read-only predicate over a changed-file list and a MonitorConfig: a bot doc-only commit (every changed path is a managed document, normalized POSIX) returns False so the heal does not re-trigger and open another docs PR; any file outside the managed-doc set returns True and an empty set returns False.

### `FEAT-PR-004` — Deterministic merge-request plan

plan_docs_pr turns a SyncResult into a frozen MergeRequestPlan whose source_branch is f"{branch_prefix}-{sha256(patch)[:12]}" (stable per unchanged patch, unique per change), carrying the current on-disk content of each changed doc; an empty sync returns None (no MR).

### `FEAT-PR-005` — Injected PR transport seam

PRTransport is a runtime-checkable Protocol with a submit(plan) method, so a fake transport drives the docs-PR flow and tests assert the exact plan without touching the network. open_docs_pr plans then (unless dry_run, which returns the plan dict) submits through the injected transport.

### `FEAT-PR-006` — GitLab docs-MR transport (stdlib-only, env-built)

GitLabTransport.submit performs the canonical 3-call GitLab REST flow — create the source branch off the target, commit every healed file as one update action, then open the merge request — through one injected HTTP leaf (a stdlib urllib client built lazily when none is supplied, no requests). GitLabTransport.from_env builds it from CI env, raising a loud TransportError when the project id or token is unset.

### `FEAT-PR-007` — Coverage-gap issue plan

plan_coverage_issue turns a CoverageReport plus suggest_owners output into a frozen IssuePlan whose body groups every undocumented public symbol under its suggested owner (owners sorted ascending, a "(new doc)" marker and the suggestion reason per group); no gaps returns None.

### `FEAT-PR-008` — GitLab and GitHub issue transports

GitLabIssueTransport and GitHubIssueTransport each POST one coverage-gap issue (to /projects/<id>/issues and /repos/<repo>/issues respectively) through one injected HTTP leaf so tests never hit the network; each from_env builds from CI env with a loud TransportError on a missing id/repo or token, and open_coverage_issue plans then submits (or returns the plan dict on dry_run).

### `FEAT-PR-009` — Jira-style DriftTicket artifact

DriftTicket is the frozen, immutable artifact that replaces the one-line ProposedFix rationale: title, summary, severity, drift kind, affected public symbols, root cause, proposed change + diff, change_kind, a verdict-aware acceptance checklist of AcceptanceCheck items, recommended action, and a schema_version.

### `FEAT-PR-010` — Pure deterministic ticket builder

build_ticket derives every DriftTicket field from a handled drift, its verdict/cause/fix, and the code surface with no clock and no I/O — severity from the verdict/healability, change_kind from the fix shape, and the acceptance checklist from the verdict — so identical inputs always yield an identical ticket.

### `FEAT-PR-011` — Ticket status from human resolution

ticket_status maps a human ResolutionRecord outcome to a TicketStatus: None to PROPOSED, accepted to VALIDATED, overridden to CHANGES_REQUESTED, and rejected or invalidated both to REJECTED.

## quality

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-QUALITY-001` | Four-category writing-style map | docstyle | K0 | — | — | implemented |
| `FEAT-QUALITY-002` | Loud doc-style template validation | docstyle | K8 | — | — | implemented |
| `FEAT-QUALITY-003` | Composed writing guidance for the authoring prompt | docstyle | K10 | — | — | implemented |
| `FEAT-QUALITY-004` | Idempotent doc-style.yaml serialization | docstyle | K7, K10 | — | — | implemented |
| `FEAT-QUALITY-005` | coverage.rpt builder over the real coverage engine | report | K1, K10 | — | — | implemented |
| `FEAT-QUALITY-006` | Suggested-unit attribution for coverage gaps | report | K10 | — | — | implemented |
| `FEAT-QUALITY-007` | Byte-stable .rpt render / parse round-trip | report | K7, K8, K10 | — | — | implemented |
| `FEAT-QUALITY-008` | cdx doctor offline adoption preflight | doctor | K1, K4, K10 | — | — | implemented |
| `FEAT-QUALITY-009` | WARN-vs-FAIL doctor grading philosophy | doctor | K8 | — | — | implemented |

### `FEAT-QUALITY-001` — Four-category writing-style map

load_doc_style parses a `doc-style.yaml` into a DocStyleMap of a `defaults` DocStyleSelection plus per-document DocStyleMapping overrides, where each maps a document to ONE template name per the four STYLE_CATEGORIES (document-type, tone, writing-style, vocabulary). DocStyleMap.style_for resolves a document id to its explicit mapping, else the defaults.

### `FEAT-QUALITY-002` — Loud doc-style template validation

load_doc_style validates the frontmatter (cdmon-config-version + a `doc-style-map` kind) and that EVERY named template — the defaults and every mapping's four names — resolves to an existing templates_root/<category>/<name>.md, raising a single ConfigError listing every offending selection so a typo is caught once with the full picture.

### `FEAT-QUALITY-003` — Composed writing guidance for the authoring prompt

resolve_style_files projects a DocStyleSelection to its `category -> template path` mapping in the fixed STYLE_CATEGORIES order, and read_style_guidance reads those four bodies from disk and concatenates them under `## Writing guidance — <category>` headers, deterministically, to feed the agent's authoring prompt when it writes a no-renderer `llm` region.

### `FEAT-QUALITY-004` — Idempotent doc-style.yaml serialization

dump_doc_style serializes a DocStyleMap back to canonical `---`-fenced frontmatter + body YAML such that load_doc_style of the written text round-trips to an equal model; key order is deterministic and a loaded-then-dumped map is byte-identical, with only the frontmatter `updated:` field refreshed from the injected clock.

### `FEAT-QUALITY-005` — coverage.rpt builder over the real coverage engine

build_coverage_rpt produces a CoverageRpt (RptSummary + per-unit RptUnit slices + an RptUndocumented gap list) by reusing effective_coverage → inventory.discover_files/discover_symbols → coverage.resolve_coverage, so the report counts are the same facts `cdx coverage` shows, never a parallel computation. Per-unit attribution is deepest-wins and waived files leave both sides of each percentage.

### `FEAT-QUALITY-006` — Suggested-unit attribution for coverage gaps

Each RptUndocumented gap file pairs its `path` with the `suggested_unit` it should be declared in — the deepest unit whose `dir-covered` contains the path and whose `source-files-format` includes its extension — or a None suggestion with a `reason` explaining the format mismatch or that no unit directory contains it.

### `FEAT-QUALITY-007` — Byte-stable .rpt render / parse round-trip

render_rpt emits a CoverageRpt as a `---` frontmatter block (report-version / kind / repo / ref / generated-by, no wall-clock) over a fixed-key-order YAML body with every list sorted and percentages at two decimals (`n/a` when the denominator is 0), and parse_rpt is its loud inverse so parse_rpt(render_rpt(r)) == r; write_rpt writes the text to config_dir/coverage.rpt.

### `FEAT-QUALITY-008` — cdx doctor offline adoption preflight

run_checks answers "is this repo wired up correctly enough to run cdx and report centrally?" with a deterministic, ordered list of Check results over config / documents / backend / central (and the agent extra), reading only os.environ / $PATH / installed distributions with no network and no mutation.

### `FEAT-QUALITY-009` — WARN-vs-FAIL doctor grading philosophy

Each Check carries a CheckStatus where only FAIL fails the gate: a merely absent prereq (no `claude` CLI, unset $ANTHROPIC_API_KEY, missing langgraph extra, an unset central token, an unresolved code ref) is a WARN because the config is valid, while a structurally broken config (an `http` central sink missing its url or repo_id) is a FAIL.

## record

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-RECORD-001` | Public versioned review record | schema | K5, K6, K10 | — | — | implemented |
| `FEAT-RECORD-002` | Additive schema evolution | schema | K6 | — | — | implemented |
| `FEAT-RECORD-003` | Model-derived JSON schema | schema | K6 | — | — | implemented |
| `FEAT-RECORD-004` | Proposed fix model | schema | K5 | — | — | implemented |
| `FEAT-RECORD-005` | Deterministic record id | schema | K10 | — | — | implemented |
| `FEAT-RECORD-006` | Separate resolution outcome event | schema | K5, K6, K10 | — | — | implemented |
| `FEAT-RECORD-007` | Append-only review log | reviewlog | K5, K8 | — | — | implemented |
| `FEAT-RECORD-008` | Deterministic review summaries | reviewlog | K10 | — | — | implemented |
| `FEAT-RECORD-009` | Append-only resolutions log with last-write-wins join | reviewlog | K5, K10 | — | — | implemented |
| `FEAT-RECORD-010` | Shared ingest wire envelope | sinks | K6 | — | — | implemented |
| `FEAT-RECORD-011` | Offline-default sinks | sinks | K0, K4 | — | — | implemented |
| `FEAT-RECORD-012` | Resilient HTTP sink with outbox | sinks | K0, K4, K6 | — | — | implemented |
| `FEAT-RECORD-013` | Config-resolved sink factory | sinks | K4, K8 | — | — | implemented |

### `FEAT-RECORD-001` — Public versioned review record

ReviewRecord is the public, frozen/extra-forbid payload for one handled drift — carrying the original drift, the LLM cause, the Verdict, the ProposedFix, and an audience/config/hash snapshot — versioned by schema_version so the central system has one contract to consume.

### `FEAT-RECORD-002` — Additive schema evolution

ReviewRecord grows only by appending optional fields (source_sha, ticket, drifted_tiers) that default empty, so an old "1.0.0" JSONL line still model_validate_json's; minor schema_version bumps signal the new metadata without breaking pre-existing records.

### `FEAT-RECORD-003` — Model-derived JSON schema

review_record_schema and resolution_record_schema emit the public JSON Schema straight from the pydantic models (model_json_schema), so the model is the single source of truth and the schema is never hand-written.

### `FEAT-RECORD-004` — Proposed fix model

ProposedFix is the backend's remediation for one drift — either a region-shaped fix (region_id + new_region_body) or a whole-doc fix (new_doc_text), always with a rationale — and satisfies the structural heal.ProposedFixLike protocol.

### `FEAT-RECORD-005` — Deterministic record id

new_record_id derives a stable 12-char sha256 prefix from a drift's identity (doc_id, surface_hash, detected_at), so the same drift handled with the same inputs always yields the same id — reproducible and dedupable without a clock or counter.

### `FEAT-RECORD-006` — Separate resolution outcome event

ResolutionRecord captures the human OUTCOME (Resolution: accepted / overridden / rejected / invalidated) as a separate frozen event linked to a ReviewRecord by record_id, so a reviewer's decision is recorded without ever mutating the immutable review record.

### `FEAT-RECORD-007` — Append-only review log

reviewlog.append writes each ReviewRecord as one JSON line in append mode (never rewriting existing lines) and read_all parses every line back; a corrupt non-empty line raises a loud typed SchemaError naming the line number rather than being silently skipped.

### `FEAT-RECORD-008` — Deterministic review summaries

summarize counts records by verdict, audience, and doc id (each map sorted by key) with a total, and select_by_verdict returns the records of one Verdict in append (oldest-first) order — pure, order-stable, and deterministic.

### `FEAT-RECORD-009` — Append-only resolutions log with last-write-wins join

append_resolution and read_resolutions manage a separate resolutions JSONL (DEFAULT_RESOLUTIONS_PATH under .cdmon); resolved_index joins record_id to its ResolutionRecord last-write-wins, and summarize_with_resolutions reports resolved-vs-unresolved counts while ignoring orphan resolutions.

### `FEAT-RECORD-010` — Shared ingest wire envelope

IngestEnvelope is the one versioned client to server wire format, wrapping a ReviewRecord with its RepoIdentity (repo_id, commit, optional local_path / default_branch), so the HttpSink client and the central /ingest server share a single schema with no separate DTOs.

### `FEAT-RECORD-011` — Offline-default sinks

A sink emits a ReviewRecord to the central system; the Sink protocol's default NullSink emits nowhere and FileSink appends JSONL as an offline stand-in, so reporting runs in CI with zero network.

### `FEAT-RECORD-012` — Resilient HTTP sink with outbox

HttpSink POSTs an IngestEnvelope with an injected stdlib-only client (no requests), draining a JSONL outbox oldest-first, retrying with a bounded budget, and queuing to the outbox on final failure — emit NEVER raises, so a down central system can't break a heal run.

### `FEAT-RECORD-013` — Config-resolved sink factory

make_sink resolves a CentralConfig to the right sink (none / file / http), raising a loud SchemaError on a missing required field (file path, http url, or repo_id) and building the RepoIdentity with config-or-CI_COMMIT_SHA commit precedence.

## reference

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-REFERENCE-001` | Golden feature catalog (typed, loadable) | featurecatalog | K0, K1, K8, K10 | — | — | implemented |
| `FEAT-REFERENCE-002` | Rendered human feature reference | featurecatalog | K7, K10 | — | — | implemented |
| `FEAT-REFERENCE-003` | Feature traceability matrix engine | traceability | K0, K1, K8, K10 | — | — | implemented |
| `FEAT-REFERENCE-004` | Test-wiki AST extractor | testwiki | K0, K1, K8, K10 | — | — | implemented |
| `FEAT-REFERENCE-005` | Source index + no-orphan-capability check | srcindex | K0, K1, K8, K10 | — | — | implemented |
| `FEAT-REFERENCE-006` | Rendered source wiki | srcindex | K7, K10 | — | — | implemented |
| `FEAT-REFERENCE-007` | cdx wiki regeneration + freshness gate | wiki | K0, K7, K8, K10 | — | — | implemented |

### `FEAT-REFERENCE-001` — Golden feature catalog (typed, loadable)

featurecatalog.load_catalog aggregates feature-doc/catalog/*.yaml into a validated, id-sorted FeatureCatalog of frozen Feature records (extra=forbid); it is loud (CatalogError) on a missing/empty dir, malformed yaml, a bad id pattern, a duplicate id across files, or a feature naming a non-existent module — the single machine-readable source of truth for every cdx feature.

### `FEAT-REFERENCE-002` — Rendered human feature reference

featurecatalog.render_features_md renders feature-doc/FEATURES.md from the catalog — grouped by subsystem, sorted, with per-feature demo/test traceability columns — as a pure, byte-stable function (no clock), so the human reference is regenerated, never hand-edited.

### `FEAT-REFERENCE-003` — Feature traceability matrix engine

traceability.build_matrix crosses the golden catalog against the inline Feature:/Features: tag convention scanned (as TEXT — never imported) from tests/, demo/, and optionally source/, producing a TraceMatrix that reports every feature lacking a test or a demo and every unknown ref (a tagged id absent from the catalog — a loud gap). is_complete() is the 1:1 every-feature-has-a-demo-and-a-test guarantee; render_matrix_md emits the byte-stable traceability wiki. Pure, sorted, clock-free.

### `FEAT-REFERENCE-004` — Test-wiki AST extractor

testwiki.collect_tests AST-parses every test_*.py (NEVER importing or executing it) into TestModule/TestCase records carrying each test's docstring summary, its boundary resolved from the directory (unit / integration / system / smoke / regression), and the union of its own and its module's Feature: tags; render_test_wiki_md emits a byte-stable wiki grouped by boundary with a per-feature "tested by" index. Loud only on a genuinely unparseable test file.

### `FEAT-REFERENCE-005` — Source index + no-orphan-capability check

srcindex.build_source_index inventories a package (reusing inventory.discover_files/discover_symbols — no AST re-impl), folds every file into its top-level module, attaches each module's public symbols, and joins each module to the catalog features whose modules name it. SourceIndex.modules_without_feature is the deferred R-02 "no orphan public capability" check (a public module with zero catalog features) and features_without_module_match catches a catalog feature naming a module the package no longer ships. Pure, deterministic, loud on a bad package root.

### `FEAT-REFERENCE-006` — Rendered source wiki

srcindex.render_source_wiki_md renders the source wiki from a SourceIndex — per-module path, public symbols, and implementing-feature links, plus a Coverage summary that counts the public modules and names any orphan (un-catalogued) module — as a pure, byte-stable function (no clock), so the SOURCE view of the golden reference is regenerated, never hand-edited.

### `FEAT-REFERENCE-007` — cdx wiki regeneration + freshness gate

wiki.regenerate, driven by `cdx wiki`, regenerates ALL of EPIC R's derived artifacts from their single sources in one command — feature-doc/FEATURES.md plus the test, source, and traceability wikis under feature-doc/wiki/ — via a shared WIKI_TARGETS (path -> render thunk) that is the single source of the output set, so write-mode and --check can never diverge. `cdx wiki` writes every changed target (a second run is a no-op — idempotent K7); `cdx wiki --check` is the read-only CI freshness gate that lists every stale file and exits nonzero without writing (loud K8). Deterministic (K10), no new dependency (K0). With `cdx trace --fail-on-gap` wired into CI, the golden reference can no longer silently drift from the code, demos, or tests.

## server

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-SERVER-001` | Optional central FastAPI service | server | K0, K4 | — | — | implemented |
| `FEAT-SERVER-002` | Repo registration over the shared schema | server | K6 | — | — | implemented |
| `FEAT-SERVER-003` | Record ingest with explicit-registration policy | server | K6, K8 | — | — | implemented |
| `FEAT-SERVER-004` | Per-repo bearer-token auth on writes | server | K8, K10 | — | — | implemented |
| `FEAT-SERVER-005` | Store persistence seam with two backends | server | K6, K10 | — | — | implemented |
| `FEAT-SERVER-006` | Postgres-first SqlStore with SQLite offline twin | server | K6, K10 | — | — | implemented |
| `FEAT-SERVER-007` | Environment store selection + Alembic migrations | server | K0, K8 | — | — | implemented |
| `FEAT-SERVER-008` | Computed status / health / telemetry views | server | K6, K10 | — | — | implemented |
| `FEAT-SERVER-009` | Server-side config sync route | server | K1, K8, K10 | — | — | implemented |
| `FEAT-SERVER-010` | Document and editable-config relationship views | server | K6, K8, K10 | — | — | implemented |
| `FEAT-SERVER-011` | Staged config-edit tickets | server | K6, K8, K10 | — | — | implemented |
| `FEAT-SERVER-012` | Generate staged edits to disk | server | K7, K8, K10 | — | — | implemented |
| `FEAT-SERVER-013` | One-click apply of an LLM-proposed fix | server | K7, K8, K10 | — | — | implemented |
| `FEAT-SERVER-014` | Standalone per-repo `cdx serve` | server | K1, K4, K10 | — | — | implemented |
| `FEAT-SERVER-015` | Single-origin dashboard SPA + landing payload | server | K0 | — | — | implemented |
| `FEAT-SERVER-016` | Public config-template reference endpoint | server | K10 | — | — | implemented |
| `FEAT-SERVER-017` | Client-side `cdx register` | registry | K0, K4, K6, K8 | — | — | implemented |
| `FEAT-SERVER-018` | Client-side remote sync trigger | registry | K0, K4, K8 | — | — | implemented |
| `FEAT-SERVER-019` | Feature-wiki endpoint | server | K0, K4, K8, K10 | — | — | implemented |

### `FEAT-SERVER-001` — Optional central FastAPI service

create_app builds the central FastAPI app over a dependency-injected Store (defaulting to InMemoryStore); importing the server subpackage requires the [server] extra (fastapi), kept lazy so `import custodex` core pulls in nothing from here, and main launches it via uvicorn on port 33333.

### `FEAT-SERVER-002` — Repo registration over the shared schema

The POST /repos route validates its body directly against the shared, versioned RegistrationPayload and persists it via Store.add_repo — ONE schema shared with the client-side register, no hand-written DTOs.

### `FEAT-SERVER-003` — Record ingest with explicit-registration policy

The POST /ingest route consumes the shared IngestEnvelope directly and stores its ReviewRecord through Store.add_record; ingest never auto-registers, so an envelope for an unregistered repo_id is a loud 404, not a silent create.

### `FEAT-SERVER-004` — Per-repo bearer-token auth on writes

Writes (/ingest, /resolutions, /coverage, /sync, /config/edits, /config/generate, apply-fix) are guarded by a per-repo bearer token whose sha256 (hash_token) is the ONLY thing stored — the plaintext is never kept or returned; a missing header on a protected repo is 401, a wrong token 403, and a token-less repo stays open while reads are always open.

### `FEAT-SERVER-005` — Store persistence seam with two backends

The Store Protocol is the one persistence boundary the routes depend on; InMemoryStore (dict-backed) and SqlStore implement the SAME Protocol so create_app swaps them transparently, both storing the shared models (RegistrationPayload / ReviewRecord / ResolutionRecord) and returning deterministic insertion-ordered lists.

### `FEAT-SERVER-006` — Postgres-first SqlStore with SQLite offline twin

SqlStore is a SQLAlchemy 2.0 store — JSONB on Postgres, JSON on SQLite via _json_type — using an "indexed columns + full JSON" hybrid where the full shared pydantic model is the source of truth on read (so an added field round-trips with no migration) alongside indexed scalar projections for filtered queries; engine_from_url builds the engine and create_all is the dev schema path.

### `FEAT-SERVER-007` — Environment store selection + Alembic migrations

store_from_env reads $CDMON_DATABASE_URL — when set it runs Alembic `upgrade head` and returns a persistent SqlStore; when unset it returns a transient InMemoryStore and logs a LOUD warning that ingested data is lost on restart; SQLite and Postgres run the same migration scripts so dev/test and prod stay in lock-step.

### `FEAT-SERVER-008` — Computed status / health / telemetry views

Read routes expose RepoStatus (verdict counts, escalations, unresolved, coverage_ratio), RepoHealth (escalation rate, overrides, MTTR), and RepoTelemetry (worst-first ShapeStat per drift_kind/audience plus detect_promotions candidates) as deterministic AGGREGATE views over store reads — not parallel copies of the shared schema.

### `FEAT-SERVER-009` — Server-side config sync route

POST /repos/{id}/sync runs run_sync read-only against the repo's local_path, then REPLACES the (repo_id, mode) config rows and appends a SyncRun via the store; a bad mode or missing tree is a loud 400 (not a 500) and the injected server clock stamps every persisted row.

### `FEAT-SERVER-010` — Document and editable-config relationship views

GET /documents returns the DocumentTree (each ConfigDocument with its nested ConfigCodeRef rows); GET /config/editable returns the EditableConfigTree joining stored documents with disk-derived undocumented_files / ignored_files / unit_files / doc_styles, defaulting to the local working-tree view and degrading gracefully for a central-only repo.

### `FEAT-SERVER-011` — Staged config-edit tickets

POST /config/edits stages one typed ConfigEdit (a discriminated union over create_doc / add_code_ref / remove_code_ref / set_context_refs / set_doc_style) as a pending StoredConfigEdit with a deterministic edit_id; GET /config/edits lists them in insertion order, optionally filtered by status, and an unknown action or stray field is a loud 422.

### `FEAT-SERVER-012` — Generate staged edits to disk

POST /config/generate makes selected pending edits live — applying them to the on-disk config via apply_edits_to_disk (offline, no-LLM), re-running run_sync to reproject the DB, marking the edits applied, and returning the applied ids, fresh SyncRun and recomputed undocumented_files; a central-only repo with no local_path is a 409 and no pending edits is an idempotent no-op.

### `FEAT-SERVER-013` — One-click apply of an LLM-proposed fix

POST /repos/{id}/records/{record_id}/apply-fix applies a FIX-verdict record's proposed fix to its doc on disk via apply_record_fix (offline, scoped), appends an accepted ResolutionRecord, re-syncs to reproject the DB, and returns the ApplyFixResponse (applied / doc_path / diff / sync_run); a non-FIX or fix-less record is a 409 and a central-only repo a 409.

### `FEAT-SERVER-014` — Standalone per-repo `cdx serve`

build_standalone_store / build_standalone_app build an InMemoryStore holding ONLY the current repo, auto-registered OPEN (no token), pre-synced read-only for both local (required) and git (best-effort) modes so the dashboard renders on first load with no central server, registration, token or network; resolve_repo_id picks the id from the bundle index or the directory name.

### `FEAT-SERVER-015` — Single-origin dashboard SPA + landing payload

When a built dashboard SPA (dashboard/dist) is located via _default_static_dir and mounted, create_app serves the console at / and its assets at /assets on the same port as the API (single-origin); otherwise GET / returns a friendly JSON landing payload, and /health is an unauthenticated liveness probe.

### `FEAT-SERVER-016` — Public config-template reference endpoint

GET /config/templates returns the four canonical config/cdmon v2 template strings (unit, index, ignore, doc_style) as JSON with no auth, deterministic — the same bytes every call — for the dashboard Config page and adopters.

### `FEAT-SERVER-017` — Client-side `cdx register`

register_repo builds a RegistrationPayload (identity from repo_identity_from_config: repo_id/name/url plus commit from config or $CI_COMMIT_SHA) and submits it through an INJECTED RegisterTransport — or a lazily-built stdlib-only HttpRegisterTransport (no requests) — to <url>/repos; dry_run returns the would-send payload with no network, and a missing url/repo_id is a loud typed SchemaError.

### `FEAT-SERVER-018` — Client-side remote sync trigger

sync_repo_remote POSTs {mode} to <url>/repos/{repo_id}/sync through an injected HttpSyncTransport (or a default built from url/auth_env), reusing the exact stdlib HTTP + bearer-from-auth_env seam as register so it is mocked in tests identically, and returns the server's SyncRun JSON verbatim; a missing url is a loud SchemaError.

### `FEAT-SERVER-019` — Feature-wiki endpoint

GET /wiki serves the committed EPIC-R wikis — the Feature Reference, Traceability Matrix, Test Wiki and Source Wiki — rendered to HTML via the engine's OWN dependency-free render_markdown (no new dep), as {"sections":[{"id","title","html"}...]} in the deterministic WIKI_SECTIONS order; it is GLOBAL and public (no auth, like /config/templates), a missing section file is omitted, and an absent feature-doc/ degrades to an empty payload rather than crashing.

## settings

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-SETTINGS-001` | Frozen versioned settings model | settings | K0, K6, K8, K10 | — | — | implemented |
| `FEAT-SETTINGS-002` | Loud settings YAML loader | settings | K8, K10 | — | — | implemented |
| `FEAT-SETTINGS-003` | Env overlay + precedence + secret presence | settings | K8, K10 | — | — | implemented |
| `FEAT-SETTINGS-004` | Hardening middleware wired from settings | server | K4, K8, K10 | — | — | implemented |
| `FEAT-SETTINGS-005` | Git SSRF allowlist + clone timeout from settings | server, gitfetch | K8 | — | — | implemented |
| `FEAT-SETTINGS-006` | Settings-driven uvicorn launch | server | K6, K10 | — | — | implemented |
| `FEAT-SETTINGS-007` | Redacted GET /settings endpoint | server | K8, K10 | — | — | implemented |
| `FEAT-SETTINGS-008` | cdx settings CLI | cli | K1, K4, K8 | — | — | implemented |

### `FEAT-SETTINGS-001` — Frozen versioned settings model

settings.Settings/ServerSettings (+ nested CorsSettings/RateLimitSettings/ GitSettings) is a frozen, extra="forbid" pydantic model whose every field defaults to today's server behavior (host 0.0.0.0, port 33333, CORS off, TrustedHost off via ["*"], no rate limit, the github.com/gitlab.com git allowlist + file:// allowed), so an absent settings.yaml is a no-op (back-compat, K6). Pure core (pydantic + pyyaml only, K0); a port out of range or a non-positive rate-limit/timeout is a loud validation error.

### `FEAT-SETTINGS-002` — Loud settings YAML loader

settings.load_settings reads config/settings.yaml and validates it, wrapping every failure (bad suffix, unreadable file, malformed yaml, non-mapping top level, unknown key, out-of-range value) in a typed ConfigError (K8). An empty file resolves to the built-in defaults. Deterministic (K10).

### `FEAT-SETTINGS-003` — Env overlay + precedence + secret presence

settings.settings_from_env overlays CDMON_SERVER_* / CDMON_TRUSTED_HOSTS / CDMON_CORS_ORIGINS / CDMON_RATE_LIMIT_RPM / CDMON_ALLOWED_GIT_HOSTS / CDMON_GIT_CLONE_TIMEOUT onto a loaded Settings (env WINS over the file, with an injectable env for tests); resolve_settings layers file → env → defaults. secret_presence reports ONLY whether $CDMON_ADMIN_TOKEN / $CDMON_DATABASE_URL / $CDMON_SECRET_KEY are set — never their values (K8). A bad env value is loud.

### `FEAT-SETTINGS-004` — Hardening middleware wired from settings

create_app installs CORS, TrustedHost and a per-process rate-limit middleware, each ONLY when the operator configures it (origins listed / hosts restricted / a request cap set), so the default app is byte-identical to the pre-SVR server (back-compat). TrustedHost rejects a spoofed Host (400); CORS answers a configured cross-origin preflight; the rate limiter returns 429 past the cap (clock-injected, deterministic; per-worker — documented in DEPLOY.md).

### `FEAT-SETTINGS-005` — Git SSRF allowlist + clone timeout from settings

The clone-on-demand / docs-PR SSRF guard (_allowed_git_hosts / _check_remote_allowed) is driven by server.git (allowed_hosts + extra_allowed_hosts, and allow_file_scheme can forbid file:// in a shared deployment), and server.git.clone_timeout_seconds threads to the clone subprocess so a hung clone is a loud SyncError instead of a stuck worker. Defaults preserve today's behavior.

### `FEAT-SETTINGS-006` — Settings-driven uvicorn launch

The central server main() binds host/port and sets the uvicorn log level from the resolved settings (config/settings.yaml + env) instead of the hardcoded 0.0.0.0:33333, and the FastAPI app version is single-sourced from the package metadata (it was duplicated as "0.1.0" in two places).

### `FEAT-SETTINGS-007` — Redacted GET /settings endpoint

GET /settings is an OPEN read returning the effective non-secret settings plus the secret PRESENCE booleans (never the secret values, K8) — the payload the console Settings page renders. Defined before the SPA catch-all mount.

### `FEAT-SETTINGS-008` — cdx settings CLI

The read-only `cdx settings [--settings PATH] [--json]` command resolves the effective settings (file → env → defaults) and prints the host/port + hardening knobs and the secret presence, never a secret value; a malformed file is a loud ConfigError → exit 1. Offline, no backend (K1/K4).

## staleness

| ID | Feature | Modules | Constraints | Demos | Tests | Status |
|----|---------|---------|-------------|-------|-------|--------|
| `FEAT-STALENESS-001` | Pure staleness grading engine | staleness | K1, K10 | — | — | implemented |
| `FEAT-STALENESS-002` | Fresh / stale / never-reviewed classification | staleness | K8, K10 | — | — | implemented |
| `FEAT-STALENESS-003` | Config-as-truth reviewed stamp + audience-aware SLA | staleness, config | K3, K6 | — | — | implemented |
| `FEAT-STALENESS-004` | cdx staleness CLI | cli | K1, K3, K4 | — | — | implemented |
| `FEAT-STALENESS-005` | Reviewed + resolved SLA mirrored at sync | server, configsync | K6, K10 | — | — | implemented |
| `FEAT-STALENESS-006` | Read-time GET /staleness view | server | K10 | — | — | implemented |

### `FEAT-STALENESS-001` — Pure staleness grading engine

staleness.grade_doc / detect_stale grade a document's `reviewed` date against an INJECTED `now` (no wall clock, K10) and its SLA — the one shared core reused by the CLI and the server route. Pure + offline (K1): no I/O, no backend, no clock read.

### `FEAT-STALENESS-002` — Fresh / stale / never-reviewed classification

A doc with no `reviewed` stamp is NEVER_REVIEWED; one reviewed longer than its SLA ago is STALE (with the age in days); otherwise FRESH (omitted from the report unless asked). Findings are deterministically sorted by doc_id (K10); a malformed `reviewed` date is a loud ConfigError (K8).

### `FEAT-STALENESS-003` — Config-as-truth reviewed stamp + audience-aware SLA

DocumentSpec.reviewed (an ISO date, config = truth, additive K6) is the last-review source; StalenessConfig (default_days + per-audience audience_days) sets the SLA so a user-guide may get a longer window than an eng-guide (audience changes the verdict, K3). reviewed_docs_from_config projects a loaded config into the engine's input.

### `FEAT-STALENESS-004` — cdx staleness CLI

The read-only `cdx staleness [--config][--now ISO][--json][--fail-on-stale]` command resolves the reviewed-docs from config and grades them against `--now` (default the wall clock) + the audience-aware SLA; the table shows only docs needing review, --json shows all, --fail-on-stale is a CI review gate. Pure + offline (K1/K4).

### `FEAT-STALENESS-005` — Reviewed + resolved SLA mirrored at sync

configsync._build_rows projects each document's `reviewed` plus the audience-resolved `sla_days` (from the bundle's staleness policy) into ConfigDocument's existing JSON (additive, K6), so the server grades against the mirror without re-deriving the policy.

### `FEAT-STALENESS-006` — Read-time GET /staleness view

GET /repos/{id}/staleness grades the synced docs' `reviewed` + `sla_days` against the app clock at READ time (deduped by doc_id, FRESH omitted unless include_fresh), so a doc goes stale on the NEXT read with no re-sync — mirroring the ownership read-time cascade. Open read, deterministic.
