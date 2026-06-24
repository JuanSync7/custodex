"""G-02 — `cdx doctor`: an offline, read-only preflight (K1, K4, K10).

:func:`run_checks` answers one question — *is this repo wired up correctly enough
to run cdx and report to its central system?* — WITHOUT touching the network
and WITHOUT mutating anything (it reads ``os.environ`` / ``$PATH`` / installed
distributions only). It returns a DETERMINISTIC, ordered list of :class:`Check`
results; ``cdx doctor`` prints them and exits 0 unless any is ``FAIL``.

The grading philosophy (the G-02 lesson): a prereq that is merely ABSENT in this
environment (no ``claude`` CLI, no ``$ANTHROPIC_API_KEY``, no optional extra
installed, an unset token) is a ``WARN`` — the *config* is valid, this particular
machine just can't RUN that path. Only a config that is structurally broken (an
``http`` sink missing its ``url`` / ``repo_id`` — which :func:`make_sink` would
raise on, K8) is a ``FAIL``. A real connectivity ``--ping`` (an injected
transport) is intentionally out of scope; the default doctor is offline.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import MonitorConfig

__all__ = ["CheckStatus", "Check", "run_checks"]

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class CheckStatus(str, Enum):
    """A doctor check outcome. ``FAIL`` is the only status that fails the gate."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class Check(BaseModel):
    """One preflight result: a stable ``name``, a ``status``, and a ``detail``."""

    model_config = _MODEL_CONFIG

    name: str
    status: CheckStatus
    detail: str


def _check_documents(config: MonitorConfig, root: Path) -> Check:
    """Docs resolve under root (a MISSING doc is heal-creatable, NOT a failure).

    A missing doc *file* is PASS — ``cdx new-doc`` / the heal can scaffold it.
    A missing *code ref* file is WARN — extraction would have nothing to read, so
    the surface (and thus any drift verdict) is degraded, but the config itself is
    still valid in another checkout where the file exists.
    """
    missing_refs: list[str] = []
    for doc in config.documents:
        for ref in doc.code_refs:
            if not (root / ref.path).is_file():
                missing_refs.append(ref.path)
    if missing_refs:
        shown = ", ".join(sorted(set(missing_refs)))
        return Check(
            name="documents",
            status=CheckStatus.WARN,
            detail=f"code ref file(s) not found under root: {shown}",
        )
    return Check(
        name="documents",
        status=CheckStatus.PASS,
        detail=f"{len(config.documents)} document(s); all code refs resolve under root",
    )


def _check_backend(config: MonitorConfig) -> Check:
    """Backend kind valid + its runtime prereq present (absent prereq → WARN)."""
    kind = config.backend.kind
    if kind == "mock":
        return Check(
            name="backend",
            status=CheckStatus.PASS,
            detail="mock backend (deterministic, offline) — always runnable",
        )
    if kind == "claude-code":
        if shutil.which("claude") is None:
            return Check(
                name="backend",
                status=CheckStatus.WARN,
                detail="backend 'claude-code' but the `claude` CLI is not on $PATH",
            )
        return Check(
            name="backend",
            status=CheckStatus.PASS,
            detail="backend 'claude-code'; the `claude` CLI is on $PATH",
        )
    if kind == "api":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return Check(
                name="backend",
                status=CheckStatus.WARN,
                detail="backend 'api' but $ANTHROPIC_API_KEY is unset/empty",
            )
        return Check(
            name="backend",
            status=CheckStatus.PASS,
            detail="backend 'api'; $ANTHROPIC_API_KEY is set",
        )
    # kind == "agent": the langgraph extra check is emitted separately; the
    # driver's own prereq (api key / local base_url) is the runtime concern.
    return Check(
        name="backend",
        status=CheckStatus.PASS,
        detail=f"backend 'agent' (driver {config.agent.driver}); see agent-extra",
    )


def _check_central(config: MonitorConfig) -> Check:
    """Central reporting wiring: a broken http sink is FAIL; an unset token WARN."""
    central = config.central
    if central.sink == "none":
        return Check(
            name="central",
            status=CheckStatus.PASS,
            detail="central sink 'none' — local review log only (offline)",
        )
    if central.sink == "file":
        if not central.path:
            return Check(
                name="central",
                status=CheckStatus.FAIL,
                detail="central sink 'file' requires a 'path'",
            )
        return Check(
            name="central",
            status=CheckStatus.PASS,
            detail=f"central sink 'file' -> {central.path}",
        )
    # sink == "http": mirror make_sink's loud K8 requirements as FAILs.
    if not central.url:
        return Check(
            name="central",
            status=CheckStatus.FAIL,
            detail="central sink 'http' requires a 'url'",
        )
    if not central.repo_id:
        return Check(
            name="central",
            status=CheckStatus.FAIL,
            detail="central sink 'http' requires a 'repo_id'",
        )
    if central.auth_env and not os.environ.get(central.auth_env):
        return Check(
            name="central",
            status=CheckStatus.WARN,
            detail=(
                f"central http -> {central.url} (repo {central.repo_id}); "
                f"token env ${central.auth_env} is unset (records send unauthenticated)"
            ),
        )
    return Check(
        name="central",
        status=CheckStatus.PASS,
        detail=f"central http -> {central.url} (repo {central.repo_id})",
    )


def _check_agent_extra(config: MonitorConfig) -> Check:
    """The optional ``[agent]`` extra (langgraph) importability — absent → WARN."""
    if importlib.util.find_spec("langgraph") is None:
        return Check(
            name="agent-extra",
            status=CheckStatus.WARN,
            detail=(
                "backend 'agent' needs the optional 'langgraph' dependency; "
                "install custodex[agent]"
            ),
        )
    return Check(
        name="agent-extra",
        status=CheckStatus.PASS,
        detail="optional 'langgraph' extra is importable",
    )


def run_checks(config: MonitorConfig, config_dir: Path) -> list[Check]:
    """Run the offline preflight checks in a DETERMINISTIC order (K10).

    The config is assumed already loaded (the CLI loads it, surfacing a malformed
    one as a loud K8 error BEFORE doctor runs). The first ``config`` check is thus
    always PASS — it records that the config parsed. Pure except env / ``$PATH`` /
    installed-distribution reads; NO network (K4).
    """
    root = config_dir / config.root
    checks: list[Check] = [
        Check(
            name="config",
            status=CheckStatus.PASS,
            detail="config loaded and validated",
        ),
        _check_documents(config, root),
        _check_backend(config),
        _check_central(config),
    ]
    if config.backend.kind == "agent":
        checks.append(_check_agent_extra(config))
    return checks
