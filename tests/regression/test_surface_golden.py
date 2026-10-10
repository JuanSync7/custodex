"""FPW-FIXTURES — frozen legacy stamps and the surface golden guard (critique B2).

Two guards, both over committed data under ``tests/fixtures/``:

* **The frozen legacy trees** (``fpwave_legacy/{enc1,enc2}/{body-off,body-on}``):
  one mini repo, stamped once by the enc-1 engine (``git archive`` of the commit
  pinned in ``capture.json``) and once by step-0 main, captured on the interpreter
  ``capture.json`` names. They are write-once data for the fingerprint wave (FPW):
  ``test_frozen_fpwave_fixtures_are_intact`` proves no byte moved, and the restamp
  tests prove the CURRENT engine still reads enc2 stamps as current (and still
  rewrites the enc1 ones, so that check is not vacuous).
* **The surface golden** (``surface_golden.json``): the current engine's
  fingerprint, tiers, symbol_sigs, region_anchors, code-index digests and coverage
  manifest over the enc2 tree and a synthetic tree. An unflagged move in any
  extractor path those trees exercise fails here: python symbols, decorators,
  properties, pydantic and dataclass fields, ``names:``/``lines``/``arg_signature``
  selectors, argparse/python/shell-case/getopts/tcl switches and JSON records, the
  code index and coverage. A path neither tree exercises is out of its reach.
  Only a [WAVE] slice may re-pin it (``capture.py golden --repin ID``),
  and each appends its id to ``repins``; the pinned digest below is keyed by that
  list, so a re-pin also needs a visible edit to this file. Supersedes AF test 23
  (PD-5).

The tool refuses a mis-flagged re-pin; review rejects an unflagged one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tarfile
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "tests" / "fixtures"
_LEGACY = _FIXTURES / "fpwave_legacy"
_CAPTURE_PATH = _LEGACY / "capture.py"
_GOLDEN_PATH = _FIXTURES / "surface_golden.json"
_VARIANTS = ("body-off", "body-on")

# sha256 of the committed SHA256SUMS file. Moving any frozen byte needs BOTH a
# regenerated manifest AND an edit to this literal — the frozen trees are
# write-once, so no slice should ever have to touch it.
_MANIFEST_DIGEST = "d8423a8b80d04810f89a208da20378160c17b791bad2c588b3a6c9fe4ad43a65"

# sha256 of the golden's canonical ``trees`` payload, keyed by its ``repins`` list.
# A [WAVE] re-pin appends a row here; any other change to the golden fails.
_GOLDEN_DIGESTS: dict[tuple[str, ...], str] = {
    (): "50f8f2ba84ae784aa14e2b1519d5d56e9099f69be2bd1f43f236e4045beb03ba",
}

# The cdm stamp keys the surface golden owns. Only a [WAVE] slice may move them
# (and re-pins the golden when it does). Every other cdm key belongs to the slice
# that writes it ([SW]: "changes what later writes stamp", e.g. cdm.region_inputs
# or the encoding marker), so the current-engine tests below ignore it: an
# additive stamp never trips them, and they need no edit from an [SW] slice.
_GOLDEN_OWNED = ("fingerprint", "fingerprint_tiers", "symbol_sigs", "region_anchors")

# Per golden ``repins`` tuple: on which docs the CURRENT engine's output differs
# from a frozen tree, in what a reader or the golden sees (the doc body, its
# non-cdm front matter, or a golden-owned stamp). Three checks, one row per tuple:
#   "restamp enc1"  monitor --apply over a copy of each enc-1 tree. The liveness
#                   sentinel: it must rewrite something, or the enc-2 identity
#                   check below could pass because nothing ran.
#   "restamp enc2"  monitor --apply over a copy of each enc-2 tree (empty until
#                   a [WAVE] slice moves the enc-2 stamps).
#   "fresh stamp"   capture.stamp of the seed vs the frozen enc-2 tree (empty
#                   until a [WAVE] slice moves what a fresh heal stamps).
# A [WAVE] re-pin adds the row for its new tuple here, next to its
# _GOLDEN_DIGESTS row; test_every_repin_has_a_row_in_each_keyed_table names both.
_ENGINE_MOVES: dict[tuple[str, ...], dict[str, dict[str, frozenset[str]]]] = {
    (): {
        "restamp enc1": {
            "body-off": frozenset({"docs/cli.md", "docs/model.md"}),
            "body-on": frozenset({"docs/cli.md", "docs/model.md"}),
        },
        "restamp enc2": {"body-off": frozenset(), "body-on": frozenset()},
        "fresh stamp": {"body-off": frozenset(), "body-on": frozenset()},
    },
}

_REGION_RE = re.compile(r"(<!-- CDM:BEGIN (\S+) -->\n).*?(<!-- CDM:END \2 -->)", re.S)
_FRONT_MATTER_RE = re.compile(r"\A---\n.*?^---\n", re.S | re.M)


@pytest.fixture(scope="module")
def capture() -> ModuleType:
    """Load the committed capture tool (it lives with its data, not in a package)."""
    if not _CAPTURE_PATH.is_file():
        pytest.fail(f"missing capture tool {_CAPTURE_PATH}")
    spec = importlib.util.spec_from_file_location("fpwave_capture", _CAPTURE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fpwave_capture"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def isolated(
    capture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point the tool's HERE/MANIFEST/GOLDEN at an empty scratch dir."""
    here = tmp_path / "fpwave_legacy"
    here.mkdir()
    monkeypatch.setattr(capture, "HERE", here)
    monkeypatch.setattr(capture, "MANIFEST", here / "SHA256SUMS")
    monkeypatch.setattr(capture, "GOLDEN", tmp_path / "surface_golden.json")
    return here


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and ".cdmon" not in p.parts
    }


def _golden() -> dict[str, Any]:
    return json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))


def _cdm(text: str) -> dict[str, Any]:
    match = _FRONT_MATTER_RE.match(text)
    assert match is not None, "doc has no front matter"
    meta = yaml.safe_load(match.group(0).strip("-\n"))
    assert isinstance(meta, dict)
    cdm = meta.get("cdm")
    assert isinstance(cdm, dict)
    return cdm


def _prose(text: str) -> str:
    """The doc with its front matter and every managed-region body masked out."""
    return _REGION_RE.sub(r"\1\3", _FRONT_MATTER_RE.sub("", text, count=1))


def _region(text: str, region_id: str) -> str:
    match = re.search(
        rf"<!-- CDM:BEGIN {re.escape(region_id)} -->\n(.*?)<!-- CDM:END "
        rf"{re.escape(region_id)} -->",
        text,
        re.S,
    )
    assert match is not None, f"no region {region_id!r}"
    return match.group(1)


