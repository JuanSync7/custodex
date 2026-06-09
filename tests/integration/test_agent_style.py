"""N-05 — the writing-style seam in the agent's composed authoring prompt.

Asserts that, when a ``FixRequest`` carries ``style_guidance`` (the four selected
``templates/writing/`` bodies composed by ``docstyle.read_style_guidance``), the
agent's per-drift context — and thus the composed prompt — includes those four
bodies; and that with NO guidance the rendered context is BYTE-IDENTICAL to
today (additive, K6). Plus the Monitor seam: a ``DocStyleMap`` only feeds
guidance into the FixRequest for a no-renderer ``llm`` (authored-prose) region,
never otherwise. All offline/deterministic — no network (K4/K10).

Features: FEAT-AGENT-004, FEAT-AGENT-005, FEAT-AGENT-006, FEAT-AGENT-008
Features: FEAT-BACKENDS-008, FEAT-QUALITY-003, FEAT-MONITOR-009
"""

from __future__ import annotations

from pathlib import Path

from code_doc_monitor.agent import PromptLibrary, render_context, select_artifacts
from code_doc_monitor.agent.graph import build_graph
from code_doc_monitor.backends import FixRequest
from code_doc_monitor.config import AgentConfig, Audience, RegionMode
from code_doc_monitor.docstyle import DocStyleSelection, read_style_guidance
from code_doc_monitor.drift import Drift, DriftKind
from code_doc_monitor.extract import DocumentSurface, Symbol

# Reuse the docstyle suite's template-tree builder so the bodies are assertable.
from tests.unit.test_docstyle import _write_templates

_SELECTION = DocStyleSelection(
    document_type="api-reference",
    tone="precise",
    writing_style="reference-dense",
    vocabulary="engine-domain",
)

_BODIES = (
    "BODY-document-type-api-reference",
    "BODY-tone-precise",
    "BODY-writing-style-reference-dense",
    "BODY-vocabulary-engine-domain",
)


def _surface() -> DocumentSurface:
    return DocumentSurface(
        doc_id="d",
        audience=Audience.ENG_GUIDE,
        symbols=(
            Symbol(
                name="create_client",
                kind="function",
                signature="def create_client() -> Client",
                lineno=1,
                end_lineno=2,
                is_public=True,
                docstring="Make a client.",
            ),
        ),
    )


def _drift() -> Drift:
    return Drift(
        kind=DriftKind.REGION,
        doc_id="d",
        doc_path="d.md",
        detail="stale",
        region_id="prose",
        healable=True,
        audience=Audience.ENG_GUIDE,
    )


def _req(**kw) -> FixRequest:
    return FixRequest(
        drift=kw.pop("drift", _drift()),
        surface=kw.pop("surface", _surface()),
        doc_text=kw.pop("doc_text", "# d"),
        doc_spec_id=kw.pop("doc_spec_id", "d"),
        **kw,
    )


def test_render_context_includes_four_style_bodies_when_supplied(
    tmp_path: Path,
) -> None:
    """All four selected template bodies appear in the rendered context."""
    root = _write_templates(tmp_path)
    guidance = read_style_guidance(_SELECTION, root)
    ctx = render_context(_req(style_guidance=guidance))
    for body in _BODIES:
        assert body in ctx
    assert "Writing guidance (apply when AUTHORING" in ctx


def test_render_context_without_style_is_byte_identical(tmp_path: Path) -> None:
    """No style_guidance ⇒ render_context is byte-identical to a None request (K6)."""
    with_none = render_context(_req(style_guidance=None))
    baseline = render_context(_req())
    assert with_none == baseline
    # And none of the guidance markers leak in.
    assert "Writing guidance (apply when AUTHORING" not in baseline


def test_composed_prompt_includes_style_bodies(tmp_path: Path) -> None:
    """The agent's compose node folds the guidance into the full prompt."""
    root = _write_templates(tmp_path)
    guidance = read_style_guidance(_SELECTION, root)

    captured: dict[str, str] = {}

    def fake_driver(prompt: str) -> str:
        captured["prompt"] = prompt
        return (
            '{"verdict": "FIX", "cause": "authored from surface", '
            '"fix": {"region_id": "prose", "new_region_body": "x", '
            '"new_doc_text": null, "rationale": "authored prose"}}'
        )

    cfg = AgentConfig()
    graph = build_graph(fake_driver, PromptLibrary(), cfg)
    graph.invoke({"req": _req(style_guidance=guidance), "attempts": 0})
    for body in _BODIES:
        assert body in captured["prompt"]


