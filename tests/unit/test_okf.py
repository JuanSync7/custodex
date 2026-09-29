"""OKF-01 — the OKF v0.2 bundle projection (`okf.py`).

A projection of existing truths (config + doc bytes + the review and
resolutions logs + the drift report), never a storage format: clock-free
(v0.2 makes `generated.at` optional — omitted), byte-idempotent, reserved
filenames honored, `custodex:` extension block as the round-trip tag.

Features: FEAT-OKF-001
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from custodex import okf
from custodex.config import Audience, CodeRef, DocumentSpec, MonitorConfig
from custodex.drift import Drift, DriftKind, DriftReport
from custodex.errors import ConfigError, SchemaError
from custodex.okf import (
    VERIFYING_RESOLUTIONS,
    OkfExportResult,
    check_okf,
    export_okf,
    okf_type_for,
    render_bundle,
)
from custodex.schema import Resolution, ResolutionRecord, ReviewRecord, Verdict

_DOC = """---
cdm:
  fingerprint: aabbccddeeff0011
---
# The Widget Guide

> Everything a widget owner needs.

<!-- CDM:BEGIN symbols -->
| a | b |
<!-- CDM:END symbols -->

See [the other guide](other.md).
"""

_PLAIN_DOC = """# Other
body only
"""


def _config() -> MonitorConfig:
    return MonitorConfig(
        documents=(
            DocumentSpec(
                id="widget",
                path="docs/widget.md",
                audience=Audience.USER_GUIDE,
                code_refs=(CodeRef(path="pkg/widget.py"), CodeRef(path="pkg/util.py")),
            ),
            DocumentSpec(
                id="other",
                path="docs/other.md",
                audience=Audience.ENG_GUIDE,
            ),
        )
    )


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "widget.md").write_text(_DOC, encoding="utf-8")
    (tmp_path / "docs" / "other.md").write_text(_PLAIN_DOC, encoding="utf-8")
    return tmp_path


#: The stored fingerprint `_DOC` carries — a record bound to it is CURRENT.
_FP = "aabbccddeeff0011"

#: A clean drift report: positive evidence that no managed doc has drift now.
_CLEAN = DriftReport(drifts=())

#: A line that IS in `_DOC`'s body — an override whose text landed on disk.
_ON_DISK = "See [the other guide](other.md)."


def _record(
    record_id: str,
    *,
    doc_id: str = "widget",
    surface_hash: str = _FP,
    detected_at: str = "2026-08-01T00:00:00Z",
    drift_kind: str = "HASH",
    verdict: Verdict = Verdict.FIX,
) -> ReviewRecord:
    """A minimal review-log record: doc_id, surface_hash and detected_at feed
    the join (drift_kind and verdict must NOT — any later record
    supersedes)."""
    return ReviewRecord(
        record_id=record_id,
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        audience=Audience.USER_GUIDE,
        drift_kind=drift_kind,
        drift_detail="surface moved",
        cause="c",
        verdict=verdict,
        surface_hash=surface_hash,
        backend_kind="mock",
        detected_at=detected_at,
        resolved_at=detected_at,
        config_snapshot={},
    )


def _resolution(
    record_id: str,
    resolution: Resolution,
    *,
    by: str | None = "juan",
    at: str = "2026-08-02T00:00:00Z",
    text: str | None = None,
) -> ResolutionRecord:
    return ResolutionRecord(
        record_id=record_id,
        resolution=resolution,
        resolved_by=by,
        resolved_at=at,
        resolved_text=text,
    )


def _drift(kind: DriftKind, doc_id: str = "widget") -> DriftReport:
    """A drift report carrying one outstanding drift of ``kind`` on ``doc_id``."""
    return DriftReport(
        drifts=(
            Drift(
                kind=kind,
                doc_id=doc_id,
                doc_path=f"docs/{doc_id}.md",
                detail="outstanding",
                audience=Audience.USER_GUIDE,
            ),
        )
    )


def _front(files: dict[str, str], rel_path: str = "docs/widget.md") -> dict:
    text = files[rel_path]
    return yaml.safe_load(text[4 : text.index("---\n", 4)])


def test_concept_frontmatter_golden(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    files, skipped = render_bundle(
        _config(),
        root,
        generated_by="custodex/test",
        records=(_record("r1"),),
        resolutions=(
            _resolution("r1", Resolution.ACCEPTED, at="2026-08-01T00:00:00Z"),
        ),
        drift_report=_CLEAN,
    )
    assert skipped == ()
    text = files["docs/widget.md"]
    # the body survives byte-for-byte after the front matter
    body_start = text.index("# The Widget Guide")
    assert text[body_start:] == _DOC[_DOC.index("# The Widget Guide") :]
    front = yaml.safe_load(text[4 : text.index("---\n", 4)])
    assert front == {
        "type": "User Guide",  # audience fallback (no doc-style map)
        "title": "The Widget Guide",
        "description": "Everything a widget owner needs.",
        "resource": "docs/widget.md",
        "tags": ["user-guide"],
        "generated": {"by": "custodex/test"},  # no `at` — clock-free (K10)
        "verified": [{"by": "human:juan", "at": "2026-08-01T00:00:00Z"}],
        "sources": [
            {"resource": "pkg/widget.py"},
            {"resource": "pkg/util.py"},
        ],
        "custodex": {
            "doc_id": "widget",
            "audience": "user-guide",
            "fingerprint": "aabbccddeeff0011",
        },
    }
    # optional families omitted, never emitted empty (spec: consumers MUST
    # NOT need them)
    other = yaml.safe_load(
        files["docs/other.md"][4 : files["docs/other.md"].index("---\n", 4)]
    )
    assert "verified" not in other and "sources" not in other
    assert "description" not in other
    assert "fingerprint" not in other["custodex"]
    assert other["type"] == "Engineering Guide"


def test_root_index_carries_only_okf_version(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    files, _ = render_bundle(_config(), root, generated_by="t")
    index = files["index.md"]
    assert index.startswith('---\nokf_version: "0.2"\n---\n')
    assert "* [Other](docs/other.md)" in index
    assert (
        "* [The Widget Guide](docs/widget.md) - Everything a widget owner needs."
        in index
    )


def test_index_named_doc_becomes_a_frontmatterless_directory_index(
    tmp_path: Path,
) -> None:
    """Dogfood finding: custodex's own `api-index` doc lives at
    docs/api/index.md — the spec reserves that name for a directory index
    ("contain no frontmatter"), so the doc maps onto it body-verbatim."""
    config = MonitorConfig(
        documents=(
            DocumentSpec(
                id="landing", path="docs/index.md", audience=Audience.USER_GUIDE
            ),
        )
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.md").write_text(
        "---\ncdm:\n  fingerprint: ff\n---\n# Landing\n\n* items\n", encoding="utf-8"
    )
    files, skipped = render_bundle(config, tmp_path, generated_by="t")
    assert skipped == ()
    assert files["docs/index.md"] == "# Landing\n\n* items\n"  # no front matter
    # and it is NOT listed as a concept in the root index
    assert "docs/index.md" not in files["index.md"]


def test_log_named_doc_is_a_loud_error(tmp_path: Path) -> None:
    config = MonitorConfig(
        documents=(
            DocumentSpec(id="bad", path="docs/log.md", audience=Audience.USER_GUIDE),
        )
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "log.md").write_text("# X\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        render_bundle(config, tmp_path, generated_by="t")


def test_okf_type_for_audience_fallback() -> None:
    spec = DocumentSpec(id="d", path="d.md", audience=Audience.ENG_GUIDE)
    assert okf_type_for(spec, None) == "Engineering Guide"


def test_export_is_idempotent_and_check_agrees(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    out_dir = tmp_path / ".cdmon" / "okf"
    config = _config()
    first = export_okf(config, root, out_dir=out_dir, generated_by="t")
    assert set(first.written) == {"docs/widget.md", "docs/other.md", "index.md"}
    second = export_okf(config, root, out_dir=out_dir, generated_by="t")
    assert second == OkfExportResult(
        written=(),
        unchanged=("docs/other.md", "docs/widget.md", "index.md"),
        skipped=(),
    )
    assert check_okf(config, root, out_dir=out_dir, generated_by="t") == ()

    # editing the source doc stales exactly that concept (+ the index when
    # its title/description line changes — here it does not)
    (root / "docs" / "other.md").write_text("# Other\nchanged\n", encoding="utf-8")
    stale = check_okf(config, root, out_dir=out_dir, generated_by="t")
    assert stale == ("docs/other.md",)


def test_missing_source_doc_is_skipped_not_fatal(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "docs" / "other.md").unlink()
    result = export_okf(_config(), root, out_dir=tmp_path / "bundle", generated_by="t")
    assert result.skipped == ("other",)
    assert "docs/other.md" not in result.written


def test_foreign_files_are_never_pruned(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    out_dir.mkdir()
    foreign = out_dir / "NOT_OURS.md"
    foreign.write_text("keep me\n", encoding="utf-8")
    export_okf(_config(), root, out_dir=out_dir, generated_by="t")
    assert foreign.read_text(encoding="utf-8") == "keep me\n"


def test_root_index_doc_and_escaping_paths_are_loud(tmp_path: Path) -> None:
    """Adversarial-review pins: a bundle-ROOT index.md doc would silently
    overwrite the generated root index; a `../` path would write outside
    the bundle. Both are loud, and BEFORE the existence check (K8)."""
    root_index = MonitorConfig(
        documents=(
            DocumentSpec(id="landing", path="index.md", audience=Audience.USER_GUIDE),
        )
    )
    with pytest.raises(ConfigError):
        render_bundle(root_index, tmp_path, generated_by="t")

    escaping = MonitorConfig(
        documents=(
            DocumentSpec(id="esc", path="../escape.md", audience=Audience.USER_GUIDE),
        )
    )
    with pytest.raises(ConfigError):
        render_bundle(escaping, tmp_path, generated_by="t")


# --- `verified` binding (idea 11 / critic 2.5): verdict + last-write + surface ---


def test_verifying_resolutions_are_exactly_accepted_and_overridden() -> None:
    """Pins the deliberate UNDER-claim: only an outcome where a human confirmed
    (ACCEPTED) or authored (OVERRIDDEN) the content is `verified`. REJECTED
    ("the fix was wrong; drift stands") never is; INVALIDATED ("a non-event")
    is left out on purpose — under-claiming a human attestation is the safe
    direction, and it is a stated choice rather than an accident."""
    # Feature: FEAT-OKF-001
    expected = frozenset({Resolution.ACCEPTED, Resolution.OVERRIDDEN})
    assert expected == VERIFYING_RESOLUTIONS


@pytest.mark.parametrize(
    ("resolution", "surface_hash", "expected"),
    [
        (
            Resolution.ACCEPTED,
            _FP,
            [{"by": "human:juan", "at": "2026-08-02T00:00:00Z"}],
        ),
        (
            Resolution.OVERRIDDEN,
            _FP,
            [{"by": "human:juan", "at": "2026-08-02T00:00:00Z"}],
        ),
        (Resolution.REJECTED, _FP, None),
        (Resolution.INVALIDATED, _FP, None),
        # an ACCEPT of a record graded against an OLDER code surface is stale:
        # the doc's stored fingerprint has moved on, so the claim does not bind
        (Resolution.ACCEPTED, "0000000000000000", None),
    ],
)
def test_verified_needs_a_verifying_outcome_bound_to_the_stored_fingerprint(
    tmp_path: Path,
    resolution: Resolution,
    surface_hash: str,
    expected: list[dict[str, str]] | None,
) -> None:
    """Bug: every resolution — a REJECTED one included — became a human
    `verified` event, with no check that the record was graded against the
    doc's CURRENT code surface. Only ACCEPTED/OVERRIDDEN outcomes whose
    record.surface_hash equals the doc's stored fingerprint may be emitted."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1", surface_hash=surface_hash),),
        # the override text is on disk, so only the verdict + surface decide
        resolutions=(_resolution("r1", resolution, text=_ON_DISK),),
        drift_report=_CLEAN,
    )
    assert _front(files).get("verified") == expected


