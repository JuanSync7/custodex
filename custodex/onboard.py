"""AGT-04 — the config-authoring onboarding agent (deterministic core — K11).

Kills the #1 measured adoption friction (the 2026-07-02 fresh-eyes simulation:
code↔doc mapping was 100% hand-authored YAML): point ``cdx onboard`` at a repo
and it ANALYZES the tree into a reviewable plan artifact (the Mintlify
plan-before-config pattern), PROPOSES a complete ``config/cdmon/`` bundle built
from real :class:`~custodex.config.UnitFile` models (never string-templated
YAML — these are FRESH files, so the model dump is correct here, unlike
``cdx link``'s comment-preserving splice), and — only on the explicit,
human-invoked ``--apply`` (K11) — writes it, scaffolds the proposed docs, and
SELF-VALIDATES (the Mintlify arrive-green rule: never emit a config the tool
itself rejects, K8).

Heuristics are deliberately conservative and deterministic (no LLM in this
slice — the refinement tier is a documented follow-on behind the Backend
seam): one unit per top-level package (its directory as ``dir-covered``), one
eng-guide document per package covering its ``.py`` files, and the README
(when present) mapped as a user-guide document. Everything else the analysis
sees but does not act on (loose top-level ``.py`` files, extra doc trees,
unparseable sources) becomes a WARNING in the plan — visible, never silent.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import (
    Audience,
    CodeRef,
    DocumentSpec,
    UnitFile,
    UnitFrontmatter,
    dump_unit_file,
    regenerate_index,
    write_index,
)
from .errors import ConfigError, ExtractionError
from .extract import extract_file
from .templates_v2 import IGNORE_TEMPLATE, ensure_writing_templates

__all__ = [
    "DocCandidate",
    "PackageCandidate",
    "RepoMap",
    "OnboardPlan",
    "analyze_repo",
    "propose_config",
    "apply_plan",
    "render_plan_text",
]

# Frozen + extra="forbid": the plan is an immutable, reviewable snapshot (K10).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: Directory names never scanned (VCS/venv/cache — mirrors the entities walk).
_SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".cdmon", ".tox", "dist"}
)

#: Reserved unit stems (config/cdmon file names that are NOT units) — a package
#: with one of these names cannot become a unit file (warned, skipped).
_RESERVED_STEMS = frozenset({"index", "ignore", "doc-style"})

#: Doc-file names whose stem suggests a user-facing narrative (audience guess).
_USER_GUIDE_HINT = re.compile(
    r"readme|tutorial|getting[-_]?started|quickstart|usage|guide|faq", re.IGNORECASE
)

_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

#: Top-level markdown files that are agent/repo SELF-DESCRIPTION, not docs to
#: manage — they surface as signals, never as document candidates.
_SELF_DESCRIPTION = frozenset({"AGENTS.md", "CLAUDE.md"})


class DocCandidate(BaseModel):
    """One markdown file the analysis found, with an audience guess + evidence."""

    model_config = _MODEL_CONFIG

    path: str
    title: str | None
    guessed_audience: Audience
    evidence: str  # WHY this audience was guessed (silent inference is banned)


class PackageCandidate(BaseModel):
    """One top-level package (a directory holding ``.py`` files)."""

    model_config = _MODEL_CONFIG

    name: str
    dir: str
    files: tuple[str, ...]  # repo-relative .py files, sorted
    public_symbols: int  # extracted count (0 when everything was unparseable)


class RepoMap(BaseModel):
    """The PLAN ARTIFACT: what the analysis saw (reviewable, debuggable)."""

    model_config = _MODEL_CONFIG

    root: str
    docs: tuple[DocCandidate, ...]
    packages: tuple[PackageCandidate, ...]
    signals: dict[
        str, str
    ]  # readme / agents_md / claude_md / docs_dir / existing_config
    warnings: tuple[str, ...]


class OnboardPlan(BaseModel):
    """The proposed config bundle, held as REAL models until ``--apply``."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    repo: str
    repo_map: RepoMap
    units: tuple[UnitFile, ...]
    index_text: str
    docs_to_scaffold: tuple[str, ...]  # doc ids whose FILE does not exist yet
    notes: tuple[str, ...]


