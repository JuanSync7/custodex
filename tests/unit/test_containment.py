"""X-CONTAIN — one path formula for a doc, and a containment gate for writers.

Two helpers in :mod:`custodex.config`:

* :func:`doc_path` — ``normpath(root / rel)``: lexical, unconfined, pure, never
  follows a link. The converted readers and the config owner's own writers use
  it, so a ``ghost/../docs/guide.md`` or ``link/../docs/guide.md`` path names
  ONE file for detect, the bundle, the index lane, the suspect-link lane, the
  entity lane, monitor's heal, ``sync_pr``'s diff and the docs-PR commit
  (``cdx lint``/``lint --fix``/``new-doc`` are a queued follow-up). Before
  this slice detect, monitor and docdeps joined the raw string (the kernel
  resolves ``link/..`` PHYSICALLY, ``ghost/..`` not at all) while the OKF
  bundle normalised — two files, one id.
* :func:`resolve_within` — the writer's gate for configs a writer does NOT own:
  the lexical path, or ``None`` when it is not provably a proper descendant of
  the root (lexically AND physically, links resolved).

Features: FEAT-CONFIGV2-019, FEAT-CONFIGV2-020
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from custodex.build import build
from custodex.config import (
    Audience,
    CodeRef,
    DocDepsConfig,
    DocEdge,
    DocumentSpec,
    MonitorConfig,
    RegionColumn,
    RegionTemplate,
    doc_path,
    resolve_within,
)
from custodex.docdeps import (
    SuspectStatus,
    detect_suspect_links,
    infer_edges_from_links,
    stamp_edges,
)
from custodex.drift import DriftKind, auto_routable_docs, detect, mechanical_docs
from custodex.entities import corpus_entities
from custodex.extract import build_document_surface
from custodex.heal import regenerate_regions
from custodex.index import render_index
from custodex.monitor import Monitor
from custodex.okf import render_bundle
from custodex.pr import plan_docs_pr
from custodex.sinks import NullSink
from custodex.syncpr import should_sync, sync_pr
from custodex.workers import suggest_fixes_tick

_NOW = "2026-10-10T00:00:00Z"

# --------------------------------------------------------------------------- #
# resolve_within — the writer's gate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "rel",
    ["..", "/etc/passwd", "a/../../x", "", ".", "./", "../x.md", "d/../..", "//x"],
)
def test_resolve_within_rejects_escapes_and_the_root_itself(
    tmp_path: Path, rel: str
) -> None:
    # Feature: FEAT-CONFIGV2-020
    assert resolve_within(tmp_path, rel) is None


@pytest.mark.parametrize(
    "rel", ["docs/x.md", "docs/../docs/x.md", "./docs/x.md", "docs//x.md"]
)
def test_resolve_within_accepts_inside_paths_and_normalises_them(
    tmp_path: Path, rel: str
) -> None:
    # Feature: FEAT-CONFIGV2-020
    assert resolve_within(tmp_path, rel) == tmp_path / "docs" / "x.md"


def test_resolve_within_accepts_a_path_whose_parents_do_not_exist_yet(
    tmp_path: Path,
) -> None:
    """A writer creates new docs: an unborn parent is not an escape."""
    # Feature: FEAT-CONFIGV2-020
    assert resolve_within(tmp_path, "new/deeper/x.md") == tmp_path / "new/deeper/x.md"


def test_resolve_within_refuses_a_dir_symlink_out(tmp_path: Path) -> None:
    # Feature: FEAT-CONFIGV2-020
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "outside").mkdir()
    (repo / "out").symlink_to(tmp_path / "outside", target_is_directory=True)
    assert resolve_within(repo, "out/x.md") is None


def test_resolve_within_refuses_a_file_symlink_out(tmp_path: Path) -> None:
    # Feature: FEAT-CONFIGV2-020
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "secret.txt").write_text("s", encoding="utf-8")
    (repo / "x.md").symlink_to(tmp_path / "secret.txt")
    assert resolve_within(repo, "x.md") is None


def test_resolve_within_refuses_a_symlink_to_the_root_itself(tmp_path: Path) -> None:
    """``self`` IS the root (not a proper descendant); ``self/x.md`` is inside
    and comes back LEXICALLY (the writer writes the path it was given)."""
    # Feature: FEAT-CONFIGV2-020
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "self").symlink_to(repo, target_is_directory=True)
    assert resolve_within(repo, "self") is None
    assert resolve_within(repo, "self/x.md") == repo / "self" / "x.md"


def test_resolve_within_keeps_a_symlink_that_stays_inside(tmp_path: Path) -> None:
    """The result is the LEXICAL candidate, never the resolved target."""
    # Feature: FEAT-CONFIGV2-020
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "alias").symlink_to(repo / "docs", target_is_directory=True)
    assert resolve_within(repo, "alias/x.md") == repo / "alias" / "x.md"


def test_resolve_within_honours_a_symlinked_root(tmp_path: Path) -> None:
    # Feature: FEAT-CONFIGV2-020
    real = tmp_path / "real"
    (real / "docs").mkdir(parents=True)
    root = tmp_path / "rootlink"
    root.symlink_to(real, target_is_directory=True)
    assert resolve_within(root, "docs/x.md") == root / "docs" / "x.md"


def test_resolve_within_refuses_an_absolute_path_even_inside_the_root(
    tmp_path: Path,
) -> None:
    # Feature: FEAT-CONFIGV2-020
    assert resolve_within(tmp_path, str(tmp_path / "docs" / "x.md")) is None


def test_resolve_within_refuses_a_sibling_sharing_the_roots_prefix(
    tmp_path: Path,
) -> None:
    """Component-wise, not string-prefix: ``repo-evil`` is not inside ``repo``."""
    # Feature: FEAT-CONFIGV2-020
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "repo-evil").mkdir()
    (repo / "l").symlink_to(tmp_path / "repo-evil", target_is_directory=True)
    assert resolve_within(repo, "l/x.md") is None


def test_resolve_within_refuses_when_the_location_is_unprovable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative root under a deleted cwd cannot be resolved — fail closed."""
    # Feature: FEAT-CONFIGV2-020
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    gone.rmdir()
    assert resolve_within(Path("repo"), "x.md") is None


