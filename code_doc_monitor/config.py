"""Config models, loader, and starter template (K0, K8, K10).

Everything the engine needs to know about a target codebase enters through a
single YAML or JSON config file (K0). The models below mirror the contracts in
ARCHITECTURE.md exactly. They are frozen and forbid unknown keys so a typo or a
stale field raises a loud, typed :class:`ConfigError` (K8).
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .errors import ConfigError

__all__ = [
    "Audience",
    "CodeRef",
    "BackendConfig",
    "CentralConfig",
    "RegionColumn",
    "RegionTemplate",
    "DocumentSpec",
    "MonitorConfig",
    "load_config",
    "write_template",
    "CONFIG_TEMPLATE",
]

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
    lang: Literal["auto", "python", "shell", "tcl", "json"] = "auto"
    json_records: str | None = None  # list-valued key, or "*"
    record_name_field: str = "name"  # which json field identifies a row


class BackendConfig(BaseModel):
    """Which LLM backend produces verdicts. Offline ``mock`` by default (K4)."""

    model_config = _MODEL_CONFIG

    kind: Literal["mock", "claude-code", "api"] = "mock"
    model: str | None = None
    command: tuple[str, ...] | None = None  # claude-code argv template
    timeout_s: int = 120
    extra: dict[str, str] = {}


class CentralConfig(BaseModel):
    """Where review records are emitted. Offline ``none`` by default (K4)."""

    model_config = _MODEL_CONFIG

    sink: Literal["none", "file", "http"] = "none"
    path: str | None = None  # file sink
    url: str | None = None  # http sink
    auth_env: str | None = None  # env var holding a bearer token


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


class DocumentSpec(BaseModel):
    """One logical document: an id, a path, an audience, and code refs."""

    model_config = _MODEL_CONFIG

    id: str
    path: str  # repo-relative doc path
    audience: Audience
    code_refs: tuple[CodeRef, ...] = ()  # empty for an index/collection doc
    region_keys: tuple[str, ...] = ()  # managed regions this doc carries
    html: bool = False  # does this doc have a derived .html twin? (layout standard)
    index: bool = False  # landing page that must link every other document
    nav_section: str | None = None  # group heading in the html-twin sidebar
    nav_label: str | None = None  # short sidebar label (falls back to the title)


class MonitorConfig(BaseModel):
    """Top-level config: documents plus backend/central/apply settings."""

    model_config = _MODEL_CONFIG

    version: str = "1.0.0"
    root: str = "."  # repo root, relative to the config file
    documents: tuple[DocumentSpec, ...]
    region_templates: dict[str, RegionTemplate] = {}  # region id -> table template
    backend: BackendConfig = BackendConfig()
    central: CentralConfig = CentralConfig()
    apply_default: bool = False  # monitor auto-applies FIX by default?


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

# Which LLM backend produces verdicts for detected drift.
#   mock        -> deterministic, offline (default; used in CI/tests)
#   claude-code -> headless `claude -p` subprocess (set `command`)
#   api         -> Anthropic Messages API (key from env)
backend:
  kind: "mock"
  # model: "claude-sonnet-4"
  # command: ["claude", "-p"]
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
"""


def write_template(path: Path) -> None:
    """Write the documented starter config to ``path``."""
    try:
        path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot write config template to {path}: {exc}") from exc