def test_verified_is_last_write_wins_per_record(tmp_path: Path) -> None:
    """A record resolved twice is a correction (reviewlog.resolved_index):
    an ACCEPT retracted by a later REJECT emits nothing, and a REJECT later
    corrected to ACCEPT emits exactly the one accepting event — never one
    event per line of the append-only log."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    retracted, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(
            _resolution("r1", Resolution.ACCEPTED, by="bob", at="2026-08-02T00:00:00Z"),
            _resolution("r1", Resolution.REJECTED, by="bob", at="2026-08-03T00:00:00Z"),
        ),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(retracted)

    corrected, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(
            _resolution("r1", Resolution.REJECTED, by="amy", at="2026-08-02T00:00:00Z"),
            _resolution("r1", Resolution.ACCEPTED, by="bob", at="2026-08-03T00:00:00Z"),
        ),
        drift_report=_CLEAN,
    )
    assert _front(corrected)["verified"] == [
        {"by": "human:bob", "at": "2026-08-03T00:00:00Z"}
    ]


@pytest.mark.parametrize("by", [None, "", "   "])
def test_unknown_resolver_is_never_a_human_verified_event(
    tmp_path: Path, by: str | None
) -> None:
    """Bug: a resolution with no `resolved_by` (the server apply-fix route,
    an MCP call without an actor) was emitted as `human:unrecorded` — a
    human attestation nobody made. An unknown resolver emits NO event."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.ACCEPTED, by=by),),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)
    assert "unrecorded" not in files["docs/widget.md"]


def test_orphan_and_foreign_resolutions_never_verify_a_doc(tmp_path: Path) -> None:
    """A resolution whose record_id is not in the review log (orphan) is
    ignored, and a record about ANOTHER doc never lends its verification to
    this one — even when the surface hashes happen to coincide."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r-other", doc_id="other"),),
        resolutions=(
            _resolution("r-orphan", Resolution.ACCEPTED),
            _resolution("r-other", Resolution.ACCEPTED),
        ),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)
    assert "verified" not in _front(files, "docs/other.md")


def test_doc_without_a_stored_fingerprint_is_never_verified(tmp_path: Path) -> None:
    """No stored fingerprint means there is no code surface to bind a claim
    to, so no resolution can verify the doc."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1", doc_id="other"),),
        resolutions=(_resolution("r1", Resolution.ACCEPTED),),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files, "docs/other.md")


def test_verified_events_are_sorted_and_input_order_free(tmp_path: Path) -> None:
    """K10: several bound verifications are emitted sorted by (at, by), and
    the bytes do not depend on the order the logs were read in."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    records = (_record("r1"), _record("r2"))
    resolutions = (
        _resolution(
            "r2",
            Resolution.OVERRIDDEN,
            by="zed",
            at="2026-08-01T00:00:00Z",
            text=_ON_DISK,  # the override's text is in the doc (gate 3)
        ),
        _resolution("r1", Resolution.ACCEPTED, by="amy", at="2026-08-05T00:00:00Z"),
    )
    forward, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    backward, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=tuple(reversed(records)),
        resolutions=tuple(reversed(resolutions)),
        drift_report=_CLEAN,
    )
    assert forward == backward
    assert _front(forward)["verified"] == [
        {"by": "human:zed", "at": "2026-08-01T00:00:00Z"},
        {"by": "human:amy", "at": "2026-08-05T00:00:00Z"},
    ]


def test_identical_events_from_one_run_collapse_to_one(tmp_path: Path) -> None:
    """A run's HASH and REGION records share a surface; one person accepting
    both in the same instant (an injected clock, as MCP uses) is ONE
    attestation, not two identical `verified` entries."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("hash-rec"), _record("region-rec")),
        resolutions=(
            _resolution("hash-rec", Resolution.ACCEPTED),
            _resolution("region-rec", Resolution.ACCEPTED),
        ),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:juan", "at": "2026-08-02T00:00:00Z"}
    ]


