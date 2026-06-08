"""Pluggable LLM fixer backends — offline by default (K0, K4, K8).

A backend turns one :class:`~code_doc_monitor.drift.Drift` into a
:class:`BackendResult` (a verdict + cause + optional proposed fix). Every
backend returns the SAME JSON contract so the orchestrator is backend-agnostic
(K4). Three implementations ship:

* :class:`MockBackend` — deterministic and offline (the default, K4). No
  network, no LLM; its rules make the whole pipeline reproducible in CI.
* :class:`ClaudeCodeBackend` — headless ``claude -p`` subprocess. The process
  ``runner`` is INJECTED so tests never spawn ``claude`` (K4); when none is
  given a stdlib :mod:`subprocess` runner is built lazily (K0).
* :class:`ApiBackend` — Anthropic Messages API. The HTTP ``client`` is INJECTED
  so tests never hit the network (K4); the lazily-built default uses stdlib
  :mod:`urllib` only (no ``anthropic`` package, K0).

:func:`build_prompt` is the single, audience-aware prompt builder shared by the
LLM backends (K3). :func:`parse_backend_json` robustly extracts the JSON verdict
object from a possibly-prose-wrapped reply and validates it into a
:class:`BackendResult`, raising a loud :class:`BackendError` on anything
malformed (K8).
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from .blocks import expected_region, symbol_table
from .config import (
    AgentConfig,
    Audience,
    BackendConfig,
    ContextRef,
    RegionMode,
    RegionTemplate,
)
from .drift import Drift, DriftKind
from .errors import BackendError, ExtractionError
from .extract import DocumentSurface, extract_file
from .heal import render_corrected
from .schema import ProposedFix, Verdict
from .similar import Exemplar

__all__ = [
    "FixRequest",
    "BackendResult",
    "Backend",
    "MockBackend",
    "ClaudeCodeBackend",
    "ApiBackend",
    "build_prompt",
    "parse_backend_json",
    "make_backend",
]

# Frozen + extra="forbid": a request/result is an immutable snapshot and an
# unexpected key is a loud error, not a silent pass (K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: Default API model when none is configured.
_DEFAULT_API_MODEL = "claude-sonnet-4-20250514"

#: Token replaced by the rendered prompt in a configured claude-code command.
_PROMPT_TOKEN = "{prompt}"

#: Markers in a user-guide HASH drift detail that signal a non-public change the
#: mock backend can safely INVALIDATE (a deterministic stand-in for the LLM's
#: "this doesn't affect the public surface" judgement).
_INVALIDATE_MARKERS = ("docstring", "comment", "private")

#: The audience-aware clause appended to an LLM backend's prompt for a no-renderer
#: `llm` REGION request (B-06). Real backends only; the mock authors prose
#: deterministically in code and never sees this.
_LLM_PROSE_CLAUSE = (
    "This region is LLM-authored PROSE (it has no mechanical renderer): write a "
    "clear, audience-appropriate prose description of the surface below; do NOT "
    "emit a symbol table."
)


def _authored_prose(surface: DocumentSurface) -> str:
    """A deterministic, idempotent prose body authored from ``surface`` (B-06).

    The offline stand-in for "what an LLM would write" for a no-renderer ``llm``
    region (mirrors how MockBackend rule 3 stands in for whole-doc prose). It is
    a stable, audience-aware sentence enumerating the PUBLIC symbols the section
    covers, derived purely from the code surface (K2) — same surface ⇒ identical
    body (K10), so a re-author is a clean no-op (K7).
    """
    audience = surface.audience.value
    names = sorted(s.name for s in surface.symbols if s.is_public)
    covered = ", ".join(f"`{n}`" for n in names) if names else "no public symbols"
    return (
        f"This {audience} section is authored from the code surface "
        "(the single source of truth) and is re-authored whenever that surface "
        f"changes. It covers the public API: {covered}."
    )


class FixRequest(BaseModel):
    """Everything a backend needs to judge one drift (immutable)."""

    model_config = _MODEL_CONFIG

    drift: Drift
    surface: DocumentSurface
    doc_text: str
    doc_spec_id: str
    # Config region templates, so a backend regenerates templated tables the same
    # way the engine does (empty for symbol-only / built-in regions).
    region_templates: dict[str, RegionTemplate] = {}
    # Pre-rendered body for a `source='index'` region (it lists OTHER documents,
    # so the engine renders it with all-docs context and passes it in). None
    # unless the drifted region is an index region.
    index_body: str | None = None
    # B-06 (ADDITIVE, K6): the authority mode of the drifted region, so a backend
    # knows a no-renderer `llm` REGION is PROSE it must author (vs a `generated`
    # region it mechanically renders). Defaults to GENERATED ⇒ every pre-B-06
    # FixRequest/test is unchanged; `monitor.run` sets it from `spec.mode_for(...)`.
    region_mode: RegionMode = RegionMode.GENERATED
    # D-04 few-shot exemplars (ADDITIVE, K6): the most-similar PAST RESOLVED drifts
    # (from `similar.rank_similar`). Default empty ⇒ every pre-D-04 FixRequest and
    # backend test is unchanged. Only the agent backend renders them; the mock and
    # the single-shot `build_prompt` IGNORE them (the mock stays deterministic).
    exemplars: tuple[Exemplar, ...] = ()
    # N-05 (ADDITIVE, K6): writing-style guidance for AUTHORING a no-renderer
    # `llm` region's prose — the four selected `templates/writing/` bodies,
    # already composed by `docstyle.read_style_guidance`. Default None ⇒ the
    # agent's composed prompt is BYTE-IDENTICAL to today (no style map => no
    # change). Only the agent backend's `render_context` injects it; the mock
    # (which authors prose deterministically in code) ignores it (K4/K10).
    style_guidance: str | None = None
    # E-02 (ADDITIVE, K6): the document's `context_refs` — "glance-through"
    # sub-documents / sub-source-files the author should refer to (EDITOR §3).
    # They are NOT coverage and NOT the documented surface; they are rendered as
    # a reference block in the authoring prompt. `repo_root` is the repo-root
    # path used to read source-file context refs for a deterministic public-symbol
    # glance (K10). Default empty ⇒ every pre-E-02 FixRequest/test is unchanged:
    # no context_refs ⇒ no reference block at all. The mock backend ignores them
    # (it authors prose deterministically in code).
    context_refs: tuple[ContextRef, ...] = ()
    repo_root: str | None = None
    # P-01 (ADDITIVE, K6): the opt-in body-AST fingerprint tier. The backend MUST
    # stamp the whole-doc fix's fingerprint with the SAME tier `drift.detect` used
    # (one shared truth), else a re-stamp the engine then re-detects diverges into
    # a permanent HASH drift. Default False ⇒ every pre-P-01 FixRequest/test is
    # byte-identical; `monitor.run` sets it from `config.fingerprint_body_tier`.
    fingerprint_body_tier: bool = False


class BackendResult(BaseModel):
    """A backend's decision for one drift: verdict + cause + optional fix."""

    model_config = _MODEL_CONFIG

    verdict: Verdict
    cause: str
    fix: ProposedFix | None = None