def test_resolve_within_refuses_nul(tmp_path: Path) -> None:
    # Feature: FEAT-CONFIGV2-020
    assert resolve_within(tmp_path, "docs/a\x00b.md") is None


#: A doc path the OS cannot name: a lone UTF-16 surrogate reaches a config
#: through PyYAML's ``"\uD800"`` escape and a server request through JSON.
_SURROGATE_REL = yaml.safe_load('p: "docs/\\uD800.md"')["p"]


@pytest.mark.parametrize(
    "rel",
    [_SURROGATE_REL, json.loads('"docs/\\ud800.md"')],
    ids=["yaml", "json"],
)
def test_resolve_within_refuses_an_unencodable_rel(tmp_path: Path, rel: str) -> None:
    """Fails CLOSED with ``None`` — never an untyped UnicodeEncodeError — so
    every caller still raises its OWN typed K8 error."""
    # Feature: FEAT-CONFIGV2-020
    assert "\ud800" in rel
    assert resolve_within(tmp_path, rel) is None


@pytest.mark.parametrize("bad", ["a\x00b", "\ud800"], ids=["nul", "surrogate"])
def test_resolve_within_refuses_an_unrepresentable_root(
    tmp_path: Path, bad: str
) -> None:
    # Feature: FEAT-CONFIGV2-020
    assert resolve_within(os.fspath(tmp_path) + "/" + bad, "x.md") is None


def test_resolve_within_is_pure(tmp_path: Path) -> None:
    # Feature: FEAT-CONFIGV2-020
    resolve_within(tmp_path, "a/b/c.md")
    resolve_within(tmp_path, "../x.md")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "rel", ["..", "../x.md", "d/../../x.md", "./../x.md", "./..", "d/../.."]
)
def test_resolve_within_refuses_a_climb_that_a_link_brings_back_inside(
    tmp_path: Path, rel: str
) -> None:
    """Root ``tmp/a/up`` where ``up -> tmp``: physically ``tmp/a`` is inside the
    resolved root, so ONLY the lexical climb check on the NORMALISED rel
    refuses it. A climb out of the root is refused whatever it lands on."""
    # Feature: FEAT-CONFIGV2-020
    (tmp_path / "a").mkdir()
    root = tmp_path / "a" / "up"
    root.symlink_to(tmp_path, target_is_directory=True)
    assert resolve_within(root, rel) is None