def test_verified_binds_the_code_surface_not_the_prose(tmp_path: Path) -> None:
    """Honest limit, pinned so no docstring over-claims it: the stored
    fingerprint is a CODE-surface hash (K2), so a prose-only edit leaves it
    unchanged and the claim survives, while a code change that moves the
    fingerprint drops it. Binding to the prose would need a doc digest
    captured at resolve time — a separate additive schema slice."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    kwargs = {
        "records": (_record("r1"),),
        "resolutions": (_resolution("r1", Resolution.ACCEPTED),),
        "drift_report": _CLEAN,
    }
    doc = root / "docs" / "widget.md"
    doc.write_text(_DOC + "\nUnreviewed prose nobody verified.\n", encoding="utf-8")
    prose_edit, _ = render_bundle(_config(), root, generated_by="t", **kwargs)
    assert _front(prose_edit)["verified"] == [
        {"by": "human:juan", "at": "2026-08-02T00:00:00Z"}
    ]

    doc.write_text(_DOC.replace(_FP, "1122334455667788"), encoding="utf-8")
    code_moved, _ = render_bundle(_config(), root, generated_by="t", **kwargs)
    assert "verified" not in _front(code_moved)


def test_export_with_verifications_is_idempotent_and_check_agrees(
    tmp_path: Path,
) -> None:
    """K7: re-exporting with the same logs writes nothing; `check` agrees.
    A retraction appended to the resolutions log stales exactly the one
    concept whose `verified` claim it withdraws."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    config = _config()
    records = (_record("r1"),)
    accepted = (_resolution("r1", Resolution.ACCEPTED),)
    export_okf(
        config,
        root,
        out_dir=out_dir,
        generated_by="t",
        drift_report=_CLEAN,
        records=records,
        resolutions=accepted,
    )
    again = export_okf(
        config,
        root,
        out_dir=out_dir,
        generated_by="t",
        drift_report=_CLEAN,
        records=records,
        resolutions=accepted,
    )
    assert again.written == ()
    assert (
        check_okf(
            config,
            root,
            out_dir=out_dir,
            generated_by="t",
            drift_report=_CLEAN,
            records=records,
            resolutions=accepted,
        )
        == ()
    )
    retracted = (
        *accepted,
        _resolution("r1", Resolution.REJECTED, at="2026-08-03T00:00:00Z"),
    )
    assert check_okf(
        config,
        root,
        out_dir=out_dir,
        generated_by="t",
        drift_report=_CLEAN,
        records=records,
        resolutions=retracted,
    ) == ("docs/widget.md",)


# --- review round 1: the claim needs a RESOLVED doc, not just a matching hash ---


@pytest.mark.parametrize(
    "report",
    [
        None,
        _drift(DriftKind.REGION),
        _drift(DriftKind.SUSPECT_LINK),
        _drift(DriftKind.HASH),
        _drift(DriftKind.UNHEALABLE),
    ],
    ids=["unchecked", "region", "suspect-link", "hash", "unhealable"],
)
def test_verified_needs_positive_evidence_the_doc_is_drift_free(
    tmp_path: Path, report: DriftReport | None
) -> None:
    """Bug (review r1, major): the surface-hash gate never checked that the
    drift was RESOLVED. A REGION or SUSPECT_LINK record's surface_hash equals
    the stored fingerprint BEFORE any fix lands, so accepting an unapplied
    proposal (or an escalation) published `verified` over content `cdx check`
    still reports as drifted. A doc verifies only on positive evidence: a
    drift report was supplied and it has no drift on that doc. No report
    (unchecked) verifies nothing — the safe direction."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.ACCEPTED),),
        drift_report=report,
    )
    assert "verified" not in _front(files)


def test_drift_on_another_doc_does_not_block_this_one(tmp_path: Path) -> None:
    """The drift gate is per document: an outstanding drift on `other` leaves
    a drift-free `widget`'s bound verification intact."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.ACCEPTED),),
        drift_report=_drift(DriftKind.REGION, doc_id="other"),
    )
    assert _front(files)["verified"] == [
        {"by": "human:juan", "at": "2026-08-02T00:00:00Z"}
    ]


@pytest.mark.parametrize(
    ("later_doc", "later_detected_at", "superseded"),
    [
        ("widget", "2026-08-03T00:00:00Z", True),
        ("widget", "2026-08-02T00:30:00+00:00", True),
        # 2026-08-02T01:00Z — LATER as an instant, EARLIER as a string
        ("widget", "2026-08-01T23:00:00-02:00", True),
        # the SAME instant as the resolution — not strictly later
        ("widget", "2026-08-02T00:00:00Z", False),
        # 00:00Z again — EQUAL as an instant, LATER as a string
        ("widget", "2026-08-02T01:00:00+01:00", False),
        ("widget", "2026-08-01T12:00:00Z", False),
        # a later record about ANOTHER doc never supersedes this one
        ("other", "2026-08-03T00:00:00Z", False),
    ],
)
def test_a_later_review_record_supersedes_the_attestation(
    tmp_path: Path, later_doc: str, later_detected_at: str, superseded: bool
) -> None:
    """Bug (review r1): an attestation is for the doc as it stood when the
    human resolved. Any review record for the SAME doc detected strictly
    LATER (a machine heal the human never saw, a code move and its revert)
    supersedes it. Instants compare as parsed datetimes, never as strings."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(
            _record("r1"),
            _record("r-later", doc_id=later_doc, detected_at=later_detected_at),
        ),
        resolutions=(_resolution("r1", Resolution.ACCEPTED),),
        drift_report=_CLEAN,
    )
    expected = (
        None if superseded else [{"by": "human:juan", "at": "2026-08-02T00:00:00Z"}]
    )
    assert _front(files).get("verified") == expected


def test_a_reverted_surface_does_not_revive_an_old_attestation(
    tmp_path: Path,
) -> None:
    """Bug (review r1): an ACCEPT at surface S1 came back after S1 → S2 → S1,
    over prose added in between that nobody reviewed. The machine heals at S2
    and back at S1 are later records, so the old accept is superseded; a
    resolution recorded AT OR AFTER the newest record, of a record bound to
    the current surface, verifies the doc again (review r2 corrected this
    rationale: it need not be the latest record — see
    test_a_review_after_the_newest_record_lifts_supersession)."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    records = (
        _record("r-s1", detected_at="2026-08-01T00:00:00Z"),
        _record(
            "r-s2", surface_hash="2222222222222222", detected_at="2026-08-03T00:00:00Z"
        ),
        _record("r-back", detected_at="2026-08-04T00:00:00Z"),
    )
    old_accept = _resolution("r-s1", Resolution.ACCEPTED, by="alice")
    revived, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=(old_accept,),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(revived)

    fresh, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=(
            old_accept,
            _resolution(
                "r-back", Resolution.ACCEPTED, by="bob", at="2026-08-05T00:00:00Z"
            ),
        ),
        drift_report=_CLEAN,
    )
    assert _front(fresh)["verified"] == [
        {"by": "human:bob", "at": "2026-08-05T00:00:00Z"}
    ]


@pytest.mark.parametrize(
    ("text", "verified"),
    [
        (_ON_DISK, True),
        (f"  {_ON_DISK}\n", True),  # surrounding whitespace is not content
        ("| connect | opens a TLS socket; see the security guide |", False),
        (None, False),  # no recorded text: nothing of the human's is on disk
        ("", False),
        ("  \n", False),  # blank would be `in` every body — never a match
    ],
)
def test_an_override_verifies_only_once_the_humans_text_is_on_disk(
    tmp_path: Path, text: str | None, verified: bool
) -> None:
    """Bug (review r1): custodex never writes `resolved_text` into the doc
    (the engine's own ticket status for OVERRIDDEN is CHANGES_REQUESTED), so
    an OVERRIDDEN resolution attested the machine text the human overrode.
    It verifies only when the human's final text appears verbatim in the
    current doc body; an override with no recorded text attests nothing."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.OVERRIDDEN, text=text),),
        drift_report=_CLEAN,
    )
    expected = (
        [{"by": "human:juan", "at": "2026-08-02T00:00:00Z"}] if verified else None
    )
    assert _front(files).get("verified") == expected


def test_accepted_ignores_any_recorded_text(tmp_path: Path) -> None:
    """Only an override AUTHORS text; an ACCEPT confirms the fix as merged, so
    a stray `resolved_text` on it (never on disk) does not withhold the
    claim."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(
            _resolution("r1", Resolution.ACCEPTED, text="never written to the doc"),
        ),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:juan", "at": "2026-08-02T00:00:00Z"}
    ]


@pytest.mark.parametrize(
    ("detected_at", "resolved_at", "field"),
    [
        ("yesterday", "2026-08-02T00:00:00Z", "detected_at"),
        ("2026-08-01T00:00:00Z", "soon", "resolved_at"),
    ],
)
def test_a_malformed_instant_the_join_reads_is_a_loud_schema_error(
    tmp_path: Path, detected_at: str, resolved_at: str, field: str
) -> None:
    """K8: supersession compares instants, so an unparseable `detected_at` or
    `resolved_at` on a log line the join must read is a loud, typed
    SchemaError naming the field — never a silent pass or a bare
    ValueError."""
    # Feature: FEAT-OKF-001
    with pytest.raises(SchemaError, match=field):
        render_bundle(
            _config(),
            _repo(tmp_path),
            generated_by="t",
            records=(_record("r1", detected_at=detected_at),),
            resolutions=(_resolution("r1", Resolution.ACCEPTED, at=resolved_at),),
            drift_report=_CLEAN,
        )


