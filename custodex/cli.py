"""``cdx`` command-line interface.

The full SPEC surface: ``init | surface | check | monitor | report | coverage |
schema``.
``init`` writes a config template; the rest load a config whose parent directory
is the ``config_dir`` paths resolve under. With no ``--config`` the loader
auto-detects the canonical CONFIG-V2 ``config/cdmon/`` dir layout; the single
``cdmon.yaml``/``.json`` file (the ``--config`` default name) is the supported
back-compat path (``load_config``) and still wins when present.

Exit codes mirror the SPEC: ``check`` exits 1 when drift is present (the warning
signal), ``monitor`` exits 1 when drift *remains* after remediation, both exit 0
when clean. Any :class:`~custodex.errors.CodeDocMonitorError` is printed
as a clean one-line message to stderr and turned into a non-zero exit — never a
traceback (K8).
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from . import coverage as coverage_mod
from . import inventory
from .build import build as build_twins
from .config import (
    DEFAULT_CENTRAL_TOKEN_ENV,
    MonitorConfig,
    central_config_template,
    load_bundle,
    load_config,
    load_config_dir,
    regenerate_index,
    resolve_repo_root,
    write_index,
    write_template,
)
from .docdeps import (
    InferredEdge,
    SuspectLink,
    detect_suspect_links,
    impacted_by,
    infer_edges_from_links,
    propagate_suspect,
    render_deps_text,
    render_impact_text,
    stamp_edges,
)
from .docstyle import DocStyleMap
from .doctor import CheckStatus, run_checks
from .drift import DriftKind
from .entities import corpus_entities, render_entities_text
from .errors import CodeDocMonitorError, SchemaError
from .extract import build_document_surface
from .featurecatalog import load_catalog
from .issues import (
    GitHubIssueTransport,
    GitLabIssueTransport,
    open_coverage_issue,
    plan_coverage_issue,
)
from .layout import (
    config_region_states,
    lint_config,
    scaffold_doc,
    stamp_doc_meta,
)
from .manifest import parse_doc
from .monitor import DEFAULT_LOG_PATH, Monitor
from .ownership import (
    OwnershipStatus,
    detect_orphans,
    load_roster,
    render_ownership_text,
    resolve_ownership,
)
from .pr import GitLabTransport, open_docs_pr
from .promotion import detect_promotions
from .registry import register_repo, repo_identity_from_config, sync_repo_remote
from .report import (
    build_coverage_rpt,
    render_rpt,
    report_repo_root,
    write_rpt,
)
from .reviewlog import (
    DEFAULT_RESOLUTIONS_PATH,
    append_resolution,
    read_all,
    read_resolutions,
    select_by_verdict,
    summarize,
    summarize_with_resolutions,
)
from .schema import Resolution, ResolutionRecord, Verdict, review_record_schema
from .settings import Settings, resolve_settings, secret_presence
from .staleness import (
    StalenessStatus,
    detect_stale,
    render_staleness_text,
    reviewed_docs_from_config,
)
from .syncpr import should_sync, sync_pr
from .templates_v2 import scaffold_config_dir
from .traceability import TraceMatrix, build_matrix
from .worklist import render_worklist_text, worklist_from_repo

app = typer.Typer(
    name="cdx",
    help="Custodex — keeps your code and docs in sync, owned, and accountable.",
    no_args_is_help=True,
    add_completion=False,
)

_CONFIG_OPTION = typer.Option(
    Path("cdmon.yaml"),
    "--config",
    help="Path to the cdx config (YAML or JSON).",
)


def _now() -> str:
    """Injectable wall-clock seam (ISO-8601 UTC) for ``resolve`` timestamps (K10).

    Mirrors ``monitor._default_now``; tests monkeypatch this module attribute to make
    ``resolved_at`` deterministic.
    """
    return datetime.now(timezone.utc).isoformat()


# A frontmatter ``updated:`` line (the only wall-clock-driven field in a
# regenerated index). Blanked before the ``index --check`` comparison so a pure
# timestamp delta is NOT drift (N-06, K1).
_UPDATED_LINE_RE = re.compile(r"^updated:[^\n]*$", re.MULTILINE)


def _blank_updated(text: str) -> str:
    """Return ``text`` with every frontmatter ``updated:`` line value blanked.

    ``index --check`` regenerates the index — which always refreshes the
    ``updated:`` wall-clock stamp via the injected seam — and compares it to the
    on-disk file. Blanking the ``updated:`` value on BOTH sides makes the
    comparison insensitive to a pure timestamp change, so only a real units-list
    change reads as drift (N-06).
    """
    return _UPDATED_LINE_RE.sub("updated:", text)


def _resolve_config(config: Path) -> tuple[MonitorConfig, Path]:
    """Resolve a config to ``(config, config_dir)``, auto-detecting the layout.

    The CONFIG-V2 dir layout wins when ``config`` is itself a directory OR a
    ``config/cdmon/index.yaml`` exists relative to cwd (CONFIG-V2 §0); the merged
    :class:`MonitorConfig` then resolves doc/code paths under
    ``config_dir / cfg.root`` exactly like the single-file path (here ``root``
    defaults to ``".."`` so the repo root is ``config/cdmon/..``). Otherwise the
    single-file :func:`load_config` path is used unchanged — no existing behavior
    or default (``--config cdmon.yaml``) regresses.
    """
    if config.is_dir():
        return load_config_dir(config), config
    # An explicitly-pointed-at existing single file always wins (back-compat):
    # auto-detect only kicks in when no such file is present at ``--config``.
    if not config.is_file():
        auto_dir = Path("config") / "cdmon"
        if (auto_dir / "index.yaml").is_file():
            return load_config_dir(auto_dir), auto_dir
    return load_config(config), config.parent


def _load(config: Path) -> tuple[MonitorConfig, Path]:
    """Load a config, returning ``(config, config_dir)``; clean error on failure."""
    return _resolve_config(config)


def _doc_style_for(config_dir: Path) -> DocStyleMap | None:
    """Return the writing-template map for a dir-layout config, else None (N-05).

    A single-file config has no ``doc-style.yaml`` seam, so this returns None
    there. For a ``config/cdmon/`` directory it reuses :func:`load_bundle` (the
    one loader that resolves the doc-style pointer + templates_root) and lifts
    its ``doc_style``. None ⇒ the monitor run is byte-identical to today (K6).
    """
    if not (config_dir / "index.yaml").is_file():
        return None
    return load_bundle(config_dir).doc_style


def _unit_owner_map(config_dir: Path) -> dict[str, str]:
    """``doc_id`` → its unit-frontmatter owner for a dir-layout config (EPIC OWN).

    The per-document ownership fallback: a doc that declares no owner of its own
    inherits its unit's frontmatter owner. A single-file config has no units, so
    this is empty there (no fallback).
    """
    if not (config_dir / "index.yaml").is_file():
        return {}
    bundle = load_bundle(config_dir)
    return {
        doc.id: unit.frontmatter.owner
        for unit in bundle.units
        for doc in unit.documents
    }


@app.callback()
def main() -> None:
    """custodex — detect code↔doc drift, remediate, record (cdx)."""
    # A group-level callback keeps `cdx` a multi-command app even while only
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
    central: str | None = typer.Option(
        None,
        "--central",
        metavar="URL",
        help="Wire `central:` for HTTP reporting to this central-server URL "
        "(sink=http). Without it, the offline template is written unchanged.",
    ),
    repo_id: str | None = typer.Option(
        None,
        "--repo-id",
        help="Stable repo identifier the central system keys on (required for "
        "--central; defaults to the current directory name).",
    ),
    token_env: str = typer.Option(
        DEFAULT_CENTRAL_TOKEN_ENV,
        "--token-env",
        metavar="VAR",
        help="Env var the HTTP sink reads the central bearer token from "
        f"(default {DEFAULT_CENTRAL_TOKEN_ENV}).",
    ),
    repo_url: str | None = typer.Option(
        None,
        "--repo-url",
        help="This repo's clone/browse URL, recorded on each reported record "
        "(only with --central).",
    ),
    v2: bool = typer.Option(
        False,
        "--v2",
        help="Scaffold the multi-file config/cdmon/ layout (index + example unit "
        "+ ignore + doc-style) instead of the single-file template.",
    ),
    config_dir: Path = typer.Option(
        Path("config") / "cdmon",
        "--config-dir",
        help="Where to scaffold the config/cdmon/ directory (only with --v2).",
    ),
    repo: str | None = typer.Option(
        None,
        "--repo",
        help="Repo id/name written into the scaffolded index.yaml (only with "
        "--v2; defaults to the current directory name).",
    ),
) -> None:
    """Write a documented config template (refuses to clobber unless --force).

    WITHOUT ``--central`` the offline starter template is written byte-for-byte.
    WITH ``--central URL`` the ``central:`` block is wired for HTTP reporting
    (``sink: http`` + url + repo_id + auth_env + outbox) — ready to
    ``cdx register`` and report; ``--repo-id`` defaults to the current directory
    name. The written config round-trips through ``load_config`` and satisfies the
    HTTP sink's requirements.

    WITH ``--v2`` the multi-file ``config/cdmon/`` layout is scaffolded instead
    (``--config-dir``, default ``config/cdmon``): an ``index.yaml``, one example
    unit, ``ignore.yaml``, and ``doc-style.yaml``, all from the canonical
    templates and ready for ``load_bundle`` / ``cdx check``. It refuses to
    clobber an existing directory unless ``--force`` (loud, K8).
    """
    if v2:
        if config_dir.exists() and not force:
            typer.echo(
                f"Refusing to overwrite existing {config_dir}; pass --force to "
                "overwrite.",
                err=True,
            )
            raise typer.Exit(code=1)
        resolved_repo = repo or Path.cwd().name or "your-repo"
        scaffold_config_dir(config_dir, repo=resolved_repo, now=_now())
        typer.echo(
            f"Scaffolded config/cdmon layout in {config_dir} (repo={resolved_repo})"
        )
        return

    if path.exists() and not force:
        typer.echo(
            f"Refusing to overwrite existing {path}; pass --force to overwrite.",
            err=True,
        )
        raise typer.Exit(code=1)

    if central is None:
        write_template(path)
        typer.echo(f"Wrote config template to {path}")
        return

    resolved_repo_id = repo_id or Path.cwd().name
    if not resolved_repo_id:
        typer.echo(
            "error: --central needs a --repo-id (could not derive one from the "
            "current directory)",
            err=True,
        )
        raise typer.Exit(code=1)
    write_template(
        path,
        central_config_template(
            url=central,
            repo_id=resolved_repo_id,
            token_env=token_env,
            repo_url=repo_url,
        ),
    )
    typer.echo(
        f"Wrote central-reporting config to {path} "
        f"(repo_id={resolved_repo_id}, token env ${token_env})"
    )


@app.command()
def index(
    config_dir: Path = typer.Option(
        Path("config") / "cdmon",
        "--config-dir",
        help="The config/cdmon directory whose index.yaml to regenerate.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Read-only: exit 1 if the on-disk index differs from a freshly "
        "regenerated one (CI gate), 0 when in sync. Writes nothing.",
    ),
) -> None:
    """Regenerate ``index.yaml``'s ``units:`` from the on-disk unit files.

    The unit list is rebuilt (sorted alphabetically) to list every ``*.yaml`` unit
    present in the directory, the frontmatter ``updated`` is refreshed, and every
    global is preserved. Default mode rewrites the file and reports the change;
    ``--check`` is read-only (K1) and exits 1 on drift after printing a diff,
    making it a CI guard against an out-of-sync index. The check ignores the
    frontmatter ``updated:`` timestamp (which the regenerate always refreshes), so
    only a real units-list change reads as drift — a pure timestamp delta is in
    sync (N-06). Idempotent (K7).
    """
    try:
        new_text = regenerate_index(config_dir)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    index_path = config_dir / "index.yaml"
    current = index_path.read_text(encoding="utf-8")

    if check:
        # N-06 (K1): the on-disk and regenerated frontmatter ``updated:`` lines
        # ALWAYS differ (regenerate_index refreshes the wall-clock stamp), so a
        # pure timestamp delta must NOT read as drift. Compare with both
        # ``updated:`` values blanked — only a REAL units-list change then exits 1.
        if _blank_updated(current) == _blank_updated(new_text):
            typer.echo(f"{index_path}: in sync")
            raise typer.Exit(code=0)
        diff = difflib.unified_diff(
            current.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"{index_path} (on disk)",
            tofile=f"{index_path} (regenerated)",
        )
        typer.echo("".join(diff), nl=False)
        typer.echo(
            f"{index_path}: OUT OF SYNC — run `cdx index` to regenerate", err=True
        )
        raise typer.Exit(code=1)

    if current == new_text:
        typer.echo(f"{index_path}: already in sync (no change)")
        return
    try:
        write_index(config_dir, new_text)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"{index_path}: regenerated")


@app.command()
def rpt(
    config_dir: Path = typer.Option(
        Path("config") / "cdmon",
        "--config-dir",
        help="The config/cdmon directory to build the coverage report from.",
    ),
    write: bool = typer.Option(
        False,
        "--write",
        help="Write config/cdmon/coverage.rpt (idempotent, K7). Default prints "
        "to stdout and writes nothing (read-only, K1).",
    ),
    ref: str | None = typer.Option(
        None,
        "--ref",
        help="Branch/commit the report reflects (provenance, stamped in the "
        "frontmatter). Left null when omitted; a later sync slice fills it.",
    ),
) -> None:
    """Compute the dir-layout coverage report; print it, or --write coverage.rpt.

    Reuses the real coverage engine (effective_coverage → discover_files →
    discover_symbols → resolve_coverage) and renders a YAML-with-frontmatter
    report: a repo-wide ``summary``, a per-``units`` breakdown, and an
    ``undocumented`` list naming each gap file's ``suggested_unit``. Read-only by
    default (K1); ``--write`` writes ``config/cdmon/coverage.rpt`` deterministically
    (no wall-clock in the file, so a re-run with no change is byte-identical — K7).
    """
    try:
        bundle = load_bundle(config_dir)
        repo_root = report_repo_root(config_dir, bundle)
        coverage_rpt = build_coverage_rpt(bundle, repo_root, ref=ref)
        text = render_rpt(coverage_rpt)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if write:
        try:
            write_rpt(config_dir, text)
        except CodeDocMonitorError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"{config_dir / 'coverage.rpt'}: wrote coverage report")
        return

    typer.echo(text, nl=False)


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
                "surface_hash": s.surface_hash(include_body=cfg.fingerprint_body_tier),
                "symbols": [sym.model_dump() for sym in s.symbols],
            }
            for s in surfaces
        ]
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    for s in surfaces:
        typer.echo(
            f"{s.doc_id} [{s.audience.value}] — {len(s.symbols)} symbol(s) "
            f"(hash {s.surface_hash(include_body=cfg.fingerprint_body_tier)})"
        )


@app.command()
def check(config: Path = _CONFIG_OPTION) -> None:
    """Detect drift; exit 1 when drift is present, 0 when clean (K1).

    A ``SUSPECT_LINK`` (doc↔doc) drift is always REPORTED, but whether it counts
    toward the nonzero exit is the ``docdeps.gate`` config knob (default: gates,
    unlike Doorstop which exits 0 on a suspect link). Code↔doc drift always gates.
    """
    try:
        cfg, config_dir = _load(config)
        report = Monitor(cfg, config_dir).check()
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(report.summary())
    gating = [
        d
        for d in report.drifts
        if d.kind is not DriftKind.SUSPECT_LINK or cfg.docdeps.gate
    ]
    raise typer.Exit(code=1 if gating else 0)


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
    ref: str | None = typer.Option(
        None,
        "--ref",
        "--source-sha",
        help="Source code ref/commit to stamp on every review record "
        "(provenance, C-05). Precedence: this flag, else $CI_COMMIT_SHA, else "
        "none. The same ref can flow to `open-docs-pr --ref` (one source of truth).",
    ),
) -> None:
    """Detect -> backend verdict -> record -> (apply) -> recheck.

    Exits 1 when drift remains after remediation, 0 when clean. Each review
    record carries a ``source_sha`` provenance stamp: ``--ref``/``--source-sha``
    wins, else ``$CI_COMMIT_SHA``, else none (C-05).
    """
    try:
        cfg, config_dir = _load(config)
        source_sha = ref if ref is not None else os.environ.get("CI_COMMIT_SHA")
        result = Monitor(
            cfg,
            config_dir,
            source_sha=source_sha,
            doc_style=_doc_style_for(config_dir),
        ).run(apply=apply)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for handled in result.handled:
        applied = " (applied)" if handled.applied else ""
        typer.echo(
            f"{handled.drift.doc_id}: {handled.drift.kind.value} -> "
            f"{handled.result.verdict.value}{applied}"
        )
    # PROP-01: opt-in transitive-suspect advisory — purely informational, never
    # affects the exit code (the gate stays the direct wavefront, K1/K7). Guarded so a
    # doc mutated between the run and here cannot turn a clean exit into a traceback.
    if cfg.docdeps.transitive:
        advisory: tuple[SuspectLink, ...] = ()
        try:
            root = resolve_repo_root(config_dir, cfg.root)
            advisory = propagate_suspect(cfg, detect_suspect_links(cfg, root))
        except CodeDocMonitorError as exc:
            typer.echo(f"advisory unavailable: {exc}", err=True)
        if advisory:
            n_docs = len({link.doc_id for link in advisory})
            typer.echo(
                f"advisory: {len(advisory)} edge(s) across {n_docs} document(s) "
                "transitively suspect (pending wavefront; does not gate). "
                "Run `cdx deps --transitive` for detail."
            )
    if result.remaining:
        typer.echo(f"{len(result.remaining)} drift(s) remaining:", err=True)
        for drift in result.remaining:
            typer.echo(
                f"  {drift.doc_id}: {drift.kind.value} — {drift.detail}", err=True
            )
        raise typer.Exit(code=1)
    typer.echo("clean — no drift remaining")


@app.command(name="sync-pr")
def sync_pr_cmd(
    config: Path = _CONFIG_OPTION,
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write the unified-diff patch to this file instead of stdout.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute the patch WITHOUT mutating the working tree (K1).",
    ),
) -> None:
    """Heal the docs and emit a unified diff (patch) of exactly the changed docs.

    Default: applies the heal and prints the patch (or writes it to ``--out``),
    with a one-line summary to stderr; exit 0. ``--dry-run`` computes the SAME
    patch but leaves the working tree byte-identical (the file producer C-03 turns
    into a docs MR). A clean repo (or a second run after an apply) emits an empty
    patch (idempotent, K7). Offline + deterministic (mock backend default, K4/K10).
    """
    try:
        cfg, config_dir = _load(config)
        result = sync_pr(Monitor(cfg, config_dir), dry_run=dry_run)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if out is not None:
        out.write_text(result.patch, encoding="utf-8")
        typer.echo(f"wrote patch to {out}", err=True)
    else:
        typer.echo(result.patch, nl=False)
    typer.echo(result.summary, err=True)


@app.command(name="should-sync")
def should_sync_cmd(
    files: list[str] = typer.Argument(
        None,
        metavar="[FILES...]",
        help="Changed file paths to test. If omitted, read newline-separated "
        "paths from stdin (e.g. `git diff --name-only | cdx should-sync`).",
    ),
    config: Path = _CONFIG_OPTION,
) -> None:
    """Loop-safety guard (C-04): exit 0 to PROCEED with a heal, 1 to SKIP.

    Exits 0 when at least one changed file is NOT a managed doc path (a real code
    change → heal), 1 when every changed file is a managed doc (a bot doc-only
    commit) or the set is empty (nothing to do). Pure + read-only (K1); the CI
    heal job uses it so a doc-only commit does NOT re-trigger the heal loop.
    """
    try:
        cfg, _config_dir = _load(config)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    changed = files if files else [ln.strip() for ln in sys.stdin if ln.strip()]
    proceed = should_sync(changed, cfg)
    raise typer.Exit(code=0 if proceed else 1)


class _NullTransport:
    """A transport that is never submitted to (used only on the --dry-run path).

    ``open_docs_pr(dry_run=True)`` returns the plan without calling ``submit``, so
    no real transport need be built (and no env is required) for a dry run.
    """

    def submit(self, plan: object) -> dict:  # pragma: no cover - never called
        raise AssertionError("dry-run transport must not be submitted to")


_NULL_TRANSPORT = _NullTransport()


@app.command(name="open-docs-pr")
def open_docs_pr_cmd(
    config: Path = _CONFIG_OPTION,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute + print the MR plan WITHOUT mutating the tree or opening an "
        "MR (uses a dry sync, so NOTHING is written, and never builds a transport).",
    ),
    target: str = typer.Option(
        "main",
        "--target",
        help="The MR target branch (default 'main').",
    ),
    ref: str | None = typer.Option(
        None,
        "--ref",
        help="Source ref to record in the MR title/description (provenance).",
    ),
) -> None:
    """Heal the docs and open a docs merge request via the default GitLab transport.

    Heals the docs (``sync-pr``), then turns the resulting patch into a branch +
    commit + MR. A clean repo (empty sync) is a no-op: prints "clean — nothing to
    open" and exits 0 (no transport built, no MR). ``--dry-run`` computes the SAME
    plan from a DRY sync (so the working tree is left byte-identical, K1) and prints
    it as JSON WITHOUT building or calling a transport. Otherwise the default
    :class:`~custodex.pr.GitLabTransport` is built from the CI environment
    (loud K8 error if a required env var is missing) and the MR is opened. Offline
    + deterministic in --dry-run (mock backend default, K4/K10).
    """
    try:
        cfg, config_dir = _load(config)
        root = config_dir / cfg.root
        result = sync_pr(Monitor(cfg, config_dir), dry_run=dry_run)
        if not result.patch:
            typer.echo("clean — nothing to open")
            return
        if dry_run:
            plan = open_docs_pr(
                result,
                root,
                transport=_NULL_TRANSPORT,
                dry_run=True,
                target_branch=target,
                ref=ref,
            )
            typer.echo(json.dumps(plan, indent=2, sort_keys=True))
            return
        transport = GitLabTransport.from_env()
        response = open_docs_pr(
            result,
            root,
            transport=transport,
            target_branch=target,
            ref=ref,
        )
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    web_url = response.get("web_url") if isinstance(response, dict) else None
    typer.echo(f"opened docs MR: {web_url}" if web_url else "opened docs MR")


@app.command()
def register(
    config: Path = _CONFIG_OPTION,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the registration payload as JSON WITHOUT calling the server "
        "(no url/token required).",
    ),
) -> None:
    """Announce this repo to the central server (POST its identity to /repos, E-02).

    Builds a :class:`~custodex.sinks.RepoIdentity` from the central config
    (loud K8 if ``central.repo_id`` is missing) and POSTs a versioned
    :class:`~custodex.registry.RegistrationPayload` to ``<central url>/repos``
    via the default stdlib transport (bearer from ``central.auth_env``; loud K8 if
    ``central.url`` is missing). ``--dry-run`` prints the payload it WOULD send and
    makes no network call (K4) — handy to inspect identity/commit before wiring up
    the server.
    """
    try:
        cfg, _config_dir = _load(config)
        identity = repo_identity_from_config(cfg.central)
        response = register_repo(
            identity,
            url=cfg.central.url or "",
            auth_env=cfg.central.auth_env,
            dry_run=dry_run,
        )
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if dry_run:
        typer.echo(json.dumps(response, indent=2, sort_keys=True))
        return
    typer.echo(f"registered {identity.repo_id} with {cfg.central.url}")


def _sync_run_lines(run: dict) -> list[str]:
    """Deterministic, scannable human render of a sync run summary (Y-03, K10).

    Renders the same fields the central server returns — ``fully_synced``, the
    document/code_ref counts, ``commits_ahead``, and the drift summary (count +
    per-kind breakdown + coverage %). Both callers pass a dict: the local path
    feeds ``SyncRun.model_dump(mode="json")`` and the remote path the server's
    JSON, so the local and remote printouts read identically.
    """
    drift = run["drift"] or {}
    status = "fully synced" if run["fully_synced"] else "NOT fully synced"
    lines = [
        f"{run['repo_id']} [{run['sync_kind']}] — {status}",
        f"  documents:    {run['document_count']}",
        f"  code refs:    {run['code_ref_count']}",
        f"  commits ahead: {run['commits_ahead']}",
        f"  drift:        {drift.get('drift_count', 0)} "
        f"(coverage {drift.get('coverage_percent', 0)}%)",
    ]
    by_kind = drift.get("by_kind") or {}
    for kind, count in sorted(by_kind.items()):
        lines.append(f"    {kind}: {count}")
    return lines


@app.command()
def sync(
    mode: str = typer.Option(
        "local",
        "--mode",
        help="Which sync to run: 'local' (the working tree / feature branch) or "
        "'git' (the default branch baseline).",
    ),
    remote: str | None = typer.Option(
        None,
        "--remote",
        metavar="URL",
        help="Central-server URL to POST the sync to. Without it the sync runs "
        "locally and prints the summary (no central access required).",
    ),
    repo_id: str | None = typer.Option(
        None,
        "--repo-id",
        help="Stable repo id. REQUIRED with --remote; for a local sync it "
        "defaults to the bundle's index `repo` field (else the directory name).",
    ),
    token_env: str = typer.Option(
        DEFAULT_CENTRAL_TOKEN_ENV,
        "--token-env",
        metavar="VAR",
        help="Env var the remote bearer token is read from "
        f"(default {DEFAULT_CENTRAL_TOKEN_ENV}).",
    ),
    default_branch: str = typer.Option(
        "main",
        "--default-branch",
        help="The default branch the local sync compares against (commits_ahead).",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit the SyncRun as JSON instead of the human summary.",
    ),
) -> None:
    """Run a config sync — locally (print the summary) or against a --remote server.

    LOCAL (no ``--remote``): runs :func:`custodex.configsync.run_sync`
    READ-ONLY against the current repo (cwd, K1), computing drift + coverage +
    commits-ahead, and prints the run summary (or ``--json``). ``--repo-id``
    defaults to the bundle's index ``repo`` field — read, never invented. Exit 0;
    non-zero only on a loud error (K8). REMOTE (``--remote URL --repo-id ID``):
    POSTs ``{mode}`` to ``<URL>/repos/{ID}/sync`` (bearer from ``--token-env``)
    via the SAME HTTP+auth seam as ``cdx register`` and prints the server's run
    summary. The clock is injected (``_now``) so a local run is deterministic
    (K10).
    """
    from .configsync import run_sync

    if remote is not None:
        if not repo_id:
            typer.echo("error: --remote requires --repo-id", err=True)
            raise typer.Exit(code=1)
        try:
            run = sync_repo_remote(
                repo_id,
                mode=mode,
                url=remote,
                auth_env=token_env,
            )
        except CodeDocMonitorError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        if as_json:
            typer.echo(json.dumps(run, indent=2, sort_keys=True))
            return
        for line in _sync_run_lines(run):
            typer.echo(line)
        return

    cwd = Path.cwd()
    try:
        resolved_repo_id = repo_id
        if resolved_repo_id is None:
            config_dir = cwd / "config" / "cdmon"
            if (config_dir / "index.yaml").is_file():
                resolved_repo_id = load_bundle(config_dir).index.frontmatter.repo
            else:
                resolved_repo_id = cwd.name
        result = run_sync(
            cwd,
            resolved_repo_id,
            mode=mode,
            default_branch=default_branch,
            now=_now(),
        )
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    run = result.run.model_dump(mode="json")
    if as_json:
        typer.echo(json.dumps(run, indent=2, sort_keys=True))
        return
    for line in _sync_run_lines(run):
        typer.echo(line)


@app.command()
def serve(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host/interface to bind the standalone server to.",
    ),
    port: int = typer.Option(
        0,
        "--port",
        help="Port to bind (0 = let the OS pick a free port).",
    ),
    repo_id: str | None = typer.Option(
        None,
        "--repo-id",
        help="Repo id for the standalone view. Defaults to the bundle's index "
        "`repo` field (else the current directory name).",
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Do not open a browser tab (accepted for parity; never auto-opens).",
    ),
) -> None:
    """Serve the dashboard for THIS repo standalone — no central access (L-01).

    Auto-registers ONLY the current repo (``local_path`` = cwd, OPEN — no token),
    pre-syncs it (git + local) so the Documents / relationship / Sync views are
    populated on first load, and launches the SAME FastAPI app + dashboard SPA on
    ``--host``/``--port`` (port 0 = an OS-picked free port). Loud K8 if cwd has no
    ``config/cdmon/index.yaml`` (run ``cdx init --v2`` first). All logic lives in
    the import-safe builders, so this launch is thin (tests never bind a socket).
    """
    repo_root = Path.cwd()
    if not (repo_root / "config" / "cdmon" / "index.yaml").is_file():
        typer.echo(
            f"error: no config/cdmon/index.yaml in {repo_root} — this is not a "
            "config/cdmon repo. Run `cdx init --v2` to scaffold one first.",
            err=True,
        )
        raise typer.Exit(code=1)

    from .server.standalone import build_standalone_app

    try:
        app_obj = build_standalone_app(repo_root, repo_id=repo_id, now=_now())
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _run_uvicorn(app_obj, host=host, port=port)


def _run_uvicorn(  # pragma: no cover — the real socket-binding launch leaf (K4)
    app_obj: Any, *, host: str, port: int
) -> None:
    """Bind the standalone app to a socket and serve it (the thin launch leaf).

    Isolated so :func:`serve`'s logic stays in the import-safe builders and tests
    drive those directly without ever binding a port. Prints the URL once bound.
    """
    import uvicorn

    config = uvicorn.Config(app_obj, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    typer.echo(f"Serving the standalone cdx dashboard on http://{host}:{port}")
    server.run()


@app.command()
def doctor(config: Path = _CONFIG_OPTION) -> None:
    """Offline preflight: is this repo wired to run cdx + report? (G-02).

    Loads the config (a malformed one is a loud K8 error → exit 1), then runs the
    read-only, network-free checks (config / documents / backend prereq / central
    wiring / optional extras) and prints one ``STATUS  name — detail`` line each.
    A merely-absent runtime prereq (no `claude` CLI, unset API key/token, an
    optional extra not installed) is a WARN; only a structurally-broken config
    (e.g. an http sink with no url/repo_id) is a FAIL. Exit 0 unless any FAIL.
    """
    try:
        cfg, config_dir = _load(config)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    checks = run_checks(cfg, config_dir)
    for chk in checks:
        typer.echo(f"{chk.status.value:4}  {chk.name} — {chk.detail}")
    failed = sum(1 for c in checks if c.status is CheckStatus.FAIL)
    if failed:
        typer.echo(f"{failed} check(s) FAILED", err=True)
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


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
        resolutions = read_resolutions(config_dir / DEFAULT_RESOLUTIONS_PATH)
        wanted = _parse_verdict(verdict) if verdict is not None else None
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if wanted is None:
        # Aggregate counts PLUS the D-01/D-02 resolved/unresolved join (additive).
        payload = summarize(records)
        payload.update(summarize_with_resolutions(records, resolutions))
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
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


@app.command()
def promotions(
    config: Path = _CONFIG_OPTION,
    min_count: int = typer.Option(
        3,
        "--min-count",
        help="How many resolved records of one shape must unanimously share a "
        "decision before it is a promotion candidate.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit the candidates as machine-readable JSON.",
    ),
) -> None:
    """List promotion CANDIDATES from the local logs (read-only, D-05).

    A candidate is a GENERALIZABLE shape ``(doc_id, drift_kind, audience)`` whose
    RESOLVED records (>= ``--min-count``) ALL share ONE *decision* resolution
    (``invalidated``/``rejected``). Such a decision can be PROMOTED to a
    deterministic rule so the backend is no longer consulted for it — the cost
    curve bends down as the system learns. ``overridden`` (human prose) and
    ``accepted`` (already LLM-free) are excluded. Pure + read-only (K1/K10).
    """
    try:
        _cfg, config_dir = _load(config)
        records = read_all(config_dir / DEFAULT_LOG_PATH)
        resolutions = read_resolutions(config_dir / DEFAULT_RESOLUTIONS_PATH)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    candidates = detect_promotions(records, resolutions, min_count=min_count)

    if as_json:
        typer.echo(
            json.dumps(
                [c.model_dump(mode="json") for c in candidates],
                indent=2,
                sort_keys=True,
            )
        )
        return

    if not candidates:
        typer.echo(
            f"no promotable shapes (need >= {min_count} unanimous decision "
            "resolutions of one shape)"
        )
        return
    typer.echo(f"{len(candidates)} promotion candidate(s):")
    for c in candidates:
        typer.echo(
            f"  {c.doc_id} [{c.audience.value}] {c.drift_kind} -> "
            f"{c.resolution.value} (x{c.count})"
        )


_DEFAULT_MANIFEST = Path(".cdmon/coverage.json")


@app.command()
def coverage(
    config: Path = _CONFIG_OPTION,
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit the full CoverageReport as round-trippable JSON.",
    ),
    fail_under: float | None = typer.Option(
        None,
        "--fail-under",
        help="Exit 1 if public-symbol coverage is below this percent "
        "(informational — always exits 0 — when omitted).",
    ),
    write: bool = typer.Option(
        False,
        "--write",
        help="Write a deterministic coverage manifest (payload + owner "
        f"suggestions) to PATH (default {_DEFAULT_MANIFEST}); idempotent (K7).",
    ),
    manifest_path: Path | None = typer.Argument(
        None,
        metavar="[PATH]",
        help=f"Manifest destination for --write (default {_DEFAULT_MANIFEST}).",
    ),
) -> None:
    """Report doc coverage: file/public-symbol percentages + the three baskets.

    Read-only by default (K1): scans ``coverage.include``/``exclude``, crosses the
    inventory against the documents' code refs, and prints what is documented, the
    undocumented gaps, and the waived items (with reasons). ``--json`` dumps the
    whole :class:`~custodex.coverage.CoverageReport`. ``--fail-under N``
    turns it into a gate (exit 1 when ``percent_public_symbols < N``); without it
    the command is informational like ``report`` and always exits 0.

    ``--write [PATH]`` (A-08) is the one mutating mode: it writes a deterministic
    manifest (the JSON payload PLUS the A-07 owner suggestions) to ``PATH``
    (default ``.cdmon/coverage.json``). Idempotent (K7): if the existing manifest
    already equals the new content it is not rewritten and prints "coverage
    manifest unchanged"; otherwise it writes and prints the path. ``--write``
    composes with ``--json``/``--fail-under`` (those govern stdout/exit only).
    """
    try:
        cfg, config_dir = _load(config)
        root = config_dir / cfg.root
        inv = inventory.discover_files(
            root,
            include=cfg.coverage.include,
            exclude=cfg.coverage.exclude,
        )
        sym = inventory.discover_symbols(inv, root)
        report = coverage_mod.resolve_coverage(cfg, sym)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if write:
        target = manifest_path if manifest_path is not None else _DEFAULT_MANIFEST
        changed = _write_coverage_manifest(report, cfg, target)
        if changed:
            typer.echo(f"wrote coverage manifest to {target}")
        else:
            typer.echo("coverage manifest unchanged")

    if json_out:
        typer.echo(json.dumps(_coverage_payload(report), indent=2, sort_keys=True))
    else:
        for line in _coverage_lines(report):
            typer.echo(line)

    if fail_under is not None and report.percent_public_symbols < fail_under:
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


def _coverage_manifest_text(
    report: coverage_mod.CoverageReport, config: MonitorConfig
) -> str:
    """Deterministic manifest text = A-05 payload + A-07 suggestions (K10).

    Stable formatting (sorted keys, fixed indent, trailing newline) so a re-run
    with no source change produces byte-identical content (the K7 idempotency
    invariant the writer relies on).
    """
    payload = _coverage_payload(report)
    payload["suggestions"] = [
        s.model_dump(mode="json") for s in coverage_mod.suggest_owners(report, config)
    ]
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _write_coverage_manifest(
    report: coverage_mod.CoverageReport, config: MonitorConfig, target: Path
) -> bool:
    """Write the manifest to ``target``; return ``True`` only if it changed (K7).

    Mirrors :func:`heal.regenerate_regions`' changed/unchanged contract: the
    existing file is read first and the write is skipped when the content is
    already identical, so a second ``--write`` with no source change rewrites
    nothing (idempotent — K7).
    """
    new_text = _coverage_manifest_text(report, config)
    if target.is_file() and target.read_text(encoding="utf-8") == new_text:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_text, encoding="utf-8")
    return True


def _coverage_payload(report: coverage_mod.CoverageReport) -> dict[str, object]:
    """Round-trippable JSON view of a report: the lossless model plus the baskets.

    ``model_dump`` carries every file/symbol losslessly; the derived baskets and
    percentages (pydantic ``@property``, not dumped) are added explicitly so a
    consumer can read a gate metric without recomputing it.
    """
    payload: dict[str, object] = report.model_dump(mode="json")
    payload["percent_files"] = report.percent_files
    payload["percent_public_symbols"] = report.percent_public_symbols
    payload["undocumented_symbols"] = [
        s.model_dump(mode="json") for s in report.undocumented_symbols
    ]
    payload["waived_symbols"] = [
        s.model_dump(mode="json") for s in report.waived_symbols
    ]
    payload["undocumented_files"] = [
        f.model_dump(mode="json") for f in report.undocumented_files
    ]
    payload["waived_files"] = [f.model_dump(mode="json") for f in report.waived_files]
    return payload


def _coverage_lines(report: coverage_mod.CoverageReport) -> list[str]:
    """Deterministic, scannable human render of a coverage report (K10)."""
    docd_files = report.documented_files
    gap_files = report.undocumented_files
    waived_files = report.waived_files
    docd_sym = report.documented_symbols
    gap_sym = report.undocumented_symbols
    waived_sym = report.waived_symbols

    lines = [
        f"files: {report.percent_files:.1f}% documented "
        f"({len(docd_files)}/{len(docd_files) + len(gap_files)})",
        f"public symbols: {report.percent_public_symbols:.1f}% documented "
        f"({len(docd_sym)}/{len(docd_sym) + len(gap_sym)})",
        "",
        f"documented {len(docd_sym)} public symbol(s)",
        f"undocumented {len(gap_sym)} public symbol gap(s):",
    ]
    lines.extend(f"  {s.path}::{s.name} ({s.kind})" for s in gap_sym)
    lines.append(f"waived {len(waived_sym)} public symbol(s):")
    lines.extend(f"  {s.path}::{s.name} — {s.waived_reason}" for s in waived_sym)
    if gap_files:
        lines.append(f"undocumented {len(gap_files)} file(s):")
        lines.extend(f"  {f.path}" for f in gap_files)
    if waived_files:
        lines.append(f"waived {len(waived_files)} file(s):")
        lines.extend(f"  {f.path} — {f.waived_reason}" for f in waived_files)
    return lines


@app.command(name="surface-gaps")
def surface_gaps(
    config: Path = _CONFIG_OPTION,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute + print the issue plan WITHOUT opening an issue (never builds "
        "a transport, so no provider env is required).",
    ),
    provider: str = typer.Option(
        "gitlab",
        "--provider",
        help="Issue tracker to open the coverage-gap issue on (gitlab | github).",
    ),
) -> None:
    """Turn doc coverage gaps into a tracker issue (H-04; injected transport, K4).

    Runs discover→``resolve_coverage``→``suggest_owners``, then builds a
    deterministic :class:`~custodex.issues.IssuePlan` listing every
    undocumented public symbol grouped by its suggested owner (A-07). NO gaps is a
    no-op: prints "no coverage gaps" and exits 0 (no transport built). ``--dry-run``
    prints the plan as JSON WITHOUT building or calling a transport. Otherwise the
    provider transport is built from the CI environment (loud K8 error if a required
    env var is missing) and the issue is opened. Offline + deterministic in
    --dry-run (K4/K10).
    """
    try:
        cfg, config_dir = _load(config)
        root = config_dir / cfg.root
        inv = inventory.discover_files(
            root,
            include=cfg.coverage.include,
            exclude=cfg.coverage.exclude,
        )
        sym = inventory.discover_symbols(inv, root)
        report = coverage_mod.resolve_coverage(cfg, sym)
        suggestions = coverage_mod.suggest_owners(report, cfg)
        plan = plan_coverage_issue(report, suggestions)
        if plan is None:
            typer.echo("no coverage gaps — nothing to surface")
            return
        if dry_run:
            out = open_coverage_issue(
                report, suggestions, transport=_NULL_TRANSPORT, dry_run=True
            )
            typer.echo(json.dumps(out, indent=2, sort_keys=True))
            return
        transport = _issue_transport(provider)
        response = open_coverage_issue(report, suggestions, transport=transport)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    web_url = None
    if isinstance(response, dict):
        web_url = response.get("web_url") or response.get("html_url")
    typer.echo(f"opened coverage-gap issue: {web_url}" if web_url else "opened issue")


def _issue_transport(provider: str) -> GitLabIssueTransport | GitHubIssueTransport:
    """Build the provider issue transport from CI env (loud K8 on a bad provider)."""
    key = provider.lower()
    if key == "gitlab":
        return GitLabIssueTransport.from_env()
    if key == "github":
        return GitHubIssueTransport.from_env()
    raise SchemaError(f"unknown --provider {provider!r} (choose from: gitlab, github)")


def _parse_verdict(value: str) -> Verdict:
    """Resolve a ``--verdict`` argument to a :class:`Verdict` (case-insensitive)."""
    try:
        return Verdict(value.upper())
    except ValueError as exc:
        choices = ", ".join(v.value for v in Verdict)
        raise SchemaError(
            f"unknown verdict {value!r} (choose from: {choices})"
        ) from exc


def _parse_resolution(value: str) -> Resolution:
    """Resolve a ``--resolution`` argument to a :class:`Resolution` (lower-cased)."""
    try:
        return Resolution(value.lower())
    except ValueError as exc:
        choices = ", ".join(r.value for r in Resolution)
        raise SchemaError(
            f"unknown resolution {value!r} (choose from: {choices})"
        ) from exc


@app.command()
def resolve(
    record_id: str | None = typer.Argument(
        None, help="The ReviewRecord id to record an outcome for."
    ),
    resolution: str | None = typer.Option(
        None,
        "--resolution",
        help="The human outcome: accepted | overridden | rejected | invalidated.",
    ),
    edge: tuple[str, str] | None = typer.Option(
        None,
        "--edge",
        help="DOWNSTREAM UPSTREAM: re-confirm one doc↔doc edge after reviewing it "
        "(the per-edge ack — re-stamps just that edge's baseline, EPIC B). Use "
        "instead of a record_id.",
    ),
    by: str | None = typer.Option(
        None, "--by", help="Who resolved it (stored as resolved_by)."
    ),
    text: str | None = typer.Option(
        None,
        "--text",
        help="The human's final body when --resolution overridden (resolved_text).",
    ),
    note: str | None = typer.Option(
        None, "--note", help="A free-text note attached to the outcome."
    ),
    config: Path = _CONFIG_OPTION,
    log: Path | None = typer.Option(
        None,
        "--log",
        help="Resolutions log path (default .cdmon/resolutions.jsonl alongside "
        "the review log).",
    ),
) -> None:
    """Record the human OUTCOME of a handled drift as a separate append-only event.

    Two modes. With ``--edge DOWN UP`` (EPIC B): re-stamp exactly that one doc↔doc
    edge's baseline after a human has reviewed the upstream change — the finer-grained
    Doorstop ``clear`` (never re-bless a whole doc). Otherwise: validate ``record_id``
    EXISTS in the review log (a loud K8 error if not), then append a
    :class:`~custodex.schema.ResolutionRecord` to the resolutions log (the review log
    is NEVER mutated; linked by FK, K5). The timestamp is injected via ``_now`` (K10).
    """
    if edge is not None:
        _resolve_edge(edge[0], edge[1], config)
        return
    if record_id is None or resolution is None:
        typer.echo(
            "error: provide a RECORD_ID and --resolution, or --edge DOWN UP",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        _cfg, config_dir = _load(config)
        wanted = _parse_resolution(resolution)
        records = read_all(config_dir / DEFAULT_LOG_PATH)
        if not any(r.record_id == record_id for r in records):
            raise SchemaError(
                f"unknown record_id {record_id!r}: not found in the review log "
                f"({config_dir / DEFAULT_LOG_PATH})"
            )
        res_path = log if log is not None else config_dir / DEFAULT_RESOLUTIONS_PATH
        append_resolution(
            res_path,
            ResolutionRecord(
                record_id=record_id,
                resolution=wanted,
                resolved_text=text,
                resolved_by=by,
                resolved_at=_now(),
                note=note,
            ),
        )
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"resolved {record_id} as {wanted.value}")


def _resolve_edge(downstream: str, upstream: str, config: Path) -> None:
    """Re-stamp one doc↔doc edge's baseline (the per-edge ack, EPIC B B-05).

    Loud (K8) when the edge is not declared in config — the declaration is the
    source of truth (K2); a typo or a forgotten ``depends_on`` must not silently
    create an edge. Idempotent (K7): an already-current edge re-stamps nothing.
    """
    try:
        cfg, config_dir = _load(config)
        root = resolve_repo_root(config_dir, cfg.root)
        spec = next((d for d in cfg.documents if d.id == downstream), None)
        if spec is None or all(e.doc != upstream for e in spec.depends_on):
            raise SchemaError(
                f"no declared edge {downstream!r} → {upstream!r}: add it to the "
                f"document's depends_on (or run `cdx deps --suggest`) first"
            )
        changed = stamp_edges(cfg, root, downstream, only=upstream)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if changed:
        typer.echo(f"re-stamped edge {downstream} → {upstream} (suspect link cleared)")
    else:
        typer.echo(f"edge {downstream} → {upstream} already current — nothing to do")


@app.command()
def deps(
    config: Path = _CONFIG_OPTION,
    suspect: bool = typer.Option(
        False, "--suspect", help="Show only edges that need review (hide OK edges)."
    ),
    suggest: bool = typer.Option(
        False,
        "--suggest",
        help="Infer edges from Markdown cross-links between managed docs and print "
        "paste-ready `depends_on` config (the low-tedium authoring aid). Read-only.",
    ),
    impact: str | None = typer.Option(
        None,
        "--impact",
        metavar="DOC",
        help="Show the blast radius of changing DOC — the documents that "
        "(transitively) depend on it and would need re-review. Read-only.",
    ),
    transitive: bool = typer.Option(
        False,
        "--transitive",
        help="Also show the EAGER transitive-suspect advisory (PROP-01): documents "
        "whose upstream is itself pending review. Advisory only — never gates "
        "`cdx check`. Applies to the default suspect listing (ignored with --impact, "
        "which is already transitive, and with --suggest).",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the dependency graph / suggestions as JSON."
    ),
) -> None:
    """Show the doc↔doc dependency graph + suspect status (read-only, K1/K4).

    The doc↔doc analogue of ``cdx ownership``: lists every declared ``depends_on``
    edge and whether it is OK / suspect / unstamped, all derived from config (the
    source of truth) + the downstream's stored baseline stamps. ``--suggest`` instead
    proposes edges inferred from existing Markdown cross-links so a human approves a
    graph rather than authoring it; ``--impact DOC`` answers the proactive "what must
    I review if I change DOC" by walking the dependents reverse-reachable from DOC. No
    backend, no network.
    """
    try:
        cfg, config_dir = _load(config)
        root = resolve_repo_root(config_dir, cfg.root)
        if impact is not None:
            impacted = impacted_by(cfg, impact)
            if as_json:
                typer.echo(
                    json.dumps(
                        {"upstream": impact, "impacted": list(impacted)},
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                typer.echo(render_impact_text(impact, impacted))
            return
        if suggest:
            inferred = infer_edges_from_links(cfg, root)
            if as_json:
                typer.echo(
                    json.dumps(
                        [e.model_dump(mode="json") for e in inferred],
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                typer.echo(_render_suggestions(inferred))
            return
        links = detect_suspect_links(cfg, root, include_ok=not suspect)
        # propagate_suspect ignores OK links, so the include_ok graph is a safe basis.
        trans = propagate_suspect(cfg, links) if transitive else ()
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        edges_json = [link.model_dump(mode="json") for link in links]
        if transitive:
            # Opt-in shape: only --transitive widens the payload to an object, so
            # plain `cdx deps --json` keeps its back-compat bare-list contract (K6).
            payload: object = {
                "edges": edges_json,
                "transitive": [link.model_dump(mode="json") for link in trans],
            }
        else:
            payload = edges_json
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(render_deps_text(links, suspect_only=suspect, transitive=trans))


@app.command()
def entities(
    doc_id: str | None = typer.Argument(
        None,
        metavar="[DOC_ID]",
        help="Limit the report to one managed document (default: every doc).",
    ),
    config: Path = _CONFIG_OPTION,
    unresolved: bool = typer.Option(
        False,
        "--unresolved",
        help="Show only UNRESOLVED mentions — the graph-rot signal (a mention "
        "whose referent no longer exists, or never did).",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the per-document mention lists as JSON."
    ),
) -> None:
    """Show each managed doc's entity mentions, linked or unresolved (read-only, K1).

    The AGT-01 mention layer: every backticked symbol/path/env-var span and
    markdown link in a doc's PROSE (machine regions and code fences excluded),
    resolved against the code surface + the managed-doc set + the repo tree.
    Deterministic, offline, no backend (K4/K10); precision-first — an ambiguous
    span is unresolved or ignored, never guessed.
    """
    try:
        cfg, config_dir = _load(config)
        root = resolve_repo_root(config_dir, cfg.root)
        results = corpus_entities(cfg, root, doc_id=doc_id)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        payload = [r.model_dump(mode="json") for r in results]
        if unresolved:
            payload = [
                {
                    **r,
                    "mentions": [m for m in r["mentions"] if not m["resolved"]],
                }
                for r in payload
            ]
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(render_entities_text(results, unresolved_only=unresolved))


def _render_suggestions(inferred: Sequence[InferredEdge]) -> str:
    """Render inferred edges as paste-ready ``depends_on`` config (EPIC B B-05)."""
    if not inferred:
        return "# no new doc↔doc edges inferred from Markdown links"
    by_doc: dict[str, list[str]] = {}
    for e in inferred:
        by_doc.setdefault(e.doc_id, []).append(e.upstream_id)
    lines = [f"# {len(inferred)} inferred edge(s) — add to the relevant documents:"]
    for doc_id in sorted(by_doc):
        lines.append(f"# document {doc_id!r}:")
        lines.append("    depends_on:")
        for up in sorted(by_doc[doc_id]):
            lines.append(f"      - doc: {up}")
    return "\n".join(lines)


def _region_mode_lines(cfg: MonitorConfig, config_dir: Path) -> list[str]:
    """Deterministic per-region authority STATE lines for ``lint --modes`` (B-05).

    One line per managed region: ``doc::region — mode [renderer|no-renderer]
    [locked] [advisory]``. A pure surface over :func:`config_region_states`;
    informational only — it never affects lint's exit code (K10).
    """
    lines = ["region authority modes:"]
    for st in config_region_states(cfg, config_dir):
        flags = ["renderer" if st.has_renderer else "no-renderer"]
        if st.locked:
            flags.append("locked")
        if st.advisory:
            flags.append("advisory")
        flag_str = " ".join(flags)
        lines.append(f"  {st.doc_id}::{st.region_id} — {st.mode.value} [{flag_str}]")
    return lines


@app.command()
def lint(
    config: Path = _CONFIG_OPTION,
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Stamp missing static front matter (schema_version/audience).",
    ),
    modes: bool = typer.Option(
        False,
        "--modes",
        help="Also print each managed region's authority mode + lock/advisory "
        "state (informational — does NOT change lint's pass/fail).",
    ),
) -> None:
    """Validate doc *structure* against the Layout Standard (exit 1 on issues).

    Orthogonal to ``check`` (which grades *content*): run both in CI. ``--fix``
    repairs front-matter issues; structural issues (title/purpose/regions/html)
    still need authoring and are reported as remaining. ``--modes`` adds a
    per-region authority STATE view (mode + renderer + lock/advisory) — a
    surface, NOT a gate: it never changes the exit code (B-05).
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
        if modes:
            for line in _region_mode_lines(cfg, config_dir):
                typer.echo(line)
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
        doc_path.write_text(
            scaffold_doc(spec, surface, include_body=cfg.fingerprint_body_tier),
            encoding="utf-8",
        )
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Wrote conformant doc scaffold to {spec.path}")


