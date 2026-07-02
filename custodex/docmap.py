"""AGT-02 — entity-based doc↔doc edge suggestions + the accept/reject verbs (K11).

Upgrades Pillar B's mapping aid from lexical link-inference to entity-grounded,
provenance-tiered suggestions, and closes the loop with BOTH human verbs:
accept (``cdx link DOWN UP`` → a declared edge, written by comment-preserving
textual splice) and reject (``cdx link --reject`` → a durable verdict in
``.cdmon/edge-rejections.jsonl`` that the suggester excludes forever). Every
output here is advisory until a human applies it — agents suggest; humans
apply (K11).

Two suggestion rules, each with a PRINCIPLED direction (never guessed):

* **RESOLVED_LINK** — doc A's prose contains a markdown link that resolves to
  managed doc B (via the AGT-01 mention layer, so machine regions and code
  fences can no longer mint suggestions — a review-measured fix over the
  legacy ``infer_edges_from_links``, which stays untouched for back-compat).
* **SHARED_SYMBOL** — doc A's prose mentions code symbol S (resolved, AGT-01)
  and EXACTLY ONE doc B documents S through its ``code_refs`` ⇒ A depends on
  B. A symbol covered by ≥2 docs is excluded (ambiguous ownership — precision
  first), as is a doc mentioning a symbol it covers itself.

Exclusions (all review-hardened): declared edges, self-edges, REJECTED pairs,
and any ``index: true`` downstream — the index page's links are MANDATED by
the INDEX_INCOMPLETE lint (measured: 13/13 pure noise on the dogfood corpus).
The same pair found by both rules keeps the STRONGER tier with merged
evidence. Every suggestion whose upstream is code-tracked carries a churn
note (:func:`churn_note`) — the DOCDEPS-01 lesson surfaced to the human
instead of re-learned: a code-tracked upstream reheals on any covered-source
change, and under the default ``docdeps.baseline: body`` each reheal flips
the edge SUSPECT (``baseline: prose`` is the semantic fix).
"""

from __future__ import annotations

import json
import posixpath
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from .config import (
    ConfigBundle,
    DocEdgeType,
    MonitorConfig,
    load_bundle,
)
from .entities import EntityKind, corpus_entities
from .errors import ConfigError, ExtractionError, SchemaError
from .extract import extract_file

__all__ = [
    "SuggestionTier",
    "ScoredEdge",
    "EdgeRejection",
    "REJECTIONS_PATH",
    "suggest_edges",
    "churn_note",
    "render_suggestions_text",
    "declare_edge",
    "reject_edge",
    "read_rejections",
]

# Frozen + extra="forbid": suggestions and verdicts are immutable snapshots (K8/K10).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: The durable repo-side opt-out, beside the review/resolutions logs (.cdmon).
REJECTIONS_PATH = Path(".cdmon") / "edge-rejections.jsonl"


class SuggestionTier(str, Enum):
    """Provenance TIERS, strongest first — never a bare float (review rule)."""

    RESOLVED_LINK = "resolved_link"  # a prose markdown link to the managed upstream
    SHARED_SYMBOL = "shared_symbol"  # downstream mentions a symbol the upstream covers


class ScoredEdge(BaseModel):
    """One suggested ``depends_on`` edge with its provenance trail."""

    model_config = _MODEL_CONFIG

    doc_id: str  # the suggested DOWNSTREAM (the mentioning doc)
    upstream_id: str
    # K6: the legacy `deps --suggest --json` items carried {doc_id, upstream_id,
    # via} — `via` is kept (the link target for RESOLVED_LINK; None for
    # SHARED_SYMBOL) so the new items stay a key-SUPERSET of the old shape.
    via: str | None
    tier: SuggestionTier
    evidence: tuple[str, ...]  # entity ids / link targets justifying the edge
    score: int  # count of independent evidence items (int — K10)


