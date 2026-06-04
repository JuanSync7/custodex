"""Tests for the LangGraph remediation agent (offline, deterministic — K4/K10).

The agent is a deterministic LangGraph workflow whose prompt is composed from
separated Markdown artifacts (AGENT/PROTOCOL/TOOL/PERSONA), loaded only when a
node needs them, and whose model-talking leaf (the *driver*) is INJECTED — so the
whole workflow runs with no subprocess and no network (K4). A malformed reply is
re-asked once and then raised as a loud, typed ``BackendError`` (K8). TDD (K9).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_doc_monitor.agent import (
    AgentBackend,
    Artifact,
    PromptLibrary,
    make_agent_backend,
    render_context,
    resolve_driver,
    select_artifacts,
)
from code_doc_monitor.agent import runtime as agent_runtime
from code_doc_monitor.backends import FixRequest, make_backend
from code_doc_monitor.blocks import symbol_table
from code_doc_monitor.config import (
    AgentConfig,
    Audience,
    BackendConfig,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    load_config,
    write_template,
)
from code_doc_monitor.drift import Drift, DriftKind
from code_doc_monitor.extract import DocumentSurface, Symbol, build_document_surface
from code_doc_monitor.monitor import Monitor
from code_doc_monitor.reviewlog import read_all
from code_doc_monitor.schema import Verdict
from code_doc_monitor.sinks import NullSink

FIXED_NOW = "2026-06-01T00:00:00+00:00"


def _now() -> str:
    return FIXED_NOW


def _surface(audience: Audience = Audience.ENG_GUIDE) -> DocumentSurface:
    return DocumentSurface(
        doc_id="d",
        audience=audience,
        symbols=(
            Symbol(
                name="create_client",
                kind="function",
                signature="def create_client(timeout: int = 30) -> Client",
                lineno=1,
                end_lineno=2,
                is_public=True,
                docstring="Make a client.",
            ),
        ),
    )


def _drift(
    *,
    kind: DriftKind = DriftKind.REGION,
    audience: Audience = Audience.ENG_GUIDE,
    healable: bool = True,
    region_id: str | None = "symbols",
    diff: str = "",
) -> Drift:
    return Drift(
        kind=kind,
        doc_id="d",
        doc_path="d.md",
        detail="stale",
        region_id=region_id,
        healable=healable,
        audience=audience,
        diff=diff,
    )


def _req(**kw) -> FixRequest:
    drift = kw.pop("drift", _drift())
    surface = kw.pop("surface", _surface())
    return FixRequest(
        drift=drift,
        surface=surface,
        doc_text=kw.pop("doc_text", "# d"),
        doc_spec_id=kw.pop("doc_spec_id", "d"),
        **kw,
    )


def _fix_reply(body: str) -> str:
    return json.dumps(
        {
            "verdict": "FIX",
            "cause": "regenerated from the surface",
            "fix": {
                "region_id": "symbols",
                "new_region_body": body,
                "new_doc_text": None,
                "rationale": "regenerated region symbols from the surface",
            },
        }
    )


# ---------------------------------------------------------------------------
# PromptLibrary — lazy load, frontmatter stripped, loud on missing (K8)
# ---------------------------------------------------------------------------
def test_packaged_artifacts_load_and_strip_frontmatter() -> None:
    lib = PromptLibrary()
    agent_md = lib.get(Artifact.AGENT)
    assert not agent_md.startswith("---")  # YAML frontmatter stripped
    assert "single source of truth" in agent_md
    assert "ONE JSON object" in lib.get(Artifact.PROTOCOL)
    assert "Region shape" in lib.get(Artifact.TOOL)
    assert lib.exists(Artifact.PERSONA)


def test_library_caches_after_first_read(tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text("body one", encoding="utf-8")
    lib = PromptLibrary(tmp_path)
    assert lib.get(Artifact.AGENT) == "body one"
    (tmp_path / "AGENT.md").write_text("body two", encoding="utf-8")
    assert lib.get(Artifact.AGENT) == "body one"  # cached, not re-read


def test_missing_artifact_raises_backend_error(tmp_path: Path) -> None:
    lib = PromptLibrary(tmp_path)
    assert not lib.exists(Artifact.AGENT)
    with pytest.raises(Exception) as exc:
        lib.get(Artifact.AGENT)
    assert "AGENT.md not found" in str(exc.value)


def test_strip_handles_unterminated_and_plain_bodies(tmp_path: Path) -> None:
    (tmp_path / "TOOL.md").write_text("no frontmatter here", encoding="utf-8")
    (tmp_path / "PROTOCOL.md").write_text(
        "---\nname: x\nno close fence", encoding="utf-8"
    )
    lib = PromptLibrary(tmp_path)
    assert lib.get(Artifact.TOOL) == "no frontmatter here"
    # Unterminated frontmatter -> whole stripped text returned (no crash).
    assert "name: x" in lib.get(Artifact.PROTOCOL)


# ---------------------------------------------------------------------------
# select_artifacts — "only when needed"
# ---------------------------------------------------------------------------
def test_region_drift_selects_tool_artifact() -> None:
    names = select_artifacts(_req(), AgentConfig(), PromptLibrary())
    assert names == [Artifact.AGENT, Artifact.PROTOCOL, Artifact.TOOL, Artifact.PERSONA]


def test_unhealable_drift_skips_tool_artifact() -> None:
    req = _req(drift=_drift(kind=DriftKind.UNHEALABLE, healable=False, region_id=None))
    names = select_artifacts(req, AgentConfig(), PromptLibrary())
    assert Artifact.TOOL not in names
    assert names[:2] == [Artifact.AGENT, Artifact.PROTOCOL]


def test_persona_skipped_when_disabled_or_absent(tmp_path: Path) -> None:
    # disabled
    names = select_artifacts(_req(), AgentConfig(use_persona=False), PromptLibrary())
    assert Artifact.PERSONA not in names
    # absent (empty dir with only AGENT/PROTOCOL/TOOL would still skip persona)
    names2 = select_artifacts(_req(), AgentConfig(), PromptLibrary(tmp_path))
    assert Artifact.PERSONA not in names2


# ---------------------------------------------------------------------------
# render_context
# ---------------------------------------------------------------------------
def test_render_context_includes_drift_surface_and_audience() -> None:
    ctx = render_context(_req(drift=_drift(diff="- old\n+ new")))
    assert "Audience: eng-guide" in ctx
    assert "kind: REGION" in ctx
    assert "managed region id: symbols" in ctx
    assert "- old\n+ new" in ctx
    assert "create_client" in ctx  # surface symbol table


def test_render_context_includes_index_body_when_present() -> None:
    ctx = render_context(_req(index_body="| Document | ... |"))
    assert "Pre-rendered index body" in ctx
    assert "| Document | ... |" in ctx


# ---------------------------------------------------------------------------
# The graph via AgentBackend — happy path, retry, exhaustion
# ---------------------------------------------------------------------------
def test_propose_happy_path_single_call() -> None:
    seen = {}

    def driver(prompt: str) -> str:
        seen["prompt"] = prompt
        seen["calls"] = seen.get("calls", 0) + 1
        return _fix_reply("X")

    result = AgentBackend(AgentConfig(), driver=driver).propose(_req())
    assert result.verdict == Verdict.FIX
    assert result.fix is not None and result.fix.new_region_body == "X"
    assert seen["calls"] == 1
    # The prompt is composed from the artifacts + the context (the .md files
    # actually drive the prompt).
    assert "single source of truth" in seen["prompt"]  # AGENT.md
    assert "ONE JSON object" in seen["prompt"]  # PROTOCOL.md
    assert "Region shape" in seen["prompt"]  # TOOL.md
    assert "kind: REGION" in seen["prompt"]  # context


def test_graph_is_built_once_and_reused_across_proposes() -> None:
    backend = AgentBackend(AgentConfig(), driver=lambda p: _fix_reply("X"))
    backend.propose(_req())
    graph1 = backend._graph
    backend.propose(_req())
    assert backend._graph is graph1  # compiled once, reused (the is-not-None branch)


def test_library_directory_accessor() -> None:
    assert PromptLibrary().directory.name == "prompts"


def test_driver_raising_backend_error_propagates_unwrapped(monkeypatch) -> None:
    from code_doc_monitor.errors import BackendError

    def raise_typed(argv, stdin, timeout):
        raise BackendError("already typed")

    # A BackendError from the leaf must pass through unchanged (not re-wrapped
    # with the generic "driver failed" message).
    monkeypatch.setattr(agent_runtime, "_default_process_runner", raise_typed)
    driver = resolve_driver(AgentConfig(driver="claude-code"))
    with pytest.raises(BackendError) as exc:
        driver("P")
    assert str(exc.value) == "already typed"


def test_invalidate_verdict_has_no_fix() -> None:
    reply = json.dumps({"verdict": "INVALIDATE", "cause": "comment only", "fix": None})
    result = AgentBackend(AgentConfig(), driver=lambda p: reply).propose(_req())
    assert result.verdict == Verdict.INVALIDATE
    assert result.fix is None


def test_malformed_reply_is_reasked_once_then_succeeds() -> None:
    calls = {"n": 0}

    def flaky(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            assert "PREVIOUS REPLY WAS NOT VALID JSON" not in prompt
            return "sorry, here is some prose"
        assert "PREVIOUS REPLY WAS NOT VALID JSON" in prompt  # retry nudge added
        return _fix_reply("Y")

    result = AgentBackend(AgentConfig(), driver=flaky).propose(_req())
    assert result.verdict == Verdict.FIX
    assert calls["n"] == 2  # one retry


def test_exhausted_retries_raise_backend_error() -> None:
    from code_doc_monitor.errors import BackendError

    backend = AgentBackend(
        AgentConfig(max_parse_retries=1), driver=lambda p: "never json"
    )
    with pytest.raises(BackendError):
        backend.propose(_req())


def test_zero_retries_fails_on_first_bad_reply() -> None:
    from code_doc_monitor.errors import BackendError

    calls = {"n": 0}

    def driver(prompt: str) -> str:
        calls["n"] += 1
        return "garbage"

    backend = AgentBackend(AgentConfig(max_parse_retries=0), driver=driver)
    with pytest.raises(BackendError):
        backend.propose(_req())
    assert calls["n"] == 1  # no retry when budget is 0


# ---------------------------------------------------------------------------
# Driver resolution — claude-code / api / local (K4, leaves monkeypatched)
# ---------------------------------------------------------------------------
def test_claude_code_driver_uses_runner_without_subprocess(monkeypatch) -> None:
    captured = {}

    def fake_runner(argv, stdin, timeout):
        captured["argv"] = argv
        captured["timeout"] = timeout
        return _fix_reply("Z")

    monkeypatch.setattr(agent_runtime, "_default_process_runner", fake_runner)
    driver = resolve_driver(AgentConfig(driver="claude-code", model="m", timeout_s=7))
    out = driver("PROMPT")
    assert "Z" in out
    assert captured["argv"] == ["claude", "-p", "--model", "m", "PROMPT"]
    assert captured["timeout"] == 7


def test_claude_code_command_template_substitutes_prompt(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        agent_runtime,
        "_default_process_runner",
        lambda argv, stdin, t: captured.setdefault("argv", argv) or "{}",
    )
    # {prompt} token form
    resolve_driver(AgentConfig(driver="claude-code", command=("c", "{prompt}", "-x")))(
        "P"
    )
    assert captured["argv"] == ["c", "P", "-x"]
    captured.clear()
    # no token -> appended
    resolve_driver(AgentConfig(driver="claude-code", command=("c", "-y")))("P")
    assert captured["argv"] == ["c", "-y", "P"]


def test_api_driver_requires_key_and_calls_leaf(monkeypatch) -> None:
    from code_doc_monitor.errors import BackendError

    monkeypatch.delenv("CDM_TEST_API_KEY", raising=False)
    with pytest.raises(BackendError) as exc:
        resolve_driver(AgentConfig(driver="api", api_key_env="CDM_TEST_API_KEY"))
    assert "needs an API key" in str(exc.value)

    monkeypatch.setenv("CDM_TEST_API_KEY", "sk-test")
    captured = {}

    def fake_call(model, prompt, timeout, key):
        captured.update(model=model, prompt=prompt, key=key)
        return "ok"

    monkeypatch.setattr(agent_runtime, "_anthropic_messages_call", fake_call)
    driver = resolve_driver(
        AgentConfig(driver="api", api_key_env="CDM_TEST_API_KEY", model="claude-x")
    )
    assert driver("HELLO") == "ok"
    assert captured == {"model": "claude-x", "prompt": "HELLO", "key": "sk-test"}


def test_local_driver_requires_base_url_and_calls_leaf(monkeypatch) -> None:
    from code_doc_monitor.errors import BackendError

    with pytest.raises(BackendError) as exc:
        resolve_driver(AgentConfig(driver="local"))
    assert "base_url" in str(exc.value)

    captured = {}

    def fake_call(base_url, model, prompt, timeout, key):
        captured.update(base_url=base_url, model=model, prompt=prompt)
        return "local-ok"

    monkeypatch.setattr(agent_runtime, "_openai_chat_call", fake_call)
    driver = resolve_driver(
        AgentConfig(driver="local", base_url="http://h/v1", model="llama")
    )
    assert driver("HEY") == "local-ok"
    assert captured["base_url"] == "http://h/v1"
    assert captured["model"] == "llama"


def test_driver_failure_is_wrapped_in_backend_error(monkeypatch) -> None:
    from code_doc_monitor.errors import BackendError

    def boom(argv, stdin, timeout):
        raise RuntimeError("subprocess blew up")

    monkeypatch.setattr(agent_runtime, "_default_process_runner", boom)
    driver = resolve_driver(AgentConfig(driver="claude-code"))
    with pytest.raises(BackendError) as exc:
        driver("P")
    assert "claude-code driver failed" in str(exc.value)


# ---------------------------------------------------------------------------
# Config + factory wiring
# ---------------------------------------------------------------------------
def test_agent_config_defaults() -> None:
    cfg = AgentConfig()
    assert cfg.driver == "claude-code"
    assert cfg.use_persona is True
    assert cfg.max_parse_retries == 1
    assert cfg.api_key_env == "ANTHROPIC_API_KEY"


def test_make_backend_kind_agent_builds_agent_backend() -> None:
    backend = make_backend(BackendConfig(kind="agent"), AgentConfig())
    assert isinstance(backend, AgentBackend)


def test_make_agent_backend_uses_prompts_dir_override(tmp_path: Path) -> None:
    for name in ("AGENT", "PROTOCOL", "TOOL", "PERSONA"):
        (tmp_path / f"{name}.md").write_text(f"{name} body", encoding="utf-8")
    seen = {}

    def capturing_driver(prompt: str) -> str:
        seen["p"] = prompt
        return _fix_reply("Q")

    backend = make_agent_backend(
        AgentConfig(prompts_dir=str(tmp_path)), driver=capturing_driver
    )
    result = backend.propose(_req())
    assert result.verdict == Verdict.FIX
    assert "AGENT body" in seen["p"]  # the override dir's artifacts were composed


def test_config_template_round_trips_with_agent_block(tmp_path: Path) -> None:
    path = tmp_path / "cdmon.yaml"
    write_template(path)
    cfg = load_config(path)
    assert cfg.agent.driver == "claude-code"
    assert cfg.agent.use_persona is True


def test_config_accepts_agent_backend_and_driver(tmp_path: Path) -> None:
    path = tmp_path / "cdmon.json"
    path.write_text(
        json.dumps(
            {
                "documents": [],
                "backend": {"kind": "agent"},
                "agent": {"driver": "local", "base_url": "http://h/v1"},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.backend.kind == "agent"
    assert cfg.agent.driver == "local"
    assert cfg.agent.base_url == "http://h/v1"


# ---------------------------------------------------------------------------
# End-to-end through the Monitor (offline, injected agent backend) — K4/K5/K7
# ---------------------------------------------------------------------------
def test_monitor_heals_with_agent_backend(tmp_path: Path) -> None:
    code = '''\
"""m."""


def public_fn(x: int) -> int:
    """Double."""
    return x * 2
'''
    (tmp_path / "code.py").write_text(code, encoding="utf-8")
    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    surface = build_document_surface(spec, tmp_path)
    correct_body = symbol_table(surface)
    # A stale region body (correct fingerprint) -> a single REGION drift.
    (tmp_path / "guide.md").write_text(
        f"---\ncdm:\n  fingerprint: {surface.surface_hash()}\n---\n# Guide\n\n"
        "<!-- CDM:BEGIN symbols -->\nSTALE\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    config = MonitorConfig(
        root=".", documents=(spec,), backend=BackendConfig(kind="agent")
    )

    # Inject an AgentBackend whose driver returns the correct region body.
    agent_backend = AgentBackend(
        AgentConfig(), driver=lambda p: _fix_reply(correct_body)
    )
    monitor = Monitor(
        config, tmp_path, backend=agent_backend, now=_now, sink=NullSink()
    )

    result = monitor.run(apply=True)

    assert result.remaining == ()  # the agent's FIX closed the drift (K7)
    assert all(h.result.verdict == Verdict.FIX for h in result.handled)
    records = read_all(tmp_path / ".cdmon" / "review-log.jsonl")
    assert records[0].verdict == Verdict.FIX
    assert records[0].fix is not None  # both drift and fix recorded (K5)
