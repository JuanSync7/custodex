"""The SharePoint mirror connector (EPIC SP, SP-01).

Mirrors a SharePoint document library into the repo tree as DETERMINISTIC
TEXT so the unchanged engine can govern the files like any other managed doc
(fingerprints, doc↔doc edges, staleness, ownership). The engine never
converts and never fetches — this module lives at the edge, the
``gitfetch.py``/``pr.py`` precedent for provider-specific code (K0). Stdlib
only: ``urllib`` (in-process HTTP), ``zipfile`` + ``xml.etree``, ``json``.

Three seams:

- :class:`Source` — where library bytes come from. :class:`DirSource` reads a
  library already mirrored to disk (the ``pull_sharepoint.py`` output, and
  every offline test fixture — K4); :class:`ProxySource` talks to the
  ``rag-sharepoint-api`` service (``POST /documents/list`` +
  ``POST /documents/fetch`` with ``include_content=true``).
- :class:`Converter` — raw library bytes → stable text. Built-ins:
  ``passthrough`` (UTF-8, loud on undecodable — K8) and ``docx-text``
  (WordprocessingML → markdown-shaped text; CONTAINER-CHURN-INVARIANT: the
  output depends only on ``word/document.xml``, never zip timestamps or
  member order, so a Word re-save with unchanged words never moves a hash).
  A lossless external converter (doc2md) plugs in as a registry entry later —
  conversion fidelity is the converter's concern; HASHING STAYS IN THE ENGINE
  (a baseline is a property of governance, not of the document).
- :func:`sync_mirror` — the writer verb behind ``cdx sp-sync``. Skips
  unchanged files via ``.cdmon/sp-manifest.json`` (size + last_modified from
  the SOURCE LISTING, never the clock — K10), writes a mirror file only when
  its body actually changed (K7), and PRESERVES any existing ``cdm:`` front
  matter so the engine baseline survives every re-sync. A file gone from the
  listing is pruned from the manifest but its mirror file is KEPT and
  reported — deleting a governed doc is a human decision (K5).
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from collections.abc import Mapping
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol
from xml.etree import ElementTree

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .errors import CodeDocMonitorError
from .inventory import _matches_any, _translate
from .manifest import parse_text, render_doc

__all__ = [
    "SpMirrorError",
    "SpDocument",
    "Source",
    "DirSource",
    "ProxySource",
    "SpMirrorConfig",
    "SpSyncReport",
    "convert_bytes",
    "load_spmirror_config",
    "sync_mirror",
    "DEFAULT_SPMIRROR_PATH",
]

DEFAULT_SPMIRROR_PATH = Path("config") / "spmirror.yaml"
_MANIFEST_REL = Path(".cdmon") / "sp-manifest.json"
_MANIFEST_SCHEMA_VERSION = "1.0.0"

# The one HTTP leaf, module-level so tests monkeypatch it (K4: no socket in
# any test) — the gitfetch/gitauth injected-leaf precedent.
_urlopen = urllib.request.urlopen


class SpMirrorError(CodeDocMonitorError):
    """Malformed spmirror config/input or an unreachable source (K8: loud)."""


class SpDocument(BaseModel):
    """One library file as listed by a source.

    ``last_modified`` is copied verbatim from the SOURCE LISTING (Graph /
    stat), never read from the clock (K10) — it is a skip-key, not
    provenance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str  # library-relative, POSIX separators
    size_bytes: int
    last_modified: str


class Source(Protocol):
    """The one fetch seam (the ``gitfetch._Cloner`` precedent)."""

    def list_documents(self) -> tuple[SpDocument, ...]:
        """List every file the library currently holds (sorted by path)."""
        ...

    def fetch(self, path: str) -> bytes:
        """Return one listed file's raw bytes."""
        ...