class EdgeRejection(BaseModel):
    """A human's durable 'no' to one suggested edge (a VERDICT, K5-style)."""

    model_config = _MODEL_CONFIG

    doc_id: str
    upstream_id: str
    rejected_at: str  # injected, never read from a clock here (K10)
    rejected_by: str | None = None
    note: str | None = None


def _symbol_owners(config: MonitorConfig, root: Path) -> dict[str, set[str]]:
    """Map a SYMBOL entity id (``symbol <path>#<name>``) → covering doc ids.

    Per-(doc, code_ref) extraction through the audience-agnostic
    :func:`~custodex.extract.extract_file` path; resilient — a missing or
    unparseable ref is skipped, never fatal (an advisory scan must survive
    arbitrary repos).
    """
    owners: dict[str, set[str]] = {}
    for spec in config.documents:
        for ref in spec.code_refs:
            path = posixpath.normpath(ref.path)
            target = root / path
            if not target.is_file():
                continue
            try:
                symbols = extract_file(target)
            except ExtractionError:
                continue
            for sym in symbols:
                if not sym.is_public:
                    continue
                owners.setdefault(f"symbol {path}#{sym.name}", set()).add(spec.id)
    return owners


def suggest_edges(
    config: MonitorConfig,
    root: Path,
    *,
    rejections: tuple[EdgeRejection, ...] | list[EdgeRejection] = (),
) -> tuple[ScoredEdge, ...]:
    """Suggest ``depends_on`` edges from the mention layer (pure, K1/K10/K11).

    See the module docstring for the two rules + the exclusion set. Returns
    suggestions sorted ``(doc_id, upstream_id)``; the same pair found by both
    rules is ONE suggestion at the stronger (RESOLVED_LINK) tier with merged,
    sorted evidence.
    """
    declared = {(d.id, e.doc) for d in config.documents for e in d.depends_on}
    rejected = {(r.doc_id, r.upstream_id) for r in rejections}
    index_docs = {d.id for d in config.documents if d.index}
    doc_id_by_path = {posixpath.normpath(d.path): d.id for d in config.documents}
    owners = _symbol_owners(config, root)

    links: dict[tuple[str, str], list[str]] = {}
    symbols: dict[tuple[str, str], list[str]] = {}
    for result in corpus_entities(config, root):
        if result.doc_id in index_docs:
            continue  # an index doc's links are mandated navigation, not deps
        for mention in result.mentions:
            if not mention.resolved or mention.entity_id is None:
                continue
            if mention.kind is EntityKind.DOC:
                upstream = doc_id_by_path.get(mention.entity_id.split(" ", 1)[1])
                if upstream is None or upstream == result.doc_id:
                    continue
                links.setdefault((result.doc_id, upstream), []).append(mention.text)
            elif mention.kind is EntityKind.SYMBOL:
                covering = owners.get(mention.entity_id, set())
                if len(covering) != 1:
                    continue  # uncovered or ambiguous ownership: never guess
                (upstream,) = covering
                if upstream == result.doc_id:
                    continue  # it documents the symbol itself
                symbols.setdefault((result.doc_id, upstream), []).append(
                    mention.entity_id
                )

    out: list[ScoredEdge] = []
    for pair in sorted(set(links) | set(symbols)):
        if pair in declared or pair in rejected:
            continue
        link_ev = sorted(set(links.get(pair, [])))
        sym_ev = sorted(set(symbols.get(pair, [])))
        evidence = tuple(link_ev + sym_ev)
        tier = SuggestionTier.RESOLVED_LINK if link_ev else SuggestionTier.SHARED_SYMBOL
        out.append(
            ScoredEdge(
                doc_id=pair[0],
                upstream_id=pair[1],
                via=link_ev[0] if link_ev else None,
                tier=tier,
                evidence=evidence,
                score=len(evidence),
            )
        )
    return tuple(out)


