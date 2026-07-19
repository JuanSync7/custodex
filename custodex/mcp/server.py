"""The Custodex MCP server over FastMCP (the ``[mcp]`` extra — EPIC MCP).

This module is IMPORT-SAFE: the ``mcp`` SDK is imported lazily INSIDE
:func:`build_mcp_server` (the :func:`custodex.backends.make_backend` precedent),
wrapped in a typed :class:`~custodex.errors.McpError` with an actionable install
hint (K8). So ``import custodex`` — and even ``import custodex.mcp.server`` —
pulls in nothing from the SDK (K0); only *building* a server requires the extra.
All projection logic lives in the pure :mod:`custodex.mcp.tools` module; this
module only maps those functions onto FastMCP tools and runs the stdio transport.

The tool set is CURATED and its output is SHAPED (pydantic → ``model_dump``), not
a 1:1 wrap of the 37 ``cdx`` verbs. ``custodex_status`` is the progressive-
disclosure overview; the seven MCP-01 tools (``custodex_drift``/
``custodex_coverage``/``custodex_ownership``/``custodex_staleness``/
``custodex_worklist``/``custodex_doc_graph``/``custodex_records``) are the
per-domain drill-downs. Each tool is ``custodex_``-prefixed so it stays
collision-safe in a client that mounts several MCP servers into one namespace.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Audience
from ..drift import DriftKind
from ..errors import McpError
from ..schema import Resolution, Verdict
from . import tools

__all__ = ["build_mcp_server", "main"]


def _now() -> str:
    """The as-of timestamp for the SLA/staleness folds (K10 injection boundary).

    The impure seam (mirrors ``cli._now``): the pure ``tools`` helpers NEVER read
    a clock — the tool wrapper reads it here and injects it, so every fold stays
    deterministic under a fixed ``now`` in the tests.
    """
    return datetime.now(timezone.utc).isoformat()


def build_mcp_server(repo_root: Path, *, read_only: bool = False) -> Any:
    """Build the Custodex MCP server over ``repo_root`` (import-safe; no transport).

    Guards the missing SDK loudly (K8, the ``make_backend`` precedent), then fails
    fast if ``repo_root`` has no resolvable Custodex config, then registers the
    curated tools as thin wrappers over the pure :mod:`tools` functions. Each tool
    RELOADS the config bundle per call so it reflects live repo state, and returns
    ``model_dump(mode="json")`` (shaped output). Returns the :class:`FastMCP`
    server WITHOUT binding a transport, so tests drive it directly (the
    :func:`custodex.server.standalone.build_standalone_app` precedent — all logic
    here, the stdio launch stays a thin leaf).

    The eight MCP-00/01 READ tools always register. The three MCP-02 WRITE tools
    (``custodex_remediate``/``custodex_resolve``/``custodex_sync_docs``) register
    ONLY when ``read_only`` is False (the default): ``read_only=True`` gives an
    operator a PROVABLE no-write surface for an untrusted agent (K11), the coarse
    gate complementing each write tool's own advisory ``apply=False`` default.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - only without the [mcp] extra
        raise McpError(
            "the MCP server needs the optional 'mcp' dependency; install custodex[mcp]"
        ) from exc

    # Fail fast (K8): refuse to serve a repo with no resolvable config, so the
    # error surfaces at launch, not on the first tool call.
    tools.load_repo_bundle(repo_root)

    server = FastMCP("custodex")

    def _bundle() -> tuple[Any, Path, str]:
        """(cfg, config_dir, repo_id) reloaded per call — reflects live repo state."""
        cfg, config_dir = tools.load_repo_bundle(repo_root)
        return cfg, config_dir, tools.resolve_repo_id(repo_root, config_dir)

    @server.tool()
    def custodex_status() -> dict[str, Any]:
        """Is this repo in sync? The 4-pillar health headline in one call.

        The progressive-disclosure entrypoint: call this FIRST for drift totals
        (code↔doc vs doc↔doc) + coverage % + unowned + docs-needing-review, then
        drill into the per-domain tools below.
        """
        cfg, config_dir, repo_id = _bundle()
        return tools.status_summary(
            cfg, config_dir, repo_id=repo_id, now=_now()
        ).model_dump(mode="json")

    @server.tool()
    def custodex_drift(
        limit: int = 50,
        kind: DriftKind | None = None,
        audience: Audience | None = None,
    ) -> dict[str, Any]:
        """The per-drift DETAIL list (``custodex_status`` only counts).

        Each item: the doc, drift kind, audience (K3), whether it heals
        automatically, the change severity, and a human message. Optionally filter
        by ``kind`` / ``audience``; capped at ``limit`` (``truncated`` flags it).
        """
        cfg, config_dir, repo_id = _bundle()
        return tools.drift_detail(
            cfg, config_dir, repo_id=repo_id, limit=limit, kind=kind, audience=audience
        ).model_dump(mode="json")

    @server.tool()
    def custodex_coverage(gap_limit: int = 50) -> dict[str, Any]:
        """Doc-coverage: what share of the code surface is documented + the gaps.

        Percentages (files + public symbols) + basket counts + a capped
        ``top_gaps`` list of undocumented public symbols (``gaps_truncated`` flags
        the cut). The headline metric is ``percent_public_symbols``.
        """
        cfg, config_dir, repo_id = _bundle()
        return tools.coverage_summary(
            cfg, config_dir, repo_id=repo_id, gap_limit=gap_limit
        ).model_dump(mode="json")

    @server.tool()
    def custodex_ownership() -> dict[str, Any]:
        """Who owns each doc: unowned gaps (+ departed-owner orphans with a roster).

        Runs against the LOCAL repo (config = source of truth): ``unowned_count``
        is always computed; departed-owner orphan detection needs a central roster
        this local surface does not hold, so ``roster_checked`` is False here.
        """
        cfg, config_dir, repo_id = _bundle()
        return tools.ownership_summary(cfg, config_dir, repo_id=repo_id).model_dump(
            mode="json"
        )

    @server.tool()
    def custodex_staleness(include_fresh: bool = False) -> dict[str, Any]:
        """Review-SLA staleness: which docs are past their audience-aware window.

        Grades each doc's ``reviewed`` date as-of now; ``needs_review_total`` =
        stale + never-reviewed. Set ``include_fresh`` to also return in-SLA docs.
        """
        cfg, config_dir, repo_id = _bundle()
        return tools.staleness_summary(
            cfg, config_dir, repo_id=repo_id, now=_now(), include_fresh=include_fresh
        ).model_dump(mode="json")

    @server.tool()
    def custodex_worklist(
        owner_filter: str | None = None,
        include_suspect: bool = True,
        limit: int = 50,
    ) -> dict[str, Any]:
        """The prioritised "what needs a human" queue (ownership + SLA + doc↔doc).

        The accountability JOIN: orphan + stale + suspect items in global priority
        order, capped at ``limit``. Filter to one owner with ``owner_filter``.
        Orphans need a roster (absent locally → ``orphans_included`` is False).
        """
        cfg, config_dir, repo_id = _bundle()
        return tools.worklist_summary(
            cfg,
            config_dir,
            repo_id=repo_id,
            now=_now(),
            owner_filter=owner_filter,
            include_suspect=include_suspect,
            limit=limit,
        ).model_dump(mode="json")

    @server.tool()
    def custodex_doc_graph() -> dict[str, Any]:
        """The doc↔doc dependency graph + per-edge suspect status.

        Every declared ``depends_on`` edge with its status (OK / unstamped /
        suspect / missing upstream). ``enabled`` disambiguates "detection off"
        from "no edges"; ``gates`` says whether a suspect link fails ``cdx check``.
        """
        cfg, config_dir, repo_id = _bundle()
        return tools.doc_graph_summary(cfg, config_dir, repo_id=repo_id).model_dump(
            mode="json"
        )

    @server.tool()
    def custodex_records(
        verdict: Verdict | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """The local review-log audit trail (K5), newest-first.

        Each handled drift is one record (doc, verdict, severity, timestamps).
        Optionally filter by ``verdict`` (FIX / INVALIDATE / ESCALATE — the enum
        is advertised in the tool schema); capped at ``limit``. A fresh repo with
        no log returns an empty list (not an error).
        """
        cfg, config_dir, repo_id = _bundle()
        return tools.list_records(
            cfg, config_dir, repo_id=repo_id, verdict=verdict, limit=limit
        ).model_dump(mode="json")

    if not read_only:
        # MCP-02: the gated WRITE tools — registered ONLY on a read-write server, so
        # `read_only=True` leaves an operator a provable no-write surface (K11). Each
        # defaults its write to advisory and injects `_now()` at this boundary (K10).

        @server.tool()
        def custodex_remediate(apply: bool = False, limit: int = 50) -> dict[str, Any]:
            """Propose (and optionally apply) fixes for the repo's drift.

            Drives the remediation pipeline: each handled drift gets a verdict + a
            proposed fix, RECORDED as a ReviewRecord (K5) whatever the outcome. With
            ``apply=False`` (the default, K11) NOTHING is written to a doc — the
            proposals are advisory and each item's ``record_id`` is the handle you
            pass to ``custodex_resolve``. Set ``apply=True`` to heal ``FIX`` verdicts
            in place. Each call records the proposals; for a pure, record-free view
            of what is drifted, use ``custodex_drift``.
            """
            cfg, config_dir, repo_id = _bundle()
            return tools.remediate_drift(
                cfg, config_dir, repo_id=repo_id, now=_now(), apply=apply, limit=limit
            ).model_dump(mode="json")

        @server.tool()
        def custodex_resolve(
            record_id: str,
            resolution: Resolution,
            resolved_by: str | None = None,
            resolved_text: str | None = None,
            note: str | None = None,
        ) -> dict[str, Any]:
            """Record the human OUTCOME of a handled drift (K5, append-only).

            Links a ``Resolution`` (accepted / overridden / rejected / invalidated —
            the enum is advertised in the tool schema) to an existing review
            ``record_id`` (from ``custodex_records`` or ``custodex_remediate``). The
            review log is never mutated — the outcome is a separate append-only event
            (a re-resolution is a correction, last-write-wins). An unknown
            ``record_id`` or resolution is a loud error (K8). Use ``resolved_text``
            for the human's final body when the resolution is ``overridden``.
            """
            cfg, config_dir, repo_id = _bundle()
            return tools.resolve_drift(
                cfg,
                config_dir,
                repo_id=repo_id,
                record_id=record_id,
                resolution=resolution,
                now=_now(),
                resolved_text=resolved_text,
                resolved_by=resolved_by,
                note=note,
            ).model_dump(mode="json")

        @server.tool()
        def custodex_sync_docs(apply: bool = False) -> dict[str, Any]:
            """Preview (or apply) the doc heal as a unified diff.

            With ``apply=False`` (the default, K1) returns the ``patch`` of what
            healing WOULD change while leaving the working tree untouched; set
            ``apply=True`` to write the healed docs. ``clean`` (empty patch) means the
            docs are already in sync. Like ``custodex_remediate``, even a preview
            records the proposals to the review log (the doc tree is restored, but
            ``.cdmon/review-log.jsonl`` grows — a repeated preview is not idempotent
            on the audit log). The live merge-request bot stays in ``cdx``.
            """
            cfg, config_dir, repo_id = _bundle()
            return tools.sync_docs(
                cfg, config_dir, repo_id=repo_id, now=_now(), apply=apply
            ).model_dump(mode="json")

    return server


def main() -> None:  # pragma: no cover — the `cdx-mcp` entry point (stdio leaf, K4)
    """The ``cdx-mcp`` console entry point: serve the cwd repo over stdio.

    Guards the missing extra + a config-less repo loudly (K8, exit 1), mirroring
    ``cdx mcp-serve`` — both entry points reach the SAME guarded builder.
    """
    try:
        server = build_mcp_server(Path.cwd())
    except McpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    server.run()
