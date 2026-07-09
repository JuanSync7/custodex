"""SP-01 — the SharePoint mirror connector: converters, manifest, sync core.

Pure-offline (K4): every Source here is a fake or a local directory; the
ProxySource HTTP leaf is exercised through a monkeypatched module seam, never
a socket. Pinned contract: ARCHITECTURE.md §EPIC SP.

Features: FEAT-SPMIRROR-001, FEAT-SPMIRROR-002

Feature: FEAT-SPMIRROR-001
Feature: FEAT-SPMIRROR-002
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest
import yaml

from custodex.errors import CodeDocMonitorError
from custodex.manifest import parse_text
from custodex.spmirror import (
    DirSource,
    ProxySource,
    SpDocument,
    SpMirrorError,
    convert_bytes,
    load_spmirror_config,
    sync_mirror,
)
from tests._docx import build_docx, document_xml

_DOC_PARAGRAPHS: list[tuple[str | None, str]] = [
    ("Heading1", "Design Spec"),
    (None, "The API accepts widgets."),
    ("list", "item one"),
    ("Heading2", "Details"),
    (None, "Second paragraph."),
]

_GOLDEN_MD = (
    "# Design Spec\n"
    "\n"
    "The API accepts widgets.\n"
    "\n"
    "- item one\n"
    "\n"
    "## Details\n"
    "\n"
    "Second paragraph.\n"
)


def _docx_bytes(**kwargs: object) -> bytes:
    buf_path = kwargs.pop("_path", None)
    assert buf_path is None
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.docx"
        build_docx(p, _DOC_PARAGRAPHS, **kwargs)  # type: ignore[arg-type]
        return p.read_bytes()


class FakeSource:
    """An in-memory Source: {path: (bytes, last_modified)} + a fetch counter."""

    def __init__(self, files: dict[str, tuple[bytes, str]]) -> None:
        self.files = dict(files)
        self.fetch_calls: list[str] = []

    def list_documents(self) -> tuple[SpDocument, ...]:
        return tuple(
            SpDocument(path=p, size_bytes=len(raw), last_modified=ts)
            for p, (raw, ts) in sorted(self.files.items())
        )

    def fetch(self, path: str) -> bytes:
        self.fetch_calls.append(path)
        return self.files[path][0]


def _config(tmp_path: Path, **overrides: object) -> Path:
    """Write a config/spmirror.yaml under ``tmp_path`` and return its path."""
    payload: dict[str, object] = {
        "source": "dir",
        "source_dir": str(tmp_path / "library"),
        "dest": "docs/sharepoint",
        "include": ["**/*.docx", "**/*.md"],
        "converters": {".docx": "docx-text", ".md": "passthrough"},
    }
    payload.update(overrides)
    cfg_path = tmp_path / "repo" / "config" / "spmirror.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump({"spmirror": payload}), encoding="utf-8")
    (tmp_path / "repo").mkdir(exist_ok=True)
    return cfg_path


class TestConverters:
    def test_docx_text_golden(self) -> None:
        assert convert_bytes("docx-text", _docx_bytes(), source_name="x.docx") == (
            _GOLDEN_MD
        )

    def test_docx_container_churn_is_invisible(self) -> None:
        """Same words, different zip container → byte-identical text.

        A Word re-save rewrites zip timestamps, member order, and metadata
        parts without touching document.xml — none of that may move a hash.
        """
        a = _docx_bytes(zip_date=(2026, 1, 1, 0, 0, 0))
        b = _docx_bytes(
            zip_date=(2026, 6, 30, 12, 34, 56),
            extra_member="<coreProperties>resaved</coreProperties>",
            reverse_order=True,
        )
        assert a != b  # the containers genuinely differ...
        out_a = convert_bytes("docx-text", a, source_name="x.docx")
        out_b = convert_bytes("docx-text", b, source_name="x.docx")
        assert out_a == out_b == _GOLDEN_MD  # ...the text does not

    def test_docx_heading_levels_clamp(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "h.docx"
            build_docx(p, [("Heading9", "Deep"), ("Heading3", "Mid")])
            out = convert_bytes("docx-text", p.read_bytes(), source_name="h.docx")
        assert "###### Deep" in out
        assert "### Mid" in out

    def test_docx_malformed_zip_is_loud(self) -> None:
        with pytest.raises(SpMirrorError):
            convert_bytes("docx-text", b"this is not a zip", source_name="x.docx")

    def test_docx_dtd_is_rejected_before_parse(self) -> None:
        """XXE/billion-laughs guard: a DTD in document.xml is loud (K8).

        Word never writes a DOCTYPE into WordprocessingML — its presence in
        library-fetched bytes is an attack shape, not a document. The guard
        must fire BEFORE the XML parser ever sees the payload (stdlib expat
        entity-expansion hardening varies by version; refusing the shape
        outright does not).
        """
        import tempfile
        import zipfile

        evil = (
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE w:document [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>\n'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&b;</w:t>'
            "</w:r></w:p></w:body></w:document>"
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "evil.docx"
            with zipfile.ZipFile(p, "w") as zf:
                zf.writestr("word/document.xml", evil)
            raw = p.read_bytes()
        with pytest.raises(SpMirrorError) as exc:
            convert_bytes("docx-text", raw, source_name="evil.docx")
        assert "DOCTYPE" in str(exc.value) or "DTD" in str(exc.value)

    def test_passthrough_utf8_and_loud_on_binary(self) -> None:
        assert convert_bytes("passthrough", b"# ok\n", source_name="a.md") == "# ok\n"
        with pytest.raises(SpMirrorError) as exc:
            convert_bytes("passthrough", b"\xff\xfe\x00\x01", source_name="a.md")
        assert "a.md" in str(exc.value)

    def test_unknown_converter_is_loud_and_typed(self) -> None:
        with pytest.raises(SpMirrorError):
            convert_bytes("bogus", b"x", source_name="a.md")
        assert issubclass(SpMirrorError, CodeDocMonitorError)  # K8 family


class TestConfig:
    def test_load_roundtrip_and_env_override(self, tmp_path: Path) -> None:
        cfg_path = _config(
            tmp_path, source="proxy", site_url="https://x.sharepoint.com/sites/s"
        )
        cfg = load_spmirror_config(cfg_path, env={})
        assert cfg.source == "proxy"
        assert cfg.dest == "docs/sharepoint"
        over = load_spmirror_config(cfg_path, env={"CDMON_SP_API": "http://ai03:8100"})
        assert over.api_url == "http://ai03:8100"

    def test_missing_file_is_loud(self, tmp_path: Path) -> None:
        with pytest.raises(SpMirrorError):
            load_spmirror_config(tmp_path / "nope.yaml", env={})

    def test_dir_source_requires_source_dir(self, tmp_path: Path) -> None:
        cfg_path = _config(tmp_path, source_dir=None)
        with pytest.raises(SpMirrorError) as exc:
            load_spmirror_config(cfg_path, env={})
        assert "source_dir" in str(exc.value)

    def test_proxy_source_requires_site_url(self, tmp_path: Path) -> None:
        cfg_path = _config(tmp_path, source="proxy")
        with pytest.raises(SpMirrorError) as exc:
            load_spmirror_config(cfg_path, env={})
        assert "site_url" in str(exc.value)

    def test_unknown_converter_id_rejected_at_load(self, tmp_path: Path) -> None:
        cfg_path = _config(tmp_path, converters={".docx": "bogus"})
        with pytest.raises(SpMirrorError) as exc:
            load_spmirror_config(cfg_path, env={})
        assert "bogus" in str(exc.value)


def _sync(tmp_path: Path, source: FakeSource, **kwargs: object):
    cfg = load_spmirror_config(_config(tmp_path), env={})
    return sync_mirror(cfg, tmp_path / "repo", source, **kwargs)  # type: ignore[arg-type]


class TestSyncCore:
    def test_first_sync_writes_mirror_and_manifest(self, tmp_path: Path) -> None:
        src = FakeSource(
            {
                "specs/Design.docx": (_docx_bytes(), "2026-07-01T10:00:00Z"),
                "README.md": (b"# Library\n", "2026-07-01T09:00:00Z"),
            }
        )
        report = _sync(tmp_path, src)
        mirror = tmp_path / "repo" / "docs" / "sharepoint"
        assert (mirror / "specs" / "Design.docx.md").read_text() == _GOLDEN_MD
        assert (mirror / "README.md").read_text() == "# Library\n"
        assert report.pulled == 2 and report.unchanged == 0
        assert sorted(report.written) == [
            "docs/sharepoint/README.md",
            "docs/sharepoint/specs/Design.docx.md",
        ]
        manifest = json.loads(
            (tmp_path / "repo" / ".cdmon" / "sp-manifest.json").read_text()
        )
        assert set(manifest["files"]) == {"specs/Design.docx", "README.md"}

    def test_manifest_skip_avoids_refetch(self, tmp_path: Path) -> None:
        src = FakeSource({"README.md": (b"# L\n", "2026-07-01T09:00:00Z")})
        _sync(tmp_path, src)
        assert src.fetch_calls == ["README.md"]
        report = _sync(tmp_path, src)
        assert src.fetch_calls == ["README.md"]  # no second fetch
        assert report.unchanged == 1 and report.pulled == 0

        # A changed listing entry (size or timestamp) re-fetches exactly it.
        src.files["README.md"] = (b"# L v2\n", "2026-07-02T09:00:00Z")
        report = _sync(tmp_path, src)
        assert src.fetch_calls == ["README.md", "README.md"]
        assert report.pulled == 1

    def test_force_refetches_but_stays_idempotent(self, tmp_path: Path) -> None:
        src = FakeSource({"README.md": (b"# L\n", "2026-07-01T09:00:00Z")})
        _sync(tmp_path, src)
        mirror = tmp_path / "repo" / "docs" / "sharepoint" / "README.md"
        before = mirror.read_bytes()
        report = _sync(tmp_path, src, force=True)
        assert src.fetch_calls == ["README.md", "README.md"]  # force refetched
        assert report.written == ()  # ...but unchanged bytes wrote nothing (K7)
        assert mirror.read_bytes() == before

    def test_second_sync_is_a_no_op(self, tmp_path: Path) -> None:
        src = FakeSource({"specs/Design.docx": (_docx_bytes(), "2026-07-01T10:00:00Z")})
        _sync(tmp_path, src)
        manifest_path = tmp_path / "repo" / ".cdmon" / "sp-manifest.json"
        before = manifest_path.read_bytes()
        report = _sync(tmp_path, src)
        assert report.written == () and report.pulled == 0
        assert manifest_path.read_bytes() == before  # K7: byte-stable state

    def test_front_matter_survives_body_update(self, tmp_path: Path) -> None:
        """The engine's cdm baseline block must survive every re-sync."""
        src = FakeSource({"README.md": (b"# L\n", "2026-07-01T09:00:00Z")})
        _sync(tmp_path, src)
        mirror = tmp_path / "repo" / "docs" / "sharepoint" / "README.md"
        # A heal stamps front matter onto the mirror file (simulated):
        stamped = "---\ncdm:\n  audience: user-guide\n  fingerprint: abc123\n---\n# L\n"
        mirror.write_text(stamped, encoding="utf-8")

        src.files["README.md"] = (b"# L v2\n", "2026-07-02T09:00:00Z")
        _sync(tmp_path, src)
        doc = parse_text(mirror.read_text(), mirror)
        assert doc.body == "# L v2\n"  # the new upstream body...
        assert doc.meta["cdm"]["fingerprint"] == "abc123"  # ...baseline intact

    def test_unmapped_suffix_skipped_and_reported(self, tmp_path: Path) -> None:
        src = FakeSource(
            {
                "logo.docx": (_docx_bytes(), "2026-07-01T10:00:00Z"),
                "logo.png": (b"\x89PNG", "2026-07-01T10:00:00Z"),
            }
        )
        cfg = load_spmirror_config(_config(tmp_path, include=["**"]), env={})
        report = sync_mirror(cfg, tmp_path / "repo", source=src)
        assert report.skipped_unmapped == ("logo.png",)
        assert src.fetch_calls == ["logo.docx"]  # the png was never fetched

    def test_include_exclude_and_max_bytes(self, tmp_path: Path) -> None:
        src = FakeSource(
            {
                "keep/a.md": (b"# a\n", "2026-07-01T00:00:00Z"),
                "archive/old.md": (b"# old\n", "2026-07-01T00:00:00Z"),
                "keep/big.md": (b"#" * 100, "2026-07-01T00:00:00Z"),
            }
        )
        cfg = load_spmirror_config(
            _config(
                tmp_path,
                include=["**/*.md"],
                exclude=["archive/**"],
                max_bytes=50,
            ),
            env={},
        )
        report = sync_mirror(cfg, tmp_path / "repo", source=src)
        assert report.pulled == 1 and report.skipped_filtered == 2
        assert src.fetch_calls == ["keep/a.md"]

    def test_prune_keeps_mirror_file_but_reports_it(self, tmp_path: Path) -> None:
        src = FakeSource(
            {
                "a.md": (b"# a\n", "2026-07-01T00:00:00Z"),
                "b.md": (b"# b\n", "2026-07-01T00:00:00Z"),
            }
        )
        _sync(tmp_path, src)
        del src.files["b.md"]
        report = _sync(tmp_path, src)
        assert report.stale_candidates == ("docs/sharepoint/b.md",)
        assert (tmp_path / "repo" / "docs" / "sharepoint" / "b.md").is_file()  # K5
        manifest = json.loads(
            (tmp_path / "repo" / ".cdmon" / "sp-manifest.json").read_text()
        )
        assert set(manifest["files"]) == {"a.md"}

    def test_dry_run_fetches_nothing_and_writes_nothing(self, tmp_path: Path) -> None:
        src = FakeSource({"a.md": (b"# a\n", "2026-07-01T00:00:00Z")})
        report = _sync(tmp_path, src, dry_run=True)
        assert src.fetch_calls == []
        assert report.pulled == 1  # reported as would-pull
        assert not (tmp_path / "repo" / "docs" / "sharepoint").exists()
        assert not (tmp_path / "repo" / ".cdmon" / "sp-manifest.json").exists()

    def test_mirror_is_deterministic_across_roots(self, tmp_path: Path) -> None:
        """Same source state → byte-identical mirror + manifest (K10)."""
        outputs = []
        for name in ("one", "two"):
            root = tmp_path / name
            root.mkdir()
            src = FakeSource(
                {"specs/Design.docx": (_docx_bytes(), "2026-07-01T10:00:00Z")}
            )
            cfg = load_spmirror_config(_config(root), env={})
            sync_mirror(cfg, root / "repo", source=src)
            outputs.append(
                (
                    (root / "repo/docs/sharepoint/specs/Design.docx.md").read_bytes(),
                    (root / "repo/.cdmon/sp-manifest.json").read_bytes(),
                )
            )
        assert outputs[0] == outputs[1]