@runtime_checkable
class Backend(Protocol):
    """Something that proposes a verdict for one drift."""

    def propose(self, req: FixRequest) -> BackendResult: ...


# Injected process/HTTP shapes (K4): tests pass a fake, no real subprocess/net.
ProcessRunner = Callable[[list[str], str, int], str]
ApiClient = Callable[..., str]


#: Header for the E-02 reference-material block (EDITOR §3). Present only when a
#: document declares `context_refs`; absent otherwise ⇒ pre-E-02 byte-identical.
_CONTEXT_REFS_HEADER = (
    "# Reference material (glance through; do NOT duplicate — refer/link as needed)"
)


def _context_ref_symbol_glance(path: str, repo_root: str | None) -> str:
    """A short, deterministic public-symbol glance for a SOURCE-file context ref.

    Reuses :func:`~code_doc_monitor.extract.extract_file` (the same AST-only,
    import-free machinery the surface uses, K0/K10) to list the file's PUBLIC
    symbol names so the author can refer to them. Returns a ``(not found)``
    marker when the file is absent on disk (a context ref MAY point at a
    not-yet-created file — never raise, EDITOR §3). The repo-root-relative
    ``path`` is resolved against ``repo_root`` when given (else the cwd).
    """
    base = Path(repo_root) if repo_root is not None else Path()
    target = base / path
    if not target.is_file():
        return "  (not found — refer to it once it exists)"
    try:
        symbols = extract_file(target)
    except ExtractionError:
        return "  (could not parse — refer to it by path)"
    names = sorted(s.name for s in symbols if s.is_public)
    if not names:
        return "  public symbols: (none)"
    return "  public symbols: " + ", ".join(names)


