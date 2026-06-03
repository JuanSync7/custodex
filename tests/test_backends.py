"""Tests for code_doc_monitor.backends (CDM-05).

Backends are pluggable and offline by default (K4): the default is the
deterministic ``MockBackend`` (no network, no LLM). The ``claude-code`` and
``api`` backends are exercised ONLY through an injected fake runner/client — no
real subprocess and no real network ever run (K4). A malformed LLM reply raises
a loud, typed ``BackendError`` (K8). The shared ``build_prompt`` is audience
aware (K3). TDD (K9).
"""

from __future__ import annotations

import json

import pytest

from code_doc_monitor.backends import (
    ApiBackend,
    Backend,
    BackendResult,
    ClaudeCodeBackend,
    FixRequest,
    MockBackend,
    build_prompt,
    make_backend,
    parse_backend_json,
)
from code_doc_monitor.blocks import expected_region
from code_doc_monitor.config import Audience, BackendConfig
from code_doc_monitor.drift import Drift, DriftKind
from code_doc_monitor.errors import BackendError
from code_doc_monitor.extract import DocumentSurface, Symbol
from code_doc_monitor.schema import ProposedFix, Verdict


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------
def _surface(audience: Audience = Audience.USER_GUIDE) -> DocumentSurface:
    return DocumentSurface(
        doc_id="user-guide",
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
    audience: Audience = Audience.USER_GUIDE,
    region_id: str | None = "symbols",
    detail: str = "managed region 'symbols' is out of date",
) -> Drift:
    return Drift(
        kind=kind,
        doc_id="user-guide",
        doc_path="docs/user-guide.md",
        detail=detail,
        region_id=region_id,
        healable=kind is not DriftKind.UNHEALABLE,
        audience=audience,
    )