class DirSource:
    """A library already mirrored to local disk.

    The deployed shape: ``pull_sharepoint.py`` (rag-sharepoint-api) lands raw
    library bytes under a directory; this source governs that directory. It
    is also what every offline test uses (K4).
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def list_documents(self) -> tuple[SpDocument, ...]:
        if not self._root.is_dir():
            raise SpMirrorError(f"spmirror source_dir does not exist: {self._root}")
        out: list[SpDocument] = []
        for path in sorted(self._root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            stat = path.stat()
            stamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            out.append(
                SpDocument(
                    path=path.relative_to(self._root).as_posix(),
                    size_bytes=stat.st_size,
                    last_modified=stamp,
                )
            )
        return tuple(out)

    def fetch(self, path: str) -> bytes:
        return (self._root / PurePosixPath(path)).read_bytes()


class ProxySource:
    """The ``rag-sharepoint-api`` service over stdlib urllib.

    In-process HTTP on purpose (the EDR environment kills shell ``curl``);
    auth lives entirely in the service (cert-based Graph app) — no credential
    ever passes through here.
    """

    def __init__(
        self,
        api_url: str,
        site_url: str,
        folder: str | None = None,
        *,
        timeout: int = 120,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._site_url = site_url
        self._folder = folder
        self._timeout = timeout

    def _post(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self._api_url + route,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with _urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise SpMirrorError(
                f"spmirror proxy unreachable at {self._api_url}{route}: {exc}"
            ) from exc
        except (ValueError, OSError) as exc:
            raise SpMirrorError(
                f"spmirror proxy returned malformed JSON from {route}: {exc}"
            ) from exc

    def list_documents(self) -> tuple[SpDocument, ...]:
        data = self._post(
            "/documents/list",
            {"site_url": self._site_url, "folder_path": self._folder},
        )
        try:
            docs = tuple(
                SpDocument(
                    path=f["path"],
                    size_bytes=f["size_bytes"],
                    last_modified=f["last_modified"],
                )
                for f in data["files"]
            )
        except (KeyError, TypeError, ValidationError) as exc:
            raise SpMirrorError(
                f"spmirror proxy /documents/list shape unexpected: {exc}"
            ) from exc
        return tuple(sorted(docs, key=lambda d: d.path))

    def fetch(self, path: str) -> bytes:
        data = self._post(
            "/documents/fetch",
            {
                "site_url": self._site_url,
                "document_path": path,
                "include_content": True,
            },
        )
        encoded = data.get("content_base64")
        if not isinstance(encoded, str):
            raise SpMirrorError(
                f"spmirror proxy returned no content_base64 for {path!r} "
                "(is include_content supported by the service?)"
            )
        try:
            return base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise SpMirrorError(
                f"spmirror proxy content for {path!r} is not valid base64: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


class Converter(Protocol):
    """Raw library bytes → deterministic text (same bytes → same text)."""

    def convert(self, raw: bytes, *, source_name: str) -> str: ...


class _Passthrough:
    def convert(self, raw: bytes, *, source_name: str) -> str:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SpMirrorError(
                f"passthrough converter: {source_name!r} is not UTF-8 text "
                f"({exc}); map its suffix to a converting entry or exclude it"
            ) from exc


_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING_RE = re.compile(r"[Hh]eading(\d+)$")


class _DocxText:
    """WordprocessingML → markdown-shaped text, container-churn-invariant.

    Reads ONLY ``word/document.xml`` — zip timestamps, member order, and
    every other part (docProps, styles, …) are invisible, so a Word re-save
    with unchanged words converts byte-identically (the property the
    fingerprint needs). Fidelity is deliberately minimal (paragraphs,
    Heading``N`` styles, list items); a lossless converter (doc2md) can take
    this registry slot without any engine change.
    """

    def convert(self, raw: bytes, *, source_name: str) -> str:
        try:
            with zipfile.ZipFile(BytesIO(raw)) as zf:
                payload = zf.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise SpMirrorError(
                f"docx-text converter: {source_name!r} is not a docx "
                f"(no readable word/document.xml: {exc})"
            ) from exc
        # XXE / billion-laughs guard (K8): Word never writes a DTD into
        # WordprocessingML — refuse the shape before any XML parser runs.
        # The WHOLE payload is scanned (a head-only window is paddable past);
        # the strings cannot appear in well-formed element text un-escaped.
        if b"<!DOCTYPE" in payload or b"<!ENTITY" in payload:
            raise SpMirrorError(
                f"docx-text converter: {source_name!r} carries a DTD/DOCTYPE "
                "in word/document.xml — refusing to parse it"
            )
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise SpMirrorError(
                f"docx-text converter: {source_name!r} has malformed "
                f"word/document.xml: {exc}"
            ) from exc

        blocks: list[str] = []
        for para in root.iter(f"{_W_NS}p"):
            text = self._paragraph_text(para)
            if not text.strip():
                continue
            prefix = self._prefix(para)
            blocks.append(f"{prefix}{text}")
        return "\n\n".join(blocks) + "\n" if blocks else ""

    @staticmethod
    def _paragraph_text(para: ElementTree.Element) -> str:
        parts: list[str] = []
        for node in para.iter():
            if node.tag == f"{_W_NS}t":
                parts.append(node.text or "")
            elif node.tag == f"{_W_NS}br":
                parts.append("\n")
        return "".join(parts)

    @staticmethod
    def _prefix(para: ElementTree.Element) -> str:
        ppr = para.find(f"{_W_NS}pPr")
        if ppr is None:
            return ""
        if ppr.find(f"{_W_NS}numPr") is not None:
            return "- "
        style = ppr.find(f"{_W_NS}pStyle")
        if style is not None:
            match = _HEADING_RE.match(style.get(f"{_W_NS}val", ""))
            if match:
                level = min(max(int(match.group(1)), 1), 6)
                return "#" * level + " "
        return ""


_CONVERTERS: dict[str, Converter] = {
    "passthrough": _Passthrough(),
    "docx-text": _DocxText(),
}


def convert_bytes(converter_id: str, raw: bytes, *, source_name: str) -> str:
    """Run one registered converter; an unknown id is loud (K8)."""
    converter = _CONVERTERS.get(converter_id)
    if converter is None:
        known = ", ".join(sorted(_CONVERTERS))
        raise SpMirrorError(f"unknown converter {converter_id!r} (known: {known})")
    return converter.convert(raw, source_name=source_name)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class SpMirrorConfig(BaseModel):
    """The ``config/spmirror.yaml`` payload (``settings.py`` file precedent).

    This file configures the CONNECTOR only; which mirrored docs are
    GOVERNED (owner, audience, ``depends_on``) stays declared in
    ``config/cdmon`` like every other managed doc.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Literal["proxy", "dir"] = "proxy"
    api_url: str = "http://localhost:8100"
    site_url: str = ""
    folder: str | None = None
    source_dir: str | None = None
    dest: str = "docs/sharepoint"
    include: tuple[str, ...] = ("**",)
    exclude: tuple[str, ...] = ()
    max_bytes: int | None = None
    timeout_seconds: int = 120
    converters: dict[str, str] = {".md": "passthrough", ".txt": "passthrough"}

    @model_validator(mode="after")
    def _wellformed(self) -> SpMirrorConfig:
        if self.source == "dir" and not self.source_dir:
            raise ValueError('source: "dir" requires source_dir')
        if self.source == "proxy" and not self.site_url:
            raise ValueError('source: "proxy" requires site_url')
        for suffix, name in self.converters.items():
            if name not in _CONVERTERS:
                known = ", ".join(sorted(_CONVERTERS))
                raise ValueError(
                    f"converters[{suffix!r}] names unknown converter "
                    f"{name!r} (known: {known})"
                )
        return self