def _render_context_refs(req: FixRequest) -> str:
    """Render the E-02 reference-material block, or ``""`` when there are none.

    Lists each :class:`~code_doc_monitor.config.ContextRef` by ``path`` (+ its
    ``note`` when present). For a SOURCE-file ref (``.py``) it ALSO appends a
    short public-symbol glance derived deterministically from the file (K10);
    doc (``.md``) refs are listed by path + note only. Returns the empty string
    for a context-ref-free request so the prompt is byte-identical to pre-E-02
    (additive, K6).
    """
    if not req.context_refs:
        return ""
    lines: list[str] = ["", _CONTEXT_REFS_HEADER]
    for ref in req.context_refs:
        note = f" — {ref.note}" if ref.note else ""
        lines.append(f"- {ref.path}{note}")
        if ref.path.endswith(".py"):
            lines.append(_context_ref_symbol_glance(ref.path, req.repo_root))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Shared prompt + reply parsing
# ---------------------------------------------------------------------------
def build_prompt(req: FixRequest) -> str:
    """Build the shared, audience-aware prompt for an LLM backend (K3).

    Describes the drift, includes the current document text and the relevant
    code surface (symbol table), states the audience and the audience-specific
    decision rule, and demands a JSON-only reply matching the backend contract.
    """
    drift = req.drift
    audience = req.surface.audience.value
    region_line = (
        f"- managed region id: {drift.region_id}\n"
        if drift.region_id is not None
        else ""
    )
    diff_line = f"- diff:\n{drift.diff}\n" if drift.diff else ""

    if req.surface.audience is Audience.USER_GUIDE:
        rule = (
            "This document's audience is USER-GUIDE: only the externally-visible "
            "surface matters. If the underlying change is to a comment, a "
            "docstring, a private (_-prefixed) symbol, or a local variable — "
            "anything that does NOT change the public API surface — reply "
            "INVALIDATE (the drift is irrelevant to this audience). Reply FIX "
            "only when the public surface actually changed."
        )
    else:
        rule = (
            "This document's audience is ENG-GUIDE: the implementation surface "
            "matters too. A comment/docstring/private/internal change IS relevant "
            "here, so reply FIX (regenerate the affected content) rather than "
            "INVALIDATE."
        )

    if drift.kind is DriftKind.REGION:
        shape = (
            "This is a REGION drift: return a region-shaped fix — set "
            '"region_id" to the managed region id above and "new_region_body" to '
            'its regenerated content, and leave "new_doc_text" null. Fill exactly '
            "one fix shape; do not also return a whole-document text."
        )
    else:
        shape = (
            "This is a whole-document drift (e.g. a HASH/fingerprint mismatch or a "
            'missing doc): return a whole-doc fix — set "new_doc_text" to the FULL '
            "corrected document (keep the human prose, regenerate every managed "
            "region, and refresh the front-matter fingerprint), and leave "
            '"region_id" and "new_region_body" null. Fill exactly one fix shape.'
        )

    # B-06: a no-renderer `llm` REGION is authored PROSE (real backends only —
    # the mock authors prose deterministically in code). Append a prose clause so
    # the model writes a description, not a symbol table.
    prose_clause = (
        f"\n\n{_LLM_PROSE_CLAUSE}"
        if drift.kind is DriftKind.REGION and req.region_mode is RegionMode.LLM
        else ""
    )

    # E-02: the document's glance-through context refs (sub-docs / sub-source
    # files) as a labeled reference block. Empty for a context-ref-free request
    # ⇒ byte-identical to pre-E-02 (additive, K6).
    context_block = _render_context_refs(req)

    return (
        "You are a documentation-drift remediation assistant. A monitor detected "
        "that a document is out of sync with the code it describes. Decide whether "
        "to FIX the document, INVALIDATE the drift (the change is irrelevant to "
        "this document's audience), or ESCALATE it to a human.\n"
        "\n"
        f"Audience: {audience}\n"
        f"Document id: {req.doc_spec_id}\n"
        f"Document path: {drift.doc_path}\n"
        "\n"
        "Detected drift:\n"
        f"- kind: {drift.kind.value}\n"
        f"- detail: {drift.detail}\n"
        f"{region_line}"
        f"{diff_line}"
        "\n"
        "Current document text:\n"
        "<<<DOC\n"
        f"{req.doc_text}\n"
        "DOC\n"
        "\n"
        "Relevant code surface (the single source of truth):\n"
        "<<<SURFACE\n"
        f"{symbol_table(req.surface)}\n"
        "SURFACE\n"
        f"{context_block}"
        "\n"
        f"Decision rule: {rule}\n"
        "\n"
        "Reply with ONLY a single JSON object and no other text:\n"
        '{"verdict": "FIX|INVALIDATE|ESCALATE", "cause": "...", '
        '"fix": {"region_id": ..., "new_region_body": ..., '
        '"new_doc_text": ..., "rationale": ...} | null}\n'
        "Use null for fix when the verdict is INVALIDATE or ESCALATE.\n"
        "\n"
        f"Fix shape: {shape}"
        f"{prose_clause}"
    )


