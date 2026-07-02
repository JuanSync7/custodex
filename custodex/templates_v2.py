"""Canonical ``config/cdmon/`` v2 templates + the dir scaffolder (W-02).

ONE authoritative, tested source for the multi-file ``config/cdmon/`` layout
(CONFIG-V2 §1.1–§1.4). Each template string is a well-commented canonical
example that ROUND-TRIPS through its N-01..N-05 loader:

* :data:`UNIT_TEMPLATE`     → :func:`custodex.config.load_unit_file`
* :data:`INDEX_TEMPLATE`    → :func:`custodex.config.load_index_file`
* :data:`IGNORE_TEMPLATE`   → :func:`custodex.config.load_ignore_file`
* :data:`DOC_STYLE_TEMPLATE`→ :func:`custodex.docstyle.load_doc_style`

:data:`V2_TEMPLATES` aggregates the four for the ``GET /config/templates``
endpoint and the dashboard Config page (W-02 Part B). The strings are
DETERMINISTIC (K10): no wall-clock, no env — the only moving parts are the
``{repo}`` / ``{now}`` placeholders, substituted by :func:`scaffold_config_dir`
when it materializes a complete, ``load_bundle``-valid directory (K7).

The ``root: "../.."`` convention is canonical: ``config/cdmon/`` lives two
levels below the repo root, so the ONE :func:`custodex.config.resolve_repo_root`
formula (``config_dir / root``) lands on the repo (CONFIG-V2 §1.2). The
doc-style template references writing templates that ALREADY exist under the
repo's ``templates/writing/`` (api-reference / precise / reference-dense /
engine-domain), so a scaffolded dir validates against a repo that ships them.
"""

from __future__ import annotations

from pathlib import Path

from .errors import ConfigError

__all__ = [
    "UNIT_TEMPLATE",
    "INDEX_TEMPLATE",
    "IGNORE_TEMPLATE",
    "DOC_STYLE_TEMPLATE",
    "EXAMPLE_UNIT_STEM",
    "V2_TEMPLATES",
    "WRITING_TEMPLATE_STEMS",
    "ensure_writing_templates",
    "scaffold_config_dir",
]

#: The example unit's filename stem. The unit frontmatter ``unit:`` MUST equal
#: the filename stem (loud K8 in :func:`load_unit_file`), and ``index.yaml``
#: lists ``<stem>.yaml`` — so the scaffolded dir is internally consistent.
EXAMPLE_UNIT_STEM = "example"


# ---------------------------------------------------------------------------
# Unit file — `<unit>.yaml` (CONFIG-V2 §1.1).
#
# A coverage UNIT: a `---` frontmatter block of traceability metadata, then a
# body declaring the directories it owns, the source extensions that count
# toward coverage, and its documents (the existing DocumentSpec schema). The
# `{repo}`/`{now}` placeholders are filled by `scaffold_config_dir`; left as-is
# the template is still valid YAML (round-trips with the placeholders present —
# they are plain strings).
# ---------------------------------------------------------------------------
UNIT_TEMPLATE = """\
---
# Frontmatter (REQUIRED, fenced by --- ... ---): traceability metadata.
cdmon-config-version: "2.0.0"          # REQUIRED, must be "2.0.0"
unit: example                          # REQUIRED, MUST equal this file's stem
title: "Example coverage unit"         # REQUIRED, human title
owner: your-team                       # REQUIRED, team/person accountable
created: "{now}"                       # REQUIRED ISO date
updated: "{now}"                       # REQUIRED ISO date
---
# Body: what this unit covers + the documents it owns.

# >=1 repo-relative directories this unit OWNS. dir-covered scopes which files
# the coverage scan attributes to this unit; they MUST be disjoint across units
# (a file belongs to at most one unit — loud error on overlap).
dir-covered:
  - src/example

# >=1 file extensions (each WITH a leading dot) that count toward coverage under
# dir-covered. A file under dir-covered whose extension is NOT listed here is
# EXCLUDED from the coverage denominator (so .log / .rpt never read "uncovered").
source-files-format:
  - ".py"

# >=1 documents (the same DocumentSpec schema as the single-file config). Each
# document's code_refs SHOULD live under this unit's dir-covered.
documents:
  - id: example-guide
    path: docs/example-guide.md
    audience: eng-guide                # user-guide | eng-guide
    region_keys: ["symbols"]           # managed CDM:BEGIN/END regions this doc carries
    code_refs:
      # Whole file (no selectors): the module's entire symbol surface.
      - path: src/example/core.py
      # Named symbols only: just these functions/classes.
      - path: src/example/api.py
        symbols: ["create_client", "Client"]
    # context_refs (OPTIONAL, additive): sibling docs / source files to glance
    # through when generating this document. They are GENERATION CONTEXT only —
    # never counted in coverage, drift, or the .rpt (EDITOR §1). Repo-relative
    # paths; not resolved for existence at load (may point at a not-yet-made doc).
    # context_refs:
    #   - path: docs/api/core-api.md
    #     note: "link to the full engine reference"
    #   - path: src/example/engine.py
    #     note: "scheduling semantics referenced in the tour"
"""


