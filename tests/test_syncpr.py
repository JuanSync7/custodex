"""C-01 — tests for the `sync_pr` doc-patch producer (offline, deterministic).

The unit-of-test is `syncpr.sync_pr(monitor, *, dry_run=...)` orchestrating around
a real `Monitor` on a real temp-repo fixture: drift heals + emits a unified diff
of exactly the changed docs; `--dry-run` emits the SAME patch but leaves the doc
tree byte-identical; a clean/second run emits an empty patch (idempotent, K7); and
a human-owned region body never appears in the patch (authority respected, B-02).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from code_doc_monitor.backends import BackendResult, FixRequest
from code_doc_monitor.blocks import symbol_table
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    RegionMode,
)
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.monitor import Monitor
from code_doc_monitor.schema import ProposedFix, Verdict
from code_doc_monitor.sinks import NullSink
from code_doc_monitor.syncpr import SyncResult, should_sync, sync_pr

FIXED_NOW = "2026-06-01T00:00:00+00:00"


def _now() -> str:
    return FIXED_NOW


CODE = '''\
"""A tiny module."""


def public_fn(x: int) -> int:
    """Double x."""
    return x * 2


class Widget:
    """A widget."""

    def spin(self) -> None:
        """Spin it."""
'''


def _write_doc(doc_path: Path, surface_body: str, fingerprint: str) -> None:
    doc_path.write_text(
        f"---\ncdm:\n  fingerprint: {fingerprint}\n---\n# Guide\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        f"{surface_body}\n"
        "<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )


def _make_fixture(
    tmp_path: Path, *, stale: bool = True
) -> tuple[MonitorConfig, Path, Path, DocumentSpec]:
    """A code file + a doc whose region body is stale -> one FIXable REGION drift."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    doc_path = tmp_path / "guide.md"
    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    surface = build_document_surface(spec, tmp_path)
    body = "OUT OF DATE" if stale else symbol_table(surface)
    _write_doc(doc_path, body, surface.surface_hash())
    config = MonitorConfig(root=".", documents=(spec,))
    return config, tmp_path, doc_path, spec


def _monitor(config: MonitorConfig, cfg_dir: Path) -> Monitor:
    return Monitor(config, cfg_dir, now=_now, sink=NullSink())


def test_sync_pr_with_drift_heals_and_emits_patch(tmp_path: Path) -> None:
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path, stale=True)
    result = sync_pr(_monitor(config, cfg_dir))

    assert isinstance(result, SyncResult)
    assert result.changed_paths == ("guide.md",)
    # The patch is a unified diff naming the doc and carrying the healed line.
    assert "a/guide.md" in result.patch
    assert "b/guide.md" in result.patch
    assert "OUT OF DATE" in result.patch  # removed line
    assert "public_fn" in result.patch  # added (healed) content
    assert "doc(s) updated" in result.summary
    # The file on disk is now healed (apply mode).
    assert "OUT OF DATE" not in doc_path.read_text(encoding="utf-8")
    assert "public_fn" in doc_path.read_text(encoding="utf-8")


def test_sync_pr_dry_run_same_patch_tree_unchanged(tmp_path: Path) -> None:
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path, stale=True)
    before = doc_path.read_bytes()

    result = sync_pr(_monitor(config, cfg_dir), dry_run=True)

    # Same patch a non-dry run would produce...
    assert result.changed_paths == ("guide.md",)
    assert "OUT OF DATE" in result.patch
    assert "public_fn" in result.patch
    # ...but the tree is byte-identical to the start (K1).
    assert doc_path.read_bytes() == before


def test_sync_pr_dry_run_then_apply_matches(tmp_path: Path) -> None:
    """The dry-run patch equals the patch the real apply produces (deterministic)."""
    config, cfg_dir, _, _ = _make_fixture(tmp_path, stale=True)
    dry = sync_pr(_monitor(config, cfg_dir), dry_run=True)

    # The tree is unchanged by the dry run, so a real apply on the same tree
    # produces a byte-identical patch (determinism, K10).
    applied = sync_pr(_monitor(config, cfg_dir))

    assert dry.patch == applied.patch
    assert dry.changed_paths == applied.changed_paths


def test_sync_pr_clean_repo_empty_patch(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path, stale=False)
    result = sync_pr(_monitor(config, cfg_dir))

    assert result.patch == ""
    assert result.changed_paths == ()
    assert result.summary == "clean"


def test_sync_pr_idempotent_second_run_empty(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path, stale=True)
    first = sync_pr(_monitor(config, cfg_dir))
    assert first.changed_paths == ("guide.md",)

    # K7: a second run on the now-healed tree heals nothing -> empty patch.
    second = sync_pr(_monitor(config, cfg_dir))
    assert second.patch == ""
    assert second.changed_paths == ()
    assert second.summary == "clean"


