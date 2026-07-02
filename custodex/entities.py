"""AGT-01 — deterministic entity extraction + mention linking (pure — K0/K1/K10).

The mention layer of EPIC AGT. Each managed document's PROSE is parsed
deterministically and every candidate mention is LINKED against a closed
registry built from the code surface, the managed-doc set, and the full repo
file tree — entity *linking* against known referents, never open-set NER (the
LazyGraphRAG split: the index is built with zero LLM involvement; an LLM only
ever *consumes* it, K4/K11). Unresolved mentions are first-class data (the
Obsidian rule) — they are the graph-rot signal — but ONLY where the rules
below allow a span to be unresolved: **precision beats recall; an ambiguous
mention is unresolved-or-ignored, never guessed** (the 2026-07-02
design-review rules, ARCHITECTURE.md `EPIC AGT` ⟨R⟩ markers).

Mention sources, in order (fenced code blocks and ``CDM:BEGIN/END`` machine
regions are stripped first — machine-generated text must not mint mentions;
blank lines keep ``Mention.line`` file-accurate, front-matter height included):

* **headings** — the doc's own SECTION entities (GitHub-style slugs, repeated
  slugs deduplicated ``-2``/``-3``);
* **inline markdown links** (images and ``mailto:`` skipped) — absolute ⇒ URL;
  relative ⇒ DOC when it resolves to a managed doc, else PATH against the full
  repo tree (files and directories), unresolved when nothing matches;
* **inline backtick spans** — classified by the pinned rules: spans with
  whitespace/braces/glob metachars mint nothing; path-shaped spans resolve
  against the full tree; SCREAMING_SNAKE spans resolve registry-first, then
  the configured ``entities.env_prefixes`` gate (else ignored); identifier
  spans resolve by exact registry match, where only *dotted*, *snake_case*,
  or *multi-hump CamelCase* spans may mint an UNRESOLVED mention — a plain
  word resolves or is ignored, never unresolved.

Symbol resolution is exact-match only: qualified ``Class.method``,
module-qualified ``stem.name`` (registered only while the stem is unique),
and full-dotted ``pkg.mod.name`` forms; a bare name needs GLOBAL uniqueness
*and* no module-stem collision (a bare name that is also a file stem — the
measured ``app``/``coverage``/``index`` cli.py trap — is ambiguous ⇒
unresolved). The registry is RESILIENT: an unparseable or unextractable
source file becomes a ``warnings`` entry and contributes no symbols — a
read-only advisory scan never aborts on one bad file (K8 stays for *config*
errors; a target repo's broken file is data, not a crash).
"""

from __future__ import annotations

import posixpath
import re
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import EntitiesConfig, MonitorConfig
from .errors import DriftError, ExtractionError
from .extract import _SYMBOL_LANG_BY_SUFFIX, get_extractor
from .inventory import discover_files
from .manifest import parse_text

__all__ = [
    "EntityKind",
    "Entity",
    "Mention",
    "DocEntities",
    "EntityRegistry",
    "build_registry",
    "extract_doc_entities",
    "corpus_entities",
    "render_entities_text",
]

# Frozen + extra="forbid": mentions are immutable, normalized snapshots (K10).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: Directory names never walked for the PATH universe (VCS/venv/cache trees).
_SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".cdmon"})

#: Suffixes that mark a backtick span as path-shaped even without a slash.
_KNOWN_SUFFIXES = frozenset(
    {
        ".py",
        ".md",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".sh",
        ".bash",
        ".tcl",
        ".txt",
        ".cfg",
        ".ini",
        ".rst",
        ".js",
        ".ts",
        ".tsx",
        ".css",
        ".html",
    }
)

# An inline markdown link that is NOT an image: [text](target) with an
# optional "title". The lookbehind rejects ![alt](...) embeds.
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# An inline single-backtick code span (double-backtick spans are a documented
# limitation — rare in this corpus).
_BACKTICK = re.compile(r"`([^`\n]+)`")

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CDM_BEGIN = re.compile(r"^<!-- CDM:BEGIN \S+ -->\s*$")
_CDM_END = re.compile(r"^<!-- CDM:END \S+ -->\s*$")

