"""X-CONTAIN — the editor writers heal the file detect grades.

``generate.apply_record_fix`` (E-07) and ``generate.apply_edits_to_disk`` (E-06)
joined ``root / path`` raw, so a ``ghost/..`` doc path crashed (or conjured a
``ghost/`` dir and scaffolded over the prose) and a ``link/..`` doc path wrote a
file OUTSIDE the doc detect grades. Both now write ``doc_path(root, path)``, as
does ``docwriter.write_and_register`` (``cdx write-doc``), whose refuse-to-
overwrite guard checks the same file it writes.

Features: FEAT-CONFIGV2-019
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.config import Audience, CodeRef, DocumentSpec, load_config_dir
from custodex.docwriter import write_and_register
from custodex.drift import detect
from custodex.errors import ConfigError
from custodex.generate import apply_edits_to_disk, apply_record_fix
from custodex.monitor import Monitor
from custodex.schema import ReviewRecord, Verdict
from custodex.server.edits import AddCodeRefEdit, EditCodeRef
from custodex.sinks import NullSink

_NOW = "2026-10-10T00:00:00Z"

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: contain
generated-by: cdx
updated: "2026-10-10"
---
root: "../.."
version: "2.0.0"
apply_default: false
backend: {kind: mock}
central: {sink: none}
units:
  - file: core.yaml
ignore: ignore.yaml
"""
_CORE_UNIT_YAML = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "Core"
owner: eng-platform
created: "2026-10-10"
updated: "2026-10-10"
---
dir-covered:
  - src
source-files-format:
  - ".py"