def churn_note(config: MonitorConfig, upstream_id: str) -> str:
    """The heal-path coupling warning for one suggested upstream (or ``""``).

    A code-tracked upstream's CDM regions are rewritten by ``cdx monitor
    --apply`` whenever any covered source changes; under the default
    ``docdeps.baseline: body`` every reheal flips dependent edges SUSPECT
    (the recorded DOCDEPS-01 failure). Surfaced with EVERY suggestion and
    echoed by ``cdx link`` so the human decides informed.
    """
    spec = next((d for d in config.documents if d.id == upstream_id), None)
    if spec is None or not spec.code_refs:
        return ""
    n = len(spec.code_refs)
    if config.docdeps.baseline == "prose":
        return (
            f"note: upstream {upstream_id!r} is code-tracked ({n} code ref(s)); "
            "baseline is 'prose', so machine reheals will NOT trip this edge."
        )
    return (
        f"note: upstream {upstream_id!r} is code-tracked ({n} code ref(s)) — it "
        "reheals when any of them change, and each reheal flips this edge "
        "SUSPECT under `docdeps.baseline: body` (set `baseline: prose` to track "
        "human prose only)."
    )


def render_suggestions_text(
    edges: tuple[ScoredEdge, ...] | list[ScoredEdge],
    *,
    notes: dict[str, str] | None = None,
) -> str:
    """Paste-ready ``depends_on`` YAML + tier/evidence/churn lines (K10)."""
    if not edges:
        return "# no new doc↔doc edges suggested"
    notes = notes or {}
    by_doc: dict[str, list[ScoredEdge]] = {}
    for e in edges:
        by_doc.setdefault(e.doc_id, []).append(e)
    lines = [
        f"# {len(edges)} suggested edge(s) — accept with `cdx link DOWN UP`, "
        "silence with `cdx link --reject DOWN UP`:"
    ]
    for doc_id in sorted(by_doc):
        lines.append(f"# document {doc_id!r}:")
        lines.append("    depends_on:")
        for e in sorted(by_doc[doc_id], key=lambda s: s.upstream_id):
            lines.append(f"      - doc: {e.upstream_id}")
            evidence = ", ".join(e.evidence)
            lines.append(f"        # {e.tier.value} (score {e.score}): {evidence}")
            note = notes.get(e.upstream_id, "")
            if note:
                lines.append(f"        # {note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The accept verb — a comment-preserving textual splice (never dump_unit_file)
# ---------------------------------------------------------------------------
def _find_document_block(lines: list[str], doc_id: str) -> tuple[int, int, str] | None:
    """Locate ``- id: doc_id``'s entry block: (start, end_exclusive, indent)."""
    start = None
    indent = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == f"- id: {doc_id}" or stripped.startswith(f"- id: {doc_id} "):
            start = i
            indent = line[: len(line) - len(line.lstrip())]
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            continue
        current = line[: len(line) - len(line.lstrip())]
        if len(current) < len(indent):
            end = j
            break
        if current == indent and line.lstrip().startswith("- "):
            end = j
            break
    return (start, end, indent)


def declare_edge(
    config_dir: Path,
    downstream_id: str,
    upstream_id: str,
    *,
    type: DocEdgeType = DocEdgeType.DEPENDS,
    now: str,
) -> Path:
    """Declare ``downstream depends_on upstream`` in the unit YAML (the accept).

    Validates through the LOADED models (unknown ids, self-edge, duplicate —
    all loud ``ConfigError``, K8) but WRITES via a targeted textual splice of
    the unit file — inserting/extending the ``depends_on:`` block under the
    matching ``- id:`` entry and bumping the frontmatter ``updated:`` line —
    NEVER a model re-serialization: hand-maintained units carry load-bearing
    YAML comments a ``dump_unit_file`` round-trip would destroy (the
    ``regenerate_index`` textual-surgery precedent). Dir-layout configs only.
    """
    bundle: ConfigBundle = load_bundle(config_dir)
    cfg = bundle.config
    ids = {d.id for d in cfg.documents}
    for name in (downstream_id, upstream_id):
        if name not in ids:
            raise ConfigError(f"unknown document id {name!r} — not a managed document")
    if downstream_id == upstream_id:
        raise ConfigError(f"document {downstream_id!r} cannot depend on itself")
    spec = next(d for d in cfg.documents if d.id == downstream_id)
    if any(e.doc == upstream_id for e in spec.depends_on):
        raise ConfigError(
            f"edge {downstream_id!r} → {upstream_id!r} is already declared"
        )
    unit = bundle.unit_for_document(downstream_id)
    if unit is None:  # pragma: no cover - unreachable: id validated above
        raise ConfigError(f"no unit declares document {downstream_id!r}")
    unit_path = config_dir / f"{unit.frontmatter.unit}.yaml"
    text = unit_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    located = _find_document_block(lines, downstream_id)
    if located is None:
        raise ConfigError(
            f"could not locate `- id: {downstream_id}` in {unit_path.name} — "
            "the entry may use an unexpected layout; add the edge by hand"
        )
    start, end, indent = located
    field_indent = indent + "  "
    item_indent = field_indent + "  "
    new_item = [f"{item_indent}- doc: {upstream_id}"]
    if type is not DocEdgeType.DEPENDS:
        new_item.append(f"{item_indent}  type: {type.value}")

    dep_line = None
    for j in range(start + 1, end):
        if lines[j].strip() == "depends_on:":
            dep_line = j
            break
    if dep_line is not None:
        insert_at = dep_line + 1
        for j in range(dep_line + 1, end):
            stripped = lines[j].strip()
            if not stripped:
                break
            current = lines[j][: len(lines[j]) - len(lines[j].lstrip())]
            if len(current) <= len(field_indent):
                break
            insert_at = j + 1
        lines[insert_at:insert_at] = new_item
    else:
        insert_at = end
        while insert_at > start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1  # keep trailing blank lines after the new block
        lines[insert_at:insert_at] = [f"{field_indent}depends_on:", *new_item]

    # Bump the frontmatter `updated:` stamp textually (date part of `now`).
    date = now.split("T", 1)[0]
    for j, line in enumerate(lines):
        if line.startswith("updated:"):
            lines[j] = f'updated: "{date}"'
            break

    unit_path.write_text("\n".join(lines), encoding="utf-8")
    try:
        load_bundle(config_dir)  # self-validate: never leave a broken config (K8)
    except ConfigError as exc:  # pragma: no cover - splice bug guard
        unit_path.write_text(text, encoding="utf-8")
        raise ConfigError(
            f"edge splice produced an invalid config ({exc}); {unit_path.name} "
            "restored — add the edge by hand"
        ) from exc
    return unit_path


# ---------------------------------------------------------------------------
# The reject verb — a durable verdict in .cdmon (the reviewlog precedent)
# ---------------------------------------------------------------------------
def reject_edge(
    cdmon_dir: Path,
    downstream_id: str,
    upstream_id: str,
    *,
    now: str,
    by: str | None = None,
    note: str | None = None,
) -> Path:
    """Append a durable rejection; the suggester excludes the pair forever."""
    path = cdmon_dir / REJECTIONS_PATH.name
    path.parent.mkdir(parents=True, exist_ok=True)
    rejection = EdgeRejection(
        doc_id=downstream_id,
        upstream_id=upstream_id,
        rejected_at=now,
        rejected_by=by,
        note=note,
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rejection.model_dump(mode="json"), sort_keys=True) + "\n")
    return path


def read_rejections(cdmon_dir: Path) -> tuple[EdgeRejection, ...]:
    """Read every recorded rejection (missing file ⇒ none; corrupt line loud, K8)."""
    path = cdmon_dir / REJECTIONS_PATH.name
    if not path.is_file():
        return ()
    out: list[EdgeRejection] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(EdgeRejection(**json.loads(line)))
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise SchemaError(
                f"corrupt edge-rejection line {lineno} in {path}: {exc}"
            ) from exc
    return tuple(out)