_SCREAMING = re.compile(r"\A[A-Z][A-Z0-9_]{2,}\Z")
_IDENT_CHARS = re.compile(r"\A[A-Za-z_][A-Za-z0-9_.]*\Z")
_GLOB_CHARS = ("*", "?", "[")


class EntityKind(str, Enum):
    """The CLOSED entity taxonomy (Backstage discipline — extend deliberately)."""

    DOC = "doc"
    SECTION = "section"
    SYMBOL = "symbol"
    PATH = "path"
    ENV_VAR = "env_var"
    URL = "url"


class Entity(BaseModel):
    """One known referent, with a SCIP-style deterministic string id (K10)."""

    model_config = _MODEL_CONFIG

    id: str  # e.g. "symbol custodex/drift.py#detect_drift" / "doc docs/api/x.md"
    kind: EntityKind
    name: str  # display name; a SECTION's name is its SLUG (K2-safe for the hub)


class Mention(BaseModel):
    """One prose mention of an entity — resolved or first-class unresolved."""

    model_config = _MODEL_CONFIG

    doc_id: str
    entity_id: str | None  # None ⇔ unresolved
    kind: EntityKind
    text: str  # the raw mention as written
    line: int  # 1-based line in the FILE (front-matter height included)
    resolved: bool


class DocEntities(BaseModel):
    """One managed doc's extracted mentions + its own section entities."""

    model_config = _MODEL_CONFIG

    doc_id: str
    doc_path: str
    mentions: tuple[Mention, ...]  # sorted (line, text) — K10
    sections: tuple[Entity, ...]  # heading entities, in document order


class EntityRegistry(BaseModel):
    """The closed resolution universe one repo scan yields (pure data)."""

    model_config = _MODEL_CONFIG

    doc_by_path: dict[str, str]  # normalized managed-doc path -> doc id
    symbol_keys: dict[str, tuple[str, ...]]  # resolution key -> entity ids
    file_set: frozenset[str]  # FULL repo tree files (repo-relative posix)
    dir_set: frozenset[str]  # FULL repo tree directories
    basenames: dict[str, tuple[str, ...]]  # basename -> files bearing it
    stems: dict[str, tuple[str, ...]]  # source-file stem -> files bearing it
    warnings: tuple[str, ...]  # unparseable/unextractable source files

    def resolve_symbol(self, span: str) -> str | None:
        """Resolve a symbol span per the pinned rules, or ``None``.

        Exact-match only. A dotted span resolves when its key maps to exactly
        one entity. A bare span additionally requires NO module-stem collision
        (the measured cli.py-command trap: ``app``/``coverage``/``index``).
        """
        ids = self.symbol_keys.get(span)
        if ids is None or len(ids) != 1:
            return None
        if "." not in span and span in self.stems:
            return None  # bare name shadowed by a module stem — never guess
        return ids[0]


