"""DEPLOY-MANAGED: the operator runbook ``DEPLOY.md`` is a monitored user-guide doc.

``config/cdmon/deploy.yaml`` declares ``DEPLOY.md`` as a ``user-guide`` document
whose code_refs select every settings model the server reads, with NO managed
region, so it is tracked by the whole-doc fingerprint over that surface (the
same shape as the README, FEAT-CONFIGV2-016). A public settings change (a new
key, a changed default) drifts the runbook; ``monitor --apply`` restamps it and
records a ``ReviewRecord`` for the human (K5); a re-run is a no-op (K7).

Scope of the "prose untouched" claim: it is asserted under the offline ``mock``
backend only. A real backend receives a whole-doc fix request and may rewrite
prose — that is the reviewer's job, and the content checks in
``tests/unit/test_deploy_runbook.py`` are what keep a stale body from passing.

Features: FEAT-QUALITY-010
"""

from __future__ import annotations

import ast
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import BaseModel

from custodex.config import (
    Audience,
    DocumentSpec,
    load_bundle,
    load_config_dir,
    unit_for_path,
)
from custodex.entities import corpus_entities
from custodex.inventory import discover_files
from custodex.monitor import Monitor
from custodex.settings import Settings
from tests._repo import REPO_ROOT
from tests.unit.test_deploy_runbook import _body, _reachable_models

_CONFIG_DIR = REPO_ROOT / "config" / "cdmon"
_DOC_ID = "deploy"
_SETTINGS = "custodex/settings.py"
_NOW = "2026-06-01T00:00:00Z"


def _deploy_doc() -> DocumentSpec:
    cfg = load_config_dir(_CONFIG_DIR)
    hits = [d for d in cfg.documents if d.id == _DOC_ID]
    assert len(hits) == 1, f"expected one {_DOC_ID!r} document"
    return hits[0]


def _module_file(model: type[BaseModel]) -> str:
    mod = sys.modules[model.__module__]
    assert mod.__file__ is not None
    return Path(mod.__file__).resolve().relative_to(REPO_ROOT.resolve()).as_posix()


# ── the declaration ──────────────────────────────────────────────────────────


def test_deploy_is_a_user_guide_doc_selecting_every_settings_model() -> None:
    doc = _deploy_doc()
    assert doc.path == "DEPLOY.md"
    assert doc.audience is Audience.USER_GUIDE
    assert doc.region_keys == ()  # fingerprint-tracked only; no managed region

    expected: dict[str, set[str]] = {}
    for model in _reachable_models(Settings):
        expected.setdefault(_module_file(model), set()).add(model.__name__)
    selected: dict[str, set[str]] = {}
    for ref in doc.code_refs:
        selected.setdefault(ref.path, set()).update(ref.symbols)
    # Exactly the reachable models, each under its OWN module's code_ref: a model
    # added (or moved to another module) without a code_ref fails here.
    assert selected == expected


def test_deploy_unit_owns_the_settings_module_and_nothing_it_does_not_track() -> None:
    """The deploy unit owns the module ``Settings`` lives in, and every file it owns
    is one its doc tracks. A code_ref MAY point into another unit's file (a model
    nested from elsewhere) without taking that file over."""
    bundle = load_bundle(_CONFIG_DIR)
    units = [u for u in bundle.units if u.frontmatter.unit == _DOC_ID]
    assert len(units) == 1
    refs = {r.path for d in units[0].documents for r in d.code_refs}
    inv = discover_files(REPO_ROOT, include=("custodex/**",))
    assert inv.files, "inventory is empty — the probe is broken"
    owned = {
        f.path
        for f in inv.files
        if (u := unit_for_path(bundle, f.path)) is not None
        and u.frontmatter.unit == _DOC_ID
    }
    assert _module_file(Settings) in owned
    assert owned <= refs, sorted(owned - refs)


def test_deploy_doc_is_in_sync_and_lint_clean() -> None:
    from custodex.layout import lint_config

    _deploy_doc()  # not vacuous: the doc is declared
    cfg = load_config_dir(_CONFIG_DIR)
    drifts = [
        d for d in Monitor(cfg, _CONFIG_DIR).check().drifts if d.doc_id == _DOC_ID
    ]
    assert drifts == []
    issues = [i for i in lint_config(cfg, REPO_ROOT) if i.doc_id == _DOC_ID]
    assert issues == [], [f"{i.code.value} — {i.detail}" for i in issues]


