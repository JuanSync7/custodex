"""Config models, loaders, and starter template (K0, K8, K10).

Everything the engine needs to know about a target codebase enters through one
config that merges into a single :class:`MonitorConfig` (K0). The canonical form
is the CONFIG-V2 multi-file ``config/cdmon/`` directory layout (an ``index.yaml``
plus N unit files — see :func:`load_bundle` / :func:`load_config_dir`). A single
YAML or JSON config file (:func:`load_config` + :data:`CONFIG_TEMPLATE`) is the
supported BACK-COMPAT path. The models below mirror the contracts in
ARCHITECTURE.md exactly. They are frozen and forbid unknown keys so a typo or a
stale field raises a loud, typed :class:`ConfigError` (K8).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# CONFIG-V2 (Z-03): the four parsing primitives docstyle also needs live in the
# leaf :mod:`_v2base` so :mod:`config` can import the concrete ``DocStyleMap``
# below without a cycle (config -> docstyle -> _v2base; one-way). They are
# re-exported under their historic ``config.*`` paths so callers/tests that
# reference ``config._split_frontmatter`` etc. keep working (K6).
from ._v2base import (
    _FM_RE,
    _V2_MODEL_CONFIG,
    CDMON_CONFIG_VERSION,
    _parse_v2_body,
    _split_frontmatter,
)
from .docstyle import DocStyleMap, load_doc_style
from .errors import ConfigError

__all__ = [
    "Audience",
    "CodeRef",
    "ContextRef",
    "BackendConfig",
    "AgentConfig",
    "CentralConfig",
    "RegionColumn",
    "RegionTemplate",
    "RegionMode",
    "DocumentSpec",
    "WaiverEntry",
    "CoverageConfig",
    "MonitorConfig",
    "load_config",
    "write_template",
    "central_config_template",
    "CONFIG_TEMPLATE",
    "DEFAULT_CENTRAL_TOKEN_ENV",
    # CONFIG-V2 (N-01): the multi-file ``config/cdmon/`` layout.
    "CDMON_CONFIG_VERSION",
    "UnitFrontmatter",
    "UnitFile",
    "IndexFrontmatter",
    "IndexUnitRef",
    "IndexFile",
    "ConfigBundle",
    "load_unit_file",
    "load_index_file",
    "load_config_dir",
    "load_bundle",
    "unit_for_path",
    # EDITOR (E-01): unit-file serializer + pure model editors.
    "dump_unit_file",
    "upsert_document",
    "add_code_ref",
    "remove_code_ref",
    "set_context_refs",
    # CONFIG-V2 (N-02): index↔disk reverse validation + regeneration.
    "RESERVED_UNIT_STEMS",
    "regenerate_index",
    "write_index",
    # CONFIG-V2 (N-03): ignore.yaml + .gitignore merge + format coverage scoping.
    "IgnoreFrontmatter",
    "IgnoreFile",
    "load_ignore_file",
    "gitignore_to_globs",
    "effective_coverage",
    # CONFIG-V2 (N-06): the ONE repo-root resolver shared by every consumer.
    "resolve_repo_root",
]

#: Default env var the HTTP sink reads the central bearer token from (G-01).
DEFAULT_CENTRAL_TOKEN_ENV = "CDMON_CENTRAL_TOKEN"

# Frozen + extra="forbid": configs are immutable snapshots and unknown keys are
# an error, not a silent pass (K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class Audience(str, Enum):
    """Who a document is written for — drives extraction and drift verdicts."""

    USER_GUIDE = "user-guide"
    ENG_GUIDE = "eng-guide"


class CodeRef(BaseModel):
    """A pointer into one code file.

    With no selectors the whole file's Python symbol surface is referenced.
    ``symbols``/``names`` select by name; ``lines`` selects 1-based inclusive
    ranges; ``arg_signature`` selects functions whose positional parameter list
    matches exactly (a generic stand-in for "every function registered by
    signature" — no target codebase is hard-coded, K0).

    ``extract`` chooses *what kind* of surface this ref contributes:

    * ``symbols`` (default) — Python functions/classes/methods/variables (AST).
    * ``switches`` — CLI ``-x``/``--x`` switch tokens parsed from a python /
      shell / tcl tool, each contributed as a ``Record`` of kind ``switch``.
    * ``records`` — rows projected from a JSON file: ``json_records`` names the
      list-valued key (``"*"`` = the sole list-valued top-level key) and
      ``record_name_field`` names the field that identifies each row.

    ``lang`` selects the parser for ``switches``/``records`` (``auto`` infers it
    from the file suffix).
    """

    model_config = _MODEL_CONFIG

    path: str  # repo-relative
    symbols: tuple[str, ...] = ()  # named functions/classes
    lines: tuple[tuple[int, int], ...] = ()  # 1-based inclusive ranges
    names: tuple[str, ...] = ()  # named module-level variables
    arg_signature: tuple[str, ...] = ()  # functions with exactly these params
    extract: Literal["symbols", "switches", "records"] = "symbols"
    # P3: open string (was a closed Literal) so a SYMBOL ref can name any
    # language registered via `extract.register_extractor` — a new language is a
    # registration, not an engine/schema edit (K0). "auto" infers from the file
    # suffix. Unknown languages stay loud, but at extraction time (K8,
    # `get_extractor`) rather than config-load. The built-in switch/record
    # parsers still recognize only python/shell/tcl/json.
    lang: str = "auto"
    json_records: str | None = None  # list-valued key, or "*"
    record_name_field: str = "name"  # which json field identifies a row


class ContextRef(BaseModel):
    """A "glance-through" generation reference, NOT a documented surface (K6).

    A ``context_refs`` entry on a :class:`DocumentSpec` points an author at a
    sibling document or a source file to refer to while generating this document.
    It is additive context for the generation prompt only — it never enters
    ``code_refs``, coverage, drift, or the ``.rpt`` (EDITOR §1). ``path`` is
    repo-root-relative and is NOT resolved for existence at load (a context ref
    MAY point at a not-yet-created doc). ``note`` is an optional human hint.
    """

    model_config = _MODEL_CONFIG

    path: str  # repo-relative; not resolved for existence at load
    note: str | None = None


class BackendConfig(BaseModel):
    """Which LLM backend produces verdicts. Offline ``mock`` by default (K4).

    ``mock``/``claude-code``/``api`` are the single-shot backends. ``agent``
    selects the deterministic LangGraph remediation workflow (see
    :class:`AgentConfig` and :mod:`code_doc_monitor.agent`), whose *runtime* (the
    process/network leaf that talks to a model) is in turn chosen by
    ``agent.driver`` — so the engine is the same whether the agent drives the
    Claude Code CLI headless, the Anthropic API, or a local model.
    """

    model_config = _MODEL_CONFIG

    kind: Literal["mock", "claude-code", "api", "agent"] = "mock"
    model: str | None = None
    command: tuple[str, ...] | None = None  # claude-code argv template
    timeout_s: int = 120
    extra: dict[str, str] = {}


class AgentConfig(BaseModel):
    """The LangGraph remediation-agent runtime (used when ``backend.kind`` is
    ``agent``).

    This is the single, top-level knob the SPEC calls for: *"the agent is using
    the Claude Code CLI headless, and can instead be pointed at an API key or an
    API connection for a local model."* ``driver`` picks the runtime leaf and
    the rest configure it:

    * ``claude-code`` (default) — a headless ``claude -p`` subprocess. ``command``
      overrides the argv template (a ``{prompt}`` token is substituted, else the
      prompt is appended); ``model`` adds ``--model``.
    * ``api`` — the Anthropic Messages API; the key is read from ``api_key_env``
      and ``base_url`` overrides the endpoint.
    * ``local`` — any OpenAI-compatible chat endpoint (a local model server);
      ``base_url`` is required and ``api_key_env`` is optional.

    ``prompts_dir`` overrides where the ``AGENT.md`` / ``PROTOCOL.md`` /
    ``TOOL.md`` / ``PERSONA.md`` artifacts are read from (default: the packaged
    ones). ``use_persona`` gates loading ``PERSONA.md`` at all (it is composed
    into the prompt *only when needed*). ``max_parse_retries`` bounds the graph's
    re-ask loop when a reply is not valid JSON (K8).
    """

    model_config = _MODEL_CONFIG

    driver: Literal["claude-code", "api", "local"] = "claude-code"
    model: str | None = None
    command: tuple[str, ...] | None = None  # claude-code argv template
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str | None = None  # api/local endpoint override (required for local)
    prompts_dir: str | None = None  # override the packaged .md artifacts
    use_persona: bool = True  # compose PERSONA.md when present
    max_parse_retries: int = 1  # bounded re-ask on a non-JSON reply (K8)
    timeout_s: int = 120


class CentralConfig(BaseModel):
    """Where review records are emitted. Offline ``none`` by default (K4).

    The E-01 repo-identity fields are additive (all default ``None`` / ``2``), so
    a pre-E-01 config still loads unchanged. They identify which repo a record
    came from in a multi-repo central system: ``repo_id`` is REQUIRED when
    ``sink == "http"`` (a loud :class:`SchemaError` in :func:`make_sink` if
    missing, K8). ``repo_commit`` pins the commit on the wire envelope; absent, it
    falls back to ``$CI_COMMIT_SHA``. ``outbox`` is the offline queue path
    (default ``.cdmon/outbox.jsonl``) and ``max_retries`` bounds send attempts
    before a record is queued.
    """

    model_config = _MODEL_CONFIG

    sink: Literal["none", "file", "http"] = "none"
    path: str | None = None  # file sink
    url: str | None = None  # http sink
    auth_env: str | None = None  # env var holding a bearer token
    repo_id: str | None = None  # E-01: required when sink=="http" (loud K8)
    repo_name: str | None = None  # E-01: human-readable repo name
    repo_url: str | None = None  # E-01: repo clone/browse url
    repo_commit: str | None = None  # E-01: commit; else $CI_COMMIT_SHA fallback
    outbox: str | None = None  # E-01: offline queue path (default .cdmon/outbox.jsonl)
    max_retries: int = 2  # E-01: send attempts before queueing


class RegionColumn(BaseModel):
    """One column of a templated region table: a header and a value source.

    ``field`` names a record field (``records`` source) or a symbol attribute
    (``symbols`` source: ``name``/``kind``/``signature``). For an ``index``
    source it names a synthetic per-doc field (e.g. ``doc_id``, ``link``, or a
    ``summary.*`` key) — see the layout standard.
    """

    model_config = _MODEL_CONFIG

    header: str
    field: str


class RegionTemplate(BaseModel):
    """A declarative table renderer for a managed region (K0, K2, K10).

    ``source`` picks the rows — the document's ``records`` (optionally filtered
    by ``kind``), its ``symbols``, or an ``index`` over other documents — and
    ``columns`` map each row to cells. ``empty_text`` is rendered when there are
    no rows. Nothing target-specific lives here; the genbuild tables are just
    one configured instance.
    """

    model_config = _MODEL_CONFIG

    source: Literal["records", "symbols", "index"] = "records"
    kind: str | None = None  # for source=records: keep only this record kind
    columns: tuple[RegionColumn, ...]
    empty_text: str = ""


class RegionMode(str, Enum):
    """Per-region authority — who owns a managed region and how heal treats it.

    * ``generated`` (DEFAULT) — a pure mechanical projection of the code surface
      (symbol table / index / fingerprint). Heal overwrites it, no LLM. This is
      the only behavior in EPIC-A; absent ``region_modes`` means every region is
      ``generated`` (K6 additive).
    * ``llm`` — prose authored by the backend; on code drift the backend
      re-proposes and heal applies the LLM fix rather than a mechanical render.
      **B-06 (no longer ==generated):** a renderer-backed ``llm`` region is still
      mechanically rendered + kept in sync, but a NO-renderer ``llm`` region is
      backend-AUTHORED prose — re-authored when the code surface it documents
      MOVES (the whole-doc fingerprint diverges), and NOT graded against any
      mechanical render while the surface is unchanged (its prose legitimately
      differs). The offline ``MockBackend`` authors a deterministic, idempotent
      prose stand-in (K4/K10). A non-``llm`` no-renderer region still surfaces
      ``UNHEALABLE`` (no authoring path, loud K8). See LAYOUT_STANDARD §7.
    * ``human`` — a human owns it; heal NEVER writes it, and code drift only
      raises an advisory "the code this section describes changed — review"
      (persisted via ``cdm.region_hashes`` until the human edits the body).
    * ``llm-seeded`` — behaves as ``generated`` until a human edits it (a stored
      per-region content hash diverges), then locks to ``human``.

    Schema lands in B-01; ``human`` (B-02), the ``llm-seeded`` lock (B-03), the
    mixed-authorship e2e + renderer-backed ``llm`` rule (B-04), and pure-``llm``
    (no-renderer) prose authoring (B-06) wire the behaviors.
    """

    GENERATED = "generated"
    LLM = "llm"
    HUMAN = "human"
    LLM_SEEDED = "llm-seeded"


class DocumentSpec(BaseModel):
    """One logical document: an id, a path, an audience, and code refs."""

    model_config = _MODEL_CONFIG

    id: str
    path: str  # repo-relative doc path
    audience: Audience
    code_refs: tuple[CodeRef, ...] = ()  # empty for an index/collection doc
    context_refs: tuple[ContextRef, ...] = ()  # K6: generation context, NOT coverage
    region_keys: tuple[str, ...] = ()  # managed regions this doc carries
    region_modes: dict[str, RegionMode] = {}  # region id -> mode; absent => generated
    html: bool = False  # does this doc have a derived .html twin? (layout standard)
    index: bool = False  # landing page that must link every other document
    nav_section: str | None = None  # group heading in the html-twin sidebar
    nav_label: str | None = None  # short sidebar label (falls back to the title)
    # EPIC OWN — ownership-of-record (config = truth; K0, the K2 scope note). All
    # optional + additive (K6); a doc with none inherits its unit's frontmatter owner.
    owner: str | None = None  # accountable identity (a person OR a team handle)
    team: str | None = None  # durable group accountability (survives a person leaving)
    dri: str | None = None  # current Directly-Responsible-Individual (vacatable)

    @model_validator(mode="after")
    def _region_modes_reference_declared_regions(self) -> DocumentSpec:
        """Every ``region_modes`` key must name a declared region (K8).

        A mode pinned to a region the doc does not carry is a loud config error,
        surfaced as :class:`ConfigError` by :func:`load_config`.
        """
        unknown = [k for k in self.region_modes if k not in self.region_keys]
        if unknown:
            raise ValueError(
                f"document {self.id!r}: region_modes names region(s) "
                f"{sorted(unknown)!r} not in region_keys {list(self.region_keys)!r}"
            )
        return self

    @model_validator(mode="after")
    def _context_refs_paths_unique(self) -> DocumentSpec:
        """No two ``context_refs`` in one document may share a ``path`` (K8).

        A duplicate context-ref path is a config mistake (the same reference
        listed twice), surfaced as a loud :class:`ConfigError` by the loaders.
        """
        seen: set[str] = set()
        dups: list[str] = []
        for ref in self.context_refs:
            if ref.path in seen:
                dups.append(ref.path)
            seen.add(ref.path)
        if dups:
            raise ValueError(
                f"document {self.id!r}: duplicate context_refs path(s) "
                f"{sorted(set(dups))!r}; each context ref must be listed once"
            )
        return self

    def mode_for(self, region_id: str) -> RegionMode:
        """Authority mode declared for ``region_id``, or ``GENERATED`` if none.

        The single accessor B-02/03/04 consume — no scattered
        ``.get(..., GENERATED)`` calls.
        """
        return self.region_modes.get(region_id, RegionMode.GENERATED)


class WaiverEntry(BaseModel):
    """One intentional documentation gap, justified (A-04, K8).

    ``path`` is a glob over repo-relative POSIX paths (same ``**`` semantics as
    :mod:`code_doc_monitor.inventory`). ``symbol`` names an exact symbol to
    waive; ``None`` (the default) waives the whole file and every symbol under
    it. ``reason`` is REQUIRED — a waiver must justify itself, so omitting it
    raises a loud :class:`ConfigError` at load time (K8).
    """

    model_config = _MODEL_CONFIG

    path: str  # glob over repo-relative POSIX paths
    symbol: str | None = None  # exact symbol name; None => whole-file waiver
    reason: str  # REQUIRED (K8): a waiver must justify itself


# The coverage scan-scope defaults mirror inventory.DEFAULT_INCLUDE/EXCLUDE.
# They are inlined (not imported) to avoid an import cycle: inventory imports
# extract, extract imports config — so config must not import inventory. A test
# (test_coverage_defaults_match_inventory) asserts these stay in lock-step.
_DEFAULT_INCLUDE: tuple[str, ...] = ("**/*.py",)
_DEFAULT_EXCLUDE: tuple[str, ...] = (
    "**/.*/**",
    "**/__pycache__/**",
    "**/.venv/**",
)


class CoverageConfig(BaseModel):
    """The ``coverage:`` block: scan scope plus the explicit waiver list (A-04).

    ``include``/``exclude`` are the globs the A-05 ``cdmon coverage`` CLI will
    pass to :func:`code_doc_monitor.inventory.discover_files`; they default to
    the inventory's own defaults. ``waive`` carries intentional, justified
    documentation gaps folded into the coverage report
    (:class:`~code_doc_monitor.coverage.CoverageReport`).
    """

    model_config = _MODEL_CONFIG

    include: tuple[str, ...] = _DEFAULT_INCLUDE
    exclude: tuple[str, ...] = _DEFAULT_EXCLUDE
    waive: tuple[WaiverEntry, ...] = ()


class MonitorConfig(BaseModel):
    """Top-level config: documents plus backend/central/apply settings."""

    model_config = _MODEL_CONFIG

    version: str = "1.0.0"
    root: str = "."  # repo root, relative to the config file
    documents: tuple[DocumentSpec, ...]
    region_templates: dict[str, RegionTemplate] = {}  # region id -> table template
    backend: BackendConfig = BackendConfig()
    agent: AgentConfig = AgentConfig()  # runtime for backend.kind == "agent"
    central: CentralConfig = CentralConfig()
    apply_default: bool = False  # monitor auto-applies FIX by default?
    coverage: CoverageConfig = CoverageConfig()  # A-04: scan scope + waivers (additive)
    # P-01: opt-in body-AST fingerprint tier. Default OFF keeps surface_hash bytes
    # identical to the pre-P1 contract, so stored fingerprints stay valid; ON folds
    # function/method bodies into non-user-guide hashes (a deliberate re-baseline).
    fingerprint_body_tier: bool = False


def load_config(path: Path) -> MonitorConfig:
    """Load and validate a config file, choosing YAML/JSON by suffix.

    Any read, parse, or validation failure is wrapped in :class:`ConfigError`
    with a clear message (K8).
    """
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        loader = "yaml"
    elif suffix == ".json":
        loader = "json"
    else:
        raise ConfigError(
            f"Unsupported config suffix {path.suffix!r} for {path}: "
            "use .yaml, .yml, or .json"
        )

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(text) if loader == "yaml" else json.loads(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Malformed config file {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(
            f"Config file {path} must contain a mapping at the top level, "
            f"got {type(data).__name__}"
        )

    try:
        return MonitorConfig(**data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config in {path}:\n{exc}") from exc


# A documented starter config covering both audiences and all selector kinds.
# It round-trips through load_config (asserted in the test suite).
CONFIG_TEMPLATE = """\
# code-doc-monitor configuration
#
# Maps groups of code (down to symbols / line ranges / module variables) onto
# logical documents, each tagged with an audience. Edit the paths and refs to
# match your project, then run `cdmon check` / `cdmon monitor`.