@pytest.mark.parametrize("rel", ["..notes/x.md", "...md", "..hidden"])
def test_resolve_within_accepts_a_name_that_merely_starts_with_dotdot(
    tmp_path: Path, rel: str
) -> None:
    # Feature: FEAT-CONFIGV2-020
    assert resolve_within(tmp_path, rel) == tmp_path / rel


def test_resolve_within_judges_an_unnormalised_root_lexically(tmp_path: Path) -> None:
    """``repo/link/..`` names ``repo`` (normpath), so ``docs -> secrets`` is out,
    even though PHYSICALLY ``link/..`` is ``tmp`` and ``tmp/secrets`` is in it."""
    # Feature: FEAT-CONFIGV2-020
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "sub").mkdir()
    (tmp_path / "secrets").mkdir()
    (repo / "link").symlink_to(tmp_path / "sub", target_is_directory=True)
    (repo / "docs").symlink_to(tmp_path / "secrets", target_is_directory=True)
    assert resolve_within(repo / "link" / "..", "docs/x.md") is None


def _loop(repo: Path, shape: str) -> str:
    if shape == "file-self":
        (repo / "loop").symlink_to(repo / "loop")
        return "loop"
    if shape == "dir-self":
        (repo / "d").symlink_to(repo / "d", target_is_directory=True)
        return "d/x.md"
    (repo / "a").symlink_to(repo / "b", target_is_directory=True)
    (repo / "b").symlink_to(repo / "a", target_is_directory=True)
    return "a/x.md" if shape == "dirs-mutual" else "a/new/x.md"


@pytest.mark.parametrize(
    "shape", ["file-self", "dirs-mutual", "mutual-with-new-tail", "dir-self"]
)
def test_resolve_within_refuses_symlink_loops(tmp_path: Path, shape: str) -> None:
    """Non-strict ``realpath`` returns a loop's path with the link still in it;
    an unresolvable location is not provably inside."""
    # Feature: FEAT-CONFIGV2-020
    repo = tmp_path / "repo"
    repo.mkdir()
    assert resolve_within(repo, _loop(repo, shape)) is None


def test_resolve_within_accepts_a_dangling_link_whose_target_would_be_inside(
    tmp_path: Path,
) -> None:
    # Feature: FEAT-CONFIGV2-020
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "dang").symlink_to(repo / "docs" / "new.md")
    assert resolve_within(repo, "dang") == repo / "dang"


def test_resolve_within_refuses_a_root_that_is_itself_a_loop(tmp_path: Path) -> None:
    # Feature: FEAT-CONFIGV2-020
    root = tmp_path / "rl"
    root.symlink_to(root, target_is_directory=True)
    assert resolve_within(root, "x.md") is None


# --------------------------------------------------------------------------- #
# doc_path — the one lexical formula
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("ghost/../docs/x.md", "docs/x.md"),
        ("./docs//x.md", "docs/x.md"),
    ],
)
def test_doc_path_is_lexical(tmp_path: Path, rel: str, expected: str) -> None:
    # Feature: FEAT-CONFIGV2-019
    assert doc_path(tmp_path, rel) == tmp_path / expected


def test_doc_path_is_unconfined(tmp_path: Path) -> None:
    """The owner may point a doc anywhere (N-06 parity with resolve_repo_root)."""
    # Feature: FEAT-CONFIGV2-019
    assert doc_path(tmp_path, "../outside.md") == tmp_path.parent / "outside.md"
    assert doc_path(tmp_path, "/etc/x.md") == Path("/etc/x.md")
    assert doc_path(tmp_path / "a" / "..", "x.md") == tmp_path / "x.md"


def test_doc_path_does_not_follow_symlinks(tmp_path: Path) -> None:
    # Feature: FEAT-CONFIGV2-019
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    assert doc_path(tmp_path, "link/x.md") == tmp_path / "link" / "x.md"
    assert doc_path(tmp_path, "link/../x.md") == tmp_path / "x.md"