def test_composed_prompt_without_style_omits_guidance() -> None:
    """No guidance ⇒ the composed prompt carries no writing-guidance header (K6)."""
    captured: dict[str, str] = {}

    def fake_driver(prompt: str) -> str:
        captured["prompt"] = prompt
        return (
            '{"verdict": "FIX", "cause": "c", '
            '"fix": {"region_id": "prose", "new_region_body": "x", '
            '"new_doc_text": null, "rationale": "r"}}'
        )

    graph = build_graph(fake_driver, PromptLibrary(), AgentConfig())
    graph.invoke({"req": _req(), "attempts": 0})
    assert "Writing guidance (apply when AUTHORING" not in captured["prompt"]


def _monitor_with_doc_style(tmp_path: Path, doc_style: object | None):
    """Build a Monitor over an empty config with ``templates/writing`` at root.

    The config dir IS ``tmp_path`` and ``root`` defaults to ".", so
    ``self.root / templates/writing`` == the tree _write_templates lays down.
    """
    from code_doc_monitor.config import MonitorConfig
    from code_doc_monitor.monitor import Monitor

    cfg = MonitorConfig(documents=())
    return Monitor(cfg, tmp_path, doc_style=doc_style)


def test_monitor_style_guidance_only_for_no_renderer_llm_region(
    tmp_path: Path,
) -> None:
    """_style_guidance_for fires for a no-renderer llm REGION; None otherwise."""
    from code_doc_monitor.config import load_bundle

    # A real bundle so doc_style is a genuine DocStyleMap.
    from tests.integration.test_config_v2 import _write_tree
    from tests.unit.test_docstyle import _DOC_STYLE_WITH_MAPPING

    d = _write_tree(tmp_path)
    repo_root = d.parent.parent
    _write_templates(repo_root)
    (d / "doc-style.yaml").write_text(_DOC_STYLE_WITH_MAPPING, encoding="utf-8")
    bundle = load_bundle(d)

    from code_doc_monitor.monitor import Monitor

    mon = Monitor(bundle.config, d, doc_style=bundle.doc_style)

    llm_region = _drift()  # REGION, region_id="prose"
    # Authoring case: a no-renderer llm region ⇒ guidance composed.
    guidance = mon._style_guidance_for(llm_region, RegionMode.LLM)
    assert guidance is not None
    for body in _BODIES:
        assert body in guidance

    # A generated region ⇒ no guidance.
    assert mon._style_guidance_for(llm_region, RegionMode.GENERATED) is None
    # A whole-doc (HASH) drift ⇒ no guidance even in llm mode.
    hash_drift = Drift(
        kind=DriftKind.HASH,
        doc_id="d",
        doc_path="d.md",
        detail="moved",
        region_id=None,
        healable=True,
        audience=Audience.ENG_GUIDE,
    )
    assert mon._style_guidance_for(hash_drift, RegionMode.LLM) is None


def test_monitor_no_doc_style_yields_no_guidance(tmp_path: Path) -> None:
    """No DocStyleMap ⇒ _style_guidance_for is always None (additive, K6)."""
    mon = _monitor_with_doc_style(tmp_path, None)
    assert mon._style_guidance_for(_drift(), RegionMode.LLM) is None


def test_monitor_renderer_backed_llm_region_gets_no_guidance(tmp_path: Path) -> None:
    """A renderer-backed llm region is rendered, not authored ⇒ no guidance."""
    from code_doc_monitor.config import (
        MonitorConfig,
        RegionColumn,
        RegionTemplate,
    )
    from code_doc_monitor.docstyle import DocStyleFrontmatter, DocStyleMap
    from code_doc_monitor.monitor import Monitor

    root = _write_templates(tmp_path)
    ds = DocStyleMap(
        frontmatter=DocStyleFrontmatter.model_validate(
            {
                "cdmon-config-version": "2.0.0",
                "kind": "doc-style-map",
                "updated": "2026-06-07",
            }
        ),
        defaults=_SELECTION,
    )
    # The drifted region "prose" HAS a renderer template ⇒ not an authoring case.
    cfg = MonitorConfig(
        documents=(),
        region_templates={
            "prose": RegionTemplate(
                source="symbols",
                columns=(RegionColumn(header="Name", field="name"),),
            )
        },
    )
    mon = Monitor(cfg, tmp_path, doc_style=ds)
    assert mon._style_guidance_for(_drift(), RegionMode.LLM) is None
    assert root.is_dir()  # templates exist; the guard, not absence, is what skips


def test_select_artifacts_unaffected_by_style(tmp_path: Path) -> None:
    """Style guidance does not change which artifacts are selected (orthogonal)."""
    root = _write_templates(tmp_path)
    guidance = read_style_guidance(_SELECTION, root)
    base = select_artifacts(_req(), AgentConfig(), PromptLibrary())
    styled = select_artifacts(
        _req(style_guidance=guidance), AgentConfig(), PromptLibrary()
    )
    assert base == styled
