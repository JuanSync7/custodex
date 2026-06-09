"""N-05 — tests for ``doc-style.yaml`` + the writing-template composer (K8/K10).

Covers the :mod:`code_doc_monitor.docstyle` models (frontmatter/kind validation,
hyphenated-alias round-trip), :func:`load_doc_style` (loud on a missing template
file, K8), :meth:`DocStyleMap.style_for` (mapping overrides defaults),
:func:`resolve_style_files`, and :func:`read_style_guidance` (the four bodies in
the fixed deterministic order, K10) — plus the :func:`load_bundle` seam exposing
``bundle.doc_style`` (present ⇒ a map, absent ⇒ None, K6).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.config import load_bundle
from code_doc_monitor.docstyle import (
    STYLE_CATEGORIES,
    DocStyleMap,
    DocStyleMapping,
    DocStyleSelection,
    load_doc_style,
    read_style_guidance,
    resolve_style_files,
)
from code_doc_monitor.errors import ConfigError
from tests.test_config_v2 import _write_tree

# All template stems referenced by the fixtures below, per category.
_TEMPLATES: dict[str, tuple[str, ...]] = {
    "document-type": ("api-reference", "tutorial"),
    "tone": ("precise", "friendly"),
    "writing-style": ("reference-dense", "narrative"),
    "vocabulary": ("engine-domain", "general"),
}

_DOC_STYLE_DEFAULTS_ONLY = (
    '---\ncdmon-config-version: "2.0.0"\nkind: doc-style-map\n'
    'updated: "2026-06-07"\n---\n'
    "defaults:\n"
    "  document-type: api-reference\n"
    "  tone: precise\n"
    "  writing-style: reference-dense\n"
    "  vocabulary: engine-domain\n"
)

_DOC_STYLE_WITH_MAPPING = _DOC_STYLE_DEFAULTS_ONLY + (
    "mappings:\n"
    "  - doc: agent-workflow\n"
    "    document-type: tutorial\n"
    "    tone: friendly\n"
    "    writing-style: narrative\n"
    "    vocabulary: general\n"
)


def _write_templates(repo_root: Path) -> Path:
    """Materialize every fixture template under ``templates/writing`` (K10 layout)."""
    root = repo_root / "templates" / "writing"
    for category, names in _TEMPLATES.items():
        cat_dir = root / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            # The body uniquely identifies the file so a composed prompt is
            # assertable by substring.
            (cat_dir / f"{name}.md").write_text(
                f"# {category}/{name}\nBODY-{category}-{name}\n", encoding="utf-8"
            )
    return root


# --------------------------------------------------------------------------- #
# Models: frontmatter/kind validation + alias round-trip.
# --------------------------------------------------------------------------- #


def test_selection_hyphenated_alias_round_trip() -> None:
    """The hyphenated YAML aliases populate the snake_case attributes."""
    sel = DocStyleSelection.model_validate(
        {
            "document-type": "api-reference",
            "tone": "precise",
            "writing-style": "reference-dense",
            "vocabulary": "engine-domain",
        }
    )
    assert sel.document_type == "api-reference"
    assert sel.writing_style == "reference-dense"
    assert sel.tone == "precise"
    assert sel.vocabulary == "engine-domain"


def test_mapping_selection_property_projects_four_fields() -> None:
    """A mapping's ``selection`` carries exactly its four template names."""
    mapping = DocStyleMapping.model_validate(
        {
            "doc": "d",
            "document-type": "tutorial",
            "tone": "friendly",
            "writing-style": "narrative",
            "vocabulary": "general",
        }
    )
    sel = mapping.selection
    assert (sel.document_type, sel.tone, sel.writing_style, sel.vocabulary) == (
        "tutorial",
        "friendly",
        "narrative",
        "general",
    )


def test_wrong_version_is_loud(tmp_path: Path) -> None:
    """A non-2.0.0 cdmon-config-version is a loud ConfigError (K8)."""
    repo = tmp_path
    root = _write_templates(repo)
    path = tmp_path / "doc-style.yaml"
    path.write_text(
        _DOC_STYLE_DEFAULTS_ONLY.replace('"2.0.0"', '"1.0.0"'), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="cdmon-config-version"):
        load_doc_style(path, templates_root=root)