def load_spmirror_config(
    path: Path, *, env: Mapping[str, str] | None = None
) -> SpMirrorConfig:
    """Load + validate ``config/spmirror.yaml``; loud on any malformation.

    ``CDMON_SP_API`` (the ``CDMON_*`` convention) overrides ``api_url`` so a
    deployment can point at the service without editing tracked config.
    """
    source = os.environ if env is None else env
    if not Path(path).is_file():
        raise SpMirrorError(f"spmirror config not found: {path}")
    try:
        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpMirrorError(f"malformed YAML in {path}: {exc}") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("spmirror"), dict):
        raise SpMirrorError(
            f"{path} must be a mapping with a top-level 'spmirror:' key"
        )
    payload = dict(loaded["spmirror"])
    api_override = source.get("CDMON_SP_API")
    if api_override:
        payload["api_url"] = api_override
    try:
        return SpMirrorConfig.model_validate(payload)
    except ValidationError as exc:
        raise SpMirrorError(f"invalid spmirror config in {path}: {exc}") from exc


def source_from_config(cfg: SpMirrorConfig) -> Source:
    """Build the configured Source (the CLI's one construction point)."""
    if cfg.source == "dir":
        assert cfg.source_dir is not None  # _wellformed guarantees it
        return DirSource(Path(cfg.source_dir))
    return ProxySource(
        cfg.api_url, cfg.site_url, cfg.folder, timeout=cfg.timeout_seconds
    )


# ---------------------------------------------------------------------------
# The sync core
# ---------------------------------------------------------------------------


class SpSyncReport(BaseModel):
    """What one ``sync_mirror`` pass did (sorted tuples — K10)."""

    model_config = ConfigDict(frozen=True)

    pulled: int = 0
    unchanged: int = 0
    skipped_filtered: int = 0
    skipped_unmapped: tuple[str, ...] = ()
    written: tuple[str, ...] = ()
    stale_candidates: tuple[str, ...] = ()
    dry_run: bool = False