def test_a_malformed_stamp_anywhere_in_the_review_log_is_loud(
    tmp_path: Path,
) -> None:
    """K8: the join reads the whole review log (any record may supersede), so
    a corrupt `detected_at` is loud even on a record of a doc nobody
    verified — the same rule `read_all` applies to a corrupt line."""
    # Feature: FEAT-OKF-001
    with pytest.raises(SchemaError, match="'r-other': detected_at"):
        render_bundle(
            _config(),
            _repo(tmp_path),
            generated_by="t",
            records=(
                _record("r1"),
                _record("r-other", doc_id="other", detected_at="yesterday"),
            ),
            resolutions=(_resolution("r1", Resolution.ACCEPTED),),
            drift_report=_CLEAN,
        )


@pytest.fixture
def _non_utc_local_zone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the test with the process's LOCAL zone at UTC+9 (a POSIX TZ string,
    so no tzdata is needed), restoring the zone afterwards. A naive-as-local
    reading then differs from naive-as-UTC on every host, including a CI
    runner whose local zone IS UTC."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is POSIX-only")
    monkeypatch.setenv("TZ", "JST-9")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.parametrize(
    ("later_detected_at", "superseded"),
    [("2026-08-02T00:00:01+00:00", True), ("2026-08-01T23:59:59Z", False)],
)
@pytest.mark.usefixtures("_non_utc_local_zone")
def test_naive_and_aware_instants_compare_as_utc(
    tmp_path: Path, later_detected_at: str, superseded: bool
) -> None:
    """A log may mix naive and offset-aware ISO stamps (an injected clock, an
    older writer). Comparing them must not crash with a bare TypeError (K8):
    a naive stamp is read as UTC — whatever the host's local zone (review r2
    gap R2-14u: under TZ=UTC a naive-as-LOCAL reading passed by accident)."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(
            _record("r1"),
            _record("r-later", detected_at=later_detected_at),
        ),
        resolutions=(_resolution("r1", Resolution.ACCEPTED, at="2026-08-02T00:00:00"),),
        drift_report=_CLEAN,
    )
    expected = (
        None if superseded else [{"by": "human:juan", "at": "2026-08-02T00:00:00"}]
    )
    assert _front(files).get("verified") == expected


# --- review round 1: mutation-gap witnesses (M1/M4/M17, M3, M5, M7) ------------


def test_distinct_resolvers_at_one_instant_are_all_kept_sorted_by_resolver(
    tmp_path: Path,
) -> None:
    """Several people resolving different records bound to the current surface
    at the SAME instant each emit an event (only fully identical (by, at)
    events collapse), tie-broken by resolver name, and the bytes do not
    depend on the order the logs were read in (K10). Eight names, so a
    set-iteration order can not pass for sorted by luck."""
    # Feature: FEAT-OKF-001
    names = ["hal", "eve", "bob", "gus", "amy", "fay", "dan", "cat"]
    at = "2026-08-02T00:00:00Z"
    records = tuple(_record(f"r-{name}") for name in names)
    resolutions = tuple(
        _resolution(f"r-{name}", Resolution.ACCEPTED, by=name, at=at) for name in names
    )
    root = _repo(tmp_path)
    forward, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    backward, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=tuple(reversed(records)),
        resolutions=tuple(reversed(resolutions)),
        drift_report=_CLEAN,
    )
    assert forward == backward
    assert _front(forward)["verified"] == [
        {"by": f"human:{name}", "at": at} for name in sorted(names)
    ]


def test_one_resolver_at_two_instants_is_two_events(tmp_path: Path) -> None:
    """The same person verifying two records of the current surface at two
    different instants is two attestations, not one per person."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"), _record("r2")),
        resolutions=(
            _resolution("r1", Resolution.ACCEPTED, by="bob", at="2026-08-02T00:00:00Z"),
            _resolution("r2", Resolution.ACCEPTED, by="bob", at="2026-08-04T00:00:00Z"),
        ),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:bob", "at": "2026-08-02T00:00:00Z"},
        {"by": "human:bob", "at": "2026-08-04T00:00:00Z"},
    ]


def test_a_later_resolution_without_a_resolver_still_retracts(tmp_path: Path) -> None:
    """Last-write-wins runs over EVERY line: a later REJECT with no
    `resolved_by` (an MCP call without an actor, `cdx resolve` without
    `--by`) still withdraws an earlier named ACCEPT. The anonymous line is
    not filtered out before the join."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(
            _resolution("r1", Resolution.ACCEPTED, by="bob", at="2026-08-02T00:00:00Z"),
            _resolution("r1", Resolution.REJECTED, by=None, at="2026-08-03T00:00:00Z"),
        ),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


def test_resolver_name_is_whitespace_normalized(tmp_path: Path) -> None:
    """`cdx resolve --by` stores the value as typed; the emitted actor is
    normalized (K10), so `  alice ` publishes as `human:alice`."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.ACCEPTED, by="  alice \t"),),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:alice", "at": "2026-08-02T00:00:00Z"}
    ]


# --- review round 2: ONE verdict per doc — a current dispute vetoes it --------

#: A change the human asked for that is NOT in `_DOC` (an unlanded override).
_NOT_ON_DISK = "| connect | opens a TLS socket |"


def _run_records() -> tuple[ReviewRecord, ReviewRecord]:
    """One `monitor --apply` run's HASH and REGION records for `widget`: both
    graded against the current surface, stamped microseconds apart (the
    production clock gives each record its own instant and id)."""
    return (
        _record("hash-rec", detected_at="2026-08-01T00:00:00.000001Z"),
        _record("region-rec", detected_at="2026-08-01T00:00:00.000002Z"),
    )


def test_resolution_outcomes_split_into_attest_dispute_and_neutral() -> None:
    """Pins the outcome semantics the doc-level verdict rests on: ACCEPTED and
    OVERRIDDEN can attest; REJECTED ("the fix was wrong") disputes; the sets
    are disjoint, and INVALIDATED ("a non-event") is the one outcome that
    neither attests nor disputes. (An OVERRIDDEN whose text has not landed
    disputes too — a pending change request; pinned behaviourally below.)"""
    # Feature: FEAT-OKF-001
    disputing = okf.DISPUTING_RESOLUTIONS
    assert disputing == frozenset({Resolution.REJECTED})
    assert not (disputing & VERIFYING_RESOLUTIONS)
    assert set(Resolution) - VERIFYING_RESOLUTIONS - disputing == {
        Resolution.INVALIDATED
    }


@pytest.mark.parametrize("dispute_first", [False, True], ids=["after", "before"])
@pytest.mark.parametrize(
    ("outcome", "by", "text"),
    [
        (Resolution.REJECTED, "bob", None),
        (Resolution.REJECTED, None, None),
        (Resolution.OVERRIDDEN, "dave", _NOT_ON_DISK),
        (Resolution.OVERRIDDEN, "dave", None),
    ],
    ids=["rejected", "rejected-anonymously", "override-unlanded", "override-no-text"],
)
def test_a_current_review_disputing_the_doc_withholds_every_claim_on_it(
    tmp_path: Path,
    dispute_first: bool,
    outcome: Resolution,
    by: str | None,
    text: str | None,
) -> None:
    """Bug (review r2, major): the gates ran per record, so alice's ACCEPT of
    a run's HASH record kept `verified: human:alice` while bob REJECTED the
    same run's REGION record — content on disk a human explicitly disputed.
    A doc has ONE verdict: any CURRENT review that disputes it (a REJECT,
    named or not, or an OVERRIDE whose text is not in the doc — a change
    request still pending) withholds every claim on the doc, in either
    order."""
    # Feature: FEAT-OKF-001
    early, late = "2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"
    dispute_at, accept_at = (early, late) if dispute_first else (late, early)
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=_run_records(),
        resolutions=(
            _resolution("hash-rec", Resolution.ACCEPTED, by="alice", at=accept_at),
            _resolution("region-rec", outcome, by=by, at=dispute_at, text=text),
        ),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


