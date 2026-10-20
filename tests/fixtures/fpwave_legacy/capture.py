"""Capture the frozen fingerprint-wave fixtures and keep the surface golden (FPW).

Two committed data sets live next to this tool:

``enc1/``, ``enc2/`` + ``SHA256SUMS`` — the **frozen legacy trees**. The mini repo
under ``seed/`` stamped by two pinned engines (``capture.json`` ``encodings``:
enc1 = the engine before step 0, enc2 = step-0 main), each with the body tier
off and on (``variants``). They are WRITE-ONCE: ``trees --write`` refuses while
any part exists, and ``SHA256SUMS`` pins every byte. A tree is captured as:

1. ``git archive`` the pinned commit's ``custodex/`` into a scratch dir, after
   checking that the commit's ``custodex`` tree id is the pinned one;
2. copy ``seed/`` into the destination (the body-on variant flips the one
   ``body_tier_line`` in its config);
3. in a subprocess whose ``custodex`` resolves to that archive (checked):
   ``Monitor.run(apply=True)`` with the offline mock backend, then once more
   (it must converge — a second heal writes nothing);
4. AFTER the heal, the tool itself applies ``hand_edits`` (a human editing a
   region after its last heal) and strips each ``pre_p2_docs`` doc's ``cdm`` to
   the composite ``fingerprint`` (a doc last stamped before per-tier
   fingerprints) — no engine wrote those bytes;
5. one more heal must change nothing (the tree is a fixed point of its engine),
   and the review log (``.cdmon/``) is discarded.

Captures run only on the interpreter ``capture_python`` names: the body tier
hashes ``ast.dump`` output, which differs across CPython minors.

``../surface_golden.json`` — the **surface golden**: what the CURRENT engine
derives from the ``golden_encoding`` frozen tree and from ``synthetic/`` (each
variant): per document the fingerprint, its tiers, symbol_sigs, region_anchors
and the selected surface; the code index (provenance fields dropped); and the
coverage manifest. ``golden --check`` fails on any move; ``golden --repin ID``
rewrites it from the current engine and appends ``ID`` to ``repins``, and only a
[WAVE] slice (``wave_slices``, in plan order) may do that. The tool refuses a
mis-flagged re-pin; review rejects an unflagged one.

Usage (from the repo root, with the engine importable)::

    python tests/fixtures/fpwave_legacy/capture.py trees --write | --check
    python tests/fixtures/fpwave_legacy/capture.py manifest
    python tests/fixtures/fpwave_legacy/capture.py golden --init | --check
    python tests/fixtures/fpwave_legacy/capture.py golden --repin FPW-D

Exit codes: 0 ok, 1 a check found a difference, 2 refused or malformed input.
``tarfile``'s ``filter="data"`` needs CPython 3.11.4+; the capture guard checks it.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

TOOL_DIR = Path(__file__).resolve().parent
REPO = TOOL_DIR.parents[2]
SETTINGS_PATH = TOOL_DIR / "capture.json"
SEED = TOOL_DIR / "seed"
SYNTHETIC = TOOL_DIR / "synthetic"
# Where the frozen trees, their manifest and the golden live (tests repoint these).
HERE = TOOL_DIR
MANIFEST = HERE / "SHA256SUMS"
GOLDEN = TOOL_DIR.parent / "surface_golden.json"

_SKIPPED_PARTS = frozenset({"__pycache__", ".cdmon"})
_FRONT_MATTER = re.compile(r"\A---\n(.*?)^---\n", re.S | re.M)


class CaptureError(Exception):
    """A refused or malformed capture/golden operation (exit code 2)."""


def _load_settings() -> dict[str, Any]:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureError(f"cannot read {SETTINGS_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise CaptureError(f"{SETTINGS_PATH} must hold a JSON object")
    return data


SETTINGS: dict[str, Any] = _load_settings()
CONFIG_NAME: str = SETTINGS["config_name"]
HAND_EDITS: tuple[tuple[str, str, str], ...] = tuple(
    (e["doc"], e["region"], e["body"]) for e in SETTINGS["hand_edits"]
)


# --------------------------------------------------------------------------- #
# Trees on disk                                                                #
# --------------------------------------------------------------------------- #


def _walk(root: Path) -> dict[str, bytes]:
    """``relpath -> bytes`` for each file under ``root`` (no caches, no review log)."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not _SKIPPED_PARTS.intersection(p.relative_to(root).parts)
    }


