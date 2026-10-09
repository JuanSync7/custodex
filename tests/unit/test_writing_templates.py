"""DOC-01 — the shipped writing templates stay internally consistent.

Only one ``tone/`` stem is ever selected, so the rules that hold regardless of
tone (claim discipline, denominators, no version literals, no autobiography) are
repeated in every tone stem. ``templates/writing/README.md`` promises those
copies are marked and edited together. These tests turn that promise into a
check: every tone stem carries one section marked ``(shared by every tone)``, it
is the last section, and it is byte-identical in every stem — so one copy can no
longer quietly gain rules the others lack. They also pin that README describes
the marker and the stems exactly as they exist on disk.

Features: FEAT-QUALITY-003
"""

from __future__ import annotations

import re
from pathlib import Path

from custodex.docstyle import STYLE_CATEGORIES

REPO_ROOT = Path(__file__).resolve().parents[2]
WRITING = REPO_ROOT / "templates" / "writing"
README = WRITING / "README.md"

# The documentation convention README.md describes; a stem marks its shared
# section with a level-2 heading ending in this suffix.
SHARED_SUFFIX = "(shared by every tone)"
_SHARED_HEADING_RE = re.compile(r"^## (?P<title>.+ \(shared by every tone\))$", re.M)

# Anchors for every shared rule, taken as the UNION of what the three tone stems
# carried before reconciliation. The second and the last seven existed only in
# precise.md; they are listed so a reconcile that takes the intersection instead
# fails here.
_SHARED_RULE_ANCHORS = (
    "State as fact only what the code surface establishes",
    "Never assert that something was executed, verified, deployed, reviewed or",
    "Give a completeness claim its denominator",
    "Say whether a thing is there, not which release put it there",
    "Write the current truth, not the document's autobiography",
    "Resolve a disagreement; never record one",
    "fully supported",
    "an opinion with digits",
    "a command someone copies",
    "Version control holds the timeline",
    "this section now",
    "restate the trap in the present tense",
    "a skimming reader takes the first value",
)


def _tone_stems() -> dict[str, str]:
    """Every shipped ``tone/<stem>.md`` body, keyed by stem (sorted, K10)."""
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted((WRITING / "tone").glob("*.md"))
    }


def _shared_section(stem: str, text: str) -> str:
    """The text from the stem's single shared heading to end of file."""
    headings = list(_SHARED_HEADING_RE.finditer(text))
    assert len(headings) == 1, (
        f"tone/{stem}.md must carry exactly one '## ... {SHARED_SUFFIX}' heading, "
        f"found {len(headings)}"
    )
    return text[headings[0].start() :]


def test_every_tone_stem_carries_the_same_shared_section() -> None:
    """Every tone stem ends with ONE shared section, byte-identical across stems.

    Pins the README's "edit them together" contract: a rule added to one copy
    and not the others fails here, naming the stems that disagree.
    """
    # Feature: FEAT-QUALITY-003
    stems = _tone_stems()
    assert len(stems) >= 2, "the shared-section contract needs at least two stems"
    sections = {stem: _shared_section(stem, text) for stem, text in stems.items()}
    reference_stem, reference = next(iter(sections.items()))
    differing = sorted(s for s, body in sections.items() if body != reference)
    assert not differing, (
        f"shared section differs from tone/{reference_stem}.md in: "
        + ", ".join(f"tone/{s}.md" for s in differing)
    )


def test_shared_section_carries_every_shared_rule() -> None:
    """The reconciled shared section is the union of the rules, in every stem.

    Before DOC-01's fix precise.md carried eight rule clauses that formal.md and
    friendly.md lacked; selecting ``tone: friendly`` silently dropped them. Each
    anchor must now appear in every stem's shared section.
    """
    # Feature: FEAT-QUALITY-003
    missing: dict[str, list[str]] = {}
    for stem, text in _tone_stems().items():
        # Whitespace-normalized so an anchor matches across a line wrap.
        section = " ".join(_shared_section(stem, text).split())
        absent = [anchor for anchor in _SHARED_RULE_ANCHORS if anchor not in section]
        if absent:
            missing[stem] = absent
    assert not missing, f"shared rules missing: {missing}"


def test_readme_names_the_shared_heading_the_stems_use() -> None:
    """README.md quotes the exact shared heading the tone stems carry.

    README tells an editor which section to keep identical; if the heading is
    renamed in the stems and not in README, the instruction points at nothing.
    """
    # Feature: FEAT-QUALITY-003
    titles = {
        m.group("title")
        for text in _tone_stems().values()
        for m in _SHARED_HEADING_RE.finditer(text)
    }
    assert len(titles) == 1, f"tone stems disagree on the shared heading: {titles}"
    readme = " ".join(README.read_text(encoding="utf-8").split())
    assert titles.pop() in readme


def _readme_stems(readme: str, category: str) -> set[str]:
    """Backticked stem names README lists for ``category``."""
    if category == "document-type":
        line = re.search(
            r"^`document-type` stems: (?P<rest>.+?)\n\n", readme, re.M | re.S
        )
        assert line is not None, "README lists no document-type stems"
        return set(re.findall(r"`([a-z0-9-]+)`", line.group("rest")))
    row = re.search(rf"^\| `{category}` \| (?P<cell>[^|]+) \|", readme, re.M)
    assert row is not None, f"README table has no `{category}` row"
    return set(re.findall(r"`([a-z0-9-]+)`", row.group("cell")))


def test_readme_lists_exactly_the_shipped_stems() -> None:
    """README's stem lists match the ``<category>/<stem>.md`` files on disk.

    A stem shipped without a README entry, or a README entry with no file, makes
    README an inaccurate map of what a ``doc-style.yaml`` can select. The
    categories come from the engine's ``STYLE_CATEGORIES``, so a category the
    composer gains is checked here too, rather than skipped.
    """
    # Feature: FEAT-QUALITY-003
    readme = README.read_text(encoding="utf-8")
    for _attr, category in STYLE_CATEGORIES:
        on_disk = {p.stem for p in (WRITING / category).glob("*.md")}
        assert _readme_stems(readme, category) == on_disk, category