def test_deploy_doc_mentions_resolve() -> None:
    bundle = load_bundle(_CONFIG_DIR)
    results = [
        r for r in corpus_entities(bundle.config, REPO_ROOT) if r.doc_id == _DOC_ID
    ]
    assert len(results) == 1
    mentions = results[0].mentions
    unresolved = [(m.line, m.text) for m in mentions if not m.resolved]
    assert unresolved == []
    resolved = {m.text: m.entity_id for m in mentions if m.resolved}
    for model in _reachable_models(Settings):
        assert resolved.get(model.__name__) == (
            f"symbol {_module_file(model)}#{model.__name__}"
        )


# ── drift and reheal on a copy ───────────────────────────────────────────────


def _copy_tree(dst: Path) -> Path:
    from tests.system.test_dogfood import _copy_dogfood_tree

    config_dir = _copy_dogfood_tree(dst)
    if not (dst / "DEPLOY.md").exists():
        shutil.copy2(REPO_ROOT / "DEPLOY.md", dst / "DEPLOY.md")
    return config_dir


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    hits = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
    assert len(hits) == 1, name
    return hits[0]


def _bump_default_port(src: str) -> str:
    tree = ast.parse(src)
    port = Settings().server.port
    fields = [
        n
        for n in _class(tree, "ServerSettings").body
        if isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and n.target.id == "port"
    ]
    assert len(fields) == 1 and fields[0].value is not None
    lines = src.split("\n")
    i = fields[0].value.lineno - 1
    assert str(port) in lines[i]
    lines[i] = lines[i].replace(str(port), str(port + 1), 1)
    return "\n".join(lines)


def _add_worker_key(src: str) -> str:
    tree = ast.parse(src)
    body = _class(tree, "WorkerSettings").body
    fields = [n for n in body if isinstance(n, ast.AnnAssign)]
    assert fields
    last = fields[-1]
    assert last.end_lineno is not None
    lines = src.split("\n")
    indent = " " * last.col_offset
    lines.insert(last.end_lineno, f"{indent}probe_new_key: int = 1")
    return "\n".join(lines)


def _comment_in_server_settings(src: str) -> str:
    tree = ast.parse(src)
    body = _class(tree, "ServerSettings").body
    fields = [n for n in body if isinstance(n, ast.AnnAssign)]
    assert fields
    lines = src.split("\n")
    indent = " " * fields[0].col_offset
    lines.insert(fields[0].lineno - 1, f"{indent}# probe: a comment-only change")
    return "\n".join(lines)


_PUBLIC_EDITS: dict[str, Callable[[str], str]] = {
    "changed-default": _bump_default_port,
    "new-key": _add_worker_key,
}


@pytest.mark.parametrize("edit", sorted(_PUBLIC_EDITS))
def test_a_public_settings_change_drifts_only_the_runbook_and_reheals(
    edit: str, tmp_path: Path
) -> None:
    dst = tmp_path / "proj"
    config_dir = _copy_tree(dst)
    cfg = load_config_dir(config_dir)
    assert Monitor(cfg, config_dir).check().ok  # the copy starts clean

    doc = dst / "DEPLOY.md"
    original = doc.read_text(encoding="utf-8")
    settings = dst / _SETTINGS
    before = settings.read_text(encoding="utf-8")
    after = _PUBLIC_EDITS[edit](before)
    assert after != before
    settings.write_text(after, encoding="utf-8")

    drifts = Monitor(cfg, config_dir).check().drifts
    assert {(d.doc_id, d.kind.value) for d in drifts} == {(_DOC_ID, "HASH")}

    first = Monitor(cfg, config_dir, now=lambda: _NOW).run(apply=True, tiered=False)
    assert first.records, "a ReviewRecord is written for the human (K5)"
    assert Monitor(cfg, config_dir).check().ok
    healed = doc.read_text(encoding="utf-8")
    # Mock backend: only the front-matter stamp moved, never the prose.
    assert _body(healed) == _body(original)
    assert healed != original

    again = Monitor(cfg, config_dir, now=lambda: _NOW).run(apply=True, tiered=False)
    assert not again.records  # K7: nothing new to record
    assert doc.read_text(encoding="utf-8") == healed


def test_a_comment_only_settings_change_does_not_drift_the_runbook(
    tmp_path: Path,
) -> None:
    dst = tmp_path / "proj"
    config_dir = _copy_tree(dst)
    cfg = load_config_dir(config_dir)
    assert any(d.id == _DOC_ID for d in cfg.documents)  # not vacuous
    settings = dst / _SETTINGS
    settings.write_text(
        _comment_in_server_settings(settings.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    drifts = [d for d in Monitor(cfg, config_dir).check().drifts if d.doc_id == _DOC_ID]
    assert drifts == []  # K3: a user-guide is not flagged for a comment-only change