def _source_files(source: Path, *, body_tier: bool) -> dict[str, str]:
    files = {rel: data.decode("utf-8") for rel, data in _walk(source).items()}
    if body_tier:
        line = SETTINGS["body_tier_line"]
        config = files[CONFIG_NAME]
        if config.count(line + "\n") != 1:
            raise CaptureError(f"{source / CONFIG_NAME} must carry {line!r} once")
        files[CONFIG_NAME] = config.replace(line, line.replace("false", "true"))
    return files


def seed_files(*, body_tier: bool) -> dict[str, str]:
    """The committed seed repo (``seed/``), body tier switched as asked."""
    return _source_files(SEED, body_tier=body_tier)


def synthetic_files(*, body_tier: bool) -> dict[str, str]:
    """The golden-only synthetic repo (``synthetic/``), body tier switched as asked."""
    return _source_files(SYNTHETIC, body_tier=body_tier)


def write_tree(dest: Path, files: dict[str, str]) -> None:
    """Materialise ``files`` under ``dest``; refuse a non-empty destination."""
    if dest.exists() and any(dest.iterdir()):
        raise CaptureError(f"refusing to write into {dest}: it is not empty")
    for rel, text in sorted(files.items()):
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def frozen_files(root: Path) -> dict[str, bytes]:
    """Every file of every frozen tree under ``root`` (``enc*/``), keyed by relpath.

    A missing ``enc*`` dir contributes nothing (``rglob`` yields nothing for it);
    callers that need files refuse an empty result themselves.
    """
    return {
        f"{label}/{rel}": data
        for label in SETTINGS["encodings"]
        for rel, data in _walk(root / label).items()
    }


def render_manifest(files: dict[str, bytes]) -> str:
    """``sha256sum``-compatible manifest text, sorted by path (K10)."""
    return "".join(
        f"{hashlib.sha256(data).hexdigest()}  {rel}\n"
        for rel, data in sorted(files.items())
    )


# --------------------------------------------------------------------------- #
# Stamping (runs inside the subprocess whose `custodex` is the pinned engine)  #
# --------------------------------------------------------------------------- #


def _replace_region(text: str, region_id: str, body: str, where: str) -> str:
    pattern = re.compile(
        rf"(<!-- CDM:BEGIN {re.escape(region_id)} -->\n).*?"
        rf"(<!-- CDM:END {re.escape(region_id)} -->)",
        re.S,
    )
    new, count = pattern.subn(lambda m: m.group(1) + body + "\n" + m.group(2), text)
    if count != 1:
        raise CaptureError(f"{where}: expected one region {region_id!r}, got {count}")
    return new


def apply_hand_edits(tree: Path) -> None:
    """Overwrite each ``HAND_EDITS`` region body, as a human would after a heal."""
    for doc, region_id, body in HAND_EDITS:
        path = tree / doc
        text = path.read_text(encoding="utf-8")
        path.write_text(_replace_region(text, region_id, body, doc), encoding="utf-8")


def pre_p2_text(text: str) -> str:
    """Strip a doc's ``cdm`` to the composite ``fingerprint`` (block-style YAML).

    The layout is the one ``render_doc`` writes (``yaml.safe_dump``, sorted keys,
    block style), so the doc reads like one an older heal stamped. Idempotent.
    """
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise CaptureError("a pre-P2 doc needs YAML front matter")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict) or not isinstance(meta.get("cdm"), dict):
        raise CaptureError("a pre-P2 doc needs a stamped cdm mapping")
    fingerprint = meta["cdm"].get("fingerprint")
    if not isinstance(fingerprint, str):
        raise CaptureError("a pre-P2 doc needs a stamped cdm.fingerprint")
    meta["cdm"] = {"fingerprint": fingerprint}
    front = yaml.safe_dump(meta, sort_keys=True, default_flow_style=False)
    return f"---\n{front}---\n{text[match.end() :]}"


def strip_pre_p2(tree: Path) -> None:
    for doc in SETTINGS["pre_p2_docs"]:
        path = tree / doc
        path.write_text(pre_p2_text(path.read_text(encoding="utf-8")), encoding="utf-8")


