"""``cdmon`` command-line interface.

The full SPEC surface: ``init | surface | check | monitor | report | schema``.
``init`` writes a config template; the rest load a config (``--config``, default
``cdmon.yaml``) whose parent directory is the ``config_dir`` paths resolve under.

Exit codes mirror the SPEC: ``check`` exits 1 when drift is present (the warning
signal), ``monitor`` exits 1 when drift *remains* after remediation, both exit 0
when clean. Any :class:`~code_doc_monitor.errors.CodeDocMonitorError` is printed
as a clean one-line message to stderr and turned into a non-zero exit — never a
traceback (K8).
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .build import build as build_twins
from .config import MonitorConfig, load_config, write_template
from .errors import CodeDocMonitorError, SchemaError
from .extract import build_document_surface
from .layout import lint_config, scaffold_doc, stamp_doc_meta
from .manifest import parse_doc
from .monitor import DEFAULT_LOG_PATH, Monitor
from .reviewlog import read_all, select_by_verdict, summarize
from .schema import Verdict, review_record_schema

app = typer.Typer(
    name="cdmon",
    help="Standardized code→documentation drift monitor.",
    no_args_is_help=True,
    add_completion=False,
)

_CONFIG_OPTION = typer.Option(
    Path("cdmon.yaml"),
    "--config",
    help="Path to the cdmon config (YAML or JSON).",
)


def _load(config: Path) -> tuple[MonitorConfig, Path]:
    """Load a config, returning ``(config, config_dir)``; clean error on failure."""
    cfg = load_config(config)
    return cfg, config.parent


@app.callback()
def main() -> None:
    """code-doc-monitor — detect code↔doc drift, remediate, record (cdmon)."""
    # A group-level callback keeps `cdmon` a multi-command app even while only
    # `init` exists; later slices add surface/check/monitor/report/schema.


@app.command()
def init(
    path: Path = typer.Option(
        Path("cdmon.yaml"),
        "--path",
        help="Where to write the config template.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing config file.",
    ),
) -> None:
    """Write a documented config template (refuses to clobber unless --force)."""
    if path.exists() and not force:
        typer.echo(
            f"Refusing to overwrite existing {path}; pass --force to overwrite.",
            err=True,
        )
        raise typer.Exit(code=1)
    write_template(path)
    typer.echo(f"Wrote config template to {path}")


@app.command()
def surface(
    config: Path = _CONFIG_OPTION,
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Dump each document's surface as a JSON list.",
    ),
) -> None:
    """Print each document's id/audience/symbol count (debug)."""
    try:
        cfg, config_dir = _load(config)
        root = config_dir / cfg.root
        surfaces = [build_document_surface(doc, root) for doc in cfg.documents]
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        payload = [
            {
                "doc_id": s.doc_id,
                "audience": s.audience.value,
                "surface_hash": s.surface_hash(),
                "symbols": [sym.model_dump() for sym in s.symbols],
            }
            for s in surfaces
        ]
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    for s in surfaces:
        typer.echo(
            f"{s.doc_id} [{s.audience.value}] — {len(s.symbols)} symbol(s) "
            f"(hash {s.surface_hash()})"
        )


@app.command()
def check(config: Path = _CONFIG_OPTION) -> None:
    """Detect drift; exit 1 when drift is present, 0 when clean (K1)."""
    try:
        cfg, config_dir = _load(config)
        report = Monitor(cfg, config_dir).check()
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(report.summary())
    raise typer.Exit(code=0 if report.ok else 1)


@app.command()
def build(config: Path = _CONFIG_OPTION) -> None:
    """Render every ``html: true`` doc to its derived ``.html`` twin."""
    try:
        cfg, config_dir = _load(config)
        written = build_twins(cfg, config_dir)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for path in written:
        typer.echo(f"wrote {path}")
    typer.echo(f"built {len(written)} HTML twin(s)")


@app.command()
def monitor(
    config: Path = _CONFIG_OPTION,
    apply: bool | None = typer.Option(
        None,
        "--apply/--no-apply",
        help="Auto-apply FIX verdicts (defaults to the config's apply_default).",
    ),
) -> None:
    """Detect -> backend verdict -> record -> (apply) -> recheck.

    Exits 1 when drift remains after remediation, 0 when clean.
    """
    try:
        cfg, config_dir = _load(config)
        result = Monitor(cfg, config_dir).run(apply=apply)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for handled in result.handled:
        applied = " (applied)" if handled.applied else ""
        typer.echo(
            f"{handled.drift.doc_id}: {handled.drift.kind.value} -> "
            f"{handled.result.verdict.value}{applied}"
        )
    if result.remaining:
        typer.echo(f"{len(result.remaining)} drift(s) remaining:", err=True)
        for drift in result.remaining:
            typer.echo(
                f"  {drift.doc_id}: {drift.kind.value} — {drift.detail}", err=True
            )
        raise typer.Exit(code=1)
    typer.echo("clean — no drift remaining")


