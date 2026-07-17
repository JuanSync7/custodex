"""Pure MCP tool logic (EPIC MCP, MCP-00).

Imports ONLY core deps — never the ``mcp`` SDK — so the projection logic is
testable without the ``[mcp]`` extra and the engine's K0 surface is untouched.
The FastMCP registration that turns these into MCP tools lives in
:mod:`custodex.mcp.server` (the only module that imports the SDK). Every function
here READS the same detectors the ``cdx`` verbs call (K1/K2) — the MCP layer
never re-implements detection, and it never mutates.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..config import MonitorConfig, load_bundle, load_config, load_config_dir
from ..drift import DriftKind
from ..errors import CodeDocMonitorError, McpError
from ..monitor import Monitor

__all__ = [
    "StatusSummary",
    "load_repo_bundle",
    "resolve_repo_id",
    "status_summary",
]

# Where a repo's dir-layout config lives, relative to the repo root (CONFIG-V2 §1).
_CONFIG_SUBDIR = ("config", "cdmon")


def load_repo_bundle(repo_root: Path) -> tuple[MonitorConfig, Path]:
    """Resolve ``repo_root``'s Custodex config to ``(cfg, config_dir)`` (K8).

    The CONFIG-V2 ``config/cdmon/`` dir layout wins (``index.yaml`` present),
    else the single-file ``cdmon.yaml`` back-compat path. Neither present is a
    loud :class:`McpError` — there is nothing to serve. Returns the same
    ``(cfg, config_dir)`` pair the CLI's ``_load`` yields, so ``Monitor`` and the
    detectors resolve paths identically (a malformed config still raises the
    loader's own :class:`~custodex.errors.ConfigError`, K8).
    """
    config_dir = repo_root.joinpath(*_CONFIG_SUBDIR)
    if (config_dir / "index.yaml").is_file():
        return load_config_dir(config_dir), config_dir
    single = repo_root / "cdmon.yaml"
    if single.is_file():
        return load_config(single), repo_root
    raise McpError(
        f"no Custodex config under {repo_root} — expected config/cdmon/index.yaml "
        f"or cdmon.yaml (run `cdx init --v2` first)"
    )


def resolve_repo_id(repo_root: Path, config_dir: Path) -> str:
    """The repo id: the bundle index ``repo`` field, else the dir name (K8-safe).

    Mirrors :func:`custodex.server.standalone.resolve_repo_id` WITHOUT importing
    the ``[server]`` subpackage. A malformed/absent index falls back to the
    directory name so the status tool never fails on the id alone — the real
    config error surfaces loudly in the detect step (K8).
    """
    if (config_dir / "index.yaml").is_file():
        try:
            return load_bundle(config_dir).index.frontmatter.repo
        except CodeDocMonitorError:
            pass
    return repo_root.name


class StatusSummary(BaseModel):
    """The ``custodex_status`` overview: "is this repo in sync?" (MCP-00).

    ADDITIVE — MCP-01 enriches it with coverage/ownership/staleness counts, so a
    client reading only these fields keeps working (K6). ``clean`` is true only
    when there is no drift of any kind; ``drift_total`` is split into ``code↔doc``
    (``code_doc_drift``) and ``doc↔doc`` (``suspect_link_drift``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    clean: bool
    doc_count: int
    drift_total: int
    code_doc_drift: int
    suspect_link_drift: int
    summary: str


def status_summary(
    cfg: MonitorConfig, config_dir: Path, *, repo_id: str
) -> StatusSummary:
    """Project the live drift report into a shaped overview (K1/K2/K10).

    Runs the SAME detect ``cdx check`` runs (:meth:`Monitor.check`) and folds the
    :class:`~custodex.drift.DriftReport` into counts, split code↔doc vs doc↔doc
    (``SUSPECT_LINK``). Pure: no clock, no mutation, no network.
    """
    report = Monitor(cfg, config_dir).check()
    total = len(report.drifts)
    suspect = sum(1 for d in report.drifts if d.kind is DriftKind.SUSPECT_LINK)
    return StatusSummary(
        repo_id=repo_id,
        clean=report.ok,
        doc_count=len(cfg.documents),
        drift_total=total,
        code_doc_drift=total - suspect,
        suspect_link_drift=suspect,
        summary=report.summary(),
    )