@pytest.mark.parametrize(
    ("records", "resolutions", "expected"),
    [
        pytest.param(
            (*_run_records(), _record("r-old", surface_hash="0000000000000000")),
            (
                _resolution("hash-rec", Resolution.ACCEPTED, by="alice"),
                _resolution(
                    "r-old", Resolution.REJECTED, by="bob", at="2026-08-03T00:00:00Z"
                ),
            ),
            [{"by": "human:alice", "at": "2026-08-02T00:00:00Z"}],
            id="reject-of-an-older-surface",
        ),
        pytest.param(
            (
                _record("region-dry", detected_at="2026-08-01T00:00:00Z"),
                _record("hash-rec", detected_at="2026-08-03T00:00:00Z"),
            ),
            (
                _resolution(
                    "region-dry",
                    Resolution.REJECTED,
                    by="bob",
                    at="2026-08-02T00:00:00Z",
                ),
                _resolution(
                    "hash-rec",
                    Resolution.ACCEPTED,
                    by="alice",
                    at="2026-08-04T00:00:00Z",
                ),
            ),
            [{"by": "human:alice", "at": "2026-08-04T00:00:00Z"}],
            id="superseded-reject",
        ),
        pytest.param(
            _run_records(),
            (
                _resolution("hash-rec", Resolution.ACCEPTED, by="alice"),
                _resolution(
                    "region-rec",
                    Resolution.INVALIDATED,
                    by="bob",
                    at="2026-08-03T00:00:00Z",
                ),
            ),
            [{"by": "human:alice", "at": "2026-08-02T00:00:00Z"}],
            id="invalidated-is-neutral",
        ),
        pytest.param(
            _run_records(),
            (
                _resolution("hash-rec", Resolution.ACCEPTED, by="alice"),
                _resolution(
                    "region-rec",
                    Resolution.REJECTED,
                    by="bob",
                    at="2026-08-02T06:00:00Z",
                ),
                _resolution(
                    "region-rec",
                    Resolution.ACCEPTED,
                    by="bob",
                    at="2026-08-03T00:00:00Z",
                ),
            ),
            [
                {"by": "human:alice", "at": "2026-08-02T00:00:00Z"},
                {"by": "human:bob", "at": "2026-08-03T00:00:00Z"},
            ],
            id="corrected-reject-lifts-the-veto",
        ),
        pytest.param(
            _run_records(),
            (
                _resolution("hash-rec", Resolution.ACCEPTED, by="alice"),
                _resolution(
                    "region-rec",
                    Resolution.OVERRIDDEN,
                    by="dave",
                    at="2026-08-03T00:00:00Z",
                    text=_ON_DISK,
                ),
            ),
            [
                {"by": "human:alice", "at": "2026-08-02T00:00:00Z"},
                {"by": "human:dave", "at": "2026-08-03T00:00:00Z"},
            ],
            id="landed-override-attests",
        ),
        pytest.param(
            _run_records(),
            (
                _resolution("hash-rec", Resolution.ACCEPTED, by="alice"),
                _resolution("region-rec", Resolution.ACCEPTED, by=None),
            ),
            [{"by": "human:alice", "at": "2026-08-02T00:00:00Z"}],
            id="unnamed-accept-is-no-dispute",
        ),
    ],
)
def test_only_a_current_disputing_review_withholds_the_claim(
    tmp_path: Path,
    records: tuple[ReviewRecord, ...],
    resolutions: tuple[ResolutionRecord, ...],
    expected: list[dict[str, str]],
) -> None:
    """The veto has exactly a claim's scope. A REJECT of a record graded
    against an OLDER surface reviews a doc that no longer exists; a REJECT
    recorded BEFORE the doc's newest record reviews an earlier state; an
    INVALIDATED sibling judges the drift, not the content; a REJECT later
    corrected to ACCEPT is no longer the record's verdict; a landed
    override and an unnamed accept attest. None of them withholds a current
    ACCEPT."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    assert _front(files).get("verified") == expected


# --- review round 2: the presumption, and supersession order-freedom --------


def test_a_review_after_the_newest_record_lifts_supersession(tmp_path: Path) -> None:
    """Review r2 (the gate-6 rationale, corrected in ship shape): supersession
    is lifted by a verifying resolution recorded AT OR AFTER the doc's newest
    record, of ANY record bound to the current surface — re-accepting the
    OLD S1 record after S1 → S2 → S1 verifies — while accepting a newer
    record graded against a surface that no longer exists never can."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    records = (
        _record("r-s1", detected_at="2026-08-01T00:00:00Z"),
        _record(
            "r-s2", surface_hash="2222222222222222", detected_at="2026-08-03T00:00:00Z"
        ),
        _record("r-back", detected_at="2026-08-04T00:00:00Z"),
    )
    old_accept = _resolution("r-s1", Resolution.ACCEPTED, by="alice")
    newer_surface, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=(
            old_accept,
            _resolution(
                "r-s2", Resolution.ACCEPTED, by="bob", at="2026-08-05T00:00:00Z"
            ),
        ),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(newer_surface)

    re_accepted, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=(
            old_accept,
            _resolution(
                "r-s1", Resolution.ACCEPTED, by="alice", at="2026-08-05T00:00:00Z"
            ),
        ),
        drift_report=_CLEAN,
    )
    assert _front(re_accepted)["verified"] == [
        {"by": "human:alice", "at": "2026-08-05T00:00:00Z"}
    ]


def test_supersession_does_not_depend_on_review_log_order(tmp_path: Path) -> None:
    """Review r2 gap R2-01: the NEWEST record by instant supersedes wherever it
    sits in the log. A git-merged or multi-writer review log is not
    chronological, so "the last line is the newest" would revive a
    superseded attestation."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(
            _record("r-later", detected_at="2026-08-03T00:00:00Z"),
            _record("r1"),
        ),
        resolutions=(_resolution("r1", Resolution.ACCEPTED),),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


def test_a_later_record_at_another_surface_also_supersedes(tmp_path: Path) -> None:
    """Review r2 gap R2-02: the rule is ANY later record for the doc (a dry-run
    preview of a code change touches no doc but still supersedes), not only
    a later record graded against the claim's own surface."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(
            _record("r1"),
            _record(
                "r-s2",
                surface_hash="2222222222222222",
                detected_at="2026-08-03T00:00:00Z",
            ),
        ),
        resolutions=(_resolution("r1", Resolution.ACCEPTED),),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


def test_last_appended_resolution_wins_not_the_latest_stamp(tmp_path: Path) -> None:
    """Review r2 gap R2-05: last-write-wins is APPEND order
    (reviewlog.resolved_index), so a REJECT appended after an ACCEPT retracts
    it even when its resolved_at is earlier (clock skew between writers, a
    merged log)."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(
            _resolution("r1", Resolution.ACCEPTED, by="bob", at="2026-08-03T00:00:00Z"),
            _resolution("r1", Resolution.REJECTED, by="bob", at="2026-08-02T00:00:00Z"),
        ),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


# --- review round 2: remaining mutation gaps and design decisions -----------


@pytest.mark.parametrize("by", [" alice  smith ", "alice\tsmith", "alice\n  smith"])
def test_resolver_whitespace_collapses_to_single_spaces(
    tmp_path: Path, by: str
) -> None:
    """Review r2 gap R2-06, decided: `resolved_by` is whitespace-NORMALIZED
    (K10) — ends stripped and every interior run collapsed to one space — so
    one person typed two ways is one actor, and a newline can never leak into
    the emitted `by`."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.ACCEPTED, by=by),),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:alice smith", "at": "2026-08-02T00:00:00Z"}
    ]


def test_a_multiline_override_needs_all_of_its_text_on_disk(tmp_path: Path) -> None:
    """Review r2 gap R2-07: an override is usually a multi-line region or
    table rewrite. Its FIRST line being in the doc while its table row is not
    is a partial paste, not a landed change."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(
            _resolution(
                "r1", Resolution.OVERRIDDEN, text=f"{_ON_DISK}\n{_NOT_ON_DISK}"
            ),
        ),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


def test_accept_and_override_by_one_person_at_one_instant_is_one_event(
    tmp_path: Path,
) -> None:
    """Review r2 gap R2-11: identical `(by, at)` events collapse whatever
    outcome produced them (an injected clock, as MCP uses, resolving a run's
    HASH and REGION records in one call)."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"), _record("r2")),
        resolutions=(
            _resolution("r1", Resolution.ACCEPTED),
            _resolution("r2", Resolution.OVERRIDDEN, text=_ON_DISK),
        ),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:juan", "at": "2026-08-02T00:00:00Z"}
    ]


