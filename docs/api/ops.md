---
cdm:
  audience: eng-guide
  fingerprint: 4ddefa45e9cab82f
  fingerprint_tiers:
    composite: 4ddefa45e9cab82f
    docstring: 3b48178bd8d78505
    signature: 63743d74a94dbe2d
  region_anchors:
    symbols:
    - 01b8016fdce455c4
    - 051af376199dec21
    - 09ab528f037a044d
    - 0a12e5898c92bfc6
    - 0c9d51b72e16a207
    - 0d4275088d28bef2
    - 0d6e4079e36703eb
    - 0dad8198442ebc15
    - 12a435ec8454c6d1
    - 1a4e31eebbd1771e
    - 1bc04b5291c26a46
    - 1d3c8aff2168435b
    - 20f65c28671b4093
    - 24c458cfb46d9a45
    - 2a07ca57ed083879
    - 44575cf5b28512d7
    - 484de142f352dff3
    - 49e9627e39c92dd0
    - 4e95b8c32f60f796
    - 602fda589448378a
    - 62067d75d7bbed60
    - 655076b86b1c4c83
    - 663f896d732e2207
    - 6eb2db11cfd447e6
    - 7022c89609e06451
    - 706a95d834379a05
    - 72f4be89d6ebab14
    - 731dc691eb24a65c
    - 7482f6dd334689ff
    - 75c75efe327a8ef3
    - 763cdc62a869262b
    - 7de97367c9cdc3c6
    - 845e91831319e89c
    - 85877352f834ad30
    - 87780fa5de684e87
    - 8790ad57e78ac78e
    - 8dcd689ac1fd0270
    - 9185806e77b1178b
    - 9d60841e0a7891df
    - a03de20603d8e571
    - a0df5f85a3810828
    - a172cedcae47474b
    - a1c1adc663fbd6f0
    - b0e0fabb95a65a96
    - b6611f50a091a760
    - b9ac8d502e11101f
    - bb54068aea85faa7
    - c3a3091b9d32267d
    - ca8e9a370614b71a
    - cde0fb0dec1400c5
    - d3a3ed1c7e737699
    - d42417752e8efd40
    - d734efde26c583c9
    - da966368ea663ea5
    - df0ad6e43880f09c
    - df2a20195d34af2d
    - e31271f86c854de9
    - e62f7af7ce023782
    - eafe895eb8119e6e
    - edcc4b4214b84e54
    - f4e94e73272ff576
    - fdf09cdfc26cccf6
    - fe494651a43235a5
  region_hashes:
    symbols: 508cd47942204f91
  schema_version: 1.0.0
---
# ops