version: "1.0.0"

# Repo root, relative to THIS config file. Doc/code paths below are relative
# to this root.
root: "."

documents:
  # ---- A user-facing guide --------------------------------------------------
  # Audience `user-guide`: only the externally-visible surface matters.
  # Comment edits, private (_-prefixed) symbols, and local-variable changes are
  # NOT drift for this audience.
  - id: "user-guide"
    path: "docs/user-guide.md"
    audience: "user-guide"
    code_refs:
      # Whole file (no selectors): the entire public surface of this module.
      - path: "src/myproject/cli.py"
      # Named symbols only: just these functions/classes.
      - path: "src/myproject/api.py"
        symbols: ["create_client", "Client"]
      # Line ranges (1-based, inclusive): handy for a hand-picked region.
      - path: "src/myproject/constants.py"
        lines:
          - [1, 20]
          - [40, 55]
    # Managed regions this document carries (CDM:BEGIN/END blocks).
    region_keys: ["symbols"]

  # ---- An engineering guide -------------------------------------------------
  # Audience `eng-guide`: the implementation surface matters too, so comment
  # and internal changes ARE flagged.
  - id: "eng-guide"
    path: "docs/eng-guide.md"
    audience: "eng-guide"
    code_refs:
      # Named module-level variables only.
      - path: "src/myproject/constants.py"
        names: ["DEFAULT_TIMEOUT", "MAX_RETRIES"]
      # Whole file.
      - path: "src/myproject/core.py"
    region_keys: ["symbols"]
    # Per-region authority (optional; absent => every region is `generated`).
    #   generated  -> mechanical projection of code; heal overwrites it (default)
    #   llm        -> backend-authored prose; heal applies the LLM-proposed fix
    #   human      -> a human owns it; heal NEVER writes it (drift is advisory only)
    #   llm-seeded -> behaves as `llm` until a human edits it, then locks to `human`
    # Every key here MUST be a region declared in `region_keys` above.
    # region_modes:
    #   symbols: generated