def stamp(tree: Path, engine: Path) -> None:
    """Heal ``tree`` with the engine ``custodex`` resolved to, then freeze it.

    Refuses (``CaptureError``) when ``custodex`` is not imported from ``engine``,
    when a second heal still writes (no convergence), or when a heal after the
    hand edits and the pre-P2 strip writes (not a fixed point of this engine).
    """
    import custodex

    resolved = Path(custodex.__file__).resolve().parents[1]
    if resolved != engine.resolve():
        raise CaptureError(
            f"custodex resolved to {resolved}, not the requested engine {engine}"
        )
    from custodex.config import load_config
    from custodex.monitor import Monitor

    config = load_config(tree / CONFIG_NAME)
    now = SETTINGS["now"]

    def heal() -> None:
        Monitor(config, tree, now=lambda: now).run(apply=True)

    heal()
    healed = _walk(tree)
    heal()
    if _walk(tree) != healed:
        raise CaptureError(f"{tree}: the heal did not converge")
    apply_hand_edits(tree)
    strip_pre_p2(tree)
    edited = _walk(tree)
    heal()
    if _walk(tree) != edited:
        moved = sorted(r for r, d in _walk(tree).items() if edited.get(r) != d)
        raise CaptureError(f"{tree}: not a fixed point of its engine: {moved}")
    shutil.rmtree(tree / ".cdmon", ignore_errors=True)


# --------------------------------------------------------------------------- #
# Capturing (git + subprocess)                                                 #
# --------------------------------------------------------------------------- #


def _git(*args: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise CaptureError(f"git {' '.join(args)} failed: {err}")
    return proc.stdout


def _require_capture_python() -> None:
    want = tuple(SETTINGS["capture_python"])
    have = sys.version_info[: len(want)]
    if sys.implementation.name != "cpython" or have != want:
        raise CaptureError(
            f"captures run on CPython {'.'.join(map(str, want))} only (the body "
            f"tier hashes ast.dump); this is {sys.implementation.name} "
            f"{sys.version.split()[0]}"
        )
    if not hasattr(tarfile, "data_filter"):
        raise CaptureError("tarfile extraction filters need CPython 3.11.4+")


def _archive_engine(commit: str, engine_tree: str, dest: Path) -> Path:
    """Extract the pinned commit's ``custodex/`` into ``dest``; return ``dest``."""
    got = _git("rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    if got != commit:
        raise CaptureError(f"{commit} resolved to {got!r}, expected the commit itself")
    tree = _git("rev-parse", f"{commit}:custodex").decode().strip()
    if tree != engine_tree:
        raise CaptureError(
            f"{commit}:custodex is tree {tree!r}, expected the pinned {engine_tree!r}"
        )
    data = _git("archive", "--format=tar", commit, "custodex")
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(dest, filter="data")
    return dest


def _run_stamp(tree: Path, engine: Path, cwd: Path) -> None:
    """Run ``_stamp`` in a subprocess whose only import root is ``engine``.

    ``cwd`` (the capture's scratch dir) does not steer imports: a script's
    ``sys.path[0]`` is its own dir, and ``PYTHONPATH`` is the engine alone. It is
    there so that a stray relative write by an archived engine lands in scratch,
    never in the repo the tool was launched from.
    """
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "_stamp", str(tree)]
        + ["--engine", str(engine)],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={"PYTHONPATH": str(engine), "PATH": "/usr/bin:/bin"},
    )
    if proc.returncode != 0:
        raise CaptureError(f"stamping {tree} failed:\n{proc.stderr}")


def capture_trees(dest: Path) -> None:
    """Capture every ``encodings`` x ``variants`` tree under ``dest``."""
    _require_capture_python()
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        for label, pin in SETTINGS["encodings"].items():
            engine = _archive_engine(
                pin["commit"], pin["engine_tree"], scratch / f"engine-{label}"
            )
            for variant, body_tier in SETTINGS["variants"].items():
                tree = dest / label / variant
                write_tree(tree, seed_files(body_tier=body_tier))
                _run_stamp(tree, engine, scratch)


def _trees_write() -> int:
    present = [
        p.name
        for p in (*(HERE / label for label in SETTINGS["encodings"]), MANIFEST)
        if p.exists()
    ]
    if present:
        raise CaptureError(
            f"refusing to recapture: {present} exist and the frozen trees are "
            "write-once (a new encoding gets a new label, never an overwrite)"
        )
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "staged"
        capture_trees(staged)
        for label in SETTINGS["encodings"]:
            shutil.copytree(staged / label, HERE / label)
    MANIFEST.write_text(render_manifest(frozen_files(HERE)), encoding="utf-8")
    return 0


