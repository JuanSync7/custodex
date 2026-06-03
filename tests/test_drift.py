"""Tests for code_doc_monitor.drift (CDM-03).

Detection is pure and side-effect free (K1). Covers each DriftKind, the
healable/audience fields, and — end to end through `detect` — the audience rule
(K3): a docstring-only edit drifts an eng-guide doc but NOT a user-guide doc
over the same code file.
"""

from __future__ import annotations

from pathlib import Path

from code_doc_monitor.blocks import expected_region, symbol_table
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.drift import Drift, DriftKind, DriftReport, detect
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.manifest import (
    render_doc,
    set_fingerprint,
    set_region,
)

CODE_V1 = '''\
def greet(name: str) -> str:
    """Say hello."""
    return f"hi {name}"


def _hidden(x):
    """Internal."""
    return x
'''

# Same public signatures; only a docstring and a private body changed (K3).
CODE_V2 = '''\
def greet(name: str) -> str:
    """Say hello to the user politely."""
    return f"hi {name}"


def _hidden(x):
    """Internal, now different."""
    return x + 1
'''


def _setup(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    return root


def _write_code(root: Path, text: str) -> None:
    (root / "src" / "mod.py").write_text(text, encoding="utf-8")


def _doc_spec(doc_id: str, audience: Audience) -> DocumentSpec:
    return DocumentSpec(
        id=doc_id,
        path=f"docs/{doc_id}.md",
        audience=audience,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
    )


def _synced_doc_text(spec: DocumentSpec, root: Path) -> str:
    """Build doc text whose region + fingerprint match the current surface."""
    surface = build_document_surface(spec, root)
    body = "# Title\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    return render_doc(meta, body)


def _config(root: Path, specs: tuple[DocumentSpec, ...]) -> MonitorConfig:
    return MonitorConfig(root="repo", documents=specs)


def test_detect_clean(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    assert report.ok
    assert report.drifts == ()
    assert "clean" in report.summary().lower() or "no drift" in report.summary().lower()


def test_detect_missing_doc(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    report = detect(_config(root, (spec,)), tmp_path)
    assert not report.ok
    (d,) = report.drifts
    assert d.kind is DriftKind.MISSING_DOC
    assert d.healable is True
    assert d.audience is Audience.ENG_GUIDE
    assert d.doc_id == "eng-guide"
    assert "MISSING_DOC" in report.summary()


def test_detect_hash_drift(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")
    # Change the code so the surface hash moves.
    _write_code(root, CODE_V2)
    report = detect(_config(root, (spec,)), tmp_path)
    kinds = {d.kind for d in report.drifts}
    assert DriftKind.HASH in kinds
    hash_drift = next(d for d in report.drifts if d.kind is DriftKind.HASH)
    assert hash_drift.healable is True
    assert hash_drift.detail


def test_detect_region_drift(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    text = _synced_doc_text(spec, root)
    # Corrupt only the region body, keep the fingerprint correct.
    text = text.replace(
        text.split("<!-- CDM:BEGIN symbols -->\n")[1].split("<!-- CDM:END symbols -->")[
            0
        ],
        "stale region contents\n",
    )
    (root / spec.path).write_text(text, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    region_drift = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region_drift.region_id == "symbols"
    assert region_drift.healable is True


def test_detect_unhealable_unknown_region(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "mystery"),
    )
    surface = build_document_surface(spec, root)
    body = (
        "# Title\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        "<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN mystery -->\nhand written\n<!-- CDM:END mystery -->\n"
    )
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    unhealable = next(d for d in report.drifts if d.kind is DriftKind.UNHEALABLE)
    assert unhealable.healable is False
    assert unhealable.region_id == "mystery"


def test_detect_is_side_effect_free(tmp_path: Path) -> None:
    """K1: detect never mutates the doc file."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    text = _synced_doc_text(spec, root)
    (root / spec.path).write_text(text, encoding="utf-8")
    _write_code(root, CODE_V2)
    detect(_config(root, (spec,)), tmp_path)
    assert (root / spec.path).read_text(encoding="utf-8") == text


def test_audience_split_docstring_only_change(tmp_path: Path) -> None:
    """K3 end-to-end: two docs over the same file, different audiences.

    Editing only a docstring (and a private body) must keep the user-guide doc
    clean while drifting the eng-guide doc.
    """
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    user_spec = _doc_spec("user-guide", Audience.USER_GUIDE)
    eng_spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    for spec in (user_spec, eng_spec):
        (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")

    # Edit only the docstring + a private symbol body.
    _write_code(root, CODE_V2)

    report = detect(_config(root, (user_spec, eng_spec)), tmp_path)
    by_doc = {d.doc_id for d in report.drifts}
    # User-guide stays clean; eng-guide drifts.
    assert "user-guide" not in by_doc
    assert "eng-guide" in by_doc
    eng_drift = next(d for d in report.drifts if d.doc_id == "eng-guide")
    assert eng_drift.audience is Audience.ENG_GUIDE


def test_drift_report_summary_and_ok() -> None:
    empty = DriftReport(drifts=())
    assert empty.ok
    d = Drift(
        kind=DriftKind.HASH,
        doc_id="x",
        doc_path="docs/x.md",
        detail="moved",
        audience=Audience.ENG_GUIDE,
    )
    rep = DriftReport(drifts=(d,))
    assert not rep.ok
    assert "x" in rep.summary()


def test_detect_ignores_region_not_declared_by_spec(tmp_path: Path) -> None:
    """A region present in the doc but absent from spec.region_keys is ignored."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=(),  # declares NO managed regions
    )
    surface = build_document_surface(spec, root)
    body = "# T\n\n<!-- CDM:BEGIN symbols -->\nstale\n<!-- CDM:END symbols -->\n"
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    # The undeclared region is not graded, so the report is clean.
    assert report.ok


def test_expected_region_unknown_id_is_none() -> None:
    spec = DocumentSpec(
        id="e",
        path="docs/e.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(),
    )
    surface = build_document_surface(spec, Path("."))
    assert expected_region("nope", surface) is None
    assert expected_region("symbols", surface) is not None