# --------------------------------------------------------------------------- #
# One id, one file: each converted lane reads doc_path(root, spec.path)
# --------------------------------------------------------------------------- #

_LIB = 'def connect(host: str) -> None:\n    """Open."""\n'
_LIB_MOVED = 'def connect(host: str) -> None:\n    """Open the link."""\n'
_DOC = (
    "# Guide\n\n> How to connect.\n\n"
    "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
)
_DECOY = (
    "# Decoy\n\n> Not this file.\n\n"
    "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
)
_OVERVIEW = "# Overview\n\nThe big picture.\n"

#: ``ghost/..`` names a directory that does not exist (the kernel cannot open
#: it); ``link/..`` crosses a symlink whose PHYSICAL parent holds a decoy.
FORMS = {"ghost": "ghost/../docs/{}", "link": "link/../docs/{}"}


def _tree(tmp_path: Path, form: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "src" / "lib.py").write_text(_LIB, encoding="utf-8")
    (repo / "docs" / "guide.md").write_text(_DOC, encoding="utf-8")
    (repo / "docs" / "overview.md").write_text(_OVERVIEW, encoding="utf-8")
    if form == "link":
        hub = tmp_path / "hub"
        (hub / "sub").mkdir(parents=True)
        (hub / "docs").mkdir()
        (hub / "docs" / "guide.md").write_text(_DECOY, encoding="utf-8")
        (hub / "docs" / "overview.md").write_text("# Decoy\n", encoding="utf-8")
        (repo / "link").symlink_to(hub / "sub", target_is_directory=True)
    return repo


def _decoys(tmp_path: Path) -> dict[str, bytes]:
    hub = tmp_path / "hub" / "docs"
    if not hub.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(hub.iterdir())}


def _guide(
    path: str, audience: Audience = Audience.USER_GUIDE, **kw: object
) -> DocumentSpec:
    return DocumentSpec(
        id="guide",
        path=path,
        audience=audience,
        region_keys=("symbols",),
        code_refs=(CodeRef(path="src/lib.py"),),
        **kw,  # type: ignore[arg-type]
    )


def _cfg(form: str | None, audience: Audience = Audience.USER_GUIDE) -> MonitorConfig:
    path = "docs/guide.md" if form is None else FORMS[form].format("guide.md")
    return MonitorConfig(root=".", documents=(_guide(path, audience),))


def _monitor(cfg: MonitorConfig, repo: Path, tmp_path: Path) -> Monitor:
    return Monitor(
        cfg,
        repo,
        now=lambda: _NOW,
        sink=NullSink(),
        log_path=tmp_path / "log" / "review-log.jsonl",
    )


def _heal(repo: Path, tmp_path: Path) -> None:
    _monitor(_cfg(None), repo, tmp_path).run(apply=True)
    assert detect(_cfg(None), repo).drifts == ()


@pytest.mark.parametrize("form", FORMS)
def test_detect_and_okf_agree_on_a_dotdot_doc_path(tmp_path: Path, form: str) -> None:
    """The split this slice closes: a healed doc re-pointed through ``ghost/..``
    (detect reported MISSING_DOC) or across a symlink (detect graded the decoy)
    while the bundle read the normalised file."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    _heal(repo, tmp_path)
    cfg = _cfg(form)
    assert detect(cfg, repo).drifts == ()
    files, skipped = render_bundle(cfg, repo)
    assert skipped == ()
    assert "How to connect." in files["docs/guide.md"]


def test_okf_reads_the_normalised_path_under_an_unnormalised_root(
    tmp_path: Path,
) -> None:
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, "link")
    _heal(repo, tmp_path)
    files, _ = render_bundle(_cfg(None), repo / "link" / "..")
    assert "How to connect." in files["docs/guide.md"]
    assert "Decoy" not in files["docs/guide.md"]


def test_detect_stays_unconfined_for_the_owners_config(tmp_path: Path) -> None:
    """Readers never refuse: the owner's ``../shared`` doc is graded, not raised."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, "ghost")
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "guide.md").write_text(_DOC, encoding="utf-8")
    cfg = MonitorConfig(root=".", documents=(_guide("../shared/guide.md"),))
    kinds = {d.kind for d in detect(cfg, repo).drifts}
    assert kinds and DriftKind.MISSING_DOC not in kinds