@app.command()
def report(
    config: Path = _CONFIG_OPTION,
    verdict: str | None = typer.Option(
        None,
        "--verdict",
        help="List the individual records with this verdict (e.g. ESCALATE) "
        "instead of the aggregate summary.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON (records when --verdict is set).",
    ),
) -> None:
    """Summarize the review log, or list records of one verdict (``--verdict``).

    With no ``--verdict`` it prints aggregate counts (by verdict/audience/doc).
    With ``--verdict ESCALATE`` it lists the actual records a human must act on —
    the audit detail counts alone can't give (K5).
    """
    try:
        _cfg, config_dir = _load(config)
        log_path = config_dir / DEFAULT_LOG_PATH
        records = read_all(log_path)
        wanted = _parse_verdict(verdict) if verdict is not None else None
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if wanted is None:
        typer.echo(json.dumps(summarize(records), indent=2, sort_keys=True))
        return

    selected = select_by_verdict(records, wanted)
    if as_json:
        typer.echo(
            json.dumps([r.model_dump() for r in selected], indent=2, sort_keys=True)
        )
        return
    if not selected:
        typer.echo(f"no {wanted.value} records in the review log")
        return
    typer.echo(f"{len(selected)} {wanted.value} record(s):")
    for rec in selected:
        typer.echo(
            f"  {rec.record_id} {rec.doc_id} [{rec.audience.value}] "
            f"{rec.drift_kind} @ {rec.resolved_at}"
        )
        typer.echo(f"      drift: {rec.drift_detail}")
        typer.echo(f"      cause: {rec.cause}")


def _parse_verdict(value: str) -> Verdict:
    """Resolve a ``--verdict`` argument to a :class:`Verdict` (case-insensitive)."""
    try:
        return Verdict(value.upper())
    except ValueError as exc:
        choices = ", ".join(v.value for v in Verdict)
        raise SchemaError(
            f"unknown verdict {value!r} (choose from: {choices})"
        ) from exc


@app.command()
def lint(
    config: Path = _CONFIG_OPTION,
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Stamp missing static front matter (schema_version/audience).",
    ),
) -> None:
    """Validate doc *structure* against the Layout Standard (exit 1 on issues).

    Orthogonal to ``check`` (which grades *content*): run both in CI. ``--fix``
    repairs front-matter issues; structural issues (title/purpose/regions/html)
    still need authoring and are reported as remaining.
    """
    try:
        cfg, config_dir = _load(config)
        if fix:
            root = config_dir / cfg.root
            for spec in cfg.documents:
                doc_path = root / spec.path
                if not doc_path.is_file():
                    continue
                doc = parse_doc(doc_path)
                fixed = stamp_doc_meta(doc, spec)
                if fixed != doc.raw:
                    doc_path.write_text(fixed, encoding="utf-8")
                    typer.echo(f"fixed front matter: {spec.path}")
        issues = lint_config(cfg, config_dir)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not issues:
        typer.echo("clean — every document conforms to the Layout Standard")
        return
    typer.echo(f"{len(issues)} layout issue(s):", err=True)
    for issue in issues:
        typer.echo(
            f"  {issue.doc_id} ({issue.doc_path}): {issue.code.value} — {issue.detail}",
            err=True,
        )
    raise typer.Exit(code=1)


@app.command(name="new-doc")
def new_doc(
    doc_id: str = typer.Argument(..., help="The document id from the config."),
    config: Path = _CONFIG_OPTION,
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing doc file."
    ),
) -> None:
    """Scaffold a conformant, in-sync Markdown document for ``doc_id``."""
    try:
        cfg, config_dir = _load(config)
        spec = next((d for d in cfg.documents if d.id == doc_id), None)
        if spec is None:
            ids = ", ".join(d.id for d in cfg.documents)
            typer.echo(
                f"error: no document with id {doc_id!r} in the config (have: {ids})",
                err=True,
            )
            raise typer.Exit(code=1)
        root = config_dir / cfg.root
        doc_path = root / spec.path
        if doc_path.exists() and not force:
            typer.echo(
                f"Refusing to overwrite existing {spec.path}; pass --force.", err=True
            )
            raise typer.Exit(code=1)
        surface = build_document_surface(spec, root)
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(scaffold_doc(spec, surface), encoding="utf-8")
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Wrote conformant doc scaffold to {spec.path}")


@app.command()
def schema(
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write the schema to this file instead of stdout.",
    ),
) -> None:
    """Emit the public review-record JSON schema (one source of truth, K6)."""
    text = json.dumps(review_record_schema(), indent=2, sort_keys=True)
    if out is not None:
        out.write_text(text + "\n", encoding="utf-8")
        typer.echo(f"Wrote review-record schema to {out}")
        return
    typer.echo(text)


if __name__ == "__main__":
    # So `python -m code_doc_monitor.cli ...` runs the app (not a silent no-op);
    # the installed `cdmon` console script uses the `app` entry point directly.
    app()