def test_wrong_kind_is_loud(tmp_path: Path) -> None:
    """A kind other than doc-style-map is a loud ConfigError (K8)."""
    root = _write_templates(tmp_path)
    path = tmp_path / "doc-style.yaml"
    path.write_text(
        _DOC_STYLE_DEFAULTS_ONLY.replace("doc-style-map", "something-else"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="kind"):
        load_doc_style(path, templates_root=root)


def test_unknown_key_is_loud(tmp_path: Path) -> None:
    """An unknown body key is rejected (extra='forbid', K8)."""
    root = _write_templates(tmp_path)
    path = tmp_path / "doc-style.yaml"
    path.write_text(_DOC_STYLE_DEFAULTS_ONLY + "bogus: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid doc-style file"):
        load_doc_style(path, templates_root=root)


def test_missing_file_is_loud(tmp_path: Path) -> None:
    """A doc-style.yaml that does not exist is a loud ConfigError (K8)."""
    root = _write_templates(tmp_path)
    with pytest.raises(ConfigError, match="Cannot read config file"):
        load_doc_style(tmp_path / "nope.yaml", templates_root=root)


# --------------------------------------------------------------------------- #
# load_doc_style: template-file existence validation (loud K8).
# --------------------------------------------------------------------------- #


def test_load_doc_style_happy_path(tmp_path: Path) -> None:
    """A valid map whose templates all exist loads into a DocStyleMap."""
    root = _write_templates(tmp_path)
    path = tmp_path / "doc-style.yaml"
    path.write_text(_DOC_STYLE_WITH_MAPPING, encoding="utf-8")
    ds = load_doc_style(path, templates_root=root)
    assert isinstance(ds, DocStyleMap)
    assert ds.frontmatter.kind == "doc-style-map"
    assert len(ds.mappings) == 1


def test_missing_default_template_is_loud_and_listed(tmp_path: Path) -> None:
    """A defaults selection naming an absent template file is loud, listed (K8)."""
    root = _write_templates(tmp_path)
    (root / "tone" / "precise.md").unlink()  # break one default
    path = tmp_path / "doc-style.yaml"
    path.write_text(_DOC_STYLE_DEFAULTS_ONLY, encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_doc_style(path, templates_root=root)
    msg = str(excinfo.value)
    assert "do not exist" in msg
    assert "defaults.tone" in msg
    assert "precise.md" in msg


def test_missing_mapping_template_is_loud_with_doc_id(tmp_path: Path) -> None:
    """A mapping naming an absent template names the offending doc id (K8)."""
    root = _write_templates(tmp_path)
    (root / "writing-style" / "narrative.md").unlink()  # break the mapping
    path = tmp_path / "doc-style.yaml"
    path.write_text(_DOC_STYLE_WITH_MAPPING, encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_doc_style(path, templates_root=root)
    msg = str(excinfo.value)
    assert "mappings[agent-workflow].writing-style" in msg


# --------------------------------------------------------------------------- #
# style_for + resolve_style_files + read_style_guidance.
# --------------------------------------------------------------------------- #


def test_style_for_returns_defaults_when_unmapped(tmp_path: Path) -> None:
    """A doc with no explicit mapping resolves to ``defaults``."""
    root = _write_templates(tmp_path)
    path = tmp_path / "doc-style.yaml"
    path.write_text(_DOC_STYLE_WITH_MAPPING, encoding="utf-8")
    ds = load_doc_style(path, templates_root=root)
    sel = ds.style_for("some-other-doc")
    assert sel == ds.defaults
    assert sel.document_type == "api-reference"


def test_style_for_mapping_overrides_defaults(tmp_path: Path) -> None:
    """A mapped doc resolves to its mapping, not defaults."""
    root = _write_templates(tmp_path)
    path = tmp_path / "doc-style.yaml"
    path.write_text(_DOC_STYLE_WITH_MAPPING, encoding="utf-8")
    ds = load_doc_style(path, templates_root=root)
    sel = ds.style_for("agent-workflow")
    assert sel.document_type == "tutorial"
    assert sel.tone == "friendly"
    assert sel.writing_style == "narrative"
    assert sel.vocabulary == "general"


def test_resolve_style_files_paths(tmp_path: Path) -> None:
    """resolve_style_files maps each category to its on-disk template path."""
    root = _write_templates(tmp_path)
    sel = DocStyleSelection(
        document_type="api-reference",
        tone="precise",
        writing_style="reference-dense",
        vocabulary="engine-domain",
    )
    files = resolve_style_files(sel, root)
    assert files["document-type"] == root / "document-type" / "api-reference.md"
    assert files["tone"] == root / "tone" / "precise.md"
    assert files["writing-style"] == root / "writing-style" / "reference-dense.md"
    assert files["vocabulary"] == root / "vocabulary" / "engine-domain.md"
    # Keys are exactly the four categories.
    assert set(files) == {subdir for _attr, subdir in STYLE_CATEGORIES}


def test_read_style_guidance_contains_four_bodies_in_fixed_order(
    tmp_path: Path,
) -> None:
    """All four bodies appear under category headers in doc-type→vocabulary order."""
    root = _write_templates(tmp_path)
    sel = DocStyleSelection(
        document_type="api-reference",
        tone="precise",
        writing_style="reference-dense",
        vocabulary="engine-domain",
    )
    text = read_style_guidance(sel, root)
    for body in (
        "BODY-document-type-api-reference",
        "BODY-tone-precise",
        "BODY-writing-style-reference-dense",
        "BODY-vocabulary-engine-domain",
    ):
        assert body in text
    # Fixed order: document-type, tone, writing-style, vocabulary (K10).
    positions = [
        text.index("## Writing guidance — document-type"),
        text.index("## Writing guidance — tone"),
        text.index("## Writing guidance — writing-style"),
        text.index("## Writing guidance — vocabulary"),
    ]
    assert positions == sorted(positions)


def test_read_style_guidance_loud_on_missing_file(tmp_path: Path) -> None:
    """read_style_guidance raises a loud ConfigError if a body file vanished (K8)."""
    root = _write_templates(tmp_path)
    sel = DocStyleSelection(
        document_type="api-reference",
        tone="precise",
        writing_style="reference-dense",
        vocabulary="engine-domain",
    )
    (root / "tone" / "precise.md").unlink()
    with pytest.raises(ConfigError, match="Cannot read writing template"):
        read_style_guidance(sel, root)


# --------------------------------------------------------------------------- #
# load_bundle seam: bundle.doc_style present vs absent (K6 additive).
# --------------------------------------------------------------------------- #


def test_bundle_doc_style_none_when_absent(tmp_path: Path) -> None:
    """No doc-style.yaml ⇒ bundle.doc_style is None (back-compat, K6)."""
    d = _write_tree(tmp_path)
    bundle = load_bundle(d)
    assert bundle.doc_style is None


def test_bundle_loads_doc_style_when_present(tmp_path: Path) -> None:
    """A present doc-style.yaml ⇒ bundle.doc_style is a populated DocStyleMap."""
    d = _write_tree(tmp_path)
    repo_root = d.parent.parent  # config/cdmon -> repo root (index root "../..")
    _write_templates(repo_root)
    (d / "doc-style.yaml").write_text(_DOC_STYLE_WITH_MAPPING, encoding="utf-8")
    bundle = load_bundle(d)
    assert isinstance(bundle.doc_style, DocStyleMap)
    assert bundle.doc_style.style_for("agent-workflow").document_type == "tutorial"


def test_bundle_loud_when_doc_style_template_missing(tmp_path: Path) -> None:
    """load_bundle surfaces the loud missing-template error from doc-style (K8)."""
    d = _write_tree(tmp_path)
    repo_root = d.parent.parent
    _write_templates(repo_root)
    (repo_root / "templates" / "writing" / "tone" / "precise.md").unlink()
    (d / "doc-style.yaml").write_text(_DOC_STYLE_DEFAULTS_ONLY, encoding="utf-8")
    with pytest.raises(ConfigError, match="do not exist"):
        load_bundle(d)
