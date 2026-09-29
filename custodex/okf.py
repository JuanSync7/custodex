"""The OKF v0.2 bundle projection (EPIC OKF, OKF-01 — K0/K1/K2/K5/K6/K7/K8/K10).

Projects the managed doc set into a Google Open Knowledge Format v0.2 bundle
(``knowledge-catalog/okf/SPEC.md``): a directory of markdown files with YAML
front matter that any OKF-aware consumer can read. A PROJECTION of existing
truths — config + doc bytes + the review and resolutions logs + the pure
drift report — never a storage format: deleting the bundle changes nothing,
and regenerating it is byte-idempotent because the bundle is deliberately
CLOCK-FREE. OKF v0.2 makes ``generated.at`` optional, so we emit
``generated: {by}`` with no timestamp (K10) and the per-file writer is a
plain compare-skip (K7).

Per managed doc the front matter carries: ``type`` (the one REQUIRED field —
doc-style document-type mapped to a display name, audience fallback),
``title`` (first H1 else the doc id), ``description`` (the first
purpose-blockquote line, omitted when absent), ``resource`` (the
repo-relative doc path), ``tags`` (``[audience]``), ``generated: {by}``,
``verified`` (see below), ``sources`` (one ``{resource}`` per code ref) —
plus a ``custodex:`` extension block
(``doc_id``, ``audience``, ``fingerprint``) for round-trip traceability,
legal per the v0.2 extensions clause ("Producers MAY include any additional
keys"). The body is the doc body with the ``cdm:`` front matter stripped and
every other byte verbatim — the bundle mirrors ``spec.path`` so relative
doc↔doc links survive. The bundle-root ``index.md`` carries
``okf_version: "0.2"`` and nothing else in its front matter (the one
exception the spec allows an index file), and no concept is ever written to
a reserved filename: a managed doc NAMED ``index.md`` (a landing page —
custodex's own ``api-index`` doc, found by dogfooding within the hour) is
emitted body-verbatim as the per-directory INDEX FILE the spec reserves
that name for, and a doc named ``log.md`` is a loud :class:`ConfigError`
(K8). So are two doc ids on ONE bundle path: the bundle has one file per
path, so the later concept would silently replace the earlier one and its
verdict.

``verified`` is a HUMAN attestation (the ``human:`` prefix is a spec MUST),
so it needs positive evidence, and a doc has ONE verdict.

A doc's CURRENT REVIEWS are the last-write resolutions
(:func:`reviewlog.resolved_index` — a later APPENDED line is a correction,
whatever its stamp) of its review records that

- were graded against the doc's CURRENT stored fingerprint (a record of an
  older surface reviewed a doc that no longer exists), and
- were recorded at or after the doc's NEWEST review record (instants
  compared as parsed datetimes, never as strings). A review recorded before
  a newer record of ANY drift kind or verdict — the record of a machine heal
  it never saw, of a dry-run preview, of a code move and its revert, of an
  upstream edit's escalation — is superseded until a record bound to the
  current surface is (re)resolved at or after the newest one; a newer record
  graded against a surface that no longer exists can never lift that.
  Supersession is per doc: another doc's records never touch it. Only a
  RECORD supersedes: a write that leaves none is not seen (see "Code
  surface, not content" below).

The doc carries ``verified`` only when BOTH hold:

1. the caller's drift report shows NO outstanding drift on it (no report →
   nothing verifies). A REGION or SUSPECT_LINK record is graded against the
   current surface BEFORE its fix lands, so the surface alone would vouch
   for content ``cdx check`` still rejects;
2. no current review DISPUTES it: an outcome in
   :data:`DISPUTING_RESOLUTIONS` (REJECTED, named or not), or an OVERRIDDEN
   one whose ``resolved_text`` (surrounding whitespace stripped) is not in
   the doc body byte-for-byte as ONE contiguous block — the change it
   requests has not landed (custodex never writes that text, and a match
   only after case-folding or collapsing whitespace is not the human's
   words). When a run writes a doc's HASH and REGION records under DISTINCT
   ids, as ``cdx monitor`` does, bob's REJECT of one withholds alice's
   ACCEPT of the other, in either order; a run that gives them ONE id is one
   review (see "Record grain" below).

It then carries one ``{by: "human:<id>", at: <resolved_at>}`` event per
current review that ATTESTS it — ACCEPTED, or OVERRIDDEN with its text in
the body — and names a resolver (``resolved_by``, whitespace collapsed; none
→ no event, never an invented ``human:unrecorded``). INVALIDATED ("a
non-event") judges the drift, not the content: it neither attests nor
disputes. Identical events collapse; the order is by parsed instant, then
resolver, then the verbatim stamp (K10). :func:`pending_verifications` asks
the same question minus the drift gate, so a caller runs the drift check
only when a verification is at stake.

Scope, stated honestly:

- **Presumption.** A record carries no run id and no applied flag, so the
  engine cannot tell WHICH same-surface record a human looked at: a review
  recorded at or after the doc's newest record is presumed to be of the doc
  as it stands. Accepting an OLD dry-run proposal after the machine heal
  therefore verifies the heal's write — byte-identical with a deterministic
  backend, not necessarily with an LLM. Closing it needs a run id and an
  applied marker on the record (additive, K6 — follow-up OKF-02); a doc
  digest captured at resolve time alone would not, since it proves the doc
  is unchanged since the resolve, not which write the human reviewed.
- **Code surface, not content.** The fingerprint is a CODE-surface hash
  (K2) and only a review record supersedes, so ANY content change that
  moves no code surface and writes no :class:`ReviewRecord` keeps the
  claim — a human prose edit, and equally a record-less MACHINE rewrite:
  custodex's own ``cdx new-doc --force`` (the whole reviewed body replaced
  by a TODO scaffold at the same surface, ``cdx check`` still clean) and
  the server editor's :func:`custodex.generate.apply_record_fix` and
  :func:`custodex.generate.apply_edits_to_disk`. Binding to the content
  needs a doc digest captured at resolve time (additive, K6 — follow-up
  OKF-03).
- **Recorded instants, not wall time.** Supersession compares the instants
  the writers stamped. ``cdx monitor`` stamps each record just BEFORE it
  applies that record's fix; MCP ``remediate_drift`` and ``sync_docs`` stamp
  EVERY record with the call-start instant. A resolution recorded while a
  run is in flight — for MCP, at any point of a possibly minutes-long
  LLM-backed call, even one of that call's OWN record — still predates the
  writes it then vouches for. A run id alone does not close this; OKF-02's
  applied receipt or OKF-03's resolve-time digest does.
- **Record grain.** A resolution names a record id, and the id hashes the
  doc, its surface and the record's stamp. ``cdx monitor`` stamps each
  record, so a run's HASH and REGION records on a doc are two reviews. MCP
  ``remediate_drift`` and ``sync_docs`` stamp every record with the
  call-start instant, so a doc's simultaneous drifts share ONE id — the
  grain MCP documents ("resolving it covers all of that doc's simultaneous
  drifts") — and are ONE review under last-write-wins: bob's REJECT of the
  REGION facet followed by alice's ACCEPT of the HASH facet is a correction
  and verifies, while the reverse order does not. This is a STANDING limit:
  MCP keeps its documented doc grain (the known limitation in
  ``.project/problems/MCP-02-record-id-grain.md``), and a ResolutionRecord
  names no facet, so okf cannot split one id's facets on its own.
- **Containment, not replacement.** An override's text must be in the
  body; the machine text may still sit beside it.
- **Writer channel.** Who wrote a resolution (a person at ``cdx resolve``,
  or an MCP agent passing ``resolved_by`` to ``resolve_drift``) is not
  recorded, so a ``resolved_by`` supplied by a non-human writer still reads
  as ``human:`` (follow-up OKF-CHANNEL: a ``channel`` on the resolution).
- **Local logs only.** The join reads the review and resolutions logs it is
  given — for ``cdx okf``, the local ``.cdmon/review-log.jsonl`` and
  ``.cdmon/resolutions.jsonl``. A resolution recorded through the central
  hub (the console's ``POST /repos/{id}/resolutions``, or ``POST
  /repos/{id}/records/{record_id}/apply-fix``) lives only in the server's
  store and never reaches the local log, so it neither attests nor vetoes:
  a REJECT made in the console does not withhold a CLI accept.
- **K8 scope.** The review log's instants are read only when a resolution
  joins one of its records; then every record's stamp is parsed (any may
  supersede) and a corrupt one is a loud :class:`SchemaError`. With
  ``drift_report=None``, or no joining resolution, none is read.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import yaml
from pydantic import BaseModel, ConfigDict

from .codeindex import GENERATED_BY
from .config import Audience, DocumentSpec, MonitorConfig
from .docstyle import DocStyleMap
from .drift import DriftReport
from .errors import ConfigError, SchemaError
from .manifest import parse_doc, stored_fingerprint
from .reviewlog import resolved_index
from .schema import Resolution, ResolutionRecord, ReviewRecord

__all__ = [
    "DISPUTING_RESOLUTIONS",
    "OKF_DIR",
    "OKF_VERSION",
    "VERIFYING_RESOLUTIONS",
    "OkfExportResult",
    "check_okf",
    "export_okf",
    "okf_type_for",
    "pending_verifications",
    "render_bundle",
]

# Frozen + extra="forbid": the export result is an immutable summary (K10).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: The default bundle directory (config_dir-anchored, beside the artifacts).
OKF_DIR = Path(".cdmon") / "okf"

#: The OKF version this module emits (declared in the bundle-root index.md).
OKF_VERSION = "0.2"

#: Reserved OKF filenames — never legal as concept documents.
_RESERVED = frozenset({"index.md", "log.md"})

#: The resolution outcomes that CAN attest content (the SEMANTICS of OKF
#: ``verified`` against :class:`~custodex.schema.Resolution`, not a tunable):
#: ACCEPTED (a human confirmed the fix as merged) and OVERRIDDEN (a human
#: rewrote the fix). An override's final text lives only in the resolutions
#: log (``resolved_text``) — custodex never writes it to the doc, and the
#: engine's own ticket status for it is CHANGES_REQUESTED — so an override
#: attests only once that text is in the doc body — until then it DISPUTES
#: the doc (a change request still pending). REJECTED ("the fix was wrong;
#: drift stands") is never an attestation. INVALIDATED ("a non-event") is
#: left out deliberately — under-claiming a human attestation is the safe
#: direction, and it differs from what counts as a REVIEW elsewhere (an SLA
#: bump) by design.
VERIFYING_RESOLUTIONS: frozenset[Resolution] = frozenset(
    {Resolution.ACCEPTED, Resolution.OVERRIDDEN}
)

#: The resolution outcomes that DISPUTE the doc as it stands (semantics, not a
#: tunable): one current REJECTED review withholds every claim on its doc — the
#: doc has ONE verdict. Disjoint from :data:`VERIFYING_RESOLUTIONS`; the one
#: outcome in neither is INVALIDATED, which judges the drift ("a non-event"),
#: not the content. An OVERRIDDEN review whose text has not landed also
#: disputes (see the module docstring).
DISPUTING_RESOLUTIONS: frozenset[Resolution] = frozenset({Resolution.REJECTED})

#: The OKF v0.2 prefix a ``verified.by`` MUST carry for human confirmation.
_HUMAN_PREFIX = "human:"

#: doc-style document-type stem → OKF display type.
_TYPE_BY_STYLE = {
    "api-reference": "API Reference",
    "explanation": "Explanation",
    "how-to": "How-To Guide",
    "tutorial": "Tutorial",
}

#: Audience fallback when no doc-style map is available.
_TYPE_BY_AUDIENCE = {
    Audience.USER_GUIDE: "User Guide",
    Audience.ENG_GUIDE: "Engineering Guide",
}

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^>\s*(\S.*?)\s*$", re.MULTILINE)


class OkfExportResult(BaseModel):
    """One export run's accounting (bundle-relative paths, sorted — K10)."""

    model_config = _MODEL_CONFIG

    written: tuple[str, ...]
    unchanged: tuple[str, ...]
    #: Doc ids whose source file is missing on disk — reported, never fatal.
    skipped: tuple[str, ...]


