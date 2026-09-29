"""Regression corpus — a same-name anchor collision never closes unattended.

Review finding ``jarvis-contribution-key-identity`` (slice 1a). ``anchor_id``
hashes the qualified name only, so two documented symbols can share one anchor
(``main`` in two code_refs, an ``@overload`` stack, a property getter/setter).
The per-symbol ``cdm.symbol_sigs`` map keeps only the LAST writer per anchor and
the anchor delta used to be a SET, so an in-place break of a shadowed symbol —
or deleting it — plus any addition in the same edit graded ADDITIVE, routed
CODE_DERIVED, and ``monitor --apply --tiered`` closed it with NO review, leaving
prose such as "Call ``main(x)`` with one int" false.

These cases drive the real :class:`~custodex.monitor.Monitor` in tiered mode
(ship shape: real heal stamps, real extraction, the offline default backend).

See ``tests/regression/README.md`` for the case -> lesson map.

Features: FEAT-DRIFT-006, FEAT-DRIFT-012, FEAT-MONITOR-001
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.config import Audience, CodeRef, DocumentSpec, MonitorConfig
from custodex.drift import ChangeSeverity, DriftKind
from custodex.extract import build_document_surface
from custodex.heal import regenerate_regions
from custodex.manifest import parse_doc, stored_symbol_sigs
from custodex.monitor import Monitor
from custodex.sinks import NullSink

NOW = "2026-06-01T00:00:00+00:00"
A_V1 = "def main(x: int) -> int:\n    return x\n"
# b.main is BELOW a.main by line number: it is the last writer of the shared
# `symbol_sigs` entry, so a.main is the shadowed collider.
B_V1 = "# pad\n# pad\n# pad\ndef main(y: str, z: str) -> str:\n    return y + z\n"
EXTRA = "\n\ndef extra() -> None:\n    pass\n"
PROSE = "Call `main(x)` with one int."


def _repo(tmp_path: Path, *, pre_dig01: bool = False) -> tuple[Path, Monitor]:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "a.py").write_text(A_V1, encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text(B_V1, encoding="utf-8")
    spec = DocumentSpec(
        id="api",
        path="docs/api.md",
        audience=Audience.USER_GUIDE,
        code_refs=(CodeRef(path="src/a.py"), CodeRef(path="src/b.py")),
        region_keys=("symbols",),
    )
    doc = tmp_path / spec.path
    doc.write_text(
        f"# API\n\n{PROSE}\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    regenerate_regions(doc, build_document_surface(spec, tmp_path))
    if pre_dig01:
        # DIG-01 rolled out lazily: an adopter doc keeps its anchors and tier
        # digests but has no `symbol_sigs` block until its next heal.
        text = doc.read_text(encoding="utf-8")
        start = text.index("  symbol_sigs:")
        doc.write_text(
            text[:start] + text[text.index("---\n", start) :], encoding="utf-8"
        )
        assert stored_symbol_sigs(parse_doc(doc)) is None
    mon = Monitor(
        MonitorConfig(root=".", documents=(spec,)),
        tmp_path,
        sink=NullSink(),
        now=lambda: NOW,
        log_path=tmp_path / "log.jsonl",
    )
    assert mon.check().ok, "fixture must start healed"
    return doc, mon


_SHADOWED_BREAK = "def main(x: int, strict: bool) -> int:\n    return x\n" + EXTRA
_GROWN_ONLY_BREAK = (
    "def main(w: float) -> float:\n    return w\n"
    "def main(x: int, strict: bool) -> int:\n    return x\n"
)
_UNPROVEN = (
    "(unproven: the additions alone do not reproduce the stored signature "
    "tier; 1 same-name anchor(s) could hide a change)"
)


@pytest.mark.parametrize(
    ("a_edit", "evidence", "pre_dig01"),
    [
        # rc_mask: the shadowed a.main gains a required parameter + extra().
        # Held by rule 2b; the record says the PROOF failed, never a culprit.
        pytest.param(_SHADOWED_BREAK, _UNPROVEN, False, id="shadowed-signature-change"),
        # rc_rm: the shadowed a.main is DELETED + extra() added. Held by rule 1:
        # the multiset delta counts the removal itself.
        pytest.param(
            EXTRA.lstrip("\n"),
            "(anchored symbols changed: +1/-1)",
            False,
            id="shadowed-deletion",
        ),
        # rc_mask on a doc stamped WITHOUT `symbol_sigs` (pre-DIG-01): nothing
        # can attribute an in-place change there, so the guard is the only
        # thing standing between this break and an unattended close.
        pytest.param(
            _SHADOWED_BREAK,
            _UNPROVEN,
            True,
            id="shadowed-signature-change-pre-dig01",
        ),
        # A GROWN-ONLY addition: a second `main` above the shadowed a.main,
        # which also gains a required parameter; no wholly-new name is added.
        # b.main stays the last writer, so only the collision proof holds it.
        pytest.param(
            _GROWN_ONLY_BREAK,
            _UNPROVEN,
            False,
            id="grown-only-shadowed-break",
        ),
    ],
)
def test_tiered_never_closes_a_break_hidden_under_a_collided_anchor(
    tmp_path: Path, a_edit: str, evidence: str, pre_dig01: bool
) -> None:
    """[jarvis-contribution-key-identity] A collision cannot launder a break.

    Before the fix all three edits read ``HASH [additive]`` with ``routing: 1/1
    document(s) mechanical``, and ``monitor --apply --tiered`` printed ``closed
    mechanically (no backend)`` — the review record carried ``resolved_by=engine``
    and the doc still promised ``main(x)`` with one int. Now the document is held:
    nothing is written, no closure is claimed, the human is told (K5), and the
    next cycle still asks.

    BREAK-IT (confirmed bites; not committed): turning the multiset anchor delta
    in ``drift.detect`` back into a SET makes the deletion case ADDITIVE again,
    and dropping the ambiguous-anchor rule from ``classify_change_severity`` makes
    the signature-change case ADDITIVE again — either way ``closures`` is
    non-empty and the doc is rewritten, so this reds. Gating the collision guard
    on the doc carrying ``symbol_sigs`` makes the pre-DIG-01 row ADDITIVE again,
    and consulting it only when a wholly-new name was added makes the
    grown-only row ADDITIVE again.
    """
    # Feature: FEAT-DRIFT-012
    doc, mon = _repo(tmp_path, pre_dig01=pre_dig01)
    (tmp_path / "src" / "a.py").write_text(a_edit, encoding="utf-8")
    before = doc.read_bytes()

    (hash_drift,) = [d for d in mon.check().drifts if d.kind is DriftKind.HASH]
    assert hash_drift.change_severity is ChangeSeverity.BREAKING

    result = mon.run(apply=True, tiered=True)

    assert result.closures == ()  # the engine claimed nothing
    assert doc.read_bytes() == before  # nothing on the held doc was written
    assert result.records  # but the human WAS told (K5)
    assert all(r.config_snapshot.get("resolved_by") != "engine" for r in result.records)
    hash_records = [r for r in result.records if r.drift_kind == "HASH"]
    assert {r.change_severity for r in hash_records} == {"breaking"}
    # The reviewer reads WHY it was held from the record's drift_detail (K5).
    assert hash_records and all(evidence in r.drift_detail for r in hash_records)
    assert not mon.check().ok  # the escalation survives into the next cycle


def test_tiered_still_closes_a_pure_addition_beside_a_collision(
    tmp_path: Path,
) -> None:
    """[jarvis-contribution-key-identity] The guard must not over-fire (control).

    ``extra`` is appended below every existing symbol and nothing under ``main``
    moved, so the refresh is a pure projection of the surface: tiered mode closes
    it with no backend, exactly as for a collision-free doc — and a second run is
    a no-op (K7: nothing left to close, nothing rewritten).
    """
    # Feature: FEAT-DRIFT-012
    doc, mon = _repo(tmp_path)
    (tmp_path / "src" / "b.py").write_text(B_V1 + EXTRA, encoding="utf-8")

    result = mon.run(apply=True, tiered=True)

    assert [c.doc_id for c in result.closures] == ["api"]
    assert mon.check().ok
    assert PROSE in doc.read_text(encoding="utf-8")
    settled = doc.read_bytes()
    again = mon.run(apply=True, tiered=True)
    assert again.closures == () and again.records == ()
    assert doc.read_bytes() == settled


def test_tiered_still_closes_after_a_same_name_deletion_left_the_stamp_over_counting(
    tmp_path: Path,
) -> None:
    """[jarvis-contribution-key-identity] A stale stamp is no permanent phantom.

    A human replaced the declared ``symbols`` region with prose; b.main is then
    deleted and the default backend resolves that removal (heal re-stamps the
    tiers and ``symbol_sigs`` but, with no region in the body, not the
    anchors). The stamp still counts two `main`s. With a multiset delta that
    count-only decrease read as a removal on EVERY later drift: a pure addition
    was held BREAKING with a false "-1", on every cycle. The stored signature
    tier proves the stamp stale (it re-derives with the addition set aside),
    so tiered mode closes the addition mechanically again, as the pre-fix
    engine did, and a second run is a no-op (K7).

    BREAK-IT (confirmed bites; not committed): dropping the stale-stamp
    discharge from ``drift.detect`` holds the addition with "+1/-1" and
    ``closures == ()``, so this reds.
    """
    # Feature: FEAT-DRIFT-006
    doc, mon = _repo(tmp_path)
    text = doc.read_text(encoding="utf-8")
    start = text.index("<!-- CDM:BEGIN symbols -->")
    end = text.index("<!-- CDM:END symbols -->") + len("<!-- CDM:END symbols -->")
    doc.write_text(text[:start] + "See the wiki.\n" + text[end:], encoding="utf-8")
    assert mon.check().ok
    (tmp_path / "src" / "b.py").write_text("", encoding="utf-8")
    removal = mon.run(apply=True)  # a REAL removal, resolved by the backend
    assert [r.change_severity for r in removal.records] == ["breaking"]
    assert mon.check().ok

    (tmp_path / "src" / "b.py").write_text(EXTRA.lstrip("\n"), encoding="utf-8")
    result = mon.run(apply=True, tiered=True)

    assert [c.doc_id for c in result.closures] == ["api"]
    hash_records = [r for r in result.records if r.drift_kind == "HASH"]
    assert [r.change_severity for r in hash_records] == ["additive"]
    assert all("-1)" not in r.drift_detail for r in hash_records)
    assert mon.check().ok
    settled = doc.read_bytes()
    again = mon.run(apply=True, tiered=True)
    assert again.closures == () and again.records == ()
    assert doc.read_bytes() == settled
