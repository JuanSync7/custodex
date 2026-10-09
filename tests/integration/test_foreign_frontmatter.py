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
  purpose line are left for ``cdx monitor --apply`` and a human. The front-matter
  TEXT is re-rendered, not preserved; KEEL-01 records what that costs a
  consumer that compares the text instead of parsing YAML (a line-based
  reader, a template-twin line check);
- a second ``cdx lint --fix`` with nothing changed writes nothing (K7).

Features: FEAT-LAYOUT-001, FEAT-LAYOUT-004
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from custodex.cli import app
from custodex.config import Audience, DocumentSpec
from custodex.layout import LAYOUT_VERSION, LayoutCode, lint_doc, stamp_doc_meta
from custodex.manifest import parse_text

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
