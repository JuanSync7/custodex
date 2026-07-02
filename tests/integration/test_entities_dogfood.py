"""AGT-01 goal 7 — the dogfood PRECISION budget for the mention layer.

Runs `corpus_entities` over THIS repo's real managed corpus (config/cdmon)
and pins the precision contract the 2026-07-02 design review demanded: the
day-one unresolved output is EMPTY (the graph-rot signal starts clean, so a
real rot event is visible), and no mention — resolved or not — matches a
forbidden noise shape (routes, globs, colon markers, plain words).

If this test fails after a prose edit, the rot signal has NEW content: either
fix the prose reference, extend `entities.ignore` in config/cdmon/index.yaml
(with a justification comment), or accept the new unresolved mention as real
signal by pinning it here — the same triage the wiki freshness gate forces.

Features: FEAT-ENTITIES-001, FEAT-ENTITIES-003
"""

from __future__ import annotations

import re

from custodex.config import load_bundle
from custodex.entities import corpus_entities
from tests._repo import REPO_ROOT


def _results():
    bundle = load_bundle(REPO_ROOT / "config" / "cdmon")
    return corpus_entities(bundle.config, REPO_ROOT)


def test_dogfood_unresolved_set_is_empty() -> None:
    """Day one, the rot signal is CLEAN: zero unresolved mentions repo-wide."""
    unresolved = [
        (r.doc_id, m.line, m.text)
        for r in _results()
        for m in r.mentions
        if not m.resolved
    ]
    assert unresolved == []


def test_dogfood_mentions_contain_no_noise_shapes() -> None:
    """No mention text is a route/glob/colon-marker/whitespace fragment."""
    for r in _results():
        for m in r.mentions:
            assert not re.search(r"\s", m.text), (r.doc_id, m.text)
            assert not any(c in m.text for c in "{}*?["), (r.doc_id, m.text)
            if m.kind.value != "url":
                assert ":" not in m.text, (r.doc_id, m.text)


def test_dogfood_known_resolutions_hold() -> None:
    """Spot-check: real prose mentions resolve to the right entities."""
    by_doc = {r.doc_id: r for r in _results()}
    readme = by_doc["readme"]
    resolved = {m.text: m.entity_id for m in readme.mentions if m.resolved}
    assert resolved.get("BackendResult") == "symbol custodex/backends.py#BackendResult"
    assert resolved.get("config/cdmon/") == "path config/cdmon"
    # The measured misresolution traps stay blocked: `app`/`coverage`/`index`
    # (module-stem collisions) must not appear as resolved SYMBOL mentions.
    for r in _results():
        for m in r.mentions:
            if m.kind.value == "symbol" and m.resolved:
                assert m.text not in {"app", "coverage", "index"}, (
                    r.doc_id,
                    m.line,
                    m.entity_id,
                )
