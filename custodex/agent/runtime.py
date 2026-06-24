"""Agent runtime drivers — the model-talking leaf, chosen by config (K4, K8).

A :data:`Driver` is the single side-effecting boundary of the LangGraph agent: a
``Callable[[str], str]`` that takes the composed prompt and returns the model's
raw text. :func:`resolve_driver` turns an :class:`~custodex.config.AgentConfig`
into one of three drivers — the headless Claude Code CLI (default), the Anthropic
API, or any OpenAI-compatible local endpoint — so pointing the agent at a
different model host is a config edit, never a code change (the SPEC's "agent is
using the Claude Code CLI … or an API … or a local model").

Every real syscall is reused from / kept as a single ``# pragma: no cover`` leaf
so tests inject a fake driver and never spawn a process or open a socket (K4).
Any driver failure is wrapped in a typed :class:`BackendError` (K8).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from ..backends import (
    _PROMPT_TOKEN,
    _anthropic_messages_call,
    _default_process_runner,
)
from ..config import AgentConfig
from ..errors import BackendError

__all__ = ["Driver", "resolve_driver"]

#: A prompt -> raw model reply callable (the agent's only side-effecting leaf).
Driver = Callable[[str], str]

#: Default Anthropic model when an api/local driver configures none.
_DEFAULT_MODEL = "claude-sonnet-4-20250514"


def _claude_code_argv(cfg: AgentConfig, prompt: str) -> list[str]:
    """Build the ``claude -p`` argv (or substitute a configured command)."""
    if cfg.command is None:
        argv = ["claude", "-p"]
        if cfg.model:
            argv += ["--model", cfg.model]
        argv.append(prompt)
        return argv
    if _PROMPT_TOKEN in cfg.command:
        return [part.replace(_PROMPT_TOKEN, prompt) for part in cfg.command]
    return [*cfg.command, prompt]


def _openai_chat_call(
    base_url: str, model: str, prompt: str, timeout: int, api_key: str | None
) -> str:  # pragma: no cover - real socket; tests inject a fake driver (K4)
    """POST to an OpenAI-compatible ``/chat/completions`` endpoint via urllib.

    The single real network leaf for the ``local`` driver (no ``openai`` package,
    K0). Never exercised in tests; isolated so it is the only uncovered line.
    """
    import urllib.request

    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}]}
    ).encode("utf-8")
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))
    choices = payload.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "")


def _wrap(driver: Driver, label: str) -> Driver:
    """Wrap a driver so any failure becomes a typed :class:`BackendError` (K8)."""

    def wrapped(prompt: str) -> str:
        try:
            return driver(prompt)
        except BackendError:
            raise
        except Exception as exc:  # noqa: BLE001 - any runtime failure is loud (K8)
            raise BackendError(f"agent {label} driver failed: {exc}") from exc

    return wrapped


def resolve_driver(cfg: AgentConfig) -> Driver:
    """Resolve an :class:`AgentConfig` to a :data:`Driver` (one factory, K4).

    Raises :class:`BackendError` for a misconfigured driver — a ``local`` driver
    with no ``base_url``, or an ``api``/``local`` driver whose key env is unset
    when a key is required (K8).
    """
    if cfg.driver == "claude-code":

        def claude_code(prompt: str) -> str:
            return _default_process_runner(
                _claude_code_argv(cfg, prompt), prompt, cfg.timeout_s
            )

        return _wrap(claude_code, "claude-code")

    if cfg.driver == "api":
        raw_key = os.environ.get(cfg.api_key_env)
        if not raw_key:
            raise BackendError(
                f"agent api driver needs an API key in ${cfg.api_key_env} "
                "(unset or empty)"
            )
        api_key: str = raw_key
        model = cfg.model or _DEFAULT_MODEL

        def api(prompt: str) -> str:
            return _anthropic_messages_call(model, prompt, cfg.timeout_s, api_key)

        return _wrap(api, "api")

    if cfg.driver == "local":
        if not cfg.base_url:
            raise BackendError(
                "agent local driver needs a base_url (e.g. http://localhost:11434/v1)"
            )
        base_url = cfg.base_url
        local_model = cfg.model or "local-model"
        local_key = os.environ.get(cfg.api_key_env)

        def local(prompt: str) -> str:
            return _openai_chat_call(
                base_url, local_model, prompt, cfg.timeout_s, local_key
            )

        return _wrap(local, "local")

    raise BackendError(f"unknown agent driver {cfg.driver!r}")  # pragma: no cover
