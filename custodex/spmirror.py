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
  unchanged files via ``.cdmon/sp-manifest.json`` (an EXACT ``content_hash``
  when the source supplies one, else the listing's ``size_bytes`` +
  ``last_modified``, never the clock — K10), writes a mirror file only when
  its body actually changed (K7), and PRESERVES any existing ``cdm:`` front
  matter so the engine baseline survives every re-sync. A file gone from the
  full listing (not merely filtered out) is pruned from the manifest but its
  mirror file is KEPT and reported — deleting a governed doc is a human
  decision (K5).
"""

from __future__ import annotations

import base64
import hashlib
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
from xml.parsers import expat

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
    "docx_lossy_parts",
    "load_spmirror_config",
    "sync_mirror",
    "source_from_config",
    "DEFAULT_SPMIRROR_PATH",
]

DEFAULT_SPMIRROR_PATH = Path("config") / "spmirror.yaml"
_MANIFEST_REL = Path(".cdmon") / "sp-manifest.json"
_MANIFEST_SCHEMA_VERSION = "1.0.0"

#: Cap on a single proxy HTTP response / base64 blob we buffer into RAM — a
#: hostile or buggy service must not stream the connector into OOM (128 MiB,
#: far above any real document).
_MAX_RESPONSE_BYTES = 128 * 1024 * 1024

# The one HTTP leaf, module-level so tests monkeypatch it (K4: no socket in
# any test) — the gitfetch/gitauth injected-leaf precedent.
_urlopen = urllib.request.urlopen


class SpMirrorError(CodeDocMonitorError):
    """Malformed spmirror config/input or an unreachable source (K8: loud)."""


class SpDocument(BaseModel):
    """One library file as listed by a source.

    ``last_modified`` is copied verbatim from the SOURCE LISTING (Graph /
    stat), never read from the clock (K10) — it is a skip-key, not
    provenance. ``content_hash`` is an OPTIONAL exact skip-key a source may
    supply when it can hash cheaply (``DirSource`` does — the bytes are
    local); when present it supersedes ``last_modified`` in the skip
    decision, so a same-size edit within one clock second is never missed
    and an mtime-only bump never forces a needless re-fetch. A source that
    cannot hash without fetching (``ProxySource``) leaves it ``None`` and
    the listing's ``last_modified`` remains the skip signal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str  # library-relative, POSIX separators
    size_bytes: int
    last_modified: str
    content_hash: str | None = None


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
        root_resolved = self._root.resolve()
        out: list[SpDocument] = []
        for path in sorted(self._root.rglob("*")):
            # Skip a symlink (file OR the entries under a symlinked dir): it
            # can point OUT of the library tree, and mirroring out-of-tree
            # content into the governed dest is an escape (K8). Belt-and-
            # braces: also require the resolved path stays inside the root.
            if path.is_symlink():
                continue
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(root_resolved)
            except (OSError, ValueError):
                continue
            stat = path.stat()
            stamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            # A local file can be hashed cheaply — supply the EXACT skip-key
            # (kills both the same-second same-size miss and the mtime-bump
            # false re-fetch; also makes the manifest machine-independent).
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            out.append(
                SpDocument(
                    path=path.relative_to(self._root).as_posix(),
                    size_bytes=stat.st_size,
                    last_modified=stamp,
                    content_hash=digest,
                )
            )
        return tuple(out)

    def fetch(self, path: str) -> bytes:
        try:
            return (self._root / PurePosixPath(path)).read_bytes()
        except OSError as exc:
            raise SpMirrorError(
                f"spmirror source_dir file unreadable: {path}: {exc}"
            ) from exc


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
                # Bound the body: a malicious/buggy proxy must not stream us
                # into OOM. Read one byte past the cap to detect overflow.
                body = resp.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise SpMirrorError(
                    f"spmirror proxy response from {route} exceeds "
                    f"{_MAX_RESPONSE_BYTES} bytes — refusing to buffer it"
                )
            return json.loads(body.decode("utf-8"))
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
        # No separate size guard is needed here: ``_post`` already caps the
        # whole HTTP body at ``_MAX_RESPONSE_BYTES``, and the base64 string is
        # a field inside that body — so it is bounded, and the decode (which
        # SHRINKS to ~3/4) cannot exceed the cap either.
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

#: Cap on the DECOMPRESSED size of a single docx part we will read into RAM.
#: A ~200 KB zip can expand to hundreds of MB (a decompression bomb); the
#: listing-side ``max_bytes`` gate only sees the compressed size, so the cap
#: lives here at the read (default 64 MiB — larger than any real document.xml).
_MAX_PART_BYTES = 64 * 1024 * 1024

#: Auxiliary WordprocessingML parts that carry human text ``docx-text`` does
#: NOT mirror. A text-bearing one is REPORTED (never silently dropped) so an
#: edit landing there is visible as a lossy-part warning, not an invisible
#: governance blind spot — full fidelity is the doc2md converter's job.
_AUX_TEXT_PART_RE = re.compile(
    r"^word/(header\d+|footer\d+|footnotes|endnotes|comments)\.xml$"
)