def _trees_check() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "staged"
        capture_trees(staged)
        fresh = frozen_files(staged)
    frozen = frozen_files(HERE)
    moved = sorted(
        r for r in fresh.keys() | frozen.keys() if fresh.get(r) != frozen.get(r)
    )
    if moved:
        print(f"recapture differs from the frozen trees: {moved}", file=sys.stderr)
        return 1
    return 0


def _manifest_check() -> int:
    try:
        listed = MANIFEST.read_text(encoding="utf-8")
    except OSError as exc:
        raise CaptureError(f"cannot read {MANIFEST}: {exc}") from exc
    files = frozen_files(HERE)
    if not files:
        raise CaptureError(f"no frozen trees under {HERE}")
    if render_manifest(files) != listed:
        print(f"{MANIFEST} does not match the frozen trees", file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# The surface golden (runs on the current engine)                              #
# --------------------------------------------------------------------------- #


def document_stamps(spec: Any, root: Path, *, include_body: bool) -> dict[str, Any]:
    """What heal stamps for one document, plus the surface it was derived from.

    The composite, the tiers as ``set_fingerprint_tiers`` stores them and
    ``symbol_sigs`` are exactly what ``heal._corrected`` stamps. ``region_anchors``
    is a SUPERSET of what heal stamps: the anchor list ``set_region_anchors``
    would store (sorted, duplicates kept) for every declared ``REGION_KEYS``
    region, whatever its mode. Heal stamps only the regions it authors or skips
    by its own rules, so a consumer compares the regions heal did stamp against
    this map, never the reverse.
    """
    from custodex.blocks import REGION_KEYS
    from custodex.extract import build_document_surface
    from custodex.manifest import set_fingerprint_tiers

    surface = build_document_surface(spec, root)
    fp = surface.fingerprint(include_body=include_body)
    anchors = sorted(s.anchor_id for s in surface.symbols)
    return {
        "path": spec.path,
        "fingerprint": fp.composite,
        "fingerprint_tiers": set_fingerprint_tiers({}, fp)["cdm"]["fingerprint_tiers"],
        "symbol_sigs": dict(fp.sig_by_anchor or {}),  # rendered with sort_keys (K10)
        "region_anchors": {
            rid: anchors for rid in sorted(spec.region_keys) if rid in REGION_KEYS
        },
        "surface": {
            "symbols": [[s.name, s.kind, s.signature] for s in surface.symbols],
            "records": [
                {"kind": r.kind, "name": r.name, "fields": dict(r.fields)}
                for r in surface.records
            ],
        },
    }


def tree_golden(root: Path) -> dict[str, Any]:
    """Documents + code index + coverage manifest the current engine derives."""
    from custodex import inventory
    from custodex.cli import _coverage_manifest_text
    from custodex.codeindex import build_code_index
    from custodex.config import load_config
    from custodex.coverage import resolve_coverage

    config = load_config(root / CONFIG_NAME)
    include_body = config.fingerprint_body_tier
    index = build_code_index(config, root)
    files = inventory.discover_files(
        root, include=config.coverage.include, exclude=config.coverage.exclude
    )
    report = resolve_coverage(config, inventory.discover_symbols(files, root))
    return {
        "documents": {
            spec.id: document_stamps(spec, root, include_body=include_body)
            for spec in config.documents
        },
        "codeindex": index.model_dump(
            mode="json", exclude={"generated_by", "source_sha"}
        ),
        "coverage": json.loads(_coverage_manifest_text(report, config)),
    }


def compute_golden() -> dict[str, Any]:
    """The golden ``trees`` payload, computed afresh from the current engine."""
    out: dict[str, Any] = {}
    encoding = SETTINGS["golden_encoding"]
    for variant in SETTINGS["variants"]:
        out[f"{encoding}/{variant}"] = tree_golden(TOOL_DIR / encoding / variant)
    with tempfile.TemporaryDirectory() as tmp:
        for variant, body_tier in SETTINGS["synthetic_variants"].items():
            tree = Path(tmp) / variant
            write_tree(tree, synthetic_files(body_tier=body_tier))
            out[f"synthetic/{variant}"] = tree_golden(tree)
    return out


def golden_digest(trees: dict[str, Any]) -> str:
    blob = json.dumps(trees, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def render_golden(repins: list[str], trees: dict[str, Any]) -> str:
    payload = {"repins": list(repins), "trees": trees}
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load_golden() -> dict[str, Any]:
    """Read and shape-check the committed golden; ``CaptureError`` if unusable (K8)."""
    try:
        data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureError(f"cannot read the golden {GOLDEN}: {exc}") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"repins", "trees"}
        or not isinstance(data["repins"], list)
        or not isinstance(data["trees"], dict)
    ):
        raise CaptureError(f"{GOLDEN} must be an object with 'repins' and 'trees'")
    wave: list[str] = list(SETTINGS["wave_slices"])
    repins = data["repins"]
    order = [wave.index(r) if isinstance(r, str) and r in wave else -1 for r in repins]
    if -1 in order or order != sorted(set(order)):
        raise CaptureError(
            f"{GOLDEN} repins {repins!r} must be distinct [WAVE] ids in plan "
            f"order {wave}"
        )
    return data


