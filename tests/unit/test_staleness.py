"""EPIC SLA (SLA-01/02) — pure time-based staleness / review SLA.

Config is the source of truth (a human stamps `reviewed`); staleness is graded against
an INJECTED `now` (no wall-clock, K10), audience changes the verdict (K3), malformed
dates are loud (K8). FRESH docs are omitted unless asked for.

Features: FEAT-STALENESS-001, FEAT-STALENESS-002, FEAT-STALENESS-003
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from code_doc_monitor.config import (
    Audience,
    DocumentSpec,
    MonitorConfig,
    StalenessConfig,
)
from code_doc_monitor.errors import ConfigError
from code_doc_monitor.staleness import (
    ReviewedDoc,
    StalenessStatus,
    detect_stale,
    resolve_sla_days,
    reviewed_docs_from_config,
)

_NOW = "2026-06-22T00:00:00+00:00"  # injected clock


def _doc(
    doc_id: str, *, reviewed: str | None, audience: str = "eng-guide"
) -> ReviewedDoc:
    return ReviewedDoc(
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        audience=Audience(audience),
        reviewed=reviewed,
    )


# ── the three statuses ───────────────────────────────────────────────────────


def test_detect_stale_grades_each_status() -> None:
    docs = [
        _doc("a-stale", reviewed="2026-01-01"),  # 172 days ago > 90
        _doc("b-fresh", reviewed="2026-06-20"),  # 2 days ago < 90
        _doc("c-never", reviewed=None),  # no stamp
    ]
    findings = detect_stale(docs, now=_NOW, default_days=90)
    # FRESH is omitted by default; findings are sorted by doc_id (K10)
    by_id = {f.doc_id: f for f in findings}
    assert set(by_id) == {"a-stale", "c-never"}
    assert by_id["a-stale"].status is StalenessStatus.STALE
    assert by_id["a-stale"].age_days == 172
    assert by_id["a-stale"].sla_days == 90
    assert by_id["c-never"].status is StalenessStatus.NEVER_REVIEWED
    assert by_id["c-never"].age_days is None
    assert [f.doc_id for f in findings] == ["a-stale", "c-never"]  # sorted


def test_include_fresh_shows_fresh_docs() -> None:
    docs = [_doc("fresh", reviewed="2026-06-20")]
    assert detect_stale(docs, now=_NOW, default_days=90) == ()  # omitted
    shown = detect_stale(docs, now=_NOW, default_days=90, include_fresh=True)
    assert len(shown) == 1 and shown[0].status is StalenessStatus.FRESH


# ── audience changes the verdict (K3) ────────────────────────────────────────


def test_audience_specific_sla_changes_the_verdict() -> None:
    # both reviewed 172 days ago; a user-guide gets a 365-day SLA, an eng-guide 90.
    docs = [
        _doc("guide", reviewed="2026-01-01", audience="user-guide"),
        _doc("api", reviewed="2026-01-01", audience="eng-guide"),
    ]
    findings = detect_stale(
        docs,
        now=_NOW,
        default_days=90,
        audience_days={Audience.USER_GUIDE: 365},
        include_fresh=True,
    )
    by_id = {f.doc_id: f for f in findings}
    assert by_id["guide"].status is StalenessStatus.FRESH  # 172 < 365
    assert by_id["guide"].sla_days == 365
    assert by_id["api"].status is StalenessStatus.STALE  # 172 > 90
    assert by_id["api"].sla_days == 90


def test_resolve_sla_days_override_else_default() -> None:
    assert resolve_sla_days(Audience.ENG_GUIDE, default_days=90) == 90
    assert (
        resolve_sla_days(
            Audience.USER_GUIDE,
            default_days=90,
            audience_days={Audience.USER_GUIDE: 30},
        )
        == 30
    )


# ── edge cases ───────────────────────────────────────────────────────────────


def test_future_review_date_is_fresh_age_zero() -> None:
    docs = [_doc("ahead", reviewed="2027-01-01")]  # in the future relative to now
    [finding] = detect_stale(docs, now=_NOW, default_days=90, include_fresh=True)
    assert finding.status is StalenessStatus.FRESH
    assert finding.age_days == 0  # negative clamped to 0


def test_bad_review_date_is_loud() -> None:
    docs = [_doc("bad", reviewed="not-a-date")]
    with pytest.raises(ConfigError, match="reviewed is not an ISO date"):
        detect_stale(docs, now=_NOW, default_days=90)


# ── config-as-truth adapter + the staleness config block ─────────────────────


def test_reviewed_docs_from_config_projects_documents() -> None:
    config = MonitorConfig(
        documents=(
            DocumentSpec(
                id="z", path="docs/z.md", audience="eng-guide", reviewed="2026-01-01"
            ),
            DocumentSpec(id="a", path="docs/a.md", audience="user-guide"),
        )
    )
    docs = reviewed_docs_from_config(config)
    assert [d.doc_id for d in docs] == ["a", "z"]  # sorted
    assert docs[0].reviewed is None
    assert docs[1].reviewed == "2026-01-01"


def test_document_reviewed_defaults_none_and_staleness_block_defaults() -> None:
    spec = DocumentSpec(id="d", path="docs/d.md", audience="eng-guide")
    assert spec.reviewed is None  # additive, back-compat (K6)
    assert MonitorConfig(documents=(spec,)).staleness.default_days == 90


def test_staleness_config_rejects_non_positive_days() -> None:
    with pytest.raises(ValidationError):
        StalenessConfig(default_days=0)
    with pytest.raises(ValidationError):
        StalenessConfig(audience_days={Audience.ENG_GUIDE: -1})