documents:
  - id: guide
    path: {path}
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: src/lib.py
"""
_IGNORE_YAML = """\
---
cdmon-config-version: "2.0.0"
source: "manual"
updated: "2026-10-10"
---
gitignore: false
patterns: []
"""
_LIB = 'def connect(host: str) -> None:\n    """Open."""\n'
_DOC = (
    "# Guide\n\n> How to connect.\n\n"
    "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
)
_DECOY = (
    "# Decoy\n\n> Not this file.\n\n"
    "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
)
FORMS = {"ghost": "ghost/../docs/guide.md", "link": "link/../docs/guide.md"}


def _repo(tmp_path: Path, form: str) -> Path:
    repo = tmp_path / "repo"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(_INDEX_YAML, encoding="utf-8")
    (cfg / "core.yaml").write_text(
        _CORE_UNIT_YAML.format(path=FORMS[form]), encoding="utf-8"
    )
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "lib.py").write_text(_LIB, encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text(_DOC, encoding="utf-8")
    if form == "link":
        hub = tmp_path / "hub"
        (hub / "sub").mkdir(parents=True)
        (hub / "docs").mkdir()
        (hub / "docs" / "guide.md").write_text(_DECOY, encoding="utf-8")
        (repo / "link").symlink_to(hub / "sub", target_is_directory=True)
    return repo


def _decoy(tmp_path: Path) -> bytes | None:
    hub_doc = tmp_path / "hub" / "docs" / "guide.md"
    return hub_doc.read_bytes() if hub_doc.is_file() else None


def _drifts(repo: Path) -> tuple:
    config_dir = repo / "config" / "cdmon"
    return detect(load_config_dir(config_dir), config_dir).drifts


def _fix_record(repo: Path) -> ReviewRecord:
    config_dir = repo / "config" / "cdmon"
    monitor = Monitor(
        load_config_dir(config_dir), config_dir, now=lambda: _NOW, sink=NullSink()
    )
    result = monitor.run(apply=False)
    return next(
        r
        for r in result.records
        if r.verdict is Verdict.FIX and r.fix and r.fix.new_doc_text is not None
    )


@pytest.mark.parametrize("form", FORMS)
def test_apply_record_fix_heals_the_doc_detect_grades(
    tmp_path: Path, form: str
) -> None:
    # Feature: FEAT-CONFIGV2-019
    repo = _repo(tmp_path, form)
    decoy = _decoy(tmp_path)
    record = _fix_record(repo)
    assert record.doc_path == FORMS[form]

    result = apply_record_fix(repo, record, now=_NOW)
    assert result.applied is True
    assert result.doc_path == record.doc_path
    assert _drifts(repo) == ()
    text = (repo / "docs" / "guide.md").read_text(encoding="utf-8")
    assert "> How to connect." in text and "connect" in text.split("BEGIN", 1)[1]

    again = apply_record_fix(repo, record, now=_NOW)
    assert again.applied is False
    assert again.diff == ""
    assert _decoy(tmp_path) == decoy
    assert not (repo / "ghost").exists()


@pytest.mark.parametrize("form", FORMS)
def test_apply_record_fix_diff_names_the_file_it_wrote(
    tmp_path: Path, form: str
) -> None:
    """The diff headers name the file written, ``docs/guide.md`` (the docs-PR
    path, the sync_pr patch headers); ``ApplyFixResult.doc_path`` keeps the
    record's config spelling, the record's identity."""
    # Feature: FEAT-CONFIGV2-019
    repo = _repo(tmp_path, form)
    record = _fix_record(repo)
    result = apply_record_fix(repo, record, now=_NOW)
    assert result.doc_path == FORMS[form]
    headers = [ln for ln in result.diff.splitlines() if ln[:4] in ("--- ", "+++ ")]
    assert headers == ["--- a/docs/guide.md", "+++ b/docs/guide.md"]


@pytest.mark.parametrize("form", FORMS)
def test_apply_edits_to_disk_keeps_prose_and_heals_the_real_doc(
    tmp_path: Path, form: str
) -> None:
    # Feature: FEAT-CONFIGV2-019
    repo = _repo(tmp_path, form)
    decoy = _decoy(tmp_path)
    (repo / "src" / "extra.py").write_text(
        'def extra(n: int) -> int:\n    """More."""\n    return n\n', encoding="utf-8"
    )
    edit = AddCodeRefEdit(
        unit="core", doc_id="guide", ref=EditCodeRef(path="src/extra.py")
    )
    result = apply_edits_to_disk(repo, [edit], now=_NOW)
    assert result.affected_docs == (FORMS[form],)
    text = (repo / "docs" / "guide.md").read_text(encoding="utf-8")
    assert "> How to connect." in text
    assert "extra" in text.split("BEGIN", 1)[1]
    assert _drifts(repo) == ()
    assert _decoy(tmp_path) == decoy
    assert not (repo / "ghost").exists()


def _fresh(path: str) -> DocumentSpec:
    return DocumentSpec(
        id="fresh",
        path=path,
        audience=Audience.ENG_GUIDE,
        region_keys=("symbols",),
        code_refs=(CodeRef(path="src/lib.py"),),
    )


@pytest.mark.parametrize("form", FORMS)
def test_write_and_register_writes_the_file_detect_grades(
    tmp_path: Path, form: str
) -> None:
    """``cdx write-doc`` on a dotdot path: born in-sync on the file detect reads,
    no ``ghost/`` dir conjured, the decoy across the link never written (and
    its presence never mistaken for "already exists")."""
    # Feature: FEAT-CONFIGV2-019
    repo = _repo(tmp_path, form)
    path = FORMS[form].replace("guide.md", "fresh.md")
    if form == "link":
        (tmp_path / "hub" / "docs" / "fresh.md").write_text(_DECOY, encoding="utf-8")
    decoys = sorted((tmp_path / "hub").rglob("*")) if form == "link" else []
    before = {p: p.read_bytes() for p in decoys if p.is_file()}
    config_dir = repo / "config" / "cdmon"

    written = write_and_register(config_dir, unit="core", spec=_fresh(path), now=_NOW)
    assert written == repo / "docs" / "fresh.md"
    assert written.is_file()
    assert [d for d in _drifts(repo) if d.doc_id == "fresh"] == []
    assert not (repo / "ghost").exists()
    assert {p: p.read_bytes() for p in decoys if p.is_file()} == before


@pytest.mark.parametrize("form", FORMS)
def test_write_and_register_refuses_to_overwrite_the_normalised_file(
    tmp_path: Path, form: str
) -> None:
    """The K8 refuse-to-overwrite guard checks the file it would write: a
    ``ghost/..`` spelling of an existing doc used to slip past it and scaffold
    over the hand-written prose."""
    # Feature: FEAT-CONFIGV2-019
    repo = _repo(tmp_path, form)
    if form == "link":
        (tmp_path / "hub" / "docs" / "guide.md").unlink()  # only the real file
    config_dir = repo / "config" / "cdmon"
    core = (config_dir / "core.yaml").read_bytes()
    original = (repo / "docs" / "guide.md").read_bytes()
    with pytest.raises(ConfigError, match="already exists"):
        write_and_register(config_dir, unit="core", spec=_fresh(FORMS[form]), now=_NOW)
    assert (repo / "docs" / "guide.md").read_bytes() == original
    assert (config_dir / "core.yaml").read_bytes() == core