# Which LLM backend produces verdicts for detected drift.
#   mock        -> deterministic, offline (default; used in CI/tests)
#   claude-code -> headless `claude -p` subprocess (set `command`)
#   api         -> Anthropic Messages API (key from env)
#   agent       -> the deterministic LangGraph remediation workflow; its runtime
#                  (CLI / API / local model) is chosen by the `agent:` block below
backend:
  kind: "mock"
  # model: "claude-sonnet-4"
  # command: ["claude", "-p"]
  timeout_s: 120

# The LangGraph remediation agent's runtime (only used when backend.kind: agent).
# This is the one knob to point the agent at a different model host:
#   claude-code -> headless `claude -p` CLI (the default)
#   api         -> Anthropic Messages API (key from $api_key_env)
#   local       -> any OpenAI-compatible chat endpoint (set base_url) for a
#                  locally-served model
agent:
  driver: "claude-code"
  # model: "claude-sonnet-4"
  # command: ["claude", "-p"]          # claude-code argv template ({prompt} token)
  api_key_env: "ANTHROPIC_API_KEY"      # api/local key (optional for local)
  # base_url: "http://localhost:11434/v1"   # required for driver: local
  # prompts_dir: "agent-prompts"        # override the packaged AGENT/PROTOCOL/...md
  use_persona: true                     # compose PERSONA.md when present
  max_parse_retries: 1                  # bounded re-ask on a non-JSON reply
  timeout_s: 120

# Where handled-drift review records are emitted.
#   none -> local review log only (default)
#   file -> also append JSON to `path` (offline-testable central system)
#   http -> POST to `url` with a bearer token read from `auth_env`
central:
  sink: "none"
  # path: "review-central.jsonl"
  # url: "https://central.example.com/ingest"
  # auth_env: "CDM_CENTRAL_TOKEN"

# Should `cdmon monitor` auto-apply FIX verdicts by default?
# (Override per-run with `monitor --apply` / `--no-apply`.)
apply_default: false

# Coverage scan scope + intentional, justified documentation gaps (A-04).
# Used by `cdmon coverage`. `include`/`exclude` bound which code files are
# scanned (same `**` glob semantics as inventory; defaults shown). `waive`
# lists code that intentionally needs NO doc — each entry MUST carry a `reason`
# (a waiver justifies itself). A waiver matching an already-documented item is a
# no-op; one matching nothing is silently inert. Waived items are removed from
# BOTH sides of the coverage percentage (universe = total - waived).
coverage:
  include: ["**/*.py"]
  exclude: ["**/.*/**", "**/__pycache__/**", "**/.venv/**"]
  waive:
    # Whole-file waiver (no `symbol`): the file and all its symbols.
    - path: "src/myproject/_generated.py"
      reason: "generated code; documented upstream"
    # Single-symbol waiver: just this public symbol in matching files.
    - path: "src/myproject/legacy/*.py"
      symbol: "old_entrypoint"
      reason: "deprecated; scheduled for removal in 2.0"
"""


# The offline ``central:`` block exactly as it appears in CONFIG_TEMPLATE — the
# anchor `central_config_template` swaps out for an HTTP-reporting block (G-01).
_OFFLINE_CENTRAL_BLOCK = """\
central:
  sink: "none"
  # path: "review-central.jsonl"
  # url: "https://central.example.com/ingest"
  # auth_env: "CDM_CENTRAL_TOKEN"
