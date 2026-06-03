"""Detect-only drift detection: docs graded against the code (K1, K2, K3).

:func:`detect` is **pure and side-effect free** (K1): it never writes a file and
never calls a backend. For each document it builds the code surface (the single
source of truth, K2) and compares the doc to it:

* the doc file is missing -> ``MISSING_DOC`` (a stub can be created, healable);
* the stored fingerprint differs from the surface hash -> ``HASH``;
* a managed region whose id is a known :data:`REGION_KEYS` key has a body that
  differs from the freshly rendered body -> ``REGION`` (healable);
* a managed region whose id is *not* a known key -> ``UNHEALABLE`` (we cannot
  regenerate prose we do not own).

The audience rule (K3) is enforced upstream in extraction: the user-guide
surface hash excludes docstrings and private symbols, so a comment/docstring- or
private-only change simply does not move that hash and produces no ``HASH``
drift — while it does for an eng-guide. Every :class:`Drift` carries the doc's
audience.
"""

from __future__ import annotations

import difflib
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .blocks import expected_region, known_region_ids
from .config import Audience, MonitorConfig
from .extract import build_document_surface
from .index import render_index
from .manifest import parse_doc, regions, stored_fingerprint

__all__ = ["DriftKind", "Drift", "DriftReport", "detect"]


class DriftKind(str, Enum):
    """The kind of discrepancy detected between a doc and its code surface."""

    MISSING_DOC = "MISSING_DOC"
    HASH = "HASH"
    REGION = "REGION"
    UNHEALABLE = "UNHEALABLE"


class Drift(BaseModel):
    """One detected doc<->code discrepancy (data, never an exception)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DriftKind
    doc_id: str
    doc_path: str
    detail: str
    region_id: str | None = None
    healable: bool = True
    audience: Audience
    diff: str = ""


class DriftReport(BaseModel):
    """The full set of drifts found across a config's documents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    drifts: tuple[Drift, ...]

    @property
    def ok(self) -> bool:
        """True when no drift was detected."""
        return not self.drifts

    def summary(self) -> str:
        """A short human-readable summary of the report."""
        if not self.drifts:
            return "clean — no drift detected"
        lines = [f"{len(self.drifts)} drift(s) detected:"]
        for d in self.drifts:
            loc = f" [{d.region_id}]" if d.region_id else ""
            heal = "" if d.healable else " (UNHEALABLE)"
            lines.append(f"  {d.doc_id}{loc}: {d.kind.value}{heal} — {d.detail}")
        return "\n".join(lines)


def _short_diff(expected: str, actual: str, region_id: str) -> str:
    """A compact unified diff of an expected vs actual region body."""
    return "\n".join(
        difflib.unified_diff(
            actual.split("\n"),
            expected.split("\n"),
            fromfile=f"{region_id} (doc)",
            tofile=f"{region_id} (code)",
            lineterm="",
        )
    )


def detect(config: MonitorConfig, config_dir: Path) -> DriftReport:
    """Detect drift for every document in ``config`` (pure, K1).

    ``root = config_dir / config.root``. Doc and code paths are resolved under
    that root. Returns a :class:`DriftReport`; the file system is never mutated.
    """
    root = config_dir / config.root
    templates = config.region_templates
    known = known_region_ids(templates)
    drifts: list[Drift] = []

    for spec in config.documents:
        surface = build_document_surface(spec, root)
        doc_path = root / spec.path

        if not doc_path.is_file():
            drifts.append(
                Drift(
                    kind=DriftKind.MISSING_DOC,
                    doc_id=spec.id,
                    doc_path=spec.path,
                    detail="document file is missing — a stub can be created",
                    healable=True,
                    audience=spec.audience,
                )
            )
            continue

        doc = parse_doc(doc_path)

        stored = stored_fingerprint(doc)
        current = surface.surface_hash()
        if stored != current:
            drifts.append(
                Drift(
                    kind=DriftKind.HASH,
                    doc_id=spec.id,
                    doc_path=spec.path,
                    detail=(
                        f"fingerprint {stored!r} != current surface hash {current!r}"
                    ),
                    healable=True,
                    audience=spec.audience,
                )
            )

        doc_regions = regions(doc)
        for region_id, current_body in doc_regions.items():
            if region_id not in spec.region_keys:
                # Present in the doc but not declared by the spec — ignore it;
                # the spec governs which regions this doc manages.
                continue
            if region_id not in known:
                drifts.append(
                    Drift(
                        kind=DriftKind.UNHEALABLE,
                        doc_id=spec.id,
                        doc_path=spec.path,
                        detail=(
                            f"managed region {region_id!r} has no known renderer; "
                            "cannot auto-heal"
                        ),
                        region_id=region_id,
                        healable=False,
                        audience=spec.audience,
                    )
                )
                continue
            template = templates.get(region_id)
            expected: str | None
            if template is not None and template.source == "index":
                expected = render_index(template, spec, config, root)
            else:
                expected = expected_region(region_id, surface, template)
            if expected is not None and current_body != expected:
                drifts.append(
                    Drift(
                        kind=DriftKind.REGION,
                        doc_id=spec.id,
                        doc_path=spec.path,
                        detail=f"managed region {region_id!r} is out of date",
                        region_id=region_id,
                        healable=True,
                        audience=spec.audience,
                        diff=_short_diff(expected, current_body, region_id),
                    )
                )

    return DriftReport(drifts=tuple(drifts))
