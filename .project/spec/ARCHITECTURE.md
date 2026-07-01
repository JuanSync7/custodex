# custodex — architecture & module contracts

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
    # E-01 repo identity (ADDITIVE, all default None/2 — old configs still load):
    repo_id: str | None = None      # REQUIRED when sink=="http" (loud K8 in make_sink)
    repo_name: str | None = None
    repo_url: str | None = None
    repo_commit: str | None = None  # commit; else $CI_COMMIT_SHA at make_sink time
    outbox: str | None = None       # offline queue path; default ".cdmon/outbox.jsonl"
    max_retries: int = 2            # attempts before queueing a failed send

class WaiverEntry(BaseModel):       # frozen, extra="forbid" (A-04)
    path: str                       # glob over repo-relative POSIX paths
    symbol: str | None = None       # exact symbol name; None => whole-file waiver
    reason: str                     # REQUIRED (K8: a waiver must justify itself)

class CoverageConfig(BaseModel):    # frozen, extra="forbid" (A-04)
    include: tuple[str,...] = inventory.DEFAULT_INCLUDE   # scan scope (A-05 wires to discover_files)
    exclude: tuple[str,...] = inventory.DEFAULT_EXCLUDE
    waive: tuple[WaiverEntry,...] = ()  # intentional doc gaps, each justified

class RegionMode(str, Enum):        # per-region authority (B-01)
    GENERATED = "generated"         # DEFAULT: mechanical projection of code; heal overwrites
    LLM = "llm"                     # backend-authored prose; heal applies the LLM fix
    HUMAN = "human"                 # a human owns it; heal NEVER writes it (advisory only)
    LLM_SEEDED = "llm-seeded"       # llm until a human edits it, then locks to human

class DocEdgeType(str, Enum):       # EPIC B: the role of a doc→doc edge
    DEPENDS="depends"; REFINES="refines"; IMPLEMENTS="implements"; VERIFIES="verifies"
class DocEdge(BaseModel):           # frozen, extra="forbid" — one upstream dependency
    doc: str                        # upstream document id (must resolve, K8)
    type: DocEdgeType = DocEdgeType.DEPENDS
    note: str | None = None
class DocDepsConfig(BaseModel):     # the `docdeps:` block (additive, K6) — NOTHING hardcoded
    enabled: bool = True            # detect suspect links at all
    gate: bool = True               # SUSPECT_LINK counts toward `cdx check` exit 1
    default_type: DocEdgeType = DocEdgeType.DEPENDS
    infer_from_links: bool = False  # auto-INCLUDE edges inferred from md cross-links (suggest is always available)

class DocumentSpec(BaseModel):
    id: str
    path: str                       # repo-relative doc path
    audience: Audience
    code_refs: tuple[CodeRef,...]
    region_keys: tuple[str,...] = ()  # managed regions this doc carries
    region_modes: dict[str, RegionMode] = {}  # region id -> mode; absent => generated (B-01)
    depends_on: tuple[DocEdge,...] = ()  # EPIC B: doc→doc upstream deps (additive K6)
    # model_validator: region_modes keys in region_keys; depends_on has no self-edge / no dup upstream (K8)
    def mode_for(self, region_id: str) -> RegionMode  # declared mode or GENERATED

class MonitorConfig(BaseModel):
    version: str = "1.0.0"
    root: str = "."                 # repo root, relative to the config file
    documents: tuple[DocumentSpec,...]
    backend: BackendConfig = BackendConfig()
    agent: AgentConfig = AgentConfig()   # runtime for backend.kind == "agent"
    central: CentralConfig = CentralConfig()
    apply_default: bool = False     # monitor auto-applies FIX by default?
    coverage: CoverageConfig = CoverageConfig()  # A-04: scan scope + waivers (defaulted, additive)
    docdeps: DocDepsConfig = DocDepsConfig()  # EPIC B: doc↔doc policy (additive)
    # model_validator: every depends_on.doc must name a known document id (else ConfigError, K8)

def load_config(path: Path) -> MonitorConfig     # yaml|json by suffix; ConfigError on bad input
CONFIG_TEMPLATE: str                             # documented starter config
def write_template(path: Path) -> None
```

### CONFIG-V2 dir layout — `config/cdmon/` (N-01; additive projection onto `MonitorConfig`)
The multi-file `config/cdmon/` layout is a *projection*: an `index.yaml`
(globals + an ordered list of unit files) plus N `<unit>.yaml` files (each a `---`
front-matter block + a body) merge into exactly ONE `MonitorConfig`, so every
downstream module is untouched. Models are frozen, `extra="forbid"`, and use
pydantic aliases with `populate_by_name=True` so YAML keys are hyphenated while
attrs stay snake_case (K0). All failures raise typed `ConfigError` (K8); the
merge is pure and deterministic (K10: index order, then in-file order).

**Z-01b/Z-02 — cdx dogfoods this layout on ITSELF (it is now the canonical
self-config).** The repo carries `config/cdmon/` (`index.yaml` + nested units
`core`/`agent`/`server` = `custodex`/`custodex/agent`/
`custodex/server`, plus `ignore.yaml`/`doc-style.yaml`/`coverage.rpt`)
covering its 12 documents, `api-index` region template, and the three
`__init__.py` waivers. Z-02 REMOVED the now-redundant root `cdmon.yaml`: the dir
layout is cdmon's only self-config; `cdx check`/`coverage` auto-detect it from
the repo root. Enforced by `tests/test_dogfood.py`. Self-coverage is 100% of
scanned engine public symbols: `report.py`→`coverage-system`, `configsync.py`→
`central-client`, and `server/standalone.py`→`server` close the last gaps. The
single-file `load_config` path remains the documented BACK-COMPAT capability
(`cdx init`, `examples/`), kept and tested against a SEPARATE fixture (NOT
cdmon's own config).
```python
CDMON_CONFIG_VERSION = "2.0.0"   # the only accepted cdmon-config-version

class UnitFrontmatter(BaseModel):           # unit file's --- block; version must == "2.0.0"
    cdmon_config_version: str  # alias "cdmon-config-version"
    unit: str; title: str; owner: str; created: str; updated: str
class UnitFile(BaseModel):                   # one coverage UNIT (scope + documents)
    frontmatter: UnitFrontmatter
    dir_covered: tuple[str,...]              # alias "dir-covered"; >=1, non-empty
    source_files_format: tuple[str,...]      # alias "source-files-format"; >=1, each starts "."
    documents: tuple[DocumentSpec,...]       # >=1; reuses the existing DocumentSpec
class IndexFrontmatter(BaseModel):           # index.yaml --- block; version must == "2.0.0"
    cdmon_config_version: str; repo: str
    generated_by: str  # alias "generated-by"
    updated: str
class IndexUnitRef(BaseModel):
    file: str
class IndexFile(BaseModel):                  # globals + ordered unit index
    frontmatter: IndexFrontmatter
    root: str = "../.."                      # repo root relative to config/cdmon/ (N-06)
    version: str = "2.0.0"; apply_default: bool = False
    backend: BackendConfig = ...; agent: AgentConfig = ...; central: CentralConfig = ...
    region_templates: dict[str, RegionTemplate] = {}; coverage: CoverageConfig = ...
    units: tuple[IndexUnitRef,...]
    ignore: str = "ignore.yaml"; doc_style: str = "doc-style.yaml"  # alias "doc-style"
class ConfigBundle(BaseModel):               # the load result + the per-unit seams (N-03/N-04/N-05)
    config: MonitorConfig; index: IndexFile; units: tuple[UnitFile,...]; config_dir: str
    doc_style: object | None = None          # N-05: DocStyleMap | None (None when doc-style.yaml absent, K6)
    def unit_for_document(self, doc_id: str) -> UnitFile | None
    def unit_for_path(self, repo_relative_path: str) -> UnitFile | None  # Z-01a deepest-wins (method form)
def unit_for_path(bundle: ConfigBundle, path: str) -> UnitFile | None  # Z-01a: deepest dir-covered ancestor (by components)

def _split_frontmatter(text: str, where: Path) -> tuple[dict, str]   # mirror manifest fence; loud
def load_unit_file(path: Path) -> UnitFile     # validates unit == filename stem (K8)
def load_index_file(path: Path) -> IndexFile
def load_bundle(config_dir: Path) -> ConfigBundle   # reads index, then units in order; merges
def load_config_dir(config_dir: Path) -> MonitorConfig   # == load_bundle(config_dir).config

# N-02: index<->disk reverse validation + regeneration (`cdx index`).
RESERVED_UNIT_STEMS = frozenset({"index", "ignore", "doc-style"})  # not coverage units
def regenerate_index(config_dir: Path) -> str   # rescan units (sorted), rebuild units:, refresh updated (clock seam)
def write_index(config_dir: Path, text: str) -> None   # loud writer (ConfigError on OSError, K8)
```
Merge: `MonitorConfig.documents` = concat of unit `documents` (index `units`
order, then in-file order); `version/root/backend/agent/central/apply_default/
region_templates/coverage` come from `index.yaml`. Loud `ConfigError` on: version
!= "2.0.0"; `unit` != filename stem; a `source-files-format` entry without a
leading dot; empty `dir-covered`; duplicate document `id` across units; two units
sharing an IDENTICAL (normalized — trailing slash / `./` / `//` equivalent)
`dir-covered` path (**Z-01a: NESTING across units is now ALLOWED — deepest-wins
attribution; only identical paths conflict**); an index-listed unit file missing
on disk; a missing `index.yaml`. The CLI auto-detects via
`_resolve_config(config) -> (MonitorConfig, Path)`: a directory arg OR (when the
`--config` file is absent) a `config/cdmon/index.yaml` under cwd uses
`load_config_dir`; otherwise the single-file `load_config` path is unchanged.

**N-02 — index↔disk reverse validation + `cdx index`.** `load_bundle` now also
enforces the REVERSE invariant: every on-disk `config/cdmon/*.yaml` (minus the
reserved stems `index`/`ignore`/`doc-style`, `RESERVED_UNIT_STEMS`) MUST appear in
`index.yaml`'s `units:`; an on-disk-not-in-index unit is a loud `ConfigError`
naming the offenders in sorted order (K8/K10). `regenerate_index(config_dir)`
rescans the on-disk units (alphabetical, reserved excluded), rebuilds the body
`units:` block, and refreshes the frontmatter `updated` via the injected `_now`
clock seam (mirrors `monitor._default_now`) — every other global and frontmatter
field is preserved byte-for-byte by textual surgery (no parse→re-serialize), so it
is idempotent (K7) and deterministic (K10). `write_index(config_dir, text)` is the
loud writer. The `cdx index [--config-dir config/cdmon] [--check]` CLI rewrites
the index by default (no-op when already synced) and `--check` is read-only (K1):
exit 1 + unified diff on drift, 0 when synced — a CI guard.

**N-03 — `ignore.yaml` + `.gitignore` merge + `source-files-format` coverage
scoping.** `load_bundle` now DERIVES `MonitorConfig.coverage` from the dir layout
so the EXISTING coverage engine (`inventory.discover_files` →
`discover_symbols` → `coverage.resolve_coverage`) is untouched — the derived
globs simply flow through it (CONFIG-V2 §1.1/§1.3). New `config.py` surface:
```python
class IgnoreFrontmatter(BaseModel):   # ignore.yaml --- block; version must == "2.0.0"
    cdmon_config_version: str  # alias "cdmon-config-version"
    source: str; updated: str
class IgnoreFile(BaseModel):          # manual ignore globs + .gitignore merge (§1.3)
    frontmatter: IgnoreFrontmatter
    gitignore: bool = False           # if true, merge the repo .gitignore
    patterns: tuple[str,...] = ()     # manual ignore globs (inventory ** semantics)
def load_ignore_file(path: Path) -> IgnoreFile          # frontmatter+body; loud K8
def gitignore_to_globs(text: str) -> tuple[str,...]     # hand-rolled (K0), sorted+deduped (K10)
def effective_coverage(bundle: ConfigBundle, repo_root: Path) -> CoverageConfig
```
`gitignore_to_globs` is a HAND-ROLLED translation (NO new dep, K0) into
inventory's exact `**` semantics (confirmed against `inventory._translate`):
blanks/`#`-comments skipped; negations (`!…`) emit nothing; a trailing `/`
(directory) → its contents (`__pycache__/`→`**/__pycache__/**`,
`/dist/`→`dist/**`, `docs/build/`→`docs/build/**`); a leading `/` (root-anchored)
→ the entry + its contents (`/dist`→`dist`,`dist/**`); an embedded-slash path →
as-is + a `/**` contents companion unless it already has a wildcard
(`docs/**/*.html` kept verbatim); a bare token → `**/<tok>` (+ `**/<tok>/**`
contents companion unless it carries a wildcard, so `*.log`→`**/*.log` only).
Output sorted + deduped (K10). `effective_coverage` builds:
`include` = for each unit, each `dir-covered` `d` × each `source-files-format`
`ext`, the glob `d/**/*ext` (which matches a file BOTH directly in `d` and
nested — `**/` is zero-or-more segments); `exclude` = `ignore.patterns` ∪
(`gitignore_to_globs(repo_root/.gitignore)` when `ignore.gitignore` and the file
exists) ∪ the default excludes (`**/.*/**`, `**/__pycache__/**`, `**/.venv/**`)
∪ **the Z-01a deepest-wins format-scoping excludes**: for each unit dir `d` and
each `ext` in the include universe that `d`'s OWN unit does NOT scope, the glob
`d/**/*ext` — UNLESS a strictly-deeper unit dir under `d` DOES scope `ext` (the
coverage engine is exclude-wins-over-include, so this expresses "a file under a
child unit is scoped by the CHILD's `source-files-format`, not the parent's");
`waive` = `index.coverage.waive` (unchanged). All sorted + deduped (K10).
`load_bundle` resolves `repo_root = resolve_repo_root(config_dir, index.root) =
normpath(config_dir / index.root)` — the ONE repo-root formula shared by
`Monitor`, `drift.detect`, `effective_coverage`, the doc-style `templates_root`,
and `cdx rpt` (N-06: `root` is the repo root relative to the dir the config
lives in — `config/cdmon/`, default `../..`; the repo root for a single file,
default `.`). It reads the ignore pointer (`index.ignore`, default `ignore.yaml`) from
`config_dir`, and rebuilds the merged config with the derived coverage; the
single-file `load_config` is UNCHANGED. RESULT: a file under a unit's
`dir-covered` whose extension is not in that unit's `source-files-format` (a
`.log`/`.rpt`) never enters the include set, so it is never "uncovered"; an
ignored file is excluded the same way — both leave the coverage denominator.

**N-05 — writing templates + `doc-style.yaml` + agent authoring wiring.** Four
independent writing-template categories live as real markdown guidance under
`templates/writing/{document-type,tone,writing-style,vocabulary}/` (many files
each). A `config/cdmon/doc-style.yaml` maps each document id to ONE template per
category (with `defaults`). The agent, when AUTHORING a no-renderer `llm`
region's prose, composes the four selected files into its prompt. The models +
loader live in a NEW module `custodex/docstyle.py` (config.py kept lean;
no cycle — docstyle imports config's leaf helpers, config does a LAZY local
import in `load_bundle`):
```python
STYLE_CATEGORIES = (("document_type","document-type"),("tone","tone"),
                    ("writing_style","writing-style"),("vocabulary","vocabulary"))  # fixed order (K10)
class DocStyleFrontmatter(BaseModel):   # version == "2.0.0"; kind == "doc-style-map" (loud K8)
class DocStyleSelection(BaseModel):     # 4 fields, hyphenated aliases (document-type/writing-style)
class DocStyleMapping(BaseModel):       # doc id + flattened selection; .selection property
class DocStyleMap(BaseModel):           # frontmatter + defaults + mappings tuple
    def style_for(self, doc_id) -> DocStyleSelection   # mapping if present, else defaults
def load_doc_style(path, *, templates_root) -> DocStyleMap   # validates EVERY named template file EXISTS (loud K8, lists all missing)
def resolve_style_files(selection, templates_root) -> dict[str,Path]   # category -> path (pure projection)
def read_style_guidance(selection, templates_root) -> str   # the 4 bodies under "## Writing guidance — <category>" headers, fixed order
```
`load_bundle` loads `doc-style.yaml` when the index `doc-style` pointer (default
`doc-style.yaml`) names a present file, with `templates_root =
repo_root/"templates/writing"` (same `repo_root = resolve_repo_root(config_dir,
index.root)` the coverage path uses), exposing `bundle.doc_style: DocStyleMap |
None` — absent ⇒ None (additive, K6). Agent seam: `FixRequest.style_guidance:
str | None = None` (additive); `agent.graph.render_context` appends it LAST under
a "Writing guidance (apply when AUTHORING …)" header WHEN present, so with no map
the composed prompt is BYTE-IDENTICAL to today (K6) and the offline `MockBackend`
(which authors prose in code) is untouched (K4/K10). `Monitor(..., doc_style=…)`
threads it: `_style_guidance_for(drift, region_mode)` returns the composed
guidance ONLY for a no-renderer `llm` REGION drift (a REGION whose `region_id`
is mode `llm` and has NO `region_templates` renderer), else None. The `cdx
monitor` CLI lifts `doc_style` from the bundle (dir layout only; single-file
configs have no doc-style seam).

## `templates_v2.py`  (canonical `config/cdmon/` templates + scaffolder — W-02, K7/K10)
ONE authoritative, tested source for the multi-file layout. Four well-commented
canonical template strings — `UNIT_TEMPLATE`, `INDEX_TEMPLATE`, `IGNORE_TEMPLATE`,
`DOC_STYLE_TEMPLATE` — each matching CONFIG-V2 §1.1–§1.4 with the `root: "../.."`
convention, and each ROUND-TRIPPING through its N-01..N-05 loader (a test writes
each to a stem-matching file and `load_unit_file`/`load_index_file`/
`load_ignore_file`/`load_doc_style` accepts it). The only template placeholders are
`{repo}`/`{now}` (block-style YAML elsewhere ⇒ no literal braces to escape); they
are QUOTED so a raw, unfilled template is still valid loadable YAML.
```python
EXAMPLE_UNIT_STEM = "example"                    # the scaffolded unit's stem (== its `unit:`)
V2_TEMPLATES: dict[str, str]                     # {"unit","index","ignore","doc_style"} (served by /config/templates)
def scaffold_config_dir(config_dir, *, repo, now) -> None  # write index.yaml + example.yaml + ignore.yaml + doc-style.yaml
```
`scaffold_config_dir` substitutes `repo`/`now` and writes the four files (the
referenced writing templates already live in `templates/writing/`, not rewritten);
the result PASSES `load_bundle` for a repo shipping those templates (asserted).
OS errors wrap into a typed `ConfigError` (K8). `cdx init --v2` is the loud
caller (no-clobber without `--force`). The DOC_STYLE_TEMPLATE names writing
templates that exist (api-reference / precise / reference-dense / engine-domain).