def okf_type_for(spec: DocumentSpec, doc_style: DocStyleMap | None) -> str:
    """The REQUIRED ``type`` value: doc-style mapped, else the audience."""
    if doc_style is not None:
        stem = doc_style.style_for(spec.id).document_type
        mapped = _TYPE_BY_STYLE.get(stem)
        if mapped is not None:
            return mapped
        return stem.replace("-", " ").title()
    return _TYPE_BY_AUDIENCE[spec.audience]


def _frontmatter(
    spec: DocumentSpec,
    body: str,
    fingerprint: str | None,
    *,
    doc_style: DocStyleMap | None,
    generated_by: str,
    verified: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    """The OKF front-matter mapping, in the FIXED emission order (K10)."""
    heading = _H1_RE.search(body)
    quote = _BLOCKQUOTE_RE.search(body)
    out: dict[str, object] = {"type": okf_type_for(spec, doc_style)}
    out["title"] = heading.group(1) if heading else spec.id
    if quote:
        out["description"] = quote.group(1)
    out["resource"] = posixpath.normpath(spec.path)
    out["tags"] = [spec.audience.value]
    out["generated"] = {"by": generated_by}  # no `at` — clock-free (K10)
    if verified:
        out["verified"] = [{"by": by, "at": at} for by, at in verified]
    if spec.code_refs:
        out["sources"] = [
            {"resource": posixpath.normpath(ref.path)} for ref in spec.code_refs
        ]
    custodex_block: dict[str, object] = {
        "doc_id": spec.id,
        "audience": spec.audience.value,
    }
    if fingerprint is not None:
        custodex_block["fingerprint"] = fingerprint
    out["custodex"] = custodex_block
    return out


class _Review(NamedTuple):
    """One record's last-write resolution that no newer record supersedes."""

    #: The code surface the record was graded against (current iff it is the
    #: doc's stored fingerprint).
    surface_hash: str
    outcome: Resolution
    #: ``human:<resolved_by>``, whitespace-collapsed; ``None`` when unrecorded.
    by: str | None
    #: The resolution's ``resolved_at``, emitted verbatim.
    at: str
    #: ``at`` parsed — the chronological sort key (K10).
    instant: datetime
    #: OVERRIDDEN only: the human's final text, stripped; ``None`` if blank.
    text: str | None


def _actor(resolved_by: str | None) -> str | None:
    """``human:<id>`` with whitespace collapsed (K10); ``None`` if unrecorded."""
    name = " ".join((resolved_by or "").split())
    return f"{_HUMAN_PREFIX}{name}" if name else None


def _instant(value: str, *, what: str) -> datetime:
    """Parse an ISO instant for comparison; a naive stamp is read as UTC.

    Loud (K8): an unparseable stamp is a :class:`SchemaError` naming ``what``
    — never a bare ``ValueError``, and never a naive-vs-aware ``TypeError``.
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaError(f"{what} is not an ISO instant: {value!r}") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _reviews_by_doc(
    records: Sequence[ReviewRecord],
    resolutions: Sequence[ResolutionRecord],
) -> dict[str, list[_Review]]:
    """doc_id → the reviews no newer record supersedes (the log-level join).

    Pure (K1). One review per review record, from its LAST-WRITE resolution
    only (``resolved_index``: a later appended line corrects an earlier one,
    so a retracted accept is gone — the correction counts whoever wrote it).
    Orphan resolutions (no such record) join nothing. A review recorded
    strictly before the newest record of its doc is superseded. When no
    resolution joins a record there is nothing to supersede and no instant is
    read; otherwise every record's ``detected_at`` is parsed (any may
    supersede), so a corrupt stamp anywhere in the review log is loud (K8), as
    a corrupt line is for ``read_all``. Records sharing a record_id share
    their doc and surface (the id hashes both).
    """
    record_by_id = {record.record_id: record for record in records}
    joined = [
        (record_by_id[record_id], resolution)
        for record_id, resolution in resolved_index(list(resolutions)).items()
        if record_id in record_by_id
    ]
    if not joined:
        return {}
    newest: dict[str, datetime] = {}
    for record in records:
        seen = _instant(
            record.detected_at,
            what=f"review record {record.record_id!r}: detected_at",
        )
        newest[record.doc_id] = max(seen, newest.get(record.doc_id, seen))
    reviews: dict[str, list[_Review]] = {}
    for record, resolution in joined:
        resolved = _instant(
            resolution.resolved_at,
            what=f"resolution of record {record.record_id!r}: resolved_at",
        )
        if resolved < newest[record.doc_id]:
            continue
        text = None
        if resolution.resolution is Resolution.OVERRIDDEN:
            text = (resolution.resolved_text or "").strip() or None
        reviews.setdefault(record.doc_id, []).append(
            _Review(
                record.surface_hash,
                resolution.resolution,
                _actor(resolution.resolved_by),
                resolution.resolved_at,
                resolved,
                text,
            )
        )
    return reviews


def _attests(review: _Review, body: str) -> bool | None:
    """``True`` attests the doc, ``False`` disputes it, ``None`` is neutral."""
    if review.outcome is Resolution.OVERRIDDEN:
        # An override attests only once its text landed; until then it is a
        # change request against the doc as it stands.
        return review.text is not None and review.text in body
    if review.outcome in DISPUTING_RESOLUTIONS:
        return False
    return True if review.outcome in VERIFYING_RESOLUTIONS else None


def _bound_verifications(
    reviews: Sequence[_Review], fingerprint: str | None, body: str
) -> tuple[tuple[str, str], ...]:
    """``(by, at)`` events for the doc as it stands, ignoring drift.

    Only CURRENT reviews count — graded against ``fingerprint`` (no stored
    fingerprint, ``None``, matches nothing: a surface hash is a string). Any
    current review that disputes the doc withholds every event on it; the
    rest are one event per attesting review with a named resolver.
    Identical events (a run's records resolved by one person in one instant)
    collapse to one. Ordered by parsed instant, then resolver, then the
    verbatim stamp, so the bytes are independent of log order (K10).
    """
    events: set[tuple[datetime, str, str]] = set()
    for review in reviews:
        if review.surface_hash != fingerprint:
            continue
        stance = _attests(review, body)
        if stance is False:
            return ()
        if stance and review.by is not None:
            events.add((review.instant, review.by, review.at))
    return tuple((by, at) for _, by, at in sorted(events))


def _doc_sources(
    config: MonitorConfig, root: Path
) -> Iterator[tuple[DocumentSpec, str, Path | None]]:
    """``(spec, bundle-relative path, source or None if missing)`` per doc.

    Guards run over EVERY doc before the first source existence check, so a
    missing file can never mask a collision (adversarial-review findings, all
    K8): a path escaping the bundle root, a ``log.md``, a bundle-ROOT
    ``index.md`` and two doc ids on ONE bundle path (compared once
    normalised — the bundle writes one file per path, so the later concept
    would silently replace the earlier one and its verdict) are a loud
    :class:`ConfigError`.
    """
    placed: list[tuple[DocumentSpec, str]] = []
    owner_by_path: dict[str, str] = {}
    for spec in config.documents:
        rel_path = posixpath.normpath(spec.path)
        if posixpath.isabs(rel_path) or rel_path == ".." or rel_path.startswith("../"):
            raise ConfigError(
                f"document {spec.id!r} path {spec.path!r} escapes the bundle root"
            )
        if posixpath.basename(rel_path) == "log.md":
            raise ConfigError(
                f"document {spec.id!r} path {rel_path!r} collides with the "
                "reserved OKF log filename (log.md)"
            )
        if rel_path == "index.md":
            raise ConfigError(
                f"document {spec.id!r} path 'index.md' collides with the "
                "generated bundle-root index file — move the landing doc "
                "into a subdirectory"
            )
        owner = owner_by_path.setdefault(rel_path, spec.id)
        if owner != spec.id:
            raise ConfigError(
                f"documents {owner!r} and {spec.id!r} share the bundle path "
                f"{rel_path!r} — each OKF concept needs its own file"
            )
        placed.append((spec, rel_path))
    for spec, rel_path in placed:
        source = root / rel_path
        yield spec, rel_path, source if source.is_file() else None


def pending_verifications(
    config: MonitorConfig,
    root: Path,
    *,
    records: Sequence[ReviewRecord] = (),
    resolutions: Sequence[ResolutionRecord] = (),
) -> tuple[str, ...]:
    """Doc ids that WOULD carry ``verified`` if drift-free (pure — K1), sorted.

    Every gate of the module docstring except the drift gate — the question
    that decides whether a drift report is needed at all, so ``cdx okf``
    extracts code only when a verification is at stake. It agrees with
    :func:`render_bundle` under a drift report with no drift. Reads a doc
    only when a review of it survives the log-level join.
    """
    reviews = _reviews_by_doc(records, resolutions)
    if not reviews:
        return ()
    pending: set[str] = set()
    for spec, rel_path, source in _doc_sources(config, root):
        if (
            source is None
            or spec.id not in reviews
            or posixpath.basename(rel_path) == "index.md"
        ):
            continue
        doc = parse_doc(source)
        if _bound_verifications(reviews[spec.id], stored_fingerprint(doc), doc.body):
            pending.add(spec.id)
    return tuple(sorted(pending))


def _render_concept(frontmatter: dict[str, object], body: str) -> str:
    """Front matter + verbatim body (deterministic YAML — fixed order, K10)."""
    block = yaml.safe_dump(
        frontmatter, sort_keys=False, default_flow_style=False, allow_unicode=True
    )
    return f"---\n{block}---\n{body}"


def render_bundle(
    config: MonitorConfig,
    root: Path,
    *,
    doc_style: DocStyleMap | None = None,
    generated_by: str = GENERATED_BY,
    records: Sequence[ReviewRecord] = (),
    resolutions: Sequence[ResolutionRecord] = (),
    drift_report: DriftReport | None = None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Render the whole bundle in memory (pure — K1).

    Returns ``(files, skipped)``: bundle-relative path → exact text, plus the
    doc ids whose source file is missing. Reserved OKF filenames: a managed
    doc NAMED ``index.md`` (a landing/collection page — custodex's own
    dogfood config has one) IS an OKF index file, so its body is emitted
    frontmatter-less as the per-directory index the spec reserves that name
    for — it is never written as a concept. A doc named ``log.md`` has no
    such reading and is a loud :class:`ConfigError` (K8).

    ``records``/``resolutions`` are the review and resolutions logs as read,
    and ``drift_report`` is the CURRENT :func:`custodex.drift.detect` report
    for ``config``. The ``verified`` join (the module docstring) happens
    here, beside the fingerprint and body it binds to. ``drift_report=None``
    means drift was not checked, so no doc can be shown resolved: nothing
    verifies and the join does not run — under-claiming is the safe default.
    """
    if drift_report is None:
        reviews: dict[str, list[_Review]] = {}
        drifted: set[str] = set()
    else:
        reviews = _reviews_by_doc(records, resolutions)
        drifted = {drift.doc_id for drift in drift_report.drifts}
    files: dict[str, str] = {}
    skipped: list[str] = []
    entries: list[tuple[str, str, str | None]] = []  # (rel_path, title, desc)
    for spec, rel_path, source in _doc_sources(config, root):
        if source is None:
            skipped.append(spec.id)
            continue
        if posixpath.basename(rel_path) == "index.md":
            # The spec reserves index.md at ANY level for a directory index
            # ("contain no frontmatter"); a landing-page doc maps onto it
            # body-verbatim, never as a concept.
            files[rel_path] = parse_doc(source).body
            continue
        doc = parse_doc(source)
        fingerprint = stored_fingerprint(doc)
        frontmatter = _frontmatter(
            spec,
            doc.body,
            fingerprint,
            doc_style=doc_style,
            generated_by=generated_by,
            verified=(
                ()
                if spec.id in drifted
                else _bound_verifications(
                    reviews.get(spec.id, ()), fingerprint, doc.body
                )
            ),
        )
        files[rel_path] = _render_concept(frontmatter, doc.body)
        heading = _H1_RE.search(doc.body)
        quote = _BLOCKQUOTE_RE.search(doc.body)
        entries.append(
            (
                rel_path,
                heading.group(1) if heading else spec.id,
                quote.group(1) if quote else None,
            )
        )

    lines = ["# Index", ""]
    for rel_path, title, description in sorted(entries):
        suffix = f" - {description}" if description else ""
        lines.append(f"* [{title}]({rel_path}){suffix}")
    index_body = "\n".join(lines) + "\n"
    files["index.md"] = f'---\nokf_version: "{OKF_VERSION}"\n---\n{index_body}'
    return files, tuple(sorted(skipped))


def export_okf(
    config: MonitorConfig,
    root: Path,
    *,
    out_dir: Path,
    doc_style: DocStyleMap | None = None,
    generated_by: str = GENERATED_BY,
    records: Sequence[ReviewRecord] = (),
    resolutions: Sequence[ResolutionRecord] = (),
    drift_report: DriftReport | None = None,
) -> OkfExportResult:
    """Write the bundle idempotently (per-file compare-skip — K7).

    The ONE impure section of the module. Foreign files already under
    ``out_dir`` are never touched or pruned (documented limit — ``--out``
    may point at a directory that is not ours).
    """
    files, skipped = render_bundle(
        config,
        root,
        doc_style=doc_style,
        generated_by=generated_by,
        records=records,
        resolutions=resolutions,
        drift_report=drift_report,
    )
    written: list[str] = []
    unchanged: list[str] = []
    for rel_path in sorted(files):
        target = out_dir / rel_path
        text = files[rel_path]
        if target.is_file() and target.read_text(encoding="utf-8") == text:
            unchanged.append(rel_path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(rel_path)
    return OkfExportResult(
        written=tuple(written), unchanged=tuple(unchanged), skipped=skipped
    )


def check_okf(
    config: MonitorConfig,
    root: Path,
    *,
    out_dir: Path,
    doc_style: DocStyleMap | None = None,
    generated_by: str = GENERATED_BY,
    records: Sequence[ReviewRecord] = (),
    resolutions: Sequence[ResolutionRecord] = (),
    drift_report: DriftReport | None = None,
) -> tuple[str, ...]:
    """Bundle-relative paths that are stale or missing (read-only — K1)."""
    files, _ = render_bundle(
        config,
        root,
        doc_style=doc_style,
        generated_by=generated_by,
        records=records,
        resolutions=resolutions,
        drift_report=drift_report,
    )
    stale: list[str] = []
    for rel_path in sorted(files):
        target = out_dir / rel_path
        if (
            not target.is_file()
            or target.read_text(encoding="utf-8") != files[rel_path]
        ):
            stale.append(rel_path)
    return tuple(stale)
