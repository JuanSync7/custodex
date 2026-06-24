"""The golden feature catalog (EPIC R).

The single machine-readable source of truth for every cdx *feature*. The
catalog lives in ``feature-doc/catalog/*.yaml`` (one file per subsystem,
mirroring the ``config/cdmon/`` multi-file layout); ``feature-doc/FEATURES.md``
is *rendered* from it by :func:`render_features_md` and never hand-edited — the
yaml is the only place a feature's prose lives, so there is nothing to drift.

Pure and deterministic (no clock, sorted output — K10); loud on every malformed
input (a :class:`CatalogError`, never a silent empty catalog — K8); no new
dependency (pydantic + pyyaml are already core — K0); never imports or executes
target code (K1). Demos/tests are wired into the ``demos``/``tests`` slots by
later EPIC-R slices (R3/R5); R-01 ships the schema, loader, and renderer.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from .errors import CatalogError

__all__ = [
    "FEATURE_ID_RE",
    "Feature",
    "FeatureCatalog",
    "load_catalog",
    "render_features_md",
]

# A stable feature id: ``FEAT-<SUBSYSTEM>-<NNN>`` where SUBSYSTEM is uppercase
# alnum (e.g. EXTRACT, CONFIGV2) and NNN is a zero-padded 3-digit ordinal.
FEATURE_ID_RE: Final = re.compile(r"^FEAT-[A-Z][A-Z0-9]*-\d{3}$")

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

_Status = Literal["implemented", "planned", "deprecated"]


class Feature(BaseModel):
    """One catalogued capability — the golden reference for a single feature.

    Frozen + ``extra="forbid"``: a feature is an immutable, audited record and an
    unknown key is a typo we want to fail loud on (K8), not silently ignore.
    """

    model_config = _MODEL_CONFIG

    id: str
    title: str
    summary: str
    subsystem: str
    modules: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    status: _Status = "implemented"
    demos: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def _id_pattern(cls, v: str) -> str:
        if not FEATURE_ID_RE.match(v):
            raise ValueError(f"feature id {v!r} must match {FEATURE_ID_RE.pattern}")
        return v

    @field_validator("modules")
    @classmethod
    def _modules_non_empty(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("a feature must name at least one implementing module")
        return v


class FeatureCatalog(BaseModel):
    """An immutable, id-sorted collection of :class:`Feature` records."""

    model_config = ConfigDict(frozen=True)

    features: tuple[Feature, ...]

    def by_id(self, fid: str) -> Feature:
        """Return the feature with ``fid``; loud :class:`CatalogError` on miss (K8)."""
        for f in self.features:
            if f.id == fid:
                return f
        raise CatalogError(f"no feature with id {fid!r} in the catalog")

    def by_subsystem(self) -> dict[str, tuple[Feature, ...]]:
        """Group features by subsystem; deterministic insertion order (K10)."""
        groups: dict[str, list[Feature]] = {}
        for f in self.features:  # self.features is already id-sorted
            groups.setdefault(f.subsystem, []).append(f)
        return {sub: tuple(items) for sub, items in sorted(groups.items())}


def load_catalog(
    catalog_dir: Path,
    *,
    known_modules: Collection[str] | None = None,
) -> FeatureCatalog:
    """Aggregate ``catalog_dir/*.yaml`` into one validated, id-sorted catalog.

    Each yaml file is ``{"features": [ {<Feature fields>}, ... ]}``. Loud
    :class:`CatalogError` (K8) on: a missing dir, a dir with no ``*.yaml``,
    malformed yaml, a field/validation failure (with the offending file named),
    a duplicate id across files, or — when ``known_modules`` is supplied — a
    feature naming a module not in that set. Deterministic: files are read in
    sorted order and the result is sorted by id (K10).
    """
    if not catalog_dir.is_dir():
        raise CatalogError(f"feature catalog dir not found: {catalog_dir}")
    files = sorted(catalog_dir.glob("*.yaml"))
    if not files:
        raise CatalogError(f"no *.yaml feature files under {catalog_dir}")

    by_id: dict[str, Feature] = {}
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise CatalogError(
                f"{path.name}: unreadable or malformed yaml: {exc}"
            ) from exc
        if data is None:
            continue
        if not isinstance(data, dict) or "features" not in data:
            raise CatalogError(f"{path.name}: expected a mapping with a 'features' key")
        raw_features = data["features"]
        if not isinstance(raw_features, list):
            raise CatalogError(f"{path.name}: 'features' must be a list")
        for raw in raw_features:
            try:
                feat = Feature.model_validate(raw)
            except Exception as exc:  # pydantic ValidationError + anything malformed
                raise CatalogError(f"{path.name}: invalid feature: {exc}") from exc
            if feat.id in by_id:
                raise CatalogError(
                    f"{path.name}: duplicate feature id {feat.id!r} "
                    "(already defined in the catalog)"
                )
            if known_modules is not None:
                unknown = [m for m in feat.modules if m not in known_modules]
                if unknown:
                    raise CatalogError(
                        f"{path.name}: feature {feat.id} names unknown module(s): "
                        f"{', '.join(sorted(unknown))}"
                    )
            by_id[feat.id] = feat

    features = tuple(sorted(by_id.values(), key=lambda f: f.id))
    return FeatureCatalog(features=features)


def render_features_md(catalog: FeatureCatalog) -> str:
    """Render the human golden reference (``feature-doc/FEATURES.md``) — pure (K10).

    Grouped by subsystem (sorted), features sorted by id, with a demo/test
    traceability column so a reader sees coverage at a glance. No clock, no
    environment — same catalog in, byte-identical markdown out.
    """
    lines: list[str] = [
        "# custodex — feature reference (golden)",
        "",
        (
            "Generated from `feature-doc/catalog/*.yaml` — **do not hand-edit**. "
            "Run `cdx wiki` (R-08) to regenerate. Each row's Demos/Tests columns "
            "trace the feature to its demo case(s) and test(s)."
        ),
        "",
        f"**{len(catalog.features)} features** across "
        f"{len(catalog.by_subsystem())} subsystems.",
        "",
    ]
    for subsystem, feats in catalog.by_subsystem().items():
        lines.append(f"## {subsystem}")
        lines.append("")
        lines.append(
            "| ID | Feature | Modules | Constraints | Demos | Tests | Status |"
        )
        lines.append(
            "|----|---------|---------|-------------|-------|-------|--------|"
        )
        for f in feats:
            lines.append(
                f"| `{f.id}` | {f.title} | {', '.join(f.modules)} | "
                f"{', '.join(f.constraints) or '—'} | "
                f"{', '.join(f.demos) or '—'} | "
                f"{len(f.tests) or '—'} | {f.status} |"
            )
        lines.append("")
        for f in feats:
            lines.append(f"### `{f.id}` — {f.title}")
            lines.append("")
            lines.append(f.summary)
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
