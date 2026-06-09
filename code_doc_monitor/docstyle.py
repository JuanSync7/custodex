"""``doc-style.yaml`` models + loader and the writing-template composer (N-05).

CONFIG-V2 §1.4/§2. A ``doc-style.yaml`` maps each logical document to ONE
writing template per category — ``document-type``, ``tone``, ``writing-style``,
``vocabulary`` — with a ``defaults`` selection used for any unmapped document.
Each name resolves to ``templates/writing/<category>/<name>.md``; those four
markdown bodies are composed into the agent's AUTHORING prompt when it writes a
no-renderer ``llm`` region's prose.

This lives OUTSIDE :mod:`config` to keep that module lean, and it imports its
four parsing primitives (``CDMON_CONFIG_VERSION``, ``_V2_MODEL_CONFIG``,
``_split_frontmatter``, ``_parse_v2_body``) from the LEAF :mod:`_v2base` — NOT
from :mod:`config`. That makes the edge one-way (``config -> docstyle ->
_v2base``), so :mod:`config` can import the concrete ``DocStyleMap`` at module
level for a precisely-typed ``ConfigBundle.doc_style`` with no cycle (K0, Z-03).

Every failure — a wrong ``cdmon-config-version``/``kind``, an unknown key, or a
mapping naming a template file that does not exist on disk — is a loud, typed
:class:`ConfigError` listing exactly what is missing (K8).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from ._v2base import (
    _V2_MODEL_CONFIG,
    CDMON_CONFIG_VERSION,
    _parse_v2_body,
    _split_frontmatter,
)
from .errors import ConfigError

__all__ = [
    "STYLE_CATEGORIES",
    "DocStyleFrontmatter",
    "DocStyleSelection",
    "DocStyleMapping",
    "DocStyleMap",
    "load_doc_style",
    "dump_doc_style",
    "resolve_style_files",
    "read_style_guidance",
]

#: The four writing-template categories, in the FIXED deterministic order the
#: composer emits them (K10). Each tuple is (attribute, on-disk subdir = alias).
STYLE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("document_type", "document-type"),
    ("tone", "tone"),
    ("writing_style", "writing-style"),
    ("vocabulary", "vocabulary"),
)


class DocStyleFrontmatter(BaseModel):
    """Traceability metadata for ``doc-style.yaml``'s ``---`` block (§1.4)."""

    model_config = _V2_MODEL_CONFIG

    cdmon_config_version: str = Field(alias="cdmon-config-version")
    kind: str
    updated: str

    @model_validator(mode="after")
    def _version_and_kind(self) -> DocStyleFrontmatter:
        if self.cdmon_config_version != CDMON_CONFIG_VERSION:
            raise ValueError(
                f"cdmon-config-version must be {CDMON_CONFIG_VERSION!r}, "
                f"got {self.cdmon_config_version!r}"
            )
        if self.kind != "doc-style-map":
            raise ValueError(f"kind must be 'doc-style-map', got {self.kind!r}")
        return self


class DocStyleSelection(BaseModel):
    """One template per category. Hyphenated YAML aliases, snake_case attrs.

    The four fields name a template stem in each category; the loader validates
    that each resolves to an existing ``templates/writing/<category>/<name>.md``.
    """

    model_config = _V2_MODEL_CONFIG

    document_type: str = Field(alias="document-type")
    tone: str
    writing_style: str = Field(alias="writing-style")
    vocabulary: str


class DocStyleMapping(BaseModel):
    """A per-document override: a ``doc`` id plus its four-template selection.

    The selection fields are flattened onto the mapping in the YAML (``doc`` +
    ``document-type``/``tone``/``writing-style``/``vocabulary``), matching §1.4.
    """

    model_config = _V2_MODEL_CONFIG

    doc: str
    document_type: str = Field(alias="document-type")
    tone: str
    writing_style: str = Field(alias="writing-style")
    vocabulary: str

    @property
    def selection(self) -> DocStyleSelection:
        """The four-template :class:`DocStyleSelection` this mapping carries."""
        # Build via the hyphenated aliases (model_validate keys by alias) so this
        # is sound under mypy whether or not the pydantic plugin is loaded — the
        # synthesized ``__init__`` keys by alias, while ``model_validate`` always
        # accepts them (Z-03).
        return DocStyleSelection.model_validate(
            {
                "document-type": self.document_type,
                "tone": self.tone,
                "writing-style": self.writing_style,
                "vocabulary": self.vocabulary,
            }
        )


class DocStyleMap(BaseModel):
    """``doc-style.yaml`` parsed: frontmatter + defaults + per-doc mappings (§1.4).

    :meth:`style_for` resolves a document id to its :class:`DocStyleSelection`
    (its explicit mapping, else ``defaults``).
    """

    model_config = _V2_MODEL_CONFIG

    frontmatter: DocStyleFrontmatter
    defaults: DocStyleSelection
    mappings: tuple[DocStyleMapping, ...] = ()

    def style_for(self, doc_id: str) -> DocStyleSelection:
        """The selection for ``doc_id``: its mapping if present, else defaults."""
        for mapping in self.mappings:
            if mapping.doc == doc_id:
                return mapping.selection
        return self.defaults