def test_sync_pr_human_region_body_not_in_patch(tmp_path: Path) -> None:
    """B-02 regression guard: a human-owned region body is never in the patch."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    doc_path = tmp_path / "guide.md"
    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.HUMAN},
    )
    surface = build_document_surface(spec, tmp_path)
    human_body = "HUMAN OWNED PROSE the engine must never touch"
    _write_doc(doc_path, human_body, surface.surface_hash())
    config = MonitorConfig(root=".", documents=(spec,))

    result = sync_pr(_monitor(config, cfg_dir=tmp_path))

    # The human body is not rewritten -> it must not appear as a -/+ diff line.
    assert human_body not in result.patch
    # And the on-disk human region is untouched.
    assert human_body in doc_path.read_text(encoding="utf-8")


class _CreatingBackend:
    """A backend that heals a MISSING_DOC by authoring the whole file (creates it)."""

    def propose(self, req: FixRequest) -> BackendResult:
        return BackendResult(
            verdict=Verdict.FIX,
            cause="missing doc authored",
            fix=ProposedFix(
                new_doc_text="# Created\n\nfresh stub body\n",
                rationale="seed the missing doc",
            ),
        )


def test_sync_pr_dry_run_deletes_newly_created_stub(tmp_path: Path) -> None:
    """A run that CREATES a doc (heal of a missing doc) is deleted on dry-run (K1)."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    new_doc = tmp_path / "created.md"
    spec = DocumentSpec(
        id="guide",
        path="created.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    config = MonitorConfig(root=".", documents=(spec,))
    assert not new_doc.exists()
    monitor = Monitor(
        config, tmp_path, now=_now, sink=NullSink(), backend=_CreatingBackend()
    )

    result = sync_pr(monitor, dry_run=True)

    # The patch shows the file being added (diff against empty), but the run that
    # CREATED it was reverted: the stub is deleted, tree byte-identical to start.
    assert result.changed_paths == ("created.md",)
    assert "fresh stub body" in result.patch
    assert not new_doc.exists()


def test_sync_pr_apply_creates_missing_doc(tmp_path: Path) -> None:
    """Without dry-run, a heal that authors a missing doc leaves it on disk."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    new_doc = tmp_path / "created.md"
    spec = DocumentSpec(
        id="guide",
        path="created.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    config = MonitorConfig(root=".", documents=(spec,))
    monitor = Monitor(
        config, tmp_path, now=_now, sink=NullSink(), backend=_CreatingBackend()
    )

    result = sync_pr(monitor)

    assert result.changed_paths == ("created.md",)
    assert new_doc.is_file()
    assert "fresh stub body" in new_doc.read_text(encoding="utf-8")


def test_sync_result_is_frozen(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path, stale=False)
    result = sync_pr(_monitor(config, cfg_dir))
    try:
        result.patch = "mutated"  # type: ignore[misc]
    except Exception:  # pydantic ValidationError on a frozen model
        return
    raise AssertionError("SyncResult should be frozen")


# --- C-04: should_sync — the structural loop-breaker (pure, deterministic) -----


def _doc_config() -> MonitorConfig:
    """A config managing two doc paths (used by the should_sync truth-table)."""
    return MonitorConfig(
        root=".",
        documents=(
            DocumentSpec(
                id="user-guide",
                path="docs/user-guide.md",
                audience=Audience.USER_GUIDE,
            ),
            DocumentSpec(
                id="eng-guide",
                path="docs/eng-guide.md",
                audience=Audience.ENG_GUIDE,
            ),
        ),
    )


def test_should_sync_doc_only_is_false() -> None:
    """Every changed file is a managed doc -> a bot doc-only commit -> skip heal."""
    cfg = _doc_config()
    assert should_sync(["docs/user-guide.md", "docs/eng-guide.md"], cfg) is False


def test_should_sync_mixed_is_true() -> None:
    """One non-doc file among the docs -> real code change -> proceed with heal."""
    cfg = _doc_config()
    assert should_sync(["docs/user-guide.md", "src/app.py"], cfg) is True


def test_should_sync_empty_is_false() -> None:
    """Nothing changed -> nothing to do -> skip."""
    assert should_sync([], _doc_config()) is False


def test_should_sync_normalizes_separators_and_dot_slash() -> None:
    """`./docs/x.md` / mixed separators normalize to the managed POSIX path."""
    cfg = _doc_config()
    # ./-prefixed + back-slash variants of the SAME managed doc -> still doc-only.
    assert should_sync(["./docs/user-guide.md"], cfg) is False
    assert should_sync(["docs\\user-guide.md"], cfg) is False
    # A non-doc path even with a ./ prefix -> proceed.
    assert should_sync(["./src/app.py"], cfg) is True


def test_should_sync_single_non_doc_is_true() -> None:
    assert should_sync(["README.md"], _doc_config()) is True


# --- C-02: the CI gate stays valid YAML and carries the docs:gate job ----------


def test_gitlab_ci_is_valid_yaml_with_docs_gate() -> None:
    """`.gitlab-ci.yml` parses and defines the offline docs:gate job (C-02)."""
    ci_path = Path(__file__).resolve().parent.parent / ".gitlab-ci.yml"
    data = yaml.safe_load(ci_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "docs:gate" in data
    gate = data["docs:gate"]
    # Runs the two offline doc gates against the dogfood config.
    script = "\n".join(gate["script"])
    assert "cdmon check" in script
    assert "cdmon lint" in script
    # On MRs + branches, like tests:offline.
    assert gate["rules"]


def test_gitlab_ci_heal_job_uses_should_sync_loop_guard() -> None:
    """C-04: a heal/sync job guards on `cdmon should-sync` to skip doc-only commits."""
    ci_path = Path(__file__).resolve().parent.parent / ".gitlab-ci.yml"
    text = ci_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict)  # still valid YAML
    # Some heal job runs the loop-safety guard before opening a docs MR.
    assert "should-sync" in text
    # And the guard is wired to the diff of the push (provider-agnostic file list).
    assert "git diff --name-only" in text
