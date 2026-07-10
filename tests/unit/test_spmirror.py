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
    docx_lossy_parts,
    load_spmirror_config,
    sync_mirror,
)
from tests._docx import (
    build_docx,
    build_docx_raw,
    document_xml,
    run,
    text_run,
    wrap_document,
)

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


def _raw_docx(
    body_xml: str,
    *,
    xml_prolog: str | None = None,
    parts: dict[str, str] | None = None,
) -> bytes:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.docx"
        build_docx_raw(p, wrap_document(body_xml, xml_prolog=xml_prolog), parts=parts)
        return p.read_bytes()


class TestDoc2mdOffice:
    """The in-process `doc2md-office` converter (optional [doc2md] extra).

    Gated on doc2md being importable — these SKIP cleanly in a core/CI env
    without it (the live_llm/pg opt-in precedent), and run for real when
    `pip install custodex[doc2md]` is present.
    """

    def _docx(self, paragraphs: list[tuple[str | None, str]], **kw: object) -> bytes:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.docx"
            build_docx(p, paragraphs, **kw)  # type: ignore[arg-type]
            return p.read_bytes()

    def test_registered_even_without_doc2md(self) -> None:
        # The converter is REGISTERED unconditionally, so a config naming it
        # loads/validates (and dry-runs) without doc2md installed.
        cfg_ok = load_spmirror_config  # smoke: import is fine
        assert cfg_ok is not None
        from custodex.spmirror import _CONVERTERS

        assert "doc2md-office" in _CONVERTERS

    def test_missing_dep_is_a_loud_install_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force the lazy import to fail and assert the actionable message.
        import builtins

        real_import = builtins.__import__

        def _no_backend(name: str, *a: object, **k: object):  # noqa: ANN202
            if name == "backend.ingest" or name.startswith("backend."):
                raise ImportError("no doc2md")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _no_backend)
        with pytest.raises(SpMirrorError) as exc:
            convert_bytes(
                "doc2md-office", self._docx([(None, "x")]), source_name="a.docx"
            )
        assert "custodex[doc2md]" in str(exc.value)

    def test_converts_docx_deterministically(self) -> None:
        pytest.importorskip("backend.ingest")
        out = convert_bytes(
            "doc2md-office",
            self._docx([("Heading1", "Spec"), (None, "widgets")]),
            source_name="a.docx",
        )
        assert "widgets" in out and out.endswith("\n")

    def test_container_churn_is_invisible(self) -> None:
        pytest.importorskip("backend.ingest")
        a = self._docx([(None, "same words")], zip_date=(2026, 1, 1, 0, 0, 0))
        b = self._docx(
            [(None, "same words")],
            zip_date=(2026, 6, 30, 12, 0, 0),
            reverse_order=True,
            extra_member="<x/>",
        )
        assert a != b
        assert convert_bytes("doc2md-office", a, source_name="a.docx") == convert_bytes(
            "doc2md-office", b, source_name="b.docx"
        )

    def test_unsupported_ext_is_loud(self) -> None:
        pytest.importorskip("backend.ingest")
        with pytest.raises(SpMirrorError) as exc:
            convert_bytes(
                "doc2md-office", self._docx([(None, "x")]), source_name="a.txt"
            )
        assert "office" in str(exc.value)

    def test_dtd_refused_through_the_doc2md_path(self) -> None:
        pytest.importorskip("backend.ingest")
        raw = _raw_docx(
            "<w:p><w:r><w:t>hi</w:t></w:r></w:p>",
            xml_prolog=(
                '<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY x "boom">]>'
            ),
        )
        with pytest.raises(SpMirrorError) as exc:
            convert_bytes("doc2md-office", raw, source_name="evil.docx")
        assert "DOCTYPE" in str(exc.value) or "DTD" in str(exc.value)

    def test_non_zip_is_loud(self) -> None:
        pytest.importorskip("backend.ingest")
        with pytest.raises(SpMirrorError):
            convert_bytes("doc2md-office", b"not a zip", source_name="a.docx")

    def test_doc2md_internal_failure_is_wrapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A future doc2md that RAISES inside its converter must surface as a
        # typed SpMirrorError, never a raw traceback through the CLI (K8).
        pytest.importorskip("backend.ingest")
        import backend.ingest as ingest

        def boom(ext: str, parts: dict, emit_images: bool = False):  # noqa: ANN202
            raise RuntimeError("doc2md exploded")

        monkeypatch.setattr(ingest, "ooxml_markdown", boom)
        with pytest.raises(SpMirrorError) as exc:
            convert_bytes(
                "doc2md-office", self._docx([(None, "x")]), source_name="a.docx"
            )
        assert "doc2md failed" in str(exc.value)

    def test_config_accepts_doc2md_office_without_the_dep(self, tmp_path: Path) -> None:
        # Config validation must not require doc2md — only conversion does.
        cfg_path = _config(tmp_path, converters={".docx": "doc2md-office"})
        cfg = load_spmirror_config(cfg_path, env={})
        assert cfg.converters[".docx"] == "doc2md-office"