def _restamp(capture: ModuleType, tree: Path) -> None:
    """Run the CURRENT engine's monitor --apply (mock backend) over ``tree``."""
    from custodex.config import load_config
    from custodex.monitor import Monitor

    config = load_config(tree / capture.CONFIG_NAME)
    now = capture.SETTINGS["now"]
    Monitor(config, tree, now=lambda: now).run(apply=True)


def _labels(capture: ModuleType) -> list[str]:
    return [
        f"{enc}/{variant}"
        for enc in capture.SETTINGS["encodings"]
        for variant in capture.SETTINGS["variants"]
    ]


def _doc_view(text: str) -> dict[str, Any]:
    """What a reader or the golden sees of a doc: body, non-cdm meta, owned stamps.

    Front matter is compared parsed, not as bytes, and cdm keys outside
    ``_GOLDEN_OWNED`` are dropped, so neither an [SW] front-matter layout change
    nor an additive stamp key reads as a move.
    """
    match = _FRONT_MATTER_RE.match(text)
    assert match is not None, "doc has no front matter"
    meta = yaml.safe_load(match.group(0).strip("-\n"))
    assert isinstance(meta, dict)
    cdm = meta.pop("cdm", {})
    return {
        "body": text[match.end() :],
        "meta": meta,
        "owned": {k: cdm[k] for k in _GOLDEN_OWNED if k in cdm},
    }


def _tree_view(root: Path) -> dict[str, Any]:
    """``_tree_bytes`` with every ``docs/*.md`` replaced by its ``_doc_view``."""
    return {
        rel: _doc_view(data.decode("utf-8"))
        if rel.startswith("docs/") and rel.endswith(".md")
        else data
        for rel, data in _tree_bytes(root).items()
    }


def _view_moves(before: dict[str, Any], after: dict[str, Any]) -> frozenset[str]:
    assert sorted(before) == sorted(after)
    return frozenset(rel for rel in after if after[rel] != before[rel])


def _engine_moves(check: str, variant: str) -> frozenset[str]:
    """The ``_ENGINE_MOVES`` row for the committed golden's ``repins``."""
    repins = tuple(_golden()["repins"])
    assert repins in _ENGINE_MOVES, (
        f"no _ENGINE_MOVES row for repins {repins}: the [WAVE] slice that re-pinned "
        "the golden must add one"
    )
    return _ENGINE_MOVES[repins][check][variant]