# --- the doc<->doc lane (docdeps) ---------------------------------------------


def _deps_cfg(form: str | None, side: str) -> MonitorConfig:
    """``guide`` depends on ``overview``; ``side`` picks which one is dotdot."""

    def _path(name: str) -> str:
        if form is None or side != name:
            return f"docs/{name}.md"
        return FORMS[form].format(f"{name}.md")

    overview = DocumentSpec(
        id="overview", path=_path("overview"), audience=Audience.USER_GUIDE
    )
    guide = _guide(_path("guide"), depends_on=(DocEdge(doc="overview"),))
    return MonitorConfig(
        root=".",
        documents=(overview, guide),
        docdeps=DocDepsConfig(enabled=True),
    )


@pytest.mark.parametrize("form", FORMS)
def test_suspect_link_lane_reads_a_dotdot_downstream(tmp_path: Path, form: str) -> None:
    """A changed upstream is SUSPECT — never silently dropped (the downstream
    "missing") nor UNSTAMPED (the decoy's empty stamps)."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    assert stamp_edges(_deps_cfg(None, "guide"), repo, "guide") == ("overview",)
    (repo / "docs" / "overview.md").write_text(
        _OVERVIEW + "\nA new paragraph.\n", encoding="utf-8"
    )
    links = detect_suspect_links(_deps_cfg(form, "guide"), repo, include_ok=True)
    assert [link.status for link in links] == [SuspectStatus.SUSPECT]
    suspect = [
        d
        for d in detect(_deps_cfg(form, "guide"), repo).drifts
        if d.kind is DriftKind.SUSPECT_LINK
    ]
    assert [d.doc_id for d in suspect] == ["guide"]


@pytest.mark.parametrize("form", FORMS)
def test_suspect_link_lane_reads_a_dotdot_upstream(tmp_path: Path, form: str) -> None:
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    stamp_edges(_deps_cfg(None, "overview"), repo, "guide")
    links = detect_suspect_links(_deps_cfg(form, "overview"), repo, include_ok=True)
    assert [link.status for link in links] == [SuspectStatus.OK]


@pytest.mark.parametrize("side", ["guide", "overview"])
@pytest.mark.parametrize("form", FORMS)
def test_stamp_edges_baselines_what_detect_reads(
    tmp_path: Path, form: str, side: str
) -> None:
    """The writer stamps the file detect grades, and is idempotent (K7)."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    decoys = _decoys(tmp_path)
    cfg = _deps_cfg(form, side)
    assert stamp_edges(cfg, repo, "guide") == ("overview",)
    links = detect_suspect_links(cfg, repo, include_ok=True)
    assert [link.status for link in links] == [SuspectStatus.OK]
    assert stamp_edges(cfg, repo, "guide") == ()
    assert _decoys(tmp_path) == decoys
    assert not (repo / "ghost").exists()


@pytest.mark.parametrize("form", FORMS)
def test_infer_edges_reads_a_dotdot_downstream(tmp_path: Path, form: str) -> None:
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    (repo / "docs" / "guide.md").write_text(
        _DOC + "\nSee [the overview](overview.md).\n", encoding="utf-8"
    )
    cfg = _deps_cfg(form, "guide")
    cfg = cfg.model_copy(
        update={
            "documents": (
                cfg.documents[0],
                cfg.documents[1].model_copy(update={"depends_on": ()}),
            )
        }
    )
    edges = infer_edges_from_links(cfg, repo)
    assert [(e.doc_id, e.upstream_id) for e in edges] == [("guide", "overview")]


@pytest.mark.parametrize("form", FORMS)
def test_index_lane_reads_a_dotdot_target(tmp_path: Path, form: str) -> None:
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    index_spec = DocumentSpec(id="index", path="index.md", audience=Audience.USER_GUIDE)
    cfg = MonitorConfig(
        root=".", documents=(index_spec, _guide(FORMS[form].format("guide.md")))
    )
    template = RegionTemplate(
        source="index", columns=(RegionColumn(header="Doc", field="title"),)
    )
    table = render_index(template, index_spec, cfg, repo)
    assert "[Guide](" in table
    assert "Decoy" not in table