def _extract_json_object(text: str) -> str:
    """Return the first balanced ``{...}`` JSON object found in ``text`` (K8).

    Handles bare JSON, ```json``-fenced JSON, and JSON embedded in prose by
    scanning for the first ``{`` and matching braces (respecting strings and
    escapes). Raises :class:`BackendError` when no object is present.
    """
    start = text.find("{")
    if start == -1:
        raise BackendError(f"backend reply contained no JSON object: {text[:200]!r}")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise BackendError(f"backend reply had an unbalanced JSON object: {text[:200]!r}")


def parse_backend_json(text: str) -> BackendResult:
    """Parse an LLM reply into a :class:`BackendResult`, loudly (K8).

    Robust to prose and ```json`` fences. Raises :class:`BackendError` on no
    JSON, malformed JSON, an invalid verdict, or a payload that fails the
    :class:`BackendResult`/:class:`ProposedFix` contract.
    """
    blob = _extract_json_object(text)

    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise BackendError(f"backend reply was not valid JSON: {exc}") from exc

    if not isinstance(data, dict):  # pragma: no cover - defensive: blob is always {...}
        raise BackendError(f"backend reply JSON was not an object: {data!r}")

    raw_fix = data.get("fix")
    fix: ProposedFix | None = None
    if raw_fix is not None:
        if not isinstance(raw_fix, dict):
            raise BackendError(f"backend 'fix' was not an object: {raw_fix!r}")
        try:
            fix = ProposedFix(**raw_fix)
        except (ValidationError, TypeError) as exc:
            raise BackendError(f"backend 'fix' was malformed: {exc}") from exc

    try:
        return BackendResult(
            verdict=data["verdict"],
            cause=data["cause"],
            fix=fix,
        )
    except KeyError as exc:
        raise BackendError(f"backend reply missing required key: {exc}") from exc
    except ValidationError as exc:
        raise BackendError(f"backend reply failed validation: {exc}") from exc