# ---------------------------------------------------------------------------
# index.yaml — globals + the ordered index of every unit file (CONFIG-V2 §1.2).
# ---------------------------------------------------------------------------
INDEX_TEMPLATE = """\
---
# Frontmatter (REQUIRED): repo identity + provenance.
cdmon-config-version: "2.0.0"          # REQUIRED
repo: "{repo}"                         # REQUIRED, repo id/name
generated-by: cdx                    # REQUIRED provenance string
updated: "{now}"                       # REQUIRED
---
# Body: the globals that merge into one MonitorConfig + the unit index.

# Repo root RELATIVE TO this config directory. config/cdmon/ sits two levels
# below the repo root, so the canonical default is "../..". The ONE resolver
# resolve_repo_root(config_dir, root) lands every consumer on the same root.
root: "../.."

version: "2.0.0"
apply_default: false                   # does `cdx monitor` auto-apply fixes?

# Which LLM backend produces drift verdicts (mock = offline default, used in CI).
backend:
  kind: mock

# The LangGraph remediation-agent runtime (only used when backend.kind: agent).
agent:
  driver: claude-code

# Where handled-drift review records are emitted (none = local log only).
central:
  sink: none

# Global coverage block: intentional, justified documentation gaps (waivers).
coverage:
  waive:
    - path: "src/example/__init__.py"
      reason: "re-export aggregator; documented upstream"

# REQUIRED index of every unit file in this directory (stable, ordered). Every
# *.yaml unit on disk MUST be listed and every listed file MUST exist
# (`cdx index` regenerates this). Reserved stems (index/ignore/doc-style) are
# NOT units.
units:
  - file: example.yaml

# Pointers to the ignore + doc-style files (defaults shown).
ignore: ignore.yaml
doc-style: doc-style.yaml
"""


# ---------------------------------------------------------------------------
# ignore.yaml — manual ignore globs + optional .gitignore merge (CONFIG-V2 §1.3).
# ---------------------------------------------------------------------------
IGNORE_TEMPLATE = """\
---
# Frontmatter (REQUIRED): provenance.
cdmon-config-version: "2.0.0"          # REQUIRED
source: ".gitignore + manual"          # REQUIRED provenance
updated: "{now}"                       # REQUIRED
---
# Body: the effective ignore set = patterns ∪ (.gitignore globs when gitignore:
# true). A file matching the ignore set is removed from the coverage universe —
# it is never reported as "uncovered".

gitignore: true                        # merge the repo .gitignore patterns in
patterns:                              # manual ignore globs (inventory ** semantics)
  - "**/__pycache__/**"
  - "**/.venv/**"
  - "*.rpt"
"""


# ---------------------------------------------------------------------------
# doc-style.yaml — writing-template mapping (CONFIG-V2 §1.4).
#
# Each name resolves to templates/writing/<category>/<name>.md. The names below
# (api-reference / precise / reference-dense / engine-domain) reference writing
# templates that ALREADY exist in the repo, so the map validates loudly only if
# they are removed (K8).
# ---------------------------------------------------------------------------
DOC_STYLE_TEMPLATE = """\
---
# Frontmatter (REQUIRED).
cdmon-config-version: "2.0.0"          # REQUIRED
kind: doc-style-map                    # REQUIRED literal
updated: "{now}"                       # REQUIRED
---
# Body: one writing template per category, per document. The four categories are
# document-type, tone, writing-style, vocabulary; each value names a stem under
# templates/writing/<category>/<stem>.md.

# defaults: used for any document without an explicit mapping below.
defaults:
  document-type: api-reference
  tone: precise
  writing-style: reference-dense
  vocabulary: engine-domain

# Per-document overrides (doc = a document id from a unit file).
mappings:
  - doc: example-guide
    document-type: api-reference
    tone: precise
    writing-style: reference-dense
    vocabulary: engine-domain
"""


#: The four canonical templates, keyed for ``GET /config/templates`` (W-02) and
#: the dashboard Config page. Order is fixed/deterministic (K10).
V2_TEMPLATES: dict[str, str] = {
    "unit": UNIT_TEMPLATE,
    "index": INDEX_TEMPLATE,
    "ignore": IGNORE_TEMPLATE,
    "doc_style": DOC_STYLE_TEMPLATE,
}