@pytest.fixture
def on_capture_python(capture: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the running interpreter the capture interpreter for a write-path test.

    The guard is pinned by its own refusal tests. The tests that use this fixture
    exercise what comes after the guard, so they must pass on every interpreter
    the suite runs on, not only the one ``capture_python`` names.
    """
    monkeypatch.setitem(capture.SETTINGS, "capture_python", list(sys.version_info[:2]))


@pytest.fixture(scope="module")
def fresh_enc2(
    capture: ModuleType, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Path]:
    """The seed stamped by the CURRENT engine through ``capture.stamp``, per variant."""
    import custodex

    engine = Path(custodex.__file__).resolve().parents[1]
    trees: dict[str, Path] = {}
    for variant, body_tier in capture.SETTINGS["variants"].items():
        tree = tmp_path_factory.mktemp("fresh") / variant
        capture.write_tree(tree, capture.seed_files(body_tier=body_tier))
        capture.stamp(tree, engine)
        trees[variant] = tree
    return trees


# --------------------------------------------------------------------------- #
# The frozen legacy trees                                                      #
# --------------------------------------------------------------------------- #


def test_frozen_fpwave_fixtures_are_intact(capture: ModuleType) -> None:
    """Every frozen byte matches the committed manifest, and the manifest is pinned."""
    manifest = _LEGACY / "SHA256SUMS"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == _MANIFEST_DIGEST
    listed = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, _, rel = line.partition("  ")
        listed[rel] = digest
    on_disk = {
        rel: hashlib.sha256(data).hexdigest()
        for rel, data in capture.frozen_files(_LEGACY).items()
    }
    assert on_disk == listed
    # A pass over zero files is a failure: every enc x variant tree is populated.
    for label in _labels(capture):
        assert any(rel.startswith(f"{label}/docs/") for rel in listed), label
    assert capture.main(["manifest"]) == 0


@pytest.mark.parametrize("variant", _VARIANTS)
def test_current_engine_restamps_the_frozen_trees_byte_identically(
    capture: ModuleType, variant: str, tmp_path: Path
) -> None:
    """The current engine reads each enc-2 stamp as current: a restamp moves nothing.

    "Nothing" is every byte a reader or the golden sees (``_doc_view``) outside
    the docs a [WAVE] slice declared in ``_ENGINE_MOVES``; that set is empty
    until the first re-pin, so today this is byte identity of every view.
    """
    frozen = _LEGACY / "enc2" / variant
    tree = tmp_path / "enc2"
    shutil.copytree(frozen, tree)
    before = _tree_view(tree)
    assert sum(rel.startswith("docs/") for rel in before) >= 5
    _restamp(capture, tree)
    moved = _view_moves(before, _tree_view(tree))
    assert moved == _engine_moves("restamp enc2", variant)
    # K7: a second restamp writes nothing at all, not even an unowned key
    healed = _tree_bytes(tree)
    _restamp(capture, tree)
    assert _tree_bytes(tree) == healed


@pytest.mark.parametrize("variant", _VARIANTS)
def test_current_engine_rewrites_the_enc1_trees_on_the_expected_docs(
    capture: ModuleType, variant: str, tmp_path: Path
) -> None:
    """Liveness for the restamp check: the enc-1 stamps DO move, on a pinned doc set."""
    frozen = _LEGACY / "enc1" / variant
    tree = tmp_path / "enc1"
    shutil.copytree(frozen, tree)
    before = _tree_view(tree)
    _restamp(capture, tree)
    changed = _view_moves(before, _tree_view(tree))
    assert changed == _engine_moves("restamp enc1", variant)
    assert changed, "the enc-1 sentinel must rewrite at least one doc"


def test_frozen_trees_are_stamped_from_the_committed_seed(capture: ModuleType) -> None:
    """Code + config are the seed verbatim; docs differ only in stamps and regions."""
    for enc in capture.SETTINGS["encodings"]:
        for variant, body_tier in capture.SETTINGS["variants"].items():
            tree = _LEGACY / enc / variant
            seed = capture.seed_files(body_tier=body_tier)
            frozen = _tree_bytes(tree)
            assert sorted(frozen) == sorted(seed), (enc, variant)
            for rel, text in seed.items():
                got = frozen[rel].decode("utf-8")
                if rel.startswith("docs/"):
                    assert _prose(got) == _prose(text), (enc, variant, rel)
                else:
                    assert got == text, (enc, variant, rel)
            for doc, region_id, body in capture.HAND_EDITS:
                assert _region(frozen[doc].decode("utf-8"), region_id) == body + "\n"


def test_frozen_trees_carry_every_fixture_shape(capture: ModuleType) -> None:
    """One liveness row per FPW fixture shape (S1-FPWAVE 'Fixtures'), on every tree."""
    from custodex.manifest import parse_text, region_body_hash, regions

    for label in _labels(capture):
        tree = _LEGACY / label
        docs = {
            p.name: p.read_text(encoding="utf-8") for p in (tree / "docs").iterdir()
        }
        model, cli, helpers = docs["model.md"], docs["cli.md"], docs["helpers.md"]
        # decorated function + named command
        assert "@functools.cache" in (tree / "pkg" / "cli.py").read_text()
        assert '@app.command("sync-all")' in (tree / "pkg" / "cli.py").read_text()
        # property getter + setter render as two Widget.size rows
        assert _region(model, "symbols").count("| Widget.size |") == 2, label
        # same-name functions in two files: two `normalise` rows in one table
        assert _region(helpers, "symbols").count("| normalise |") == 2, label
        # mode: llm region with hand prose; symbols: llm renderer-backed
        assert _region(model, "overview").startswith("Hand-written overview"), label
        assert "| Item |" in _region(model, "symbols"), label
        # symbols: human, hand-edited after its last heal (stamp != body hash).
        # Bodies are read with the engine's own region reader, so the hash
        # comparison uses exactly the text heal hashed.
        cli_bodies = regions(parse_text(cli))
        stored = _cdm(cli)["region_hashes"]["symbols"]
        assert stored != region_body_hash(cli_bodies["symbols"]), label
        # llm-seeded: `api` locked (hand edit), `symbols` unlocked (engine body)
        helper_bodies = regions(parse_text(helpers))
        hashes = _cdm(helpers)["region_hashes"]
        assert hashes["api"] != region_body_hash(helper_bodies["api"]), label
        assert hashes["symbols"] == region_body_hash(helper_bodies["symbols"]), label
        # neutral doc carries the full modern stamp set
        assert {"fingerprint", "fingerprint_tiers"} <= set(_cdm(docs["neutral.md"]))
        # composite-only pre-P2 doc
        assert set(_cdm(docs["legacy.md"])) == {"fingerprint"}, label
    # pydantic fields: only the enc-2 engine extracts them (RTE-02b)
    for variant in _VARIANTS:
        enc1 = (_LEGACY / "enc1" / variant / "docs" / "model.md").read_text()
        enc2 = (_LEGACY / "enc2" / variant / "docs" / "model.md").read_text()
        assert "| Item.name |" not in _region(enc1, "symbols")
        assert "| Item.name |" in _region(enc2, "symbols")
    # the body tier really is on in the body-on variant
    for enc in capture.SETTINGS["encodings"]:
        on = _cdm((_LEGACY / enc / "body-on" / "docs" / "neutral.md").read_text())
        off = _cdm((_LEGACY / enc / "body-off" / "docs" / "neutral.md").read_text())
        assert (
            "body" in on["fingerprint_tiers"] and "body" not in off["fingerprint_tiers"]
        )


def test_views_see_what_a_reader_or_the_golden_sees(tmp_path: Path) -> None:
    """The view helpers the current-engine checks compare through are not vacuous.

    A doc view moves on a body, non-cdm front matter or golden-owned stamp change,
    and never on an unowned cdm key or a front-matter layout change ([SW]
    territory). A tree view keeps every non-doc file's bytes.
    """
    base = (
        "---\ncdm:\n  fingerprint: a\n  region_hashes:\n    x: h\ntitle: T\n---\nbody\n"
    )
    view = _doc_view(base)
    assert view == {
        "body": "body\n",
        "meta": {"title": "T"},
        "owned": {"fingerprint": "a"},
    }
    relaid = "---\n{cdm: {fingerprint: a, encoding: 3}, title: T}\n---\nbody\n"
    assert _doc_view(relaid) == view
    for old, new in (("body\n", "body!\n"), ("T\n", "U\n"), ("a\n", "b\n")):
        assert _doc_view(base.replace(old, new)) != view, new
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "d.md").write_text(base, encoding="utf-8")
    (tmp_path / "pkg.py").write_text("x = 1\n", encoding="utf-8")
    assert _tree_view(tmp_path) == {"docs/d.md": view, "pkg.py": b"x = 1\n"}


def test_pre_p2_strip_is_block_style_and_idempotent(capture: ModuleType) -> None:
    """A pre-P2 strip keeps only the composite, in render_doc's block layout, and is
    idempotent (K7).
    """
    text = (
        "---\ncdm:\n  fingerprint: abc\n  region_hashes: {x: y}\ntitle: T\n---\nbody\n"
    )
    once = capture.pre_p2_text(text)
    assert once == "---\ncdm:\n  fingerprint: abc\ntitle: T\n---\nbody\n"
    assert capture.pre_p2_text(once) == once


# --------------------------------------------------------------------------- #
# The capture tool's refusals (write-once, engine identity, interpreter)       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("existing", ["enc1", "enc2", "SHA256SUMS"])
def test_frozen_trees_refuse_a_recapture_while_any_part_exists(
    capture: ModuleType,
    isolated: Path,
    existing: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`trees --write` refuses BEFORE any git or engine call when any part exists."""
    calls: list[object] = []
    monkeypatch.setattr(capture, "capture_trees", lambda dest: calls.append(dest))
    monkeypatch.setattr(capture, "_git", lambda *a: calls.append(a) or b"")
    target = isolated / existing
    if existing == "SHA256SUMS":
        target.write_text("")
    else:
        target.mkdir()
    assert capture.main(["trees", "--write"]) == 2
    assert calls == []
    assert "write-once" in capsys.readouterr().err


def test_trees_write_then_check_round_trip(
    capture: ModuleType, isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write-once yields exactly {enc1, enc2, SHA256SUMS}; --check sees one byte."""

    def fake_capture(dest: Path) -> None:
        for label in _labels(capture):
            shutil.copytree(_LEGACY / label, dest / label)

    monkeypatch.setattr(capture, "capture_trees", fake_capture)
    assert capture.main(["trees", "--write"]) == 0
    assert sorted(p.name for p in isolated.iterdir()) == ["SHA256SUMS", "enc1", "enc2"]
    assert capture.main(["manifest"]) == 0
    assert capture.main(["trees", "--check"]) == 0
    frozen = _tree_bytes(isolated)

    def drifted_capture(dest: Path) -> None:
        fake_capture(dest)
        doc = dest / "enc2" / "body-off" / "docs" / "neutral.md"
        doc.write_bytes(doc.read_bytes() + b" ")

    monkeypatch.setattr(capture, "capture_trees", drifted_capture)
    assert capture.main(["trees", "--check"]) == 1
    assert _tree_bytes(isolated) == frozen  # --check never writes
    (isolated / "enc1" / "body-off" / "extra.txt").write_text("x")
    assert capture.main(["manifest"]) == 1


def test_write_tree_refuses_a_non_empty_destination(
    capture: ModuleType, tmp_path: Path
) -> None:
    """write_tree never writes into a non-empty directory, so a capture cannot overlay a
    tree.
    """
    (tmp_path / "keep.txt").write_text("x")
    with pytest.raises(capture.CaptureError, match="not empty"):
        capture.write_tree(tmp_path, {"a.txt": "a"})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep.txt"]


def test_capture_refuses_the_wrong_interpreter_before_any_git_call(
    capture: ModuleType, isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A capture off the capture interpreter is refused before any git call, and so is
    golden --init.
    """
    calls: list[object] = []
    monkeypatch.setattr(capture, "_git", lambda *a: calls.append(a) or b"")
    monkeypatch.setitem(capture.SETTINGS, "capture_python", [2, 7])
    with pytest.raises(capture.CaptureError, match="CPython 2.7"):
        capture.capture_trees(isolated / "out")
    assert calls == []
    assert capture.main(["golden", "--init"]) == 2
    assert not capture.GOLDEN.exists()


def test_archive_engine_checks_the_pinned_tree_before_archiving(
    capture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit whose custodex tree is not the pinned one is refused before git archive
    runs.
    """
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> bytes:
        calls.append(args)
        if args[0] == "rev-parse" and args[1] == "--verify":
            return b"c0ffee\n"
        return b"not-the-pinned-tree\n"

    monkeypatch.setattr(capture, "_git", fake_git)
    with pytest.raises(capture.CaptureError, match="expected"):
        capture._archive_engine("c0ffee", "pinned-tree", tmp_path / "engine")
    assert all(call[0] != "archive" for call in calls)
    assert calls, "the guard must actually consult git"


def test_stamp_refuses_an_engine_custodex_did_not_resolve_to(
    capture: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """_stamp refuses (exit 2, tree untouched) when custodex was imported from another
    engine.
    """
    tree = tmp_path / "tree"
    capture.write_tree(tree, capture.seed_files(body_tier=False))
    before = _tree_bytes(tree)
    elsewhere = tmp_path / "not-an-engine"
    elsewhere.mkdir()
    assert capture.main(["_stamp", str(tree), "--engine", str(elsewhere)]) == 2
    assert "resolved" in capsys.readouterr().err
    assert _tree_bytes(tree) == before


@pytest.mark.parametrize("variant", _VARIANTS)
def test_stamp_with_the_current_engine_reproduces_the_enc2_tree(
    capture: ModuleType, variant: str, tmp_path: Path
) -> None:
    """In-process `_stamp` with the current engine reproduces the frozen enc2 tree.

    It compares what a reader or the golden sees (``_doc_view``): code and config
    bytes, doc bodies (hand edits included), non-cdm front matter, and the
    golden-owned stamps. Unowned cdm keys are [SW] territory and are ignored, so
    an [SW] slice that adds a stamp key leaves this green. A doc a [WAVE] slice
    moved (``_ENGINE_MOVES`` "fresh stamp") is exempt here; its owned stamps are
    checked against the re-pinned golden by
    test_document_stamps_equals_what_heal_writes.
    """
    import custodex

    engine = Path(custodex.__file__).resolve().parents[1]
    tree = tmp_path / "tree"
    body_tier = capture.SETTINGS["variants"][variant]
    capture.write_tree(tree, capture.seed_files(body_tier=body_tier))
    assert capture.main(["_stamp", str(tree), "--engine", str(engine)]) == 0
    assert not (tree / ".cdmon").exists()
    frozen = _tree_view(_LEGACY / "enc2" / variant)
    fresh = _tree_view(tree)
    moved = _view_moves(frozen, fresh)
    assert moved == _engine_moves("fresh stamp", variant), sorted(moved)
    assert sum(rel.startswith("docs/") for rel in fresh) >= 5
    # the pre-P2 docs carry the composite only, whatever the engine stamps
    for doc in capture.SETTINGS["pre_p2_docs"]:
        assert set(_cdm((tree / doc).read_text(encoding="utf-8"))) == {"fingerprint"}


def test_stamp_refuses_a_tree_that_is_not_a_fixed_point(
    capture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand edit to an engine-owned region would be healed back — refuse it."""
    import custodex

    engine = Path(custodex.__file__).resolve().parents[1]
    edits = (*capture.HAND_EDITS, ("docs/neutral.md", "symbols", "hand-broken"))
    monkeypatch.setattr(capture, "HAND_EDITS", edits)
    tree = tmp_path / "tree"
    capture.write_tree(tree, capture.seed_files(body_tier=False))
    with pytest.raises(capture.CaptureError, match="not a fixed point"):
        capture.stamp(tree, engine)


def test_stamp_refuses_a_heal_that_does_not_converge(
    capture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A heal whose second run still writes is refused: frozen trees are converged."""
    import custodex
    from custodex.monitor import Monitor

    engine = Path(custodex.__file__).resolve().parents[1]
    real_run = Monitor.run
    runs: list[int] = []

    def touchy_run(self: Monitor, **kwargs: Any) -> Any:
        runs.append(1)
        result = real_run(self, **kwargs)
        if len(runs) == 2:
            doc = self.root / "docs" / "neutral.md"
            doc.write_text(doc.read_text() + "\n")
        return result

    monkeypatch.setattr(Monitor, "run", touchy_run)
    tree = tmp_path / "tree"
    capture.write_tree(tree, capture.seed_files(body_tier=False))
    with pytest.raises(capture.CaptureError, match="did not converge"):
        capture.stamp(tree, engine)


# --------------------------------------------------------------------------- #
# The surface golden                                                           #
# --------------------------------------------------------------------------- #


def test_surface_golden_matches_the_current_engine(capture: ModuleType) -> None:
    """The committed golden IS the current engine's canonical render (critique B2)."""
    golden = _golden()
    trees = capture.compute_golden()
    assert trees == golden["trees"], (
        f"the surface golden moved under CPython {sys.version.split()[0]}; only a "
        "[WAVE] slice may re-pin it (capture.py golden --repin <ID>)"
    )
    assert (
        capture.golden_digest(golden["trees"])
        == _GOLDEN_DIGESTS[tuple(golden["repins"])]
    )
    assert capture.main(["golden", "--check"]) == 0
    # the committed bytes are the canonical render (sorted keys, indent), so a
    # hand-edited golden cannot hide a value behind an equal-but-reformatted file
    assert _GOLDEN_PATH.read_text(encoding="utf-8") == capture.render_golden(
        golden["repins"], trees
    )
    # every tree carries all three parts, and none is empty
    assert sorted(trees) == sorted(
        [*_labels(capture)[len(_VARIANTS) :], "synthetic/body-off", "synthetic/body-on"]
    )
    for label, part in trees.items():
        assert part["documents"] and part["codeindex"]["files"], label
        assert part["coverage"]["files"], label


def test_surface_golden_is_computed_identically_twice(capture: ModuleType) -> None:
    """K7/K10: two computations render byte-identically, and a render round-trips."""
    first = capture.render_golden([], capture.compute_golden())
    second = capture.render_golden([], capture.compute_golden())
    assert first == second
    assert capture.render_golden([], json.loads(first)["trees"]) == first


def test_surface_golden_repins_name_only_wave_slices(capture: ModuleType) -> None:
    """The committed repins are distinct [WAVE] ids in plan order (capture.json
    wave_slices).
    """
    repins = _golden()["repins"]
    wave = list(capture.SETTINGS["wave_slices"])
    assert set(repins) <= set(wave)
    assert len(repins) == len(set(repins))
    assert repins == sorted(repins, key=wave.index)


def _part(trees: dict[str, Any], part: str) -> Iterator[dict[str, Any]]:
    for label in sorted(trees):
        yield trees[label][part]


@pytest.mark.parametrize("part", ["documents", "codeindex", "coverage"])
def test_golden_check_sees_every_part_move(
    capture: ModuleType, isolated: Path, part: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """golden --check exits 1 on a move in each part, and names the part and the
    interpreter.
    """
    trees = capture.compute_golden()
    capture.GOLDEN.write_text(capture.render_golden([], trees), encoding="utf-8")
    assert capture.main(["golden", "--check"]) == 0
    tampered = json.loads(json.dumps(trees))
    target = next(_part(tampered, part))
    if part == "documents":
        doc = target[sorted(target)[0]]
        doc["fingerprint"] = "0" * 16
    elif part == "codeindex":
        target["files"][0]["content_digest"] = "0" * 16
    else:
        target["percent_public_symbols"] = -1.0
    capture.GOLDEN.write_text(capture.render_golden([], tampered), encoding="utf-8")
    assert capture.main(["golden", "--check"]) == 1
    err = capsys.readouterr().err
    assert part in err and "CPython" in err


def test_golden_check_is_loud_on_a_missing_or_malformed_golden(
    capture: ModuleType, isolated: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing, non-object or unparsable golden is a typed refusal (exit 2), never a
    traceback (K8).
    """
    assert capture.main(["golden", "--check"]) == 2
    capture.GOLDEN.write_text("[]", encoding="utf-8")
    assert capture.main(["golden", "--check"]) == 2
    capture.GOLDEN.write_text("{not json", encoding="utf-8")
    assert capture.main(["golden", "--check"]) == 2
    assert "Traceback" not in capsys.readouterr().err


def _wave(capture: ModuleType, need: int) -> list[str]:
    """The [WAVE] ids in plan order, failing (never skipping) if fewer than ``need``.

    The repin self-tests run on an isolated golden that starts at ``repins: []``,
    so they take ids from the plan, never from the committed golden: they keep
    checking after every [WAVE] slice has re-pinned.
    """
    wave = list(capture.SETTINGS["wave_slices"])
    assert len(wave) >= need, f"the repin self-tests need {need} [WAVE] ids: {wave}"
    return wave


def test_repin_refuses_any_non_wave_slice_and_an_out_of_order_repin(
    capture: ModuleType,
    isolated: Path,
    on_capture_python: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only [WAVE] ids re-pin, exactly spelled, in plan order; --init runs once.

    A refusal writes nothing.
    """
    wave = _wave(capture, 3)
    assert capture.main(["golden", "--init"]) == 0
    initial = capture.GOLDEN.read_bytes()
    assert capture.main(["golden", "--init"]) == 2  # init is once only
    assert capture.main(["golden", "--repin", "FPW-FIXTURES"]) == 2  # not [WAVE]
    assert capture.main(["golden", "--repin", "fpw-d"]) == 2  # ids are exact
    assert capture.GOLDEN.read_bytes() == initial
    # an earlier id may not re-pin again, and a new id may not jump backwards
    assert capture.main(["golden", "--repin", wave[1]]) == 0
    assert capture.main(["golden", "--repin", wave[0]]) == 2
    assert capture.main(["golden", "--repin", wave[2]]) == 0
    assert capture.main(["golden", "--repin", wave[1]]) == 2
    assert json.loads(capture.GOLDEN.read_text())["repins"] == [wave[1], wave[2]]
    assert "refus" in capsys.readouterr().err


def test_repin_appends_to_the_existing_repins(
    capture: ModuleType, isolated: Path, on_capture_python: None
) -> None:
    """A re-pin appends its id once; the last re-pinner may repeat (K7, no dup)."""
    first, second = _wave(capture, 2)[:2]
    assert capture.main(["golden", "--init"]) == 0
    assert capture.main(["golden", "--repin", first]) == 0
    assert capture.main(["golden", "--repin", first]) == 0  # last may repeat
    assert json.loads(capture.GOLDEN.read_text())["repins"] == [first]
    assert capture.main(["golden", "--repin", second]) == 0
    assert json.loads(capture.GOLDEN.read_text())["repins"] == [first, second]


def test_repin_replaces_stale_values_with_the_current_engine(
    capture: ModuleType, isolated: Path, on_capture_python: None
) -> None:
    """A re-pin rewrites stale golden values from the current engine; --check passes."""
    trees = capture.compute_golden()
    stale = json.loads(json.dumps(trees))
    for part in _part(stale, "coverage"):
        part["percent_files"] = -1.0
    capture.GOLDEN.write_text(capture.render_golden([], stale), encoding="utf-8")
    assert capture.main(["golden", "--check"]) == 1
    first = _wave(capture, 1)[0]
    assert capture.main(["golden", "--repin", first]) == 0
    golden = json.loads(capture.GOLDEN.read_text())
    assert golden["trees"] == trees
    assert golden["repins"] == [first]
    assert capture.main(["golden", "--check"]) == 0


def test_document_stamps_equals_what_heal_writes(
    capture: ModuleType, tmp_path: Path, fresh_enc2: dict[str, Path]
) -> None:
    """The golden's document projection IS what the current heal stamps.

    The enc2 rows are compared with a FRESH stamp of the seed (same code and
    config as the frozen enc2 tree), not with the frozen bytes, so a [WAVE]
    re-pin that moves the stamps keeps this an equality with the new golden.
    """
    trees = capture.compute_golden()
    compared_anchor_regions = 0
    duplicate_anchor_regions = 0
    sources: dict[str, Path] = {}
    for label in trees:
        enc, variant = label.split("/")
        if enc == "synthetic":
            tree = tmp_path / label
            body_tier = capture.SETTINGS["variants"][variant]
            capture.write_tree(tree, capture.synthetic_files(body_tier=body_tier))
            _restamp(capture, tree)
            sources[label] = tree
        else:
            sources[label] = fresh_enc2[variant]
    for label, tree in sources.items():
        for doc_id, want in trees[label]["documents"].items():
            cdm = _cdm((tree / want["path"]).read_text(encoding="utf-8"))
            if set(cdm) == {"fingerprint"}:  # the composite-only pre-P2 doc
                assert cdm["fingerprint"] == want["fingerprint"], (label, doc_id)
                continue
            assert cdm["fingerprint"] == want["fingerprint"], (label, doc_id)
            assert cdm["fingerprint_tiers"] == want["fingerprint_tiers"], (
                label,
                doc_id,
            )
            assert cdm["symbol_sigs"] == want["symbol_sigs"], (label, doc_id)
            for region_id, anchors in cdm.get("region_anchors", {}).items():
                assert anchors == want["region_anchors"][region_id], (label, doc_id)
                compared_anchor_regions += 1
                duplicate_anchor_regions += len(anchors) != len(set(anchors))
    assert compared_anchor_regions >= len(sources)
    assert duplicate_anchor_regions >= 2, "the same-name tie must repeat an anchor"


def test_synthetic_golden_tree_exercises_every_shape(capture: ModuleType) -> None:
    """One liveness row per synthetic shape: dropping any shape fails a row."""
    golden = _golden()["trees"]
    for variant in _VARIANTS:
        part = golden[f"synthetic/{variant}"]
        docs = part["documents"]

        def names(doc_id: str, docs: dict[str, Any] = docs) -> list[str]:
            return [s[0] for s in docs[doc_id]["surface"]["symbols"]]

        def records(doc_id: str, docs: dict[str, Any] = docs) -> list[list[str]]:
            return [[r["kind"], r["name"]] for r in docs[doc_id]["surface"]["records"]]

        index = {f["path"]: f for f in part["codeindex"]["files"]}
        # shell `lines` ref selects exactly the function in range
        assert names("shell") == ["package"], variant
        assert index["tools/build.sh"]["language"] == "unknown"
        # dataclass fields via class-member expansion (`symbols: [Point]`)
        assert {"Point.x", "Point.y", "Point.tags", "Point.norm"} <= set(
            names("shapes")
        )
        # same-name tie across two files; user-guide drops the private helper (K3)
        assert names("tie") == ["clean", "clean"], variant
        assert len(docs["tie"]["region_anchors"]["symbols"]) == 2
        assert len(set(docs["tie"]["region_anchors"]["symbols"])) == 1
        assert "_trim" in [s["name"] for s in index["pkg/text_a.py"]["symbols"]]
        # multi-entry `names:` keeps only variables (ping is a function)
        assert names("settings") == ["DEFAULT_TIMEOUT", "_SECRET"], variant
        sigs = {s["name"]: s["signature"] for s in index["pkg/settings.py"]["symbols"]}
        assert sigs["EXACT_48"] != "EXACT_48 = ..."
        assert len(sigs["EXACT_48"]) == len("EXACT_48 = ") + 48
        assert sigs["LONG_49"] == "LONG_49 = ..."
        # symbols + lines (edges) in one ref, arg_signature in another
        assert names("multi-entry") == [
            "Router",
            "Router.dispatch",
            "Router.on_delete",
            "Router.on_post",
            "on_get",
            "ping",
        ], variant
        # argparse records (long default elided) + python switches, one doc
        mixed = records("mixed-records")
        assert ["option", "--output"] in mixed and ["switch", "-q"] in mixed
        options = {
            r["name"]: r["fields"]
            for r in docs["mixed-records"]["surface"]["records"]
            if r["kind"] == "option"
        }
        assert options["--output"]["default"].endswith("..."), variant
        assert len(options["--output"]["default"]) == 80
        # JSON records + shell case-arm switches (no getopts)
        assert ["record", "--fast"] in records("flags")
        assert ["switch", "--dry-run"] in records("shell")
        assert ["switch", "-n"] in records("shell")
        # tcl (switch -regexp block + regexp class) and a getopts optstring that
        # outranks the case arms (`--help`) and is not an option itself (`:`)
        assert records("tooling") == [
            ["switch", name]
            for name in ("-h", "-o", "-out-dir", "-q", "-v", "-verbose")
        ], variant
        # coverage: a waiver, an undocumented public file, a non-trivial percent
        coverage = part["coverage"]
        assert [f["path"] for f in coverage["waived_files"]] == ["pkg/legacy_api.py"]
        assert "pkg/orphan.py" in [f["path"] for f in coverage["undocumented_files"]]
        assert 0.0 < coverage["percent_public_symbols"] < 100.0
    on = golden["synthetic/body-on"]["documents"]["shapes"]["fingerprint_tiers"]
    off = golden["synthetic/body-off"]["documents"]["shapes"]["fingerprint_tiers"]
    assert "body" in on and "body" not in off


def test_golden_repins_must_be_distinct_wave_ids_in_plan_order(
    capture: ModuleType, isolated: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """K8: a golden whose ``repins`` are not distinct [WAVE] ids in order is refused.

    This is what makes the re-pin order check sufficient on its own: with
    ``repins`` strictly increasing, an id that re-pinned before always sorts
    before the last re-pinner.
    """
    wave = list(capture.SETTINGS["wave_slices"])
    capture.GOLDEN.write_text(json.dumps({"repins": wave[:2], "trees": {}}))
    assert capture.load_golden()["repins"] == wave[:2]
    for repins in ([wave[1], wave[0]], [wave[0], wave[0]], ["nope"], [1]):
        capture.GOLDEN.write_text(json.dumps({"repins": repins, "trees": {}}))
        before = capture.GOLDEN.read_bytes()
        assert capture.main(["golden", "--check"]) == 2, repins
        assert capture.main(["golden", "--repin", wave[-1]]) == 2, repins
        assert capture.GOLDEN.read_bytes() == before
        assert "plan order" in capsys.readouterr().err


def test_every_repin_has_a_row_in_each_keyed_table() -> None:
    """A [WAVE] re-pin adds its ``repins`` tuple to BOTH keyed tables, fully shaped."""
    repins = tuple(_golden()["repins"])
    missing = [
        name
        for name, table in (
            ("_GOLDEN_DIGESTS", _GOLDEN_DIGESTS),
            ("_ENGINE_MOVES", _ENGINE_MOVES),
        )
        if repins not in table
    ]
    assert not missing, f"the re-pin {repins} needs a row in {missing}"
    assert set(_GOLDEN_DIGESTS) == set(_ENGINE_MOVES)
    for row in _ENGINE_MOVES.values():
        assert set(row) == {"restamp enc1", "restamp enc2", "fresh stamp"}
        assert all(set(per) == set(_VARIANTS) for per in row.values())
        assert all(row["restamp enc1"].values()), "the enc-1 sentinel is never empty"


# --------------------------------------------------------------------------- #
# Capture-tool guards found by mutation round 1                                #
# --------------------------------------------------------------------------- #


def test_archive_engine_checks_the_commit_names_itself(
    capture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pin that resolves to another commit (a moved tag) is refused pre-archive."""
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> bytes:
        calls.append(args)
        if args[:2] == ("rev-parse", "--verify"):
            return b"f" * 40 + b"\n"  # a tag/branch pin resolving elsewhere
        return b"pinned-tree\n"  # the tree guard alone would pass

    monkeypatch.setattr(capture, "_git", fake_git)
    with pytest.raises(capture.CaptureError, match="expected the commit itself"):
        capture._archive_engine("v-tag", "pinned-tree", tmp_path / "engine")
    assert calls == [("rev-parse", "--verify", "v-tag^{commit}")]


def test_trees_check_sees_a_file_the_recapture_lost(
    capture: ModuleType, isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`trees --check` compares both ways: a frozen file the recapture lacks differs."""

    def fake_capture(dest: Path) -> None:
        for label in _labels(capture):
            shutil.copytree(_LEGACY / label, dest / label)

    monkeypatch.setattr(capture, "capture_trees", fake_capture)
    assert capture.main(["trees", "--write"]) == 0

    def lossy_capture(dest: Path) -> None:
        fake_capture(dest)
        (dest / "enc2" / "body-on" / "docs" / "legacy.md").unlink()

    monkeypatch.setattr(capture, "capture_trees", lossy_capture)
    assert capture.main(["trees", "--check"]) == 1


def test_manifest_check_refuses_zero_frozen_files(
    capture: ModuleType, isolated: Path
) -> None:
    """A manifest check over zero frozen files is a refusal, never a vacuous pass."""
    capture.MANIFEST.write_text("", encoding="utf-8")
    assert capture.main(["manifest"]) == 2


def test_hand_edit_on_a_missing_region_is_refused(
    capture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand edit whose region is absent fails loudly (K8) and writes nothing."""
    tree = tmp_path / "tree"
    capture.write_tree(tree, capture.seed_files(body_tier=False))
    before = _tree_bytes(tree)
    monkeypatch.setattr(capture, "HAND_EDITS", (("docs/neutral.md", "nope", "x"),))
    with pytest.raises(capture.CaptureError, match="expected one region 'nope', got 0"):
        capture.apply_hand_edits(tree)
    assert _tree_bytes(tree) == before


def test_repin_refuses_the_wrong_interpreter(
    capture: ModuleType,
    isolated: Path,
    on_capture_python: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`golden --repin` refuses off the capture interpreter; the golden is untouched."""
    first = _wave(capture, 1)[0]
    assert capture.main(["golden", "--init"]) == 0
    initial = capture.GOLDEN.read_bytes()
    monkeypatch.setitem(capture.SETTINGS, "capture_python", [2, 7])
    assert capture.main(["golden", "--repin", first]) == 2
    assert capture.GOLDEN.read_bytes() == initial


@pytest.mark.parametrize("line_count", [0, 2])
def test_body_tier_line_must_appear_once(
    capture: ModuleType, monkeypatch: pytest.MonkeyPatch, line_count: int
) -> None:
    """The body-on variant flips exactly one config line; zero or two is refused."""
    line = capture.SETTINGS["body_tier_line"]
    real = capture._walk

    def walk(root: Path) -> dict[str, bytes]:
        files = dict(real(root))
        cfg = files[capture.CONFIG_NAME].decode()
        cfg = cfg.replace(line + "\n", (line + "\n") * line_count)
        files[capture.CONFIG_NAME] = cfg.encode()
        return files

    monkeypatch.setattr(capture, "_walk", walk)
    with pytest.raises(capture.CaptureError, match="once"):
        capture.seed_files(body_tier=True)


def test_golden_with_an_unknown_key_is_refused(
    capture: ModuleType, isolated: Path
) -> None:
    """K8: the golden holds exactly ``repins`` and ``trees``; extra keys are refused."""
    capture.GOLDEN.write_text(
        json.dumps({"repins": [], "trees": {}, "about": "x"}), encoding="utf-8"
    )
    assert capture.main(["golden", "--check"]) == 2


def test_run_stamp_resolves_custodex_to_the_archived_engine(
    capture: ModuleType, tmp_path: Path, fresh_enc2: dict[str, Path]
) -> None:
    """The real subprocess path, with an engine dir that is NOT the repo.

    The subprocess must import ``custodex`` from the engine dir it was given (the
    stamp's own guard refuses otherwise) and stamp exactly what the in-process
    path stamps with the same engine.
    """
    import custodex

    engine = tmp_path / "engine"
    shutil.copytree(
        Path(custodex.__file__).resolve().parent,
        engine / "custodex",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    tree = tmp_path / "tree"
    capture.write_tree(tree, capture.seed_files(body_tier=False))
    capture._run_stamp(tree, engine, tmp_path)
    assert _tree_bytes(tree) == _tree_bytes(fresh_enc2["body-off"])


# --------------------------------------------------------------------------- #
# Capture-tool guards found by mutation round 2                                #
# --------------------------------------------------------------------------- #


def test_golden_check_sees_a_tree_added_or_removed(
    capture: ModuleType, isolated: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """golden --check exits 1 when the stored golden gains or loses a whole tree."""
    trees = capture.compute_golden()
    first = sorted(trees)[0]
    extra = {**trees, "enc9/body-off": trees[first]}
    capture.GOLDEN.write_text(capture.render_golden([], extra), encoding="utf-8")
    assert capture.main(["golden", "--check"]) == 1
    assert "enc9/body-off (tree added or removed)" in capsys.readouterr().err
    fewer = {k: v for k, v in trees.items() if k != first}
    capture.GOLDEN.write_text(capture.render_golden([], fewer), encoding="utf-8")
    assert capture.main(["golden", "--check"]) == 1
    assert f"{first} (tree added or removed)" in capsys.readouterr().err


@pytest.mark.parametrize("part", ["documents", "codeindex", "coverage"])
def test_golden_check_sees_a_part_missing_from_the_stored_golden(
    capture: ModuleType, isolated: Path, part: str
) -> None:
    """A stored tree that lost a whole part is a move, not a silent pass."""
    trees = capture.compute_golden()
    del trees[sorted(trees)[0]][part]
    capture.GOLDEN.write_text(capture.render_golden([], trees), encoding="utf-8")
    assert capture.main(["golden", "--check"]) == 1


def test_trees_check_sees_a_file_only_the_recapture_has(
    capture: ModuleType, isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`trees --check` compares both ways: an extra recaptured file differs too."""

    def fake_capture(dest: Path) -> None:
        for label in _labels(capture):
            shutil.copytree(_LEGACY / label, dest / label)

    monkeypatch.setattr(capture, "capture_trees", fake_capture)
    assert capture.main(["trees", "--write"]) == 0

    def grown_capture(dest: Path) -> None:
        fake_capture(dest)
        (dest / "enc2" / "body-on" / "docs" / "extra.md").write_text("x\n")

    monkeypatch.setattr(capture, "capture_trees", grown_capture)
    assert capture.main(["trees", "--check"]) == 1


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no front matter\n", "needs YAML front matter"),
        ("---\n- a list\n---\nbody\n", "needs a stamped cdm mapping"),
        ("---\ncdm: 3\n---\nbody\n", "needs a stamped cdm mapping"),
        ("---\ncdm:\n  region_hashes: {}\n---\nbody\n", "cdm.fingerprint"),
    ],
)
def test_pre_p2_strip_refuses_a_doc_it_cannot_strip(
    capture: ModuleType, text: str, message: str
) -> None:
    """K8: a pre-P2 doc missing front matter, cdm or the composite is refused."""
    with pytest.raises(capture.CaptureError, match=message):
        capture.pre_p2_text(text)


def test_run_stamp_raises_when_the_subprocess_refuses(
    capture: ModuleType, tmp_path: Path
) -> None:
    """A failed `_stamp` subprocess surfaces as CaptureError, never a silent pass."""
    tree = tmp_path / "tree"
    capture.write_tree(tree, capture.seed_files(body_tier=False))
    before = _tree_bytes(tree)
    empty = tmp_path / "engine"
    empty.mkdir()
    with pytest.raises(capture.CaptureError, match="stamping"):
        capture._run_stamp(tree, empty, tmp_path)
    assert _tree_bytes(tree) == before


def test_capture_trees_stamps_each_variant_with_its_body_tier(
    capture: ModuleType,
    tmp_path: Path,
    on_capture_python: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each encodings x variants tree is seeded with its variant's body tier and
    stamped with its own encoding's engine.
    """
    stamped: list[tuple[str, str, str, bool]] = []
    monkeypatch.setattr(
        capture, "_archive_engine", lambda commit, tree, dest: Path(commit)
    )

    def record(tree: Path, engine: Path, cwd: Path) -> None:
        cfg = (tree / capture.CONFIG_NAME).read_text(encoding="utf-8")
        line = capture.SETTINGS["body_tier_line"]
        stamped.append((tree.parent.name, tree.name, str(engine), line in cfg))

    monkeypatch.setattr(capture, "_run_stamp", record)
    capture.capture_trees(tmp_path / "out")
    want = [
        (label, variant, pin["commit"], not body_tier)
        for label, pin in capture.SETTINGS["encodings"].items()
        for variant, body_tier in capture.SETTINGS["variants"].items()
    ]
    assert stamped == want
    assert any(off for *_, off in stamped) and not all(off for *_, off in stamped)


def test_capture_refuses_a_tarfile_without_extraction_filters(
    capture: ModuleType,
    tmp_path: Path,
    on_capture_python: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``tarfile.data_filter`` the capture is refused before any git call."""
    calls: list[object] = []
    monkeypatch.setattr(capture, "_git", lambda *a: calls.append(a) or b"")
    monkeypatch.delattr(tarfile, "data_filter", raising=False)
    with pytest.raises(capture.CaptureError, match="3.11.4"):
        capture.capture_trees(tmp_path / "out")
    assert calls == []


def test_capture_refuses_a_non_cpython_interpreter(
    capture: ModuleType,
    tmp_path: Path,
    on_capture_python: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ast.dump body tier is implementation-specific: PyPy is refused too."""
    monkeypatch.setattr(sys, "implementation", SimpleNamespace(name="pypy"))
    with pytest.raises(capture.CaptureError, match="pypy"):
        capture.capture_trees(tmp_path / "out")


def test_hand_edit_on_a_duplicated_region_is_refused(capture: ModuleType) -> None:
    """Two regions with one id are ambiguous: refuse, never rewrite both."""
    text = (
        "<!-- CDM:BEGIN symbols -->\na\n<!-- CDM:END symbols -->\n"
        "<!-- CDM:BEGIN symbols -->\nb\n<!-- CDM:END symbols -->\n"
    )
    with pytest.raises(capture.CaptureError, match="got 2"):
        capture._replace_region(text, "symbols", "x", "doc.md")


def test_stamp_accepts_a_relative_engine_path(
    capture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_stamp --engine` compares resolved paths: a relative spelling is the same
    engine.
    """
    import custodex

    engine = Path(custodex.__file__).resolve().parents[1]
    tree = tmp_path / "tree"
    capture.write_tree(tree, capture.seed_files(body_tier=False))
    monkeypatch.chdir(engine)
    assert capture.main(["_stamp", str(tree), "--engine", "."]) == 0


def test_view_moves_refuses_a_file_set_change() -> None:
    """A restamp that adds or deletes a file is a failure, not an ignored key."""
    with pytest.raises(AssertionError):
        _view_moves({"a": 1, "b": 2}, {"a": 1})
    with pytest.raises(AssertionError):
        _view_moves({"a": 1}, {"a": 1, "b": 2})


def test_engine_moves_is_keyed_by_the_committed_repins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The [WAVE] update route: after a re-pin with no ``_ENGINE_MOVES`` row, every
    current-engine check fails naming the row to add, never a stale row.
    """
    golden = _golden()
    golden["repins"] = ["FPW-D"]
    path = tmp_path / "surface_golden.json"
    path.write_text(json.dumps(golden), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_GOLDEN_PATH", path)
    with pytest.raises(AssertionError, match="no _ENGINE_MOVES row"):
        _engine_moves("restamp enc2", "body-off")