class TestConverterFixes:
    """Review-round fixes to the load-bearing docx-text converter."""

    def test_tab_and_cr_are_preserved_no_collision(self) -> None:
        # Review #7: dropping w:tab/w:cr collapsed distinct content to a
        # fingerprint collision. They must render as \t and \n.
        tabbed = convert_bytes(
            "docx-text",
            _raw_docx(run(text_run("Name"), "<w:tab/>", text_run("Age"))),
            source_name="x.docx",
        )
        joined = convert_bytes(
            "docx-text",
            _raw_docx(run(text_run("NameAge"))),
            source_name="x.docx",
        )
        assert tabbed == "Name\tAge\n"
        assert tabbed != joined  # the collision is gone
        cr = convert_bytes(
            "docx-text",
            _raw_docx(run(text_run("L1"), "<w:cr/>", text_run("L2"))),
            source_name="x.docx",
        )
        assert cr == "L1\nL2\n"

    def test_br_becomes_newline(self) -> None:
        out = convert_bytes(
            "docx-text",
            _raw_docx(run(text_run("L1"), "<w:br/>", text_run("L2"))),
            source_name="x.docx",
        )
        assert out == "L1\nL2\n"

    def test_empty_paragraph_is_dropped(self) -> None:
        body = run(text_run("Real")) + "<w:p><w:r><w:t>   </w:t></w:r></w:p>"
        out = convert_bytes("docx-text", _raw_docx(body), source_name="x.docx")
        assert out == "Real\n"

    def test_non_heading_pstyle_has_no_prefix(self) -> None:
        body = (
            '<w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr>'
            "<w:r><w:t>plain</w:t></w:r></w:p>"
        )
        out = convert_bytes("docx-text", _raw_docx(body), source_name="x.docx")
        assert out == "plain\n"

    def test_text_box_content_emitted_once(self) -> None:
        # Review #6: a nested w:p (text box) was emitted twice.
        body = (
            "<w:p><w:r><w:t>Outer.</w:t></w:r>"
            "<w:pict><w:txbxContent>"
            "<w:p><w:r><w:t>Box line</w:t></w:r></w:p>"
            "</w:txbxContent></w:pict></w:p>"
        )
        out = convert_bytes("docx-text", _raw_docx(body), source_name="x.docx")
        assert out.count("Box line") == 1

    def test_malformed_xml_is_loud(self) -> None:
        raw = _raw_docx("<w:p><w:r><w:t>unclosed")
        with pytest.raises(SpMirrorError) as exc:
            convert_bytes("docx-text", raw, source_name="x.docx")
        assert "malformed" in str(exc.value)

    def test_dtd_guard_survives_a_long_benign_prefix(self) -> None:
        # Review #13: a payload[:100] head-window mutant must be killed —
        # the DOCTYPE sits far past byte 100 behind a long comment.
        prefix = (
            '<?xml version="1.0"?>' + "<!--" + ("x" * 400) + "-->"
            '<!DOCTYPE w:document [<!ENTITY a "boom">]>'
        )
        raw = _raw_docx("<w:p><w:r><w:t>hi</w:t></w:r></w:p>", xml_prolog=prefix)
        with pytest.raises(SpMirrorError) as exc:
            convert_bytes("docx-text", raw, source_name="x.docx")
        assert "DOCTYPE" in str(exc.value) or "DTD" in str(exc.value)

    def test_dtd_guard_catches_utf16_encoding(self) -> None:
        # Review #5: a byte-substring scan is evaded by UTF-16; the parser-
        # level guard sees the DOCTYPE regardless of encoding.
        doc = wrap_document(
            "<w:p><w:r><w:t>hi</w:t></w:r></w:p>",
            xml_prolog=(
                '<?xml version="1.0" encoding="UTF-16"?>'
                '<!DOCTYPE w:document [<!ENTITY x "PWNED">]>'
            ),
        )
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "u.docx"
            build_docx_raw(p, doc.encode("utf-16"))
            payload = p.read_bytes()
        assert b"<!DOCTYPE" not in payload  # the ASCII bytes are absent (UTF-16)
        with pytest.raises(SpMirrorError):
            convert_bytes("docx-text", payload, source_name="u.docx")

    def test_decompression_bomb_is_refused(self) -> None:
        # Review #8: a small zip whose document.xml decompresses huge.
        import tempfile

        big = wrap_document(
            "<w:p><w:r><w:t>" + ("A" * (70 * 1024 * 1024)) + "</w:t></w:r></w:p>"
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bomb.docx"
            build_docx_raw(p, big)
            raw = p.read_bytes()
        assert len(raw) < 1024 * 1024  # compresses tiny...
        with pytest.raises(SpMirrorError) as exc:  # ...but is refused on read
            convert_bytes("docx-text", raw, source_name="bomb.docx")
        assert "bomb" in str(exc.value).lower() or "cap" in str(exc.value).lower()


class TestLossyParts:
    def test_body_only_doc_has_no_lossy_parts(self) -> None:
        raw = _raw_docx(run(text_run("body")))
        assert docx_lossy_parts(raw) == ()

    def test_text_bearing_aux_parts_are_reported(self) -> None:
        # Review #4: a footnote/header edit is invisible to the fingerprint —
        # it must at least be REPORTED, never silently dropped.
        raw = _raw_docx(
            run(text_run("See note.")),
            parts={
                "word/footnotes.xml": wrap_document(run(text_run("the footnote"))),
                "word/header1.xml": wrap_document(run(text_run("HEADER"))),
                "word/styles.xml": "<styles/>",  # no w:t → not reported
            },
        )
        assert docx_lossy_parts(raw) == ("word/footnotes.xml", "word/header1.xml")

    def test_lossy_parts_ignores_textless_aux(self) -> None:
        raw = _raw_docx(
            run(text_run("body")),
            parts={"word/footer1.xml": "<w:ftr></w:ftr>"},  # no w:t
        )
        assert docx_lossy_parts(raw) == ()

    def test_lossy_parts_swallows_a_non_zip(self) -> None:
        assert docx_lossy_parts(b"not a zip") == ()


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

    def test_malformed_yaml_is_loud(self, tmp_path: Path) -> None:
        # Review #20: the YAMLError arm was untested.
        cfg_path = tmp_path / "repo" / "config" / "spmirror.yaml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text("spmirror:\n  - [unbalanced\n", encoding="utf-8")
        with pytest.raises(SpMirrorError) as exc:
            load_spmirror_config(cfg_path, env={})
        assert "malformed YAML" in str(exc.value)

    def test_non_mapping_top_level_is_loud(self, tmp_path: Path) -> None:
        # Review #20: the non-mapping / missing-'spmirror:' arm was untested.
        cfg_path = tmp_path / "repo" / "config" / "spmirror.yaml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text("just a string\n", encoding="utf-8")
        with pytest.raises(SpMirrorError) as exc:
            load_spmirror_config(cfg_path, env={})
        assert "spmirror" in str(exc.value)


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

    def test_last_modified_is_the_skip_signal_when_no_hash(
        self, tmp_path: Path
    ) -> None:
        # Review #12: a source with no content_hash (ProxySource shape) must
        # skip on last_modified — a SAME-SIZE edit with a changed timestamp
        # re-fetches (drops the timestamp comparison and this fails).
        src = FakeSource({"a.md": (b"# aaa\n", "2026-07-01T00:00:00Z")})
        _sync(tmp_path, src)
        assert src.fetch_calls == ["a.md"]
        # Same 6-byte size, new timestamp, changed content → must re-fetch.
        src.files["a.md"] = (b"# bbb\n", "2026-07-02T00:00:00Z")
        report = _sync(tmp_path, src)
        assert src.fetch_calls == ["a.md", "a.md"]
        assert report.pulled == 1
        mirror = tmp_path / "repo" / "docs" / "sharepoint" / "a.md"
        assert mirror.read_text() == "# bbb\n"

    def test_filtered_file_is_not_pruned_as_gone(self, tmp_path: Path) -> None:
        # Review #3: a file transiently filtered out (max_bytes) must NOT be
        # reported "gone upstream" nor dropped from the manifest — it is still
        # in the listing, just skipped this run.
        src = FakeSource(
            {
                "a.md": (b"# a\n", "2026-07-01T00:00:00Z"),
                "big.md": (b"#" * 100, "2026-07-01T00:00:00Z"),
            }
        )
        _sync(tmp_path, src)  # both mirrored (default max_bytes=None)
        cfg = load_spmirror_config(_config(tmp_path, max_bytes=50), env={})
        report = sync_mirror(cfg, tmp_path / "repo", source=src)
        assert report.stale_candidates == ()  # big.md is filtered, not gone
        assert report.skipped_filtered == 1
        manifest = json.loads(
            (tmp_path / "repo" / ".cdmon" / "sp-manifest.json").read_text()
        )
        assert set(manifest["files"]) == {"a.md", "big.md"}  # entry retained

    def test_two_sources_same_mirror_path_is_loud(self, tmp_path: Path) -> None:
        # Review #11: a literal X.docx.md (passthrough) and X.docx (docx-text
        # → X.docx.md) collide on one mirror path — refuse loudly.
        src = FakeSource(
            {
                "d/Design.docx": (_docx_bytes(), "2026-07-01T00:00:00Z"),
                "d/Design.docx.md": (b"# literal\n", "2026-07-01T00:00:00Z"),
            }
        )
        cfg = load_spmirror_config(
            _config(
                tmp_path,
                include=["**/*.docx", "**/*.md"],
                converters={".docx": "docx-text", ".md": "passthrough"},
            ),
            env={},
        )
        with pytest.raises(SpMirrorError) as exc:
            sync_mirror(cfg, tmp_path / "repo", source=src)
        assert "same mirror path" in str(exc.value)

    def test_force_refetches_but_stays_idempotent(self, tmp_path: Path) -> None:
        src = FakeSource({"README.md": (b"# L\n", "2026-07-01T09:00:00Z")})
        _sync(tmp_path, src)
        mirror = tmp_path / "repo" / "docs" / "sharepoint" / "README.md"
        before = mirror.read_bytes()
        report = _sync(tmp_path, src, force=True)
        assert src.fetch_calls == ["README.md", "README.md"]  # force refetched
        assert report.written == ()  # ...but unchanged bytes wrote nothing (K7)
        assert mirror.read_bytes() == before

    def test_second_sync_is_a_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src = FakeSource({"specs/Design.docx": (_docx_bytes(), "2026-07-01T10:00:00Z")})
        _sync(tmp_path, src)
        manifest_path = tmp_path / "repo" / ".cdmon" / "sp-manifest.json"
        before = manifest_path.read_bytes()

        # Review #22: an "always rewrite the manifest" mutant kept the bytes
        # identical, so a bytes-equality assert could not kill it. Count the
        # actual writes to that path instead.
        writes: list[Path] = []
        real_write = Path.write_text

        def _counting_write(self, *a, **k):  # noqa: ANN001, ANN002
            if self == manifest_path:
                writes.append(self)
            return real_write(self, *a, **k)

        monkeypatch.setattr(Path, "write_text", _counting_write)
        report = _sync(tmp_path, src)
        assert report.written == () and report.pulled == 0
        assert manifest_path.read_bytes() == before  # K7: byte-stable state
        assert writes == []  # ...and the manifest was NOT rewritten

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

    def test_traversal_paths_from_the_source_are_refused(self, tmp_path: Path) -> None:
        """A compromised source must not write outside dest (K8).

        DirSource paths come from rglob (repo-shaped by construction), but
        ProxySource paths are REMOTE INPUT — an absolute, parent-escaping,
        or backslashed listing entry is an attack shape, not a document.
        """
        for evil in ("../../escape.md", "/etc/owned.md", "a\\..\\b.md"):
            src = FakeSource({evil: (b"# x\n", "2026-07-01T00:00:00Z")})
            cfg = load_spmirror_config(_config(tmp_path, include=["**"]), env={})
            with pytest.raises(SpMirrorError) as exc:
                sync_mirror(cfg, tmp_path / "repo", source=src)
            assert "unsafe path" in str(exc.value)
        assert not (tmp_path / "escape.md").exists()

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

    def test_supplies_content_hash(self, tmp_path: Path) -> None:
        lib = tmp_path / "library"
        lib.mkdir()
        (lib / "a.md").write_text("# a\n", encoding="utf-8")
        (doc,) = DirSource(lib).list_documents()
        assert doc.content_hash is not None and len(doc.content_hash) == 16

    def test_fetch_unreadable_is_typed(self, tmp_path: Path) -> None:
        # Review #9: a raw OSError must not escape as an untyped traceback.
        lib = tmp_path / "library"
        lib.mkdir()
        with pytest.raises(SpMirrorError):
            DirSource(lib).fetch("does-not-exist.md")

    def _dir_cfg(self, tmp_path: Path, lib: Path) -> object:
        cfg_path = tmp_path / "repo" / "config" / "spmirror.yaml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            yaml.safe_dump(
                {
                    "spmirror": {
                        "source": "dir",
                        "source_dir": str(lib),
                        "dest": "docs/sharepoint",
                        "include": ["**/*.md"],
                        "converters": {".md": "passthrough"},
                    }
                }
            ),
            encoding="utf-8",
        )
        return load_spmirror_config(cfg_path, env={})

    def test_mtime_bump_without_content_change_is_a_noop(self, tmp_path: Path) -> None:
        # Review #2: an mtime-only bump (git checkout/rsync) must NOT refetch
        # or rewrite the manifest — the content-hash skip-key ignores mtime.
        import os

        lib = tmp_path / "library"
        lib.mkdir()
        f = lib / "a.md"
        f.write_text("# a\n", encoding="utf-8")
        cfg = self._dir_cfg(tmp_path, lib)
        sync_mirror(cfg, tmp_path / "repo", DirSource(lib))  # type: ignore[arg-type]
        manifest_path = tmp_path / "repo" / ".cdmon" / "sp-manifest.json"
        before = manifest_path.read_bytes()
        os.utime(f, (1_800_000_000, 1_800_000_000))  # bump mtime, same content
        report = sync_mirror(cfg, tmp_path / "repo", DirSource(lib))  # type: ignore[arg-type]
        assert report.pulled == 0 and report.unchanged == 1
        assert manifest_path.read_bytes() == before  # K7 across a checkout

    def test_same_size_same_second_edit_is_caught(self, tmp_path: Path) -> None:
        # Review #1: a same-size edit within one clock second used to be MISSED
        # (truncated-mtime skip-key). The content hash catches it.
        import os

        lib = tmp_path / "library"
        lib.mkdir()
        f = lib / "a.md"
        f.write_text("# aaa\n", encoding="utf-8")  # 6 bytes
        os.utime(f, (1_800_000_000.1, 1_800_000_000.1))
        cfg = self._dir_cfg(tmp_path, lib)
        sync_mirror(cfg, tmp_path / "repo", DirSource(lib))  # type: ignore[arg-type]
        mirror = tmp_path / "repo" / "docs" / "sharepoint" / "a.md"
        assert mirror.read_text() == "# aaa\n"
        # Same 6-byte size, mtime truncates to the SAME whole second:
        f.write_text("# bbb\n", encoding="utf-8")
        os.utime(f, (1_800_000_000.9, 1_800_000_000.9))
        report = sync_mirror(cfg, tmp_path / "repo", DirSource(lib))  # type: ignore[arg-type]
        assert report.pulled == 1
        assert mirror.read_text() == "# bbb\n"  # the edit is NOT missed

    def test_symlink_out_of_tree_is_skipped(self, tmp_path: Path) -> None:
        # Review #10: a symlink can point outside the library — mirroring its
        # target into dest is an escape. It must be skipped from the listing.
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET\n", encoding="utf-8")
        lib = tmp_path / "library"
        lib.mkdir()
        (lib / "real.md").write_text("# real\n", encoding="utf-8")
        try:
            (lib / "leak.md").symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")
        paths = [d.path for d in DirSource(lib).list_documents()]
        assert paths == ["real.md"]  # the symlink is gone

    def test_mirror_target_symlink_is_refused(self, tmp_path: Path) -> None:
        # Review #17: a symlink planted at the mirror target must not be
        # written through onto an out-of-tree file.
        outside = tmp_path / "outside.txt"
        outside.write_text("SECRET\n", encoding="utf-8")
        lib = tmp_path / "library"
        lib.mkdir()
        (lib / "notes.md").write_text("# n\n", encoding="utf-8")
        cfg = self._dir_cfg(tmp_path, lib)
        target = tmp_path / "repo" / "docs" / "sharepoint" / "notes.md"
        target.parent.mkdir(parents=True)
        try:
            target.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")
        with pytest.raises(SpMirrorError) as exc:
            sync_mirror(cfg, tmp_path / "repo", DirSource(lib))  # type: ignore[arg-type]
        assert "symlink" in str(exc.value)
        assert outside.read_text() == "SECRET\n"  # untouched