def _reject_dtd(payload: bytes, source_name: str) -> None:
    """Refuse any DTD/DOCTYPE at the PARSER (K8; XXE / billion-laughs).

    A raw-byte substring scan is evadable by a UTF-16-encoded
    ``document.xml`` (the ASCII bytes never appear). expat's
    ``StartDoctypeDeclHandler`` fires at the start of the DOCTYPE in ANY
    encoding expat auto-detects, BEFORE the internal subset's entities are
    declared or expanded — so raising there stops billion-laughs before it
    can begin. Word never writes a DTD into WordprocessingML.
    """

    def _on_doctype(
        name: str, sysid: object, pubid: object, has_internal: bool
    ) -> None:
        raise SpMirrorError(
            f"docx-text converter: {source_name!r} carries a DTD/DOCTYPE "
            "in word/document.xml — refusing to parse it"
        )

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = _on_doctype
    try:
        parser.Parse(payload, True)
    except expat.ExpatError:
        # A malformed body is not our concern here — ElementTree.fromstring
        # will raise the real, message-carrying parse error next.
        return


class _DocxText:
    """WordprocessingML → markdown-shaped text, container-churn-invariant.

    Reads ONLY ``word/document.xml`` — zip timestamps, member order, and
    every other part (docProps, styles, …) are invisible, so a Word re-save
    with unchanged words converts byte-identically (the property the
    fingerprint needs).

    Fidelity is deliberately minimal (body paragraphs, Heading``N`` styles,
    list items, tabs/line-breaks); a lossless converter (doc2md) plugs into
    the same registry when full fidelity is needed. Two documented
    limitations follow from the minimalism: (1) text in headers, footers,
    footnotes, endnotes, and comments is NOT mirrored — :func:`docx_lossy_parts`
    reports its presence so the gap is visible, never silent; (2) a
    style-derived prefix (``# ``/``- ``) shares the output byte-space with
    literal body text, so a HeadingN over a paragraph whose text already
    begins with ``# `` is a fingerprint no-op. Both are acceptable for a
    readable mirror; neither is silent.
    """

    def convert(self, raw: bytes, *, source_name: str) -> str:
        try:
            with zipfile.ZipFile(BytesIO(raw)) as zf:
                info = zf.getinfo("word/document.xml")
                if info.file_size > _MAX_PART_BYTES:
                    raise SpMirrorError(
                        f"docx-text converter: {source_name!r} "
                        f"word/document.xml decompresses to {info.file_size} "
                        f"bytes (> {_MAX_PART_BYTES} cap) — refusing (bomb guard)"
                    )
                payload = zf.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError, OSError) as exc:
            raise SpMirrorError(
                f"docx-text converter: {source_name!r} is not a docx "
                f"(no readable word/document.xml: {exc})"
            ) from exc
        _reject_dtd(payload, source_name)
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise SpMirrorError(
                f"docx-text converter: {source_name!r} has malformed "
                f"word/document.xml: {exc}"
            ) from exc

        # Only BODY-LEVEL paragraphs: a paragraph nested inside another (a
        # text box's ``w:txbxContent``) is folded into its outer paragraph's
        # text by ``_paragraph_text`` and must not ALSO be emitted on its own
        # (that double-counted the box text).
        parents = {child: parent for parent in root.iter() for child in parent}
        blocks: list[str] = []
        for para in root.iter(f"{_W_NS}p"):
            if self._has_paragraph_ancestor(para, parents):
                continue
            text = self._paragraph_text(para)
            if not text.strip():
                continue
            prefix = self._prefix(para)
            blocks.append(f"{prefix}{text}")
        return "\n\n".join(blocks) + "\n" if blocks else ""

    @staticmethod
    def _has_paragraph_ancestor(
        para: ElementTree.Element,
        parents: dict[ElementTree.Element, ElementTree.Element],
    ) -> bool:
        node = parents.get(para)
        while node is not None:
            if node.tag == f"{_W_NS}p":
                return True
            node = parents.get(node)
        return False

    @staticmethod
    def _paragraph_text(para: ElementTree.Element) -> str:
        parts: list[str] = []
        for node in para.iter():
            if node.tag == f"{_W_NS}t":
                parts.append(node.text or "")
            elif node.tag == f"{_W_NS}br" or node.tag == f"{_W_NS}cr":
                parts.append("\n")
            elif node.tag == f"{_W_NS}tab":
                parts.append("\t")
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


def docx_lossy_parts(raw: bytes) -> tuple[str, ...]:
    """Sorted auxiliary docx parts carrying text ``docx-text`` cannot mirror.

    Empty for a body-only document. A non-empty result is surfaced in the
    sync report (and by the CLI) so an operator knows a doc's headers /
    footers / footnotes / endnotes / comments hold text the mirror — and
    therefore the fingerprint — does not see; the fix is to route that doc
    through a fuller converter (doc2md).
    """
    try:
        with zipfile.ZipFile(BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if _AUX_TEXT_PART_RE.match(n)]
            found: list[str] = []
            for name in names:
                info = zf.getinfo(name)
                if info.file_size > _MAX_PART_BYTES:
                    found.append(name)  # oversized but present — still report
                    continue
                if b"<w:t" in zf.read(name):
                    found.append(name)
    except (zipfile.BadZipFile, KeyError, OSError):
        return ()
    return tuple(sorted(found))


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
    lossy_parts: tuple[str, ...] = ()
    dry_run: bool = False