"""


def central_config_template(
    *,
    url: str,
    repo_id: str,
    token_env: str = DEFAULT_CENTRAL_TOKEN_ENV,
    repo_url: str | None = None,
) -> str:
    """Return CONFIG_TEMPLATE with ``central:`` wired for HTTP reporting (G-01).

    The result round-trips through :func:`load_config` AND satisfies
    :func:`code_doc_monitor.sinks.make_sink`'s HTTP requirements (``repo_id``
    present). ``repo_url`` is emitted only when given. Everything else (the
    documents/backend/coverage scaffolding) is byte-identical to the offline
    template, so the only difference is the reporting wiring.
    """
    lines = [
        "central:",
        '  sink: "http"',
        f'  url: "{url}"',
        f'  repo_id: "{repo_id}"',
        f'  auth_env: "{token_env}"',
    ]
    if repo_url is not None:
        lines.append(f'  repo_url: "{repo_url}"')
    lines.append('  outbox: ".cdmon/outbox.jsonl"')
    http_block = "\n".join(lines) + "\n"
    return CONFIG_TEMPLATE.replace(_OFFLINE_CENTRAL_BLOCK, http_block, 1)


def write_template(path: Path, content: str | None = None) -> None:
    """Write the documented starter config (or ``content``) to ``path``.

    ``content`` defaults to the offline :data:`CONFIG_TEMPLATE`; the G-01
    ``init --central`` path passes :func:`central_config_template` output, so
    WITHOUT ``--central`` the written bytes are unchanged (additive, K9).
    """
    try:
        path.write_text(
            content if content is not None else CONFIG_TEMPLATE, encoding="utf-8"
        )
    except OSError as exc:
        raise ConfigError(f"Cannot write config template to {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# CONFIG-V2 (N-01): the multi-file ``config/cdmon/`` layout.
#
# The dir layout is a *projection* onto the existing :class:`MonitorConfig`: an
# ``index.yaml`` (globals + an ordered list of unit files) plus N ``<unit>.yaml``
# unit files (each a ``---`` front-matter block + a body). Merging them yields
# exactly one :class:`MonitorConfig` so every downstream module (drift, coverage,
# heal, manifest, server) is untouched. The per-unit scoping fields
# (``dir_covered``, ``source_files_format``) ride along on the
# :class:`ConfigBundle` return seam for later slices (N-03/N-04) — they are not
# in :class:`MonitorConfig`. See ``.project/spec/CONFIGV2.md`` §0–§1.2.
# ---------------------------------------------------------------------------

#: Filename stems in ``config/cdmon/`` that are NOT coverage units: the index
#: itself plus the ``ignore``/``doc-style`` pointer files (CONFIG-V2 §1.2–§1.4).
#: They are excluded from the unit scan in both directions (reverse validation
#: and :func:`regenerate_index`).
RESERVED_UNIT_STEMS: frozenset[str] = frozenset({"index", "ignore", "doc-style"})


def _now() -> str:
    """Injectable wall-clock seam (ISO-8601 UTC) for the index ``updated`` field.

    Mirrors :func:`code_doc_monitor.monitor._default_now` and ``cli._now``; tests
    monkeypatch this module attribute so :func:`regenerate_index` is deterministic
    (K10). Production callers get the real wall clock.
    """
    return datetime.now(timezone.utc).isoformat()


def _scan_unit_files(config_dir: Path) -> list[str]:
    """Return the on-disk ``*.yaml`` unit filenames, sorted, reserved excluded.

    Deterministic (K10): alphabetical by filename. The reserved stems
    (:data:`RESERVED_UNIT_STEMS`) — the index and the ignore/doc-style pointers —
    are dropped so only true coverage units remain.
    """
    return sorted(
        p.name
        for p in config_dir.glob("*.yaml")
        if p.is_file() and p.stem not in RESERVED_UNIT_STEMS
    )


class UnitFrontmatter(BaseModel):
    """Traceability metadata for a unit file's ``---`` block (CONFIG-V2 §1.1)."""

    model_config = _V2_MODEL_CONFIG

    cdmon_config_version: str = Field(alias="cdmon-config-version")
    unit: str
    title: str
    owner: str
    created: str
    updated: str

    @model_validator(mode="after")
    def _version_must_match(self) -> UnitFrontmatter:
        if self.cdmon_config_version != CDMON_CONFIG_VERSION:
            raise ValueError(
                f"cdmon-config-version must be {CDMON_CONFIG_VERSION!r}, "
                f"got {self.cdmon_config_version!r}"
            )
        return self


class UnitFile(BaseModel):
    """One coverage UNIT: front matter + scope + documents (CONFIG-V2 §1.1).

    ``dir_covered`` is the (>=1) repo-relative directories this unit owns;
    ``source_files_format`` is the (>=1) extensions (each with a leading dot)
    that count toward coverage under those directories. ``documents`` reuses the
    existing :class:`DocumentSpec` schema verbatim.
    """

    model_config = _V2_MODEL_CONFIG

    frontmatter: UnitFrontmatter
    dir_covered: tuple[str, ...] = Field(alias="dir-covered")
    source_files_format: tuple[str, ...] = Field(alias="source-files-format")
    documents: tuple[DocumentSpec, ...]

    @model_validator(mode="after")
    def _validate_scope(self) -> UnitFile:
        if not self.dir_covered:
            raise ValueError("dir-covered must list at least one directory")
        bad = [d for d in self.dir_covered if not d.strip()]
        if bad:
            raise ValueError("dir-covered entries must be non-empty")
        if not self.source_files_format:
            raise ValueError("source-files-format must list at least one extension")
        no_dot = [e for e in self.source_files_format if not e.startswith(".")]
        if no_dot:
            raise ValueError(
                f"source-files-format entries must each start with '.': {no_dot!r}"
            )
        if not self.documents:
            raise ValueError("documents must list at least one document")
        return self


class IndexFrontmatter(BaseModel):
    """Traceability metadata for ``index.yaml``'s ``---`` block (§1.2)."""

    model_config = _V2_MODEL_CONFIG

    cdmon_config_version: str = Field(alias="cdmon-config-version")
    repo: str
    generated_by: str = Field(alias="generated-by")
    updated: str

    @model_validator(mode="after")
    def _version_must_match(self) -> IndexFrontmatter:
        if self.cdmon_config_version != CDMON_CONFIG_VERSION:
            raise ValueError(
                f"cdmon-config-version must be {CDMON_CONFIG_VERSION!r}, "
                f"got {self.cdmon_config_version!r}"
            )
        return self


class IndexUnitRef(BaseModel):
    """One entry in ``index.yaml``'s ``units:`` list — a unit filename (§1.2)."""

    model_config = _V2_MODEL_CONFIG

    file: str


class IndexFile(BaseModel):
    """``index.yaml`` — repo globals plus the ordered index of unit files (§1.2).

    Everything outside ``units`` mirrors :class:`MonitorConfig`'s global fields;
    the merge lifts them straight across. ``root`` is the repo root RELATIVE TO
    the directory the config lives in (``config/cdmon/``), so it defaults to
    ``"../.."`` (two levels up). This matches the single-file convention where
    ``root`` is relative to the config file's directory (default ``"."``) and the
    ONE :func:`resolve_repo_root` formula (``config_dir / root``, normalized).
    """

    model_config = _V2_MODEL_CONFIG

    frontmatter: IndexFrontmatter
    root: str = "../.."
    version: str = CDMON_CONFIG_VERSION
    apply_default: bool = False
    backend: BackendConfig = BackendConfig()
    agent: AgentConfig = AgentConfig()
    central: CentralConfig = CentralConfig()
    region_templates: dict[str, RegionTemplate] = {}
    coverage: CoverageConfig = CoverageConfig()
    fingerprint_body_tier: bool = False  # P-01: mirrors MonitorConfig (lifted in merge)
    units: tuple[IndexUnitRef, ...]
    ignore: str = "ignore.yaml"
    doc_style: str = Field(default="doc-style.yaml", alias="doc-style")


class ConfigBundle(BaseModel):
    """The full dir-layout load result: merged config + the source seams (N-01).

    ``config`` is the one merged :class:`MonitorConfig` downstream modules
    consume. ``index`` and ``units`` retain the per-unit scoping
    (``dir_covered``/``source_files_format``) and provenance so later slices
    (N-03 coverage scoping, N-04 ``.rpt``) need not re-read disk.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    config: MonitorConfig
    index: IndexFile
    units: tuple[UnitFile, ...]
    config_dir: str
    # CONFIG-V2 (N-05): the writing-template map, loaded from the index's
    # ``doc-style`` pointer when that file is present. ``None`` when absent so
    # every pre-N-05 bundle is unchanged (additive, K6). Typed concretely now
    # that the :mod:`docstyle` import is one-way (config -> docstyle -> _v2base,
    # Z-03), so downstream callers (monitor, cli) see ``DocStyleMap`` directly.
    doc_style: DocStyleMap | None = None

    def unit_for_document(self, doc_id: str) -> UnitFile | None:
        """Return the unit that declares ``doc_id``, or ``None`` if unknown."""
        for unit in self.units:
            if any(doc.id == doc_id for doc in unit.documents):
                return unit
        return None

    def unit_for_path(self, repo_relative_path: str) -> UnitFile | None:
        """Deepest-wins attribution of a repo-relative path to a unit (Z-01a).

        Thin method form of :func:`unit_for_path`: returns the unit whose
        ``dir-covered`` is the deepest ancestor of ``repo_relative_path`` (the
        longest matching directory prefix, by path components), or ``None``.
        """
        return unit_for_path(self, repo_relative_path)


def _load_v2_yaml(path: Path) -> tuple[dict, str]:
    """Read a dir-layout file and split its front matter (loud, K8)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc
    return _split_frontmatter(text, path)