def _walk_tree(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """The full repo file+dir universe for PATH resolution (deterministic).

    Uses :func:`Path.rglob` breadth via ``os.walk`` semantics with the
    standard skip set (VCS/venv/cache). Independent of the coverage inventory
    — prose mentions non-code files and directories, and the design review
    measured a .py-only universe drowning the rot signal in false positives.
    """
    import os

    files: set[str] = set()
    dirs: set[str] = set()
    resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(resolved):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        base = Path(dirpath)
        rel_dir = base.relative_to(resolved).as_posix()
        if rel_dir != ".":
            dirs.add(rel_dir)
        for name in filenames:
            files.add((base / name).relative_to(resolved).as_posix())
    return frozenset(files), frozenset(dirs)


def build_registry(config: MonitorConfig, root: Path) -> EntityRegistry:
    """Build the resolution universe: docs + symbols + the full file tree.

    Symbols come from the coverage inventory (``config.coverage`` include/
    exclude) via the LANGUAGE-GUARDED extractor registry — a file's suffix
    picks its extractor; an unregistered suffix or an unparseable file adds a
    ``warnings`` entry and no symbols (resilient by design: a background tick
    or read-only scan over an arbitrary adopter repo must never abort on one
    bad file). Every qualified form is registered: the bare/``Class.method``
    name, the stem-qualified ``stem.name`` (only while the stem is unique),
    and the full-dotted ``pkg.mod.name``.
    """
    doc_by_path = {posixpath.normpath(doc.path): doc.id for doc in config.documents}
    file_set, dir_set = _walk_tree(root)

    inventory = discover_files(
        root, include=config.coverage.include, exclude=config.coverage.exclude
    )
    warnings: list[str] = []
    keys: dict[str, set[str]] = {}
    stems: dict[str, set[str]] = {}
    for code_file in inventory.files:
        stems.setdefault(Path(code_file.path).stem, set()).add(code_file.path)

    for code_file in inventory.files:
        suffix = Path(code_file.path).suffix
        language = _SYMBOL_LANG_BY_SUFFIX.get(suffix)
        if language is None:
            warnings.append(
                f"{code_file.path}: no symbol extractor registered for "
                f"{suffix!r} — contributes no symbols"
            )
            continue
        try:
            symbols = get_extractor(language).extract(root / code_file.path)
        except ExtractionError as exc:
            warnings.append(f"{code_file.path}: could not parse — {exc}")
            continue
        stem = Path(code_file.path).stem
        dotted = code_file.path.rsplit(".", 1)[0].replace("/", ".")
        for sym in symbols:
            if not sym.is_public:
                continue
            entity_id = f"symbol {code_file.path}#{sym.name}"
            keys.setdefault(sym.name, set()).add(entity_id)
            if len(stems[stem]) == 1:
                keys.setdefault(f"{stem}.{sym.name}", set()).add(entity_id)
            if dotted != stem:
                keys.setdefault(f"{dotted}.{sym.name}", set()).add(entity_id)

    basenames: dict[str, set[str]] = {}
    for path in file_set:
        basenames.setdefault(posixpath.basename(path), set()).add(path)

    return EntityRegistry(
        doc_by_path=doc_by_path,
        symbol_keys={k: tuple(sorted(v)) for k, v in sorted(keys.items())},
        file_set=file_set,
        dir_set=dir_set,
        basenames={k: tuple(sorted(v)) for k, v in sorted(basenames.items())},
        stems={k: tuple(sorted(v)) for k, v in sorted(stems.items())},
        warnings=tuple(warnings),
    )


def _strip_machine_text(body: str) -> list[str]:
    """Blank out fenced code + CDM regions, preserving the line count (K10)."""
    out: list[str] = []
    in_fence: str | None = None
    in_region = False
    for line in body.split("\n"):
        fence = _FENCE.match(line)
        if in_fence is not None:
            out.append("")
            if fence is not None and fence.group(1) == in_fence:
                in_fence = None
            continue
        if fence is not None:
            in_fence = fence.group(1)
            out.append("")
            continue
        if in_region:
            out.append("")
            if _CDM_END.match(line):
                in_region = False
            continue
        if _CDM_BEGIN.match(line):
            in_region = True
            out.append("")
            continue
        out.append(line)
    return out


def _slugify(text: str) -> str:
    """GitHub-style heading slug: lowercase, non-alnum runs collapse to ``-``."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def _is_path_shaped(span: str) -> bool:
    return "/" in span or Path(span).suffix in _KNOWN_SUFFIXES


def _resolve_path(
    span: str, registry: EntityRegistry
) -> tuple[EntityKind, str | None] | None:
    """Resolve a path-shaped span against the full tree.

    Exact repo-relative path first (files, then directories with the trailing
    slash normalized), then a UNIQUE-basename match. An AMBIGUOUS basename
    (≥2 files bear it) mints NOTHING — the referent exists, we just cannot
    pick one, and existing-but-ambiguous is not rot (precision rule). Only a
    span matching ZERO tree entries is an unresolved PATH mention. A
    site-absolute (`/x`) or degenerate (`/`, `.`) span mints nothing.
    """
    if span.startswith("/"):
        return None  # site-absolute route, not a repo path
    norm = posixpath.normpath(span.rstrip("/"))
    if norm in ("", ".", "..") or norm.startswith(".."):
        return None
    if norm in registry.file_set or norm in registry.dir_set:
        return (EntityKind.PATH, f"path {norm}")
    candidates = registry.basenames.get(norm)
    if candidates is not None:
        if len(candidates) == 1:
            return (EntityKind.PATH, f"path {candidates[0]}")
        return None  # ambiguous basename: exists, never guess, never rot
    return (EntityKind.PATH, None)


def _is_multi_hump(span: str) -> bool:
    """Two or more uppercase humps and not ALL-CAPS: ``ReviewRecord`` yes."""
    return len(re.findall(r"[A-Z]", span)) >= 2 and not span.isupper()


def _classify_backtick(
    span: str,
    registry: EntityRegistry,
    entities_cfg: EntitiesConfig,
) -> tuple[EntityKind, str | None] | None:
    """Apply the pinned span rules; ``None`` means the span mints nothing."""
    if span in entities_cfg.ignore:
        return None
    if any(ch.isspace() for ch in span) or "{" in span or "}" in span:
        return None  # commands / HTTP routes / prose fragments
    if any(ch in span for ch in _GLOB_CHARS) or ":" in span:
        return None  # glob spans and colon-bearing routes/markers: never noise

    if _is_path_shaped(span):
        return _resolve_path(span, registry)

    if _SCREAMING.fullmatch(span) and "_" in span:
        resolved = registry.resolve_symbol(span)
        if resolved is not None:
            return (EntityKind.SYMBOL, resolved)
        if any(span.startswith(p) for p in entities_cfg.env_prefixes):
            return (EntityKind.ENV_VAR, f"env {span}")
        return None  # enum-name-like span: ignored, never unresolved

    if not _IDENT_CHARS.fullmatch(span):
        return None
    if "." in span:
        parts = span.split(".")
        if not all(p.isidentifier() for p in parts):
            return None  # version strings and other dotted non-identifiers
        resolved = registry.resolve_symbol(span)
        if resolved is not None:
            return (EntityKind.SYMBOL, resolved)
        # A dotted PACKAGE/MODULE mention (`custodex.server`) resolves as a
        # PATH when the dots-to-slashes form names a real directory or module.
        as_path = span.replace(".", "/")
        if as_path in registry.dir_set:
            return (EntityKind.PATH, f"path {as_path}")
        if f"{as_path}.py" in registry.file_set:
            return (EntityKind.PATH, f"path {as_path}.py")
        return (EntityKind.SYMBOL, None)
    if not span.isidentifier():
        return None

    resolved = registry.resolve_symbol(span)
    if resolved is not None:
        return (EntityKind.SYMBOL, resolved)
    # A bare name matching ONLY a unique module stem is a PATH mention.
    stem_files = registry.stems.get(span)
    if span not in registry.symbol_keys and stem_files is not None:
        if len(stem_files) == 1:
            return (EntityKind.PATH, f"path {stem_files[0]}")
        return (EntityKind.SYMBOL, None)  # colliding stems: unresolved
    # Only dotted/snake/multi-hump spans may be UNRESOLVED; a plain word
    # (single lowercase/Capitalized/ALL-CAPS token) is ignored when unknown.
    if "_" in span or _is_multi_hump(span):
        return (EntityKind.SYMBOL, None)
    return None


def _link_mention(
    target: str,
    doc_dir: str,
    registry: EntityRegistry,
) -> tuple[EntityKind, str | None] | None:
    """Classify one markdown link target, or ``None`` to skip it."""
    link = target.split("#", 1)[0].strip()
    if target.startswith("mailto:"):
        return None
    if "://" in target:
        return (EntityKind.URL, f"url {link}") if link else None
    if not link:
        return None  # pure in-page anchor
    resolved = posixpath.normpath(posixpath.join(doc_dir, link))
    doc_id = registry.doc_by_path.get(resolved)
    if doc_id is not None:
        return (EntityKind.DOC, f"doc {resolved}")
    norm = resolved.rstrip("/")
    if norm in registry.file_set or norm in registry.dir_set:
        return (EntityKind.PATH, f"path {norm}")
    return (EntityKind.PATH, None)


def extract_doc_entities(
    doc_id: str,
    doc_path: str,
    raw: str,
    registry: EntityRegistry,
    *,
    entities_cfg: EntitiesConfig,
) -> DocEntities:
    """Extract one doc's mentions + section entities from its RAW text (PURE).

    Takes the raw file text (not just the body) so ``Mention.line`` is
    file-accurate: the front-matter height is added to every body line — a
    human can jump straight to the mention. No I/O, no clock (K1/K10).
    """
    doc = parse_text(raw, Path(doc_path))
    fm_height = raw[: len(raw) - len(doc.body)].count("\n")
    lines = _strip_machine_text(doc.body)
    doc_dir = posixpath.dirname(doc_path)

    sections: list[Entity] = []
    slug_counts: dict[str, int] = {}
    mentions: list[Mention] = []

    for idx, line in enumerate(lines):
        file_line = idx + 1 + fm_height

        heading = _HEADING.match(line)
        if heading is not None:
            slug = _slugify(heading.group(2))
            n = slug_counts.get(slug, 0) + 1
            slug_counts[slug] = n
            final = slug if n == 1 else f"{slug}-{n}"
            sections.append(
                Entity(
                    id=f"section {doc_path}#{final}",
                    kind=EntityKind.SECTION,
                    name=final,
                )
            )
            continue

        for match in _LINK.finditer(line):
            verdict = _link_mention(match.group(1), doc_dir, registry)
            if verdict is None:
                continue
            kind, entity_id = verdict
            mentions.append(
                Mention(
                    doc_id=doc_id,
                    entity_id=entity_id,
                    kind=kind,
                    text=match.group(1),
                    line=file_line,
                    resolved=entity_id is not None,
                )
            )

        for match in _BACKTICK.finditer(line):
            span = match.group(1)
            verdict = _classify_backtick(span, registry, entities_cfg)
            if verdict is None:
                continue
            kind, entity_id = verdict
            mentions.append(
                Mention(
                    doc_id=doc_id,
                    entity_id=entity_id,
                    kind=kind,
                    text=span,
                    line=file_line,
                    resolved=entity_id is not None,
                )
            )

    mentions.sort(key=lambda m: (m.line, m.text))
    return DocEntities(
        doc_id=doc_id,
        doc_path=doc_path,
        mentions=tuple(mentions),
        sections=tuple(sections),
    )


def corpus_entities(
    config: MonitorConfig, root: Path, *, doc_id: str | None = None
) -> tuple[DocEntities, ...]:
    """Extract mentions for every managed doc (or one), sorted by doc id.

    Builds the registry once. A managed doc whose FILE is missing is skipped
    (its ``MISSING_DOC`` drift covers it — the docdeps precedent). An unknown
    ``doc_id`` raises :class:`DriftError` (K8).
    """
    if doc_id is not None and all(d.id != doc_id for d in config.documents):
        raise DriftError(f"unknown document id {doc_id!r} — not a managed document")
    registry = build_registry(config, root)
    out: list[DocEntities] = []
    for spec in sorted(config.documents, key=lambda d: d.id):
        if doc_id is not None and spec.id != doc_id:
            continue
        path = root / spec.path
        if not path.is_file():
            continue
        out.append(
            extract_doc_entities(
                spec.id,
                spec.path,
                path.read_text(encoding="utf-8"),
                registry,
                entities_cfg=config.entities,
            )
        )
    return tuple(out)


def render_entities_text(
    results: tuple[DocEntities, ...] | list[DocEntities],
    *,
    unresolved_only: bool = False,
) -> str:
    """A deterministic plain-text mention report (K10) — the ``cdx entities`` view."""
    total = sum(len(r.mentions) for r in results)
    unresolved = sum(1 for r in results for m in r.mentions if not m.resolved)
    lines = [
        f"# Entities — {len(results)} document(s), {total} mention(s), "
        f"{unresolved} unresolved",
    ]
    for result in results:
        shown = [m for m in result.mentions if not (unresolved_only and m.resolved)]
        if not shown:
            continue
        lines.append("")
        lines.append(f"  {result.doc_id}:")
        for m in shown:
            target = m.entity_id if m.resolved else "UNRESOLVED"
            lines.append(f"    L{m.line} `{m.text}` [{m.kind.value}] → {target}")
    return "\n".join(lines)
