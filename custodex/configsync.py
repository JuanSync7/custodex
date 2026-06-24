"""Server-side config-sync engine — git/local, READ-ONLY on the repo (Y-02).

:func:`run_sync` is the one entry point the central server's ``POST
/repos/{id}/sync`` route calls. It reads a registered repo's ``config/cdmon/``
(and the source it references), merges to one :class:`MonitorConfig`, computes
drift + coverage, and projects the result into the persisted
:class:`ConfigDocument` / :class:`ConfigCodeRef` rows plus one :class:`SyncRun`
summary — all WITHOUT ever mutating the user's working tree (K1).

Two modes:

* **local** — operate directly on the repo's working tree. ``commits_ahead`` is
  ``git rev-list --count <default>..HEAD``; ``fully_synced`` is
  ``commits_ahead == 0 AND no drift``.
* **git** — materialize the git TOPLEVEL at its default branch READ-ONLY via
  ``git worktree add --detach <tmp> <branch>``, read the config from
  ``<worktree>/<rel>/config/cdmon`` (``rel`` = ``local_path`` relative to the
  toplevel, so a config in a SUBDIR works; ``rel == "."`` for a top-level
  config), run the same load+detect+coverage there, then
  ``git worktree remove --force`` in a ``finally`` so the user's tree is never
  disturbed. ``fully_synced`` is ``no drift at <default>`` (the central
  baseline).

Git is the only side effect and it is reached through ONE injected runner
(:data:`_run_git`, mirroring :mod:`custodex.backends`' injected
subprocess seam) so tests drive a real temp git repo and the failure path stays
testable. Every failure — a missing ``local_path``, an unknown ``mode``, or a
git subprocess error — is a loud, typed :class:`SyncError` (K8). The clock is
injected via ``now`` (K10).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from . import coverage as coverage_mod
from . import inventory
from .config import effective_coverage, load_bundle, resolve_repo_root
from .drift import DriftReport, detect
from .errors import SyncError
from .ownership import resolve_accountable_durable
from .server.store import (
    ConfigCodeRef,
    ConfigContextRef,
    ConfigDocument,
    SyncRun,
)
from .staleness import resolve_sla_days

__all__ = ["GitInfo", "SyncResult", "read_config_at", "run_sync"]

# The two accepted sync modes (CONFIG-V2 §4). An unknown mode is a loud K8.
_MODES = ("git", "local")

# Where a repo's dir-layout config lives, relative to the repo root.
_CONFIG_SUBDIR = ("config", "cdmon")


# Frozen + extra="forbid": these are immutable snapshots of one sync (K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


def _default_run_git(args: list[str], cwd: Path) -> str:
    """Run ``git <args>`` in ``cwd`` and return stdout (the real subprocess leaf).

    The ONLY place that shells out (mirrors
    :func:`custodex.backends._default_process_runner`): tests run this
    against a REAL temp git repo, so it is exercised — but the seam stays
    injectable for the failure path. A non-zero exit is a loud :class:`SyncError`
    (K8) carrying git's stderr.
    """
    result = subprocess.run(  # noqa: S603 (argv is fixed git verbs, no shell)
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SyncError(
            f"git {' '.join(args)} failed in {cwd} "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


#: The injected git runner — ``(args, cwd) -> stdout``. Production uses the real
#: subprocess; a test may swap it, but the suite drives a real temp repo so this
#: default IS covered.
_GitRunner = Callable[[list[str], Path], str]


class GitInfo(BaseModel):
    """The git context a sync read its config at (Y-02).

    ``branch`` / ``head_commit`` describe the working-tree HEAD;
    ``main_commit`` is the default branch's tip; ``commits_ahead`` is how far
    HEAD is ahead of the default branch (0 for git mode or when on the default).
    ``ref`` is the commit the config was actually read at (HEAD for local, the
    default-branch tip for git).
    """

    model_config = _MODEL_CONFIG

    ref: str | None = None
    branch: str | None = None
    head_commit: str | None = None
    main_commit: str | None = None
    commits_ahead: int = 0


class SyncResult(BaseModel):
    """The full outcome of one :func:`run_sync`: the rows + the run summary."""

    model_config = _MODEL_CONFIG

    documents: tuple[ConfigDocument, ...]
    code_refs: tuple[ConfigCodeRef, ...]
    run: SyncRun
    # The coverage snapshot of the synced tree: the same JSON-safe wire dict
    # ``coverage.coverage_snapshot`` produces (per-file list + basket counts +
    # percentages, stamped ``captured_at = now``). The central server persists it
    # on every sync so the dashboard's Coverage page reflects the JUST-SYNCED tree,
    # not only the last explicit ``POST /coverage`` ingest (T-02). ``run_sync``
    # always populates it; the ``None`` default keeps the field additive (K6).
    coverage: dict | None = None


def _git_info(local_path: Path, default_branch: str, *, run_git: _GitRunner) -> GitInfo:
    """Collect HEAD / default-branch / commits-ahead facts for the working tree.

    Pure reads (``rev-parse`` / ``rev-list``): never mutates the tree (K1). The
    default branch may not exist (a brand-new repo with only a feature branch);
    in that case ``main_commit`` is ``None`` and ``commits_ahead`` is 0 — there
    is no baseline to be ahead of.
    """
    head_commit = run_git(["rev-parse", "HEAD"], local_path).strip()
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], local_path).strip()

    main_commit: str | None = None
    commits_ahead = 0
    try:
        main_commit = run_git(
            ["rev-parse", "--verify", "--quiet", default_branch], local_path
        ).strip()
    except SyncError:
        # No default branch in this repo: no baseline to compare against.
        main_commit = None
    if main_commit:
        ahead = run_git(
            ["rev-list", "--count", f"{default_branch}..HEAD"], local_path
        ).strip()
        commits_ahead = int(ahead or "0")
    return GitInfo(
        ref=head_commit,
        branch=branch,
        head_commit=head_commit,
        main_commit=main_commit,
        commits_ahead=commits_ahead,
    )


def _coverage_report(bundle: object, config_dir: Path) -> coverage_mod.CoverageReport:
    """Compute the full :class:`CoverageReport` for ``bundle`` (reuses the real engine).

    Mirrors :func:`custodex.report.build_coverage_rpt`'s pipeline —
    :func:`effective_coverage` → :func:`inventory.discover_files` →
    :func:`inventory.discover_symbols` → :func:`coverage.resolve_coverage`. The
    caller reads :attr:`CoverageReport.percent_files` for the drift summary and
    projects the same report into a stored snapshot via
    :func:`custodex.coverage.coverage_snapshot`. Pure except for the
    engine's reads (K1).
    """
    repo_root = resolve_repo_root(config_dir, bundle.index.root)  # type: ignore[attr-defined]
    cov = effective_coverage(bundle, repo_root)  # type: ignore[arg-type]
    inv = inventory.discover_files(repo_root, include=cov.include, exclude=cov.exclude)
    sym = inventory.discover_symbols(inv, repo_root)
    return coverage_mod.resolve_coverage(bundle.config, sym)  # type: ignore[attr-defined]


def _drift_summary(report: DriftReport, coverage_percent: float) -> dict:
    """Project a :class:`DriftReport` + coverage into the stored ``drift`` dict.

    A compact, JSON-safe summary (the ``sync_runs.drift`` column): the total
    drift count, a per-:class:`DriftKind` breakdown (deterministic key order,
    K10), and the coverage percent. ``ok`` mirrors :attr:`DriftReport.ok`.
    """
    by_kind: dict[str, int] = {}
    for d in report.drifts:
        by_kind[d.kind.value] = by_kind.get(d.kind.value, 0) + 1
    return {
        "ok": report.ok,
        "drift_count": len(report.drifts),
        "by_kind": dict(sorted(by_kind.items())),
        "coverage_percent": round(coverage_percent, 2),
    }


@contextmanager
def _open_repo(
    local_path: Path,
    *,
    mode: str,
    branch: str,
    run_git: _GitRunner,
) -> Iterator[tuple[object, Path, GitInfo]]:
    """Yield ``(bundle, config_dir, git)`` while the source tree is READABLE (K1).

    * **local** — yields against the working tree's ``config/cdmon/`` in place; no
      checkout, nothing to clean up.
    * **git** — materializes ``branch`` in a throwaway worktree of the git
      TOPLEVEL (``git worktree add --detach``) and yields against
      ``<worktree>/<rel>``, where ``rel`` is ``local_path`` relative to the
      toplevel — so a config that lives in a SUBDIR of the repo (e.g. the demo
      under ``demo/``) resolves correctly, and ``rel == "."`` (the config at the
      toplevel) behaves exactly as a top-level checkout. The lazily-read source
      files (drift detection + coverage read files off disk) resolve to the
      default-branch content. On exit — success OR error — the worktree is
      removed (``git worktree remove --force``) and the temp dir is deleted, so
      the user's tree is never disturbed and no stray worktree leaks. If
      ``<branch>`` does not carry ``<rel>/config/cdmon`` (the config isn't
      committed to the default branch yet), a loud :class:`SyncError` is raised
      (K8) — the caller treats git as best-effort and skips.

    A missing ``local_path`` or an unknown ``mode`` is a loud :class:`SyncError`
    (K8). The :class:`GitInfo` is always computed against the ORIGINAL
    ``local_path`` (the working-tree facts), with ``ref`` pinned to HEAD (local)
    or the default-branch tip (git).
    """
    if mode not in _MODES:
        raise SyncError(f"unknown sync mode {mode!r}: expected one of {list(_MODES)!r}")
    if not local_path.is_dir():
        raise SyncError(
            f"repo local_path does not exist or is not a directory: {local_path}"
        )

    git = _git_info(local_path, branch, run_git=run_git)

    if mode == "local":
        config_dir = local_path.joinpath(*_CONFIG_SUBDIR)
        bundle = load_bundle(config_dir)
        git = git.model_copy(update={"ref": git.head_commit})  # working tree HEAD
        yield bundle, config_dir, git
        return

    # git mode: a READ-ONLY checkout of <branch> in a tmp worktree, removed after.
    # The config may live in a SUBDIR of the git repo (e.g. the demo lives under
    # `demo/` of the outer repo). Resolve the git TOPLEVEL and the path of
    # `local_path` relative to it, materialize the toplevel at <branch>, then read
    # the config from `<worktree>/<rel>/config/cdmon` with repo_root at
    # `<worktree>/<rel>`. When `local_path` IS the toplevel, `rel == "."` and this
    # is identical to a top-level checkout.
    toplevel = Path(run_git(["rev-parse", "--show-toplevel"], local_path).strip())
    rel = local_path.resolve().relative_to(toplevel.resolve())

    tmp_root = tempfile.mkdtemp(prefix="cdmon-sync-")
    worktree = Path(tmp_root) / "wt"
    run_git(["worktree", "add", "--detach", str(worktree), branch], toplevel)
    try:
        subroot = worktree / rel
        config_dir = subroot.joinpath(*_CONFIG_SUBDIR)
        if not config_dir.is_dir():
            # The config is absent at <branch>/<rel> (e.g. the demo is not yet
            # committed to the default branch). Loud, typed, and actionable (K8).
            raise SyncError(
                f"no config/cdmon at {branch!r}:{rel.as_posix()} — the config dir "
                f"{config_dir} does not exist on the default branch (is it "
                "committed?)"
            )
        bundle = load_bundle(config_dir)
        # git mode pins the config to the default-branch tip (the baseline).
        git = git.model_copy(update={"ref": git.main_commit})
        yield bundle, config_dir, git
    finally:
        # Always tear the worktree down so we never leave a stray entry behind
        # (K1) — even if load/detect raised on a malformed config at <branch>.
        # The worktree was registered against the TOPLEVEL, so remove it there.
        run_git(["worktree", "remove", "--force", str(worktree)], toplevel)
        shutil.rmtree(tmp_root, ignore_errors=True)


def read_config_at(
    local_path: Path,
    *,
    mode: str,
    branch: str,
    now: str,
    run_git: _GitRunner = _default_run_git,
) -> tuple[object, Path, GitInfo]:
    """Load the repo's config bundle for ``mode`` → ``(bundle, config_dir, git)``.

    The thin public façade over :func:`_open_repo` for callers that only need the
    MERGED config (which is fully realized at load time — no lazy disk access). In
    **git** mode the returned ``config_dir`` points into a worktree that is torn
    down on return, so do NOT read source files off it afterward; the
    drift/coverage pipeline that DOES read source runs inside :func:`run_sync`'s
    own worktree scope. A missing ``local_path`` / unknown ``mode`` is a loud
    :class:`SyncError` (K8).
    """
    with _open_repo(local_path, mode=mode, branch=branch, run_git=run_git) as opened:
        return opened


def _build_rows(
    bundle: object, repo_id: str, *, mode: str, ref: str | None, now: str
) -> tuple[tuple[ConfigDocument, ...], tuple[ConfigCodeRef, ...]]:
    """Project a merged bundle into persisted document + code-ref rows (Y-02).

    Unit attribution comes from :meth:`ConfigBundle.unit_for_document`; the
    document's audience/region keys come from its :class:`DocumentSpec`. Each
    code_ref carries the symbols its spec selected (empty = whole-file). Order is
    the bundle's document order then in-doc ref order (deterministic, K10).
    """
    documents: list[ConfigDocument] = []
    code_refs: list[ConfigCodeRef] = []
    for spec in bundle.config.documents:  # type: ignore[attr-defined]
        unit = bundle.unit_for_document(spec.id)  # type: ignore[attr-defined]
        unit_name = unit.frontmatter.unit if unit is not None else None
        # EPIC OWN: resolve the accountable/durable owner at sync (where the unit's
        # frontmatter owner is available as the per-doc fallback), using the ONE
        # shared precedence so the server mirror never diverges from the engine.
        unit_owner = unit.frontmatter.owner if unit is not None else None
        accountable, durable = resolve_accountable_durable(
            spec.owner, spec.team, spec.dri, unit_owner
        )
        # EPIC SLA: resolve each doc's audience-aware review SLA at sync (where the
        # staleness policy is available), so /staleness grades against the mirror.
        sla_days = resolve_sla_days(
            spec.audience,
            default_days=bundle.config.staleness.default_days,  # type: ignore[attr-defined]
            audience_days=bundle.config.staleness.audience_days,  # type: ignore[attr-defined]
        )
        documents.append(
            ConfigDocument(
                repo_id=repo_id,
                doc_id=spec.id,
                path=spec.path,
                audience=spec.audience.value,
                unit=unit_name,
                owner=spec.owner,
                team=spec.team,
                dri=spec.dri,
                accountable=accountable,
                durable=durable,
                reviewed=spec.reviewed,
                sla_days=sla_days,
                region_keys=tuple(spec.region_keys),
                context_refs=tuple(
                    ConfigContextRef(path=cr.path, note=cr.note)
                    for cr in spec.context_refs
                ),
                sync_kind=mode,
                ref=ref,
                synced_at=now,
            )
        )
        for cref in spec.code_refs:
            code_refs.append(
                ConfigCodeRef(
                    repo_id=repo_id,
                    doc_id=spec.id,
                    path=cref.path,
                    symbols=tuple(cref.symbols),
                    unit=unit_name,
                    sync_kind=mode,
                )
            )
    return tuple(documents), tuple(code_refs)


def run_sync(
    local_path: Path,
    repo_id: str,
    *,
    mode: str,
    default_branch: str = "main",
    now: str,
    run_git: _GitRunner = _default_run_git,
) -> SyncResult:
    """Run one config sync for ``repo_id`` and return the rows + summary (Y-02).

    Loads the bundle for ``mode`` (:func:`read_config_at`), computes drift via
    :func:`drift.detect` and coverage via the real coverage engine, projects the
    documents/code_refs, and builds the :class:`SyncRun` summary:

    * **fully_synced** — git: no drift at the default branch; local:
      ``commits_ahead == 0 AND no drift``.
    * **drift** — the compact :func:`_drift_summary` dict (kinds + coverage %).

    ``now`` stamps ``synced_at`` / ``started_at`` / ``finished_at`` (one injected
    clock, K10 — there is no second wall-clock read). The user's working tree is
    never mutated (K1); every failure is a loud :class:`SyncError` (K8).
    """
    # Run load + detect + coverage INSIDE the worktree scope: drift detection and
    # coverage read source files lazily off disk, so the git-mode checkout must
    # outlive them (the bug a premature teardown would cause). K1: read-only.
    with _open_repo(local_path, mode=mode, branch=default_branch, run_git=run_git) as (
        bundle,
        config_dir,
        git,
    ):
        report = detect(bundle.config, config_dir)  # type: ignore[attr-defined]
        cov_report = _coverage_report(bundle, config_dir)
        documents, code_refs = _build_rows(
            bundle, repo_id, mode=mode, ref=git.ref, now=now
        )
    coverage_percent = cov_report.percent_files
    drift = _drift_summary(report, coverage_percent)
    # Project the SAME report into the stored wire snapshot (T-02 shape) so the
    # central server can refresh the dashboard's Coverage page from this synced
    # tree. Pure projection (no disk reads), stamped with the one injected clock
    # (K10) — there is no second wall-clock read.
    coverage = coverage_mod.coverage_snapshot(cov_report)
    coverage["captured_at"] = now

    fully_synced = report.ok if mode == "git" else report.ok and git.commits_ahead == 0

    run = SyncRun(
        repo_id=repo_id,
        sync_kind=mode,
        ref=git.ref,
        branch=git.branch,
        head_commit=git.head_commit,
        main_commit=git.main_commit,
        commits_ahead=git.commits_ahead,
        fully_synced=fully_synced,
        document_count=len(documents),
        code_ref_count=len(code_refs),
        drift=drift,
        started_at=now,
        finished_at=now,
    )
    return SyncResult(
        documents=documents, code_refs=code_refs, run=run, coverage=coverage
    )
