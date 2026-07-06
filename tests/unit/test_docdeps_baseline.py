"""AGT-02 — the ``docdeps.baseline`` knob: body (default) vs prose.

Under ``prose``, the upstream fingerprint hashes the CDM-region-STRIPPED body
so a machine reheal of a code-tracked upstream is hash-invisible and only a
human PROSE change trips the dependents — the semantic fix for the recorded
DOCDEPS-01 heal-path churn. ``body`` stays byte-identical to today (K6).

Features: FEAT-DOCMAP-002
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import (
    Audience,
    DocDepsConfig,
    DocEdge,
    DocumentSpec,
    MonitorConfig,
    load_config,
)
from custodex.docdeps import (
    SuspectStatus,
    detect_suspect_links,
    stamp_edges,
    upstream_fingerprint,
)
from custodex.manifest import parse_text

_UP_BODY = (
    "# Upstream\n"
    "\n"
    "Human prose here.\n"
    "\n"
    "<!-- CDM:BEGIN symbols -->\n"
    "| old | table |\n"
    "<!-- CDM:END symbols -->\n"
)


def test_prose_fingerprint_ignores_region_rewrites() -> None:
    doc_a = parse_text(_UP_BODY)
    doc_b = parse_text(_UP_BODY.replace("| old | table |", "| new | table |"))
    assert upstream_fingerprint(doc_a) != upstream_fingerprint(doc_b)  # body sees it
    assert upstream_fingerprint(doc_a, baseline="prose") == upstream_fingerprint(
        doc_b, baseline="prose"
    )


def test_prose_fingerprint_sees_prose_edits() -> None:
    doc_a = parse_text(_UP_BODY)
    doc_b = parse_text(_UP_BODY.replace("Human prose here.", "Edited prose here."))
    assert upstream_fingerprint(doc_a, baseline="prose") != upstream_fingerprint(
        doc_b, baseline="prose"
    )


def test_body_default_is_byte_identical_to_pre_agt() -> None:
    """K6 guard: the default path never changes stored-stamp semantics."""
    doc = parse_text(_UP_BODY)
    assert upstream_fingerprint(doc) == upstream_fingerprint(doc, baseline="body")


def test_baseline_knob_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "cdmon.yaml"
    p.write_text(
        'version: "1.0.0"\nroot: .\n'
        "docdeps:\n  baseline: prose\n"
        "documents:\n  - id: a\n    path: a.md\n    audience: eng-guide\n",
        encoding="utf-8",
    )
    assert load_config(p).docdeps.baseline == "prose"
    assert DocDepsConfig().baseline == "body"


def _two_doc_config(baseline: str) -> MonitorConfig:
    return MonitorConfig(
        documents=(
            DocumentSpec(id="up", path="up.md", audience=Audience.ENG_GUIDE),
            DocumentSpec(
                id="down",
                path="down.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="up"),),
            ),
        ),
        docdeps=DocDepsConfig(baseline=baseline),  # type: ignore[arg-type]
    )


def test_detection_and_stamping_share_the_prose_baseline(tmp_path: Path) -> None:
    """One shared truth: a reheal-style region rewrite trips `body` but not
    `prose`, and the stamp written under `prose` matches detection's view."""
    (tmp_path / "up.md").write_text(_UP_BODY, encoding="utf-8")
    (tmp_path / "down.md").write_text("# Down\n", encoding="utf-8")

    for baseline, expected_after_rewrite in (
        ("prose", ()),  # region rewrite is invisible: edge stays OK
        ("body", (SuspectStatus.SUSPECT,)),  # today's behaviour
    ):
        cfg = _two_doc_config(baseline)
        (tmp_path / "up.md").write_text(_UP_BODY, encoding="utf-8")
        stamp_edges(cfg, tmp_path, "down")
        assert detect_suspect_links(cfg, tmp_path) == ()
        (tmp_path / "up.md").write_text(
            _UP_BODY.replace("| old | table |", "| new | table |"),
            encoding="utf-8",
        )
        statuses = tuple(link.status for link in detect_suspect_links(cfg, tmp_path))
        assert statuses == expected_after_rewrite, baseline


def test_prose_baseline_still_trips_on_prose_edit(tmp_path: Path) -> None:
    (tmp_path / "up.md").write_text(_UP_BODY, encoding="utf-8")
    (tmp_path / "down.md").write_text("# Down\n", encoding="utf-8")
    cfg = _two_doc_config("prose")
    stamp_edges(cfg, tmp_path, "down")
    (tmp_path / "up.md").write_text(
        _UP_BODY.replace("Human prose here.", "Edited."), encoding="utf-8"
    )
    (link,) = detect_suspect_links(cfg, tmp_path)
    assert link.status is SuspectStatus.SUSPECT