def test_verified_events_are_chronological_across_offset_forms(tmp_path: Path) -> None:
    """Review r2 gap R2-12, decided: events are ordered by PARSED instant, then
    resolver, then the verbatim stamp (K10) — never by the ISO string, which
    orders offset forms the other way. amy's -02:00 stamp is 01:00Z, LATER
    than bob's 00:30Z, though it sorts first as a string."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r-amy"), _record("r-bob")),
        resolutions=(
            _resolution(
                "r-amy", Resolution.ACCEPTED, by="amy", at="2026-08-01T23:00:00-02:00"
            ),
            _resolution(
                "r-bob", Resolution.ACCEPTED, by="bob", at="2026-08-02T00:30:00Z"
            ),
        ),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:bob", "at": "2026-08-02T00:30:00Z"},
        {"by": "human:amy", "at": "2026-08-01T23:00:00-02:00"},
    ]


def test_unchecked_drift_never_reads_the_review_log_instants(tmp_path: Path) -> None:
    """Review r2 gap R2-10, decided: K8 loudness covers what the join READS.
    With `drift_report=None` nothing can verify, so the join does not run and
    a corrupt stamp does not break the render — even with a resolution
    present."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1", detected_at="yesterday"),),
        resolutions=(_resolution("r1", Resolution.ACCEPTED),),
        drift_report=None,
    )
    assert "verified" not in _front(files)


# --- review round 2: is a verification at stake? (detect only if so) --------


@pytest.mark.parametrize(
    ("records", "resolutions", "pending"),
    [
        pytest.param(
            (_record("r1"),),
            (_resolution("r1", Resolution.ACCEPTED),),
            ("widget",),
            id="bound-accept",
        ),
        pytest.param((_record("r1"),), (), (), id="no-resolutions"),
        pytest.param(
            (_record("r1"),),
            (_resolution("r1", Resolution.REJECTED),),
            (),
            id="rejected-only",
        ),
        pytest.param(
            (_record("r1"),),
            (_resolution("r-orphan", Resolution.ACCEPTED),),
            (),
            id="orphan",
        ),
        pytest.param(
            (_record("r1"),),
            (_resolution("r1", Resolution.ACCEPTED, by=None),),
            (),
            id="unnamed",
        ),
        pytest.param(
            (_record("r1", surface_hash="0000000000000000"),),
            (_resolution("r1", Resolution.ACCEPTED),),
            (),
            id="older-surface",
        ),
        pytest.param(
            (_record("r1"), _record("r-later", detected_at="2026-08-03T00:00:00Z")),
            (_resolution("r1", Resolution.ACCEPTED),),
            (),
            id="superseded",
        ),
        pytest.param(
            _run_records(),
            (
                _resolution("hash-rec", Resolution.ACCEPTED, by="alice"),
                _resolution("region-rec", Resolution.REJECTED, by="bob"),
            ),
            (),
            id="vetoed",
        ),
        pytest.param(
            (_record("r1", doc_id="other"),),
            (_resolution("r1", Resolution.ACCEPTED),),
            (),
            id="no-stored-fingerprint",
        ),
    ],
)
def test_pending_verifications_are_exactly_what_a_clean_report_would_verify(
    tmp_path: Path,
    records: tuple[ReviewRecord, ...],
    resolutions: tuple[ResolutionRecord, ...],
    pending: tuple[str, ...],
) -> None:
    """Bug (review r2): `cdx okf` ran whole-config drift detection whenever
    the resolutions log had ANY entry — a log holding only a REJECT, which
    can verify nothing, made one unreadable code ref fail the export. The
    pure `pending_verifications` answers "is a verification at stake?": the
    doc ids that WOULD carry `verified` if drift-free (every gate but the
    drift gate). It agrees with `render_bundle` under a clean report."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    assert (
        okf.pending_verifications(
            _config(), root, records=records, resolutions=resolutions
        )
        == pending
    )
    files, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    verified_docs = tuple(
        spec.id
        for spec in _config().documents
        if "verified" in _front(files, spec.path)
    )
    assert verified_docs == pending


def test_pending_verifications_ignore_drift_and_log_order(tmp_path: Path) -> None:
    """`pending_verifications` takes no drift report — it is the question
    that decides whether one is needed — and, like the render, its answer
    does not depend on the order the logs were read in (K10)."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    records = (_record("r1"), _record("r-other", doc_id="other"))
    resolutions = (
        _resolution("r1", Resolution.ACCEPTED),
        _resolution("r-other", Resolution.ACCEPTED),
    )
    forward = okf.pending_verifications(
        _config(), root, records=records, resolutions=resolutions
    )
    backward = okf.pending_verifications(
        _config(),
        root,
        records=tuple(reversed(records)),
        resolutions=tuple(reversed(resolutions)),
    )
    assert forward == backward == ("widget",)


def test_the_join_reads_instants_only_when_a_resolution_joins_a_record(
    tmp_path: Path,
) -> None:
    """K8 scope (review r2 gap R2-10), decided and pinned: the review log's
    instants matter only to a resolution that joins one of its records.
    With none (no resolutions, or only orphans) nothing is read, so a corrupt
    stamp stays quiet; once one joins, EVERY record's stamp is parsed (any
    may supersede) and a corrupt one is a loud SchemaError."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    corrupt = (_record("r1"), _record("r-bad", doc_id="other", detected_at="soon"))
    for quiet in ((), (_resolution("r-orphan", Resolution.ACCEPTED),)):
        assert (
            okf.pending_verifications(
                _config(), root, records=corrupt, resolutions=quiet
            )
            == ()
        )
    with pytest.raises(SchemaError, match="'r-bad': detected_at"):
        okf.pending_verifications(
            _config(),
            root,
            records=corrupt,
            resolutions=(_resolution("r1", Resolution.ACCEPTED),),
        )


def test_one_instant_in_several_stamp_forms_orders_by_the_verbatim_stamp(
    tmp_path: Path,
) -> None:
    """Review r2 mutation gap: `at` is emitted verbatim, so one resolver's
    reviews stamped at the SAME instant in different forms (writers differ:
    `Z`, `+00:00`, another offset, naive UTC) are distinct events. Their
    order must still be fixed — instant, resolver, then the verbatim stamp —
    never the hash-seeded iteration order of a set (K10). Eight forms, so a
    lucky order cannot pass for sorted."""
    # Feature: FEAT-OKF-001
    forms = [
        "2026-08-02T00:00:00Z",
        "2026-08-02T00:00:00+00:00",
        "2026-08-02T01:00:00+01:00",
        "2026-08-01T23:00:00-01:00",
        "2026-08-02T00:00:00.000+00:00",
        "2026-08-02T02:00:00+02:00",
        "2026-08-02T00:00:00",
        "2026-08-02T00:00:00.000000Z",
    ]
    records = tuple(_record(f"r{i}") for i in range(len(forms)))
    resolutions = tuple(
        _resolution(f"r{i}", Resolution.ACCEPTED, by="bob", at=at)
        for i, at in enumerate(forms)
    )
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:bob", "at": at} for at in sorted(forms)
    ]


def test_an_index_named_doc_never_puts_a_verification_at_stake(
    tmp_path: Path,
) -> None:
    """Review r2 mutation gap: a managed doc NAMED index.md is emitted as a
    frontmatter-less directory index, so it can never carry `verified` —
    and `pending_verifications` must agree, or a bound accept on a landing
    page (custodex's own `api-index` is docs/api/index.md) would make
    `cdx okf` extract code for a claim it cannot publish."""
    # Feature: FEAT-OKF-001
    config = MonitorConfig(
        documents=(
            DocumentSpec(
                id="landing", path="docs/index.md", audience=Audience.USER_GUIDE
            ),
        )
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.md").write_text(
        f"---\ncdm:\n  fingerprint: {_FP}\n---\n# Landing\n", encoding="utf-8"
    )
    records = (_record("r1", doc_id="landing"),)
    resolutions = (_resolution("r1", Resolution.ACCEPTED),)
    assert (
        okf.pending_verifications(
            config, tmp_path, records=records, resolutions=resolutions
        )
        == ()
    )
    files, _ = render_bundle(
        config,
        tmp_path,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    assert files["docs/index.md"] == "# Landing\n"


# --- review round 3: mutation witnesses (each kills a surviving mutant) -------


def test_same_instant_ties_break_by_resolver_before_the_stamp(tmp_path: Path) -> None:
    """Mutation r3 gap M01: the documented order is (instant, RESOLVER,
    verbatim stamp). Two resolvers at ONE instant written in different stamp
    forms order by name, never by the stamp string (`+00:00` sorts before
    `Z`, so a stamp-before-resolver key puts bob first)."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r-amy"), _record("r-bob")),
        resolutions=(
            _resolution(
                "r-amy", Resolution.ACCEPTED, by="amy", at="2026-08-02T00:00:00Z"
            ),
            _resolution(
                "r-bob", Resolution.ACCEPTED, by="bob", at="2026-08-02T00:00:00+00:00"
            ),
        ),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:amy", "at": "2026-08-02T00:00:00Z"},
        {"by": "human:bob", "at": "2026-08-02T00:00:00+00:00"},
    ]