# --- the writers: monitor heals the file detect grades ------------------------


@pytest.mark.parametrize("form", FORMS)
def test_monitor_heals_the_file_detect_grades(tmp_path: Path, form: str) -> None:
    """Converges (K7) on the real doc: prose kept, no decoy written, no
    ``ghost/`` directory conjured by a stub write."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    decoys = _decoys(tmp_path)
    cfg = _cfg(form)
    first = _monitor(cfg, repo, tmp_path).run(apply=True)
    assert first.records
    assert detect(cfg, repo).drifts == ()
    second = _monitor(cfg, repo, tmp_path).run(apply=True)
    assert second.records == ()
    text = (repo / "docs" / "guide.md").read_text(encoding="utf-8")
    assert "> How to connect." in text
    assert "connect" in text.split("CDM:BEGIN symbols", 1)[1]
    assert "Decoy" not in text
    assert _decoys(tmp_path) == decoys
    assert not (repo / "ghost").exists()


@pytest.mark.parametrize("form", FORMS)
def test_tiered_engine_closes_the_file_detect_grades(tmp_path: Path, form: str) -> None:
    """The RTE-03d ENGINE write (no backend) heals the same file and verifies.
    An eng-guide: a docstring-only move is a CODE_DERIVED HASH drift there (a
    user-guide is never flagged for it, K3)."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    spec = _guide("docs/guide.md", Audience.ENG_GUIDE)
    regenerate_regions(
        repo / "docs" / "guide.md",
        build_document_surface(spec, repo),
        modes={rid: spec.mode_for(rid) for rid in spec.region_keys},
    )
    (repo / "src" / "lib.py").write_text(_LIB_MOVED, encoding="utf-8")
    decoys = _decoys(tmp_path)
    cfg = _cfg(form, Audience.ENG_GUIDE)
    result = _monitor(cfg, repo, tmp_path).run(apply=True, tiered=True)
    assert [c.doc_id for c in result.closures] == ["guide"]
    assert all(c.wrote and c.verified for c in result.closures)
    assert result.remaining == ()
    again = _monitor(cfg, repo, tmp_path).run(apply=True, tiered=True)
    assert again.records == ()
    assert _decoys(tmp_path) == decoys


@pytest.mark.parametrize("form", FORMS)
def test_sync_pr_diffs_and_restores_the_file_monitor_heals(
    tmp_path: Path, form: str
) -> None:
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    before = (repo / "docs" / "guide.md").read_bytes()
    decoys = _decoys(tmp_path)
    cfg = _cfg(form)

    dry = sync_pr(_monitor(cfg, repo, tmp_path), dry_run=True)
    assert dry.changed_paths == (FORMS[form].format("guide.md"),)
    assert "connect" in dry.patch and "Decoy" not in dry.patch
    assert (repo / "docs" / "guide.md").read_bytes() == before

    real = sync_pr(_monitor(cfg, repo, tmp_path))
    assert real.patch == dry.patch
    assert (repo / "docs" / "guide.md").read_bytes() != before
    assert _decoys(tmp_path) == decoys


@pytest.mark.parametrize("form", FORMS)
def test_plan_docs_pr_commits_the_healed_file_at_its_normalised_path(
    tmp_path: Path, form: str
) -> None:
    """The commit carries the bytes monitor wrote, at the path a provider can
    take — never a decoy read through ``link/..``, never a ``ghost/..`` crash."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    sync = sync_pr(_monitor(_cfg(form), repo, tmp_path))
    plan = plan_docs_pr(sync, repo)
    assert plan is not None
    healed = (repo / "docs" / "guide.md").read_text(encoding="utf-8")
    assert plan.files == (("docs/guide.md", healed),)
    assert "- `docs/guide.md`" in plan.description
    assert ".." not in plan.description


def test_should_sync_matches_a_dotdot_managed_path(tmp_path: Path) -> None:
    """The loop-breaker compares normalised paths, so a bot commit touching
    only the managed doc does not re-trigger (C-04)."""
    # Feature: FEAT-CONFIGV2-019
    assert should_sync(["docs/guide.md"], _cfg("ghost")) is False
    assert should_sync(["./docs/guide.md", "docs\\guide.md"], _cfg("link")) is False
    assert should_sync(["docs/guide.md", "src/lib.py"], _cfg("ghost")) is True


@pytest.mark.parametrize("form", FORMS)
def test_resolve_edge_key_reads_the_upstream_at_doc_path(
    tmp_path: Path, form: str
) -> None:
    """The RESOLVE_EDGE key carries the CURRENT upstream fingerprint — the same
    key whether the upstream is spelled plainly or through dotdot."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    stamp_edges(_deps_cfg(None, "overview"), repo, "guide")
    (repo / "docs" / "overview.md").write_text(
        _OVERVIEW + "\nChanged.\n", encoding="utf-8"
    )

    def _keys(cfg: MonitorConfig) -> list[str]:
        return [
            s.key
            for s in suggest_fixes_tick(cfg, repo, now=_NOW)
            if s.kind.value == "resolve_edge"
        ]

    plain = _keys(_deps_cfg(None, "overview"))
    assert len(plain) == 1
    assert _keys(_deps_cfg(form, "overview")) == plain


