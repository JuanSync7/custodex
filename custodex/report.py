"""``coverage.rpt`` builder + renderer (CONFIG-V2 §3, N-04 — K0/K1/K7/K8/K10).

The ``.rpt`` is a GENERATED, byte-stable coverage report: a leading ``---``
front-matter block (report-version / kind / repo / ref / generated-by) over a
YAML body (``summary`` + per-``units`` breakdown + an ``undocumented`` list that
names, for each gap file, the ``suggested_unit`` it should be declared in). It is
PURE except for the disk reads the underlying coverage engine performs.

This module does NOT fork the coverage engine. :func:`build_coverage_rpt` reuses
:func:`custodex.config.effective_coverage` to derive the scan scope from
the dir layout, then runs the EXACT same path the ``cdx coverage`` CLI runs —
:func:`inventory.discover_files` → :func:`inventory.discover_symbols` →
:func:`coverage.resolve_coverage` — and projects the resulting
:class:`~custodex.coverage.CoverageReport` into the report shape. So the
``.rpt`` counts and percentages are the same facts the coverage view shows, never
a parallel computation.

Determinism (K10) + idempotency (K7): every list is sorted, percentages are
formatted to a fixed 2 decimals (``n/a`` when the denominator is 0), and NO
wall-clock is written into the file — provenance rides on ``ref`` (a branch or
commit), so re-running with no code/config change rewrites byte-identical content.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from . import coverage as coverage_mod
from . import inventory
from .config import (
    _DEFAULT_EXCLUDE,
    ConfigBundle,
    UnitFile,
    _resolve_repo_root,
    effective_coverage,
    unit_for_path,
)
from .errors import ConfigError

__all__ = [
    "CDMON_REPORT_VERSION",
    "RptSummary",
    "RptUnit",
    "RptUndocumented",
    "CoverageRpt",
    "build_coverage_rpt",
    "render_rpt",
    "parse_rpt",
    "write_rpt",
]

#: The only accepted ``cdmon-report-version`` for the ``.rpt`` shape (§3).
CDMON_REPORT_VERSION = "1.0.0"

#: Provenance string stamped in the front matter (mirrors the CLI command name).
_GENERATED_BY = "cdx rpt"

# Frozen + extra="forbid": a report is an immutable, normalized snapshot (K10);
# an unknown field is a programming error, not a silent pass (K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class RptSummary(BaseModel):
    """Repo-wide coverage counts (CONFIG-V2 §3 ``summary``).

    ``scanned_files`` is the coverage universe (files under some unit
    ``dir-covered``, format-matched, minus the ignore set). ``documented_files``/
    ``waived_files``/``uncovered_files`` come straight from the
    :class:`~custodex.coverage.CoverageReport` baskets. ``ignored_files``
    counts files under the unit dirs that the ignore/exclude set removed from the
    universe (informational). ``percent`` = ``100 * documented / (scanned -
    waived)``, or ``None`` (rendered ``n/a``) when that denominator is 0.
    """

    model_config = _MODEL_CONFIG

    scanned_files: int
    documented_files: int
    waived_files: int
    ignored_files: int
    uncovered_files: int
    percent: float | None


class RptUnit(BaseModel):
    """One unit's coverage slice (CONFIG-V2 §3 ``units[]``).

    ``scanned``/``documented`` count the universe files attributed to this unit
    (by ``dir-covered`` containment); ``percent`` is the per-unit file percentage
    computed the SAME way as the overall summary — waived files leave BOTH sides,
    so ``percent = 100 * documented / (scanned - waived)`` (``None`` when that
    denominator is 0); ``uncovered`` lists the unit's undocumented gap files,
    sorted.
    """

    model_config = _MODEL_CONFIG

    unit: str
    file: str
    scanned: int
    documented: int
    percent: float | None
    uncovered: tuple[str, ...]


class RptUndocumented(BaseModel):
    """One gap file plus where it should be declared (CONFIG-V2 §3 ``undocumented[]``).

    ``suggested_unit`` is the filename of the unit whose ``dir-covered`` contains
    ``path`` AND whose ``source-files-format`` includes its extension; ``None``
    when no unit matches, with ``reason`` explaining why.
    """

    model_config = _MODEL_CONFIG

    path: str
    suggested_unit: str | None
    reason: str


class CoverageRpt(BaseModel):
    """The parsed ``coverage.rpt`` shape (CONFIG-V2 §3).

    ``ref`` is the branch/commit the report reflects (provenance preferred over a
    wall-clock so the written file is byte-stable, K7); a later sync slice fills
    it from git. The model is frozen so two builds of an unchanged repo compare
    equal (the round-trip + idempotency invariants).
    """

    model_config = _MODEL_CONFIG

    cdmon_report_version: str
    kind: str
    repo: str
    ref: str | None
    summary: RptSummary
    units: tuple[RptUnit, ...]
    undocumented: tuple[RptUndocumented, ...]


def _path_under(path: str, directory: str) -> bool:
    """True if repo-relative ``path`` lives at or under ``directory`` (K10)."""
    posix = path.replace("\\", "/").strip("/")
    d = directory.replace("\\", "/").strip("/")
    if not d:
        return True
    return posix == d or posix.startswith(d + "/")


def _ext(path: str) -> str:
    """Lower-cased extension (with dot) of ``path``; ``""`` if none."""
    return Path(path).suffix.lower()


def _file_for_unit(bundle: ConfigBundle, unit: UnitFile) -> str:
    """The index filename for ``unit`` (its provenance in the bundle, Z-01a)."""
    for u, ref in zip(bundle.units, bundle.index.units, strict=True):
        if u is unit:
            return ref.file
    # Unreachable for a unit drawn from this bundle; defensive fallback.
    return unit.frontmatter.unit


def _suggest_unit(bundle: ConfigBundle, path: str) -> tuple[str | None, str]:
    """Resolve ``(suggested_unit_filename, reason)`` for a gap file (§3, Z-01a).

    The suggested unit is the DEEPEST unit whose ``dir-covered`` contains
    ``path`` (deepest-wins attribution); the format check is then that deepest
    unit's ``source-files-format``. If the deepest owning unit's format does not
    include the path's extension, return ``(None, reason)`` naming the format
    mismatch; if no unit's directory contains it at all, return ``(None, reason)``
    saying so. Deterministic: deepest match, ties by bundle order.
    """
    ext = _ext(path)
    unit = unit_for_path(bundle, path)
    if unit is None:
        return (None, f"no unit dir-covered contains {path!r}")
    if ext in unit.source_files_format:
        d = next(d for d in unit.dir_covered if _path_under(path, d))
        return (
            _file_for_unit(bundle, unit),
            f"under dir-covered {d!r} and format {ext!r}",
        )
    return (
        None,
        f"under the deepest unit {_file_for_unit(bundle, unit)!r} but extension "
        f"{ext!r} is not in its source-files-format",
    )


def _percent(documented: int, universe: int) -> float | None:
    """``100 * documented / universe`` rounded to 2 dp, or ``None`` if universe 0.

    Rounded at build time (not just at render) so the stored value is exactly the
    2-dp figure the file shows — ``parse_rpt(render_rpt(r)) == r`` holds (the file
    can carry only 2 decimals, so the model must too). ``None`` when the
    denominator is 0 (rendered ``n/a``), per §3.
    """
    if universe == 0:
        return None
    return round(documented / universe * 100.0, 2)


def build_coverage_rpt(
    bundle: ConfigBundle, repo_root: Path, *, ref: str | None
) -> CoverageRpt:
    """Build the coverage report for ``bundle`` over ``repo_root`` (N-04).

    Reuses the REAL coverage engine (no fork): derives the scan scope via
    :func:`effective_coverage`, runs :func:`inventory.discover_files` →
    :func:`inventory.discover_symbols` → :func:`coverage.resolve_coverage`, and
    projects the resulting :class:`CoverageReport` into the ``.rpt`` shape.

    ``scanned_files`` is the universe size; the baskets feed
    ``documented``/``waived``/``uncovered``. ``ignored_files`` counts files under
    the unit dirs the ignore set removed (the same dir×format includes scanned
    with ONLY the default excludes, minus the universe). Per-unit slices attribute
    each universe file to the unit whose ``dir-covered`` contains it; the
    ``undocumented`` list pairs each gap file with its ``suggested_unit``. Pure
    except for the engine's reads; ``ref`` is provenance only (K7).
    """
    cov = effective_coverage(bundle, repo_root)
    inv = inventory.discover_files(repo_root, include=cov.include, exclude=cov.exclude)
    sym = inventory.discover_symbols(inv, repo_root)
    report = coverage_mod.resolve_coverage(bundle.config, sym)

    documented = report.documented_files
    undocumented = report.undocumented_files
    waived = report.waived_files
    universe = report.files  # scanned = format-matched, under-unit, non-ignored

    # ignored_files (informational): files under the unit dirs that the ignore set
    # removed. Re-scan the unit dir×format includes with ONLY the default excludes
    # (no ignore patterns / .gitignore), then subtract the universe. Deterministic.
    ignored = _count_ignored(bundle, repo_root, cov.include, len(universe))

    summary = RptSummary(
        scanned_files=len(universe),
        documented_files=len(documented),
        waived_files=len(waived),
        ignored_files=ignored,
        uncovered_files=len(undocumented),
        percent=_percent(len(documented), len(universe) - len(waived)),
    )

    units = _build_units(bundle, report)
    undoc = tuple(
        sorted(
            (
                RptUndocumented(
                    path=f.path,
                    suggested_unit=su,
                    reason=reason,
                )
                for f in undocumented
                for su, reason in (_suggest_unit(bundle, f.path),)
            ),
            key=lambda e: e.path,
        )
    )

    return CoverageRpt(
        cdmon_report_version=CDMON_REPORT_VERSION,
        kind="coverage",
        repo=bundle.index.frontmatter.repo,
        ref=ref,
        summary=summary,
        units=units,
        undocumented=undoc,
    )


def _count_ignored(
    bundle: ConfigBundle,
    repo_root: Path,
    include: tuple[str, ...],
    universe_size: int,
) -> int:
    """Count files the ignore set removed from the unit-dir × format scope (§3).

    The universe scan applies the FULL exclude set (defaults ∪ ignore ∪
    translated .gitignore). Re-scanning the same ``include`` with ONLY the default
    excludes yields the in-scope-before-ignore set; the difference from the
    universe is the count of files the ignore/exclude set removed. Deterministic
    (a pure re-scan, no wall-clock).
    """
    pre_ignore = inventory.discover_files(
        repo_root, include=include, exclude=_DEFAULT_EXCLUDE
    )
    return max(0, len(pre_ignore.files) - universe_size)


def _build_units(
    bundle: ConfigBundle, report: coverage_mod.CoverageReport
) -> tuple[RptUnit, ...]:
    """Per-unit slices: attribute each universe file to its owning unit (§3).

    The per-unit ``percent`` mirrors the overall summary's math: a waived file
    leaves BOTH the numerator and the denominator (A-04), so a unit whose only
    unreferenced files are all waived reports 100% — not a phantom gap. The
    waived set comes from the SAME :class:`CoverageReport` baskets the summary
    uses, so the two can never diverge.

    Attribution is DEEPEST-WINS (Z-01a): each universe file is counted under the
    single unit whose ``dir-covered`` is its deepest ancestor (via
    :func:`unit_for_path`), so a file in a child unit's dir counts under the child
    only — the parent unit never double-counts it.
    """
    documented_paths = {f.path for f in report.documented_files}
    gap_paths = {f.path for f in report.undocumented_files}
    waived_paths = {f.path for f in report.waived_files}

    # Deepest-wins: map each universe file to its single owning unit ONCE.
    owner_of: dict[str, UnitFile | None] = {
        f.path: unit_for_path(bundle, f.path) for f in report.files
    }

    units: list[RptUnit] = []
    for unit, ref in zip(bundle.units, bundle.index.units, strict=True):
        scanned = [f.path for f in report.files if owner_of[f.path] is unit]
        doc_n = sum(1 for p in scanned if p in documented_paths)
        waived_n = sum(1 for p in scanned if p in waived_paths)
        uncovered = tuple(sorted(p for p in scanned if p in gap_paths))
        units.append(
            RptUnit(
                unit=unit.frontmatter.unit,
                file=ref.file,
                scanned=len(scanned),
                documented=doc_n,
                # Waived files leave BOTH sides — the same removal the overall
                # summary applies (`scanned - waived`), so the two are consistent.
                percent=_percent(doc_n, len(scanned) - waived_n),
                uncovered=uncovered,
            )
        )
    return tuple(units)


# --------------------------------------------------------------------------- #
# Render / parse — ``---`` frontmatter + YAML body; byte-stable; round-trips.
# --------------------------------------------------------------------------- #


def _fmt_percent(value: float | None) -> str:
    """Format a percentage to a fixed 2 decimals, or ``n/a`` for ``None`` (K10)."""
    return "n/a" if value is None else f"{value:.2f}"


def render_rpt(rpt: CoverageRpt) -> str:
    """Render ``rpt`` to ``---`` frontmatter + YAML body, byte-stable (K7/K10).

    The front matter carries report-version / kind / repo / ref / generated-by
    (NO wall-clock — provenance is ``ref`` so re-runs are byte-identical). The
    body emits ``summary`` then ``units`` then ``undocumented`` in a fixed key
    order, every list sorted, percentages at 2 decimals (``n/a`` when None). The
    output round-trips: ``parse_rpt(render_rpt(r)) == r``.
    """
    lines: list[str] = []
    # Front matter (fixed key order).
    lines.append("---")
    lines.append(f"cdmon-report-version: {rpt.cdmon_report_version}")
    lines.append(f"kind: {rpt.kind}")
    lines.append(f"repo: {rpt.repo}")
    lines.append(f"ref: {rpt.ref if rpt.ref is not None else 'null'}")
    lines.append(f"generated-by: {_GENERATED_BY}")
    lines.append("---")

    # summary.
    s = rpt.summary
    lines.append("summary:")
    lines.append(f"  scanned_files: {s.scanned_files}")
    lines.append(f"  documented_files: {s.documented_files}")
    lines.append(f"  waived_files: {s.waived_files}")
    lines.append(f"  ignored_files: {s.ignored_files}")
    lines.append(f"  uncovered_files: {s.uncovered_files}")
    lines.append(f"  percent: {_fmt_percent(s.percent)}")

    # units.
    if not rpt.units:
        lines.append("units: []")
    else:
        lines.append("units:")
        for u in rpt.units:
            lines.append(f"  - unit: {u.unit}")
            lines.append(f"    file: {u.file}")
            lines.append(f"    scanned: {u.scanned}")
            lines.append(f"    documented: {u.documented}")
            lines.append(f"    percent: {_fmt_percent(u.percent)}")
            if not u.uncovered:
                lines.append("    uncovered: []")
            else:
                lines.append("    uncovered:")
                lines.extend(f"      - {p}" for p in u.uncovered)

    # undocumented.
    if not rpt.undocumented:
        lines.append("undocumented: []")
    else:
        lines.append("undocumented:")
        for e in rpt.undocumented:
            lines.append(f"  - path: {e.path}")
            su = e.suggested_unit if e.suggested_unit is not None else "null"
            lines.append(f"    suggested_unit: {su}")
            lines.append(f"    reason: {_yaml_scalar(e.reason)}")

    return "\n".join(lines) + "\n"


def _yaml_scalar(value: str) -> str:
    """Emit a string as a safe single-line YAML scalar (quoted if needed).

    Reuses PyYAML's dumper so embedded quotes / colons / hashes are escaped
    exactly as a parser expects, keeping the round-trip lossless (K10). The value
    is dumped inside a one-item flow list (``[scalar]``) and unwrapped: that yields
    a clean single-line scalar WITHOUT the ``\\n...\\n`` document-end marker a bare
    scalar dump appends (we control line breaks ourselves).
    """
    flow = yaml.safe_dump([value], default_flow_style=True, width=10**9).strip()
    return flow[1:-1]  # strip the surrounding ``[`` ``]``


def parse_rpt(text: str) -> CoverageRpt:
    """Parse rendered ``.rpt`` text back into a :class:`CoverageRpt` (loud K8).

    Splits the leading ``---`` front matter from the YAML body, validates the
    report version, and rebuilds the model — the inverse of :func:`render_rpt`, so
    ``parse_rpt(render_rpt(r)) == r``. A missing fence, a wrong
    ``cdmon-report-version``, or any structural error raises a typed
    :class:`ConfigError`.
    """
    fm, body = _split_rpt(text)
    version = fm.get("cdmon-report-version")
    if version != CDMON_REPORT_VERSION:
        raise ConfigError(
            f"cdmon-report-version must be {CDMON_REPORT_VERSION!r}, got {version!r}"
        )

    try:
        data = yaml.safe_load(body) if body.strip() else {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed .rpt body: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Malformed .rpt body: expected a mapping")

    summary_raw = data.get("summary") or {}
    units_raw = data.get("units") or ()
    undoc_raw = data.get("undocumented") or ()

    try:
        summary = RptSummary(
            scanned_files=summary_raw["scanned_files"],
            documented_files=summary_raw["documented_files"],
            waived_files=summary_raw["waived_files"],
            ignored_files=summary_raw["ignored_files"],
            uncovered_files=summary_raw["uncovered_files"],
            percent=_parse_percent(summary_raw.get("percent")),
        )
        units = tuple(
            RptUnit(
                unit=u["unit"],
                file=u["file"],
                scanned=u["scanned"],
                documented=u["documented"],
                percent=_parse_percent(u.get("percent")),
                uncovered=tuple(u.get("uncovered") or ()),
            )
            for u in units_raw
        )
        undoc = tuple(
            RptUndocumented(
                path=e["path"],
                suggested_unit=e.get("suggested_unit"),
                reason=e["reason"],
            )
            for e in undoc_raw
        )
        return CoverageRpt(
            cdmon_report_version=version,
            kind=fm.get("kind", ""),
            repo=fm.get("repo", ""),
            ref=fm.get("ref"),
            summary=summary,
            units=units,
            undocumented=undoc,
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise ConfigError(f"Invalid .rpt structure: {exc}") from exc


def _parse_percent(value: object) -> float | None:
    """Parse a rendered percent back to ``float | None`` (``n/a`` → None)."""
    if value is None or value == "n/a":
        return None
    return float(value)  # type: ignore[arg-type]


def _split_rpt(text: str) -> tuple[dict, str]:
    """Split a leading ``---`` front-matter fence from the body (loud K8)."""
    if not text.startswith("---\n"):
        raise ConfigError(
            "Missing '---' front-matter fence: a .rpt must begin with a "
            "'---\\n ... \\n---\\n' block"
        )
    rest = text[len("---\n") :]
    end = rest.find("\n---\n")
    if end == -1:
        raise ConfigError("Unterminated '---' front-matter fence in .rpt")
    fm_text = rest[:end]
    body = rest[end + len("\n---\n") :]
    try:
        fm = yaml.safe_load(fm_text) if fm_text.strip() else {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed .rpt front matter: {exc}") from exc
    if not isinstance(fm, dict):
        raise ConfigError("Malformed .rpt front matter: expected a mapping")
    return fm, body


def write_rpt(config_dir: Path, text: str) -> None:
    """Write ``text`` to ``config_dir/coverage.rpt`` (loud on OSError, K8).

    Mirrors :func:`config.write_index`: a plain write of already-rendered,
    byte-stable text. Idempotency is the caller's contract (re-rendering an
    unchanged repo yields identical bytes), so a second write is a no-op overwrite.
    """
    target = config_dir / "coverage.rpt"
    try:
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot write report to {target}: {exc}") from exc


def report_repo_root(config_dir: Path, bundle: ConfigBundle) -> Path:
    """Resolve the repo root the report scans, from the config dir + index root.

    Thin re-export of :func:`config._resolve_repo_root` so the CLI need not reach
    into a private helper (the index ``root`` is repo-relative to ``config/cdmon/..``).
    """
    return _resolve_repo_root(config_dir, bundle.index.root)