def test_an_override_must_be_on_disk_as_one_contiguous_text(tmp_path: Path) -> None:
    """Mutation r3 gap M05: "verbatim in the body" means the override text as
    ONE block. Each of its lines appearing somewhere in the doc (the heading
    here, the link line further down) is not the human's change landing, so
    the override still disputes the doc and nothing verifies."""
    # Feature: FEAT-OKF-001
    text = f"# The Widget Guide\n{_ON_DISK}"
    assert all(line in _DOC for line in text.splitlines()) and text not in _DOC
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.OVERRIDDEN, text=text),),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


@pytest.mark.parametrize("kind", ["SUSPECT_LINK", "REGION"])
def test_a_later_record_of_another_drift_kind_also_supersedes(
    tmp_path: Path, kind: str
) -> None:
    """Mutation r3 gap M06: the rule is ANY later record for the doc. A later
    SUSPECT_LINK record (an upstream doc edit) or REGION record (a
    region-only re-render) at the same surface supersedes an earlier accept
    of a HASH record exactly as a later HASH record does — supersession is
    keyed by the doc, never by (doc, drift kind)."""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(
            _record("r1"),
            _record("r-later", detected_at="2026-08-03T00:00:00Z", drift_kind=kind),
        ),
        resolutions=(_resolution("r1", Resolution.ACCEPTED),),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


def test_pending_verifications_are_sorted_across_many_docs(tmp_path: Path) -> None:
    """Mutation r3 gap M08: `pending_verifications` promises SORTED doc ids
    (K10, the pinned public signature). Eight verifiable docs — each carrying
    `_DOC`'s stored fingerprint and one bound accept — so a set's
    hash-seeded order cannot pass for sorted by luck."""
    # Feature: FEAT-OKF-001
    names = ["hal", "eve", "bob", "gus", "amy", "fay", "dan", "cat"]
    (tmp_path / "docs").mkdir()
    for name in names:
        (tmp_path / "docs" / f"{name}.md").write_text(_DOC, encoding="utf-8")
    config = MonitorConfig(
        documents=tuple(
            DocumentSpec(id=name, path=f"docs/{name}.md", audience=Audience.USER_GUIDE)
            for name in names
        )
    )
    records = tuple(_record(f"r-{name}", doc_id=name) for name in names)
    resolutions = tuple(_resolution(f"r-{name}", Resolution.ACCEPTED) for name in names)
    assert okf.pending_verifications(
        config, tmp_path, records=records, resolutions=resolutions
    ) == tuple(sorted(names))


def test_trailing_whitespace_on_an_override_is_not_content(tmp_path: Path) -> None:
    """Mutation r3 gap M15: surrounding whitespace is not content at EITHER
    end. An override typed with trailing spaces and blank lines has landed
    once its text is on disk. (The leading-space param of the override test
    cannot see the trailing half: the doc's own newline follows that line.)"""
    # Feature: FEAT-OKF-001
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(
            _resolution("r1", Resolution.OVERRIDDEN, text=f"{_ON_DISK}  \n\n"),
        ),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:juan", "at": "2026-08-02T00:00:00Z"}
    ]


def test_a_reviewed_doc_whose_file_is_missing_puts_nothing_at_stake(
    tmp_path: Path,
) -> None:
    """Mutation r3 thin pin M04 (was killed by one system param only): a
    bound accept on a doc whose file is gone cannot verify anything, so
    `pending_verifications` skips it without reading it — never a crash on
    the missing file — and agrees with the render, which lists it as
    skipped."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    (root / "docs" / "widget.md").unlink()
    records = (_record("r1"),)
    resolutions = (_resolution("r1", Resolution.ACCEPTED),)
    assert (
        okf.pending_verifications(
            _config(), root, records=records, resolutions=resolutions
        )
        == ()
    )
    files, skipped = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    assert skipped == ("widget",)
    assert "docs/widget.md" not in files


# --- review round 4: mutation witnesses (each kills a surviving mutant) -------


@pytest.mark.parametrize(
    "text",
    [
        "see [the other guide](other.md).",
        "See  [the other guide](other.md).",
        "# The Widget Guide\n> Everything a widget owner needs.",
    ],
    ids=["case", "double-space", "blank-line-dropped"],
)
def test_an_override_must_be_on_disk_byte_for_byte(tmp_path: Path, text: str) -> None:
    """Mutation r4 gaps N05/N07: "verbatim" means byte-for-byte. An override
    whose text matches the doc only after case-folding or collapsing internal
    whitespace (a doubled space, a dropped blank line) has NOT landed — the
    human's exact words are not on disk — so it still disputes the doc and
    nothing verifies. Only SURROUNDING whitespace is not content."""
    # Feature: FEAT-OKF-001
    body = _DOC.split("---\n", 2)[2]
    assert text not in body  # the premise: not on disk as typed ...
    assert (" ".join(text.split()) in " ".join(body.split())) or (
        text.casefold() in body.casefold()
    )  # ... yet present once normalised, which is what a lax check would see
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.OVERRIDDEN, text=text),),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


@pytest.mark.parametrize("verdict", [Verdict.ESCALATE, Verdict.INVALIDATE])
def test_a_later_record_of_any_verdict_also_supersedes(
    tmp_path: Path, verdict: Verdict
) -> None:
    """Mutation r4 gaps N08/N08b: ANY later record for the doc supersedes,
    whatever its VERDICT. A later ESCALATE record (an upstream doc edit's
    SUSPECT_LINK escalation, no fix) or INVALIDATE record at the same
    surface supersedes an earlier accept of a FIX record exactly as a later
    FIX record does — the human never saw what it reports — and
    `pending_verifications` agrees with the render."""
    # Feature: FEAT-OKF-001
    records = (
        _record("r1"),
        _record("r-later", detected_at="2026-08-03T00:00:00Z", verdict=verdict),
    )
    resolutions = (_resolution("r1", Resolution.ACCEPTED),)
    root = _repo(tmp_path)
    files, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)
    assert (
        okf.pending_verifications(
            _config(), root, records=records, resolutions=resolutions
        )
        == ()
    )


def test_pending_verifications_sort_by_doc_id_not_by_path(tmp_path: Path) -> None:
    """Mutation r4 gap N14: the promise is SORTED DOC IDS (K10), not ids in
    bundle-path order. The round-3 witness's paths mirrored its ids
    (`docs/<id>.md`), so a path-ordered result passed; here the ids run
    opposite to their paths."""
    # Feature: FEAT-OKF-001
    layout = {"zeta": "docs/a.md", "mid": "docs/m.md", "alpha": "docs/z.md"}
    (tmp_path / "docs").mkdir()
    for path in layout.values():
        (tmp_path / path).write_text(_DOC, encoding="utf-8")
    config = MonitorConfig(
        documents=tuple(
            DocumentSpec(id=doc_id, path=path, audience=Audience.USER_GUIDE)
            for doc_id, path in layout.items()
        )
    )
    assert okf.pending_verifications(
        config,
        tmp_path,
        records=tuple(_record(f"r-{doc_id}", doc_id=doc_id) for doc_id in layout),
        resolutions=tuple(
            _resolution(f"r-{doc_id}", Resolution.ACCEPTED) for doc_id in layout
        ),
    ) == ("alpha", "mid", "zeta")


def test_another_docs_later_record_never_supersedes_pending_either(
    tmp_path: Path,
) -> None:
    """Mutation r4 thin pin N09 (killed by one render param only):
    supersession is PER DOC. A later record for ANOTHER doc — here the
    `other` doc, dated after the accept — neither withholds `widget`'s claim
    in the render nor takes it out of `pending_verifications`, so `cdx okf`
    still detects drift for it."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    records = (
        _record("r1"),
        _record("r-other", doc_id="other", detected_at="2026-08-05T00:00:00Z"),
    )
    resolutions = (_resolution("r1", Resolution.ACCEPTED),)
    assert okf.pending_verifications(
        _config(), root, records=records, resolutions=resolutions
    ) == ("widget",)
    files, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:juan", "at": "2026-08-02T00:00:00Z"}
    ]


# --- review round 5: two ids on one path; the newest record; the witnesses ----