def analyze_repo(root: Path) -> RepoMap:
    """Scan a repo tree into a :class:`RepoMap` (deterministic, RESILIENT).

    One walk collects: top-level packages (directories transitively holding
    ``.py`` files), doc candidates (``README*`` + ``*.md`` at the top level and
    under ``docs/``), and the self-description signals (README / AGENTS.md /
    CLAUDE.md / docs dir / an existing config). Symbol counting goes file by
    file with a per-file ``try/except`` — an unparseable source becomes a
    warning, NEVER an abort (the design-review resilience rule; the deferred
    ``discover_symbols`` fail-fast is for the coverage GATE, not for advice).
    """
    if not root.is_dir():
        raise ConfigError(f"onboard root does not exist: {root}")
    resolved = root.resolve()

    py_by_top: dict[str, list[str]] = {}
    loose_py: list[str] = []
    doc_paths: list[str] = []
    warnings: list[str] = []

    for dirpath, dirnames, filenames in os.walk(resolved):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        base = Path(dirpath)
        for name in sorted(filenames):
            rel = (base / name).relative_to(resolved).as_posix()
            top = rel.split("/", 1)[0]
            if name.endswith(".py"):
                if "/" in rel:
                    py_by_top.setdefault(top, []).append(rel)
                else:
                    loose_py.append(rel)
            elif (
                name.endswith(".md")
                and ("/" not in rel or rel.startswith("docs/"))
                and rel not in _SELF_DESCRIPTION
            ):
                doc_paths.append(rel)

    packages: list[PackageCandidate] = []
    for top in sorted(py_by_top):
        files = tuple(sorted(py_by_top[top]))
        public = 0
        for rel in files:
            try:
                public += sum(1 for s in extract_file(resolved / rel) if s.is_public)
            except ExtractionError as exc:
                warnings.append(f"{rel}: could not parse — {exc}")
        packages.append(
            PackageCandidate(name=top, dir=top, files=files, public_symbols=public)
        )
    if loose_py:
        warnings.append(
            f"{len(loose_py)} top-level .py file(s) not under a package "
            f"({', '.join(loose_py[:5])}{'…' if len(loose_py) > 5 else ''}) — "
            "add them to a unit by hand after onboarding"
        )

    docs: list[DocCandidate] = []
    for rel in sorted(doc_paths):
        stem = Path(rel).stem
        if _USER_GUIDE_HINT.search(stem):
            audience = Audience.USER_GUIDE
            evidence = f"file name {stem!r} suggests a user-facing narrative"
        else:
            audience = Audience.ENG_GUIDE
            evidence = "no user-facing name hint — defaulting to eng-guide"
        text = ""
        try:
            text = (resolved / rel).read_text(encoding="utf-8")
        except OSError as exc:
            warnings.append(f"{rel}: could not read — {exc}")
        match = _H1.search(text)
        docs.append(
            DocCandidate(
                path=rel,
                title=match.group(1) if match else None,
                guessed_audience=audience,
                evidence=evidence,
            )
        )

    signals: dict[str, str] = {}
    for key, candidate in (
        ("readme", "README.md"),
        ("agents_md", "AGENTS.md"),
        ("claude_md", "CLAUDE.md"),
        ("docs_dir", "docs"),
    ):
        if (resolved / candidate).exists():
            signals[key] = candidate
    if (resolved / "config" / "cdmon").is_dir():
        signals["existing_config"] = "config/cdmon"
    elif (resolved / "cdmon.yaml").is_file():
        signals["existing_config"] = "cdmon.yaml"

    return RepoMap(
        root=resolved.as_posix(),
        docs=tuple(docs),
        packages=tuple(packages),
        signals=signals,
        warnings=tuple(warnings),
    )