def _known_modules() -> set[str]:
    """The set of real top-level modules under ``custodex`` (typo guard).

    Mirrors the catalog's own module-existence check: a feature naming a module
    not in this set is a loud :class:`CatalogError` at load time (K8). Discovered
    via :func:`pkgutil.iter_modules` so it stays in lock-step with the package.
    """
    import pkgutil

    from . import __path__ as pkg_path

    return {m.name for m in pkgutil.iter_modules(pkg_path)}


@app.command()
def trace(
    catalog: Path = typer.Option(
        Path("feature-doc") / "catalog",
        "--catalog",
        help="The feature-doc/catalog directory of golden feature *.yaml files.",
    ),
    tests_root: Path = typer.Option(
        Path("tests"),
        "--tests-root",
        help="Directory scanned for TEST evidence (inline `Feature:` tags).",
    ),
    demo_root: Path = typer.Option(
        Path("demo"),
        "--demo-root",
        help="Directory scanned for DEMO evidence (inline `Feature:` tags).",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit the traceability matrix as JSON instead of the human summary.",
    ),
    fail_on_gap: bool = typer.Option(
        False,
        "--fail-on-gap",
        help="Exit nonzero if ANY feature lacks a test or demo, or any unknown ref "
        "exists (the CI gate, K8). Without it the command is informational "
        "(always exits 0).",
    ),
) -> None:
    """Prove every feature has a demo + test via inline `Feature:` tags (EPIC R).

    Loads the golden catalog (``feature-doc/catalog``), scans ``tests/`` (TEST) and
    ``demo/`` (DEMO) for the inline ``Feature: <id>`` tag convention — files read
    as TEXT, never imported (K1) — and crosses them into a traceability matrix.
    Prints a human summary (covered count + the test/demo/unknown-ref gaps);
    ``--json`` emits the matrix; ``--fail-on-gap`` turns it into a gate (exit 1
    when not complete). Pure + deterministic (K10). NOTE: real tests/demos are not
    annotated until R-04/R-05, so on the real tree ``--fail-on-gap`` will (
    correctly) report gaps — the CI gate is wired in R-07.
    """
    try:
        cat = load_catalog(catalog, known_modules=_known_modules())
        matrix = build_matrix(cat, tests_root=tests_root, demo_root=demo_root)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        payload = {
            "catalog_ids": list(matrix.catalog_ids),
            "refs": [r.model_dump(mode="json") for r in matrix.refs],
            "features_without_test": list(matrix.features_without_test()),
            "features_without_demo": list(matrix.features_without_demo()),
            "unknown_refs": [r.model_dump(mode="json") for r in matrix.unknown_refs()],
            "is_complete": matrix.is_complete(),
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for line in _trace_lines(matrix):
            typer.echo(line)

    if fail_on_gap and not matrix.is_complete():
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


def _trace_lines(matrix: TraceMatrix) -> list[str]:
    """Deterministic, scannable human render of a traceability matrix (K10)."""
    no_test = matrix.features_without_test()
    no_demo = matrix.features_without_demo()
    unknown = matrix.unknown_refs()
    covered = sum(
        1
        for fid in matrix.catalog_ids
        if matrix.tests_for(fid) and matrix.demos_for(fid)
    )
    status = "COMPLETE" if matrix.is_complete() else "INCOMPLETE"
    lines = [
        f"traceability: {status} — {covered}/{len(matrix.catalog_ids)} feature(s) "
        "have both a test and a demo",
        f"features missing a test: {len(no_test)}",
    ]
    lines.extend(f"  {fid}" for fid in no_test)
    lines.append(f"features missing a demo: {len(no_demo)}")
    lines.extend(f"  {fid}" for fid in no_demo)
    lines.append(f"unknown refs (tagged id not in catalog): {len(unknown)}")
    lines.extend(
        f"  {r.feature_id} @ {r.path}:{r.line} ({r.kind.value})" for r in unknown
    )
    return lines


@app.command()
def wiki(
    check: bool = typer.Option(
        False,
        "--check",
        help="Verify the wikis are fresh; exit nonzero if any is stale (no write).",
    ),
) -> None:
    """Regenerate every EPIC-R wiki from its single source (or --check freshness).

    Renders the four canonical artifacts — ``feature-doc/FEATURES.md`` and the
    test/source/traceability wikis under ``feature-doc/wiki/`` — from the catalog
    yaml, the tests' docstrings, and the source AST via the shared
    :data:`~custodex.wiki.WIKI_TARGETS` set. Default mode WRITES every
    changed target and echoes each path + ``wrote``/``unchanged``; a second run is
    a no-op (idempotent, K7). ``--check`` is read-only (K1): it renders in memory,
    lists every STALE file, and exits 1 when any is stale — the CI freshness gate
    (K8) — else prints ``wikis fresh`` and exits 0. Deterministic (K10); loud on a
    render error (K8).
    """
    from .wiki import regenerate

    repo_root = Path.cwd()
    try:
        results = regenerate(repo_root, write=not check)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not check:
        for path, changed in results:
            typer.echo(f"{path}: {'wrote' if changed else 'unchanged'}")
        raise typer.Exit(code=0)

    stale = [path for path, is_stale in results if is_stale]
    if stale:
        for path in stale:
            typer.echo(f"{path}: STALE — run `cdx wiki` to regenerate", err=True)
        typer.echo(f"{len(stale)} wiki(s) stale", err=True)
        raise typer.Exit(code=1)
    typer.echo("wikis fresh")
    raise typer.Exit(code=0)


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


def _settings_lines(resolved: Settings, presence: dict[str, bool]) -> list[str]:
    """A deterministic human render of the resolved settings + secret presence (K10)."""
    srv = resolved.server
    rpm = srv.rate_limit.requests_per_minute
    timeout = srv.git.clone_timeout_seconds
    cors = ", ".join(srv.cors.allow_origins) or "(disabled)"
    extra_hosts = ", ".join(srv.git.extra_allowed_hosts) or "(none)"
    rpm_str = str(rpm) if rpm is not None else "(none)"
    timeout_str = str(timeout) if timeout is not None else "(none)"
    lines = [
        f"settings version: {resolved.version}",
        f"server.host: {srv.host}",
        f"server.port: {srv.port}",
        f"server.log_level: {srv.log_level}",
        f"server.trusted_hosts: {', '.join(srv.trusted_hosts)}",
        f"server.cors.allow_origins: {cors}",
        f"server.rate_limit.requests_per_minute: {rpm_str}",
        f"server.git.allowed_hosts: {', '.join(srv.git.allowed_hosts)}",
        f"server.git.extra_allowed_hosts: {extra_hosts}",
        f"server.git.allow_file_scheme: {srv.git.allow_file_scheme}",
        f"server.git.clone_timeout_seconds: {timeout_str}",
        "secrets (presence only — values never shown):",
    ]
    lines.extend(
        f"  {key}: {'set' if presence[key] else 'unset'}" for key in sorted(presence)
    )
    return lines


@app.command()
def settings(
    settings_path: Path = typer.Option(
        Path("config/settings.yaml"),
        "--settings",
        help="Path to the operator settings YAML.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the resolved settings + secret presence as JSON."
    ),
) -> None:
    """Show the EFFECTIVE server settings: file → env → defaults (read-only, K1).

    Resolves ``config/settings.yaml`` (if present) with env overrides applied and
    prints the host/port + the CORS/TrustedHost/rate-limit/git hardening knobs,
    plus whether each environment SECRET (admin token / database url / secret key) is
    configured — never the secret value. Offline (K4): no backend, no network.
    """
    try:
        resolved = resolve_settings(settings_path)
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    presence = secret_presence()
    if as_json:
        payload = {"settings": resolved.model_dump(mode="json"), "secrets": presence}
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for line in _settings_lines(resolved, presence):
            typer.echo(line)


@app.command()
def ownership(
    config: Path = _CONFIG_OPTION,
    roster: Path | None = typer.Option(
        None,
        "--roster",
        help="An offline roster YAML (identities: [...]) to cross-check owners "
        "against; without it the command just lists assignments.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit {owners, findings} as round-trippable JSON."
    ),
    fail_on_orphan: bool = typer.Option(
        False,
        "--fail-on-orphan",
        help="Exit 1 if any document is an orphan (its accountable owner has "
        "departed). Requires --roster; UNOWNED docs do NOT trip it (that is a "
        "coverage gap, not a departure).",
    ),
) -> None:
    """List per-document ownership and flag orphaned (departed-owner) docs (K1/K4).

    Pure + offline: resolves each document's accountable/durable owner from config
    (the source of truth for ownership), optionally cross-checks against an offline
    ``--roster`` to classify orphans, and prints a table (or ``--json``).
    ``--fail-on-orphan`` turns a departed-owner orphan into a nonzero exit — an
    accountability gate. No backend, no network.
    """
    if fail_on_orphan and roster is None:
        # Loud, not a vacuous pass (K8): without a roster there is no departure
        # data, so the gate could never fire — a forgotten --roster in CI would
        # silently report "clean". Refuse the misuse instead.
        typer.echo(
            "error: --fail-on-orphan requires --roster (no roster = no departure "
            "data, so the gate would pass vacuously).",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        cfg, config_dir = _load(config)
        unit_owner = _unit_owner_map(config_dir)
        owners = resolve_ownership(cfg, unit_owner=unit_owner)
        snapshot = load_roster(roster) if roster is not None else None
    except CodeDocMonitorError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    findings = detect_orphans(owners, snapshot) if snapshot is not None else ()
    if as_json:
        payload = {
            "owners": [o.model_dump(mode="json") for o in owners],
            "findings": [f.model_dump(mode="json") for f in findings],
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(render_ownership_text(owners, findings))
    if fail_on_orphan and any(
        f.status
        in (OwnershipStatus.ORPHAN_OWNER_DEPARTED, OwnershipStatus.ORPHAN_DRI_VACANT)
        for f in findings
    ):
        raise typer.Exit(code=1)


@app.command()
def staleness(
    config: Path = _CONFIG_OPTION,
    now: str | None = typer.Option(
        None,
        "--now",
        help="ISO timestamp to grade freshness against (default: the current time).",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit {findings} as JSON (includes fresh docs)."
    ),
    fail_on_stale: bool = typer.Option(
        False,
        "--fail-on-stale",
        help="Exit 1 if any document is stale or never reviewed (a review gate).",
    ),
) -> None:
    """Flag documents past their review SLA — time-based accountability (K1/K3/K4).

    Config is the source of truth: each document's ``reviewed`` date is graded against
    ``now`` and the (audience-aware) ``staleness`` SLA. The table shows only the docs
    that need a review; ``--json`` shows all; ``--fail-on-stale`` makes it a CI gate.
    Pure + offline (K4); no backend, no network.
    """
    try:
        cfg, _config_dir = _load(config)
        docs = reviewed_docs_from_config(cfg)
        findings = detect_stale(
            docs,
            now=now or _now(),
            default_days=cfg.staleness.default_days,
            audience_days=cfg.staleness.audience_days,
            include_fresh=as_json,
        )
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        payload = {"findings": [f.model_dump(mode="json") for f in findings]}
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(render_staleness_text(findings))
    if fail_on_stale and any(
        f.status in (StalenessStatus.STALE, StalenessStatus.NEVER_REVIEWED)
        for f in findings
    ):
        raise typer.Exit(code=1)


@app.command()
def worklist(
    config: Path = _CONFIG_OPTION,
    owner: str | None = typer.Option(
        None, "--owner", help="Show only this accountable owner's queue."
    ),
    roster: Path | None = typer.Option(
        None,
        "--roster",
        help="Offline roster YAML (identities: [...]) to classify ownership orphans. "
        "Without it, orphan items are skipped (no departure data).",
    ),
    now: str | None = typer.Option(
        None,
        "--now",
        help="ISO timestamp to grade staleness against (default: the current time).",
    ),
    include_suspect: bool = typer.Option(
        True,
        "--include-suspect/--no-include-suspect",
        help="Include doc↔doc suspect-link items (repo-local).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit the worklist as JSON."),
    fail_on_work: bool = typer.Option(
        False,
        "--fail-on-work",
        help="Exit 1 if ANY work item exists (a review gate). Default exits 0.",
    ),
) -> None:
    """One prioritised queue per accountable owner — the accountability JOIN (K1/K4).

    Buckets every document needing attention — an ownership ORPHAN (EPIC OWN), a
    STALE review (EPIC SLA), or a doc↔doc SUSPECT link (Pillar B) — under its
    accountable owner, so each person sees ONE queue. Read-only, offline, deterministic
    (``now`` is injected). ``--owner`` filters to one queue; ``--fail-on-work`` makes it
    a CI gate (opt-in). Orphan items need ``--roster``; ``--no-include-suspect`` drops
    the repo-local suspect items.
    """
    try:
        cfg, config_dir = _load(config)
        root = resolve_repo_root(config_dir, cfg.root)
        snapshot = load_roster(roster) if roster is not None else None
        wl = worklist_from_repo(
            cfg,
            root,
            now=now or _now(),
            roster=snapshot,
            unit_owner=_unit_owner_map(config_dir),
            include_suspect=include_suspect,
            owner_filter=owner,
        )
    except CodeDocMonitorError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(json.dumps(wl.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        typer.echo(render_worklist_text(wl))
    if fail_on_work and wl.item_count > 0:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    # So `python -m custodex.cli ...` runs the app (not a silent no-op);
    # the installed `cdx` console script uses the `app` entry point directly.
    app()