> The operator surface: the `cdx` CLI command functions that drive every
> subcommand (`cli`) and the `doctor` preflight that self-checks a config +
> environment before a run (`doctor`).

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| Check | class | class Check(BaseModel) |
| CheckStatus | class | class CheckStatus(str, Enum) |
| _CONFIG_OPTION | variable | _CONFIG_OPTION = ... |
| _DEFAULT_MANIFEST | variable | _DEFAULT_MANIFEST = Path('.cdmon/coverage.json') |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _NULL_TRANSPORT | variable | _NULL_TRANSPORT = _NullTransport() |
| _NullTransport | class | class _NullTransport |
| _NullTransport.submit | method | def submit(self, plan: object) -> dict |
| _UPDATED_LINE_RE | variable | _UPDATED_LINE_RE = re.compile('^updated:[^\\\\n]*$', re.MULTILINE) |
| __all__ | variable | __all__ = ['CheckStatus', 'Check', 'run_checks'] |
| _blank_updated | function | def _blank_updated(text: str) -> str |
| _check_agent_extra | function | def _check_agent_extra(config: MonitorConfig) -> Check |
| _check_backend | function | def _check_backend(config: MonitorConfig) -> Check |
| _check_central | function | def _check_central(config: MonitorConfig) -> Check |
| _check_documents | function | def _check_documents(config: MonitorConfig, root: Path) -> Check |
| _coverage_lines | function | def _coverage_lines(report: coverage_mod.CoverageReport) -> list[str] |
| _coverage_manifest_text | function | def _coverage_manifest_text(report: coverage_mod.CoverageReport, config: MonitorConfig) -> str |
| _coverage_payload | function | def _coverage_payload(report: coverage_mod.CoverageReport) -> dict[str, object] |
| _doc_style_for | function | def _doc_style_for(config_dir: Path) -> DocStyleMap \| None |
| _issue_transport | function | def _issue_transport(provider: str) -> GitLabIssueTransport \| GitHubIssueTransport |
| _known_modules | function | def _known_modules() -> set[str] |
| _load | function | def _load(config: Path) -> tuple[MonitorConfig, Path] |
| _now | function | def _now() -> str |
| _parse_resolution | function | def _parse_resolution(value: str) -> Resolution |
| _parse_verdict | function | def _parse_verdict(value: str) -> Verdict |
| _region_mode_lines | function | def _region_mode_lines(cfg: MonitorConfig, config_dir: Path) -> list[str] |
| _resolve_config | function | def _resolve_config(config: Path) -> tuple[MonitorConfig, Path] |
| _run_uvicorn | function | def _run_uvicorn(app_obj: Any, *, host: str, port: int) -> None |
| _settings_lines | function | def _settings_lines(resolved: Settings, presence: dict[str, bool]) -> list[str] |
| _sync_run_lines | function | def _sync_run_lines(run: dict) -> list[str] |
| _trace_lines | function | def _trace_lines(matrix: TraceMatrix) -> list[str] |
| _unit_owner_map | function | def _unit_owner_map(config_dir: Path) -> dict[str, str] |
| _write_coverage_manifest | function | def _write_coverage_manifest(report: coverage_mod.CoverageReport, config: MonitorConfig, target: Path) -> bool |
| app | variable | app = ... |
| build | function | def build(config: Path = _CONFIG_OPTION) -> None |
| check | function | def check(config: Path = _CONFIG_OPTION) -> None |
| coverage | function | def coverage(config: Path = _CONFIG_OPTION, json_out: bool = typer.Option(False, '--json', help='Emit the full CoverageReport as round-trippable JSON.'), fail_under: float \| None = typer.Option(None, '--fail-under', help='Exit 1 if public-symbol coverage is below this percent (informational — always exits 0 — when omitted).'), write: bool = typer.Option(False, '--write', help=f'Write a deterministic coverage manifest (payload + owner suggestions) to PATH (default {_DEFAULT_MANIFEST}); idempotent (K7).'), manifest_path: Path \| None = typer.Argument(None, metavar='[PATH]', help=f'Manifest destination for --write (default {_DEFAULT_MANIFEST}).')) -> None |
| doctor | function | def doctor(config: Path = _CONFIG_OPTION) -> None |
| index | function | def index(config_dir: Path = typer.Option(Path('config') / 'cdmon', '--config-dir', help='The config/cdmon directory whose index.yaml to regenerate.'), check: bool = typer.Option(False, '--check', help='Read-only: exit 1 if the on-disk index differs from a freshly regenerated one (CI gate), 0 when in sync. Writes nothing.')) -> None |
| init | function | def init(path: Path = typer.Option(Path('cdmon.yaml'), '--path', help='Where to write the config template.'), force: bool = typer.Option(False, '--force', help='Overwrite an existing config file.'), central: str \| None = typer.Option(None, '--central', metavar='URL', help='Wire `central:` for HTTP reporting to this central-server URL (sink=http). Without it, the offline template is written unchanged.'), repo_id: str \| None = typer.Option(None, '--repo-id', help='Stable repo identifier the central system keys on (required for --central; defaults to the current directory name).'), token_env: str = typer.Option(DEFAULT_CENTRAL_TOKEN_ENV, '--token-env', metavar='VAR', help=f'Env var the HTTP sink reads the central bearer token from (default {DEFAULT_CENTRAL_TOKEN_ENV}).'), repo_url: str \| None = typer.Option(None, '--repo-url', help="This repo's clone/browse URL, recorded on each reported record (only with --central)."), v2: bool = typer.Option(False, '--v2', help='Scaffold the multi-file config/cdmon/ layout (index + example unit + ignore + doc-style) instead of the single-file template.'), config_dir: Path = typer.Option(Path('config') / 'cdmon', '--config-dir', help='Where to scaffold the config/cdmon/ directory (only with --v2).'), repo: str \| None = typer.Option(None, '--repo', help='Repo id/name written into the scaffolded index.yaml (only with --v2; defaults to the current directory name).')) -> None |
| lint | function | def lint(config: Path = _CONFIG_OPTION, fix: bool = typer.Option(False, '--fix', help='Stamp missing static front matter (schema_version/audience).'), modes: bool = typer.Option(False, '--modes', help="Also print each managed region's authority mode + lock/advisory state (informational — does NOT change lint's pass/fail).")) -> None |
| main | function | def main() -> None |
| monitor | function | def monitor(config: Path = _CONFIG_OPTION, apply: bool \| None = typer.Option(None, '--apply/--no-apply', help="Auto-apply FIX verdicts (defaults to the config's apply_default)."), ref: str \| None = typer.Option(None, '--ref', '--source-sha', help='Source code ref/commit to stamp on every review record (provenance, C-05). Precedence: this flag, else $CI_COMMIT_SHA, else none. The same ref can flow to `open-docs-pr --ref` (one source of truth).')) -> None |
| new_doc | function | def new_doc(doc_id: str = typer.Argument(..., help='The document id from the config.'), config: Path = _CONFIG_OPTION, force: bool = typer.Option(False, '--force', help='Overwrite an existing doc file.')) -> None |
| open_docs_pr_cmd | function | def open_docs_pr_cmd(config: Path = _CONFIG_OPTION, dry_run: bool = typer.Option(False, '--dry-run', help='Compute + print the MR plan WITHOUT mutating the tree or opening an MR (uses a dry sync, so NOTHING is written, and never builds a transport).'), target: str = typer.Option('main', '--target', help="The MR target branch (default 'main')."), ref: str \| None = typer.Option(None, '--ref', help='Source ref to record in the MR title/description (provenance).')) -> None |
| ownership | function | def ownership(config: Path = _CONFIG_OPTION, roster: Path \| None = typer.Option(None, '--roster', help='An offline roster YAML (identities: [...]) to cross-check owners against; without it the command just lists assignments.'), as_json: bool = typer.Option(False, '--json', help='Emit {owners, findings} as round-trippable JSON.'), fail_on_orphan: bool = typer.Option(False, '--fail-on-orphan', help='Exit 1 if any document is an orphan (its accountable owner has departed). Requires --roster; UNOWNED docs do NOT trip it (that is a coverage gap, not a departure).')) -> None |
| promotions | function | def promotions(config: Path = _CONFIG_OPTION, min_count: int = typer.Option(3, '--min-count', help='How many resolved records of one shape must unanimously share a decision before it is a promotion candidate.'), as_json: bool = typer.Option(False, '--json', help='Emit the candidates as machine-readable JSON.')) -> None |
| register | function | def register(config: Path = _CONFIG_OPTION, dry_run: bool = typer.Option(False, '--dry-run', help='Print the registration payload as JSON WITHOUT calling the server (no url/token required).')) -> None |
| report | function | def report(config: Path = _CONFIG_OPTION, verdict: str \| None = typer.Option(None, '--verdict', help='List the individual records with this verdict (e.g. ESCALATE) instead of the aggregate summary.'), as_json: bool = typer.Option(False, '--json', help='Emit machine-readable JSON (records when --verdict is set).')) -> None |
| resolve | function | def resolve(record_id: str = typer.Argument(..., help='The ReviewRecord id to record an outcome for.'), resolution: str = typer.Option(..., '--resolution', help='The human outcome: accepted \| overridden \| rejected \| invalidated.'), by: str \| None = typer.Option(None, '--by', help='Who resolved it (stored as resolved_by).'), text: str \| None = typer.Option(None, '--text', help="The human's final body when --resolution overridden (resolved_text)."), note: str \| None = typer.Option(None, '--note', help='A free-text note attached to the outcome.'), config: Path = _CONFIG_OPTION, log: Path \| None = typer.Option(None, '--log', help='Resolutions log path (default .cdmon/resolutions.jsonl alongside the review log).')) -> None |
| rpt | function | def rpt(config_dir: Path = typer.Option(Path('config') / 'cdmon', '--config-dir', help='The config/cdmon directory to build the coverage report from.'), write: bool = typer.Option(False, '--write', help='Write config/cdmon/coverage.rpt (idempotent, K7). Default prints to stdout and writes nothing (read-only, K1).'), ref: str \| None = typer.Option(None, '--ref', help='Branch/commit the report reflects (provenance, stamped in the frontmatter). Left null when omitted; a later sync slice fills it.')) -> None |
| run_checks | function | def run_checks(config: MonitorConfig, config_dir: Path) -> list[Check] |
| schema | function | def schema(out: Path \| None = typer.Option(None, '--out', help='Write the schema to this file instead of stdout.')) -> None |
| serve | function | def serve(host: str = typer.Option('127.0.0.1', '--host', help='Host/interface to bind the standalone server to.'), port: int = typer.Option(0, '--port', help='Port to bind (0 = let the OS pick a free port).'), repo_id: str \| None = typer.Option(None, '--repo-id', help="Repo id for the standalone view. Defaults to the bundle's index `repo` field (else the current directory name)."), no_open: bool = typer.Option(False, '--no-open', help='Do not open a browser tab (accepted for parity; never auto-opens).')) -> None |
| settings | function | def settings(settings_path: Path = typer.Option(Path('config/settings.yaml'), '--settings', help='Path to the operator settings YAML.'), as_json: bool = typer.Option(False, '--json', help='Emit the resolved settings + secret presence as JSON.')) -> None |
| should_sync_cmd | function | def should_sync_cmd(files: list[str] = typer.Argument(None, metavar='[FILES...]', help='Changed file paths to test. If omitted, read newline-separated paths from stdin (e.g. `git diff --name-only \| cdx should-sync`).'), config: Path = _CONFIG_OPTION) -> None |
| staleness | function | def staleness(config: Path = _CONFIG_OPTION, now: str \| None = typer.Option(None, '--now', help='ISO timestamp to grade freshness against (default: the current time).'), as_json: bool = typer.Option(False, '--json', help='Emit {findings} as JSON (includes fresh docs).'), fail_on_stale: bool = typer.Option(False, '--fail-on-stale', help='Exit 1 if any document is stale or never reviewed (a review gate).')) -> None |
| surface | function | def surface(config: Path = _CONFIG_OPTION, as_json: bool = typer.Option(False, '--json', help="Dump each document's surface as a JSON list.")) -> None |
| surface_gaps | function | def surface_gaps(config: Path = _CONFIG_OPTION, dry_run: bool = typer.Option(False, '--dry-run', help='Compute + print the issue plan WITHOUT opening an issue (never builds a transport, so no provider env is required).'), provider: str = typer.Option('gitlab', '--provider', help='Issue tracker to open the coverage-gap issue on (gitlab \| github).')) -> None |
| sync | function | def sync(mode: str = typer.Option('local', '--mode', help="Which sync to run: 'local' (the working tree / feature branch) or 'git' (the default branch baseline)."), remote: str \| None = typer.Option(None, '--remote', metavar='URL', help='Central-server URL to POST the sync to. Without it the sync runs locally and prints the summary (no central access required).'), repo_id: str \| None = typer.Option(None, '--repo-id', help="Stable repo id. REQUIRED with --remote; for a local sync it defaults to the bundle's index `repo` field (else the directory name)."), token_env: str = typer.Option(DEFAULT_CENTRAL_TOKEN_ENV, '--token-env', metavar='VAR', help=f'Env var the remote bearer token is read from (default {DEFAULT_CENTRAL_TOKEN_ENV}).'), default_branch: str = typer.Option('main', '--default-branch', help='The default branch the local sync compares against (commits_ahead).'), as_json: bool = typer.Option(False, '--json', help='Emit the SyncRun as JSON instead of the human summary.')) -> None |
| sync_pr_cmd | function | def sync_pr_cmd(config: Path = _CONFIG_OPTION, out: Path \| None = typer.Option(None, '--out', help='Write the unified-diff patch to this file instead of stdout.'), dry_run: bool = typer.Option(False, '--dry-run', help='Compute the patch WITHOUT mutating the working tree (K1).')) -> None |
| trace | function | def trace(catalog: Path = typer.Option(Path('feature-doc') / 'catalog', '--catalog', help='The feature-doc/catalog directory of golden feature *.yaml files.'), tests_root: Path = typer.Option(Path('tests'), '--tests-root', help='Directory scanned for TEST evidence (inline `Feature:` tags).'), demo_root: Path = typer.Option(Path('demo'), '--demo-root', help='Directory scanned for DEMO evidence (inline `Feature:` tags).'), as_json: bool = typer.Option(False, '--json', help='Emit the traceability matrix as JSON instead of the human summary.'), fail_on_gap: bool = typer.Option(False, '--fail-on-gap', help='Exit nonzero if ANY feature lacks a test or demo, or any unknown ref exists (the CI gate, K8). Without it the command is informational (always exits 0).')) -> None |
| wiki | function | def wiki(check: bool = typer.Option(False, '--check', help='Verify the wikis are fresh; exit nonzero if any is stale (no write).')) -> None |
<!-- CDM:END symbols -->