## `report.py`  (the `coverage.rpt` builder/renderer — N-04, pure-ish, K1/K7/K8/K10)
```python
CDMON_REPORT_VERSION = "1.0.0"
class RptSummary(BaseModel):            # frozen, extra="forbid"
    scanned_files: int; documented_files: int; waived_files: int
    ignored_files: int; uncovered_files: int
    percent: float | None              # round(100*documented/(scanned-waived), 2); None=> "n/a"
class RptUnit(BaseModel):              # one unit's slice (frozen, extra="forbid")
    unit: str; file: str; scanned: int; documented: int
    percent: float | None; uncovered: tuple[str, ...]
class RptUndocumented(BaseModel):      # gap file -> where to declare it (frozen)
    path: str; suggested_unit: str | None; reason: str
class CoverageRpt(BaseModel):          # the parsed .rpt shape (frozen, extra="forbid")
    cdmon_report_version: str; kind: str; repo: str; ref: str | None
    summary: RptSummary; units: tuple[RptUnit, ...]
    undocumented: tuple[RptUndocumented, ...]

def build_coverage_rpt(bundle: ConfigBundle, repo_root: Path, *, ref: str|None) -> CoverageRpt
def render_rpt(rpt: CoverageRpt) -> str          # --- frontmatter --- + YAML body; byte-stable
def parse_rpt(text: str) -> CoverageRpt          # inverse of render_rpt; loud K8
def write_rpt(config_dir: Path, text: str) -> None   # writes config_dir/coverage.rpt; loud K8
def report_repo_root(config_dir: Path, bundle: ConfigBundle) -> Path  # re-export of _resolve_repo_root
```
**N-04 — `coverage.rpt` (CONFIG-V2 §3).** `build_coverage_rpt` does NOT fork the
coverage engine: it derives the scan scope via `effective_coverage`, runs the
SAME path the `coverage` CLI runs (`inventory.discover_files` →
`discover_symbols` → `coverage.resolve_coverage`), and projects the resulting
`CoverageReport` into the `.rpt` shape. `summary.scanned_files` = the universe
size (`len(report.files)` — format-matched, under a unit `dir-covered`, minus the
ignore set); `documented/waived/uncovered` are the basket sizes; `percent` =
`round(100*documented/(scanned-waived), 2)` (None=>`n/a` when the denominator is
0) — matching `CoverageReport.percent_files` semantics (waived off both sides).
`ignored_files` (informational) = files the ignore/exclude set removed from the
unit-dir × format scope: a re-scan of the same `include` globs with ONLY the
DEFAULT excludes (no ignore patterns / `.gitignore`) minus the universe — so a
format-matched `.py` excused by `ignore.yaml` counts, while a `.log` (not in any
unit's `source-files-format`) is simply out of scope, never "ignored". Per-unit
slices attribute each universe file to the unit whose `dir-covered` contains it
(**Z-01a deepest-wins via `unit_for_path` — a file in a child unit's dir counts
under the CHILD only, never double-counted by the parent**); each unit's `percent`
applies the SAME
`scanned - waived` denominator the overall summary does (M-02 — waived files
leave BOTH sides per-unit too), so a unit of 3 files with 1 waived + 2 documented
reports `100.0`, not `66.67`, and the per-unit and overall numbers can never
diverge. `undocumented[]` pairs each gap file with its
`suggested_unit` (the DEEPEST unit whose `dir-covered` contains it AND whose
`source-files-format` includes its extension; else `null` + a reason naming a
format mismatch vs. no-dir-match — Z-01a deepest-wins). Percentages are rounded at BUILD time (not just
render) so the model carries exactly the 2-dp figure the file shows and the
round-trip holds: `parse_rpt(render_rpt(r)) == r`.
`render_rpt` emits a `---` frontmatter block (`cdmon-report-version`/`kind`/`repo`/
`ref`/`generated-by: cdx rpt`) then the YAML body in a FIXED key order, every
list sorted, percentages at 2 dp (`n/a` for None). NO wall-clock is written
(K7) — provenance is `ref` (a branch/commit; a later sync slice fills it), so a
re-run with no code/config change is byte-identical. Free-text reasons go through
a PyYAML flow-scalar helper so colons/quotes/hashes are escaped (lossless
round-trip). `parse_rpt` is the strict inverse (loud `ConfigError` on a missing/
unterminated fence, wrong report-version, or a non-mapping/structurally-invalid
body). `write_rpt` is a plain loud writer to `config_dir/coverage.rpt`. The
`cdx rpt [--config-dir config/cdmon] [--write] [--ref REF]` CLI prints the
rendered report by default (read-only, K1) and only writes the `.rpt` under
`--write` (idempotent, K7). DB/sync filling `ref` from git is epic Y;
doc-style/templates are N-05 (see the `config.py` N-05 section above).

## `extract.py`  (audience-aware, AST-only, no imports of target code — K0)
```python
class Symbol(BaseModel):
    name: str; kind: Literal["function","class","method","variable"]
    signature: str; lineno: int; end_lineno: int
    is_public: bool                 # not _-prefixed
    docstring: str | None
    body_hash: str | None = None    # P1: function/method body-AST digest (sha256[:16]);
                                    # None for class/variable. Feeds the opt-in body tier.
    @property
    def anchor_id(self) -> str      # P4: sha256[:16] of the qualified name (lineno-free) —
                                    # stable symbol IDENTITY a region binds to across moves.

def anchor_id(qualified_name: str) -> str   # P4: the same stable identity digest (K10)

class SurfaceFingerprint(BaseModel):     # P2: frozen; the tiered fingerprint
    signature: str                       # sha256[:16] of {audience, sig-only symbols, records}
    docstring: str | None                # sha256[:16] of docstrings; None unless eng-guide
    body: str | None                     # sha256[:16] of body_hashes; None unless body tier on
    composite: str                       # == surface_hash(): the identity, byte-stable
    sig_by_anchor: dict[str,str] | None = None  # DIG-01: {anchor_id -> sha256[:16] of the
        # per-symbol signature payload}. NOT hashed into composite (byte-stable, K6/K10);
        # None only on a hand-built fp predating DIG-01 (fingerprint() always populates it).
    def drifted_against(self, other: SurfaceFingerprint) -> tuple[str, ...]
        # ("signature"/"docstring"/"body",...) tiers whose digest differs; sorted (K10)

class DocumentSurface(BaseModel):
    doc_id: str; audience: Audience
    symbols: tuple[Symbol,...]
    def surface_hash(self, *, include_body: bool = False) -> str   # == fingerprint(...).composite
        # sha256[:16] of audience-normalized payload (K10). include_body (P1) is the
        # OPT-IN body tier: additive key, byte-invisible when False; NEVER applied to
        # user-guide (a body change is a non-event for the externally-visible API, K3).
    def fingerprint(self, *, include_body: bool = False) -> SurfaceFingerprint   # P2
        # composite is byte-identical to surface_hash(...); per-tier digests are
        # diagnostic (which tier moved). signature tier folds in `records`.

# Pluggable extraction seam (P1): the engine holds no target-specific knowledge (K0);
# a new language is a new registration, never an engine edit.
@runtime_checkable
class Extractor(Protocol):
    language: str
    def extract(self, path: Path) -> list[Symbol]: ...

class PythonAstExtractor:            # the default; AST-only, import-free (K0)
    language = "python"

class ShellExtractor:                # P5: the first REAL non-Python extractor —
    language = "shell"               # regex over sh/bash, stdlib `re` only (K0-clean,
    def extract(self, path: Path) -> list[Symbol]: ...   # NO heavy dep, offline gate intact)
# P5: registered by DEFAULT at import → `register_extractor(ShellExtractor(), suffixes=(".sh", ".bash"))`
#   so a `.sh`/`.bash` ref with `lang: auto` (or `lang: shell`) resolves it with zero engine edit.
#   Extracts `name() {…}` and `function name {…}` defs → Symbol(kind="function",
#   signature=f"{name}()", is_public=leaf-name rule, docstring=leading `#` comment block).
#   body_hash stays None (the opt-in body tier is Python-AST-only; deferred for shell).
def register_extractor(extractor: Extractor, *, suffixes: tuple[str, ...] = ()) -> None
    # P3: also maps each suffix → extractor.language for `lang: auto` symbol refs
def get_extractor(language: str) -> Extractor      # loud on unknown language (K8)

def extract_file(path: Path) -> list[Symbol]       # thin wrapper → get_extractor("python")
def build_document_surface(doc: DocumentSpec, root: Path) -> DocumentSurface
# P3: symbol extraction routes through the registry by CodeRef.lang — `_symbols_for_ref`
# resolves get_extractor(lang), lang = ref.lang or (auto → suffix map, default "python").
# A new language is a register_extractor() call, NEVER an engine edit (proves K0).
```
Audience filter: `user-guide` keeps only `is_public` symbols and EXCLUDES
docstring/comment text and `variable` locals from the hash; `eng-guide` keeps all
symbols and includes docstrings. Sub-file selection: `symbols`/`names` filter by
name; `lines` keep symbols overlapping a range; empty selectors = whole file.

Body tier (P1, opt-in via `MonitorConfig.fingerprint_body_tier`, default OFF):
`body_hash` is `sha256[:16]` of the function/method body AST
(`ast.dump(..., include_attributes=False)`, leading docstring stmt stripped) — so it
is insensitive to comments/formatting/line moves and orthogonal to the docstring tier
(K10). Drift, heal, layout, and monitor MUST pass the same `include_body` value
(one-shared-truth), else heal stamps a fingerprint detect won't match. OFF →
`surface_hash` bytes are identical to the pre-P1 contract for all audiences, so stored
`cdm.fingerprint` values stay valid.

Tiered fingerprint (P2): `fingerprint()` returns a `SurfaceFingerprint` whose
`composite` IS today's `surface_hash()` bytes (the unchanged identity) plus three
diagnostic per-tier digests — `signature` (structural surface: sig-only symbols +
`records`), `docstring` (eng-guide only), `body` (body tier only). The composite
stays in `cdm.fingerprint` (identity, no re-baseline); the per-tier digests are
stamped ADDITIVELY in `cdm.fingerprint_tiers`, so `detect` can report WHICH tier
moved (`Drift.drifted_tiers`). Heal/layout stamp both from ONE `fingerprint()` call
(one-shared-truth, same `include_body`). Old docs without `cdm.fingerprint_tiers`
fall back to the composite-only "fingerprint moved" message (back-compat).

## `inventory.py`  (repo code-file discovery — pure, stdlib only — K0/K1/K10)
```python
class CodeFile(BaseModel):              # frozen, extra="forbid"
    path: str                           # repo-relative, POSIX separators
    language: str                       # extension→language ("python", ... "unknown")

class Inventory(BaseModel):             # frozen, extra="forbid"
    root: str                           # POSIX-normalized absolute root
    files: tuple[CodeFile, ...]         # sorted by path, deduped

DEFAULT_INCLUDE: tuple[str, ...] = ("**/*.py",)
DEFAULT_EXCLUDE: tuple[str, ...] = ("**/.*/**", "**/__pycache__/**", "**/.venv/**")

def discover_files(
    root: Path,
    *,
    include: tuple[str, ...] = DEFAULT_INCLUDE,
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE,
) -> Inventory: ...

# A-02 — symbol-level inventory (reuses extract.extract_file; no AST re-impl)
class FileSymbols(BaseModel):           # frozen, extra="forbid"
    path: str                           # repo-relative POSIX (== CodeFile.path)
    language: str
    symbols: tuple[Symbol, ...]         # extract.Symbol; () for non-python / no symbols

class SymbolInventory(BaseModel):       # frozen, extra="forbid"
    root: str
    files: tuple[FileSymbols, ...]      # same order as Inventory.files

def discover_symbols(inventory: Inventory, root: Path) -> SymbolInventory: ...
```
A file is kept iff it matches >=1 `include` glob AND 0 `exclude` globs
(`fnmatch` on POSIX repo-relative paths, stdlib only — K0). Output sorted by
`path`, deduped, no FS mutation, no wall-clock (K1/K10). `language` from a small
extension table; a matched file with an unknown extension is kept as
`language="unknown"` (losslessness, never dropped). Raises
`InventoryError(CodeDocMonitorError)` if `root` is missing or not a directory
(K8).

`discover_symbols` attaches each file's symbol surface (A-02): it calls
`extract.extract_file(root / path)` for every `language == "python"` file and
stores the resulting `Symbol`s in `FileSymbols.symbols`; non-python files are
kept with `symbols=()` (losslessness — tracked, never dropped). `files` preserve
`Inventory.files` order and `extract_file`'s symbol order (K10). An unparseable /
unreadable python file lets `extract.ExtractionError` propagate (loud — K8); a
resilient `--skip-unparseable` mode is deferred (see `.project/problems/A-02.md`).

## `coverage.py`  (ownership resolver — pure, reuses `extract._select` — K0/K1/K10)
```python
class OwnedFile(BaseModel):             # frozen, extra="forbid"
    path: str                           # repo-relative POSIX (== FileSymbols.path)
    language: str
    owners: tuple[str, ...]             # doc ids referencing this path; () == gap

class OwnedSymbol(BaseModel):           # frozen, extra="forbid"
    path: str                           # owning file's path
    name: str                           # qualified for methods (Class.method)
    kind: str                           # function/class/method/variable
    is_public: bool                     # extract.Symbol.is_public (leaf-name rule)
    owners: tuple[str, ...]             # doc ids whose code_refs select this symbol
    waived_reason: str | None = None    # A-04: set iff a config.coverage.waive entry matched

class CoverageReport(BaseModel):        # frozen, extra="forbid"
    files: tuple[OwnedFile, ...]        # ALL inventory files, sorted by path (lossless)
    symbols: tuple[OwnedSymbol, ...]    # ALL symbols, sorted by (path, name, kind) (lossless)

    @property
    def documented_files(self) -> tuple[OwnedFile, ...]      # owners non-empty, not waived
    @property
    def undocumented_files(self) -> tuple[OwnedFile, ...]    # owners empty, not waived (gap)
    @property
    def waived_files(self) -> tuple[OwnedFile, ...]          # A-04: waived_reason set
    @property
    def documented_symbols(self) -> tuple[OwnedSymbol, ...]  # public, owned, not waived
    @property
    def undocumented_symbols(self) -> tuple[OwnedSymbol, ...]# public, unowned, not waived (gap)
    @property
    def waived_symbols(self) -> tuple[OwnedSymbol, ...]      # A-04: public, waived_reason set
    @property
    def percent_files(self) -> float        # 100 * documented / (total - waived) files (100.0 if 0)
    @property
    def percent_public_symbols(self) -> float  # 100 * doc_public / (public - waived) (100.0 if 0)

def resolve_coverage(config: MonitorConfig, inv: SymbolInventory) -> CoverageReport: ...

class OwnerSuggestion(BaseModel):       # frozen, extra="forbid" (A-07)
    path: str                           # the gap's file path
    name: str | None                    # symbol name; None == whole-file suggestion
    suggested_doc_id: str               # an existing doc id, or a proposed new one
    is_new_doc: bool                    # True => suggested_doc_id is a proposal
    reason: str                         # "sibling symbols already in <doc>" / "no doc references <F>"

def suggest_owners(report: CoverageReport, config: MonitorConfig) -> tuple[OwnerSuggestion, ...]: ...
```
**A-07 — gap→owner suggester (pure, deterministic — Decision 1: a heuristic, NOT
the `Backend` Protocol; K0/K10).** For each **public, unowned, non-waived** symbol
gap (`report.undocumented_symbols` — private gaps are never suggested), decide a
suggested owner from ownership facts alone (no I/O, no LLM, no new dep):
- **Sibling-owned file** — if any document already owns *another* symbol in the
  same file, suggest **that** doc id (the lowest doc id if several own siblings),
  `is_new_doc=False`, reason `"sibling symbols already in <doc>"`.
- **Fully-unowned file** — else (no document owns any symbol in the file *and* the
  file is not waived), propose a **new** doc id derived from the file path by the
  scheme `path → drop ".py"/".pyi" suffix → replace "/" with "-"` (e.g.
  `pkg/sub/mod.py → pkg-sub-mod`). Chosen because the full path keeps ids unique
  across same-named modules in different packages and yields a filesystem/id-safe
  token. All gaps in that file group under the same proposed id, `is_new_doc=True`,
  reason `"no doc references <F>"`.
Output sorted by `(path, name)` (a `None` name — never emitted for a gap symbol but
defined for the whole-file shape — sorts first). Deterministic (K10).
**A-04 — waivers (additive).** `resolve_coverage` folds `config.coverage.waive`:
an **unowned** `OwnedFile`/`OwnedSymbol` whose path matches a waiver glob (reused
`inventory._translate`) — and, for a symbol waiver, whose name equals the entry's
`symbol` (None => whole-file waiver, waiving the file and every symbol under it)
— is stamped with that entry's `reason` on a new `waived_reason` field and moves
into the `waived_files`/`waived_symbols` basket, OUT of `undocumented_*`. Waived
items leave BOTH the numerator and denominator of `percent_files` /
`percent_public_symbols` (universe = total − waived), so a fully-waived-or-
documented repo reports 100%. Only **unowned, public** (for symbols) gaps are
waivable: a waiver matching an already-documented item is **inert** (no basket
change, documented wins); a waiver matching nothing is **silently inert** (no
error) — A-04 chose silent-inert over loud because the scan scope
(`coverage.include/exclude`, applied only in the A-05 CLI) legitimately removes a
waived path from the inventory, so a "stale" waiver is normal, not malformed; the
only loud failure is a missing `reason` (K8) caught at config-load. With the
default empty `waive`, every basket/percentage is identical to A-03 (additive).
Pure cross of the symbol inventory with `config.documents[*].code_refs` (K1, no
FS access — the inventory already carries every `Symbol`). A **file is owned**
iff some doc's `code_ref.path == file.path`; a **symbol is owned** iff some
`code_ref` on that file *selects* it, tested by reusing
`extract._select(file.symbols, ref.symbols, ref.lines, ref.names)` and checking
membership by `(name, lineno)` — so whole-file (empty selectors), `symbols`
(incl. class→methods pull-in), `lines`-overlap, and `names` semantics come for
free (no selection re-implementation — K0). Ownership **ignores audience** (a
deliberate divergence from `build_document_surface`, which filters): a doc that
points at a symbol covers it regardless of audience — audience governs the
hash/surface, not whether code is referenced. `arg_signature` is NOT applied
here (it narrows a surface, not ownership; a ref still "covers" the file's
symbols it names). The **gap-% universe is PUBLIC symbols only**: private
symbols are tracked losslessly in `symbols` but excluded from
`percent_public_symbols` and `undocumented_symbols` (they are not doc targets).
All tuples sorted (files by `path`; symbols by `(path, name, kind)`); `owners`
sorted + deduped; `percent_*` return `100.0` on an empty universe (no
zero-division) (K10). Not wired into cli/monitor (A-04/A-05).

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
# P2 tiered fingerprint — additive `cdm.fingerprint_tiers` (composite stays in
# `cdm.fingerprint`, the unchanged identity). Stamped beside the composite.
def stored_fingerprint_tiers(doc: Doc) -> SurfaceFingerprint | None   # None on old docs
def set_fingerprint_tiers(meta: dict, fp: SurfaceFingerprint) -> dict  # additive under cdm
# P4 region anchors — additive `cdm.region_anchors` (id -> sorted anchor_ids the
# region documents), so drift can tell a symbol add/remove/rename from an internal change.
def stored_region_anchors(doc: Doc, region_id: str) -> tuple[str, ...] | None  # None pre-P4
def set_region_anchors(meta: dict, region_id: str, anchors: tuple[str, ...]) -> dict
# DIG-01 per-symbol signature digests — additive per-doc `cdm.symbol_sigs`
# {anchor_id -> sig digest}. None pre-DIG-01 (→ severity degrades to aggregate, K6);
# `{}` when stamped-but-symbol-less. Stamped by heal AND layout.scaffold_doc (parity).
def stored_symbol_sigs(doc: Doc) -> dict[str, str] | None
def set_symbol_sigs(meta: dict, sigs: dict[str, str]) -> dict   # sorted keys, additive under cdm
```
DIG-01 `drift.classify_change_severity(drifted_tiers, anchors_added, anchors_removed,
sigs_changed=())` gains a 4th param: a non-empty `sigs_changed` (SURVIVING symbols whose
signature digest moved, from `cdm.symbol_sigs`) → `BREAKING` ABOVE the addition rule, so a
simultaneous add + in-place signature change is no longer masked as ADDITIVE. `Drift.sigs_changed`
is the additive field; no public-schema change (`ReviewRecord.change_severity` just gets more
accurate). A pre-DIG-01 doc degrades to the aggregate behaviour.
Per-region content hash (B-03) — the mode-agnostic **lock** living additively in
`cdm.region_hashes` (id -> hash), which `set_fingerprint` already copies forward,
so a hash survives a heal:
```python
def region_body_hash(body: str) -> str               # sha256[:16], CRLF-normalized (mirrors layout.md_source_hash); K10
def stored_region_hash(doc: Doc, region_id: str) -> str | None
def set_region_hash(meta: dict, region_id: str, value: str) -> dict   # additive under cdm.region_hashes
def region_is_locked(doc: Doc, region_id: str, current_body: str) -> bool
```
EPIC B per-edge upstream stamps — additive `cdm.upstream_hashes` (upstream doc id
-> hash of that upstream's body at last review). `set_fingerprint` already copies
the whole `cdm` map forward, so an edge stamp survives a code↔doc heal (zero blast
radius), exactly like `region_hashes`:
```python
def stored_upstream_hashes(doc: Doc) -> dict[str, str]                 # {} when absent
def set_upstream_hash(meta: dict, upstream_id: str, value: str) -> dict   # additive under cdm.upstream_hashes
def drop_upstream_hash(meta: dict, upstream_id: str) -> dict           # remove a stamp (edge deleted)
```
`region_is_locked` is the SINGLE shared lock predicate (CDM-07 "one shared
truth") consumed by drift + heal: a region is locked iff it has a stored region
hash AND `region_body_hash(current_body) != stored_region_hash(...)` (a human
edited it since the engine last stamped it). drift and heal MUST agree by calling
this one helper, never re-deriving the rule.

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
    SUSPECT_LINK="SUSPECT_LINK"   # EPIC B: an upstream doc this one depends_on changed
                                  # (healable=False — resolved by `cdx resolve --edge`, not auto-edit)
class Drift(BaseModel):
    kind: DriftKind; doc_id: str; doc_path: str; detail: str
    region_id: str | None = None; healable: bool = True
    audience: Audience; diff: str = ""
    drifted_tiers: tuple[str, ...] = ()   # P2: which tier(s) moved on a HASH drift;
                                          # () when unknown (old doc, no stored tiers)
    anchors_added: tuple[str, ...] = ()   # P4: anchor_ids present now but not in the
    anchors_removed: tuple[str, ...] = () # stored set / vice-versa. Both () = same symbol
                                          # identities (a move/internal change, re-bind);
                                          # nonempty = a symbol was added/removed/renamed.
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

EPIC B — `detect()` also appends `SUSPECT_LINK` drifts (healable=False) by calling
`docdeps.detect_suspect_links(config, root)` when `config.docdeps.enabled`. They
are pure data like any other Drift; `cdx check`'s EXIT code honours
`config.docdeps.gate` (a report whose only drifts are SUSPECT_LINK exits 0 when
`gate=False`). detect stays K1 — no stamp is ever written here.

## `docdeps.py`  (EPIC B — doc↔doc suspect links — pure, mirrors `ownership.py`, K0/K1/K10)
The edge DECLARATION is config (`DocumentSpec.depends_on`, K2 truth); the per-edge
baseline STAMP is the downstream doc's `cdm.upstream_hashes` front-matter
(machine-managed, like `cdm.fingerprint`). This module is pure: the one writer
(`write_edge_stamp`) is impure file I/O isolated from detection and called ONLY by
the mutation commands (`link`/`resolve`/`monitor --apply`), never by `check`.
```python
class DocEdgeType(str, Enum):              # config: DocEdge.type
    DEPENDS="depends"; REFINES="refines"; IMPLEMENTS="implements"; VERIFIES="verifies"
class SuspectStatus(str, Enum):
    OK="ok"; UNSTAMPED="unstamped"; SUSPECT="suspect"; MISSING_UPSTREAM="missing_upstream"
    SUSPECT_TRANSITIVE="suspect_transitive"   # PROP-01 advisory only — emitted by propagate_suspect, never gates
class SuspectLink(BaseModel):              # frozen, extra=forbid — one downstream→upstream edge verdict
    doc_id: str; doc_path: str; upstream_id: str; type: DocEdgeType
    status: SuspectStatus; detail: str; audience: Audience
class InferredEdge(BaseModel):             # frozen — a link-inference suggestion (author→approve)
    doc_id: str; upstream_id: str; via: str   # the relative md link that implied it

def upstream_fingerprint(doc: manifest.Doc) -> str   # sha256[:16] of normalized BODY (not front-matter); K10
def detect_suspect_links(config: MonitorConfig, root: Path, *, include_ok=False) -> tuple[SuspectLink, ...]  # pure, sorted (K1/K10)
def infer_edges_from_links(config: MonitorConfig, root: Path) -> tuple[InferredEdge, ...]  # pure, sorted
def render_deps_text(links, *, suspect_only=False, transitive=()) -> str   # the `cdx deps` human view (K10)
def write_edge_stamp(doc_path: Path, upstream_id: str, value: str) -> bool   # IMPURE writer (only mutation cmds)

# B-10 / PROP-01 — the reverse-graph half (pure, cycle-safe, K10; ungated by docdeps.enabled)
def _reverse_reachable(config, origins: set[str], *, transitive=True) -> set[str]  # shared BFS, excludes origins
def impacted_by(config, upstream_id, *, transitive=True) -> tuple[str, ...]   # blast radius; delegates to _reverse_reachable
def propagate_suspect(config, direct: Sequence[SuspectLink]) -> tuple[SuspectLink, ...]
    # PROP-01 ADVISORY: the transitive closure of the DIRECT suspect links as SUSPECT_TRANSITIVE
    # edges — origins = SUSPECT/MISSING_UPSTREAM docs, downstream's own audience (K3), sorted.
    # NEVER mints a drift (a transitive edge has no changed upstream body to stamp — K1/K7).
```
PROP-01 keeps drift the pure Doorstop **direct** wavefront (no new `DriftKind`, no schema
bump). The eager transitive blast radius is read-only: `cdx deps --transitive`, an opt-in
`cdx monitor` line gated by the additive `DocDepsConfig.transitive` knob (default OFF), and
`GET /doc-graph/reverse?transitive=true` (pure graph reachability over `config_doc_edges`,
never a suspect verdict — K2).
`detect_suspect_links`: for each downstream doc with `depends_on`, recompute each
upstream's `upstream_fingerprint` and compare to `manifest.stored_upstream_hashes`
on the downstream — equal⇒OK, differ⇒SUSPECT, absent⇒UNSTAMPED, upstream file
gone⇒MISSING_UPSTREAM. Sorted by `(doc_id, upstream_id)` (K10).

## `schema.py`  (public, versioned — K6)
```python
class Verdict(str, Enum): FIX="FIX"; INVALIDATE="INVALIDATE"; ESCALATE="ESCALATE"
class ProposedFix(BaseModel):
    region_id: str | None; new_region_body: str | None
    new_doc_text: str | None; rationale: str
class ReviewRecord(BaseModel):
    schema_version: str = "1.1.0"    # P2 minor bump: drifted_tiers added (additive, K6)
    record_id: str; doc_id: str; doc_path: str; audience: Audience
    drift_kind: str; drift_detail: str
    cause: str                       # LLM's explanation
    verdict: Verdict
    fix: ProposedFix | None
    surface_hash: str; backend_kind: str
    detected_at: str; resolved_at: str    # ISO strings, injected (K10)
    config_snapshot: dict
    # ... source_sha, ticket (additive, appended last) ...
    drifted_tiers: tuple[str, ...] = ()   # P2: which surface tier(s) moved; () pre-P2
def review_record_schema() -> dict       # ReviewRecord.model_json_schema()

# D-01/D-02 — resolution outcome (separate append-only event, K5/K6/K10)
class Resolution(str, Enum):             # accepted|overridden|rejected|invalidated
    ACCEPTED="accepted"; OVERRIDDEN="overridden"
    REJECTED="rejected"; INVALIDATED="invalidated"
class ResolutionRecord(BaseModel):       # frozen, extra="forbid"
    schema_version: str = "1.0.0"
    record_id: str                       # FK -> ReviewRecord.record_id
    resolution: Resolution
    resolved_text: str | None = None     # human's final text when OVERRIDDEN
    resolved_by: str | None = None
    resolved_at: str                     # ISO, injected (K10)
    note: str | None = None              # additive tail; old lines w/o it still parse (K6)
def resolution_record_schema() -> dict   # ResolutionRecord.model_json_schema()
```

## `reviewlog.py`  (append-only JSONL — K5)
```python
def append(path: Path, record: ReviewRecord) -> None
def read_all(path: Path) -> list[ReviewRecord]
def summarize(records: list[ReviewRecord]) -> dict   # counts by verdict/audience/doc

# D-01/D-02 — resolutions live alongside reviews (cohesive: the join needs both).
# Mirror append/read_all EXACTLY (append mode, parent dirs, blank-line skip,
# corrupt line -> SchemaError w/ line no., K8).
DEFAULT_RESOLUTIONS_PATH = Path(".cdmon") / "resolutions.jsonl"
def append_resolution(path: Path, record: ResolutionRecord) -> None
def read_resolutions(path: Path) -> list[ResolutionRecord]
# join: last-write-wins (a record resolved twice -> the LAST appended wins; the
# log stays append-only, so a correction is a new event, not a mutation).
def resolved_index(resolutions: list[ResolutionRecord]) -> dict[str, ResolutionRecord]
def summarize_with_resolutions(
    records: list[ReviewRecord], resolutions: list[ResolutionRecord]
) -> dict   # {total, resolved, unresolved, by_resolution}
```

# D-03/D-04 — similarity retrieval + agent few-shot exemplars (pure, additive, K0/K10)

## `similar.py`  (new, pure, deterministic — NO new dep, NO embeddings — K0/K10)
```python
class Exemplar(BaseModel):               # frozen, extra="forbid"
    record: ReviewRecord                 # the PAST resolved drift
    resolution: ResolutionRecord         # its human outcome (resolved_text for OVERRIDDEN)
    score: float                         # the feature-match score (deterministic)

def rank_similar(
    target: ReviewRecord,                # rank PAST RESOLVED records vs this one
    records: list[ReviewRecord],
    resolutions: list[ResolutionRecord],
    *, top_n: int = 3,
) -> list[Exemplar]
```
- **Population = RESOLVED only.** A candidate is eligible iff its `record_id` is in
  `reviewlog.resolved_index(resolutions)` (last-write-wins). The `target` itself is
  ALWAYS excluded (by `record_id`), even if it is resolved.
- **Score = deterministic weighted sum of FEATURE MATCHES** (no embeddings — the
  feature-match score is offline + deterministic; vector retrieval is a documented
  future option, out of scope). Features are exactly the `ReviewRecord` fields that
  carry the drift's *shape* (ReviewRecord has no `region_id`, so it is NOT a feature):
  | feature (equal target↔candidate) | weight |
  |----------------------------------|--------|
  | `surface_hash` exact match (same code surface) | 5.0 |
  | `doc_id` | 3.0 |
  | `drift_kind` | 2.0 |
  | `audience` | 1.0 |

  Weights are descending-distinct so each higher feature dominates any combination of
  lower ones (surface_hash 5 > doc 3 + kind 2 = 5? — no: ties are broken below, and the
  ordering is by the documented total order, not by weight-domination). Max score = 11.0.
- **Total order (K10), applied as a sort key:** higher `score`, then more-recent
  `resolution.resolved_at` (ISO strings sort lexicographically = chronologically),
  then `record_id` ascending. Fully deterministic — two equal-score candidates have a
  stable order via `record_id`. `top_n` caps the result; `top_n <= 0` or empty
  population → `[]`. Pure, no I/O, no wall-clock.
- Candidates with score `0.0` (no feature in common) are STILL eligible but rank last;
  retrieval is "the most similar resolved", not "only matches" — callers cap with `top_n`.

# D-05/D-06 — promotion detector + deterministic rule application (pure + opt-in, K4/K10)

## `promotion.py`  (new, pure, deterministic — NO new dep — K0/K10)
```python
class PromotionCandidate(BaseModel):     # frozen, extra="forbid"
    doc_id: str
    drift_kind: str
    audience: Audience
    resolution: Resolution               # the UNANIMOUS human decision for this shape
    count: int                           # how many RESOLVED records support it (>= min_count)

def detect_promotions(
    records: list[ReviewRecord],
    resolutions: list[ResolutionRecord],
    *, min_count: int = 3,
) -> list[PromotionCandidate]
```
- **Shape key = `(doc_id, drift_kind, audience)` — GENERALIZABLE, NOT `surface_hash`.**
  `surface_hash` is the EXACT code state (similar.py's dominant feature) and never
  recurs across edits, so it cannot ground a recurring rule. The shape is the
  audience-scoped doc+kind that DOES recur. Population = RESOLVED records only (a
  record whose `record_id` is in `reviewlog.resolved_index`, last-write-wins). A shape
  QUALIFIES iff ≥ `min_count` of its resolved records share ONE resolution (unanimous
  among that shape's resolved records — a single dissenting resolution disqualifies it).
- **Promotable = DECISION-shaped resolutions only: `invalidated` and `rejected`.** These
  carry NO content (a pure human decision), so automating them is safe + content-free.
  `overridden` carries human prose (`resolved_text`) that rarely generalizes — it is
  EXCLUDED from auto-promotion (a future content-rule slice could mine it). `accepted`
  of a mechanical fix is already LLM-free, so it is not a promotion target either; the
  detector promotes only the two decision resolutions. Deterministic sorted output (K10):
  `(doc_id, drift_kind, audience, resolution)`.

## `promotion.py` → rule mapping + `monitor.py` rule application (opt-in, additive, K4)
```python
class PromotionRule(BaseModel):          # frozen, extra="forbid"
    doc_id: str; drift_kind: str; audience: Audience; verdict: Verdict
def rule_for(drift: Drift, rules: tuple[PromotionRule, ...]) -> PromotionRule | None
def rule_from_candidate(c: PromotionCandidate) -> PromotionRule   # trivial mapping helper
```
- `rule_for` matches a `Drift` against rules on `(doc_id, drift_kind, audience)` and
  returns the FIRST matching rule (or `None`). `rule_from_candidate` maps a candidate's
  resolution to a verdict (`invalidated`/`rejected` → `INVALIDATE`).
- `Monitor(..., rules: tuple[PromotionRule, ...] = ())` — **default empty ⇒ today's
  behavior byte-identical.** When a drift matches a rule, `run` SYNTHESIZES a
  `BackendResult` (the rule's verdict, `fix=None`, a `cause` prefixed with the
  rule-sourced marker `RULE_CAUSE_PREFIX`) WITHOUT calling `backend.propose`, then records
  it like any other (K5 — every drift, incl. rule-resolved, is still recorded for human
  audit). The rule-sourced marker also lands in `config_snapshot["resolved_by"] = "rule"`
  so a consumer can tell rule-resolved records from backend ones. Non-matching drifts go
  to the backend exactly as today. The rule path is offline + deterministic and makes
  zero backend calls — the cost curve bends DOWN as the system learns (K4).

## `sinks.py`  (central system — offline default)
```python
class Sink(Protocol): def emit(self, record: ReviewRecord) -> None
class NullSink: ...        # default
class FileSink: ...        # appends JSON to a file (offline-testable central)

# E-01 — the SHARED, versioned client<->server wire format (K6). E-03's /ingest
# consumes IngestEnvelope directly — ONE schema, no DTOs. Defined in sinks.py
# (not schema.py) so schema.py stays the pure review-record source and sinks.py
# owns the transport envelope; re-exported from schema.py would create a cycle.
class RepoIdentity(BaseModel):     # frozen, extra="forbid"
    repo_id: str
    repo_name: str | None = None
    repo_url: str | None = None
    commit: str | None = None
class IngestEnvelope(BaseModel):   # frozen, extra="forbid"
    schema_version: str = "1.0.0"
    repo: RepoIdentity
    record: ReviewRecord

class HttpSink:           # POST IngestEnvelope to url; injected client; NEVER raises (K4)
    def __init__(self, url, auth_env=None, *, repo: RepoIdentity,
                 outbox: Path | None = None, max_retries: int = 2,
                 client: _PostClient | None = None) -> None
    def emit(self, record: ReviewRecord) -> None
    # 1. wrap record in IngestEnvelope(repo=self._repo, record=record)
    # 2. DRAIN outbox oldest-first: post each queued envelope; STOP on first
    #    failure and re-queue that one + all remaining (preserves order).
    # 3. SEND the new envelope with up to max_retries attempts.
    # 4. on final failure (drain blocked OR new send exhausted): append the new
    #    envelope to the outbox JSONL and RETURN — reporting NEVER breaks a heal
    #    run (K4). A client.post raising == "network down".
    # Outbox = JSONL of IngestEnvelope lines; drained by read-all then rewrite
    #    the undrained remainder (simple, deterministic — single-process sink).
def make_sink(cfg: CentralConfig) -> Sink
    # http: build RepoIdentity(repo_id/name/url + commit from cfg.repo_commit
    #   else $CI_COMMIT_SHA); loud SchemaError (K8) if sink=="http" & repo_id missing.
    #   outbox defaults to ".cdmon/outbox.jsonl". NullSink/FileSink unchanged.
```

## `registry.py`  (repo registration client — offline default, E-02)
```python
# A repo announces itself to the central server (an explicit `cdx register`)
# BEFORE/while reporting. CLIENT-SIDE only (the server /repos endpoint is E-03,
# which consumes RegistrationPayload directly — ONE shared schema, no DTOs, K6).
# Mirrors sinks.py / pr.py: an INJECTED transport so tests never touch the
# network (K4); the default stdlib-urllib transport's real urlopen is the only
# `# pragma: no cover` leaf (K0). Reuses RepoIdentity from sinks.py (NOT a new
# identity model) — the same wire identity as IngestEnvelope.

class RegistrationPayload(BaseModel):   # frozen, extra="forbid" (K6, K8)
    schema_version: str = "1.0.0"
    repo: RepoIdentity                  # reuse the E-01 model (sinks.py)
    default_branch: str | None = None   # optional display fields (additive, K6)
    description: str | None = None

class RegisterTransport(Protocol):
    def register(self, payload: RegistrationPayload) -> dict: ...

class HttpRegisterTransport:            # POST RegistrationPayload to <url>/repos
    def __init__(self, url, auth_env=None, *, http: _RegisterHttp | None = None)
    def register(self, payload) -> dict
    # bearer from auth_env (same env seam as HttpSink), read at register time;
    # url is the CENTRAL base url; POSTs to f"{url.rstrip('/')}/repos".
    # _UrllibRegisterHttp.request = the only real urlopen (# pragma: no cover, K0).

def repo_identity_from_config(cfg: CentralConfig) -> RepoIdentity
    # SHARED helper (de-dups make_sink's identity build): RepoIdentity from
    # repo_id/name/url + commit (cfg.repo_commit else $CI_COMMIT_SHA). Loud
    # SchemaError (K8) if repo_id is missing. make_sink reuses it.

def register_repo(identity: RepoIdentity, *, url: str, auth_env: str | None = None,
                  transport: RegisterTransport | None = None,
                  dry_run: bool = False, default_branch: str | None = None,
                  description: str | None = None) -> dict | None
    # Build RegistrationPayload(repo=identity, ...). dry_run -> return the payload
    # dict WITHOUT calling the transport. Else submit via transport (lazily built
    # HttpRegisterTransport when None) and return the server response. Loud
    # SchemaError (K8) if url is missing/empty.
```

## `server/`  (central FastAPI service — optional `[server]` extra, E-03 — K0/K4/K6/K10)
```python
# The CENTRAL side of E-01/E-02: a FastAPI app that ingests repo registrations
# (RegistrationPayload) + review records (IngestEnvelope) over the SHARED, versioned
# schemas — NO hand-written request DTOs (K6). The routes import registry/sinks
# models DIRECTLY and let FastAPI/pydantic validate them (a malformed body -> 422).
# Behind the `[server]` extra (fastapi, uvicorn[standard], httpx for TestClient);
# importing `custodex` core pulls in NOTHING from here — `server/__init__.py`
# does NOT import fastapi at import time (lazy, mirrors the `agent` extra, K0). The
# store is a Protocol seam: E-03 ships an InMemoryStore; E-04 swaps in a SQLAlchemy/
# Postgres store behind the SAME Store without touching app.py/the routes.

# server/store.py
class RegisteredRepo(BaseModel):        # frozen, extra="forbid" (K6/K8); the stored repo
    repo: RepoIdentity                  # reuse the E-01 identity (sinks.py)
    default_branch: str | None = None   # carried from the RegistrationPayload
    description: str | None = None
# Y-02 (ADDITIVE, K6 — NO migration; the FULL payload JSON is the stored source):
#   RepoIdentity (sinks.py) GAINS optional local_path + default_branch — where the
#   server reads this repo from on a local FS and its baseline branch. The sync
#   route reads repo.repo.local_path; a repo without one -> 400 on POST /sync.
#   RegistrationPayload (registry.py) GAINS optional local_path mirroring the same
#   (a register may carry it on the identity or top-level). Both default None so
#   every pre-Y-02 payload/identity still validates and round-trips through /repos.

# Y-01 config-sync persistence models (frozen, extra="forbid", K6/K8; the FULL JSON
# is the stored source of truth — added fields round-trip with NO migration):
class ConfigDocument(BaseModel):        # one synced config document (the relationship data)
    repo_id; doc_id; path; audience; unit: str | None; region_keys: tuple[str, ...]
    sync_kind: str ("git"|"local"); ref: str | None; synced_at: str
class ConfigCodeRef(BaseModel):         # one code_ref under a document (its child)
    repo_id; doc_id; path; symbols: tuple[str, ...]; unit: str | None; sync_kind
class SyncRun(BaseModel):               # one sync invocation summary (history row)
    repo_id; sync_kind; ref/branch/head_commit/main_commit: str | None
    commits_ahead: int; fully_synced: bool; document_count: int; code_ref_count: int
    drift: dict (opaque coverage/drift summary, stored verbatim); started_at; finished_at

class Store(Protocol):                  # the E-04 seam (in-memory now, DB later)
    def add_repo(self, payload: RegistrationPayload) -> None: ...
    def get_repo(self, repo_id: str) -> RegisteredRepo | None: ...
    def list_repos(self) -> list[RegisteredRepo]: ...        # deterministic order (K10)
    def add_record(self, repo_id: str, record: ReviewRecord) -> None: ...
    def records_for(self, repo_id: str) -> list[ReviewRecord]: ...  # insertion order (K10)
    # Y-01 config-sync methods (both stores; parity-tested in tests/test_store_config.py):
    def replace_config(repo_id, sync_kind, documents, code_refs) -> None
        # ATOMIC delete-then-insert for THIS (repo_id, sync_kind) scope ONLY — the other
        # sync_kind's rows are never touched. The idempotent upsert a sync calls; a 2nd
        # call with fewer rows leaves NO stragglers. New rows append in order (K10).
    def config_documents_for(repo_id, sync_kind=None) -> list[ConfigDocument]   # insertion order
    def code_refs_for(repo_id, doc_id=None, sync_kind=None) -> list[ConfigCodeRef]
    def add_sync_run(run: SyncRun) -> None
    def latest_sync_run(repo_id, sync_kind=None) -> SyncRun | None  # most-recent by id (K10)
    def sync_runs_for(repo_id, sync_kind=None) -> list[SyncRun]     # insertion order

class InMemoryStore:                    # dict-backed; deterministic ordering (K10)
    # list_repos / records_for return INSERTION order (dicts preserve it); a repeat
    # add_repo for the same repo_id UPDATES in place (no reorder). Records key on
    # the envelope's repo.repo_id, appended in arrival order.

# server/app.py
def create_app(store: Store | None = None, *, static_dir=None, clock=_default_now) -> FastAPI
    # DI: tests pass a fresh InMemoryStore; prod (E-04) passes the DB store. None ->
    # a default InMemoryStore. The store is resolved through a FastAPI dependency
    # (`app.dependency_overrides`-friendly) so routes stay store-agnostic.
    # `clock` is the Y-02 server time seam (ISO-8601 UTC): the config-sync route
    # stamps its persisted rows from it, so tests inject a fixed clock (K10).
    # Records ingested over /ingest carry their OWN client timestamps (not this seam).
    # Routes (validate against the SHARED schemas DIRECTLY, K6):
    #   POST /repos    body: RegistrationPayload -> 201 {"repo_id": ...}
    #   POST /ingest   body: IngestEnvelope -> 202 {"record_id": ...}
    #                  UNKNOWN repo_id -> 404 (registration is explicit, E-02; no
    #                  auto-register — the chosen, documented policy)
    #   GET  /repos                 -> list[RegisteredRepo]
    #   GET  /repos/{repo_id}/records -> list[ReviewRecord]  (404 if repo unknown)
    #   GET  /config/templates      -> {"unit","index","ignore","doc_style"} (W-02; PUBLIC,
    #                  no auth; the templates_v2.V2_TEMPLATES strings; deterministic, K10)
    # A malformed body -> 422 (FastAPI/pydantic against the shared model). The only
    # `# pragma: no cover` is the `uvicorn.run`/`if __name__` launch leaf.

# --- E-05: JSON query API (read endpoints over the indexed columns) ------------
#   GET /repos/{repo_id}/records?verdict=&drift_kind=&audience=&doc_id=&limit=&offset=
#        -> list[ReviewRecord]   (404 if repo unknown). Filters map 1:1 to the E-04
#        INDEXED scalar columns (SQL WHERE on the DB store; equivalent in-memory
#        filtering for InMemoryStore). Records are re-validated from the FULL JSON
#        column (K6 source-of-truth on read). limit/offset paginate; order is the
#        deterministic insertion order (surrogate id, K10). limit<=0 / offset<0 -> 422.
#   GET /repos/{repo_id}/resolutions?record_id=  -> list[ResolutionRecord]
#        (all resolutions for the repo's records, or just one record's; 404 unknown repo)
#   GET /repos/{repo_id}/coverage   -> list[dict] coverage snapshots (latest last; 404)
#   GET /repos/{repo_id}/status     -> RepoStatus   (a COMPUTED VIEW, see below; 404)
#   GET /repos/{repo_id}/health     -> RepoHealth   (a COMPUTED VIEW, see below; 404)
#
# --- F-04: resolve write path (the FIRST dashboard write) ----------------------
#   POST /repos/{repo_id}/resolutions  body = ResolutionRecord (the SHARED schema,
#        NOT a DTO — K6). Token-protected via the SAME _verify_token used for /ingest
#        (404 unknown repo / 401 missing bearer / 403 wrong bearer, reads stay open).
#        404 ALSO if rec.record_id is not a record of this repo (loud K8 — a resolution
#        must reference one of the repo's records). Else store.add_resolution(rec) and
#        return 202 {record_id}. A malformed body -> 422 (pydantic, no hand DTO).
#
# --- Y-02: config-sync routes (git/local) --------------------------------------
#   POST /repos/{repo_id}/sync  body = SyncRequest {mode: "git"|"local"} -> 201 SyncRun.
#        Token-protected via _verify_token (404 unknown repo / 401 missing / 403 wrong).
#        400 if mode is invalid OR the repo has no local_path on file. Resolves
#        local_path + default_branch from the stored RegisteredRepo, runs
#        configsync.run_sync(... now=clock()) READ-ONLY against the repo (K1), then
#        store.replace_config(repo, mode, docs, refs) + store.add_sync_run(run) and
#        returns the run. A SyncError (bad mode / missing tree / git failure) -> 400
#        with the loud engine message (K8), never a 500.
#   GET  /repos/{repo_id}/documents?sync_kind=  -> list[DocumentTree] (READ, open; 404).
#        DocumentTree = {document: ConfigDocument, code_refs: tuple[ConfigCodeRef,...]}
#        — a JOIN VIEW (not a DTO of a SHARED schema): config_documents_for joined to
#        code_refs_for, nested per doc in the store's stable insertion order (K10).
#   GET  /repos/{repo_id}/sync-state?sync_kind=  -> SyncRun | null (latest run; 404 repo).
#
# --- F-05: RepoHealth (the metrics overview) -----------------------------------
# RepoHealth (server/app.py) is a COMPUTED AGGREGATE view (like RepoStatus), NOT a
# parallel copy of a stored shared model, so K6's "no DTOs for the SHARED schema" does
# not apply. Built deterministically from store reads (K10):
#   class RepoHealth(BaseModel):    # frozen, extra="forbid"
#       repo_id: str
#       total: int                          # == len(records_for(repo_id))
#       escalations: int                    # records with verdict ESCALATE
#       escalation_rate: float              # escalations / total (0.0 when total==0)
#       unresolved: int                     # records with no ResolutionRecord (by record_id)
#       overrides: int                      # resolutions with resolution == "overridden"
#       resolved: int                       # records that HAVE a resolution (distinct ids)
#       mttr_seconds: float | None          # mean(resolved_at - detected_at) over records
#                                           # that have a resolution; None if none resolved.
#                                           # detected_at from the ReviewRecord, resolved_at
#                                           # from its ResolutionRecord (both injected ISO).
#
# RepoStatus (server/app.py) is the ONE response DTO allowed here: it is a computed
# AGGREGATE view, NOT a parallel copy of a stored shared model, so K6's "no DTOs for
# the SHARED schema" does not apply (K6 governs the stored records/resolutions, which
# these endpoints still return AS the shared schema). It is built from store reads:
#   class RepoStatus(BaseModel):    # frozen, extra="forbid"
#       repo_id: str
#       total_records: int
#       by_verdict: dict[str, int]          # {"FIX": n, "INVALIDATE": n, "ESCALATE": n}
#       escalations: int                    # == by_verdict["ESCALATE"]
#       unresolved: int                     # records with no ResolutionRecord (by record_id)
#       last_detected_at: str | None        # max detected_at across the repo's records
#       coverage_ratio: float | None        # latest coverage snapshot's "ratio" if present
#
# --- E-06: per-repo bearer auth (on writes; reads are OPEN) ---------------------
# AUTH MODEL (chosen + documented): the CLIENT PROVIDES the token at register time;
# the server stores only its sha256 HASH (never plaintext, never returned). The token
# travels on RegistrationPayload as a WRITE-ONLY `auth_token: str | None` (additive,
# K6; excluded from any read serialization — RegisteredRepo never carries it). On
# register the server hashes it -> `repos.token_hash` (new nullable column + additive
# Alembic migration 0002). A repo registered WITHOUT a token has token_hash=None and
# its writes stay open (back-compat); supplying a token LOCKS subsequent writes.
#
# require_repo_token(repo_id, Authorization header, store) -> None | raises:
#   unknown repo                       -> 404 (as before; checked first)
#   repo has a token_hash, header missing/not-Bearer -> 401
#   header present but sha256 != stored -> 403
#   match (or repo has no token_hash)  -> pass
# Applied as a FastAPI dependency on POST /ingest and re-register on POST /repos
# (re-register of an EXISTING repo that has a token requires that token; first-time
# register is open so a repo can mint its token). The client (HttpSink/registry)
# already sends `Authorization: Bearer <auth_env value>` — header name/format match.
#
# Store Protocol GAINS (both InMemoryStore + SqlStore):
#   def records_for(repo_id, *, verdict=, drift_kind=, audience=, doc_id=,
#                   limit=, offset=) -> list[ReviewRecord]   # filtered (kwargs additive)
#   def resolutions_for_repo(repo_id, record_id=None) -> list[ResolutionRecord]
#   def coverage_for(repo_id) -> list[dict]
#   def repo_token_hash(repo_id) -> str | None
#   add_repo gains the token_hash side-write (from RegistrationPayload.auth_token)
# F-04 promotes `add_resolution(resolution)` onto the Store Protocol (both stores
# already implement it; InMemoryStore as a list, SqlStore as a row). _compute_health
# reads via the existing records_for / resolutions_for_repo — no new aggregation
# method needed (RepoHealth is computed in app.py like _compute_status).
# (InMemoryStore mirrors all of this in dicts; SqlStore via the indexed columns.)
#
# E-04 swaps InMemoryStore for a SQLAlchemy store behind THIS Store Protocol (offline
# tests on in-memory SQLite + a `pg` marker for real Postgres). EPIC E COMPLETE at E-06.
```

## `server/db.py`  (SQLAlchemy 2.0 store — Postgres-first, offline SQLite, E-04 — K0/K6/K10)
```python
# Swaps the E-03 InMemoryStore for a real SQLAlchemy store behind the SAME `Store`
# Protocol (server/app.py + the routes are UNTOUCHED). Behind the `[server]` extra
# (sqlalchemy>=2.0, alembic; psycopg[binary] only for real PG — SQLite is stdlib).
# Postgres-FIRST in prod; the DEFAULT offline suite runs it on in-memory/temp-file
# SQLite (K4/K9), and a `pg` pytest marker (mirroring `live_llm`) runs the SAME
# contract against $CDMON_DATABASE_URL Postgres in CI (skipped by default).
#
# DESIGN: "indexed columns + full JSON" hybrid (K6 additivity). Every record/
# resolution row stores the FULL shared pydantic model in a JSON column
# (`JSON().with_variant(JSONB, "postgresql")` — JSONB on PG, TEXT-JSON on SQLite) so
# an ADDED schema field (e.g. a future one) round-trips with NO migration — old rows
# still parse. ALONGSIDE the JSON, indexed SCALAR columns mirror the queryable fields
# (repo_id/doc_id/verdict/drift_kind/audience/detected_at/source_sha) so E-05 query
# endpoints filter in SQL without JSON extraction. The JSON is the source of truth on
# READ (we re-validate the pydantic model from it); the scalar columns are a derived,
# indexed projection written on INSERT.

# --- declarative models (SQLAlchemy 2.0 Mapped[]/mapped_column) ---
class Base(DeclarativeBase): ...

class RepoRow(Base):                # table "repos"
    repo_id: Mapped[str]            # PK
    payload: Mapped[dict]          # FULL RegistrationPayload JSON (K6 additive)
    token_hash: Mapped[str | None]  # E-06: sha256 of the per-repo bearer token, nullable
    # (display fields live in the JSON; RegisteredRepo is rebuilt from payload on read.
    #  token_hash is the ONLY non-JSON repo column — auth is never round-tripped via the
    #  payload JSON; the plaintext auth_token from RegistrationPayload is hashed on write
    #  and the hash kept here. A None token_hash means writes stay open for that repo.)

class RecordRow(Base):              # table "records"
    id: Mapped[int]                 # surrogate PK / insertion order (K10)
    repo_id: Mapped[str]            # FK-ish -> repos.repo_id, INDEXED
    record_id: Mapped[str]          # ReviewRecord.record_id, INDEXED
    doc_id / verdict / drift_kind / audience / detected_at / source_sha  # INDEXED scalars
    record: Mapped[dict]           # FULL ReviewRecord JSON (K6 additive, source of truth)

class ResolutionRow(Base):          # table "resolutions"
    id: Mapped[int]; record_id: Mapped[str] (INDEXED); resolution: Mapped[str]
    resolved_at: Mapped[str]; resolution_json: Mapped[dict]   # FULL ResolutionRecord

class CoverageSnapshotRow(Base):    # table "coverage_snapshots"
    id: Mapped[int]; repo_id: Mapped[str] (INDEXED); captured_at: Mapped[str]
    snapshot: Mapped[dict]         # FULL coverage payload JSON (opaque to E-04)

# Y-01 config-sync tables (same hybrid: indexed scalars + FULL pydantic JSON):
class ConfigDocumentRow(Base):      # table "config_documents"
    id: Mapped[int]                 # surrogate PK / insertion order (K10)
    repo_id / doc_id / sync_kind    # INDEXED scalars (the relationship filters)
    path / audience / unit / ref / synced_at   # derived scalar projection
    document: Mapped[dict]         # FULL ConfigDocument JSON (source of truth)
class ConfigCodeRefRow(Base):       # table "config_code_refs"
    id: Mapped[int]; repo_id / doc_id / sync_kind (INDEXED); path / unit
    code_ref: Mapped[dict]         # FULL ConfigCodeRef JSON (source of truth)
class SyncRunRow(Base):             # table "sync_runs"
    id: Mapped[int]; repo_id / sync_kind (INDEXED); ref / branch / head_commit /
    main_commit; commits_ahead: Mapped[int]; fully_synced: Mapped[bool]
    run: Mapped[dict]              # FULL SyncRun JSON (the opaque drift dict rides inside)

# --- factory + store ---
def engine_from_url(url: str) -> Engine            # create_engine; future_2.0 style
def create_all(engine: Engine) -> None             # Base.metadata.create_all (dev/tests)

class SqlStore:                     # implements `Store` + resolutions/coverage methods
    def __init__(self, engine: Engine) -> None     # one Session per call (sessionmaker)
    # Store Protocol (identical behavior to InMemoryStore):
    def add_repo(self, payload) -> None            # UPSERT on repo_id (repeat updates)
    def get_repo(self, repo_id) -> RegisteredRepo | None
    def list_repos(self) -> list[RegisteredRepo]   # ORDER BY repo_id insertion (K10)
    def add_record(self, repo_id, record) -> None  # writes JSON + indexed scalars
    def records_for(self, repo_id) -> list[ReviewRecord]   # ORDER BY id (insertion, K10)
    # E-04 extra (endpoints in E-05):
    def add_resolution(self, resolution: ResolutionRecord) -> None
    def resolutions_for(self, record_id: str) -> list[ResolutionRecord]
    def add_coverage_snapshot(self, repo_id, captured_at, snapshot: dict) -> None
    def coverage_snapshots_for(self, repo_id) -> list[dict]
    # Y-01 config-sync (parity with InMemoryStore; ORDER BY surrogate id, K10):
    def replace_config(repo_id, sync_kind, documents, code_refs) -> None
        # ONE transaction: DELETE this (repo_id, sync_kind) scope's document + code_ref
        # rows, then INSERT the new set (JSON source of truth + indexed projection, K6).
    def config_documents_for(repo_id, sync_kind=None) -> list[ConfigDocument]
    def code_refs_for(repo_id, doc_id=None, sync_kind=None) -> list[ConfigCodeRef]
    def add_sync_run(run) -> None; def sync_runs_for(repo_id, sync_kind=None) -> list[SyncRun]
    def latest_sync_run(repo_id, sync_kind=None) -> SyncRun | None  # ORDER BY id DESC, first

# `import custodex` core still imports NO sqlalchemy (lazy [server] boundary
# holds — db.py is imported only from the server subpackage / tests). create_app(
# SqlStore(sqlite_engine)) re-runs the E-03 server tests unchanged (Protocol swap is
# transparent).
```

## `alembic/`  (migrations — Postgres-first, E-04)
```python
# alembic/env.py reads $CDMON_DATABASE_URL (default a local sqlite file for dev) and
# uses db.Base.metadata as target_metadata (autogenerate-ready). The initial
# migration mirrors the four tables 1:1 (repos/records/resolutions/coverage_snapshots)
# with the indexed scalar columns + the JSON column. `alembic upgrade head` creates
# them; `alembic downgrade base` drops them (the up/down round-trip is gate-tested on
# a temp SQLite DB). The JSON column is portable (JSON on SQLite / JSONB on PG via the
# same with_variant type the models use). create_all (dev/tests) and Alembic (prod
# migrations) both derive from the SAME Base.metadata — one source of truth.
#
# E-06 adds migration 0002 (down_revision="0001_initial"): ADDITIVE
# `op.add_column("repos", Column("token_hash", String(), nullable=True))` on upgrade,
# `op.drop_column("repos", "token_hash")` on downgrade. up/down round-trip gate-tested
# (the temp-SQLite test asserts the column appears after upgrade head, gone after a
# downgrade to 0001 / base). Nullable so it is back-compatible with pre-E-06 repo rows.
#
# Y-01 adds migration 0003 (down_revision="0002_token_hash"): ADDITIVE create_table for
# config_documents / config_code_refs / sync_runs (mirroring the db.py rows 1:1 — indexed
# scalar columns + the portable JSON column), with their repo_id/doc_id/sync_kind indexes;
# downgrade drops the three tables. up/down round-trip gate-tested on temp SQLite
# (test_alembic_migration_0003_config_sync_up_then_down: tables absent at 0002, present at
# head, dropped again on downgrade to 0002 while the pre-Y-01 tables remain).
```

## `backends.py`  (pluggable LLM — K4)
```python
class FixRequest(BaseModel):
    drift: Drift; surface: DocumentSurface
    doc_text: str; doc_spec_id: str
    # D-04 ADDITIVE (K6): few-shot exemplars (default empty ⇒ every existing backend
    # test unchanged; MockBackend IGNORES them; build_prompt unchanged today).
    exemplars: tuple[Exemplar, ...] = ()
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
# D-04 ADDITIVE: a new artifact `agent/prompts/EXEMPLARS.md` (the few-shot framing).
#   select_artifacts appends Artifact.EXEMPLARS ONLY when `req.exemplars` is non-empty.
#   render_context renders each exemplar (drift shape → resolution; resolved_text for
#   OVERRIDDEN) UNDER the EXEMPLARS.md framing, ONLY when present. With NO exemplars the
#   composed prompt is BYTE-IDENTICAL to pre-D-04 (asserted). EXEMPLARS.md ships with the
#   [agent] extra; the core mock path imports nothing new (K0).
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
                 now: Callable[[], str] | None = None,
                 log_path: Path | None = None, source_sha: str | None = None,
                 # D-04 ADDITIVE: opt-in exemplar retrieval. DEFAULT OFF ⇒ byte-identical
                 # to today (no log read, FixRequest.exemplars stays ()).
                 use_exemplars: bool = False,
                 resolutions_path: Path | None = None,
                 exemplar_top_n: int = 3,
                 # D-06 ADDITIVE: opt-in promoted rules. DEFAULT () ⇒ byte-identical to
                 # today (every drift still goes to the backend). A drift matching a rule
                 # is resolved by the rule with ZERO backend calls.
                 rules: tuple[PromotionRule, ...] = ()): ...
    def check(self) -> DriftReport
    def run(self, *, apply: bool | None = None) -> MonitorResult
    # D-04: when use_exemplars=True, run reads review-log + resolutions ONCE, and per
    # drift `rank_similar(record-for-drift, all_records, resolutions, top_n)` to attach
    # exemplars to the FixRequest. Default OFF keeps run() side-effect-identical to today.
```
`run`: detect → per drift call backend → build ReviewRecord → append log + emit
sink → if `apply` and verdict==FIX, heal the doc → finally re-detect; `remaining`
= drift still present (ESCALATE, or FIX not applied). `now` injected for K10.

## `heal.py`
```python
def apply_fix(doc_path: Path, fix: ProposedFix, *, preserve: frozenset[str] = frozenset()) -> bool
    # region or whole-doc; idempotent (K7). `preserve` = region ids the engine must
    # NOT overwrite (B-02 `human` mode). The guarantee lives at this WRITE boundary,
    # not in the backend: a whole-doc `new_doc_text` is re-injected with the doc's
    # CURRENT bodies for every preserved region (via manifest.set_region) before the
    # write, so a backend that returned whole-doc text cannot clobber a human region.
    # A region-shaped fix targeting a preserved id is a no-op (returns False).
def regenerate_regions(doc_path, surface, templates=None, *, preserve: frozenset[str] = frozenset()) -> bool
    # never regenerates a region in `preserve` (skips it, leaves its bytes).
def render_corrected(doc_text, surface, templates=None, *, preserve: frozenset[str] = frozenset()) -> str
    # corrected whole-doc text; preserved regions are left as-is.
# Internal: _corrected(doc, surface, templates=None, *, preserve=frozenset()).
# DEFAULT empty `preserve` == EPIC-A behavior byte-for-byte (additive, K9).
```

**B-02 — heal never overwrites `human` regions (write-boundary guarantee).**
`drift.detect`: a region with `spec.mode_for(rid) is RegionMode.HUMAN` and a known
renderer whose stored body ≠ expected → `Drift(kind=REGION, healable=False,
detail="region '<id>' is human-owned …")` (reported, not auto-healed, K5); a human
region with NO known renderer suppresses the `UNHEALABLE` drift (intentional, not an
error). `monitor.run`: computes `preserve = frozenset(rid for rid in spec.region_keys
if spec.mode_for(rid) is RegionMode.HUMAN)` and passes it to `apply_fix`. The
FixRequest / backend contract is unchanged — the guarantee is enforced at heal.

**B-03 — `llm-seeded` lock (per-region content hash) + B-02 advisory persistence.**
The lock is the SHARED `manifest.region_is_locked(doc, rid, current_body)` predicate
(stored region hash present AND current body hash ≠ it). heal STAMPS
`cdm.region_hashes[rid]` whenever the engine authors a region — i.e. a `generated`
region it rewrites, or an `llm-seeded` region that is NOT locked (engine still fills
it). `_corrected`/`regenerate_regions` take an optional `spec`/`modes` so heal can
(a) auto-add every locked id to `preserve` and (b) stamp the hash of each authored
body. drift: a `llm-seeded` region behaves like `generated` while unlocked
(REGION healable=True, regenerate on drift) and like `human` once locked (REGION
healable=False when code moved; suppress UNHEALABLE for a no-renderer locked region).
A `human` region also carries a `region_hashes` entry stamped when last authored, so
its advisory PERSISTS across a fingerprint heal until the body actually changes
(fixes B-02's known limitation). Default (no region_hashes, no modes) == B-02
byte-for-byte (additive, K9).

## `cli.py`  (`cdx`)
`init | surface | check | monitor | report | coverage | schema` per SPEC, plus the
CONFIG-V2 surface `index | rpt | sync` (sync = Y-03, see configsync.py above). `check`
exits 1 on drift; `monitor` exits 0 unless drift `remaining`. Uses
`make_backend`/`make_sink` from config; `--apply/--no-apply` overrides
`apply_default`.

**A-08 — `cdx coverage --write [PATH]` (opt-in mutation; Decision 2: a dedicated
regenerable manifest, NOT injected into `cdmon.yaml`; K1/K7/K10).** `--write` takes
an optional PATH (default `.cdmon/coverage.json`, gitignored) and writes a
deterministic manifest = the A-05 `_coverage_payload(report)` PLUS a top-level
`suggestions` list (`suggest_owners(report, config)`, each `model_dump`ed), all
`json.dumps(..., indent=2, sort_keys=True)` + trailing newline. **Idempotent (K7):**
the existing file is read first; if its content equals the new content the file is
NOT rewritten and the command prints `coverage manifest unchanged`; otherwise it
writes (creating parent dirs) and prints the path. The default `coverage`
invocation stays read-only (K1) — `--write` is the only mutating mode. `--write`
composes with `--json`/`--fail-under` (stdout/exit unaffected by the write).

**B-05 — `cdx lint --modes` (per-region authority STATE surface, NOT a new gate).**
New pure helpers in `layout.py`:
```python
class RegionState(BaseModel):           # frozen, extra="forbid"
    doc_id: str
    region_id: str
    mode: RegionMode                    # spec.mode_for(region_id)
    has_renderer: bool                  # region_id in known_region_ids(templates)
    locked: bool                        # llm-seeded + manifest.region_is_locked(doc,id,body)
    advisory: bool                      # human (or locked llm-seeded): heal never authors it

def region_states(doc: Doc, spec: DocumentSpec, *, known: frozenset[str]) -> list[RegionState]
    # one RegionState per region PRESENT in the doc AND declared in spec.region_keys,
    # in spec.region_keys order; pure (uses spec.mode_for + manifest.stored_region_hash
    # + manifest.region_is_locked). NO re-validation (config-load already validated the
    # modes map) — this is a STATE read.

def config_region_states(config, config_dir) -> list[RegionState]
    # file-reading driver: parse each existing doc and collect region_states across all
    # documents (skips missing/malformed docs, like lint_config). root=config_dir/config.root.
```
`cdx lint --modes` prints one informational line per region (`doc::region — mode
[renderer|no-renderer] [locked] [advisory]`) and **keeps lint's existing pass/fail
semantics** (structural issues still drive exit code; `--modes` adds an info view, it
is not a gate). K0/K2/K10.

**B-06 — pure-`llm` prose authoring (the interim `llm`==`generated` rule REPLACED).**
A region declared `mode: llm` with **no mechanical renderer** is now **backend-authored
prose**, not `UNHEALABLE`. The behavior splits by whether a renderer exists:

* a renderer-backed `llm` region keeps EPIC-A behavior — mechanically rendered + kept in
  sync (unchanged from B-04);
* a no-renderer `llm` region is graded by whether the **code surface it documents moved**
  (the whole-doc fingerprint `stored != current`), NOT against any mechanical render (its
  prose legitimately differs): code moved → a healable `REGION` drift (`drift.detect`,
  detail `"llm-authored region {id!r} is stale; backend will re-author from the current
  surface"`); code unchanged → **no drift** (the prose stands). A *non-*`llm` no-renderer
  region still surfaces `UNHEALABLE` (genuinely no authoring path, loud K8).

The backend authors the body: `FixRequest.region_mode: RegionMode = RegionMode.GENERATED`
(ADDITIVE, K6; `monitor.run` sets it from `spec.mode_for(region_id)`). `MockBackend.propose`
gains a rule (between rule 1 and 2): a no-renderer `llm` `REGION` drift → `FIX` with a
DETERMINISTIC, IDEMPOTENT prose body authored from the surface (`_authored_prose`, K10) —
the offline stand-in for what an LLM would write, audience-aware (K3). `build_prompt`
appends a prose clause for an `llm` `REGION` request (real backends only). The critical
idempotence point: a code change raises BOTH a HASH (whole-doc) and a REGION (the llm
region) drift; the whole-doc HASH fix (`heal.render_corrected`/`_corrected`) PRESERVES a
no-renderer region's body byte-identical (it skips any id `not in known`), the REGION fix
authors the new prose, and a second `monitor --apply` is a clean no-op (K7). Documented in
`config.RegionMode` docstring + LAYOUT_STANDARD §7; asserted by
`test_system.test_pure_llm_no_renderer_authored_e2e` (the four-goal scenario) and guarded
by `[B-06]` in `tests/regression/`. The renderer-backed interim case stays asserted by
`test_system.test_mixed_authorship_four_regions_e2e`.

**D-01/D-02 — `cdx resolve` (capture the human outcome as a separate event).**
```
cdx resolve <record_id> --resolution {accepted|overridden|rejected|invalidated}
    [--by NAME] [--text TEXT] [--note NOTE] [--config PATH] [--log PATH]
```
Validates `<record_id>` EXISTS in the review log (`reviewlog.read_all` over
`config_dir/DEFAULT_LOG_PATH`); an unknown id is a loud `SchemaError` (K8, clean
one-line stderr, no traceback). On success it appends a `ResolutionRecord` to the
resolutions log (default `config_dir/reviewlog.DEFAULT_RESOLUTIONS_PATH`, overridable
with `--log`), timestamp via the module-level `cli._now()` seam (the same injectable
clock pattern monitor uses, K10), and prints `resolved <record_id> as <resolution>`.
`--text` populates `resolved_text` (the human's final body when OVERRIDDEN). The
review log is NEVER mutated — the outcome is a new append-only event linked by FK
(K5). `report` is additively extended to print `resolved`/`unresolved` counts.

**G-01 — `cdx init --central URL` (HTTP-reporting bootstrap; ADDITIVE, K0/K8).**
`init` grows four optional flags: `--central URL`, `--repo-id ID`, `--token-env VAR`
(default `CDMON_CENTRAL_TOKEN`), `--repo-url URL`. WITHOUT `--central` the command is
byte-identical to today (writes `config.CONFIG_TEMPLATE` via `write_template` — existing
init tests stay green). WITH `--central` it writes a `central:`-configured YAML built by a
new pure helper in `config.py`:
```python
def central_config_template(*, url: str, repo_id: str,
                            token_env: str = "CDMON_CENTRAL_TOKEN",
                            repo_url: str | None = None) -> str
    # returns CONFIG_TEMPLATE with the `central:` block replaced by an HTTP block:
    #   central:
    #     sink: "http"
    #     url: "<url>"
    #     repo_id: "<repo_id>"
    #     auth_env: "<token_env>"
    #     repo_url: "<repo_url>"        # only when given
    #     outbox: ".cdmon/outbox.jsonl"
    # round-trips through load_config AND satisfies make_sink's http reqs (repo_id present).
```
`--repo-id` defaults to the cwd directory name when omitted (loud only if cwd has no
usable name). The command refuses to clobber unless `--force` (unchanged). Offline: writes
ONE file, no network (K1/K4).

**W-02 — `cdx init --v2` (scaffold the `config/cdmon/` dir layout; ADDITIVE, K7/K8).**
`init` grows `--v2`, `--config-dir` (default `config/cdmon`), and `--repo` (defaults to
the cwd name). WITHOUT `--v2` the single-file behavior is byte-identical (above). WITH
`--v2` it calls `templates_v2.scaffold_config_dir(config_dir, repo=…, now=cli._now())` —
writing the four canonical files from the templates — and refuses to clobber an EXISTING
directory unless `--force` (loud K8). The scaffolded dir passes `load_bundle`/`cdx check`
(verified). Clock via the `cli._now()` seam (deterministic in tests, K10).

## `doctor.py`  (G-02 — offline preflight; pure-ish, read-only — K1/K4/K10)
A side-effect-free preflight (reads env only; NO network by default). `run_checks` returns
a DETERMINISTIC, ordered list of `Check` results; the CLI prints them and exits 0 unless any
is `FAIL`.
```python
class CheckStatus(str, Enum):    # PASS | WARN | FAIL
    PASS = "PASS"; WARN = "WARN"; FAIL = "FAIL"

class Check(BaseModel):          # frozen, extra="forbid"
    name: str
    status: CheckStatus
    detail: str

def run_checks(config: MonitorConfig, config_dir: Path) -> list[Check]
    # deterministic order (K10):
    #  1. "config"      — always PASS here (config already loaded by the CLI).
    #  2. "documents"   — one synthesized line: every doc.path resolves under root or is
    #                     a MISSING_DOC the heal can scaffold → PASS (missing is creatable,
    #                     not a failure); a doc whose code_ref file is absent → WARN.
    #  3. "backend"     — kind valid + its prereq: claude-code → `claude` on PATH;
    #                     api → $ANTHROPIC_API_KEY set; agent → langgraph importable +
    #                     the agent.driver prereq; mock → PASS. A merely-absent prereq is
    #                     WARN (this env can't RUN it, but the config is valid), never FAIL.
    #  4. "central"     — sink=none/file → PASS; sink=http → FAIL if url missing OR repo_id
    #                     missing (make_sink would raise, K8); else PASS, plus a WARN when
    #                     auth_env is set but that env var is unset/empty (token presence).
    #  5. "server-extra"/"agent-extra" — importability of the optional extras the chosen
    #                     config needs: agent backend → "agent-extra" (langgraph); always
    #                     emit "server-extra" only when relevant? NO — keep it simple: emit
    #                     an extra check ONLY for the agent backend (the one the config
    #                     selects). WARN if absent, PASS if importable.
    # Pure except os.environ / shutil.which / importlib.util.find_spec reads; NO network.
```
A `--ping` connectivity probe is explicitly OUT of G-02 (future: an injected transport;
default doctor is offline). `cli.py` gets a `doctor [--config]` command: loads the config
(loud K8 on a malformed one — that is the one path where doctor exits 1 BEFORE running
checks), runs `run_checks`, prints `STATUS  name — detail` per check, exits 0 unless any FAIL.

## `configsync.py`  (Y-02 — server-side config-sync engine; git/local, READ-ONLY — K1/K8/K10)
```python
# The engine the central server's POST /repos/{id}/sync route calls. It reads a
# registered repo's config/cdmon/ (+ the source it references), merges to one
# MonitorConfig, computes drift + coverage, and projects the result into the Y-01
# persisted rows (ConfigDocument/ConfigCodeRef) + one SyncRun summary — WITHOUT
# ever mutating the user's working tree (K1). NOT to be confused with syncpr.py
# (C-01, the doc-PATCH producer); configsync is the multi-repo SERVER sync.

class GitInfo(BaseModel):     # frozen; the git context a sync read at
    ref/branch/head_commit/main_commit: str | None; commits_ahead: int = 0
class SyncResult(BaseModel):  # frozen
    documents: tuple[ConfigDocument, ...]; code_refs: tuple[ConfigCodeRef, ...]; run: SyncRun

def read_config_at(local_path, *, mode, branch, now, run_git=_default_run_git)
        -> tuple[ConfigBundle, Path, GitInfo]      # the thin public façade
def run_sync(local_path, repo_id, *, mode, default_branch="main", now,
             run_git=_default_run_git) -> SyncResult

# Git is the ONLY side effect, reached through ONE injected runner
# (_run_git(args, cwd) -> stdout; default = subprocess, mirrors backends.py's
# injected-subprocess seam). A non-zero git exit -> loud SyncError (K8, errors.py).
#
# _open_repo (a @contextmanager) is the core: it yields (bundle, config_dir, git)
# while the SOURCE TREE IS READABLE — critical because drift detection + coverage
# read files lazily off disk, so the checkout must outlive them:
#   local: yields against the working-tree config/cdmon/ in place (nothing to clean).
#   git:   SUBDIR-AWARE (M-02). Resolves the git TOPLEVEL (`git -C local_path
#          rev-parse --show-toplevel`) + rel = local_path relative to it, materializes
#          the TOPLEVEL at <branch> via `git worktree add --detach <tmp> <branch>`, and
#          yields against <worktree>/<rel>/config/cdmon with repo_root <worktree>/<rel>
#          — so a config in a SUBDIR of the repo (e.g. the demo under demo/) resolves,
#          and rel == "." behaves exactly as a top-level checkout. If <branch> lacks
#          <rel>/config/cdmon (the config isn't committed to the default branch yet) ->
#          loud SyncError (K8; the standalone/seed callers treat git best-effort + skip).
#          In a finally `git worktree remove --force` (run against the TOPLEVEL) +
#          rmtree(tmp) — on success OR error, so the user's tree is never disturbed and
#          NO stray worktree leaks (K1).
# GitInfo is always computed against the ORIGINAL local_path: head_commit/branch via
# `git rev-parse [--abbrev-ref] HEAD`, main_commit via `git rev-parse --verify
# --quiet <default>` (None if the default branch is absent — no baseline), and
# commits_ahead via `git rev-list --count <default>..HEAD` (0 with no baseline).
# ref = HEAD (local) or the default-branch tip (git).
#
# Rows: bundle.unit_for_document attributes each doc/ref to its unit; sync_kind=mode;
# ConfigDocument.ref = git.ref; synced_at = now; symbols from the spec's code_refs.
# drift summary dict = {ok, drift_count, by_kind (sorted), coverage_percent} where
# coverage_percent reuses the REAL engine (effective_coverage -> discover_files ->
# discover_symbols -> resolve_coverage.percent_files, like report.build_coverage_rpt).
# fully_synced: git = no drift at <default> (the baseline); local = no drift AND
# commits_ahead == 0. now (injected) stamps synced_at/started_at/finished_at — ONE
# clock read, no wall-clock leakage (K10). Loud SyncError on missing local_path /
# unknown mode / git failure (K8). Offline: real local git only, no network.
```

**Y-03 — `cdx sync` (the client-facing trigger; local + remote).**
`cli.py` adds `cdx sync [--mode git|local] [--remote URL --repo-id ID]
[--token-env VAR] [--default-branch main] [--json]`:

* **LOCAL** (no `--remote`): runs `configsync.run_sync(Path.cwd(), repo_id, mode=...,
  default_branch=..., now=cli._now())` READ-ONLY against the current repo (K1) and
  prints the run summary (`fully_synced`, document/code_ref counts, `commits_ahead`,
  drift count + per-kind breakdown + coverage %) or `--json` (the `SyncRun`
  `model_dump(mode="json")` — byte-equal to the engine's). `repo_id` defaults to the
  bundle's index `repo` field (`load_bundle(config/cdmon).index.frontmatter.repo`) when
  a dir layout is present, else the cwd directory name — read, never invented. Exit 0;
  a loud `error:` line + Exit(1) on any `CodeDocMonitorError` (K8, no traceback).
* **REMOTE** (`--remote URL --repo-id ID`): POSTs `{mode}` to `<URL>/repos/{ID}/sync`
  via `registry.sync_repo_remote` → `HttpSyncTransport`, which REUSES the exact same
  stdlib HTTP+auth seam as `cdx register` (`registry._UrllibRegisterHttp.request(
  method, url, *, body, token)` lazily built when no leaf is injected, K0; bearer read
  from `--token-env` at call time, default `DEFAULT_CENTRAL_TOKEN_ENV`). The server's
  `SyncRun` JSON is printed via the SAME `_sync_run_lines` renderer (or `--json`).
  Missing `--repo-id` / empty url / an HTTP error → loud Exit(1) (K8). Tests mock the
  shared leaf exactly like `test_registry.py` (no network, K4); `_now` is injected so a
  local run is deterministic (K10). `cli.py` is dogfood-tracked → reheal after the
  command lands (`central-client`/`ops` docs).

## `syncpr.py`  (C-01 — doc-patch producer; git-free, offline, deterministic)
```python
class SyncResult(BaseModel):           # frozen, extra="forbid"
    patch: str                         # concatenated per-file unified diffs ("" if none)
    changed_paths: tuple[str, ...]     # repo-relative POSIX doc paths that changed (sorted)
    summary: str                       # human one-liner ("N doc(s) updated" / "clean")

def sync_pr(monitor: Monitor, *, dry_run: bool = False) -> SyncResult: ...
```
`sync_pr` orchestrates AROUND `Monitor` (no new heal/backend logic): it snapshots
each configured document's current text (or `None` if missing) BEFORE, runs
`monitor.run(apply=True)` (heals in place via the existing pipeline — so B-02/B-03
region authority is honored automatically: a `human`/locked `llm-seeded` body never
appears in the patch), reads each document AFTER, and builds a per-file
`difflib.unified_diff` for every changed doc (`fromfile="a/<path>"`,
`tofile="b/<path>"`, `lineterm=""`, deterministic — K10). Paths are the document's
repo-relative POSIX `spec.path`. A newly-created file diffs against `""` (an add).

**`dry_run` (K1) — restore-INCLUDING-delete.** When `dry_run` is true the patch is
computed exactly as above, then the tree is restored byte-identical to the start:
every doc that existed before is rewritten to its before-text, and every file the run
NEWLY created (before-text was `None`, e.g. a MISSING_DOC stub) is DELETED. The
contract is verified by a content snapshot before/after. `monitor.run` still appends
review-log/sink records (it always does — K5); the dry-run restore is about the
*document tree*, the thing C-03 turns into a docs MR.

Idempotent (K7): a clean repo (or a second `sync_pr` after an apply) heals nothing,
so AFTER == BEFORE for every doc → empty `patch`, empty `changed_paths`, summary
`"clean"`. Offline by default (mock backend, K4). `cli.py` adds
`cdx sync-pr [--config] [--out FILE] [--dry-run]`: default applies + prints the
patch (or writes it to `--out`) + prints the summary to stderr, exit 0; `--dry-run`
computes the same patch with NO mutation; malformed config → clean `error:` + Exit(1)
(K8). NOT dogfood-tracked (it imports nothing dogfood docs grade). `.gitlab-ci.yml`
gains a fast offline `docs:gate` job (`cdx check` + `cdx lint`) that fails the
pipeline on drift — orthogonal to `tests:offline`. C-03 (bot-PR opener) consumes
`SyncResult.patch` + `changed_paths` over an INJECTED GitLab transport.

## `pr.py`  (C-03 — bot-PR opener; provider-agnostic, INJECTED transport — K0/K4/K10)
```python
class MergeRequestPlan(BaseModel):          # frozen, extra="forbid"
    source_branch: str                      # f"{branch_prefix}-{sha256(patch)[:12]}" (deterministic, K10)
    target_branch: str = "main"
    title: str                              # "docs: sync" (+ " to <ref>" when ref given)
    description: str                        # bot-generated note + bulleted changed_paths
    files: tuple[tuple[str, str], ...]      # (repo-relative POSIX path, NEW healed content) commit actions
    labels: tuple[str, ...] = ()

class PRTransport(Protocol):                # runtime_checkable
    def submit(self, plan: MergeRequestPlan) -> dict: ...   # provider response (e.g. {"web_url": ...})

class GitLabTransport:                      # DEFAULT — stdlib urllib only (no python-gitlab/requests, K0)
    def __init__(self, *, project_id: str, token: str, api_url: str = "https://gitlab.com/api/v4",
                 http: _GitLabHttp | None = None) -> None: ...
    # submit(): 3 GitLab REST calls behind ONE injected http leaf — create branch from target,
    #   create a commit with the file actions, open the MR; returns the MR JSON.
    @classmethod
    def from_env(cls, *, project_env="CI_PROJECT_ID", token_env="CDMON_GITLAB_TOKEN",
                 api_env="CI_API_V4_URL") -> GitLabTransport: ...
    #   loud GitLabError (CodeDocMonitorError) when a required env var is missing/empty (K8).

def plan_docs_pr(sync: SyncResult, root: Path, *, target_branch="main", ref: str | None = None,
                 branch_prefix="cdmon/docs-sync", labels: tuple[str, ...] = ()) -> MergeRequestPlan | None
    # None when sync.patch == "" (empty → no MR). Reads each sync.changed_paths file's CURRENT
    # content from `root` (the healed docs) into `files`. Deterministic branch from sha256(patch).

def open_docs_pr(sync: SyncResult, root: Path, *, transport: PRTransport, dry_run: bool = False,
                 **plan_kw) -> dict | None
    # empty sync → return None (no-op, transport untouched). dry_run → return plan.model_dump()
    #   (no transport call). else transport.submit(plan).
```
**Inject-the-leaf (CDM-04/05, K4).** The single side-effecting boundary is the
`GitLabTransport` HTTP leaf `_GitLabHttp.request(method, url, *, body, token) -> dict`;
its one real `urllib.request.urlopen` is the ONLY `# pragma: no cover` line. Tests
drive `open_docs_pr` with a FAKE `PRTransport` that records and asserts the exact plan
(branch/title/description/files/labels); the build-default + missing-env branches are
covered by stubbing the leaf and by asserting the loud `from_env` error — so 100% holds
with ZERO network. `cli.py` adds
`cdx open-docs-pr [--config] [--dry-run] [--target BRANCH] [--ref REF]`: runs
`sync_pr` (with `dry_run=True` under `--dry-run` so NOTHING is written) then `open_docs_pr`;
an empty sync prints "clean — nothing to open" (no transport, no MR); `--dry-run` prints
the plan as JSON without building/calling a transport; otherwise it builds the default
`GitLabTransport.from_env()` (loud K8 error if env missing) and submits. C-04 consumes the
plan's `files`/`changed_paths` (the doc paths) to build a heal-exclude so the bot's
doc-only commit does not re-trigger heal; C-05 threads `ref`/`source_sha` into provenance
(here `ref` already lands in the title + description).

`pr.py`/`cli.py` import nothing the dogfood docs grade (NOT dogfood-tracked).

### C-04/C-05 — loop-safety + provenance (the loop-closing slices)

**C-04 — `syncpr.should_sync` (the structural loop-breaker, K1/K10).** A pure,
deterministic predicate co-located with `sync_pr`:

```python
def should_sync(changed_files: Iterable[str], config: MonitorConfig) -> bool
    # managed = {PurePosixPath(d.path) for d in config.documents} (POSIX-normalized)
    # return True iff at least one changed file is NOT a managed doc path.
    # empty changed set -> False (nothing to do). Read-only (K1), no I/O (K10).
```

Normalization: each changed path and each `config.documents[*].path` is run through
`PurePosixPath` (so `./docs/x.md`, `docs/x.md`, and a back-slash variant compare
equal). `should_sync` returns `True` (PROCEED with heal) when any changed file is
outside the managed-doc set, `False` (SKIP) when EVERY changed file is a managed doc
(a bot doc-only commit) or the set is empty. It is provider-agnostic — it only needs
the changed-file list, however CI obtains it.

`cli.py` adds `cdx should-sync [--config] [FILES...]` (also reads newline-separated
paths from stdin when no FILES are given): exits `0` when `should_sync` is `True`
(proceed), `1` when `False` (skip). Malformed config → clean `error:` line + Exit(1)
(K8). `.gitlab-ci.yml`'s heal path uses it (a commented guard) so a doc-only commit
runs no heal — breaking the PR→heal→PR loop structurally.

**C-05 — `ReviewRecord.source_sha` provenance (ADDITIVE, K6).** `schema.py` adds one
field to `ReviewRecord`, AFTER the existing fields, default `None`:

```python
    source_sha: str | None = None  # the code ref/commit this heal came from (K6 additive)
```

Old JSONL lines without `source_sha` still `model_validate_json` (default None);
existing records stay byte-valid; `cdx schema` re-emits it. `monitor.py` threads it:

```python
Monitor(config, config_dir, *, ..., source_sha: str | None = None)  # __init__ stores it
Monitor.run(*, apply=None)  # stamps every ReviewRecord with self._source_sha
```

`_record_for` passes `source_sha=self._source_sha` (default None keeps today's records
valid). `cli.py` `monitor` gains `--ref/--source-sha REF`; the value flows to
`Monitor(..., source_sha=ref)`. **Ref precedence (documented one source of truth):**
explicit `--ref`/`--source-sha` wins; else `$CI_COMMIT_SHA` from the environment; else
`None`. The SAME ref a CI run passes to `monitor` can be passed to `open-docs-pr --ref`,
so the record's `source_sha` and the MR title/description (C-03) agree.

`should_sync` lives in `syncpr.py` (NOT dogfood-tracked); `schema.py` (SHARED across
foundation+remediation docs) and `monitor.py` (remediation) ARE dogfood-tracked → reheal
after the field/signature land.

## Dashboard (EPIC F)  (`dashboard/` — Vite + React + TypeScript SPA, frontend-only)

A standalone SPA that READS the central server (EPIC-E) and visualises repos,
drift records, and coverage. It is **not** a Python module: it lives in `dashboard/`,
has its own Node toolchain + test gate (Vitest), and is NOT tracked by `cdx`
(no `**/*.py`). The Python gate is untouched by EPIC-F.

### Toolchain + scripts
- **Vite + React 19 + TypeScript** (`react-ts` template). **Vitest** + `@testing-library/react`
  + `jsdom` for component/unit tests; **ESLint** (flat config, `typescript-eslint`).
- `package.json` scripts: `dev` (Vite dev server w/ proxy), `build` (`tsc -b && vite build`
  → `dist/`, ZERO TS errors), `lint` (ESLint), `test` (Vitest watch), `test:run` (Vitest CI,
  single run, no watch). **No real network in tests** — the API client is injected/mocked.
- `package-lock.json` committed; `node_modules/` + `dist/` gitignored.

### API client contract (`src/api/client.ts`)
A small typed client over the OPEN read endpoints (E-06: reads need no auth):

```ts
type Fetch = typeof fetch;                       // injectable for tests (no MSW needed)
interface ApiClientOptions { baseUrl?: string; fetchImpl?: Fetch; }
class ApiClient {
  constructor(opts?: ApiClientOptions);          // baseUrl default = VITE_API_BASE ?? "/api"
  listRepos(): Promise<RegisteredRepo[]>;        // GET {base}/repos
  repoStatus(repoId: string): Promise<RepoStatus>; // GET {base}/repos/{encoded}/status
}
```

`repoId` is URL-encoded **except `/`** (repo_ids may be `org/name`; the server route is
`{repo_id:path}`). Non-2xx → a thrown `ApiError {status, url}`. Base URL from
`import.meta.env.VITE_API_BASE` (UNSET → `/api`).

**Two deploy modes (same code):**
- **Dev** (`npm run dev`, mode=development): SPA on its own port, `VITE_API_BASE` unset
  → `/api`; Vite `server.proxy` maps `/api` → `http://127.0.0.1:33333` (the FastAPI app
  on `0.0.0.0:33333`), stripping the prefix.
- **Single-origin** (the shipped build): `dashboard/.env.production` sets `VITE_API_BASE=/`
  → the client collapses the trailing slash to `""` and calls the API at the **origin root**
  (`/repos`, `/health`). `create_app(static_dir=…)` then serves the built `dist/` — `index.html`
  at `/` and assets at `/assets` — on the SAME FastAPI app/port as the API. `main()` auto-detects
  `dashboard/dist` (built) and passes it. The SPA uses a **HashRouter** (`#/repos/…`) so a client
  route never shadows an API route like `GET /repos/{id}/coverage` (the server only ever sees `/`).
  No build present → `/` falls back to the JSON landing.

### Types (`src/types.ts`) — hand-mirror the server models (one source of truth = the server)
```ts
interface RepoIdentity { repo_id: string; repo_name?: string | null; repo_url?: string | null; commit?: string | null; }
interface RegisteredRepo { repo: RepoIdentity; default_branch?: string | null; description?: string | null; }
type Verdict = "ok" | "review" | "escalate";   // mirrors schema.Verdict
interface RepoStatus {
  repo_id: string; total_records: number; by_verdict: Record<string, number>;
  escalations: number; unresolved: number;
  last_detected_at?: string | null; coverage_ratio?: number | null;
}
```
F-02+ can generate `ReviewRecord`/`ResolutionRecord` TS from `cdx schema` (JSON Schema)
rather than hand-writing them; F-01 hand-writes only the two small shapes it consumes.

### Pages / structure
- `src/api/client.ts`, `src/types.ts` — the contract above (reused by F-02/03/04).
- `src/pages/Repos.tsx` — fetches `listRepos()` then `repoStatus(id)` per repo; renders a
  table (repo id/name, total records, by-verdict, unresolved, escalations, coverage %).
  Explicit **loading** and **error** states. Client injected via prop (default = singleton)
  so tests pass a fake — NO network.
- `src/App.tsx` — single route now (`/` → Repos); F-02/03/04 add routes (drift timeline,
  coverage, resolve). Router kept minimal (a stub switch, or react-router if added later).
- `src/main.tsx`, `index.html`, `src/index.css` — Vite entry + minimal styling.

### Test approach
Component tests render a page with a **fake client** (a plain object implementing the
`ApiClient` surface) resolving/rejecting fixtures → assert rendered repo ids + a status
number, the loading state (pending promise), and the error state (rejected promise). The
client unit test injects a **fake `fetch`** capturing the requested URL/method to assert the
path + base-URL building. Everything runs under `jsdom`; zero sockets opened.

### F-02/F-03 — routing + drift-timeline + coverage views (frontend-only)

**Routing (`react-router-dom` ^7).** `main.tsx` wraps `<App>` in `<BrowserRouter>`; tests
use `<MemoryRouter>`. Routes:
- `/` → `Repos` (F-01). Each repo id cell is a `<Link>` to its detail route + a `coverage` link.
- `/repos/:repoId` → drift timeline (F-02).
- `/repos/:repoId/coverage` → coverage snapshot (F-03).

A repo id may contain a slash (`org/name`), which a react-router `:param` can't capture, so a
single **splat** route `/repos/*` lands on `src/pages/RepoRoute.tsx`, which reconstructs the
full id from the tail and dispatches: a `…/coverage` suffix → `Coverage`, else `RepoDetail`.
`src/routing.ts` holds the inverse link builders `linkToRepo(id)` / `linkToCoverage(id)`
(each path segment `encodeURIComponent`d, slashes preserved).

**ApiClient additions (`src/api/client.ts`).** Still OPEN reads (E-06), `fetch` injectable.
The default client now resolves `globalThis.fetch` **lazily** (so `vi.stubGlobal('fetch', …)`
is honored by the shared singleton in integration tests):
```ts
interface RecordFilters { verdict?: string; drift_kind?: string; audience?: string;
                          doc_id?: string; limit?: number; offset?: number; }
class ApiClient {
  recordsFor(repoId, filters?: RecordFilters): Promise<ReviewRecord[]>; // GET …/records?<filters>
  resolutionsFor(repoId): Promise<ResolutionRecord[]>;                  // GET …/resolutions
  coverageFor(repoId): Promise<CoverageSnapshot[]>;                     // GET …/coverage (latest last)
}
```
Filters → query params via `URLSearchParams`, dropping `undefined`/`""` (so `offset: 0` is
still sent but an empty drift_kind is not).

**Types (`src/types.ts`).** `RecordVerdict` (`FIX|INVALIDATE|ESCALATE`), `Audience`,
`ProposedFix`, `ReviewRecord` are **generated** from the real Python schema —
`.venv/bin/cdx schema --out dashboard/src/schema.review.json` (schema.py::ReviewRecord,
the K6 source of truth); the interfaces mirror that JSON's `properties`. `cdx schema`
emits ONLY the review record, so `Resolution`/`ResolutionRecord` are hand-written from
schema.py::ResolutionRecord, and `CoverageSnapshot` from the server's OPAQUE snapshot dict
(`store.coverage_for → list[dict]`; only `ratio` is contractual, app.py reads it — the
documented/undocumented/waived basket counts are optional + defensively rendered).
NOTE the verdict naming: F-01's `Verdict` (`ok|review|escalate`) is the *RepoStatus
aggregate* bucket; the per-record decision is the distinct `RecordVerdict`.

**Pages.** `src/pages/RepoDetail.tsx` — controlled filter inputs (verdict/audience selects +
drift_kind text) whose state is a `useApi` dep, so a change re-queries `recordsFor` with the
new params; rows show doc, drift_kind, verdict, detected_at, source_sha + a **resolution
badge** (resolutions fetched once and joined by `record_id`; `unresolved` otherwise).
`src/pages/Coverage.tsx` — the latest snapshot's `ratio` as a % + the three baskets; empty
list → "No coverage reported yet". Both have loading/error/empty states.

**Shared hook `src/hooks/useApi.ts`.** `useApi(loader, deps) → {phase:'loading'|'error'|'ready', …}`
re-runs `loader()` on dep change and cancels a stale in-flight load (so a fast filter change
can't overwrite newer results).

**Test approach (extends F-01).** Same injectable-fake-client pattern (no MSW/sockets). The
RepoDetail test's fake **captures `recordsFor` call args** to assert a filter change
re-queries with the right params; a resolved record shows its badge. Coverage asserts the %
+ basket counts and the empty state. The App routing test stubs `globalThis.fetch` (URL→fixture)
and drives the *real* router end to end (click a repo link → detail/coverage renders).

### F-04/F-05 — resolve write path + health overview (full-stack)

**ApiClient additions (`src/api/client.ts`).** The FIRST WRITE methods. A small
`postJson` helper adds `Content-Type: application/json` + `Authorization: Bearer <token>`:
```ts
class ApiClient {
  // POST {base}/repos/{encoded}/resolutions, body = ResolutionRecord, Bearer token.
  // Returns the server's {record_id}. Non-2xx -> ApiError (401/403/404 surface).
  resolve(repoId, rec: ResolutionRecord, token: string): Promise<{ record_id: string }>;
  // GET {base}/repos/{encoded}/health -> RepoHealth (OPEN read).
  healthFor(repoId): Promise<RepoHealth>;
}
```
`RepoHealth` is added to `src/types.ts` mirroring the server's computed view (the same
distinction noted for `RepoStatus`: a computed AGGREGATE, not the shared wire schema).
`ResolutionRecord` (already in types) is the SHARED schema sent on the wire.

**RepoDetail resolve control.** Each UNRESOLVED record row gains a small resolve form: a
`<select>` of `Resolution` (`accepted|overridden|rejected|invalidated`), an optional
note/text input, and a token input (the bearer). On submit it builds a `ResolutionRecord`
(injected `resolved_at` ISO — `new Date().toISOString()` at the page edge, NOT in pure
code) and calls `api.resolve(repoId, rec, token)`; on success the row reflects the new
resolution badge (re-query). A MISSING token is a friendly inline validation, never a POST
(so the fake client is not called). The fake client **captures the `(repoId, rec, token)`
args** so the test asserts the right body + bearer.

**Health panel.** `src/pages/Health.tsx` renders `RepoHealth` as stat cards (total,
escalations, escalation rate %, unresolved, overrides, resolved, MTTR — humanised seconds,
"—" when null). Routed via the `/repos/*` splat: a `…/health` suffix → `Health`
(`linkToHealth(id)` in `routing.ts`). Loading/error/empty states like Coverage.

# EPIC H — surface what needs improving (telemetry + gap issues)

## H-01 — `GET /repos/{repo_id}/telemetry` (server underperformer view — K6/K10)
A COMPUTED AGGREGATE view (like `RepoStatus`/`RepoHealth`, NOT a parallel copy of a
stored shared model, so K6's "no DTOs for the SHARED schema" does not apply — the
record/resolution endpoints still return the SHARED schema). Built deterministically
from `store.records_for(repo_id)` + `store.resolutions_for_repo(repo_id)` in `app.py`
(no new Store method — same pattern as `_compute_health`):
```python
# server/app.py
class ShapeStat(BaseModel):              # frozen, extra="forbid"
    drift_kind: str
    audience: str                        # Audience .value (the stored string)
    count: int                           # records of this (drift_kind, audience) shape
    escalations: int                     # those with verdict == ESCALATE
    escalation_rate: float               # escalations / count  (count >= 1, so no /0)
    overrides: int                       # resolved (first-resolution-wins) == OVERRIDDEN
    override_rate: float                 # overrides / count   (fraction of the SHAPE's records)

class RepoTelemetry(BaseModel):          # frozen, extra="forbid"
    repo_id: str
    shapes: tuple[ShapeStat, ...]        # one per (drift_kind, audience), WORST-FIRST
    promotion_candidates: tuple[PromotionCandidate, ...]  # detect_promotions over the repo

def _compute_telemetry(store, repo_id) -> RepoTelemetry
#   GET /repos/{repo_id}/telemetry -> RepoTelemetry (OPEN read, 404 if repo unknown)
```
- **Shape key = `(drift_kind, audience)`** (NOT `doc_id` — a coarser, cross-doc shape
  than promotion's, surfacing which KIND of drift the backend handles poorly).
- **`override_rate`** = OVERRIDDEN resolutions / the shape's record count. First
  resolution per record wins (insertion order, mirrors `_compute_health`); a record
  with no resolution contributes 0 overrides. `escalation_rate` = ESCALATE verdicts /
  count.
- **Ordering (K10): worst-first** = `escalation_rate` DESC, then `override_rate` DESC,
  then `(drift_kind, audience)` ASC as the deterministic tie-break.
- **`promotion_candidates`** reuses `detect_promotions(records, resolutions)` server-side
  (the SAME pure detector the CLI uses) — surfacing shapes ripe to auto-promote.

## H-04 — `issues.py` + `cdx surface-gaps` (coverage gaps → tracker issue — K0/K4/K8/K10)
A NEW engine module mirroring `pr.py`'s INJECTED-transport / inject-the-leaf pattern:
the deterministic issue payload is pure; the real provider POST is the only
`# pragma: no cover` leaf; tests drive a fake transport (no network, K4).
```python
# custodex/issues.py  (new)
class IssuePlan(BaseModel):              # frozen, extra="forbid"
    title: str                          # "docs: N undocumented public symbol(s)"
    body: str                           # deterministic: gaps grouped by suggested owner
    labels: tuple[str, ...] = ()        # default ("documentation",)

class IssueTransport(Protocol):
    def submit(self, plan: IssuePlan) -> dict: ...

class _IssueHttp(Protocol):             # injected JSON leaf (mirrors pr._GitLabHttp)
    def request(self, method, url, *, body, token) -> dict: ...

class GitLabIssueTransport:             # POST <api>/projects/<id>/issues (PRIVATE-TOKEN)
    def __init__(self, *, project_id, token, api_url="https://gitlab.com/api/v4",
                 http: _IssueHttp | None = None)
    @classmethod
    def from_env(cls, *, project_env="CI_PROJECT_ID", token_env="CDMON_GITLAB_TOKEN",
                 api_env="CI_API_V4_URL") -> GitLabIssueTransport   # loud K8 if unset
    def submit(self, plan) -> dict      # builds {title, description, labels} body

class GitHubIssueTransport:             # POST <api>/repos/<repo>/issues (Bearer)
    def __init__(self, *, repo, token, api_url="https://api.github.com",
                 http: _IssueHttp | None = None)
    @classmethod
    def from_env(cls, *, repo_env="GITHUB_REPOSITORY", token_env="CDMON_GITHUB_TOKEN",
                 api_env="GITHUB_API_URL") -> GitHubIssueTransport  # loud K8 if unset
    def submit(self, plan) -> dict      # builds {title, body, labels} body

def plan_coverage_issue(report: CoverageReport,
                        suggestions: tuple[OwnerSuggestion, ...]) -> IssuePlan | None
    # None if no undocumented public symbol gaps. Else a DETERMINISTIC plan: title counts
    # the gaps; body groups every gap symbol under its suggested owner (suggestions sorted
    # by (suggested_doc_id, path, name)), each line "- `path::name` (kind)". K10.

def open_coverage_issue(report, suggestions, *, transport, dry_run=False) -> dict | None
    # None if no gaps (no-op). dry_run -> plan.model_dump() WITHOUT calling transport.
    # Else transport.submit(plan) and return the provider response.
```
Both `_Urllib*IssueHttp` leaves are stdlib-only urllib (no `requests`, K0); their real
`urlopen` is the ONLY `# pragma: no cover` line. Lazy build (no http injected) + missing
-env are covered (real POST stubbed), mirroring `pr.py`.

**`cdx surface-gaps [--config] [--dry-run] [--provider gitlab|github]`.** Runs
discover→`resolve_coverage`→`suggest_owners`, builds the plan. No gaps → prints
"no coverage gaps" and exits 0 (no transport built). `--dry-run` prints the plan JSON
WITHOUT building/calling a transport (a `_NullTransport` like `open-docs-pr`). Else the
provider transport is built `from_env` (loud K8 if env missing) and the issue is opened;
prints the created issue's `web_url`. Offline + deterministic in `--dry-run` (K4/K10).

**Dogfood (cdmon.yaml):** `issues.py` is a NEW engine module → ADD it to the `pr-loop`
DocumentSpec's `code_refs` (alongside `syncpr.py`/`pr.py`, the natural home for the
PR/issue transports) so `cdx coverage --fail-under 95` self-gate stays green.

# EPIC EDITOR — the interactive config editor (E-01..E-13)

The EDITOR feature turns the read-only dashboard into a SCOPED write surface: a
per-repo **Mapping page** renders the on-disk `config/cdmon/*.yaml` document↔code
mapping live, lets a user EDIT it by "filing a ticket", and runs document
generation that writes the change back to disk + reindexes + heals + re-syncs
("makes it live"). It also adds a one-click "apply the LLM's proposed fix" on a
drift record, and a new `context_refs` unit-file key. See the master spec
`.project/spec/EDITOR.md` (the EDITOR layer builds ON CONFIG-V2 — see
`.project/spec/CONFIGV2.md`).

**Locked invariants (every EDITOR slice respects these):**
- **Disk is the source of truth; SQL is the live mirror.** A web edit is STAGED as
  a `config_edits` row (the "ticket"); "Generate / make live" APPLIES the staged
  edits to disk, scaffolds/heals docs, `regenerate_index`, and re-runs
  `run_sync(local)`, which reprojects `config_documents`/`config_code_refs`/
  `sync_runs` into SQL. The dashboard then reads the freshly-synced SQL → "live".
- **Scoped WRITE surface (K1 relaxation).** Unlike `check`/`sync` (read-only),
  generate + apply-fix mutate the working tree — but ONLY `config/cdmon/*.yaml`
  (units + index + `doc-style.yaml`) and the declared document `.md` files. Never
  an arbitrary path. Writes require the per-repo bearer token; OPEN repos write
  token-less (L-01 parity). Every loud failure is a typed `CodeDocMonitorError`
  → a 400 (NOT a 500) at the route boundary (K8).
- **`context_refs` is additive (K6) and NOT coverage.** It is GENERATION context
  ("glance-through" references — sub-docs / sub-source-files the author should
  refer to when authoring a doc), never counted in coverage/`.rpt`, never a
  documented-surface gap. Distinct from `code_refs` (the documented surface).
- **Offline + deterministic (K10), idempotent (K7).** Mock backend; injected
  `now`/`clock`; a second identical generate is a byte-identical no-op heal.
- **Store parity.** Every new store method works identically over InMemoryStore
  AND SqlStore; the new `config_edits` table is additive (JSON blob + indexed
  scalars); `context_refs` rides INSIDE the existing `ConfigDocument` JSON column
  (NO migration).

## `context_refs` — the new unit-file key (E-01, `config.py`/`schema.py`)
A document entry in a unit `.yaml` MAY carry `context_refs:` — a list of
sub-documents / sub-source-files used as generation context but NOT documented:
```yaml
documents:
  - id: getting-started
    path: docs/guide/getting-started.md
    audience: user-guide
    code_refs:
      - path: src/taskflow/core/model.py
        symbols: [Task]
    context_refs:                      # NEW (additive, K6) — generation context
      - path: docs/api/core-api.md      # a sibling DOC to refer to
        note: "link to the full engine reference"
      - path: src/taskflow/core/engine.py   # a source file to glance through
        note: "scheduling semantics referenced in the tour"
```
- `ContextRef(path: str, note: str | None = None)` — frozen, `extra="forbid"`.
  `DocumentSpec` GAINS `context_refs: tuple[ContextRef, ...] = ()` AND the v2
  `UnitDocument` parse path; it flows through the `MonitorConfig` projection
  unchanged. Loud K8: each path must be a string; duplicate paths within one
  document are an error. Paths are repo-root-relative and NOT resolved for
  existence at load (a context ref MAY point at a not-yet-created doc).
- It feeds GENERATION ONLY: `backends.build_prompt` / `agent.graph.render_context`
  surface the `context_refs` as a reference block (path + note; for a source-file
  ref, a short glance — the public symbol names) when AUTHORING a scaffold or `llm`
  region. The mock backend ignores the block; tests assert it is PRESENT in the
  built prompt and that scaffolding still succeeds. It never enters `code_refs`,
  coverage, or drift.

## `config.py` model editors + unit serializer (E-01)
Pure editors operating on the frozen MODEL (return NEW units, no mutation) — the
ONLY new config primitive the EDITOR needs (everything else is composed from
existing helpers):
```python
def dump_unit_file(unit: UnitFile, *, now: str) -> str   # --- frontmatter --- + body;
    # deterministic key order, idempotent; load_unit_file(dump_unit_file(u)) round-trips.
def upsert_document(unit: UnitFile, doc: DocumentSpec) -> UnitFile  # add/replace by id
def add_code_ref(unit, doc_id, ref: CodeRef) -> UnitFile
def remove_code_ref(unit, doc_id, path: str) -> UnitFile
def set_context_refs(unit, doc_id, refs: tuple[ContextRef, ...]) -> UnitFile
```
`docstyle.py` gains `dump_doc_style(map, *, now) -> str` (the `doc-style.yaml`
serializer) so a `set_doc_style` edit can rewrite that file too.

## `server/edits.py` — staged "mapping ticket" model (E-03)
The typed payload of one staged edit — a `ConfigEdit` discriminated union on
`action` — plus `StoredConfigEdit`, the persisted envelope. Imports only
pydantic + stdlib (no fastapi/store cycle); frozen + `extra="forbid"` (an unknown
`action`/stray field is a loud K8 validation error → 422):
```python
class EditCodeRef(BaseModel):    path; symbols: tuple[str,...] = (); lines: str | None  # "start-end"
class EditContextRef(BaseModel): path; note: str | None        # K6 generation context
class EditDocStyle(BaseModel):   document_type/tone/writing_style/vocabulary: str|None  # all optional
class CreateDocEdit:      action="create_doc";      unit; doc_id; path; audience; code_refs; context_refs; doc_style?
class AddCodeRefEdit:     action="add_code_ref";     unit; doc_id; ref: EditCodeRef
class RemoveCodeRefEdit:  action="remove_code_ref";  unit; doc_id; path
class SetContextRefsEdit: action="set_context_refs"; unit; doc_id; context_refs
class SetDocStyleEdit:    action="set_doc_style";    doc_id; doc_style   # unit-independent (keys on doc id)
ConfigEdit = Annotated[<union>, Field(discriminator="action")]
class StoredConfigEdit:   edit_id; status; created_at; applied_at: str|None; edit: ConfigEdit
```

## `generate.py` — the "make live" engine (E-06/E-07)
The core, fastapi-free engine the server's generate/apply-fix routes call (lives
in core so it is unit-testable + dogfood-coverable). Offline + deterministic
(K10), idempotent (K7), SCOPED writes only (K1 relaxation):
```python
class GenerateResult(BaseModel):  affected_units; affected_docs; wrote_doc_style; index_changed  # frozen
class ApplyFixResult(BaseModel):  applied: bool; doc_path: str; diff: str                        # frozen

def apply_edits_to_disk(local_path: Path, edits: list[ConfigEdit], *, now, backend=None) -> GenerateResult
    # 1. resolve config/cdmon (loud K8 if absent); group edits by unit, apply each via the
    #    EXISTING pure model editors (upsert_document / add_code_ref / remove_code_ref /
    #    set_context_refs), rewrite the unit yaml via dump_unit_file; set_doc_style edits
    #    rewrite doc-style.yaml. 2. regenerate_index + write_index (re-stamp `updated` from
    #    `now` for K7). 3. reload the bundle and, per affected doc, scaffold_doc a missing
    #    file then regenerate_regions to bring managed regions in sync — preserving HUMAN
    #    regions (mirrors the monitor/new-doc preserve/modes derivation, B-02/B-03). NO LLM.
def apply_record_fix(local_path: Path, record: ReviewRecord, *, now) -> ApplyFixResult
    # the SCOPED counterpart of `cdx monitor --apply` for ONE recorded drift: loud K8 if
    # the record carries no applicable fix (fix is None / verdict != FIX); resolve the doc
    # path under the repo root; derive preserve/modes from the DocumentSpec; call heal.apply_fix;
    # return a unified `diff` of before→after (empty + applied=False when unchanged, K7).
```

## `server/store.py` + `server/db.py` — `config_edits` table (E-03)
Store Protocol GAINS (parity over InMemoryStore + SqlStore, tested in
`tests/test_config_edits.py`):
```python
def add_config_edit(repo_id, edit: ConfigEdit, *, edit_id, at) -> None
def config_edits_for(repo_id, status: str | None = None) -> list[StoredConfigEdit]  # insertion order (K10)
def mark_config_edits(repo_id, edit_ids, status, *, at) -> None
```
`db.py` adds `ConfigEditRow` (table `config_edits`): surrogate `id` (K10 order),
indexed `repo_id`/`edit_id`/`status`, `created_at`/`applied_at`, and the FULL
typed edit in a JSON column (additive, K6). `alembic/versions/0004_config_edits_table.py`
(down_revision="0003") creates it on upgrade, drops it on downgrade (up/down
round-trip gate-tested on temp SQLite). `context_refs` is added to the
`ConfigDocument` store model (and surfaced on the `/documents` + editable trees)
and rides inside the existing config_documents JSON column — NO migration.

## `server/app.py` — the editor routes (E-04..E-07)
| Method | Path | Auth | Body | Purpose |
|---|---|---|---|---|
| GET | `/repos/{id}/config/editable?sync_kind=` | open | — | The editable tree: `documents` (with `code_refs` + `context_refs`), `undocumented_files` (in-scope, unlinked), `ignored_files` (closed-tab list, capped), `unit_files` (stems to target), `doc_styles` (selectable category options). |
| POST | `/repos/{id}/config/edits` | token | `ConfigEdit` | Stage one mapping ticket → a `pending` row. Returns `{edit_id}`. |
| GET | `/repos/{id}/config/edits?status=` | open | — | List staged edits. |
| POST | `/repos/{id}/config/generate` | token | `{edit_ids?, now?, mode?}` | Apply pending edits to disk (units + index), scaffold/heal docs, re-run local sync + reproject SQL, mark edits applied. Returns `{applied, sync_run, undocumented_files}`. **409** if the repo has no `local_path`; **400** (loud K8) on a scoped-write failure. |
| POST | `/repos/{id}/records/{record_id}/apply-fix` | token | `{}` | Apply the record's `ProposedFix` to its doc (`apply_record_fix`), append an `accepted` `ResolutionRecord`, re-sync. Returns `{applied, doc_path, diff}`. **409** no `local_path` / no applicable fix; **404** unknown record. |

`_disk_editable_parts(local_path)` computes `(undocumented_files, ignored_files,
unit_files, doc_styles)` by REUSING `effective_coverage` + the report machinery
(`undocumented_files` = the coverage gap; `ignored_files` from the ignore/gitignore
globs, sorted + capped; `unit_files` = the on-disk unit stems via the config glob).
`generate`/`apply-fix` operate on `store.get_repo(id).repo.local_path` and stamp
every persisted row from the injected server `clock` (K10).

## `dashboard/` — the Mapping page + apply-fix (E-08..E-11)
- **Mapping page** (`src/pages/Mapping.tsx`, route `/repos/:repoId/mapping`, in nav):
  scoped to the repo over `GET /config/editable`:
  - **Documents** — each a collapsible row (a dropdown); expanded reveals its
    `code_refs` (path + symbols/lines or "whole file") AND its `context_refs`
    (path + note, visually distinct), with a per-document "Edit mapping" action.
  - **Unlinked source files** — `undocumented_files` as a flat list, each with a
    "Link to a document…" action opening the ticket form.
  - **Ignored files** — a closed-by-default `<details>` tab at the bottom listing
    `ignored_files`.
  - **Mapping-ticket form** (`MappingTicketForm.tsx`) — fields: target document
    (existing id or new id+path+audience), source file, scope (`all` | `start-end`
    | symbols), the four doc-style category dropdowns, and `context_refs` (path +
    note). Submits a `POST /config/edits`; staged edits show as a pending list.
  - **"Generate / make live"** button → `POST /config/generate`; on success
    re-fetches the tree + sync-state so the page reflects the LIVE state.
- **Apply-fix button** — on the drift timeline/ticket card (`src/pages/RepoDetail.tsx`),
  a record with a FIX verdict + a `fix` gains an "Apply fix (LLM)" button →
  `POST /records/{id}/apply-fix`; on success it shows applied + the diff and
  refreshes records. Every component uses the injected-`api?`-prop test pattern;
  Vitest covers each.

## Demo (E-12)
The demo (`demo/`) introduces all of this: `getting-started` carries `context_refs`
(refers to `docs/api/core-api.md` + glances `engine.py`); `scheduler.py` is kept
UNLINKED so the Mapping page lists it under "unlinked" and a reader can link it via
the ticket form + Generate to watch it become documented live. `demo/walkthrough.py`
drives the apply-fix path + the link→generate path end-to-end (offline). `seed_demo.py`,
the demo `core.yaml`/`doc-style.yaml`, the demo README, the demo e2e tests, and the
dogfood config (cdmon's own) all exercise `context_refs`.

## `featurecatalog.py`  (EPIC R — the golden feature catalog loader; pure, stdlib+pydantic+pyyaml only — K0/K1/K10)

The machine-readable golden reference of every cdx *feature*. The catalog
lives in `feature-doc/catalog/*.yaml` (one file per subsystem, mirroring the
`config/cdmon/` multi-file pattern); `feature-doc/FEATURES.md` is RENDERED from
it (never hand-edited — the yaml is the single source of truth). Pure and
deterministic (no clock, sorted output, K10); loud on any malformed input (K8).

```python
# Stable feature-id pattern: FEAT-<SUBSYSTEM>-<NNN>, SUBSYSTEM = [A-Z][A-Z0-9]+, NNN = \d{3}
FEATURE_ID_RE: typing.Final = re.compile(r"^FEAT-[A-Z][A-Z0-9]*-\d{3}$")

class Feature(pydantic.BaseModel):           # frozen=True, extra="forbid"
    id: str                                  # matches FEATURE_ID_RE, globally unique
    title: str                               # one-line human name
    summary: str                             # 1-3 sentence description (the golden prose)
    subsystem: str                           # logical grouping, lowercase (e.g. "extract")
    modules: tuple[str, ...]                  # real custodex modules implementing it (non-empty)
    constraints: tuple[str, ...] = ()         # K-refs upheld (e.g. ("K0", "K3"))
    status: Literal["implemented", "planned", "deprecated"] = "implemented"
    demos: tuple[str, ...] = ()               # demo case ids (filled/checked in R3)
    tests: tuple[str, ...] = ()               # test node-ids / ids (filled/checked in R5)

class FeatureCatalog(pydantic.BaseModel):     # frozen=True
    features: tuple[Feature, ...]             # sorted by id
    def by_id(self, fid: str) -> Feature: ...        # loud KeyError->CatalogError on miss (K8)
    def by_subsystem(self) -> dict[str, tuple[Feature, ...]]: ...   # deterministic grouping

def load_catalog(catalog_dir: Path, *, known_modules: Collection[str] | None = None) -> FeatureCatalog: ...
#   reads *.yaml (sorted), each file = {"features": [ {...}, ... ]}; aggregates.
#   CatalogError (K8) on: malformed yaml, extra/missing key, bad id pattern,
#   DUPLICATE id across files, a module ref not in known_modules (when provided),
#   empty modules. Deterministic: features sorted by id.

def render_features_md(catalog: FeatureCatalog) -> str: ...
#   the human golden ref — grouped by subsystem, sorted, with a per-feature
#   demo/test traceability column. Pure string build (K10); cdmon-managed-region
#   compatible so `cdx wiki` can re-stamp it idempotently (R7).
```

`errors.py` gains `CatalogError(CdmError)` (loud, K8). `known_modules` is sourced
from `inventory`-style discovery so a typo'd module ref fails loud at load. No new
dependency (pydantic+pyyaml already core, K0). This module is the foundation R3
(demos), R5 (test wiki), R6 (source wiki), and R7 (`cdx wiki`) all read from.

## `traceability.py`  (EPIC R, R-03 — feature ⇄ demo/test/source coverage matrix; pure, stdlib+pydantic — K0/K1/K10)

Proves the 1:1 mapping the golden reference promises: every feature has at least
one demo AND at least one test. Reads the catalog (`featurecatalog.load_catalog`)
and scans evidence files for an **inline feature-tag convention** — the single
source of truth lives at the test/demo (no duplication, K-style): a line of the
form `Feature: <id>[, <id>...]` or `Features: <id> ...` (case-insensitive marker)
anywhere in a file (a Python docstring/comment or a Markdown line). A bare mention
of a `FEAT-id` in prose (no `Feature:` marker) is NOT a reference — the marker
disambiguates evidence from description (e.g. the catalog itself names ids).

```python
FEATURE_REF_RE: Final = re.compile(r"\bFEAT-[A-Z][A-Z0-9]*-\d{3}\b")
# a tag line: an optional leading prose, the marker `Feature(s):`, then ids.
_TAG_RE: Final = re.compile(r"(?im)\bFeatures?:\s*(?P<ids>FEAT-[A-Z0-9 ,\-]+)")

class EvidenceKind(str, Enum):  # TEST | DEMO | SOURCE
    ...

class FeatureRef(BaseModel):    # frozen, extra=forbid
    feature_id: str
    path: str                   # repo-relative
    kind: EvidenceKind
    line: int                   # 1-based

class TraceMatrix(BaseModel):   # frozen
    catalog_ids: tuple[str, ...]      # sorted
    refs: tuple[FeatureRef, ...]      # sorted (path, line)
    def tests_for(self, fid: str) -> tuple[str, ...]: ...
    def demos_for(self, fid: str) -> tuple[str, ...]: ...
    def features_without_test(self) -> tuple[str, ...]: ...
    def features_without_demo(self) -> tuple[str, ...]: ...
    def unknown_refs(self) -> tuple[FeatureRef, ...]: ...   # tagged id NOT in catalog (loud gap)
    def is_complete(self) -> bool:   # no missing-test, no missing-demo, no unknown refs

def scan_refs(root: Path, kind: EvidenceKind, *, suffixes=(".py", ".md")) -> list[FeatureRef]: ...
#   walk root (sorted), parse each matching file's `Feature:` tags → refs. Pure, no import (K1).

def build_matrix(catalog: FeatureCatalog, *, tests_root: Path, demo_root: Path,
                 source_root: Path | None = None) -> TraceMatrix: ...
#   scan tests_root (TEST), demo_root (DEMO), optional source_root (SOURCE); combine with catalog ids.

def render_matrix_md(matrix: TraceMatrix) -> str: ...
#   the traceability wiki: per-feature demo/test columns + a gaps section. Pure (K10).
```

`cli.py` gains `cdx trace` (`--json`, `--fail-on-gap`): loads `feature-doc/catalog`,
scans `tests/` + `demo/`, prints the matrix summary; `--fail-on-gap` exits nonzero
if any feature lacks a test or demo, or any unknown ref exists (K8). The catalog's
`Feature.demos`/`tests` slots are an OPTIONAL secondary source (filled by R3/R5);
the inline scan is the primary, drift-free evidence. No new dep (K0).

## `testwiki.py`  (EPIC R, R-06 — the test wiki extractor; pure AST, never imports tests — K0/K1/K10)

Turns the test tree into a navigable wiki WITHOUT a second source of truth: the
test's own docstring is the "what it asserts", its directory is the boundary, and
a `Feature:`/`Features:` tag line (in the test docstring OR inherited from the
module docstring) is the feature link. Parsed with stdlib `ast` — the tests are
NEVER imported or executed (K1) — so the wiki can't drift from the tests.

```python
class TestBoundary(str, Enum):  # UNIT | INTEGRATION | SYSTEM | SMOKE | REGRESSION | UNKNOWN
    ...

class TestCase(BaseModel):      # frozen, extra=forbid
    nodeid: str                 # tests/<boundary>/<file>::<func> (or ::Class::func)
    path: str                   # repo-relative posix
    name: str                   # function name
    boundary: TestBoundary      # from the path
    summary: str                # first line of the test's docstring ("" if none)
    features: tuple[str, ...]   # FEAT-ids from the test docstring + the module's `Features:` tag

class TestModule(BaseModel):    # frozen
    path: str
    boundary: TestBoundary
    module_features: tuple[str, ...]   # the module docstring's `Features:` tag (file-level coverage)
    cases: tuple[TestCase, ...]

def collect_tests(tests_root: Path) -> tuple[TestModule, ...]: ...
#   walk tests_root (sorted), ast.parse each test_*.py, find top-level + class-nested
#   `def test_*`, pull docstrings, resolve boundary from path, gather Feature tags.
#   Pure, deterministic, never imports the file (K1). Loud (CatalogError-style) only
#   on a genuinely unparseable test file (K8) — otherwise robust.

def render_test_wiki_md(modules: tuple[TestModule, ...]) -> str: ...
#   the test wiki: grouped by boundary → module, each case with its summary +
#   feature links; plus a per-feature "tested by" index. Pure (K10).
```

The annotation CONVENTION (R-06): each `tests/.../test_*.py` carries a module-level
`Features: FEAT-…` tag in its module docstring listing the catalog features that
file exercises (file-level coverage — this is what makes the traceability TEST side
complete, `features_without_test == []`). Per-test `Feature:` tags refine where
valuable. The boundary comes from the R-05 directory, not a tag. `cdx wiki` (R-08)
renders `render_test_wiki_md` to disk. No new dependency (K0).

## `srcindex.py`  (EPIC R, R-07 — the source index + source wiki; reuses inventory/coverage — K0/K1/K10)

Indexes every public symbol of `custodex` and ties each module to the
catalog features it implements (the inverse of `Feature.modules`), so the source
wiki and the traceability SOURCE view are complete and provably cover the whole
public surface. Reuses `inventory.discover_files`/`discover_symbols` (no AST
re-impl) and `featurecatalog` — pure, deterministic, no target import beyond the
AST extraction inventory already does (K0/K1/K10).

```python
class ModuleIndex(BaseModel):          # frozen, extra=forbid
    module: str                        # top-level module name (e.g. "extract")
    path: str                          # repo-relative posix
    public_symbols: tuple[str, ...]    # sorted public symbol names (from inventory)
    features: tuple[str, ...]          # catalog feature ids whose `modules` include this module

class SourceIndex(BaseModel):          # frozen
    modules: tuple[ModuleIndex, ...]   # sorted by module
    def features_without_module_match(self) -> tuple[str, ...]:  # catalog features naming a missing module (should be empty)
    def modules_without_feature(self) -> tuple[str, ...]:        # public modules with NO catalog feature (a documentation gap)

def build_source_index(pkg_root: Path, catalog: FeatureCatalog) -> SourceIndex: ...
#   inventory the package, attach public symbols per module, join to catalog by module name.

def render_source_wiki_md(index: SourceIndex) -> str: ...
#   per-module: path, public symbols, implementing features (links); + a coverage
#   summary (modules with no feature). Pure (K10).
```

`cdx wiki` (R-08) renders this to `feature-doc/wiki/SOURCE_WIKI.md`. The
`modules_without_feature` accessor is the deferred R-02 "no orphan public
capability" check, now realizable: a public module with zero catalog features is a
golden-reference gap, reported (and optionally gated). No new dependency (K0).

## `cdx wiki` + `cdx trace` gate  (EPIC R, R-08 — regenerate all wikis from the single sources; CI freshness + traceability gate)

`cli.py` gains `cdx wiki` — the single regeneration entry point that renders ALL
of EPIC R's derived artifacts from their sources (the catalog yaml + the tests'
docstrings + the source AST), to a canonical set of paths:

```
feature-doc/FEATURES.md          ← featurecatalog.render_features_md(load_catalog)
feature-doc/wiki/TEST_WIKI.md    ← testwiki.render_test_wiki_md(collect_tests(tests))
feature-doc/wiki/SOURCE_WIKI.md  ← srcindex.render_source_wiki_md(build_source_index)
feature-doc/wiki/TRACEABILITY.md ← traceability.render_matrix_md(build_matrix)
```

- `cdx wiki` writes all four (idempotent — a second run is a no-op, K7;
  deterministic content, K10) and echoes each path + whether it changed.
- `cdx wiki --check` renders in memory and compares to disk; exits 0 when all
  fresh, nonzero listing every stale file when not (K8) — the CI freshness gate.
  No write on `--check`.
- A shared `WIKI_TARGETS` mapping (path → render thunk) is the single source of the
  output set so `wiki` and `wiki --check` can never diverge.

The `cdx trace --fail-on-gap` command (R-03), now that the matrix is complete,
becomes a CI gate: a new demo/feature without a test (or vice-versa) fails CI. Both
`cdx wiki --check` and `cdx trace --fail-on-gap` are added to `.gitlab-ci.yml`
(offline, no network — K4). No new dependency (K0). This closes EPIC R: the golden
reference, its demo/test 1:1 mappings, and the source/test wikis all regenerate
from one source each and are gated against drift — cdmon's own discipline applied
to cdmon's own documentation.

## `GET /wiki` + dashboard Wiki page  (EPIC R, R-09 — the wikis in the console)

Surfaces the EPIC-R wikis inside the dashboard. The server gains a GLOBAL, public
(no-auth, like `/config/templates`) read that serves the committed wikis rendered
to HTML by the engine's OWN dependency-free renderer (`build.render_markdown`,
FEAT-LAYOUT-008 — no new dep, K0):

```python
# server/app.py
def create_app(store=None, *, static_dir=None, wiki_dir: Path | None = None, clock=...): ...
#   wiki_dir defaults (None) to _wiki_dir() = <repo root>/feature-doc (mirrors _spa_dir()).

WIKI_SECTIONS = (   # (id, title, repo-relative path under feature-doc/) — deterministic order
    ("features",     "Feature Reference",   "FEATURES.md"),
    ("traceability", "Traceability Matrix", "wiki/TRACEABILITY.md"),
    ("tests",        "Test Wiki",           "wiki/TEST_WIKI.md"),
    ("source",       "Source Wiki",         "wiki/SOURCE_WIKI.md"),
)

@app.get("/wiki")
def wiki() -> dict:
    """Public: the EPIC-R wikis rendered to HTML. {"sections":[{"id","title","html"}...]}.
    Missing dir/file → that section omitted (graceful empty for a non-cdx repo). K10 pure."""
```

Frontend (`dashboard/`):
- **Nav (always visible):** AppShell adds a `Wiki` item under the **Reference** group
  → `<Link to="/wiki">`; `pageLabel("/wiki")` = "Wiki". This is the "show Wiki first".
- **Lazy switch on click:** `App.tsx` routes `/wiki` to a `React.lazy(() => import("./pages/Wiki"))`
  page inside `<Suspense>`, so the wiki bundle + its fetch fire ONLY when Wiki is
  clicked ("only when clicked does it switch to the full wiki frontend").
- **`pages/Wiki.tsx`** (the full wiki frontend): on mount fetches `api.wiki()`, then
  renders a docs layout — a left **section rail** (Feature Reference / Traceability /
  Test Wiki / Source Wiki, the selected one active, with a per-section count badge) +
  a readable **prose pane** rendering the selected section's HTML. Loading / error /
  empty states; injectable `api?` prop (no network in tests). `api/client.ts` gains
  `wiki(): Promise<{sections: {id,title,html}[]}>` (GET /wiki); `types.ts` gains
  `WikiSection`/`WikiPayload`.

`featurecatalog`: add **FEAT-SERVER-019** "Feature-wiki endpoint" (subsystem server,
modules [server]) so the golden reference stays correct; tag it on the server test +
a demo case so `cdx trace` stays complete. After the endpoint lands, `cdx wiki`
is re-run (FEATURES/SOURCE/TEST wikis pick up the new feature) and the server api doc
is rehealed. No new dependency anywhere (K0); the dashboard adds no npm package.


## `frontend/` Astro application  (EPIC ASTRO — one Astro app: native docs/wiki + console as React islands)

Replaces the scattered HTML surfaces (hand-rolled `build.render_markdown` → React
`dangerouslySetInnerHTML` for the wiki; a separate Vite SPA) with ONE Astro app under
`frontend/`. Astro is a **frontend-only** toolchain — it never touches the Python
engine, so K0 (engine core deps) is untouched; the engine never imports it.

**Two surfaces, one app:**
- **Content (Astro-native, static):** the EPIC-R wikis (`feature-doc/FEATURES.md`,
  `wiki/{TRACEABILITY,TEST_WIKI,SOURCE_WIKI}.md`) become Astro pages under `/wiki/*`,
  rendered by Astro's own markdown pipeline at build time — **retiring**
  `render_markdown`'s frontend role and the `GET /wiki` JSON + the React `Wiki.tsx`
  island (R-09). Syntax highlighting / TOC / nav come free from Astro.
- **App (React islands):** the existing tested console — `api/client.ts`, `types.ts`,
  the 8 pages, `AppShell` — is **ported verbatim** into `frontend/src/` and mounted as
  a single `client:only="react"` island on the index page, keeping its **HashRouter**
  (so client routes stay `#/repos` and never shadow API paths). The 15 Vitest suites
  move with it. No component logic is rewritten — only the build/host changes.

**`astro.config.mjs`:** `integrations: [react(), mdx()]`, `output: 'static'`,
`build.assets: '_astro'` (Astro's default). `npm run build` = `astro check && astro
build` → `frontend/dist/` (`index.html`, `wiki/**/index.html`, `_astro/*`).

**Serving (the one real integration point — `server/app.py`):** the per-`/assets`
mount + `@app.get("/")`→`FileResponse(index.html)` is replaced by a single
catch-all **mounted LAST**, after every API route, so the API always wins and any
unclaimed path falls through to the static site (Starlette matches routes in
declaration order):
```python
# after ALL @app.get/@app.post routes:
if static_dir is not None and (Path(static_dir) / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="site")
#   html=True → "/" serves index.html (the console island) and "/wiki/" serves
#   wiki/index.html (native Astro). "_astro/*" assets served verbatim.
```
`_default_static_dir()` → `<repo>/frontend/dist` (a `dashboard/dist` fallback kept
only through F-03 so the server never breaks mid-migration; dropped in F-04).
**Collision rule:** native Astro page paths MUST avoid the API's real paths —
`/health`, `/repos*`, `/config*`, `/sync*`, `/openapi.json`, `/docs` (Swagger). The
JSON `/wiki` is **retired**, freeing `/wiki/*` for the native pages.

**API base:** prod is single-origin (the server serves both), so the island client's
base stays `""` (same-origin root) — Astro exposes it as `import.meta.env.PUBLIC_API_BASE`
(replacing `VITE_API_BASE`); unset → `/api` for the `astro dev` proxy case.

**Dogfood (catalog stays correct):** `GET /wiki` is retired, so **FEAT-SERVER-019**
is removed/superseded and new **FEAT-FRONTEND-0NN** features (Astro app shell, native
wiki pages, console islands, single-origin serving) are added to the catalog with
their demo + test tags; `cdx wiki` is re-run and `cdx trace --fail-on-gap` stays
green. `frontend/` is a frontend artifact (like `dashboard/` was) — outside the Python
coverage surface; `frontend/{node_modules,dist}` are gitignored.

**Slices:** **ASTRO-01** Astro foundation + the serving rewire (build + served
in-process, gate green). **ASTRO-02** native Astro docs/wiki under `/wiki/*`, retire
`GET /wiki` + `render_markdown` frontend use. **ASTRO-03** port the console
pages/components/client + the 15 Vitest suites as the index island. **ASTRO-04**
delete `dashboard/`, rewire `.gitlab-ci.yml` (frontend build/test) + packaging,
dogfood reheal, full gate.


## EPIC GIT — server-side git sync & provider credentials  (STEP 0 + PHASE 1 + PHASE 2)

The central server can today only sync a repo that is ALREADY on its disk
(`configsync.run_sync(local_path, …)`); there is **no clone/fetch anywhere**, and
the only PR write path is `GitLabTransport`. EPIC GIT closes both gaps so the
server can sync **and** open docs-PRs against a GitHub/GitLab repo it does NOT
hold locally, authenticating with a per-repo credential. Three layers, each
additive (K6) and reusing the prior's seams:

* **STEP 0 — clone-on-demand (`gitfetch.py`).** Materialize a remote repo into a
  throwaway temp tree, then run the UNCHANGED `run_sync` over it (`mode="local"`,
  the clone is checked out at the default branch). `configsync.py` is NOT touched
  (K9). The git side effect is one injected subprocess leaf (K4); teardown +
  token shred in `finally` (K1).
* **PHASE 1 — per-repo scoped token.** A provider PAT/project-token, **sealed at
  rest** (AES-GCM, `secrets.py`) — the conscious fork from the hash-only token
  model (a git credential must be REPLAYED, so it cannot be hashed). It drives
  clone + a new `GitHubTransport` + a `POST /repos/{id}/docs-pr` route.
* **PHASE 2 — GitHub App / GitLab OAuth (`gitauth.py`).** Mint a SHORT-LIVED token
  from a stored App/OAuth credential; the hot token is never persisted (recovers
  most of the at-rest invariant Phase 1 weakened). Reuses Phase 1's `RemoteSpec`
  + clone seam + transports verbatim — only the credential SOURCE changes. GitHub
  App JWT needs **RS256 (stdlib cannot do it)** → `cryptography` (the one K0
  asterisk, confined to the `[server]` extra).

### `gitfetch.py`  (STEP 0 — clone-on-demand; stdlib subprocess behind one injected leaf — K0/K1/K4/K8)

```python
class RemoteSpec(BaseModel):          # frozen, extra=forbid
    remote_url: str                   # https://github.com/owner/repo(.git) | https://gitlab.com/group/proj(.git)
    provider: Literal["github", "gitlab"]
    default_branch: str = "main"

class _Cloner(Protocol):              # the ONE network leaf (K4)
    # clone spec.remote_url@default_branch into dest, authenticating with `secret`
    # WITHOUT putting it in argv or the URL (GIT_ASKPASS env + a username-only URL).
    def clone(self, spec: RemoteSpec, secret: str | None, dest: Path) -> None: ...

class _GitCloner:                     # real leaf; subprocess.run(["git","clone","--depth=1","--branch",b,url,dest], env=…)
    def clone(self, spec, secret, dest) -> None: ...   # token never in argv; file:// path covered, https+token leaf is the pragma

@contextmanager
def cloned_repo(spec: RemoteSpec, secret: str | None, *, cloner: _Cloner | None = None) -> Iterator[Path]:
    # mkdtemp("cdmon-fetch-") → cloner.clone(...) → yield <tmp>/repo → finally rmtree + best-effort secret shred (K1).
    # A clone failure is a loud SyncError with the secret SCRUBBED from stderr (K8).
```
The server route does `with cloned_repo(spec, secret) as tree: run_sync(tree, repo_id, mode="local", default_branch=spec.default_branch, now=now)`. Tests inject a fake `cloner` (copies a fixture tree) for orchestration/teardown/token-not-in-argv, plus a REAL `file://` clone system test that exercises `_GitCloner` with no network (EDR-safe). `_build_clone_argv(spec, dest) -> list[str]` is a pure helper unit-tested to prove the secret is absent from argv.

### `secrets.py`  (PHASE 1 — at-rest secret sealing; `cryptography` in the `[server]` extra ONLY — the one K0 asterisk)

```python
class SecretError(CodeDocMonitorError): ...   # errors.py — loud on a missing/short KEK or a tampered ciphertext (K8)

class SecretBox:                      # AES-256-GCM (cryptography.hazmat AESGCM)
    def __init__(self, key: bytes) -> None: ...        # key MUST be 32 bytes (loud SecretError otherwise)
    def seal(self, plaintext: str) -> bytes: ...       # 12-byte random nonce ‖ ciphertext+tag; returns opaque bytes
    def open_secret(self, sealed: bytes) -> str: ...   # splits nonce, decrypts; tampered/short → SecretError

def secret_box_from_env(env: str = "CDMON_SECRET_KEY") -> SecretBox:
    # reads a base64 32-byte KEK from $CDMON_SECRET_KEY; loud SecretError if unset/short/not base64.
```
Engine core never imports `secrets.py` (it lives behind the `[server]` extra; only `app.py`/tests import it), so the core dependency surface is unchanged (K0). The KEK is a single env-provided key (no KMS) — sufficient for single-org self-hosting; rotation is a manual re-encrypt (LESSON).

### identity + payload additive fields  (PHASE 1, K6 — appended LAST so field order is untouched)

* `sinks.RepoIdentity` (+2, both default `None`): `provider: Literal["github","gitlab"] | None`, `remote_url: str | None`. (The existing `repo_url` stays the inert *browse* URL — `remote_url` is the *clone/API* URL; the distinction is documented on the field.) These ride INSIDE the `RepoRow.payload` JSON → **no DB migration** (K6 additive round-trip).
* `registry.RegistrationPayload` (+1, default `None`): `provider_secret: str | None` — a WRITE-ONLY plaintext credential the client mints at register, exactly mirroring `auth_token`. The server SEALS it (never stores plaintext); it is excluded from the stored payload JSON.

### Store provider-secret seam  (PHASE 1 — `server/store.py` Protocol + `InMemoryStore` + `server/db.py` `SqlStore`)

```python
# store.Store (Protocol) gains — parallel to repo_token_hash:
def set_provider_secret(self, repo_id: str, sealed: bytes) -> None: ...   # persist OPAQUE sealed bytes
def repo_provider_secret(self, repo_id: str) -> bytes | None: ...         # the sealed bytes, or None (open/unknown)
```
Sealing happens at the ROUTE (`app.py`, the crypto-allowed `[server]` layer); the store persists opaque bytes and **never imports `cryptography`** (keeps `store.py` pure pydantic/stdlib). `db.RepoRow` gains `provider_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)` (BYTEA/​BLOB), and `SqlStore.add_repo` extends the sanitize to `exclude={"auth_token", "provider_secret"}`. **Alembic `0005_repo_provider_secret`** (`down_revision="0004_config_edits"`) adds the one nullable column via `op.add_column` in batch mode (SQLite + Postgres); up/down round-trip gate-tested on temp SQLite.

### `pr.py` GitHubTransport  (PHASE 1 — sibling to GitLabTransport; stdlib urllib behind one injected leaf — K0/K4)

```python
class _GitHubHttp(Protocol):
    def request(self, method: str, url: str, *, body: dict | None, token: str) -> dict: ...
class _UrllibGitHubHttp:              # Authorization: Bearer <token>; Accept: application/vnd.github+json (real urlopen = pragma)
    ...
class GitHubTransport:                # submit(plan) does the ATOMIC git-data flow (no local checkout):
    # 1) GET   /repos/{o}/{r}/git/ref/heads/{target}            → base commit sha
    # 2) GET   /repos/{o}/{r}/git/commits/{base}                → base tree sha
    # 3) POST  /repos/{o}/{r}/git/trees {base_tree, tree:[{path,mode:100644,type:blob,content}]}  → new tree sha
    # 4) POST  /repos/{o}/{r}/git/commits {message, tree, parents:[base]}                          → new commit sha
    # 5) POST  /repos/{o}/{r}/git/refs {ref:"refs/heads/<source>", sha:new}                        → branch
    # 6) POST  /repos/{o}/{r}/pulls {title, head:<source>, base:<target>, body}                    → PR  (returns its JSON)
    def __init__(self, *, owner: str, repo: str, token: str, api_url: str = "https://api.github.com", http: _GitHubHttp | None = None): ...
    @classmethod
    def from_env(cls, *, repo_env="GITHUB_REPOSITORY", token_env="CDMON_GITHUB_TOKEN", api_env="GITHUB_API_URL"): ...
    @classmethod
    def from_repo(cls, remote_url: str, token: str, *, api_url: str | None = None) -> GitHubTransport: ...  # parse owner/repo from URL
```
`GitLabTransport.from_repo(remote_url, token, *, api_url=None)` is the symmetric classmethod (parse the project path → URL-encoded `project_id`). A shared `pr._parse_remote(remote_url) -> (host, owner, repo)` does the parsing (loud `TransportError` on a non-provider URL → SSRF allowlist hook).

### server routes  (PHASE 1 — `server/app.py`, ENV knobs only; no `config/cdmon/server.yaml` edit)

* **`POST /repos/{id}/sync`** — when the stored identity has NO `local_path` but DOES carry `provider` + `remote_url` AND a sealed `provider_secret` exists, the route opens the secret (`secret_box_from_env`), `cloned_repo(RemoteSpec(...), token)`s, and `run_sync`s the clone (`mode="local"`); otherwise the existing local-path path is unchanged. SSRF: `remote_url` host must be on the provider allowlist.
* **`POST /repos/{id}/docs-pr`** — NEW, token-gated by the existing `_verify_token` (E-06). Clones, `syncpr.sync_pr` heals → `plan_docs_pr`, builds `{GitHub,GitLab}Transport.from_repo(remote_url, token)` by `provider`, `open_docs_pr(...)`; `?dry_run=true` returns the plan without a provider call. Returns the MR/PR response (or `null` when nothing healed). The token is scrubbed from any error surface.

### `gitauth.py`  (PHASE 2 — mint short-lived App/OAuth tokens behind one injected leaf — `cryptography` RS256)

```python
class _TokenExchangeHttp(Protocol):
    def request(self, method: str, url: str, *, body: dict | None, headers: dict[str, str]) -> dict: ...
def github_app_jwt(app_id: str, private_key_pem: str, *, now: int) -> str: ...        # RS256 JWT (cryptography), iat/exp from injected `now` (K10)
def mint_github_installation_token(app_id, private_key_pem, installation_id, *, now, http=None) -> str: ...
def mint_gitlab_oauth_token(...) -> str: ...
# transports gain `from_credential(remote_url, credential, *, now, http=None)` alongside from_repo;
# routes resolve a MINTED token when the repo carries provider + installation_id (no stored provider_secret needed).
```
`RepoIdentity` gains additive `installation_id: str | None = None` (and the App credential — app_id + the PEM — is the SAME sealed-secret column, distinguished by a `provider_kind`). Only the credential SOURCE differs from Phase 1; `RemoteSpec`/`cloned_repo`/`GitHubTransport`/`GitLabTransport`/the routes are reused verbatim. Air-gapped GHE/GitLab falls back to SSH here (only if a concrete adopter needs it).

**Slices:** **GIT-00** clone-on-demand (`gitfetch.py`). **GIT-01** `secrets.py` AES-GCM + `SecretError`. **GIT-02** identity/payload fields + Store provider-secret seam + Alembic 0005. **GIT-03** `GitHubTransport` + `from_repo` on both transports. **GIT-04** remote `/sync` + `POST /docs-pr` route. **GIT-05** `gitauth.py` App/OAuth token exchange + `from_credential`. Each: TDD red-first, green gate (ruff+mypy+pytest ≥90% branch), Store-parity over InMemoryStore AND SqlStore where the store is touched, dogfood reheal, STATUS row + LESSON.

## EPIC TDOC — test→test-doc mirror  (FEAT-CONFIGV2-017; a CONFIG CONVENTION, no engine code)

The mirror that syncs **tests → test-docs** the way source syncs to docs. The
governing finding: the engine is already **generic over any `.py` file** — a test
file is just a `.py` file, so `extract.build_document_surface`, `drift.detect`,
`heal.regenerate_regions`, and `coverage.resolve_coverage` work on test files with
**zero new code (K0)**. The mirror is therefore a *config convention* + a frontend
partition, NOT a new module or signature.

**The convention.** A `tests.yaml` unit (peer of `core.yaml`/`server.yaml`) whose
`dir-covered` names a test directory and whose `DocumentSpec`s point `code_refs` at
test files, with the documents living under a top-level **`test-docs/`** directory
and carrying a managed `symbols` region. The region then lists the test file's
`test_*` functions; editing a test drifts the test-doc; `cdx monitor --apply`
heals it (K7). The test file is the source of truth, the test-doc is graded against
it (K2). 1:1: one test-doc per test file. Scoped to keep coverage bounded — the
dogfood covers only `tests/smoke`; the demo covers all of `demo/tests/`.

**`api-index` interaction.** Test-docs are `eng-guide`, so the eng-only `api-index`
lists them — consistent with its rule (it lists every `eng-guide` doc; the README
is excluded only because it is `user-guide`, FEAT-CONFIGV2-016). The user-facing
*separation* is the frontend section, not the index.

**Frontend (`frontend/src/console/lib/grouping.ts`).** Two additive pure helpers,
parallel to `isReadmePath`/`partitionReadme`:
```ts
export function isTestDocPath(path: string): boolean;  // first segment === "test-docs"
export function partitionDocs<T>(items, pathOf): { main: T[]; readme: T[]; tests: T[] };
```
The Documents / RepoDetail(Drift) / Mapping pages call `partitionDocs` and render a
third **"Test docs"** section (after the README section) using the same row
renderers. No new API/route/store/schema surface — test-docs flow through the
existing document endpoints, distinguished purely by path.

**Slices:** **TDOC-01** convention + dogfood (`tests/smoke`) + the engine-contract
test (`test_testdoc_mirror.py`). **TDOC-02** demo 1:1 (`demo/tests` → 4 test-docs)
+ the count-pin ripple. **TDOC-03** `FEAT-CONFIGV2-017` + DEMO-058 + trace 199/199
+ wikis. **TDOC-04** the frontend Test docs section. Each: TDD red-first, full gate
green (ruff+mypy+pytest ≥90% branch + dogfood/demo `cdx` gates + `astro check`),
STATUS row + LESSON.

## EPIC OWN — ownership & accountability (`ownership.py` + roster mirror + reassignment — K0/K1/K2/K4/K5/K6/K10)

Pegs a *human (or team)* to every monitored document, so a code→doc drift always
has an accountable owner — and so a person leaving can never silently leave a
document ownerless. Two tiers, mirroring the existing `disk = truth, SQL = mirror`
split (the EDITOR contract): ownership-of-record lives **per-repo in config**; the
central server roster is a **mirror** that flags departed owners.

**Tier 1 — ownership-of-record (per-repo config, the SOURCE OF TRUTH).** Ownership
is config, never inferred from code — this is the K0 "knowledge enters through
config" door, NOT a K2 inversion (see CONSTRAINTS K2). `DocumentSpec` gains three
optional, additive fields (K6); a whole-unit default owner already exists at the
unit level (`UnitFrontmatter.owner`):
```python
class DocumentSpec(BaseModel):
    ...
    owner: str | None = None   # canonical owner identity (a person OR a team handle)
    team: str | None = None    # durable group accountability (survives a person leaving)
    dri: str | None = None     # current Directly-Responsible-Individual (vacatable)
```
Resolution (pure): a document's *accountable* identity = `dri or owner or team`;
its *durable* owner = `team or owner`; doc-level falls back to the unit `owner`
when all three are unset. Serialized by `_document_to_yaml` after `nav_label`,
before `region_keys` (defaults dropped — idempotent round-trip, K7). Code-ref-level
ownership is intentionally deferred: a code_ref's accountable human is its
document's owner (cdx already maps code → doc, so code → doc → human is closed
without new per-ref fields).

**`ownership.py` (NEW core module — pure, stdlib + pydantic only, K0/K1/K10).** No
new dependency; no network; no clock in the pure core.
```python
class Identity(BaseModel):            # one roster entry (person or team)
    name: str
    display_name: str | None = None
    kind: Literal["person", "team"] = "person"
    email: str | None = None
    active: bool = True
    departed_at: str | None = None    # injected ISO ts (K10), set when marked departed
    teams: tuple[str, ...] = ()        # teams a person belongs to

class RosterSnapshot(BaseModel):      # immutable view of the central roster
    identities: tuple[Identity, ...] = ()
    def get(self, name: str) -> Identity | None: ...
    def is_active(self, name: str | None) -> bool: ...   # None / unknown => False

class EffectiveOwner(BaseModel):      # resolved ownership for one document
    doc_id: str; doc_path: str; audience: Audience
    owner: str | None; team: str | None; dri: str | None
    accountable: str | None           # dri → owner → team → inherited unit owner
    durable: str | None               # team → owner → inherited
    # the inherited unit-owner fallback enters via resolve_ownership's `unit_owner`
    # Mapping param — it is NOT a field on this model

class OwnershipStatus(str, Enum):
    OK = "ok"
    UNOWNED = "unowned"                               # no owner/team/dri anywhere
    ORPHAN_OWNER_DEPARTED = "orphan_owner_departed"   # accountable inactive, no active fallback
    ORPHAN_DRI_VACANT = "orphan_dri_vacant"           # dri inactive but durable owner active (soft)

class OwnershipFinding(BaseModel):
    doc_id: str; doc_path: str; audience: Audience
    status: OwnershipStatus; detail: str
    accountable: str | None; owner: str | None; team: str | None; dri: str | None

def resolve_ownership(config: MonitorConfig, *, unit_owner: Mapping[str, str] | None = None) -> tuple[EffectiveOwner, ...]:
    ...  # pure; unit_owner maps doc_id -> unit frontmatter owner (the fallback); sorted by doc_id (K10)

def detect_orphans(owners: Sequence[EffectiveOwner], roster: RosterSnapshot) -> tuple[OwnershipFinding, ...]:
    ...  # pure, deterministic, NO clock. unowned => UNOWNED; accountable inactive with no active
         # durable fallback => ORPHAN_OWNER_DEPARTED; dri inactive but durable active => ORPHAN_DRI_VACANT.
```
Staleness/SLA (a doc not re-reviewed within N days) shares this module's seam but
is DEFERRED — it needs a per-doc `last_reviewed` the schema does not yet carry;
`detect_orphans` is the clock-free half, a future `detect_stale(owners,
last_reviewed, *, now, sla_days)` is the injected-clock half.

**CLI — `cdx ownership` (read-only, K1).**
```
cdx ownership [--config DIR] [--roster roster.yaml] [--json] [--fail-on-orphan]
```
Loads the config bundle, optionally an OFFLINE roster YAML (`identities: [...]`),
resolves ownership, runs `detect_orphans`, prints a per-doc owner table + findings;
`--fail-on-orphan` exits 1 on any orphan (a CI/accountability gate); with no roster
it just lists assignments. Pure + offline (K4); no backend, no network.

**EDITOR — reassignment (`ReassignOwnerEdit`, config = truth).** A new discriminated
`ConfigEdit` variant drives the disk rewrite that reassigns a departed person's
documents:
```python
class ReassignOwnerEdit(BaseModel):
    action: Literal["reassign_owner"]
    unit: str; doc_id: str
    owner: str | None = None; team: str | None = None; dri: str | None = None
```
applied by a pure editor `config.set_document_owner(unit, doc_id, *, owner, team,
dri) -> UnitFile` (returns a NEW frozen `UnitFile`, B-02 immutability), dispatched
in `generate._apply_unit_edit`; the existing `apply_edits_to_disk` → `run_sync`
flow rewrites `config/cdmon/*.yaml` then re-mirrors (no route change).

**Server — the central roster MIRROR (`[server]` extra; offline SQLite twin + `pg`).**
Marking a person departed once cascades orphan detection across every repo.
- migration `0006_roster_and_ownership.py`: creates ONLY the `roster` table
  (identity blob + indexed `name`/`kind`/`active`). DESIGN REFINEMENT vs the OWN-04
  pin: there is NO separate `ownership_mirror` table — the resolved owner/team/dri +
  accountable/durable ride in the EXISTING `config_documents` JSON column (additive,
  K6; no column migration).
- `db.py`: `RosterRow`.
- `store.py`: `ConfigDocument` gains additive `owner`/`team`/`dri` +
  `accountable`/`durable`; new Store Protocol methods (implemented in BOTH
  `InMemoryStore` and `SqlStore`, parity): `upsert_identity(identity)`,
  `list_roster() -> list[Identity]`, `mark_identity_departed(name, *, at)`.
- `configsync._build_rows`: resolves accountable/durable via the shared
  `resolve_accountable_durable` and projects owner/team/dri/accountable/durable into
  `ConfigDocument`'s existing JSON (no new table, no extra route).
- `app.py` routes: `POST /admin/roster` (admin token, upsert identity);
  `POST /admin/roster/{name}/departed` (admin token, mark departed = active=False,
  departed_at=now); `GET /roster` (open, list); `GET /repos/{repo_id}/ownership`
  (open, computed view = the synced docs' resolved owners +
  `detect_orphans(owners, roster)` against the LIVE roster at READ time — so a
  departure re-flags every repo with no re-sync). Admin auth is a SEPARATE global
  token (the `admin_token` param / `$CDMON_ADMIN_TOKEN`), hashed ONCE with
  `hash_token` into a `create_app` closure (`admin_hash`; None ⇒ routes open) and
  checked by `_verify_admin` (constant-time `hmac.compare_digest`) — NOT a per-repo
  token, and never persisted on the Store. With no admin token AND a persistent
  (DB-backed) store, `create_app` logs a loud warning that the GLOBAL routes are
  unprotected.

**Frontend — Ownership page.** `GET /repos/:repoId/ownership` → a new
`pages/Ownership.tsx` (sibling to Documents/Coverage), a `RepoNav` entry, and
`OwnershipData`/`OwnershipOwner`/`OwnershipFinding` types; a per-doc table
(Document/Accountable/Team/DRI/Status) with status dots, an orphan banner, and a
struck-through "departed" badge on an orphaned accountable owner. `astro check` +
`astro build` gate.

**Demo (shows it working).** `demo/config/cdmon/*` docs carry real owners; a
`seed_demo.py` roster seeds a team + people with ONE marked departed, so the live
:33333 Ownership page shows a real orphan; `demo_as_git` carries the owners in the
committed config; e2e asserts ownership renders and a departure produces an orphan.

**Feature catalog — new `ownership` subsystem.** `feature-doc/catalog/ownership.yaml`
(20th subsystem), FEAT-OWNERSHIP-001…, each traced 1:1 to a `demo/DEMOS.md` case
and a tagged test (`cdx trace --fail-on-gap` / `cdx wiki --check` stay green).

**Slices:** **OWN-00** pin + plan (this) · **OWN-01** config fields + `resolve_ownership`
· **OWN-02** `detect_orphans` · **OWN-03** `cdx ownership` CLI · **OWN-04** server
roster + mirror + migration 0006 + admin token + routes (store parity, `pg` twin) ·
**OWN-05** `ReassignOwnerEdit` reassignment · **OWN-06** demo seeding + Ownership page
+ e2e. Each: TDD red-first, full gate green (ruff+mypy+pytest ≥90% branch + dogfood
reheal + `cdx trace`/`wiki --check` + `astro check`), STATUS row + LESSON.

## EPIC SVR — central-server hardening + operator settings

Extract every hardcoded RUNTIME tunable into one versioned file, wire the missing
hardening middleware from it, and expose it read-only in the CLI + console. Secrets
stay in the environment; the file holds only non-secret knobs (their PRESENCE is the
only thing ever surfaced). Every default reproduces today's behavior (back-compat, K6).

**Core model — `custodex/settings.py` (pydantic + pyyaml only ⇒ CORE, K0).**
```python
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)
DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")

class CorsSettings(BaseModel):        # empty allow_origins ⇒ CORS middleware OFF (today)
    allow_origins: tuple[str,...] = (); allow_credentials: bool = False
    allow_methods: tuple[str,...] = ("*",); allow_headers: tuple[str,...] = ("*",)
class RateLimitSettings(BaseModel):   # None ⇒ no limit (today); per-process fixed window
    requests_per_minute: int | None = None
class GitSettings(BaseModel):         # the SSRF allowlist + clone hardening
    allowed_hosts: tuple[str,...] = ("github.com","gitlab.com")
    extra_allowed_hosts: tuple[str,...] = ()   # $CDMON_ALLOWED_GIT_HOSTS overlays here
    allow_file_scheme: bool = True; clone_timeout_seconds: int | None = None
class ServerSettings(BaseModel):
    host: str = "0.0.0.0"; port: int = 33333; log_level: str = "info"
    trusted_hosts: tuple[str,...] = ("*",)     # ["*"] ⇒ TrustedHost OFF (today)
    cors: CorsSettings = ...; rate_limit: RateLimitSettings = ...; git: GitSettings = ...
class Settings(BaseModel):
    version: str = "1.0.0"; server: ServerSettings = ...

def load_settings(path: Path) -> Settings: ...        # loud ConfigError (K8), yaml-only
def settings_from_env(base, env=None) -> Settings: ...  # env wins; injectable env (K10)
def resolve_settings(path=DEFAULT_SETTINGS_PATH, env=None) -> Settings: ...  # file→env→default
def secret_presence(env=None) -> dict[str,bool]: ...  # admin_token_configured/database_url_set/secret_key_set
```
Precedence: **CLI flag > env (`CDMON_SERVER_*`, `CDMON_TRUSTED_HOSTS`, `CDMON_CORS_ORIGINS`,
`CDMON_RATE_LIMIT_RPM`, `CDMON_ALLOWED_GIT_HOSTS`, `CDMON_GIT_CLONE_TIMEOUT`) > file > default.**
Secrets (`CDMON_ADMIN_TOKEN`/`CDMON_DATABASE_URL`/`CDMON_SECRET_KEY`) are NOT modelled — the
server resolves them directly; only presence is reported (K8 no-leak).

**Server wiring (`server/app.py`).** `create_app(..., settings: Settings | None = None)`
(resolve via `resolve_settings()` when None); right after `app = FastAPI(...)` add
`CORSMiddleware` (only if `cors.allow_origins`), `TrustedHostMiddleware` (allowed_hosts =
`trusted_hosts`), and a dependency-free per-process fixed-window rate-limit middleware (only
if `rate_limit.requests_per_minute`; clock-injected, K10; per-worker caveat documented). `git.*`
feeds `_check_remote_allowed`; `clone_timeout_seconds` threads to `gitfetch` `subprocess.run(timeout=)`.
New OPEN read `GET /settings` → `{settings: <Settings dump>, secrets: <presence>}` (defined BEFORE
the SPA catch-all mount). The CENTRAL server `main()` reads host/port/log_level from settings;
`cdx serve` keeps its own localhost dev defaults (127.0.0.1:0, `--host/--port` override). App
version de-duped via `importlib.metadata`.

**CLI — `cdx settings [--settings PATH] [--json]`** (read-only, K1/K4): prints the effective
resolved settings + secret presence; loud ConfigError → exit 1. Mirrors `schema`/`ownership`.

**Frontend — global Settings page** (mirrors `/config`, NOT per-repo): `pages/Settings.tsx`,
`GET /settings` via `apiClient.serverSettings()`, `ServerSettings` type, a `GearIcon` + a
"Settings" entry in `AppShell` Console nav, `/settings` route in `App.tsx`. `astro check`/vitest.

**Deploy — `Dockerfile` (node build stage → frontend/dist; python slim + `[server]` extra; CMD
`cdx-server`), `.dockerignore`, `docker-compose.yml` (server + postgres, `CDMON_DATABASE_URL`),
`DEPLOY.md` runbook** (TLS/reverse-proxy, the settings knobs, the rate-limit per-worker caveat).

**Slices:** **SVR-00** pin (this) · **SVR-01** `settings.py` + `config/settings.yaml` + loader/env ·
**SVR-02** middleware + host/port/log_level + git timeout/allowlist wiring · **SVR-03** `GET /settings`
+ `cdx settings` · **SVR-04** console Settings page · **SVR-05** Docker/compose/DEPLOY · **SVR-06**
demo + final gate. New `settings` catalog subsystem grown in lockstep; each slice TDD + full gate green.

## EPIC SLA — time-based staleness / review SLA

The time-based half of accountability (EPIC OWN was the departure-based half): a doc
not re-reviewed within its SLA is flagged so its accountable owner re-reviews it.
**Config-as-truth** (like ownership): a human stamps `reviewed` in config; staleness is
computed against an injected `now` (K10), audience-aware (K3).

**Config (additive, K6).** `DocumentSpec.reviewed: str | None = None` (ISO date the doc
was last reviewed). `MonitorConfig.staleness: StalenessConfig` —
`default_days: int = 90` + `audience_days: dict[Audience,int] = {}` (a user-guide may get
a longer SLA than an eng-guide, K3).

**Core — `custodex/staleness.py` (pure, clock-free except the injected `now`).**
```python
class StalenessStatus(str, Enum): FRESH / STALE / NEVER_REVIEWED
class ReviewedDoc(BaseModel):  # frozen
    doc_id: str; doc_path: str; audience: Audience; reviewed: str | None = None
class StalenessFinding(BaseModel):
    doc_id, doc_path, audience, status, reviewed, sla_days: int, age_days: int | None, detail
def resolve_sla_days(audience, *, default_days, audience_days=None) -> int
def detect_stale(docs, *, now, default_days, audience_days=None, include_fresh=False)
    -> tuple[StalenessFinding, ...]   # sorted by doc_id (K10); no wall-clock
def reviewed_docs_from_config(config) -> tuple[ReviewedDoc, ...]
```
`reviewed is None` ⇒ NEVER_REVIEWED; `age = now - reviewed` (days) > sla ⇒ STALE; else FRESH.

**CLI — `cdx staleness [--config][--now ISO][--json][--fail-on-stale]`** (read-only,
K1/K4): resolves reviewed-docs from config, runs `detect_stale` against `now` (default the
wall clock, injectable), prints a table; `--fail-on-stale` exits 1 on any STALE/NEVER_REVIEWED.

**Server — `GET /repos/{id}/staleness`** (open read, read-time like `/ownership`): the synced
`ConfigDocument.reviewed` + audience → `detect_stale` against the app `clock()`, so a doc goes
stale on the NEXT read with no re-sync. `ConfigDocument` gains additive `reviewed`;
`configsync._build_rows` projects it. Frontend surfaces it on the Ownership page (a Reviewed /
SLA column) — accountability + freshness in one view. New `staleness` catalog subsystem.

**Slices:** **SLA-00** pin (this) · **SLA-01** `staleness.py` pure core · **SLA-02** config
`reviewed`/`StalenessConfig` + `cdx staleness` · **SLA-03** `ConfigDocument.reviewed` +
`/staleness` route · **SLA-04** frontend column · **SLA-05** demo + final gate. Each TDD, full gate.

## `worklist.py`  (WL-01 — the per-owner review worklist; pure JOIN, mirrors `ownership.py`, K0/K1/K10)
The accountability JOIN: one prioritised queue per accountable owner across the three
attention signals Custodex already computes. It JOINS, never re-detects.
```python
class WorkReason(str, Enum): ORPHAN="orphan"; STALE="stale"; SUSPECT="suspect"
class WorkSeverity(str, Enum): HIGH="high"; MEDIUM="medium"; LOW="low"
class WorkItem(BaseModel):       # frozen — one (doc, reason[, upstream_id])
    doc_id; doc_path; audience; reason: WorkReason; severity: WorkSeverity
    detail: str; upstream_id: str | None = None
class OwnerWorklist(BaseModel):  # accountable is None ⇒ the unowned bucket (sorts last)
    accountable: str | None; items: tuple[WorkItem,...]; item_count: int; doc_count: int
class Worklist(BaseModel):
    owners: tuple[OwnerWorklist,...]; item_count: int; doc_count: int
    includes_suspect: bool = True   # False on the HUB (no bodies to hash an upstream, K2)

def build_worklist(owners, *, orphans=(), stale=(), suspect=(), owner_filter=None,
                   includes_suspect=True) -> Worklist   # PURE join, no clock/IO
def worklist_from_repo(config, root, *, now, roster=None, unit_owner=None,
                       include_suspect=True, owner_filter=None) -> Worklist  # thin impure adapter
def render_worklist_text(worklist) -> str
```
Buckets each finding under `accountable_by_doc[doc_id]` (the EffectiveOwner projection; missing
⇒ None bucket). One WorkItem per (doc, reason[, upstream_id]) — never collapsed, so no reason is
hidden; counts are item-derived (`item_count` + a DISTINCT `doc_count`, never summed across
inputs). Status→severity maps fall back to MEDIUM so a new status never crashes (K8). Bucket by
*accountable* (the current point of contact) — the worklist routes LIVE work — EXCEPT an
ORPHANED doc (accountable departed): re-routed by orphan status to the live assignee
(DRI-vacant ⇒ the still-active durable owner; owner-departed ⇒ the unowned bucket), so a
"reassign me" item never lands in a departed person's queue.

**CLI — `cdx worklist [--config][--owner][--roster][--now][--(no-)include-suspect][--json][--fail-on-work]`**
(read-only, K1/K4): runs the three detectors via `worklist_from_repo`, prints the per-owner queue;
`--fail-on-work` is an OPT-IN gate (default exit 0).

**Server — `GET /repos/{id}/worklist[?owner=]`** (open read, read-time): reuses the `/ownership` +
`/staleness` cascade for orphans+staleness, OMITS suspect (`suspect=()`, `includes_suspect:false`)
because the hub lacks the bodies to hash an upstream (K2). Parity over both stores. Frontend adds a
console **Worklist** tab. New `worklist` catalog subsystem (FEAT-WORKLIST-001), module waived in
the dogfood `coverage.waive` (api doc owned by `cdx wiki`).

## EPIC AGT — the task-agent layer  (`entities.py` / `docmap.py` / `kgraph.py` / `onboard.py` / `docwriter.py` / `workers.py` — K0/K1/K4/K5/K10/**K11**)

> **Design provenance:** pinned 2026-07-02, then REVISED the same day after a
> 3-lens adversarial design review (16 confirmed must-fixes, most measured
> against the real dogfood corpus). The revision decisions are inlined below,
> marked ⟨R⟩. Do not weaken them during implementation.

**The architecture rule (the LazyGraphRAG split, COMPETITORS.md §13):** every index —
entities, mentions, edge suggestions, the knowledge graph, the onboarding plan, the
suggestion ticks — is built **deterministically, offline, at index time** from the
extracted code surface + managed-doc prose (K1/K4/K10). The LLM enters only at
verdict/authoring time through the EXISTING Backend/Driver seams, and every
agent-produced proposal is advisory-with-provenance under **K11** (agents suggest;
humans apply). Doc-side extraction is entity **LINKING against a known registry**
(the code surface, the managed-doc set, the repo file tree), never open-set NER.
**Precision beats recall everywhere:** an ambiguous mention is UNRESOLVED-or-ignored,
never guessed. All six modules are flat top-level `custodex/*.py`.

⟨R⟩ **Epic-wide DoD correction:** `custodex/cli.py` IS a tracked module (the `ops`
eng-guide AND the `readme` user-guide both carry it in `code_refs`). EVERY slice
that adds a CLI command drifts `docs/api/ops.md` + the README fingerprint and MUST
run `cdx monitor --apply --config config/cdmon` + `cdx check`, commit the rehealed
docs, and add a README prose line for a new user-facing command.

### `entities.py`  (AGT-01 — deterministic entity extraction + mention linking; pure — K0/K1/K10)

```python
class EntityKind(str, Enum):           # a CLOSED set (Backstage discipline); extend deliberately
    DOC = "doc"; SECTION = "section"; SYMBOL = "symbol"; PATH = "path"
    ENV_VAR = "env_var"; URL = "url"

class Entity(BaseModel):               # frozen, extra="forbid" (all models in this epic)
    id: str        # SCIP-style deterministic human-readable string id, repo-relative:
                   #   "doc docs/api/drift.md" · "symbol custodex/drift.py#detect_drift" ·
                   #   "path custodex/drift.py" · "env CDMON_SECRET_KEY"
    kind: EntityKind
    name: str      # display name (SECTION: the SLUG, never raw heading text — ⟨R⟩ K2-safe
                   # for the hub snapshot and deterministic)

class Mention(BaseModel):
    doc_id: str                        # the mentioning managed doc
    entity_id: str | None              # None ⇔ unresolved (first-class data, Obsidian rule)
    kind: EntityKind
    text: str                          # the raw mention as written
    line: int                          # ⟨R⟩ 1-based line in the FILE (front-matter height
                                       # included) so a human can jump to it
    resolved: bool

class DocEntities(BaseModel):
    doc_id: str; doc_path: str
    mentions: tuple[Mention, ...]      # sorted (line, text) — K10
    sections: tuple[Entity, ...]       # this doc's own heading entities (partOf source)

class EntityRegistry(BaseModel):       # the closed resolution universe
    # docs: path→id + id set. symbols: per-file public symbols with qualified names.
    # ⟨R⟩ paths: the FULL repo file tree (os.walk from root honoring the config ignore
    #   set + .git/.venv/node_modules defaults) — NOT the coverage inventory; plus the
    #   set of DIRECTORIES. ⟨R⟩ module stems: file-stem → set of files (for collision
    #   detection + module-name resolution). ⟨R⟩ warnings: tuple[str, ...] — an
    #   unparseable source file contributes a warning + zero symbols, NEVER an abort.
    ...

class EntitiesConfig(BaseModel):       # ⟨R⟩ new config section `entities:` (K0 — target
    ignore: tuple[str, ...] = ()      #   noise enters through config). Spans matching
    env_prefixes: tuple[str, ...] = ()#   `ignore` mint nothing; ENV_VAR requires a
                                       #   configured prefix (dogfood seeds ["CDMON_"]).

def build_registry(config: MonitorConfig, root: Path) -> EntityRegistry
    # ⟨R⟩ symbol extraction goes through the language-guarded registry path
    # (suffix→language via extract's extractor registry), NEVER raw
    # extract_file-per-file; a non-registered suffix or unparseable file ⇒ warning
    # entry + no symbols (resilient by design — background ticks and read-only
    # commands must survive arbitrary adopter repos).
def extract_doc_entities(doc_id, doc_path, body, registry, *, entities_cfg) -> DocEntities  # PURE
def corpus_entities(config, root, *, doc_id=None) -> tuple[DocEntities, ...]
def render_entities_text(results, *, unresolved_only=False) -> str
```

**Mention rules (⟨R⟩ ALL pinned; deterministic, in-order).** Fenced code blocks and
`CDM:BEGIN/END` regions are stripped BEFORE scanning (replaced by blank lines so line
numbers survive; front-matter height added so `line` is file-accurate).
- **Headings** `#`..`######` → the doc's own SECTION entities; slug = GitHub-style
  lowercase-hyphenated; ⟨R⟩ a repeated slug within one doc deduplicates `-2`, `-3`…
- **Markdown links** (inline only; skip images `![..](..)` and `mailto:`): absolute
  `://` → URL (self-evident). Relative → normalize against the doc's dir; managed-doc
  path → DOC resolved; else ⟨R⟩ resolve against the FULL repo tree: existing file →
  PATH resolved; existing directory (trailing `/` normalized) → PATH resolved (dir);
  else PATH unresolved.
- **Backticked inline spans**, classified in this order; a span matching
  `entities.ignore` mints nothing:
  1. ⟨R⟩ *path-shaped* only if it contains NO whitespace and NO `{`/`}` (kills HTTP
     route spans like `GET /repos/{id}/status`) and NO glob metachar `*?[` (glob
     spans are IGNORED — never unresolved noise): contains `/` or has a known file
     suffix → PATH, resolved against the full tree (files AND dirs); unresolved
     otherwise.
  2. ⟨R⟩ SCREAMING_SNAKE (`[A-Z][A-Z0-9_]{2,}` with `_`): exact registry-symbol
     match → SYMBOL resolved; else starts with a configured `env_prefixes` entry →
     ENV_VAR (self-evident); else IGNORED (kills `MISSING_REGION`-style enum-name
     noise; registry lookup comes FIRST so `WIKI_TARGETS` resolves as the symbol
     it is).
  3. identifier-like → SYMBOL, with the ⟨R⟩ STRICT rule: only *dotted*
     (`a.b`), *snake_case* (contains `_`), or *multi-hump CamelCase* (≥2 uppercase
     humps) spans may mint an UNRESOLVED mention. A plain single word (`check`,
     `mock`, `TODO`, `cdx`) mints a mention ONLY on exact registry match — no
     match ⇒ ignored, never unresolved.
- **Symbol resolution** (exact match only; ambiguity ⇒ unresolved): qualified
  `Class.method` resolves within the registry; ⟨R⟩ *module-qualified* `stem.name`
  (for file `a/b/mod.py`, registered forms are `mod.<name>` AND the full dotted
  `a.b.mod.<name>`) resolves only when the stem is UNIQUE across the tree; bare
  names require GLOBAL uniqueness across the registry **and** ⟨R⟩ must not collide
  with any file stem (a bare name that is also a module stem — `app`, `coverage`,
  `index` — is AMBIGUOUS ⇒ unresolved; the measured cli.py-command trap). A bare
  name matching ONLY a module stem resolves as a PATH mention to that file when
  the stem is unique, else unresolved.

Symbol entity ids embed the defining file repo-relative:
`symbol custodex/drift.py#detect_drift`. CLI: `cdx entities [DOC_ID] [--json]
[--unresolved]` (read-only, K1). ⟨R⟩ **Precision budget is part of the goal:** the
AGT-01 test plan asserts over THIS repo's managed corpus that the unresolved output
contains no glob/dir/route/enum-name false positives (dogfood stoplist seeded).

### `docmap.py`  (AGT-02 — entity-based edge suggestions + the `cdx link` approve/reject verbs — K11)

```python
class SuggestionTier(str, Enum):       # provenance TIERS, strongest first — never a bare float
    RESOLVED_LINK = "resolved_link"    # a prose markdown link to the managed upstream
    SHARED_SYMBOL = "shared_symbol"    # downstream MENTIONS a symbol the upstream DOCUMENTS

class ScoredEdge(BaseModel):
    doc_id: str; upstream_id: str
    via: str | None                    # ⟨R⟩ kept for K6: the link target (RESOLVED_LINK);
                                       # None for SHARED_SYMBOL — --suggest --json items
                                       # stay a key-SUPERSET of today's {doc_id,
                                       # upstream_id, via}
    tier: SuggestionTier
    evidence: tuple[str, ...]          # entity ids / link targets justifying the edge; sorted
    score: int                         # count of independent evidence items (int, K10)

class EdgeRejection(BaseModel):        # ⟨R⟩ the repo-side durable opt-out (a human VERDICT,
    doc_id: str; upstream_id: str      # so it lives beside resolutions in .cdmon/ —
    rejected_by: str | None = None     # append-only JSONL, the reviewlog precedent)
    rejected_at: str                   # injected, K10
    note: str | None = None

def suggest_edges(config, root, *, rejections: Sequence[EdgeRejection] = ())
    -> tuple[ScoredEdge, ...]
    # RESOLVED_LINK derives from the AGT-01 DOC mentions (fences/CDM regions already
    # stripped — ⟨R⟩ machine-generated links can no longer mint suggestions; the legacy
    # infer_edges_from_links stays untouched for back-compat but docmap does NOT call it).
    # SHARED_SYMBOL: doc A has a resolved SYMBOL mention S; exactly ONE doc B covers S
    # via code_refs (coverage join); A≠B ⇒ suggest A depends_on B. A symbol covered by
    # ≥2 docs is excluded (ambiguous ownership — precision first).
    # ⟨R⟩ exclusions: declared edges, self-edges, REJECTED pairs, and any downstream
    # with spec.index=True (the index page's links are MANDATED by the INDEX_INCOMPLETE
    # lint — measured 13/13 pure noise on the dogfood). Same pair via both rules ⇒ ONE
    # suggestion at the stronger tier, merged evidence. Sorted (doc_id, upstream_id).
def churn_note(config, upstream_id) -> str
    # ⟨R⟩ "upstream is code-tracked over N source files; it reheals when any of them
    # change and this edge will go SUSPECT each time" — rendered with EVERY suggestion
    # whose upstream carries code_refs, and echoed by `cdx link` before writing (the
    # DOCDEPS-01 lesson, surfaced to the human instead of re-learned).
def render_suggestions_text(edges, *, notes) -> str   # paste-ready YAML + tier/evidence + churn notes
def declare_edge(config_dir, downstream_id, upstream_id, *, type=DocEdgeType.DEPENDS,
                 now) -> Path
    # ⟨R⟩ validates via the loaded models (unknown ids / self / duplicate ⇒ loud K8) but
    # WRITES via targeted TEXTUAL SPLICE of the unit file (insert/extend the
    # `depends_on:` block under the matching `- id:` entry — the regenerate_index
    # precedent), NEVER dump_unit_file: the dogfood units carry 30+ load-bearing
    # comment lines a model round-trip would destroy. Loud when the entry cannot be
    # located textually.
def reject_edge(cdmon_dir, downstream_id, upstream_id, *, by, now, note=None) -> Path
def read_rejections(cdmon_dir) -> tuple[EdgeRejection, ...]   # .cdmon/edge-rejections.jsonl
```

⟨R⟩ **The suspect-baseline knob** (the heal-path-churn decision): new
`DocDepsConfig.baseline: Literal["body", "prose"] = "body"`. `"body"` = today's
whole-body upstream hash (back-compat, stored stamps untouched). `"prose"` = the
upstream fingerprint is computed over the **region-STRIPPED body** (human prose
only), so machine reheals of a code-tracked upstream no longer trip its dependents —
which is what a mention-based dependency means. Flipping the knob is a deliberate
re-baseline event (every stamp mismatches once; re-confirm via `cdx resolve --edge`
or `cdx monitor --apply` restamps on UNSTAMPED-equivalent terms — document it). The
dogfood + demo flip to `"prose"` in AGT-02 and restamp their few edges.

CLI: `cdx deps --suggest` prints `suggest_edges` (+ churn notes); `--json` items are
a key-superset of today's (K6 guard). `cdx deps` report: when
`docdeps.infer_from_links` is true, append ⟨R⟩ a one-line advisory SUMMARY (count +
"run `cdx deps --suggest`"), never the full list (terminal-noise control). NEW
`cdx link DOWN UP [--type] [--reject]`: accept = `declare_edge` + `stamp_edges(...,
only=UP)` (fresh edges arrive baselined); `--reject` = `reject_edge` (the suggestion
never returns; workers' ADD_EDGE honors rejections too).

### `kgraph.py`  (AGT-03 — the unified knowledge-graph artifact; pure build, snapshot mirror — K2-safe)

```python
class NodeKind(str, Enum): DOC; SECTION; SYMBOL; PATH; ENV_VAR; URL; OWNER
class EdgeKind(str, Enum):             # closed vocabulary; directional pairs implied by reverse queries
    DOCUMENTS = "documents"            # doc → symbol (code_refs coverage join)
    DEPENDS_ON = "depends_on"          # doc → doc (declared docdeps)
    MENTIONS = "mentions"              # doc → symbol/path/env (entities layer)
    LINKS_TO = "links_to"              # doc → doc/url (resolved links; unresolved = counts)
    PART_OF = "part_of"                # section → doc
    OWNED_BY = "owned_by"              # doc → owner (accountable projection)
class EdgeTier(str, Enum): DECLARED = "declared"; RESOLVED = "resolved"; INFERRED = "inferred"

class GraphNode(BaseModel): id: str; kind: NodeKind; name: str   # SECTION name = slug (⟨R⟩)
class GraphEdge(BaseModel): source: str; target: str; kind: EdgeKind; tier: EdgeTier
class KnowledgeGraph(BaseModel):
    schema_version: str = "1.0.0"      # K6: emitted from pydantic, additive evolution
    nodes: tuple[GraphNode, ...]; edges: tuple[GraphEdge, ...]
    unresolved: dict[str, int]         # doc_id → unresolved-mention count (rot signal —
                                       # trustworthy BECAUSE of the AGT-01 precision rules)

def build_graph(config, root, *, unit_owner=None) -> KnowledgeGraph   # PURE fold of the
    # existing detectors; base facts only (Glean split) — derived quantities are
    # recomputed, never stored. Uses the AGT-01 resilient registry (⟨R⟩ one bad file
    # ⇒ warning, never an abort).
def graph_neighbors(g, node_id, *, depth=1) -> tuple[GraphEdge, ...]  # in+out, loud on unknown id
def rank_centrality(g, *, kind=NodeKind.SYMBOL, undocumented_only=False)
    -> tuple[tuple[str, int], ...]     # MENTIONS in-degree; undocumented_only crosses it
                                       # with the absence of DOCUMENTS — the
                                       # what-to-document priority feed (AGT-06)
def render_graph_text(g, *, focus=None) -> str
```

CLI: `cdx graph [--focus ID] [--rank] [--json] [--write]`; `--write` emits
`.cdmon/graph.json` (regenerable, gitignored). **Hub (K2-safe):** the graph is
computed REPO-SIDE and pushed as an opaque versioned snapshot exactly like the
coverage snapshot: `POST /repos/{id}/graph` (token) / `GET /repos/{id}/graph` (open
read); Store gains `add_graph_snapshot`/`graph_for` on BOTH stores; Alembic
`0008_graph_snapshots`. ⟨R⟩ No raw doc-body text rides the snapshot: SECTION names
are slugs; mention `text` stays repo-local (the snapshot carries entity ids/kinds/
counts, not prose).

### `onboard.py`  (AGT-04 — the config-authoring onboarding agent; deterministic core — K11)

```python
class DocCandidate(BaseModel):  path: str; title: str | None; guessed_audience: Audience; evidence: str
class PackageCandidate(BaseModel): name: str; dir: str; files: tuple[str, ...]; public_symbols: int
class RepoMap(BaseModel):              # the PLAN ARTIFACT (Mintlify pattern)
    root: str
    docs: tuple[DocCandidate, ...]
    packages: tuple[PackageCandidate, ...]
    signals: dict[str, str]            # readme/agents_md/claude_md/docs_dir/existing_config found
    warnings: tuple[str, ...]          # ⟨R⟩ incl. every unparseable file (per-file try/except —
                                       # NEVER discover_symbols' abort-on-first-error)

def analyze_repo(root, *, include=(), exclude=()) -> RepoMap
def propose_config(repo_map, *, repo, now, owner=None) -> OnboardPlan
    # OnboardPlan = {units: tuple[UnitFile,...], index_text: str, docs_to_scaffold, notes}
    # REAL UnitFile models via the pure editors + dump_unit_file (fresh files — no
    # comments to destroy, so model-dump is correct HERE, unlike declare_edge ⟨R⟩).
    # One unit per top-level package; one eng-guide doc per package; README mapped as
    # a user-guide doc. ⟨R⟩ UnitFrontmatter.owner is REQUIRED: `owner` param → else
    # git config user.name (read impurely by the CLI, passed in) → else "unassigned"
    # + a plan warning telling the adopter to set it (it feeds the accountability chain).
def apply_plan(plan, config_dir, *, now) -> tuple[Path, ...]
def render_plan_text(plan) -> str      # the Renovate onboarding-PR body
```

CLI: `cdx onboard [--path] [--repo NAME] [--owner NAME] [--apply] [--force]` —
default DRY-RUN (K11). `--apply` writes `config/cdmon/`, scaffolds docs, then
SELF-VALIDATES (load_bundle → doctor.run_checks → `Monitor.check`) and reports
(arrive-green, K8). Ships the `init --v2` DOA fix: the scaffold's `doc-style.yaml`
is emitted ONLY alongside the writing-template files it references (scaffold writes
minimal generic templates under `templates/writing/`), so a bare-repo scaffold
loads clean.

### `docwriter.py`  (AGT-05 — write-new-doc-from-code + register; Backend-authored prose — K4/K5/K11)

```python
def draft_document(spec: DocumentSpec, surface: DocumentSurface, *,
                   style_guidance: str | None = None,
                   backend: Backend | None = None) -> str
    # scaffold_doc skeleton + an authored purpose blockquote + an `overview` region in
    # mode `llm` (⟨R⟩ the generated spec DECLARES `overview` in region_keys AND
    # region_modes={"overview": "llm"} — the validator requires modes ⊆ keys) whose
    # body comes through the Backend seam (MockBackend ⇒ deterministic prose, K4/K10).
    # ⟨R⟩ Idempotency scoped honestly: byte-idempotent on the mock path; with a real
    # backend, re-running with an UNCHANGED surface performs NO re-author (the B-06
    # no-drift rule) — prose churns only when the surface moves.
def write_and_register(config_dir, *, unit, doc_id, path, audience, code_refs,
                       backend=None, now) -> Path
```

CLI: `cdx write-doc TARGET [--unit U] [--id ID] [--audience A] [--apply]` — default
DRY-RUN prints the draft + config delta (K11); `--apply` registers (pure editors +
index regen) + writes + heals. Human/locked regions honored by writing through
scaffold/heal only.

### `workers.py`  (AGT-06 — the two background suggesters; pure ticks + default-OFF loops — K4/K7/K10/K11)

```python
class SuggestionKind(str, Enum):
    FIX_DRIFT = "fix_drift"; RESOLVE_EDGE = "resolve_edge"; PROMOTE_RULE = "promote_rule"
    DOCUMENT_GAP = "document_gap"; ADD_EDGE = "add_edge"

# ⟨R⟩ Two lifecycle CLASSES, pinned:
#   EVENT kinds (FIX_DRIFT, RESOLVE_EDGE): the key EMBEDS the occurrence — the current
#     surface_hash / upstream fingerprint — so a recurrence AFTER a heal is a NEW key;
#     a dismiss silences exactly one occurrence.
#   STANDING kinds (ADD_EDGE, DOCUMENT_GAP, PROMOTE_RULE): the key is occurrence-free;
#     a dismiss is the durable opt-out (and ADD_EDGE additionally honors the repo-side
#     EdgeRejection file).

class Suggestion(BaseModel):
    key: str      # ⟨R⟩ sha256[:16] over PINNED STRUCTURED FIELDS per kind — NEVER the
                  # prose. FIX_DRIFT=(kind, doc_id, sorted drift-kinds, surface_hash);
                  # RESOLVE_EDGE=(kind, down, up, current upstream fingerprint);
                  # ADD_EDGE=(kind, doc, upstream, tier); DOCUMENT_GAP=(kind, path-or-
                  # symbol id); PROMOTE_RULE=(kind, doc_id, drift_kind, audience,
                  # resolution). detail/evidence/severity/now are EXCLUDED — a reworded
                  # detail keeps the key; a different occurrence changes it (regression-
                  # guarded).
    kind: SuggestionKind
    doc_id: str | None; target: str
    detail: str                        # embeds the exact next command
    evidence: tuple[str, ...]
    severity: WorkSeverity             # MEDIUM fallback = a robustness default (⟨R⟩ not
                                       # a K8 citation — K8 is about loud errors)

def suggest_fixes_tick(config, root, *, now) -> tuple[Suggestion, ...]   # pure; sorted by key
def suggest_docs_tick(config, root, *, now) -> tuple[Suggestion, ...]    # pure; sorted by key
# `now` feeds ONLY staleness grading inside the tick and the stored envelope's
# recorded_at — never the key (K10).
```

CLI: `cdx suggest [--kind fixes|docs|all] [--json] [--write]` — prints the CURRENT
tick output (the inbox IS current reality); ⟨R⟩ `--write` appends new keys to
`.cdmon/suggestions.jsonl`, which is documented as an append-only LOG (reviewlog
precedent) — never read back as pending state.
**Server:** `WorkerSettings` (`enabled: bool = False`, `interval_seconds: int = 900`,
`kinds`) with `CDMON_WORKER_*` overlays. `create_app` gains injected worker seams;
loops start via lifespan ONLY when enabled, in a thread executor, ⟨R⟩ with a
`threading.Event.wait(timeout)` shutdown (never a bare sleep — lifespan shutdown and
enabled-arm tests must not block) and per-repo error isolation (one repo's tick
failure logs and continues; the loop never dies). The loop leaf is the only
uncovered code. ⟨R⟩ **Store reconciliation, not INSERT-only:**
`sync_suggestions(repo_id, suggestions)` inserts new keys, keeps existing, and marks
non-dismissed keys ABSENT from the tick as `resolved` (kept for audit, excluded from
the default read) — the inbox always equals current reality (the read-time
staleness/orphan precedent); `suggestions_for(repo_id, *, include_closed=False)`;
`dismiss_suggestion(repo_id, key)`. Both stores + Alembic `0009_suggestions`; routes
`GET /repos/{id}/suggestions` (open read) + `POST /repos/{id}/suggestions/{key}/dismiss`
(token). Stored envelopes carry `source: "worker"` provenance (K5/K11 audit line).

### Frontend  (AGT-07 — Graph explorer + Suggestions inbox)

Per-repo **Graph** tab (extends the Dependencies seams; focus-node in/out edge groups
+ a top-central-undocumented table — NO graph-viz dependency) and per-repo
**Suggestions** tab (severity chips reused from Worklist; dismiss mirrors the Mapping
staged-edit lifecycle; ⟨R⟩ resolved/closed items visibly separated from pending).
Both follow the WL-01 6-point chain + demo fixtures (busy + empty variants) +
demoFetch routes + vitest suites + ConsoleChrome parity + a `/guide` page per
feature. ⟨R⟩ DEMO id allocation: the DEMOS.md duplicate-id rider renumbers the
section-M trio to DEMO-095/096/097; new AGT demos start at DEMO-098.