# ---------------------------------------------------------------------------
# MockBackend (deterministic, offline default — K4)
# ---------------------------------------------------------------------------
class MockBackend:
    """Deterministic, offline backend (the default, K4).

    Rules (kept deliberately simple and documented):

    1. **Healable region drift -> FIX.** If ``drift.kind == REGION`` and the
       region id has a known renderer, regenerate its body from the surface via
       :func:`~code_doc_monitor.blocks.expected_region` and return ``FIX``. This
       is the path that makes the auto-heal loop deterministic.
    1b. **No-renderer `llm` region drift -> FIX (authored prose).** If
       ``drift.kind == REGION`` and ``req.region_mode == LLM`` and the id has NO
       renderer (rule 1 produced no body), author a DETERMINISTIC, IDEMPOTENT
       prose body from the surface via :func:`_authored_prose` and return ``FIX``
       (B-06). This is the offline stand-in for "what an LLM would write" for a
       pure-prose region — same surface ⇒ identical body (K10), so a re-author is
       a clean no-op (K7).
    2. **User-guide comment/docstring/private HASH drift -> INVALIDATE.** If the
       audience is ``user-guide``, the drift is a ``HASH`` drift, and its
       ``detail`` mentions a non-public marker (docstring/comment/private), the
       change does not affect the public surface for this audience, so it is
       INVALIDATE-able (K3).
    3. **Surface (fingerprint) HASH drift -> FIX (whole-doc).** Any remaining
       ``HASH`` drift means the code surface moved and the document must be
       regenerated. The fix is the fully-corrected document text (managed
       regions regenerated + fingerprint refreshed) via
       :func:`~code_doc_monitor.heal.render_corrected` — exactly what an LLM would
       return, computed deterministically. This is what lets ``monitor --apply``
       fully close realistic drift (a code change raises BOTH a HASH and a REGION
       drift; this rule closes the HASH, the rule-1 fix closes the REGION).
    4. **Otherwise -> ESCALATE.** Anything else (e.g. MISSING_DOC needing prose,
       or an UNHEALABLE unknown region) needs a human.
    """

    def propose(self, req: FixRequest) -> BackendResult:
        drift = req.drift

        if drift.kind is DriftKind.REGION and drift.region_id is not None:
            template = req.region_templates.get(drift.region_id)
            if template is not None and template.source == "index":
                # An index region lists OTHER documents; the engine pre-renders it
                # (it needs all docs, not this surface) and passes it in.
                body = req.index_body
            else:
                body = expected_region(drift.region_id, req.surface, template)
            if body is not None:
                return BackendResult(
                    verdict=Verdict.FIX,
                    cause=(
                        f"managed region {drift.region_id!r} is regenerable from "
                        "the current code surface"
                    ),
                    fix=ProposedFix(
                        region_id=drift.region_id,
                        new_region_body=body,
                        new_doc_text=None,
                        rationale=(
                            "regenerated the managed region from the code surface "
                            "(the single source of truth)"
                        ),
                    ),
                )
            # B-06: a no-renderer `llm` REGION (rule-1 `body` was None) is authored
            # PROSE, not mechanically rendered. Author a deterministic, idempotent
            # body from the surface (K2/K10) — the offline stand-in for what an LLM
            # would write, exactly as rule 3 is for whole-doc.
            if req.region_mode is RegionMode.LLM:
                prose = _authored_prose(req.surface)
                return BackendResult(
                    verdict=Verdict.FIX,
                    cause=(
                        f"llm-authored region {drift.region_id!r} has no mechanical "
                        "renderer; authoring its prose from the current code surface"
                    ),
                    fix=ProposedFix(
                        region_id=drift.region_id,
                        new_region_body=prose,
                        new_doc_text=None,
                        rationale=(
                            "authored the region's prose from the code surface "
                            "(the single source of truth); deterministic stand-in "
                            "for an LLM"
                        ),
                    ),
                )

        if (
            req.drift.audience is Audience.USER_GUIDE
            and drift.kind is DriftKind.HASH
            and any(m in drift.detail.lower() for m in _INVALIDATE_MARKERS)
        ):
            return BackendResult(
                verdict=Verdict.INVALIDATE,
                cause=(
                    "the change is to a comment/docstring/private symbol and does "
                    "not affect this user-guide's public surface"
                ),
                fix=None,
            )

        if drift.kind is DriftKind.HASH:
            corrected = render_corrected(
                req.doc_text,
                req.surface,
                req.region_templates,
                include_body=req.fingerprint_body_tier,
            )
            return BackendResult(
                verdict=Verdict.FIX,
                cause=(
                    "the code surface changed; regenerating the document's managed "
                    "regions and fingerprint to match it"
                ),
                fix=ProposedFix(
                    region_id=None,
                    new_region_body=None,
                    new_doc_text=corrected,
                    rationale=(
                        "rewrote the document from the current code surface (the "
                        "single source of truth); regions + fingerprint refreshed"
                    ),
                ),
            )

        return BackendResult(
            verdict=Verdict.ESCALATE,
            cause=(
                "the mock backend cannot remediate this drift automatically; "
                "a human reviewer is needed"
            ),
            fix=None,
        )