def _mirror_rel(cfg: SpMirrorConfig, doc_path: str, converter_id: str) -> str:
    """The repo-relative mirror path for one library file.

    A TRANSFORMING converter appends ``.md`` (``specs/Design.docx`` →
    ``specs/Design.docx.md``): collision-free against a sibling
    ``Design.md`` and the provenance is visible in the filename.
    ``passthrough`` keeps the name.

    A listed path that is absolute or climbs (``..``) would let a
    compromised source write OUTSIDE ``dest`` — refused loudly (K8; the
    listing is remote input, not trusted config).
    """
    pure = PurePosixPath(doc_path)
    if pure.is_absolute() or ".." in pure.parts or "\\" in doc_path:
        raise SpMirrorError(
            f"spmirror source listed an unsafe path {doc_path!r} "
            "(absolute, parent-escaping, or backslashed) — refusing to mirror it"
        )
    rel = doc_path if converter_id == "passthrough" else doc_path + ".md"
    return (PurePosixPath(cfg.dest) / rel).as_posix()


def _load_sp_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": _MANIFEST_SCHEMA_VERSION, "files": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise SpMirrorError(f"malformed sp-manifest at {path}: {exc}") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("files"), dict):
        raise SpMirrorError(f"malformed sp-manifest at {path}: expected files map")
    return loaded


def _skip_unchanged(prior: object, doc: SpDocument) -> bool:
    """True when the manifest entry proves ``doc`` is byte-unchanged.

    Prefers the EXACT ``content_hash`` when both sides carry one (DirSource):
    a same-size edit within one clock second is caught and an mtime-only bump
    is ignored. Falls back to the listing's ``last_modified`` for a source
    that cannot hash cheaply (ProxySource, where Graph versions on any edit).
    """
    if not isinstance(prior, dict) or prior.get("size_bytes") != doc.size_bytes:
        return False
    if doc.content_hash is not None and prior.get("content_hash") is not None:
        return bool(prior.get("content_hash") == doc.content_hash)
    return bool(prior.get("last_modified") == doc.last_modified)


def _write_body_preserving_meta(target: Path, body: str) -> bool:
    """Write ``body`` keeping any existing ``cdm:`` front matter intact.

    Returns True when the file's bytes actually changed (K7's unit of
    account). The engine's baseline lives in that front matter — a re-sync
    must never strip it, or every pass would re-trigger a HASH drift.

    Refuses to write THROUGH a symlink at the target: an attacker who plants
    one inside ``dest`` could otherwise redirect the write onto an
    out-of-tree file (K8).
    """
    if target.is_symlink():
        raise SpMirrorError(
            f"mirror target is a symlink, refusing to write through it: {target}"
        )
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
    (exact ``content_hash`` when the source supplies one, else ``size_bytes``
    + ``last_modified``; equal → no fetch) → fetch → convert → write only on
    body change, preserving ``cdm:`` front matter. A file gone from the FULL
    listing (not merely filtered out) is pruned from the manifest and its
    mirror reported as a stale candidate. ``dry_run`` fetches nothing and
    writes nothing; ``force`` ignores the manifest skip but still writes only
    changed bytes (K7).
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
    lossy: list[str] = []
    listed_paths: set[str] = set()
    claimed: dict[str, str] = {}  # mirror_rel -> source path (collision guard)

    for doc in source.list_documents():
        # Track EVERY listed path (pre-filter) so prune means "gone upstream",
        # never "transiently filtered by a config knob".
        listed_paths.add(doc.path)

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
        mirror_rel = _mirror_rel(cfg, doc.path, converter_id)
        if mirror_rel in claimed:
            raise SpMirrorError(
                f"two source files map to the same mirror path {mirror_rel!r}: "
                f"{claimed[mirror_rel]!r} and {doc.path!r} — rename one or "
                "narrow the include globs"
            )
        claimed[mirror_rel] = doc.path

        if not force and _skip_unchanged(entries.get(doc.path), doc):
            unchanged += 1
            continue

        pulled += 1
        if dry_run:
            continue
        raw = source.fetch(doc.path)
        if converter_id == "docx-text":
            lossy.extend(f"{doc.path} ({part})" for part in docx_lossy_parts(raw))
        body = convert_bytes(converter_id, raw, source_name=doc.path)
        if _write_body_preserving_meta(repo_root / mirror_rel, body):
            written.append(mirror_rel)
        entries[doc.path] = {
            "size_bytes": doc.size_bytes,
            "last_modified": doc.last_modified,
            "content_hash": doc.content_hash,
            "mirror": mirror_rel,
        }

    stale: list[str] = []
    for gone in sorted(set(entries) - listed_paths):
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
        lossy_parts=tuple(sorted(lossy)),
        dry_run=dry_run,
    )