def _fill(template: str, *, repo: str, now: str) -> str:
    """Substitute the ``{repo}`` / ``{now}`` placeholders in a template (K10).

    The templates carry ONLY the ``{repo}`` and ``{now}`` ``str.format``
    placeholders (the globals use block-style YAML, so there are no literal
    braces to escape). Deterministic: the only inputs are ``repo`` and ``now``.
    The placeholders are quoted in the templates, so a RAW (unfilled) template is
    still valid YAML that round-trips through its loader.
    """
    return template.format(repo=repo, now=now)


#: The writing-template files ``DOC_STYLE_TEMPLATE`` references — (category dir,
#: stem) pairs under ``templates/writing/``. Kept in ONE place so the scaffold's
#: doc-style map and the ensured files can never drift apart (K8).
WRITING_TEMPLATE_STEMS: tuple[tuple[str, str], ...] = (
    ("document-type", "api-reference"),
    ("tone", "precise"),
    ("writing-style", "reference-dense"),
    ("vocabulary", "engine-domain"),
)

#: Minimal, generic bodies for the ensured writing templates. Deliberately
#: target-agnostic (K0): an adopter refines them; the scaffold only guarantees
#: the doc-style map LOADS in a bare repo.
_WRITING_TEMPLATE_BODY = """\
# {stem} ({category})

Guidance for the `{stem}` {category} writing template. Replace this generic
scaffold with your team's real guidance — the doc-style map in
`config/cdmon/doc-style.yaml` selects it per document, and the authoring
backend reads it when writing `llm`-mode prose.
"""


def ensure_writing_templates(repo_root: Path) -> tuple[Path, ...]:
    """Write the doc-style map's referenced writing templates IF ABSENT (AGT-04).

    The ``cdx init --v2`` DOA fix: the scaffolded ``doc-style.yaml`` references
    four writing templates that only repos like this one already ship — in a
    bare adopter repo the bundle then fails to LOAD (the measured
    adoption-simulation blocker). This helper materializes a minimal generic
    file for each referenced (category, stem) under
    ``repo_root/templates/writing/`` — and NEVER overwrites an existing file,
    so a repo's real templates are untouched (K7). Returns the paths actually
    written, sorted.
    """
    written: list[Path] = []
    try:
        for category, stem in WRITING_TEMPLATE_STEMS:
            target = repo_root / "templates" / "writing" / category / f"{stem}.md"
            if target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                _WRITING_TEMPLATE_BODY.format(stem=stem, category=category),
                encoding="utf-8",
            )
            written.append(target)
    except OSError as exc:
        raise ConfigError(
            f"Cannot write writing templates under {repo_root}: {exc}"
        ) from exc
    return tuple(sorted(written))


def scaffold_config_dir(config_dir: Path, *, repo: str, now: str) -> None:
    """Materialize a complete, ``load_bundle``-valid ``config/cdmon/`` (W-02, K7/K8).

    Writes ``index.yaml`` + one example unit (``example.yaml``) + ``ignore.yaml``
    + ``doc-style.yaml`` from the canonical templates, substituting ``repo`` and
    ``now`` — and (AGT-04) ensures the four writing templates the doc-style map
    references exist under the repo's ``templates/writing/``, writing a minimal
    generic file for any that are absent (never overwriting a real one). The
    result passes :func:`custodex.config.load_bundle` in ANY repo — a bare one
    included (the measured ``init --v2`` dead-on-arrival fix). The repo root is
    resolved by the canonical convention (``config_dir/../..``).

    Loud (K8): the directory is created if absent; an OS error wraps into a typed
    :class:`ConfigError`. Caller (``cdx init --v2``) enforces the no-clobber
    policy.
    """
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "index.yaml").write_text(
            _fill(INDEX_TEMPLATE, repo=repo, now=now), encoding="utf-8"
        )
        (config_dir / f"{EXAMPLE_UNIT_STEM}.yaml").write_text(
            _fill(UNIT_TEMPLATE, repo=repo, now=now), encoding="utf-8"
        )
        (config_dir / "ignore.yaml").write_text(
            _fill(IGNORE_TEMPLATE, repo=repo, now=now), encoding="utf-8"
        )
        (config_dir / "doc-style.yaml").write_text(
            _fill(DOC_STYLE_TEMPLATE, repo=repo, now=now), encoding="utf-8"
        )
    except OSError as exc:
        raise ConfigError(
            f"Cannot scaffold config/cdmon directory at {config_dir}: {exc}"
        ) from exc
    ensure_writing_templates((config_dir / ".." / "..").resolve())