# ---------------------------------------------------------------------------
# ClaudeCodeBackend (headless claude -p — K4, subprocess injected)
# ---------------------------------------------------------------------------
def _default_process_runner(argv: list[str], stdin: str, timeout_s: int) -> str:
    """Run ``argv`` via stdlib :mod:`subprocess`, returning stdout (K0).

    Never exercised in tests (K4): tests inject a fake runner. The single real
    ``subprocess.run`` call is isolated here so it is the only uncovered line.
    """
    result = subprocess.run(  # noqa: S603 (argv from trusted config, no shell)
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if result.returncode != 0:
        raise BackendError(
            f"claude-code exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout


class ClaudeCodeBackend:
    """Headless ``claude -p`` backend with an INJECTED process runner (K4).

    ``propose`` builds the prompt, assembles argv (default ``["claude", "-p",
    <prompt>]``, or substitutes the prompt into a configured ``command`` template
    — a ``"{prompt}"`` token is replaced in place, else the prompt is appended),
    then calls ``runner(argv, prompt, timeout_s)`` and feeds stdout to
    :func:`parse_backend_json`. The runner is injected so tests never spawn a
    process; when ``runner is None`` a stdlib runner is built lazily (K0). Any
    runner failure/timeout is wrapped in :class:`BackendError` (K8).
    """

    def __init__(
        self,
        *,
        command: tuple[str, ...] | None = None,
        model: str | None = None,
        timeout_s: int = 120,
        runner: ProcessRunner | None = None,
    ) -> None:
        self._command = command
        self._model = model
        self._timeout_s = timeout_s
        self._runner = runner

    def _build_argv(self, prompt: str) -> list[str]:
        if self._command is None:
            argv = ["claude", "-p"]
            if self._model:
                argv += ["--model", self._model]
            argv.append(prompt)
            return argv

        if _PROMPT_TOKEN in self._command:
            return [part.replace(_PROMPT_TOKEN, prompt) for part in self._command]
        return [*self._command, prompt]

    def propose(self, req: FixRequest) -> BackendResult:
        prompt = build_prompt(req)
        argv = self._build_argv(prompt)
        runner = self._runner
        if runner is None:
            runner = self._runner = _default_process_runner
        try:
            stdout = runner(argv, prompt, self._timeout_s)
        except BackendError:
            raise
        except Exception as exc:  # noqa: BLE001 - any runner failure is loud (K8)
            raise BackendError(f"claude-code backend failed: {exc}") from exc
        return parse_backend_json(stdout)


# ---------------------------------------------------------------------------
# ApiBackend (Anthropic Messages API — K4, client injected)
# ---------------------------------------------------------------------------
def _anthropic_messages_call(
    model: str, prompt: str, timeout: int, api_key: str
) -> str:
    """Call the Anthropic Messages API via stdlib :mod:`urllib`, returning text.

    Never exercised in tests (K4): tests inject a fake client or stub this leaf.
    The single real ``urlopen`` call is isolated here so it is the only
    uncovered line (no ``anthropic`` package, K0).
    """
    import urllib.request  # pragma: no cover

    body = json.dumps(  # pragma: no cover
        {
            "model": model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(  # pragma: no cover
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # pragma: no cover
        payload = json.loads(resp.read().decode("utf-8"))
    blocks = payload.get("content", [])  # pragma: no cover
    return "".join(  # pragma: no cover
        b.get("text", "") for b in blocks if isinstance(b, dict)
    )


class ApiBackend:
    """Anthropic Messages API backend with an INJECTED client (K4).

    ``propose`` builds the prompt, calls ``client(model=..., prompt=...,
    timeout=...)`` (returning the model's text), then feeds it to
    :func:`parse_backend_json`. The client is injected so tests never hit the
    network; when ``client is None`` a stdlib :mod:`urllib` client is built
    lazily (no ``anthropic`` package, K0) — building it requires the API key in
    ``api_key_env`` or a :class:`BackendError` is raised (K8).
    """

    def __init__(
        self,
        *,
        model: str,
        api_key_env: str = "ANTHROPIC_API_KEY",
        timeout_s: int = 120,
        client: ApiClient | None = None,
    ) -> None:
        self._model = model
        self._api_key_env = api_key_env
        self._timeout_s = timeout_s
        self._client = client

    def _build_default_client(self) -> ApiClient:
        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            raise BackendError(
                f"api backend needs an API key in ${self._api_key_env} (unset or empty)"
            )

        def client(*, model: str, prompt: str, timeout: int) -> str:
            return _anthropic_messages_call(model, prompt, timeout, api_key)

        return client

    def propose(self, req: FixRequest) -> BackendResult:
        prompt = build_prompt(req)
        client = self._client
        if client is None:
            client = self._client = self._build_default_client()
        try:
            text = client(model=self._model, prompt=prompt, timeout=self._timeout_s)
        except BackendError:
            raise
        except Exception as exc:  # noqa: BLE001 - any client failure is loud (K8)
            raise BackendError(f"api backend failed: {exc}") from exc
        return parse_backend_json(text)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def make_backend(cfg: BackendConfig, agent: AgentConfig | None = None) -> Backend:
    """Resolve a :class:`BackendConfig` to a backend (one factory, K4).

    ``kind == "agent"`` builds the LangGraph remediation workflow from ``agent``
    (the :class:`AgentConfig`, defaulted when ``None``); it lives behind a lazy
    import so the optional ``langgraph`` dependency is only required when the
    agent backend is actually selected (K0).
    """
    if cfg.kind == "mock":
        return MockBackend()
    if cfg.kind == "claude-code":
        return ClaudeCodeBackend(
            command=cfg.command, model=cfg.model, timeout_s=cfg.timeout_s
        )
    if cfg.kind == "api":
        return ApiBackend(
            model=cfg.model or _DEFAULT_API_MODEL, timeout_s=cfg.timeout_s
        )
    if cfg.kind == "agent":
        try:
            from .agent import make_agent_backend
        except ImportError as exc:  # pragma: no cover - only without the extra
            raise BackendError(
                "the 'agent' backend needs the optional 'langgraph' dependency; "
                "install code-doc-monitor[agent]"
            ) from exc
        return make_agent_backend(agent or AgentConfig())
    raise BackendError(f"unknown backend kind {cfg.kind!r}")  # pragma: no cover