def test_two_spellings_of_one_file_hold_each_other(tmp_path: Path) -> None:
    """RTE-03b's "block by FILE" compares NORMALISED paths: once the lanes read
    ``doc_path``, ``docs/guide.md`` and ``ghost/../docs/guide.md`` are ONE file,
    so a held spelling must hold the mechanical one (no unattended rewrite of
    the held doc's file)."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, "ghost")
    (repo / "docs" / "guide.md").write_text(
        _DOC + "\n<!-- CDM:BEGIN prose -->\nhand-written\n<!-- CDM:END prose -->\n",
        encoding="utf-8",
    )
    mech = _guide("docs/guide.md", Audience.ENG_GUIDE)
    regenerate_regions(
        repo / "docs" / "guide.md",
        build_document_surface(mech, repo),
        modes={rid: mech.mode_for(rid) for rid in mech.region_keys},
    )
    (repo / "src" / "lib.py").write_text(_LIB_MOVED, encoding="utf-8")
    held = DocumentSpec(
        id="held",
        path=FORMS["ghost"].format("guide.md"),
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/lib.py"),),
        region_keys=("prose",),  # no renderer -> NEEDS_INTENT
    )
    report = detect(MonitorConfig(root=".", documents=(mech, held)), repo)
    assert any(
        d.doc_id == "guide" and d.apply_tier.value == "code-derived"
        for d in report.drifts
    ), "the fixture must give the mechanical doc a real mechanical drift"
    assert any(d.doc_id == "held" for d in report.drifts)
    assert mechanical_docs(report) == frozenset()


def test_doc_path_matches_the_os_view_for_a_plain_path(tmp_path: Path) -> None:
    """Guard: the formula is a no-op on an already-normal relative path."""
    # Feature: FEAT-CONFIGV2-019
    assert os.fspath(doc_path(tmp_path, "docs/x.md")) == os.fspath(
        tmp_path / "docs" / "x.md"
    )


def test_a_dotdot_doc_is_held_by_its_own_needs_intent_drift(tmp_path: Path) -> None:
    """``auto_routable_docs`` (the ``require_actionable=False`` fold, which feeds
    ``DriftReport.summary()``'s routing tally) compares a doc's OWN file
    normalised: a NEEDS_INTENT drift on ``ghost/../docs/guide.md`` holds that
    doc, so the tally counts it as needing human intent, never as delegated."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, "ghost")
    (repo / "docs" / "guide.md").write_text(
        _DOC + "\n<!-- CDM:BEGIN prose -->\nhand-written\n<!-- CDM:END prose -->\n",
        encoding="utf-8",
    )
    mech = _guide("docs/guide.md", Audience.ENG_GUIDE)
    regenerate_regions(
        repo / "docs" / "guide.md",
        build_document_surface(mech, repo),
        modes={rid: mech.mode_for(rid) for rid in mech.region_keys},
    )
    (repo / "src" / "lib.py").write_text(_LIB_MOVED, encoding="utf-8")
    held = DocumentSpec(
        id="held",
        path=FORMS["ghost"].format("guide.md"),
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/lib.py"),),
        region_keys=("prose",),  # no renderer -> NEEDS_INTENT
    )
    report = detect(MonitorConfig(root=".", documents=(held,)), repo)
    assert any(d.doc_id == "held" for d in report.drifts)
    assert "held" not in auto_routable_docs(report)
    assert "1 need human intent" in report.summary()


@pytest.mark.parametrize("form", FORMS)
def test_entity_lane_reads_the_file_detect_grades(tmp_path: Path, form: str) -> None:
    """``corpus_entities`` (the kgraph/docmap/``cdx entities`` lane) skipped a
    ``ghost/..`` doc that detect grades and, across ``link/..``, extracted the
    DECOY outside the repo. It now reads ``doc_path(root, spec.path)``."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    _heal(repo, tmp_path)
    cfg = _cfg(form)
    assert detect(cfg, repo).drifts == ()
    (result,) = corpus_entities(cfg, repo)
    assert result.doc_id == "guide"
    assert result.doc_path == FORMS[form].format("guide.md")
    names = [s.name for s in result.sections]
    assert names and names[0] == "guide"
    assert "decoy" not in names


def test_both_helpers_take_a_str_root(tmp_path: Path) -> None:
    """The pinned signature is ``root: Path | str`` (adopters pass either)."""
    # Feature: FEAT-CONFIGV2-019, FEAT-CONFIGV2-020
    root = os.fspath(tmp_path)
    assert doc_path(root, "x/../docs/g.md") == tmp_path / "docs" / "g.md"
    assert resolve_within(root, "docs/g.md") == tmp_path / "docs" / "g.md"
    assert resolve_within(root, "../g.md") is None


@pytest.mark.parametrize("form", FORMS)
def test_sync_pr_patch_headers_name_the_normalised_file(
    tmp_path: Path, form: str
) -> None:
    """The patch headers name the file monitor healed, ``docs/guide.md`` — the
    path the docs-PR commit and the MR description use — never the config's
    ``ghost/..``/``link/..`` spelling, which ``git apply`` and patch(1) refuse.
    ``changed_paths`` keeps the config spelling (``plan_docs_pr`` maps it)."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, form)
    dry = sync_pr(_monitor(_cfg(form), repo, tmp_path), dry_run=True)
    assert dry.changed_paths == (FORMS[form].format("guide.md"),)
    assert "--- a/docs/guide.md" in dry.patch
    assert "+++ b/docs/guide.md" in dry.patch
    assert "/../" not in dry.patch


@pytest.mark.parametrize("spelled", ["docs/guide.md/x/..", "docs/guide.md/."])
def test_build_twin_sits_beside_the_graded_file_for_a_trailing_dot_spelling(
    tmp_path: Path, spelled: str
) -> None:
    """``build`` names the twin from the NORMALISED path. Taking the suffix of
    the raw spelling turned ``docs/guide.md/x/..`` (check grades
    ``docs/guide.md``) into ``docs/guide.md/x/...html`` — an untyped
    NotADirectoryError at mkdir — and broke the sidebar href the same way."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, "ghost")
    cfg = MonitorConfig(root=".", documents=(_guide(spelled, html=True),))
    assert not any(d.kind is DriftKind.MISSING_DOC for d in detect(cfg, repo).drifts)
    twin = repo / "docs" / "guide.html"
    assert build(cfg, repo) == [twin]
    assert 'href="guide.html"' in twin.read_text(encoding="utf-8")


def test_sync_pr_patch_headers_match_the_committed_path(tmp_path: Path) -> None:
    """Patch header and commit path share ONE formula (``posixpath.normpath``):
    a back-slash is a POSIX filename character, never a separator, for both."""
    # Feature: FEAT-CONFIGV2-019
    repo = _tree(tmp_path, "ghost")
    spelled = "docs/a\\b.md"
    (repo / "docs" / "a\\b.md").write_text(_DOC, encoding="utf-8")
    cfg = MonitorConfig(root=".", documents=(_guide(spelled),))
    sync = sync_pr(_monitor(cfg, repo, tmp_path))
    plan = plan_docs_pr(sync, repo)
    assert plan is not None
    ((committed, _),) = plan.files
    assert committed == spelled
    assert f"--- a/{committed}" in sync.patch and f"+++ b/{committed}" in sync.patch