def resolve_style_files(
    selection: DocStyleSelection, templates_root: Path
) -> dict[str, Path]:
    """Return the ``category -> template path`` mapping for ``selection``.

    The four paths are ``templates_root/<category>/<name>.md`` in the fixed
    category order (:data:`STYLE_CATEGORIES`). Existence is NOT checked here —
    :func:`load_doc_style` validates it loudly at load time; this is the pure
    name→path projection.
    """
    return {
        subdir: templates_root / subdir / f"{getattr(selection, attr)}.md"
        for attr, subdir in STYLE_CATEGORIES
    }


def read_style_guidance(selection: DocStyleSelection, templates_root: Path) -> str:
    """Concatenate the four selected template bodies under category headers (K10).

    Deterministic order: document-type, tone, writing-style, vocabulary. Each
    body is read from disk and introduced by a ``## Writing guidance — <category>``
    header so the composed prompt clearly delimits the four axes. A missing or
    unreadable file is a loud :class:`ConfigError` (K8) — though
    :func:`load_doc_style` will have already rejected the map if any file is
    absent.
    """
    files = resolve_style_files(selection, templates_root)
    blocks: list[str] = []
    for _attr, subdir in STYLE_CATEGORIES:
        path = files[subdir]
        try:
            body = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"Cannot read writing template {path}: {exc}") from exc
        blocks.append(f"## Writing guidance — {subdir}\n\n{body}")
    return "\n\n".join(blocks)


def _missing_template_files(
    selection: DocStyleSelection, templates_root: Path, *, where: str
) -> list[str]:
    """Return human-readable ``<where>.<category>=<path>`` for each absent file."""
    missing: list[str] = []
    for subdir, path in resolve_style_files(selection, templates_root).items():
        if not path.is_file():
            missing.append(f"{where}.{subdir} -> {path}")
    return missing


def load_doc_style(path: Path, *, templates_root: Path) -> DocStyleMap:
    """Load and validate ``doc-style.yaml`` (CONFIG-V2 §1.4, loud K8).

    Parses the front matter + body into a :class:`DocStyleMap`, then validates
    that EVERY named template (the ``defaults`` and every mapping's four names)
    resolves to an existing ``templates_root/<category>/<name>.md``. A missing
    file raises a :class:`ConfigError` listing every offending selection, so a
    typo is caught once with the full picture rather than one at a time.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc
    meta, body = _split_frontmatter(text, path)
    data = _parse_v2_body(body, path)
    try:
        doc_style = DocStyleMap(frontmatter=DocStyleFrontmatter(**meta), **data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid doc-style file {path}:\n{exc}") from exc

    missing: list[str] = _missing_template_files(
        doc_style.defaults, templates_root, where="defaults"
    )
    for mapping in doc_style.mappings:
        missing.extend(
            _missing_template_files(
                mapping.selection, templates_root, where=f"mappings[{mapping.doc}]"
            )
        )
    if missing:
        listed = "\n  ".join(missing)
        raise ConfigError(
            f"doc-style file {path} names template file(s) that do not exist "
            f"under {templates_root}:\n  {listed}"
        )
    return doc_style


def _selection_to_yaml(selection: DocStyleSelection) -> dict[str, str]:
    """Project a :class:`DocStyleSelection` to its hyphenated-alias YAML dict (K10)."""
    return {subdir: getattr(selection, attr) for attr, subdir in STYLE_CATEGORIES}


def dump_doc_style(doc_style: DocStyleMap, *, now: str) -> str:
    """Serialize a :class:`DocStyleMap` to canonical ``doc-style.yaml`` text (E-06).

    Returns the full ``---``-fenced front matter + body YAML such that
    ``load_doc_style`` of the written text round-trips to an EQUAL model
    (defaults + every per-doc mapping's four-template selection, in order).
    Deterministic key order and idempotent (K7): dumping a loaded-then-dumped map
    is byte-identical. The front-matter ``updated:`` field is refreshed to ``now``
    (the injected clock seam, K10); the version + kind are carried unchanged.
    Mirrors :func:`code_doc_monitor.config.dump_unit_file`'s frontmatter+body shape
    and reuses the ``---`` fence :func:`_split_frontmatter` re-parses.
    """
    fm = doc_style.frontmatter
    fm_lines = [
        "---",
        f"cdmon-config-version: {_yaml_scalar(fm.cdmon_config_version)}",
        f"kind: {_yaml_scalar(fm.kind)}",
        f"updated: {_yaml_scalar(now)}",
        "---",
    ]
    body_obj: dict[str, object] = {
        "defaults": _selection_to_yaml(doc_style.defaults),
        "mappings": [
            {"doc": m.doc, **_selection_to_yaml(m.selection)}
            for m in doc_style.mappings
        ],
    }
    body = yaml.safe_dump(
        body_obj,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    return "\n".join(fm_lines) + "\n" + body


def _yaml_scalar(value: str) -> str:
    """Quote a scalar the way :func:`yaml.safe_dump` would, deterministically.

    Mirrors :func:`code_doc_monitor.config._yaml_scalar` so the hand-built
    front-matter lines re-parse identically (idempotent, K7).
    """
    dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True)
    return dumped.replace("\n...\n", "").rstrip("\n")