def load_unit_file(path: Path) -> UnitFile:
    """Load and validate one ``<unit>.yaml`` unit file (CONFIG-V2 §1.1).

    Reads the front matter + body, builds a :class:`UnitFile`, and enforces that
    the front-matter ``unit`` equals the filename stem (loud :class:`ConfigError`
    otherwise, K8). All other structural rules (version, ``dir-covered`` >=1,
    ``source-files-format`` leading dots) are enforced by the models.
    """
    meta, body = _load_v2_yaml(path)
    data = _parse_v2_body(body, path)
    try:
        unit = UnitFile(frontmatter=UnitFrontmatter(**meta), **data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid unit file {path}:\n{exc}") from exc

    stem = path.stem
    if unit.frontmatter.unit != stem:
        raise ConfigError(
            f"unit {unit.frontmatter.unit!r} in {path} must equal the filename "
            f"stem {stem!r}"
        )
    return unit


def load_index_file(path: Path) -> IndexFile:
    """Load and validate ``index.yaml`` (CONFIG-V2 §1.2).

    Reads the front matter + body and builds an :class:`IndexFile`. Cross-file
    rules (listed unit present, duplicate ids, dir-covered overlap) are enforced
    by :func:`load_bundle`, which has every unit in hand.
    """
    meta, body = _load_v2_yaml(path)
    data = _parse_v2_body(body, path)
    try:
        return IndexFile(frontmatter=IndexFrontmatter(**meta), **data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid index file {path}:\n{exc}") from exc


def _dir_parts(p: str) -> tuple[str, ...]:
    """Normalize a repo-relative POSIX dir to its non-empty path components.

    Empty and ``.`` (current-dir) segments are dropped so equivalent spellings
    (``a/b``, ``./a/b/``, ``a//b``) normalize to the same components — the basis
    for the Z-01a identical-path conflict check (K10).
    """
    return tuple(
        part for part in p.replace("\\", "/").split("/") if part and part != "."
    )


def _is_ancestor(ancestor: tuple[str, ...], descendant: tuple[str, ...]) -> bool:
    """True if path-components ``ancestor`` are a (proper or equal) prefix of
    ``descendant`` BY COMPONENT (Z-01a, K10).

    Comparison is component-wise, never string-prefix, so ``a/agent`` is NOT an
    ancestor of ``a/agentry`` (the shared ``agent`` text is a different segment).
    """
    return descendant[: len(ancestor)] == ancestor


def _deepest_unit_for_parts(
    units: tuple[UnitFile, ...], file_parts: tuple[str, ...]
) -> UnitFile | None:
    """Shared deepest-wins resolver over pre-split path components (Z-01a, K10).

    The unit owning the LONGEST ``dir-covered`` (by components) that equals or is
    a strict ancestor of ``file_parts``; ``None`` if none. Ties on depth break by
    iteration order. Used by both :func:`unit_for_path` and
    :func:`effective_coverage`'s per-file format scoping.
    """
    best: UnitFile | None = None
    best_depth = -1
    for unit in units:
        for d in unit.dir_covered:
            dp = _dir_parts(d)
            if (
                len(dp) <= len(file_parts)
                and _is_ancestor(dp, file_parts)
                and len(dp) > best_depth
            ):
                best = unit
                best_depth = len(dp)
    return best


def unit_for_path(bundle: ConfigBundle, repo_relative_path: str) -> UnitFile | None:
    """Return the unit whose ``dir-covered`` is the DEEPEST ancestor of
    ``repo_relative_path`` (Z-01a deepest-wins attribution, K10).

    A file is attributed to the unit owning the LONGEST matching directory
    prefix (by path components, not string prefix — see :func:`_is_ancestor`).
    A directory that equals or contains the file's parent directory is a match;
    the file's own path components must start with the dir's components. With
    nested units (a parent ``dir-covered`` plus a child under it), a file under
    the child belongs to the CHILD; a file directly in the parent (not under the
    child) belongs to the parent. Ties on depth are broken by bundle order
    (deterministic). Returns ``None`` when no unit's ``dir-covered`` contains it.
    """
    return _deepest_unit_for_parts(bundle.units, _dir_parts(repo_relative_path))


def load_bundle(config_dir: Path) -> ConfigBundle:
    """Load a ``config/cdmon/`` directory into a :class:`ConfigBundle` (N-01).

    Algorithm (CONFIG-V2 §1.2):

    1. Read ``index.yaml`` (loud if absent).
    2. For each ``units[].file`` in order, :func:`load_unit_file` it (loud if a
       listed file is missing).
    3. Validate cross-file rules loudly (K8): duplicate document ``id`` across
       units, and ``dir-covered`` overlap across units.
    4. Merge into ONE :class:`MonitorConfig`: ``documents`` = concat of unit
       documents in index order then in-file order; the globals come from
       ``index.yaml``.
    """
    index_path = config_dir / "index.yaml"
    if not index_path.is_file():
        raise ConfigError(
            f"No index.yaml in config directory {config_dir}: a config/cdmon "
            "layout requires an index.yaml"
        )
    index = load_index_file(index_path)

    # Reverse invariant (N-02, K8): every on-disk unit file must be indexed. The
    # forward direction (an indexed file missing on disk) is enforced in the loop
    # below. Deterministic ordering (K10).
    listed = {ref.file for ref in index.units}
    on_disk = _scan_unit_files(config_dir)
    unindexed = [name for name in on_disk if name not in listed]
    if unindexed:
        raise ConfigError(
            f"Unit file(s) {unindexed!r} present in {config_dir} are not listed "
            f"in {index_path}'s units; run `cdmon index` to regenerate it"
        )

    units: list[UnitFile] = []
    for ref in index.units:
        unit_path = config_dir / ref.file
        if not unit_path.is_file():
            raise ConfigError(
                f"Unit file {ref.file!r} listed in {index_path} is missing "
                f"(expected at {unit_path})"
            )
        units.append(load_unit_file(unit_path))

    # Duplicate document id across all units → loud (K8).
    seen: dict[str, str] = {}
    documents: list[DocumentSpec] = []
    for unit, ref in zip(units, index.units, strict=True):
        for doc in unit.documents:
            if doc.id in seen:
                raise ConfigError(
                    f"duplicate document id {doc.id!r}: declared in both "
                    f"{seen[doc.id]!r} and {ref.file!r}"
                )
            seen[doc.id] = ref.file
            documents.append(doc)

    # dir-covered IDENTICAL across units → loud (Z-01a, K8). NESTING is now
    # allowed (a parent + a child dir-covered): a file is attributed to the
    # DEEPEST owning unit (see :func:`unit_for_path`). Only two units claiming
    # the SAME normalized directory genuinely conflict — neither could win the
    # deepest-match tie meaningfully — so that alone is the error. Compared by
    # path components so equivalent spellings (trailing slash, ``./``) collide.
    owners: dict[tuple[str, ...], str] = {}  # normalized parts -> unit-file
    for unit, ref in zip(units, index.units, strict=True):
        for d in unit.dir_covered:
            key = _dir_parts(d)
            if key in owners:
                raise ConfigError(
                    f"duplicate dir-covered: {d!r} (in {ref.file!r}) is the same "
                    f"directory as one in {owners[key]!r}; two units cannot share "
                    "an identical dir-covered path (nesting IS allowed, identical "
                    "is not)"
                )
            owners[key] = ref.file

    # Build the bundle with the index-level coverage first; then derive the
    # effective coverage (N-03: include from dir-covered × source-files-format,
    # exclude from ignore.yaml ∪ translated .gitignore ∪ defaults) and rebuild the
    # merged config so MonitorConfig.coverage IS the derived one. The intermediate
    # bundle gives effective_coverage the units + index in one object.
    base_config = MonitorConfig(
        version=index.version,
        root=index.root,
        documents=tuple(documents),
        region_templates=index.region_templates,
        backend=index.backend,
        agent=index.agent,
        central=index.central,
        apply_default=index.apply_default,
        coverage=index.coverage,
        fingerprint_body_tier=index.fingerprint_body_tier,
    )
    base_bundle = ConfigBundle(
        config=base_config,
        index=index,
        units=tuple(units),
        config_dir=str(config_dir),
    )
    repo_root = _resolve_repo_root(config_dir, index.root)
    coverage = effective_coverage(base_bundle, repo_root)
    config = base_config.model_copy(update={"coverage": coverage})

    # N-05: load the writing-template map when the index's doc-style pointer
    # names a present file. Absent ⇒ doc_style stays None (additive, K6). The
    # docstyle import is now one-way and module-level (Z-03: docstyle imports the
    # leaf _v2base, not config), so no lazy import is needed to break a cycle.
    doc_style: DocStyleMap | None = None
    doc_style_path = config_dir / index.doc_style
    if doc_style_path.is_file():
        templates_root = repo_root / "templates" / "writing"
        doc_style = load_doc_style(doc_style_path, templates_root=templates_root)

    return base_bundle.model_copy(update={"config": config, "doc_style": doc_style})


def load_config_dir(config_dir: Path) -> MonitorConfig:
    """Load a ``config/cdmon/`` directory into one merged :class:`MonitorConfig`.

    Thin wrapper over :func:`load_bundle`: ``load_config_dir(d) ==
    load_bundle(d).config``. Downstream modules consume the merged config and
    learn nothing about units (CONFIG-V2 §0).
    """
    return load_bundle(config_dir).config


# ---------------------------------------------------------------------------
# CONFIG-V2 (N-02): index regeneration (`cdmon index`).
#
# regenerate_index does TEXTUAL surgery on the existing index.yaml — it replaces
# only the frontmatter ``updated:`` line and the body ``units:`` block — so every
# global and every other frontmatter field is preserved byte-for-byte (the slice
# contract). A full parse→re-serialize round-trip would not be byte-stable, so it
# is deliberately avoided. The result is idempotent (K7): the rebuilt units list
# is deterministically sorted and the clock seam is the only moving part (and it
# is pinned in tests, K10).
# ---------------------------------------------------------------------------

# A top-level ``key:`` line followed by its (more-indented or blank) block lines.
# Used to splice the ``units:`` block out of the index body.
_UNITS_BLOCK_RE = re.compile(
    r"^units:[^\n]*\n(?:[ \t]+[^\n]*\n|[ \t]*\n)*", re.MULTILINE
)
# A top-level ``updated:`` frontmatter line (value replaced in place).
_UPDATED_LINE_RE = re.compile(r"^updated:[^\n]*$", re.MULTILINE)


def _render_units_block(filenames: list[str]) -> str:
    """Render a deterministic ``units:`` YAML block from sorted filenames (K10)."""
    if not filenames:
        return "units: []\n"
    lines = ["units:"]
    lines.extend(f"  - file: {name}" for name in filenames)
    return "\n".join(lines) + "\n"


def regenerate_index(config_dir: Path) -> str:
    """Return the index.yaml text with ``units:`` rebuilt from disk (N-02, K7/K10).

    Reads the existing ``index.yaml`` (loud if absent, K8), rescans the on-disk
    ``*.yaml`` units (sorted alphabetically, reserved stems excluded), and returns
    new index text where:

    * the body ``units:`` block lists exactly the on-disk units, sorted;
    * the frontmatter ``updated:`` field is refreshed via the injected :func:`_now`
      clock seam;
    * every other global and frontmatter field is preserved byte-for-byte.

    Pure except for the read + the clock; it does NOT write (see
    :func:`write_index`). Idempotent: ``regenerate_index`` over its own written
    output (same clock) is a fixed point.
    """
    index_path = config_dir / "index.yaml"
    if not index_path.is_file():
        raise ConfigError(
            f"No index.yaml in config directory {config_dir}: a config/cdmon "
            "layout requires an index.yaml"
        )
    try:
        text = index_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {index_path}: {exc}") from exc

    # Validate the existing file parses (loud K8) before rewriting it — never
    # clobber a structurally broken index with a half-understood one. The fence
    # span comes straight from the same regex the splitter uses, so the
    # frontmatter/body cut is exact even when the body is empty.
    _split_frontmatter(text, index_path)
    fence = _FM_RE.match(text)
    assert fence is not None  # _split_frontmatter already raised otherwise
    fm_text = text[: fence.end()]
    body = text[fence.end() :]

    filenames = _scan_unit_files(config_dir)
    new_block = _render_units_block(filenames)

    # Body: replace the existing units block, or append one if absent.
    if _UNITS_BLOCK_RE.search(body):
        new_body = _UNITS_BLOCK_RE.sub(lambda _m: new_block, body, count=1)
    else:
        sep = "" if body.endswith("\n") or body == "" else "\n"
        new_body = body + sep + new_block

    # Frontmatter: refresh updated in place (or insert before the closing fence).
    stamp = _now()
    if _UPDATED_LINE_RE.search(fm_text):
        new_fm = _UPDATED_LINE_RE.sub(f'updated: "{stamp}"', fm_text, count=1)
    else:
        # No updated line: insert one just before the closing ``---\n`` fence so
        # it lands inside the frontmatter block (rindex finds the closing fence).
        close = fm_text.rindex("---\n")
        new_fm = fm_text[:close] + f'updated: "{stamp}"\n' + fm_text[close:]

    return new_fm + new_body


def write_index(config_dir: Path, text: str) -> None:
    """Write ``text`` to ``config_dir/index.yaml`` (loud on OSError, K8)."""
    index_path = config_dir / "index.yaml"
    try:
        index_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot write index file {index_path}: {exc}") from exc


# ---------------------------------------------------------------------------
# CONFIG-V2 (N-03): ignore.yaml + .gitignore merge + source-files-format scoping.
#
# The whole point: derive MonitorConfig.coverage.include/exclude/waive PURELY
# from the dir layout so the EXISTING coverage engine (inventory.discover_files →
# discover_symbols → coverage.resolve_coverage) is untouched (CONFIG-V2 §1.1/§1.3).
#
#   include  = for each unit, each dir-covered d × each source-files-format ext,
#              the glob ``d/**/*ext``. Verified against inventory._translate:
#              ``d/**/*.py`` matches BOTH a file directly in d AND a nested one
#              (``**/`` is zero-or-more leading segments), so one form covers both.
#   exclude  = ignore.patterns ∪ (gitignore_to_globs(.gitignore) when
#              ignore.gitignore and the file exists) ∪ the default excludes
#              (dot-dirs / __pycache__ / .venv stay out regardless).
#   waive    = index.coverage.waive (unchanged).
#
# gitignore_to_globs is a HAND-ROLLED translation (K0 — no new dep) that emits
# globs in inventory's exact ``**`` semantics (confirmed empirically against
# inventory._translate). Output is deterministic: sorted + deduped (K10).
# ---------------------------------------------------------------------------


class IgnoreFrontmatter(BaseModel):
    """Traceability metadata for ``ignore.yaml``'s ``---`` block (§1.3)."""

    model_config = _V2_MODEL_CONFIG

    cdmon_config_version: str = Field(alias="cdmon-config-version")
    source: str
    updated: str

    @model_validator(mode="after")
    def _version_must_match(self) -> IgnoreFrontmatter:
        if self.cdmon_config_version != CDMON_CONFIG_VERSION:
            raise ValueError(
                f"cdmon-config-version must be {CDMON_CONFIG_VERSION!r}, "
                f"got {self.cdmon_config_version!r}"
            )
        return self


class IgnoreFile(BaseModel):
    """``ignore.yaml`` — manual ignore globs + optional ``.gitignore`` merge (§1.3).

    ``patterns`` are manual ignore globs in inventory ``**`` semantics; when
    ``gitignore`` is true the repo ``.gitignore`` is parsed (via
    :func:`gitignore_to_globs`) and merged into the coverage ``exclude`` set. A
    file matching the effective ignore set is removed from the coverage universe
    (never "uncovered").
    """

    model_config = _V2_MODEL_CONFIG

    frontmatter: IgnoreFrontmatter
    gitignore: bool = False
    patterns: tuple[str, ...] = ()


def load_ignore_file(path: Path) -> IgnoreFile:
    """Load and validate ``ignore.yaml`` (CONFIG-V2 §1.3, loud K8).

    Reads the front matter + body and builds an :class:`IgnoreFile`. A missing
    file, a missing/malformed front-matter fence, a wrong ``cdmon-config-version``,
    or an unknown key all raise a typed :class:`ConfigError`.
    """
    meta, body = _load_v2_yaml(path)
    data = _parse_v2_body(body, path)
    try:
        return IgnoreFile(frontmatter=IgnoreFrontmatter(**meta), **data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid ignore file {path}:\n{exc}") from exc


def gitignore_to_globs(text: str) -> tuple[str, ...]:
    """Translate ``.gitignore`` text to inventory ``**``-glob form (K0, K10).

    A hand-rolled translation (NO new dependency) into the EXACT ``**`` semantics
    of :func:`code_doc_monitor.inventory._translate` (``**/`` = zero-or-more
    leading path segments, ``*``/``?`` = within one segment). Per line:

    * blank lines and ``#`` comments → skipped;
    * negations (``!...``) → emit nothing (un-ignoring is not modeled here);
    * a trailing ``/`` (a directory) → the directory's contents anywhere:
      bare ``__pycache__/`` → ``**/__pycache__/**``; an embedded-path
      ``build/`` → ``build/**``; a root-anchored ``/dist/`` → ``dist/**``;
    * a leading ``/`` (root-anchored) → the entry itself plus its contents
      (``/dist`` → ``dist`` and ``dist/**``);
    * an embedded ``/`` (a path, not anchored) → the entry as-is plus its
      contents (``docs/build`` → ``docs/build`` and ``docs/build/**``); a path
      already carrying a wildcard (``docs/**/*.html``) is kept verbatim (its
      ``/**`` companion would be redundant noise);
    * a bare token (no slash) → match a file OR directory of that name anywhere
      plus the directory's contents (``build`` → ``**/build`` and
      ``**/build/**``); ``*.log`` → ``**/*.log``.

    Output is sorted + deduped (deterministic, K10).
    """
    globs: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            # Negation / un-ignore — not modeled by an exclude set; emit nothing.
            continue

        is_dir = line.endswith("/")
        anchored = line.startswith("/")
        body = line.strip("/")
        if not body:
            continue  # a lone "/" (or "///") — nothing meaningful to ignore.
        has_slash = "/" in body
        has_wildcard = "*" in body or "?" in body

        if is_dir:
            # A directory: ignore everything under it.
            if anchored or has_slash:
                globs.add(f"{body}/**")
            else:
                globs.add(f"**/{body}/**")
            continue

        if anchored:
            # Root-anchored file-or-dir: the entry plus its contents.
            globs.add(body)
            globs.add(f"{body}/**")
        elif has_slash:
            # An embedded-path entry: keep as-is; add a contents glob unless it
            # already carries a wildcard (then it is already a precise pattern).
            globs.add(body)
            if not has_wildcard:
                globs.add(f"{body}/**")
        else:
            # A bare token anywhere. A wildcard token (``*.log``) is a file
            # pattern — emit just it; a literal token (``build``) may be a dir,
            # so add its contents companion too.
            globs.add(f"**/{body}")
            if not has_wildcard:
                globs.add(f"**/{body}/**")

    return tuple(sorted(globs))


def resolve_repo_root(config_dir: Path, root: str) -> Path:
    """The ONE repo-root resolver: ``normpath(config_dir / root)`` (N-06).

    ``root`` is the repo root RELATIVE TO the directory the config lives in. This
    is the single formula every consumer shares — :class:`Monitor`,
    :func:`drift.detect`, :func:`effective_coverage`, the doc-style
    ``templates_root``, and ``cdmon rpt`` — so the dir layout and the single-file
    layout can never diverge again (the N-06 defect):

    * single-file: ``config_dir`` IS the repo, ``root = "."`` ⇒ the repo;
    * dir layout: ``config_dir`` is ``<repo>/config/cdmon``, ``root = "../.."``
      ⇒ the repo.

    Normalized so ``.gitignore``, the coverage scan, and the unit ``dir-covered``
    paths all resolve against the same directory.
    """
    return Path(os.path.normpath(Path(config_dir) / root))


def _resolve_repo_root(config_dir: Path, root: str) -> Path:
    """Back-compat alias for :func:`resolve_repo_root` (N-06 unification).

    Existing callers (``effective_coverage``, ``report.report_repo_root``,
    ``monitor``) imported this private name; it now delegates to the single
    public resolver so there is exactly ONE formula.
    """
    return resolve_repo_root(config_dir, root)


def effective_coverage(bundle: ConfigBundle, repo_root: Path) -> CoverageConfig:
    """Derive the coverage scan scope purely from the dir layout (N-03, K10).

    * ``include`` — for each unit, each ``dir-covered`` directory ``d`` and each
      ``source-files-format`` extension ``ext``, the glob ``d/**/*ext`` (which
      matches a file BOTH directly in ``d`` and in any nested subdir under the
      inventory ``**`` semantics). Sorted + deduped.
    * ``exclude`` — ``ignore.patterns`` ∪ (``gitignore_to_globs(repo_root/.gitignore)``
      when ``ignore.gitignore`` is true and the file exists) ∪ the existing
      default excludes (dot-dirs / ``__pycache__`` / ``.venv``). Sorted + deduped.
    * ``waive`` — carried unchanged from ``index.coverage.waive``.

    The result feeds the UNTOUCHED coverage engine: a file under a unit's
    ``dir-covered`` whose extension is not in that unit's ``source-files-format``
    never enters the include set, so it is never "uncovered"; an ignored file is
    excluded the same way. Pure except for the single ``.gitignore`` read.

    **Deepest-wins format scoping (Z-01a).** With NESTED ``dir-covered`` (a parent
    unit plus a child unit under it), each file's formats are the DEEPEST owning
    unit's — not the parent's. A parent ``d/**/*ext`` include glob would otherwise
    pull a file under the child dir whose ext the parent scopes but the CHILD does
    not. Because the coverage engine applies exclude-wins-over-include, this is
    expressed as a derived EXCLUDE: for each unit dir ``d`` and each extension
    ``ext`` that the include universe carries but ``d``'s OWN unit does not scope,
    exclude ``d/**/*ext`` — UNLESS a strictly-deeper unit dir under ``d`` DOES
    scope ``ext`` (excluding would wrongly drop that descendant's files). The
    decision is per-deepest-unit, mirroring :func:`unit_for_path`.
    """
    includes: set[str] = set()
    all_exts: set[str] = set()
    for unit in bundle.units:
        all_exts.update(unit.source_files_format)
        for d in unit.dir_covered:
            clean = d.replace("\\", "/").strip("/")
            for ext in unit.source_files_format:
                includes.add(f"{clean}/**/*{ext}")

    excludes: set[str] = set(_DEFAULT_EXCLUDE)

    # Deepest-wins format scoping (Z-01a): exclude an ext under a unit dir when
    # that unit does not scope it, unless a strictly-deeper unit dir re-scopes it.
    # ``(dir-parts, formats)`` for every unit dir, precomputed once.
    dir_scopes: list[tuple[tuple[str, ...], frozenset[str]]] = [
        (_dir_parts(d), frozenset(unit.source_files_format))
        for unit in bundle.units
        for d in unit.dir_covered
    ]
    for parts, formats in dir_scopes:
        clean = "/".join(parts)
        for ext in all_exts:
            if ext in formats:
                continue
            deeper_rescopes = any(
                len(other) > len(parts)
                and _is_ancestor(parts, other)
                and ext in other_formats
                for other, other_formats in dir_scopes
            )
            if not deeper_rescopes:
                excludes.add(f"{clean}/**/*{ext}")

    # The ignore pointer is a filename in config/cdmon/ (default "ignore.yaml").
    ignore_path = Path(bundle.config_dir) / bundle.index.ignore
    if ignore_path.is_file():
        ignore = load_ignore_file(ignore_path)
        excludes.update(ignore.patterns)
        if ignore.gitignore:
            gitignore_path = repo_root / ".gitignore"
            if gitignore_path.is_file():
                try:
                    gitignore_text = gitignore_path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise ConfigError(
                        f"Cannot read .gitignore at {gitignore_path}: {exc}"
                    ) from exc
                excludes.update(gitignore_to_globs(gitignore_text))

    return CoverageConfig(
        include=tuple(sorted(includes)),
        exclude=tuple(sorted(excludes)),
        waive=bundle.index.coverage.waive,
    )


# ---------------------------------------------------------------------------
# EDITOR (E-01): unit-file YAML serializer + pure model editors.
#
# The ONE new config primitive the EDITOR feature needs (EDITOR §2): turn a
# :class:`UnitFile` model back into the canonical ``---``-fenced front-matter +
# body text such that ``load_unit_file(write(dump_unit_file(u))) == u`` (a true
# round-trip) and a second dump is byte-identical (idempotent, K7). The body is
# emitted with a deterministic, hand-ordered key layout (NOT pydantic's
# ``model_dump`` order) so the output is stable and human-diffable. The editors
# below are PURE: each returns a NEW frozen :class:`UnitFile` (no mutation), so
# the server can compose edits then dump once.
# ---------------------------------------------------------------------------


def _coderef_to_yaml(ref: CodeRef) -> dict:
    """Render a :class:`CodeRef` to a minimal ordered dict (defaults dropped).

    Only non-default selectors are emitted so a whole-file ref serializes to just
    ``{path: ...}`` and reloads identically. Tuples become plain lists / lists of
    lists (``lines``) so :func:`yaml.safe_dump` accepts them.
    """
    out: dict[str, object] = {"path": ref.path}
    if ref.symbols:
        out["symbols"] = list(ref.symbols)
    if ref.lines:
        out["lines"] = [list(pair) for pair in ref.lines]
    if ref.names:
        out["names"] = list(ref.names)
    if ref.arg_signature:
        out["arg_signature"] = list(ref.arg_signature)
    if ref.extract != "symbols":
        out["extract"] = ref.extract
    if ref.lang != "auto":
        out["lang"] = ref.lang
    if ref.json_records is not None:
        out["json_records"] = ref.json_records
    if ref.record_name_field != "name":
        out["record_name_field"] = ref.record_name_field
    return out


def _contextref_to_yaml(ref: ContextRef) -> dict:
    """Render a :class:`ContextRef` to a minimal ordered dict (note dropped if None)."""
    out: dict[str, object] = {"path": ref.path}
    if ref.note is not None:
        out["note"] = ref.note
    return out


def _document_to_yaml(doc: DocumentSpec) -> dict:
    """Render a :class:`DocumentSpec` to a minimal ordered dict (defaults dropped).

    Deterministic key order: id, path, audience, then the optional structural
    fields, then code_refs / context_refs / region_keys / region_modes. Only
    non-default fields are emitted so the dump round-trips and stays minimal.
    """
    out: dict[str, object] = {
        "id": doc.id,
        "path": doc.path,
        "audience": doc.audience.value,
    }
    if doc.index:
        out["index"] = True
    if doc.html:
        out["html"] = True
    if doc.nav_section is not None:
        out["nav_section"] = doc.nav_section
    if doc.nav_label is not None:
        out["nav_label"] = doc.nav_label
    if doc.owner is not None:
        out["owner"] = doc.owner
    if doc.team is not None:
        out["team"] = doc.team
    if doc.dri is not None:
        out["dri"] = doc.dri
    if doc.region_keys:
        out["region_keys"] = list(doc.region_keys)
    if doc.region_modes:
        out["region_modes"] = {k: v.value for k, v in doc.region_modes.items()}
    if doc.code_refs:
        out["code_refs"] = [_coderef_to_yaml(r) for r in doc.code_refs]
    if doc.context_refs:
        out["context_refs"] = [_contextref_to_yaml(r) for r in doc.context_refs]
    return out


def dump_unit_file(unit: UnitFile, *, now: str) -> str:
    """Serialize a :class:`UnitFile` to canonical ``config/cdmon/<unit>.yaml`` text.

    Returns the full ``---``-fenced front matter + body YAML such that
    ``load_unit_file`` of the written text round-trips to an EQUAL model
    (documents, code_refs WITH symbols/lines, context_refs, region_keys,
    region_modes, audience, dir-covered, source-files-format all preserved).
    Deterministic key order and idempotent (K7): dumping a loaded-then-dumped
    unit is byte-identical. The front-matter ``updated:`` field is refreshed to
    ``now`` (the injected clock seam, K10); every other front-matter field is
    carried through unchanged. Uses the existing ``cdmon-config-version`` and the
    shared ``---`` fence format (:func:`_split_frontmatter` re-parses it).
    """
    fm = unit.frontmatter
    fm_lines = [
        "---",
        f"cdmon-config-version: {_yaml_scalar(fm.cdmon_config_version)}",
        f"unit: {_yaml_scalar(fm.unit)}",
        f"title: {_yaml_scalar(fm.title)}",
        f"owner: {_yaml_scalar(fm.owner)}",
        f"created: {_yaml_scalar(fm.created)}",
        f"updated: {_yaml_scalar(now)}",
        "---",
    ]
    body_obj: dict[str, object] = {
        "dir-covered": list(unit.dir_covered),
        "source-files-format": list(unit.source_files_format),
        "documents": [_document_to_yaml(doc) for doc in unit.documents],
    }
    body = yaml.safe_dump(
        body_obj,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    return "\n".join(fm_lines) + "\n" + body


def _yaml_scalar(value: str) -> str:
    """Quote a scalar string the way :func:`yaml.safe_dump` would, deterministically.

    Used for the hand-built front-matter lines so a value needing quoting (a
    date-like ``2026-06-07``, a string with special chars) is emitted exactly as
    PyYAML would, keeping the dump idempotent and re-parseable.
    """
    dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True)
    # safe_dump of a bare scalar appends a trailing "\n...\n"; strip the document
    # end marker and newline to get just the (possibly-quoted) scalar token.
    return dumped.replace("\n...\n", "").rstrip("\n")


def _replace_documents(unit: UnitFile, documents: tuple[DocumentSpec, ...]) -> UnitFile:
    """Return a NEW :class:`UnitFile` with ``documents`` replaced (no mutation)."""
    return unit.model_copy(update={"documents": documents})


def _find_doc_index(unit: UnitFile, doc_id: str) -> int:
    """Index of the document with ``doc_id``, or a loud :class:`ConfigError` (K8)."""
    for i, doc in enumerate(unit.documents):
        if doc.id == doc_id:
            return i
    raise ConfigError(
        f"document id {doc_id!r} not found in unit {unit.frontmatter.unit!r}"
    )


def upsert_document(unit: UnitFile, doc: DocumentSpec) -> UnitFile:
    """Add ``doc`` to ``unit`` (or REPLACE the existing entry with the same id).

    Pure: returns a NEW frozen :class:`UnitFile`. Replacement keeps the original
    position; a new id is appended in order (deterministic, K10).
    """
    docs = list(unit.documents)
    for i, existing in enumerate(docs):
        if existing.id == doc.id:
            docs[i] = doc
            return _replace_documents(unit, tuple(docs))
    docs.append(doc)
    return _replace_documents(unit, tuple(docs))


def add_code_ref(unit: UnitFile, doc_id: str, ref: CodeRef) -> UnitFile:
    """Append ``ref`` to the named document's ``code_refs`` (pure, new model).

    Loud :class:`ConfigError` if ``doc_id`` is unknown (K8).
    """
    i = _find_doc_index(unit, doc_id)
    doc = unit.documents[i]
    new_doc = doc.model_copy(update={"code_refs": (*doc.code_refs, ref)})
    docs = list(unit.documents)
    docs[i] = new_doc
    return _replace_documents(unit, tuple(docs))


def remove_code_ref(unit: UnitFile, doc_id: str, path: str) -> UnitFile:
    """Drop every ``code_refs`` entry with ``path`` from the named document.

    Loud :class:`ConfigError` if ``doc_id`` is unknown, or if no ``code_refs``
    entry matches ``path`` (removing a ref that is not there is a mistake, K8).
    """
    i = _find_doc_index(unit, doc_id)
    doc = unit.documents[i]
    kept = tuple(r for r in doc.code_refs if r.path != path)
    if len(kept) == len(doc.code_refs):
        raise ConfigError(
            f"document {doc_id!r}: no code_ref with path {path!r} to remove"
        )
    new_doc = doc.model_copy(update={"code_refs": kept})
    docs = list(unit.documents)
    docs[i] = new_doc
    return _replace_documents(unit, tuple(docs))


def set_context_refs(
    unit: UnitFile, doc_id: str, refs: tuple[ContextRef, ...]
) -> UnitFile:
    """Replace the named document's ``context_refs`` wholesale (pure, new model).

    Loud :class:`ConfigError` if ``doc_id`` is unknown (K8). The replacement runs
    through the model so a duplicate path in ``refs`` is rejected loudly.
    """
    i = _find_doc_index(unit, doc_id)
    doc = unit.documents[i]
    try:
        new_doc = doc.model_copy(update={"context_refs": tuple(refs)})
        # Force re-validation of the dup-path rule (model_copy skips validators).
        new_doc = DocumentSpec(**new_doc.model_dump())
    except (ValidationError, ValueError) as exc:
        raise ConfigError(f"document {doc_id!r}: invalid context_refs: {exc}") from exc
    docs = list(unit.documents)
    docs[i] = new_doc
    return _replace_documents(unit, tuple(docs))