_INDEX_BODY = """\
---
cdmon-config-version: "2.0.0"
repo: "{repo}"
generated-by: cdx
updated: "{now}"
---
# Generated by `cdx onboard` — review, then refine (owners, audiences, edges).
root: "../.."
version: "2.0.0"
apply_default: false
backend:
  kind: mock
central:
  sink: none
units:
{units}
ignore: ignore.yaml
doc-style: doc-style.yaml
"""


def propose_config(
    repo_map: RepoMap, *, repo: str, now: str, owner: str | None = None
) -> OnboardPlan:
    """Derive the proposed bundle from the plan artifact (pure, K10/K11).

    One unit per package (``dir-covered`` = its directory, ``.py`` sources),
    one eng-guide document per package covering its files; the README (when
    present) rides the first unit as a user-guide document with no code_refs
    (a narrative doc — the fingerprint stamps at first heal). The REQUIRED
    ``UnitFrontmatter.owner`` uses the precedence the review pinned:
    ``owner`` param → ``"unassigned"`` + a note telling the adopter to set it
    (it feeds the EPIC-OWN accountability chain).
    """
    if not repo_map.packages:
        raise ConfigError(
            "nothing to onboard: no top-level package with .py files was found"
        )
    date = now.split("T", 1)[0]
    unit_owner = owner or "unassigned"
    notes: list[str] = []
    if owner is None:
        notes.append(
            "unit owner set to 'unassigned' — set a real accountable owner "
            "(--owner, or edit the unit frontmatter): it feeds the ownership "
            "and worklist accountability chain"
        )

    units: list[UnitFile] = []
    docs_to_scaffold: list[str] = []
    readme = next(
        (d for d in repo_map.docs if Path(d.path).stem.lower() == "readme"), None
    )
    for i, pkg in enumerate(sorted(repo_map.packages, key=lambda p: p.name)):
        if pkg.name in _RESERVED_STEMS:
            notes.append(
                f"package {pkg.name!r} collides with a reserved config stem — "
                "skipped; add it to a differently-named unit by hand"
            )
            continue
        doc_id = f"{pkg.name}-api"
        documents: list[DocumentSpec] = [
            DocumentSpec(
                id=doc_id,
                path=f"docs/{doc_id}.md",
                audience=Audience.ENG_GUIDE,
                region_keys=("symbols",),
                code_refs=tuple(CodeRef(path=f) for f in pkg.files),
            )
        ]
        docs_to_scaffold.append(doc_id)
        if i == 0 and readme is not None:
            documents.append(
                DocumentSpec(
                    id="readme",
                    path=readme.path,
                    audience=Audience.USER_GUIDE,
                )
            )
            notes.append(
                f"README mapped as a user-guide document ({readme.evidence}); "
                "its fingerprint stamps on the first `cdx monitor --apply`"
            )
        units.append(
            UnitFile(
                frontmatter=UnitFrontmatter(
                    **{
                        "cdmon-config-version": "2.0.0",
                        "unit": pkg.name,
                        "title": f"{pkg.name} package",
                        "owner": unit_owner,
                        "created": date,
                        "updated": date,
                    }
                ),
                **{
                    "dir-covered": (pkg.dir,),
                    "source-files-format": (".py",),
                },
                documents=tuple(documents),
            )
        )
    if not units:
        raise ConfigError(
            "nothing to onboard: every package collided with a reserved stem"
        )

    unit_lines = "\n".join(f"  - file: {u.frontmatter.unit}.yaml" for u in units)
    index_text = _INDEX_BODY.format(repo=repo, now=now, units=unit_lines)
    return OnboardPlan(
        repo=repo,
        repo_map=repo_map,
        units=tuple(units),
        index_text=index_text,
        docs_to_scaffold=tuple(docs_to_scaffold),
        notes=tuple(notes),
    )