@pytest.mark.parametrize(
    "second_path",
    ["docs/widget.md", "docs/./sub/../widget.md"],
    ids=["same-path", "same-path-once-normalised"],
)
@pytest.mark.parametrize("on_disk", [True, False], ids=["file-present", "file-missing"])
def test_two_doc_ids_on_one_bundle_path_are_a_loud_error(
    tmp_path: Path, second_path: str, on_disk: bool
) -> None:
    """Review r5 (major): `MonitorConfig` accepts two doc ids over ONE path.
    The bundle writes one file per path, so the later concept silently
    replaced the earlier one: a current REJECT on `widget` vanished while
    `twin`'s ACCEPT was published for the same bytes, and the root index
    listed the file twice. The render now refuses loudly (K8), naming both
    ids and the bundle path, whether or not the file exists (the guard runs
    before the existence check) and after the path is normalised (the
    bundle path IS the normalised one). `export_okf` writes nothing and
    `check_okf` and `pending_verifications` refuse too."""
    # Feature: FEAT-OKF-001
    config = MonitorConfig(
        documents=(
            DocumentSpec(
                id="widget", path="docs/widget.md", audience=Audience.USER_GUIDE
            ),
            DocumentSpec(id="twin", path=second_path, audience=Audience.USER_GUIDE),
        )
    )
    root = _repo(tmp_path)
    if not on_disk:
        (root / "docs" / "widget.md").unlink()
    records = (_record("r-widget"), _record("r-twin", doc_id="twin"))
    resolutions = (
        _resolution("r-widget", Resolution.REJECTED, by="bob"),
        _resolution("r-twin", Resolution.ACCEPTED, by="alice"),
    )
    out_dir = tmp_path / "bundle"
    calls = {
        "render": lambda: render_bundle(
            config,
            root,
            generated_by="t",
            records=records,
            resolutions=resolutions,
            drift_report=_CLEAN,
        ),
        "export": lambda: export_okf(
            config,
            root,
            out_dir=out_dir,
            generated_by="t",
            records=records,
            resolutions=resolutions,
            drift_report=_CLEAN,
        ),
        "check": lambda: check_okf(
            config,
            root,
            out_dir=out_dir,
            generated_by="t",
            records=records,
            resolutions=resolutions,
            drift_report=_CLEAN,
        ),
        "pending": lambda: okf.pending_verifications(
            config, root, records=records, resolutions=resolutions
        ),
    }
    for name, call in calls.items():
        with pytest.raises(ConfigError) as caught:
            call()
        message = str(caught.value)
        assert "'widget'" in message and "'twin'" in message, name
        assert "'docs/widget.md'" in message, name
    assert not out_dir.exists()  # refused before a single byte is written


def test_the_newest_record_is_chosen_by_instant_not_by_string(tmp_path: Path) -> None:
    """Review r5 gap F05b: the doc's NEWEST record is picked by parsed instant.
    `r1`'s stamp `2026-08-02T00:30:00+01:00` (23:30Z) is the STRING max, but
    `r2` at 23:45Z is the INSTANT max. juan accepted `r1` at 23:40Z — before
    `r2` — so his review is superseded: no `verified`, nothing pending. A
    newest-by-string join reads 23:30Z as newest and publishes his claim.
    Every custodex writer stamps UTC, but the log accepts any offset form."""
    # Feature: FEAT-OKF-001
    records = (
        _record("r1", detected_at="2026-08-02T00:30:00+01:00"),
        _record("r2", detected_at="2026-08-01T23:45:00Z"),
    )
    assert max(r.detected_at for r in records) == records[0].detected_at
    resolutions = (_resolution("r1", Resolution.ACCEPTED, at="2026-08-01T23:40:00Z"),)
    root = _repo(tmp_path)
    files, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)
    assert (
        okf.pending_verifications(
            _config(), root, records=records, resolutions=resolutions
        )
        == ()
    )


def test_invalidating_a_later_record_does_not_lift_its_supersession(
    tmp_path: Path,
) -> None:
    """Mutation r5 gap V07: a later record supersedes whatever its RESOLUTION
    turns out to be. When bob invalidates the later record ("a non-event"),
    his review is current but neutral, and juan's older accept stays
    superseded, so nothing verifies and nothing is pending. Only an
    ATTESTING review at or after the newest record yields a claim; the older
    review never revives. Letting an invalidated record stop superseding
    revives juan's claim over something he never saw."""
    # Feature: FEAT-OKF-001
    root = _repo(tmp_path)
    records = (
        _record("r1"),
        _record("r-later", detected_at="2026-08-03T00:00:00Z"),
    )
    resolutions = (
        _resolution("r1", Resolution.ACCEPTED),
        _resolution(
            "r-later", Resolution.INVALIDATED, by="bob", at="2026-08-04T00:00:00Z"
        ),
    )
    files, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)
    assert (
        okf.pending_verifications(
            _config(), root, records=records, resolutions=resolutions
        )
        == ()
    )


_BODY = _DOC.split("---\n", 2)[2]


def test_trailing_spaces_inside_an_override_are_content(tmp_path: Path) -> None:
    """Mutation r5 gap V01: "byte-for-byte" covers whitespace INSIDE the text.
    Trailing spaces on an interior line (the doc's line has none) mean the
    human's exact text is not on disk. A per-line rstrip on both sides would
    read it as landed, so the override would verify when it should dispute."""
    # Feature: FEAT-OKF-001
    text = "# The Widget Guide  \n\n> Everything a widget owner needs."
    assert text not in _BODY
    assert text.replace("  \n", "\n") in _BODY  # the premise a lax check sees
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.OVERRIDDEN, text=text),),
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)


def test_an_override_inside_a_line_has_landed(tmp_path: Path) -> None:
    """Mutation r5 gap V03: containment means a contiguous SUBSTRING, not
    whole lines. An override the author wrote in the middle of an existing
    line has landed and attests (every other positive override test uses a
    whole line, so a stricter line-aligned check would pass them all)."""
    # Feature: FEAT-OKF-001
    text = "[the other guide](other.md)"
    assert text in _BODY and f"\n{text}\n" not in f"\n{_BODY}\n"
    files, _ = render_bundle(
        _config(),
        _repo(tmp_path),
        generated_by="t",
        records=(_record("r1"),),
        resolutions=(_resolution("r1", Resolution.OVERRIDDEN, text=text),),
        drift_report=_CLEAN,
    )
    assert _front(files)["verified"] == [
        {"by": "human:juan", "at": "2026-08-02T00:00:00Z"}
    ]


def test_an_override_found_only_in_the_cdm_front_matter_has_not_landed(
    tmp_path: Path,
) -> None:
    """Mutation r5 gap V04: the text must be in the BODY, the bytes the bundle
    publishes. Text that matches only the stripped `cdm:` front matter is not
    in the doc as published, so the override still disputes and nothing is
    pending."""
    # Feature: FEAT-OKF-001
    text = "fingerprint: aabbccddeeff0011"
    assert text in _DOC and text not in _BODY
    root = _repo(tmp_path)
    records = (_record("r1"),)
    resolutions = (_resolution("r1", Resolution.OVERRIDDEN, text=text),)
    files, _ = render_bundle(
        _config(),
        root,
        generated_by="t",
        records=records,
        resolutions=resolutions,
        drift_report=_CLEAN,
    )
    assert "verified" not in _front(files)
    assert (
        okf.pending_verifications(
            _config(), root, records=records, resolutions=resolutions
        )
        == ()
    )


def test_pending_verifications_sort_by_codepoint(tmp_path: Path) -> None:
    """Mutation r5 gap V12: ids sort as `sorted()` sorts them (codepoint
    order, the order the bundle uses for its paths), so the result is the
    same for any ids. Doc ids are free strings, so mixed-case ids must not
    be reordered case-insensitively."""
    # Feature: FEAT-OKF-001
    layout = {"alpha": "docs/a.md", "Beta": "docs/b.md"}
    (tmp_path / "docs").mkdir()
    for path in layout.values():
        (tmp_path / path).write_text(_DOC, encoding="utf-8")
    config = MonitorConfig(
        documents=tuple(
            DocumentSpec(id=doc_id, path=path, audience=Audience.USER_GUIDE)
            for doc_id, path in layout.items()
        )
    )
    assert okf.pending_verifications(
        config,
        tmp_path,
        records=tuple(_record(f"r-{d}", doc_id=d) for d in layout),
        resolutions=tuple(_resolution(f"r-{d}", Resolution.ACCEPTED) for d in layout),
    ) == ("Beta", "alpha")