class TestDirSource:
    def test_lists_and_fetches_a_local_tree(self, tmp_path: Path) -> None:
        lib = tmp_path / "library"
        (lib / "specs").mkdir(parents=True)
        (lib / "specs" / "a.md").write_text("# a\n", encoding="utf-8")
        (lib / "top.md").write_text("# top\n", encoding="utf-8")
        src = DirSource(lib)
        docs = src.list_documents()
        assert [d.path for d in docs] == ["specs/a.md", "top.md"]  # sorted
        assert all(d.last_modified.endswith("Z") for d in docs)
        assert src.fetch("specs/a.md") == b"# a\n"

    def test_missing_root_is_loud(self, tmp_path: Path) -> None:
        with pytest.raises(SpMirrorError):
            DirSource(tmp_path / "ghost").list_documents()


class _FakeHttp:
    """A canned urlopen replacement (no socket — K4)."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, object]]] = []

    def __call__(self, req, timeout: int = 0):  # noqa: ANN001
        body = json.loads(req.data.decode())
        path = req.full_url.split("8100", 1)[1]
        self.requests.append((path, body))
        payload = self.responses[path]
        return io.BytesIO(json.dumps(payload).encode())


class TestProxySource:
    def _source(self, monkeypatch: pytest.MonkeyPatch, responses: dict) -> tuple:
        import custodex.spmirror as spmirror

        fake = _FakeHttp(responses)
        monkeypatch.setattr(spmirror, "_urlopen", fake)
        src = ProxySource(
            api_url="http://x:8100",
            site_url="https://x.sharepoint.com/sites/s",
            folder=None,
        )
        return src, fake

    def test_list_and_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = b"# hello\n"
        src, fake = self._source(
            monkeypatch,
            {
                "/documents/list": {
                    "files": [
                        {
                            "path": "a.md",
                            "size_bytes": len(raw),
                            "last_modified": "2026-07-01T00:00:00Z",
                            "extension": "md",
                        }
                    ]
                },
                "/documents/fetch": {"content_base64": base64.b64encode(raw).decode()},
            },
        )
        docs = src.list_documents()
        assert docs == (
            SpDocument(
                path="a.md", size_bytes=len(raw), last_modified="2026-07-01T00:00:00Z"
            ),
        )
        assert src.fetch("a.md") == raw
        fetch_calls = [b for p, b in fake.requests if p == "/documents/fetch"]
        assert fetch_calls[0]["include_content"] is True

    def test_missing_content_is_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        src, _ = self._source(
            monkeypatch,
            {"/documents/fetch": {"download_url": "https://elsewhere"}},
        )
        with pytest.raises(SpMirrorError):
            src.fetch("a.md")

    def test_network_error_is_loud_and_typed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import urllib.error

        import custodex.spmirror as spmirror

        def boom(req, timeout: int = 0):  # noqa: ANN001
            raise urllib.error.URLError("unreachable")

        monkeypatch.setattr(spmirror, "_urlopen", boom)
        src = ProxySource(
            api_url="http://x:8100",
            site_url="https://x.sharepoint.com/sites/s",
            folder=None,
        )
        with pytest.raises(SpMirrorError):
            src.list_documents()


def test_document_xml_helper_is_wellformed() -> None:
    """The test fixture itself must stay valid XML (guards the guards)."""
    import xml.etree.ElementTree as ET

    ET.fromstring(document_xml(_DOC_PARAGRAPHS))