def _moved_parts(want: dict[str, Any], got: dict[str, Any]) -> list[str]:
    moved: list[str] = []
    for label in sorted(want.keys() | got.keys()):
        if label not in want or label not in got:
            moved.append(f"{label} (tree added or removed)")
            continue
        for part in sorted(want[label].keys() | got[label].keys()):
            if want[label].get(part) != got[label].get(part):
                moved.append(f"{label}: {part}")
    return moved


def _golden_check() -> int:
    stored = load_golden()
    moved = _moved_parts(stored["trees"], compute_golden())
    if moved:
        print(
            f"surface golden moved under CPython {sys.version.split()[0]}: {moved}. "
            "Only a [WAVE] slice may re-pin it (golden --repin <ID>).",
            file=sys.stderr,
        )
        return 1
    return 0


def _golden_init() -> int:
    if GOLDEN.exists():
        raise CaptureError(f"refusing --init: {GOLDEN} exists (re-pin with --repin)")
    _require_capture_python()
    GOLDEN.write_text(render_golden([], compute_golden()), encoding="utf-8")
    return 0


def _golden_repin(slice_id: str) -> int:
    wave: list[str] = list(SETTINGS["wave_slices"])
    if slice_id not in wave:
        raise CaptureError(
            f"refusing to re-pin for {slice_id!r}: only [WAVE] slices {wave} may"
        )
    # load_golden guarantees repins is strictly increasing in plan order, so an
    # id that re-pinned before (and is not the last) always sorts before `last`.
    repins = list(load_golden()["repins"])
    last = repins[-1] if repins else None
    if slice_id != last:
        if last is not None and wave.index(slice_id) < wave.index(last):
            raise CaptureError(
                f"refusing: {slice_id} precedes the last re-pinner {last} in plan "
                "order, or re-pinned already"
            )
        repins.append(slice_id)
    _require_capture_python()
    GOLDEN.write_text(render_golden(repins, compute_golden()), encoding="utf-8")
    return 0


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="capture.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    trees = sub.add_parser("trees", help="capture the frozen legacy trees")
    mode = trees.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write-once capture")
    mode.add_argument("--check", action="store_true", help="recapture and compare")
    sub.add_parser("manifest", help="verify SHA256SUMS against the frozen trees")
    golden = sub.add_parser("golden", help="the surface golden")
    gmode = golden.add_mutually_exclusive_group(required=True)
    gmode.add_argument("--init", action="store_true", help="first pin (once)")
    gmode.add_argument("--check", action="store_true", help="compare, exit 1 on move")
    gmode.add_argument("--repin", metavar="WAVE_ID", help="re-pin for a [WAVE] slice")
    stamp_cmd = sub.add_parser("_stamp", help="internal: heal one tree in-process")
    stamp_cmd.add_argument("tree", type=Path)
    stamp_cmd.add_argument("--engine", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    action: Callable[[], int]
    if args.command == "trees":
        action = _trees_write if args.write else _trees_check
    elif args.command == "manifest":
        action = _manifest_check
    elif args.command == "golden":
        if args.init:
            action = _golden_init
        elif args.check:
            action = _golden_check
        else:
            action = lambda: _golden_repin(args.repin)  # noqa: E731
    else:

        def action() -> int:
            stamp(args.tree, args.engine)
            return 0

    try:
        return action()
    except CaptureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