class TestManifestCorruption:
    def test_unparseable_manifest_is_loud(self, tmp_path: Path) -> None:
        # Review #14: the _load_sp_manifest raise arms were untested.
        src = FakeSource({"a.md": (b"# a\n", "2026-07-01T00:00:00Z")})
        manifest_path = tmp_path / "repo" / ".cdmon" / "sp-manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text("not json{", encoding="utf-8")
        with pytest.raises(SpMirrorError) as exc:
            _sync(tmp_path, src)
        assert "malformed sp-manifest" in str(exc.value)

    def test_wrong_type_manifest_is_loud(self, tmp_path: Path) -> None:
        src = FakeSource({"a.md": (b"# a\n", "2026-07-01T00:00:00Z")})
        manifest_path = tmp_path / "repo" / ".cdmon" / "sp-manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text('{"files": []}', encoding="utf-8")
        with pytest.raises(SpMirrorError) as exc:
            _sync(tmp_path, src)
        assert "files map" in str(exc.value)


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
        # Review #19: pin the wire request keys against the real service shape.
        list_calls = [b for p, b in fake.requests if p == "/documents/list"]
        assert list_calls[0]["site_url"] == "https://x.sharepoint.com/sites/s"
        assert list_calls[0]["folder_path"] is None
        fetch_calls = [b for p, b in fake.requests if p == "/documents/fetch"]
        assert fetch_calls[0]["include_content"] is True
        assert fetch_calls[0]["document_path"] == "a.md"
        assert fetch_calls[0]["site_url"] == "https://x.sharepoint.com/sites/s"

    def test_missing_content_is_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        src, _ = self._source(
            monkeypatch,
            {"/documents/fetch": {"download_url": "https://elsewhere"}},
        )
        with pytest.raises(SpMirrorError):
            src.fetch("a.md")

    def test_bad_list_shape_is_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Review #21: a /documents/list entry missing size_bytes.
        src, _ = self._source(
            monkeypatch,
            {"/documents/list": {"files": [{"path": "a.md"}]}},
        )
        with pytest.raises(SpMirrorError) as exc:
            src.list_documents()
        assert "shape unexpected" in str(exc.value)

    def test_invalid_base64_is_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Review #21: a /documents/fetch content_base64 that is not base64.
        src, _ = self._source(
            monkeypatch,
            {"/documents/fetch": {"content_base64": "!!! not base64 !!!"}},
        )
        with pytest.raises(SpMirrorError) as exc:
            src.fetch("a.md")
        assert "base64" in str(exc.value)

    def test_non_json_body_is_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Review #21: a body that is not JSON at all.
        import custodex.spmirror as spmirror

        def not_json(req, timeout: int = 0):  # noqa: ANN001
            return io.BytesIO(b"<html>500</html>")

        monkeypatch.setattr(spmirror, "_urlopen", not_json)
        src = ProxySource(
            api_url="http://x:8100",
            site_url="https://x.sharepoint.com/sites/s",
            folder=None,
        )
        with pytest.raises(SpMirrorError) as exc:
            src.list_documents()
        assert "malformed JSON" in str(exc.value)

    def test_oversize_response_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Review #18: an over-cap HTTP body must be refused before json.loads
        # (this bounds the base64 blob too — it is a field inside the body).
        import custodex.spmirror as spmirror

        monkeypatch.setattr(spmirror, "_MAX_RESPONSE_BYTES", 16)
        src, _ = self._source(
            monkeypatch,
            {"/documents/list": {"files": [{"path": "a.md", "size_bytes": 1}]}},
        )
        with pytest.raises(SpMirrorError) as exc:
            src.list_documents()
        assert "exceeds" in str(exc.value)

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
