"""Coexistence with an adopter's own front-matter convention (KEEL-01).

Many adopter repos already carry a house front-matter block (``title:``,
``kind:``, ``owner:``, ``tags:``, …) and grant Custodex only the ``cdm:`` key
beneath it — project-keel's ``CONVENTIONS.md §9`` is the worked case recorded
in ``.project/problems/KEEL-01-deployment-integration.md``. Its adoption steps
rely on three engine behaviours, and these tests pin each one:

- such a document lints as *missing the managed keys* (``MISSING_SCHEMA_VERSION``,
  ``MISSING_AUDIENCE``, ``MISSING_FINGERPRINT``), never as ``MISSING_FRONT_MATTER``;
- ``cdx lint --fix`` stamps ``cdm.schema_version`` and ``cdm.audience`` and keeps
  every foreign key and its parsed YAML value, so only the fingerprint and the
  purpose line are left for ``cdx monitor --apply`` and a human;
- a second ``cdx lint --fix`` with nothing changed writes nothing (K7).

FM-SPLICE adds the byte-level contract that KEEL-01 F9 asked for: every engine
write (``lint --fix``, an engine heal, ``cdx link``'s edge stamp, a SharePoint
mirror re-sync) rewrites only the ``cdm:`` entry and keeps every other
front-matter line byte-identical, for a block mapping at column 0 with no
duplicate, ``<<`` or aliased top-level key and no alias into the ``cdm:`` entry
(any other layout is re-dumped data-exact; see ``manifest.render_doc``). A
consumer that compares the text (a line-based reader, a template-twin line
check) is therefore unaffected.

Features: FEAT-LAYOUT-001, FEAT-LAYOUT-004, FEAT-LAYOUT-010
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from custodex.cli import app
from custodex.config import (
    Audience,
    DocDepsConfig,
    DocEdge,
    DocumentSpec,
    MonitorConfig,
)
from custodex.docdeps import stamp_edges
from custodex.layout import LAYOUT_VERSION, LayoutCode, lint_doc, stamp_doc_meta
from custodex.manifest import parse_doc, parse_text
from custodex.spmirror import _write_body_preserving_meta

runner = CliRunner()

# A house-style block with no ``cdm:`` key: a flow list, a boolean, a date-like
# string and a non-ASCII summary, so a stamp that drops or rewrites a foreign
# value cannot pass by accident. Title and purpose are present, so the only
# issues left are the managed-key ones.
_FOREIGN_META = {
    "title": "Project Handbook",
    "kind": "readme",
    "owner": "TBD",
    "tags": ["template", "scaffold"],
    "summary": "A house-style summary — with an em dash.",
    "updated": "2026-09-02",
    "canonical": True,
}
_FOREIGN_DOC = (
    "---\n"
    "title: Project Handbook\n"
    "kind: readme\n"
    "owner: TBD\n"
    "tags: [template, scaffold]\n"
    "summary: A house-style summary — with an em dash.\n"
    'updated: "2026-09-02"\n'
    "canonical: true\n"
    "---\n"
    "# Project Handbook\n"
    "\n"
    "> What this handbook is for.\n"
)
_MANAGED_KEY_CODES = {
    LayoutCode.MISSING_SCHEMA_VERSION,
    LayoutCode.MISSING_AUDIENCE,
    LayoutCode.MISSING_FINGERPRINT,
}


def _spec() -> DocumentSpec:
    return DocumentSpec(id="handbook", path="README.md", audience=Audience.ENG_GUIDE)


def test_foreign_only_front_matter_lints_as_missing_managed_keys() -> None:
    """A doc whose front matter has only foreign keys is missing the managed keys.

    It must never be reported as ``MISSING_FRONT_MATTER``: the block exists and
    belongs to the adopter.
    """
    doc = parse_text(_FOREIGN_DOC)
    assert doc.meta == _FOREIGN_META  # fixture sanity: the block parses as written

    codes = {issue.code for issue in lint_doc(doc, _spec())}

    assert LayoutCode.MISSING_FRONT_MATTER not in codes
    assert codes == _MANAGED_KEY_CODES  # Feature: FEAT-LAYOUT-001


def test_stamp_adds_only_cdm_and_keeps_every_foreign_key() -> None:
    """``lint --fix``'s stamp writes under ``cdm:`` and leaves foreign keys alone.

    Every foreign key keeps its value. The one new top-level key is ``cdm``, and
    it holds exactly the two static keys. Afterwards only the fingerprint is left
    for ``cdx monitor --apply``.
    """
    stamped = parse_text(stamp_doc_meta(parse_text(_FOREIGN_DOC), _spec()))

    foreign = {k: v for k, v in stamped.meta.items() if k != "cdm"}
    assert foreign == _FOREIGN_META
    assert stamped.meta["cdm"] == {
        "schema_version": LAYOUT_VERSION,
        "audience": Audience.ENG_GUIDE.value,
    }
    assert stamped.body == parse_text(_FOREIGN_DOC).body
    remaining = {issue.code for issue in lint_doc(stamped, _spec())}
    assert remaining == {LayoutCode.MISSING_FINGERPRINT}  # Feature: FEAT-LAYOUT-004


def test_lint_fix_on_foreign_front_matter_is_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    """A second ``cdx lint --fix`` with nothing changed writes nothing (K7).

    The first run stamps the foreign-front-matter doc and reports it. The second
    run must not report a fix again or change a byte of the file.
    """
    (tmp_path / "cdmon.yaml").write_text(
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        "  - id: handbook\n"
        "    path: README.md\n"
        "    audience: eng-guide\n",
        encoding="utf-8",
    )
    doc_path = tmp_path / "README.md"
    doc_path.write_text(_FOREIGN_DOC, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(app, ["lint", "--fix"])
    assert "fixed front matter: README.md" in first.output
    after_first = doc_path.read_bytes()
    assert after_first != _FOREIGN_DOC.encode("utf-8")

    second = runner.invoke(app, ["lint", "--fix"])
    assert "fixed front matter" not in second.output
    assert doc_path.read_bytes() == after_first  # Feature: FEAT-LAYOUT-004
    # Only the fingerprint is left, and only `monitor --apply` sets it.
    assert second.exit_code == 1
    assert "MISSING_FINGERPRINT" in second.output
    assert "MISSING_SCHEMA_VERSION" not in second.output
    assert "MISSING_AUDIENCE" not in second.output


# --- FM-SPLICE: the bytes, not just the values ------------------------------

# A house block with everything a re-dump would disturb: a head comment, an
# inline comment, a flow list, a folded scalar, blank and comment lines, an
# unquoted OpenWiki-style timestamp (F9's ``verified.at`` symptom), a ``yes``
# boolean and non-ASCII text.
_HOUSE_FM = (
    "# house front matter (CONVENTIONS §9)\n"
    "title: Project Handbook\n"
    "kind: readme\n"
    "owner: TBD  # assigned at review\n"
    "tags: [template, scaffold]\n"
    "summary: >-\n"
    "  A house-style summary — with\n"
    "  an em dash.\n"
    "\n"
    "updated: '2026-09-02'\n"
    "verified:\n"
    "  at: 2026-09-25T08:09:49.344Z\n"
    "  by: openwiki\n"
    "canonical: yes\n"
)
_HOUSE_BODY = "# Project Handbook\n\n> What this handbook is for.\n"
_HOUSE_DOC = f"---\n{_HOUSE_FM}---\n{_HOUSE_BODY}"


def test_stamp_keeps_every_foreign_line_byte_identical() -> None:
    """``lint --fix`` appends a sorted ``cdm:`` block and touches nothing else."""
    stamped = stamp_doc_meta(parse_text(_HOUSE_DOC), _spec())
    assert stamped == (
        f"---\n{_HOUSE_FM}"
        "cdm:\n"
        "  audience: eng-guide\n"
        f"  schema_version: {LAYOUT_VERSION}\n"
        f"---\n{_HOUSE_BODY}"
    )  # Feature: FEAT-LAYOUT-010


def test_second_stamp_is_a_noop() -> None:
    """A stamped doc stamps to itself (K7), even when its ``cdm`` was hand-written."""
    once = stamp_doc_meta(parse_text(_HOUSE_DOC), _spec())
    assert stamp_doc_meta(parse_text(once), _spec()) == once
    by_hand = (
        f"---\ntitle: T\ncdm: {{schema_version: {LAYOUT_VERSION}, "
        "audience: eng-guide}  # by hand\n---\n# T\n"
    )
    assert stamp_doc_meta(parse_text(by_hand), _spec()) == by_hand


_CODE = '''"""A tiny module."""


def public_fn(x: int) -> int:
    """Double x."""
    return x * 2
'''


def _guide_repo(tmp_path: Path) -> Path:
    (tmp_path / "code.py").write_text(_CODE, encoding="utf-8")
    (tmp_path / "cdmon.yaml").write_text(
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        "  - id: guide\n"
        "    path: guide.md\n"
        "    audience: eng-guide\n"
        "    code_refs:\n"
        "      - path: code.py\n"
        "    region_keys: [symbols]\n"
        "backend:\n"
        "  kind: mock\n",
        encoding="utf-8",
    )
    doc = tmp_path / "guide.md"
    doc.write_text(
        f"---\n{_HOUSE_FM}cdm:\n  fingerprint: stale\n# kept after cdm\n---\n"
        "# Guide\n\n> Purpose.\n\n"
        "<!-- CDM:BEGIN symbols -->\nOUT OF DATE\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    return doc


def _without_cdm(front_matter: str) -> str:
    out: list[str] = []
    skipping = False
    for line in front_matter.splitlines(keepends=True):
        if line.startswith("cdm:"):
            skipping = True
            continue
        if skipping and line.startswith("  "):
            continue
        skipping = False
        out.append(line)
    return "".join(out)


def test_refresh_rewrites_only_the_cdm_block(tmp_path: Path, monkeypatch) -> None:
    """An engine heal (``monitor --apply``, mock backend) rewrites only ``cdm:``.

    The region and the fingerprint are refreshed; every other front-matter line
    keeps its bytes and place. A second apply writes nothing (K7).
    """
    doc_path = _guide_repo(tmp_path)
    before = doc_path.read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(app, ["monitor", "--apply"])
    assert first.exit_code == 0, first.output
    after = doc_path.read_text(encoding="utf-8")
    assert after != before
    assert "OUT OF DATE" not in after
    fm_before = before.split("---\n")[1]
    fm_after = after.split("---\n")[1]
    assert fm_after.startswith(f"{_HOUSE_FM}cdm:\n  fingerprint: ")
    assert fm_after.endswith("# kept after cdm\n")
    assert _without_cdm(fm_after) == _without_cdm(fm_before)
    assert parse_text(after).meta["cdm"]["fingerprint"] != "stale"

    second = runner.invoke(app, ["monitor", "--apply"])
    assert second.exit_code == 0, second.output
    assert doc_path.read_text(encoding="utf-8") == after  # Feature: FEAT-LAYOUT-010


def test_stamp_edges_rewrites_only_the_cdm_block(tmp_path: Path) -> None:
    """``cdx link`` / ``resolve --edge`` stamp the edge under ``cdm:`` only."""
    overview = DocumentSpec(
        id="overview", path="overview.md", audience=Audience.ENG_GUIDE
    )
    api = DocumentSpec(
        id="api",
        path="api.md",
        audience=Audience.ENG_GUIDE,
        depends_on=(DocEdge(doc="overview"),),
    )
    cfg = MonitorConfig(root=".", documents=(overview, api), docdeps=DocDepsConfig())
    (tmp_path / "overview.md").write_text("# Overview\nupstream\n", encoding="utf-8")
    api_path = tmp_path / "api.md"
    api_path.write_text(_HOUSE_DOC, encoding="utf-8")

    assert stamp_edges(cfg, tmp_path, "api") == ("overview",)
    text = api_path.read_text(encoding="utf-8")
    assert text.startswith(f"---\n{_HOUSE_FM}cdm:\n  upstream_hashes:\n    overview: ")
    assert text.endswith(f"---\n{_HOUSE_BODY}")
    assert stamp_edges(cfg, tmp_path, "api") == ()  # K7


def test_a_mirror_resync_keeps_a_house_front_matter_block(tmp_path: Path) -> None:
    """A SharePoint re-sync replaces the body and leaves the front matter alone."""
    target = tmp_path / "mirror.md"
    stamped = stamp_doc_meta(parse_text(_HOUSE_DOC), _spec())
    target.write_text(stamped, encoding="utf-8")
    assert _write_body_preserving_meta(target, "# New body\n") is True
    resynced = target.read_text(encoding="utf-8")
    assert resynced == stamped.replace(_HOUSE_BODY, "# New body\n")
    assert parse_doc(target).body == "# New body\n"