def _mirror_rel(cfg: SpMirrorConfig, doc_path: str, converter_id: str) -> str:
    """The repo-relative mirror path for one library file.

    A TRANSFORMING converter appends ``.md`` (``specs/Design.docx`` →
    ``specs/Design.docx.md``): collision-free against a sibling
    ``Design.md`` and the provenance is visible in the filename.
    ``passthrough`` keeps the name.
    """
    rel = doc_path if converter_id == "passthrough" else doc_path + ".md"
    return (PurePosixPath(cfg.dest) / rel).as_posix()


def _load_sp_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": _MANIFEST_SCHEMA_VERSION, "files": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SpMirrorError(f"malformed sp-manifest at {path}: {exc}") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("files"), dict):
        raise SpMirrorError(f"malformed sp-manifest at {path}: expected files map")
    return loaded


def _write_body_preserving_meta(target: Path, body: str) -> bool:
    """Write ``body`` keeping any existing ``cdm:`` front matter intact.

    Returns True when the file's bytes actually changed (K7's unit of
    account). The engine's baseline lives in that front matter — a re-sync
    must never strip it, or every pass would re-trigger a HASH drift.
    """
    if target.is_file():
        existing = parse_text(target.read_text(encoding="utf-8"), target)
        if existing.body == body:
            return False
        new_text = render_doc(existing.meta, body)
    else:
        new_text = body
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_text, encoding="utf-8")
    return True


def sync_mirror(
    cfg: SpMirrorConfig,
    repo_root: Path,
    source: Source,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> SpSyncReport:
    """Mirror the library into ``repo_root`` (the ``cdx sp-sync`` core).

    Per listed file: include/exclude/max_bytes filter → manifest skip
    (``size_bytes`` + ``last_modified`` both equal → no fetch) → fetch →
    convert → write only on body change, preserving ``cdm:`` front matter.
    ``dry_run`` fetches nothing and writes nothing; ``force`` ignores the
    manifest skip but still writes only changed bytes (K7).
    """
    repo_root = Path(repo_root)
    include = tuple(_translate(p) for p in cfg.include)
    exclude = tuple(_translate(p) for p in cfg.exclude)
    manifest_path = repo_root / _MANIFEST_REL
    manifest = _load_sp_manifest(manifest_path)
    entries: dict[str, Any] = dict(manifest["files"])

    pulled = unchanged = skipped_filtered = 0
    skipped_unmapped: list[str] = []
    written: list[str] = []
    live_paths: set[str] = set()

    for doc in source.list_documents():
        if not _matches_any(doc.path, include) or _matches_any(doc.path, exclude):
            skipped_filtered += 1
            continue
        if cfg.max_bytes is not None and doc.size_bytes > cfg.max_bytes:
            skipped_filtered += 1
            continue
        suffix = PurePosixPath(doc.path).suffix.lower()
        converter_id = cfg.converters.get(suffix)
        if converter_id is None:
            skipped_unmapped.append(doc.path)
            continue
        live_paths.add(doc.path)
        mirror_rel = _mirror_rel(cfg, doc.path, converter_id)

        prior = entries.get(doc.path)
        if (
            not force
            and isinstance(prior, dict)
            and prior.get("size_bytes") == doc.size_bytes
            and prior.get("last_modified") == doc.last_modified
        ):
            unchanged += 1
            continue

        pulled += 1
        if dry_run:
            continue
        body = convert_bytes(converter_id, source.fetch(doc.path), source_name=doc.path)
        if _write_body_preserving_meta(repo_root / mirror_rel, body):
            written.append(mirror_rel)
        entries[doc.path] = {
            "size_bytes": doc.size_bytes,
            "last_modified": doc.last_modified,
            "mirror": mirror_rel,
        }

    stale: list[str] = []
    for gone in sorted(set(entries) - live_paths):
        prior = entries.pop(gone)
        gone_mirror = prior.get("mirror") if isinstance(prior, dict) else None
        if isinstance(gone_mirror, str) and (repo_root / gone_mirror).is_file():
            stale.append(gone_mirror)

    if not dry_run:
        manifest["files"] = {k: entries[k] for k in sorted(entries)}
        new_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if not (
            manifest_path.is_file()
            and manifest_path.read_text(encoding="utf-8") == new_text
        ):
            manifest_path.write_text(new_text, encoding="utf-8")

    return SpSyncReport(
        pulled=pulled,
        unchanged=unchanged,
        skipped_filtered=skipped_filtered,
        skipped_unmapped=tuple(sorted(skipped_unmapped)),
        written=tuple(sorted(written)),
        stale_candidates=tuple(sorted(stale)),
        dry_run=dry_run,
    )