def apply_plan(plan: OnboardPlan, config_dir: Path, *, now: str) -> tuple[Path, ...]:
    """Write the proposed bundle to disk (the human-invoked apply — K11).

    Writes ``index.yaml`` + one unit file per package (``dump_unit_file`` —
    fresh files, no comments to destroy) + ``ignore.yaml`` + ``doc-style.yaml``
    (with :func:`ensure_writing_templates` so the bundle LOADS in a bare repo —
    the init --v2 DOA fix), then normalizes the index through
    ``regenerate_index`` (the one sanctioned index writer). Doc scaffolding and
    healing are the CLI's job (they need the loaded bundle + a Monitor).
    Refuses to clobber an existing config dir (K8 — the caller offers --force
    by deleting first).
    """
    if config_dir.exists() and any(config_dir.iterdir()):
        raise ConfigError(
            f"config directory {config_dir} already exists and is not empty — "
            "refusing to overwrite (re-run with --force to replace it)"
        )
    from .templates_v2 import DOC_STYLE_TEMPLATE, _fill  # the canonical texts

    config_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index_path = config_dir / "index.yaml"
    index_path.write_text(plan.index_text, encoding="utf-8")
    written.append(index_path)
    for unit in plan.units:
        unit_path = config_dir / f"{unit.frontmatter.unit}.yaml"
        unit_path.write_text(dump_unit_file(unit, now=now), encoding="utf-8")
        written.append(unit_path)
    (config_dir / "ignore.yaml").write_text(
        _fill(IGNORE_TEMPLATE, repo=plan.repo, now=now), encoding="utf-8"
    )
    written.append(config_dir / "ignore.yaml")
    (config_dir / "doc-style.yaml").write_text(
        _fill(DOC_STYLE_TEMPLATE, repo=plan.repo, now=now), encoding="utf-8"
    )
    written.append(config_dir / "doc-style.yaml")
    repo_root = (config_dir / ".." / "..").resolve()
    written.extend(ensure_writing_templates(repo_root))
    write_index(config_dir, regenerate_index(config_dir))
    return tuple(written)


def render_plan_text(plan: OnboardPlan) -> str:
    """The Renovate onboarding-PR body: surfaces / mapping / what to expect."""
    m = plan.repo_map
    lines = [f"# Onboarding plan for {plan.repo!r} ({m.root})", ""]
    lines.append("## Detected surfaces")
    for pkg in m.packages:
        lines.append(
            f"  - package {pkg.name}/ — {len(pkg.files)} .py file(s), "
            f"{pkg.public_symbols} public symbol(s)"
        )
    for doc in m.docs:
        title = f" ({doc.title!r})" if doc.title else ""
        lines.append(
            f"  - doc {doc.path}{title} → {doc.guessed_audience.value} [{doc.evidence}]"
        )
    if m.signals:
        lines.append(
            "  - signals: "
            + ", ".join(f"{k}={v}" for k, v in sorted(m.signals.items()))
        )
    lines.append("")
    lines.append("## Proposed mapping (config/cdmon/)")
    for unit in plan.units:
        lines.append(f"  - unit {unit.frontmatter.unit}.yaml:")
        for spec in unit.documents:
            refs = (
                f"{len(spec.code_refs)} code ref(s)" if spec.code_refs else "narrative"
            )
            lines.append(
                f"      {spec.id} ({spec.audience.value}, {refs}) → {spec.path}"
            )
    lines.append("")
    lines.append("## What to expect on --apply")
    lines.append(
        f"  - {len(plan.docs_to_scaffold)} doc(s) scaffolded in-sync; the bundle "
        "self-validates (load → doctor → check) and arrives GREEN"
    )
    for note in plan.notes:
        lines.append(f"  - note: {note}")
    for warning in m.warnings:
        lines.append(f"  - warning: {warning}")
    return "\n".join(lines)