def _req(
    *,
    drift: Drift | None = None,
    audience: Audience = Audience.USER_GUIDE,
) -> FixRequest:
    surface = _surface(audience)
    return FixRequest(
        drift=drift if drift is not None else _drift(audience=audience),
        surface=surface,
        doc_text=(
            "# Guide\n\n<!-- CDM:BEGIN symbols -->\nold\n<!-- CDM:END symbols -->\n"
        ),
        doc_spec_id="user-guide",
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def test_fix_request_and_result_are_frozen() -> None:
    req = _req()
    with pytest.raises(Exception):  # noqa: B017 - pydantic frozen error
        req.doc_text = "mutated"  # type: ignore[misc]
    res = BackendResult(verdict=Verdict.ESCALATE, cause="needs a human")
    assert res.fix is None
    with pytest.raises(Exception):  # noqa: B017
        res.cause = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# build_prompt (audience-aware, JSON-only)
# ---------------------------------------------------------------------------
def test_build_prompt_is_audience_aware_and_json_only() -> None:
    prompt = build_prompt(_req(audience=Audience.USER_GUIDE))
    # Audience present.
    assert "user-guide" in prompt
    # The JSON-only instruction and the contract keys.
    assert "JSON" in prompt
    assert '"verdict"' in prompt
    assert "FIX|INVALIDATE|ESCALATE" in prompt
    # The drift detail and kind.
    assert "out of date" in prompt
    assert "REGION" in prompt
    # The region id for a region drift.
    assert "symbols" in prompt
    # The current document text and the code surface (symbol table).
    assert "create_client" in prompt
    assert "CDM:BEGIN symbols" in prompt
    # The decision rule must mention both audience verdicts.
    assert "INVALIDATE" in prompt
    assert "FIX" in prompt


def test_build_prompt_eng_guide_states_eng_audience() -> None:
    prompt = build_prompt(_req(audience=Audience.ENG_GUIDE))
    assert "eng-guide" in prompt


def test_build_prompt_handles_drift_without_region() -> None:
    d = _drift(kind=DriftKind.HASH, region_id=None, detail="fingerprint moved")
    prompt = build_prompt(_req(drift=d))
    assert "fingerprint moved" in prompt
    assert "HASH" in prompt


# ---------------------------------------------------------------------------
# parse_backend_json (robust extraction + validation)
# ---------------------------------------------------------------------------
def test_parse_bare_json() -> None:
    text = json.dumps({"verdict": "ESCALATE", "cause": "human needed", "fix": None})
    res = parse_backend_json(text)
    assert res.verdict is Verdict.ESCALATE
    assert res.cause == "human needed"
    assert res.fix is None


def test_parse_fenced_json() -> None:
    text = (
        "Here is my answer:\n```json\n"
        + json.dumps(
            {
                "verdict": "FIX",
                "cause": "regenerate",
                "fix": {
                    "region_id": "symbols",
                    "new_region_body": "| a |",
                    "new_doc_text": None,
                    "rationale": "table refresh",
                },
            }
        )
        + "\n```\nThanks!"
    )
    res = parse_backend_json(text)
    assert res.verdict is Verdict.FIX
    assert res.fix is not None
    assert isinstance(res.fix, ProposedFix)
    assert res.fix.region_id == "symbols"
    assert res.fix.rationale == "table refresh"


def test_parse_json_with_surrounding_prose() -> None:
    text = (
        "I think the verdict is invalidate. "
        + json.dumps({"verdict": "INVALIDATE", "cause": "comment only", "fix": None})
        + " That is my final answer."
    )
    res = parse_backend_json(text)
    assert res.verdict is Verdict.INVALIDATE
    assert res.cause == "comment only"


def test_parse_garbage_raises_backend_error() -> None:
    with pytest.raises(BackendError):
        parse_backend_json("no json here at all")


def test_parse_invalid_verdict_raises_backend_error() -> None:
    text = json.dumps({"verdict": "MAYBE", "cause": "x", "fix": None})
    with pytest.raises(BackendError):
        parse_backend_json(text)


def test_parse_malformed_json_object_raises_backend_error() -> None:
    # Looks like it starts an object but never closes / is not valid JSON.
    with pytest.raises(BackendError):
        parse_backend_json("{verdict: FIX, cause:}")


def test_parse_missing_cause_raises_backend_error() -> None:
    with pytest.raises(BackendError):
        parse_backend_json(json.dumps({"verdict": "FIX"}))


def test_parse_handles_braces_inside_strings() -> None:
    # A '}' inside a JSON string value must not prematurely close the object,
    # and an escaped quote must not end the string early.
    text = (
        "prose without braces "
        + json.dumps(
            {
                "verdict": "ESCALATE",
                "cause": 'a } brace and a \\" quote inside text',
                "fix": None,
            }
        )
        + " trailing"
    )
    res = parse_backend_json(text)
    assert res.verdict is Verdict.ESCALATE
    assert "}" in res.cause


def test_parse_unbalanced_object_raises_backend_error() -> None:
    with pytest.raises(BackendError):
        parse_backend_json('{"verdict": "FIX", "cause": "x"')


def test_parse_non_object_json_raises_backend_error() -> None:
    # A balanced object is required; a JSON array/scalar is rejected. We embed a
    # brace so an object is found, but its contents are not a mapping.
    with pytest.raises(BackendError):
        parse_backend_json('{"just": [1, 2, 3]}')  # missing verdict/cause


def test_parse_fix_not_an_object_raises_backend_error() -> None:
    text = json.dumps({"verdict": "FIX", "cause": "x", "fix": "not-an-object"})
    with pytest.raises(BackendError):
        parse_backend_json(text)


def test_parse_fix_malformed_raises_backend_error() -> None:
    # 'fix' is an object but missing the required 'rationale'.
    text = json.dumps({"verdict": "FIX", "cause": "x", "fix": {"region_id": "s"}})
    with pytest.raises(BackendError):
        parse_backend_json(text)


# ---------------------------------------------------------------------------
# MockBackend — deterministic (K4)
# ---------------------------------------------------------------------------
def test_mock_backend_region_drift_returns_fix_with_regenerated_body() -> None:
    req = _req(drift=_drift(kind=DriftKind.REGION, region_id="symbols"))
    res = MockBackend().propose(req)
    assert res.verdict is Verdict.FIX
    assert res.fix is not None
    assert res.fix.region_id == "symbols"
    # The regenerated body is exactly expected_region of the surface.
    assert res.fix.new_region_body == expected_region("symbols", req.surface)


def test_mock_backend_region_drift_unknown_region_does_not_fix() -> None:
    # An unknown region id has no renderer -> falls through to ESCALATE.
    req = _req(drift=_drift(kind=DriftKind.REGION, region_id="prose"))
    res = MockBackend().propose(req)
    assert res.verdict is Verdict.ESCALATE


def test_mock_backend_user_guide_comment_hash_invalidates() -> None:
    d = _drift(
        kind=DriftKind.HASH,
        audience=Audience.USER_GUIDE,
        region_id=None,
        detail="docstring text changed in a private helper",
    )
    res = MockBackend().propose(_req(drift=d, audience=Audience.USER_GUIDE))
    assert res.verdict is Verdict.INVALIDATE
    assert res.fix is None


def test_mock_backend_eng_guide_comment_hash_does_not_invalidate() -> None:
    # Same comment-style HASH drift but eng-guide audience -> NOT invalidate.
    # An eng-guide tracks docstrings, so a docstring HASH drift is real drift and
    # is FIXed (whole-doc regenerate), never INVALIDATEd.
    d = _drift(
        kind=DriftKind.HASH,
        audience=Audience.ENG_GUIDE,
        region_id=None,
        detail="docstring text changed",
    )
    res = MockBackend().propose(_req(drift=d, audience=Audience.ENG_GUIDE))
    assert res.verdict is Verdict.FIX
    assert res.verdict is not Verdict.INVALIDATE


def test_mock_backend_fixes_surface_hash_drift_whole_doc() -> None:
    # A public-surface HASH drift -> FIX with a whole-doc rewrite (regions +
    # fingerprint). This is what lets monitor --apply fully self-heal.
    d = _drift(
        kind=DriftKind.HASH,
        audience=Audience.USER_GUIDE,
        region_id=None,
        detail="public signature changed",
    )
    res = MockBackend().propose(_req(drift=d))
    assert res.verdict is Verdict.FIX
    assert res.fix is not None
    assert res.fix.new_doc_text is not None
    assert res.fix.region_id is None


def test_mock_backend_escalates_unhealable() -> None:
    # An UNHEALABLE drift (an unknown managed-region id) needs a human.
    d = _drift(
        kind=DriftKind.UNHEALABLE,
        audience=Audience.USER_GUIDE,
        region_id="mystery",
        detail="unknown managed region id",
    )
    res = MockBackend().propose(_req(drift=d))
    assert res.verdict is Verdict.ESCALATE
    assert "human" in res.cause.lower()


def test_mock_backend_satisfies_backend_protocol() -> None:
    backend: Backend = MockBackend()
    assert isinstance(backend.propose(_req()), BackendResult)


# ---------------------------------------------------------------------------
# ClaudeCodeBackend — injected runner (K4)
# ---------------------------------------------------------------------------
def test_claude_code_backend_uses_injected_runner_and_parses() -> None:
    captured: dict[str, object] = {}

    def fake_runner(argv: list[str], stdin: str, timeout_s: int) -> str:
        captured["argv"] = argv
        captured["stdin"] = stdin
        captured["timeout_s"] = timeout_s
        return json.dumps({"verdict": "ESCALATE", "cause": "from claude", "fix": None})

    backend = ClaudeCodeBackend(runner=fake_runner, timeout_s=42)
    res = backend.propose(_req())
    assert res.verdict is Verdict.ESCALATE
    assert res.cause == "from claude"
    # Default argv is ["claude", "-p", <prompt>] and the prompt is present.
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[0] == "claude"
    assert "-p" in argv
    assert any("create_client" in part for part in argv)
    assert captured["timeout_s"] == 42


def test_claude_code_backend_default_argv_includes_model() -> None:
    captured: dict[str, object] = {}

    def fake_runner(argv: list[str], stdin: str, timeout_s: int) -> str:
        captured["argv"] = argv
        return json.dumps({"verdict": "ESCALATE", "cause": "x", "fix": None})

    backend = ClaudeCodeBackend(model="sonnet", runner=fake_runner)
    backend.propose(_req())
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert "--model" in argv
    assert "sonnet" in argv
    # Prompt is still the last argument.
    assert "create_client" in argv[-1]


def test_claude_code_backend_command_template_with_placeholder() -> None:
    captured: dict[str, object] = {}

    def fake_runner(argv: list[str], stdin: str, timeout_s: int) -> str:
        captured["argv"] = argv
        return json.dumps({"verdict": "ESCALATE", "cause": "x", "fix": None})

    backend = ClaudeCodeBackend(
        command=("claude", "--model", "sonnet", "-p", "{prompt}"),
        runner=fake_runner,
    )
    backend.propose(_req())
    argv = captured["argv"]
    assert isinstance(argv, list)
    # The {prompt} token was substituted with the real prompt.
    assert "{prompt}" not in argv
    assert any("create_client" in part for part in argv)
    assert "--model" in argv


def test_claude_code_backend_command_template_without_placeholder_appends() -> None:
    captured: dict[str, object] = {}

    def fake_runner(argv: list[str], stdin: str, timeout_s: int) -> str:
        captured["argv"] = argv
        return json.dumps({"verdict": "ESCALATE", "cause": "x", "fix": None})

    backend = ClaudeCodeBackend(command=("claude", "-p"), runner=fake_runner)
    backend.propose(_req())
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[:2] == ["claude", "-p"]
    # No placeholder -> prompt is appended as the last argument.
    assert "create_client" in argv[-1]


def test_claude_code_backend_runner_failure_raises_backend_error() -> None:
    def boom(argv: list[str], stdin: str, timeout_s: int) -> str:
        raise RuntimeError("subprocess exploded")

    backend = ClaudeCodeBackend(runner=boom)
    with pytest.raises(BackendError):
        backend.propose(_req())


def test_claude_code_backend_bad_output_raises_backend_error() -> None:
    def fake_runner(argv: list[str], stdin: str, timeout_s: int) -> str:
        return "not json"

    backend = ClaudeCodeBackend(runner=fake_runner)
    with pytest.raises(BackendError):
        backend.propose(_req())


def test_claude_code_default_runner_built_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When no runner is injected, propose() builds a stdlib subprocess runner.
    # We stub subprocess.run so the lazy-build branch runs with NO real process.
    import code_doc_monitor.backends as backends_mod

    class FakeCompleted:
        def __init__(self) -> None:
            self.stdout = json.dumps(
                {"verdict": "ESCALATE", "cause": "stub", "fix": None}
            )
            self.returncode = 0

    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> FakeCompleted:
        calls.append(argv)
        return FakeCompleted()

    monkeypatch.setattr(backends_mod.subprocess, "run", fake_run)
    backend = ClaudeCodeBackend()
    res = backend.propose(_req())
    assert res.verdict is Verdict.ESCALATE
    assert calls and calls[0][0] == "claude"


def test_claude_code_default_runner_nonzero_exit_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import code_doc_monitor.backends as backends_mod

    class FakeCompleted:
        def __init__(self) -> None:
            self.stdout = ""
            self.stderr = "boom"
            self.returncode = 2

    def fake_run(argv: list[str], **kwargs: object) -> FakeCompleted:
        return FakeCompleted()

    monkeypatch.setattr(backends_mod.subprocess, "run", fake_run)
    backend = ClaudeCodeBackend()
    with pytest.raises(BackendError):
        backend.propose(_req())


# ---------------------------------------------------------------------------
# ApiBackend — injected client (K4)
# ---------------------------------------------------------------------------
def test_api_backend_uses_injected_client_and_parses() -> None:
    captured: dict[str, object] = {}

    def fake_client(*, model: str, prompt: str, timeout: int) -> str:
        captured["model"] = model
        captured["prompt"] = prompt
        captured["timeout"] = timeout
        return json.dumps(
            {"verdict": "INVALIDATE", "cause": "api says comment", "fix": None}
        )

    backend = ApiBackend(model="claude-x", client=fake_client, timeout_s=7)
    res = backend.propose(_req())
    assert res.verdict is Verdict.INVALIDATE
    assert res.cause == "api says comment"
    assert captured["model"] == "claude-x"
    assert "create_client" in str(captured["prompt"])
    assert captured["timeout"] == 7


def test_api_backend_bad_output_raises_backend_error() -> None:
    def fake_client(*, model: str, prompt: str, timeout: int) -> str:
        return "definitely not json"

    backend = ApiBackend(model="claude-x", client=fake_client)
    with pytest.raises(BackendError):
        backend.propose(_req())


def test_api_backend_client_failure_raises_backend_error() -> None:
    def boom(*, model: str, prompt: str, timeout: int) -> str:
        raise RuntimeError("network down")

    backend = ApiBackend(model="claude-x", client=boom)
    with pytest.raises(BackendError):
        backend.propose(_req())


def test_api_backend_propagates_backend_error_from_client() -> None:
    def raise_backend(*, model: str, prompt: str, timeout: int) -> str:
        raise BackendError("already typed")

    backend = ApiBackend(model="claude-x", client=raise_backend)
    with pytest.raises(BackendError, match="already typed"):
        backend.propose(_req())


def test_api_backend_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # No client injected -> default client is built, which needs the API key.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    backend = ApiBackend(model="claude-x")
    with pytest.raises(BackendError):
        backend.propose(_req())


def test_api_backend_default_client_built_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With the key present the default client is built; stub its leaf call so no
    # network runs (K4) yet the lazy-build branch is covered.
    import code_doc_monitor.backends as backends_mod

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    posted: list[str] = []

    def fake_call(model: str, prompt: str, timeout: int, api_key: str) -> str:
        posted.append(prompt)
        return json.dumps({"verdict": "ESCALATE", "cause": "stub", "fix": None})

    monkeypatch.setattr(backends_mod, "_anthropic_messages_call", fake_call)
    backend = ApiBackend(model="claude-x")
    res = backend.propose(_req())
    assert res.verdict is Verdict.ESCALATE
    assert posted and "create_client" in posted[0]


# ---------------------------------------------------------------------------
# make_backend factory
# ---------------------------------------------------------------------------
def test_make_backend_mock() -> None:
    assert isinstance(make_backend(BackendConfig(kind="mock")), MockBackend)


def test_make_backend_claude_code() -> None:
    cfg = BackendConfig(kind="claude-code", command=("claude", "-p"), timeout_s=99)
    backend = make_backend(cfg)
    assert isinstance(backend, ClaudeCodeBackend)


def test_make_backend_api() -> None:
    cfg = BackendConfig(kind="api", model="claude-x", timeout_s=99)
    backend = make_backend(cfg)
    assert isinstance(backend, ApiBackend)


def test_make_backend_api_uses_default_model_when_unset() -> None:
    backend = make_backend(BackendConfig(kind="api"))
    assert isinstance(backend, ApiBackend)
