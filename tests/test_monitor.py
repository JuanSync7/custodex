"""CDM-06 — tests for the Monitor orchestration (offline, deterministic)."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.backends import MockBackend
from code_doc_monitor.blocks import symbol_table
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.drift import DriftKind
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.monitor import Monitor
from code_doc_monitor.reviewlog import read_all
from code_doc_monitor.schema import Verdict
from code_doc_monitor.sinks import FileSink, NullSink

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


def _write_doc(doc_path: Path, surface_body: str, fingerprint: str | None) -> None:
    """Write a doc with a (possibly stale) managed region + fingerprint."""
    fm = ""
    if fingerprint is not None:
        fm = f"---\ncdm:\n  fingerprint: {fingerprint}\n---\n"
    doc_path.write_text(
        f"{fm}# Guide\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        f"{surface_body}\n"
        "<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )


def _make_fixture(
    tmp_path: Path,
    *,
    audience: Audience = Audience.ENG_GUIDE,
    stale: bool = True,
) -> tuple[MonitorConfig, Path, Path, DocumentSpec]:
    """A code file + a doc whose region/fingerprint is stale -> REGION+HASH drift."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    doc_path = tmp_path / "guide.md"

    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=audience,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    surface = build_document_surface(spec, tmp_path)
    if stale:
        # Fingerprint matches the surface (no HASH drift), but the region body
        # is stale -> a single REGION drift the MockBackend can FIX cleanly.
        _write_doc(doc_path, "OUT OF DATE", fingerprint=surface.surface_hash())
    else:
        _write_doc(doc_path, symbol_table(surface), surface.surface_hash())

    config = MonitorConfig(root=".", documents=(spec,))
    return config, tmp_path, doc_path, spec


def test_check_is_pure_no_mutation(tmp_path: Path) -> None:
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path)
    before = doc_path.read_bytes()
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink())

    report = monitor.check()

    assert not report.ok  # drift present
    assert doc_path.read_bytes() == before  # K1: check never mutates


def test_run_apply_fixes_and_records(tmp_path: Path) -> None:
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path)
    log_path = cfg_dir / ".cdmon" / "review-log.jsonl"
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink())

    result = monitor.run(apply=True)

    # The region drift was FIXed and the re-check is clean.
    assert result.remaining == ()
    assert any(h.applied for h in result.handled)
    assert all(h.result.verdict == Verdict.FIX for h in result.handled)

    # A review record was appended to the default log and carries both
    # the original drift and the fix (K5).
    records = read_all(log_path)
    assert len(records) == len(result.records) >= 1
    rec = records[0]
    assert rec.doc_id == "guide"
    assert rec.verdict == Verdict.FIX
    assert rec.fix is not None
    assert rec.detected_at == FIXED_NOW
    assert rec.resolved_at == FIXED_NOW
    assert rec.config_snapshot["backend"] == "mock"


def test_record_id_deterministic_across_runs(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    log_path = cfg_dir / ".cdmon" / "review-log.jsonl"

    # First run records (no apply) -> drift persists, so a second run records
    # the same drift again with an identical record_id (same now + surface).
    Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=False)
    first = read_all(log_path)[0]

    Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=False)
    records = read_all(log_path)
    assert records[0].record_id == records[1].record_id == first.record_id


def test_run_no_apply_records_but_leaves_drift(tmp_path: Path) -> None:
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path)
    before = doc_path.read_bytes()
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink())

    result = monitor.run(apply=False)

    assert result.records  # recorded (K5)
    assert result.remaining  # drift still present
    assert all(not h.applied for h in result.handled)
    assert doc_path.read_bytes() == before  # nothing applied


def test_run_emits_to_sink(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    central = cfg_dir / "central.jsonl"
    monitor = Monitor(config, cfg_dir, now=_now, sink=FileSink(central))

    monitor.run(apply=True)

    emitted = read_all(central)
    assert len(emitted) >= 1
    assert emitted[0].doc_id == "guide"


def test_run_apply_idempotent(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    log_path = cfg_dir / ".cdmon" / "review-log.jsonl"

    Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=True)
    after_first = read_all(log_path)

    # K7: a second run on a now-clean doc finds no drift and writes no record.
    result2 = Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=True)
    assert result2.handled == ()
    assert result2.records == ()
    assert result2.remaining == ()
    assert read_all(log_path) == after_first


def test_escalate_stays_in_remaining(tmp_path: Path) -> None:
    # An UNHEALABLE region (unknown id) -> MockBackend ESCALATEs -> stays.
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    doc_path = tmp_path / "guide.md"
    doc_path.write_text(
        "# Guide\n\n"
        "<!-- CDM:BEGIN prose -->\n"
        "hand-written prose\n"
        "<!-- CDM:END prose -->\n",
        encoding="utf-8",
    )
    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("prose",),
    )
    config = MonitorConfig(root=".", documents=(spec,))
    monitor = Monitor(config, tmp_path, now=_now, sink=NullSink())

    result = monitor.run(apply=True)

    assert any(h.result.verdict == Verdict.ESCALATE for h in result.handled)
    assert any(d.kind == DriftKind.UNHEALABLE for d in result.remaining)


def test_default_backend_and_sink(tmp_path: Path) -> None:
    # No backend/sink injected -> defaults from config (mock + null sink).
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    monitor = Monitor(config, cfg_dir, now=_now)
    assert isinstance(monitor._backend, MockBackend)
    assert isinstance(monitor._sink, NullSink)
    result = monitor.run(apply=True)
    assert result.remaining == ()


def test_default_now_is_iso(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    monitor = Monitor(config, cfg_dir, sink=NullSink())
    # Default now() returns a non-empty ISO-ish timestamp string.
    stamp = monitor._now()
    assert isinstance(stamp, str)
    assert "T" in stamp


def test_apply_default_used_when_apply_none(tmp_path: Path) -> None:
    # apply_default False -> run() with apply=None records but does not apply.
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path)
    before = doc_path.read_bytes()
    result = Monitor(config, cfg_dir, now=_now, sink=NullSink()).run()
    assert result.remaining  # not applied
    assert doc_path.read_bytes() == before


def test_missing_doc_surface_builds(tmp_path: Path) -> None:
    # MISSING_DOC: surface still builds from code, doc_text="" path exercised.
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    spec = DocumentSpec(
        id="guide",
        path="missing.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    config = MonitorConfig(root=".", documents=(spec,))
    result = Monitor(config, tmp_path, now=_now, sink=NullSink()).run(apply=True)
    # The mock backend ESCALATEs a MISSING_DOC (no region to regenerate).
    assert result.handled
    assert any(d.kind == DriftKind.MISSING_DOC for d in result.remaining)


def test_custom_log_path(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    custom = tmp_path / "custom" / "log.jsonl"
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink(), log_path=custom)
    monitor.run(apply=True)
    assert custom.is_file()
    assert read_all(custom)


@pytest.fixture(autouse=True)
def _no_network() -> None:
    # Offline guarantee is structural (MockBackend default); this fixture is a
    # readable marker that these tests never touch the network (K4).
    return None
