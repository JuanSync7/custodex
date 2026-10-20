"""The executed-CI harness: run a shipped CI template's job for real, offline.

S1-CITPL (CI-HARNESS). A template test must prove what the job DOES, not what
its YAML says. This module turns one GitLab job (or a whole GitLab pipeline) or
one GitHub Actions job into real ``bash`` processes in a fresh ``git`` checkout of
a fixture repo, with:

* an environment that is an **allowlist** — never ``os.environ`` (a developer's
  ``CI_*`` / token / LLM-key variables cannot leak into a job, T75/M50);
* the platform's **predefined variables** modelled explicitly (only the ones
  listed in :data:`_GITLAB_KNOWN_UNSET` / :data:`_GITHUB_KNOWN_UNSET` may be
  referenced while unset);
* ``cdx`` bound to ``tests/_cdx_ci_shim.py`` (this checkout, a fake forge, a
  central recorder, and network/LLM tripwires);
* loud stubs (exit :data:`STUB_EXIT`) for tools that would reach out
  (``curl``, ``pip``, ``apt-get``, ...) and for the server launchers;
* the install lines (and ONLY those, :data:`INSTALL_LINE`) dropped, since the
  shim already provides ``cdx``.

Everything outside the modelled subset raises :class:`NotModelled` — an
unknown rule syntax, job key, provider variable, GitHub expression or action is
refused loudly, never guessed or silently skipped (K8). A test that hits
``NotModelled`` must either extend this model (with a self-test here) or stop
claiming coverage for that construct.
"""

from __future__ import annotations

import ast
import copy
import heapq
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests import _cdx_ci_shim as shim
from tests import _fake_forge as forge
from tests._gitrepo import GitRepo, repo_from_tree
from tests._repo import REPO_ROOT

__all__ = [
    "DEFAULT_GITLAB_GIT_DEPTH",
    "FAKE_NOW_DEFAULT",
    "GITHUB_PLATFORM_SECRET",
    "INSTALL_LINE",
    "LOUD_STUBS",
    "SERVER_LAUNCHERS",
    "STUB_EXIT",
    "ZERO_SHA",
    "AdopterRepo",
    "CiJob",
    "CiPipelineRun",
    "CiRun",
    "CiStep",
    "NotModelled",
    "build_adopter_repo",
    "clear_ci_env",
    "copy_adopter_repo",
    "copy_repo",
    "github_job",
    "gitlab_job",
    "gitlab_pipeline",
    "install_lines",
    "job_env_names",
    "product_env_names",
    "provider_token_env",
    "run_ci_job",
    "run_ci_pipeline",
]


class NotModelled(Exception):  # noqa: N818 (a refusal, not an error condition)
    """The template uses something the harness does not model (refused, K8)."""


# --------------------------------------------------------------------------- #
# constants (test-model constants, not product configuration)
# --------------------------------------------------------------------------- #

ZERO_SHA = "0" * 40
FAKE_NOW_DEFAULT = "2026-01-02T03:04:05+00:00"
STUB_EXIT = 97
LOUD_STUBS = (
    "curl",
    "wget",
    "apt-get",
    "apt",
    "apk",
    "pip",
    "pip3",
    "npm",
    "npx",
    "uv",
)
SERVER_LAUNCHERS = ("cdx-server", "cdx-mcp", "cdmon-server")
#: GitLab's shallow-clone default when a job sets no ``GIT_DEPTH``.
DEFAULT_GITLAB_GIT_DEPTH = 20
#: actions/checkout's ``fetch-depth`` default.
DEFAULT_GITHUB_FETCH_DEPTH = 1
#: The secret GitHub Actions provides to every workflow run (platform-owned).
GITHUB_PLATFORM_SECRET = "GITHUB_TOKEN"  # noqa: S105 (a name, not a secret)

#: The ONLY lines the harness drops: venv creation, a pip install, and the
#: ``command -v git || { ...install git... }`` bootstrap.
INSTALL_LINE = re.compile(
    r"^\s*(python -m venv \.venv|(\.venv/bin/)?pip install\b"
    r"|command -v git >/dev/null 2>&1 \|\| \{)"
)
_GIT_BOOTSTRAP = re.compile(r"^\s*command -v git >/dev/null 2>&1 \|\| \{ .*\}\s*$")
#: Anything that would make an install line do MORE than install.
_CHAIN = re.compile(r"[;|`]|\$\(|&&|(?<![<>])&(?!>)")
_MENTIONS_CDX = re.compile(r"\b(cdx|cdmon)\b")
#: Install / invocation forms the shim cannot stand in for.
_BROAD_INSTALL = re.compile(
    r"(^|[\s;&|(])(pip3\s+install\b|python3?\s+-m\s+pip\b|uv\s+pip\b|pipx\b"
    r"|python3?\s+-m\s+(custodex|cdmon)\b)"
)
_PROVIDER_REF = re.compile(r"\$(?:\{[#!]?)?((?:CI|GITLAB|GITHUB|RUNNER)_[A-Za-z0-9_]*)")
_GH_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")

_HARNESS_NAMES = ("PATH", "HOME", "LANG", "TMPDIR")
_HARNESS_PREFIX = "CDX_FAKE_"
_HARNESS_ONLY_FAKE = (shim.ENV_FORGE_STATE, shim.ENV_HTTP_LOG, shim.ENV_CENTRAL_LOG)

_GITLAB_KNOWN_UNSET = {
    "push": frozenset(
        {
            "CI_MERGE_REQUEST_IID",
            "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME",
            "CI_MERGE_REQUEST_TARGET_BRANCH_NAME",
            "CI_COMMIT_TAG",
            "CI_EXTERNAL_PULL_REQUEST_IID",
        }
    ),
    "merge_request_event": frozenset({"CI_COMMIT_BRANCH", "CI_COMMIT_TAG"}),
}
_GITHUB_KNOWN_UNSET = frozenset({"GITHUB_HEAD_REF", "GITHUB_BASE_REF"})
# GitHub owns every GITHUB_* / RUNNER_* name: a workflow `env:` cannot override one.
_GITHUB_RESERVED_PREFIXES = ("GITHUB_", "RUNNER_")

_GITLAB_TOP_KEYS = frozenset(
    {"stages", "variables", "include", "default", "image", "cache"}
)
_GITLAB_REFUSED_TOP = frozenset(
    {"workflow", "services", "before_script", "after_script"}
)
_GITLAB_JOB_KEYS = frozenset(
    {
        "stage",
        "script",
        "before_script",
        "variables",
        "rules",
        "when",
        "allow_failure",
        "needs",
        "image",
        "services",
        "cache",
        "tags",
    }
)
_GITLAB_RULE_KEYS = frozenset({"if", "when", "allow_failure"})
_GITLAB_WHEN = frozenset({"on_success", "manual", "always", "never"})
_GITLAB_DEFAULT_STAGES = ("build", "test", "deploy")

_GH_WORKFLOW_KEYS = frozenset(
    {"name", "on", "env", "jobs", "permissions", "concurrency"}
)
_GH_JOB_KEYS = frozenset(
    {
        "runs-on",
        "if",
        "env",
        "steps",
        "concurrency",
        "permissions",
        "timeout-minutes",
        "name",
    }
)
_GH_STEP_KEYS = frozenset(
    {"name", "id", "uses", "with", "run", "env", "if", "shell", "timeout-minutes"}
)
_GH_ALWAYS = frozenset({"always()", "${{ always() }}"})

_FAKE_GITLAB_TOKEN = "fake-gitlab-token"  # noqa: S105 (a fake, not a secret)
_FAKE_GITHUB_TOKEN = "fake-github-token"  # noqa: S105


def provider_token_env(provider: str) -> str:
    """The token env name the product's ``from_env`` reads (derived, never typed)."""
    from custodex.pr import GitHubTransport, GitLabTransport

    from_env: dict[str, Callable[..., object]] = {
        "gitlab": GitLabTransport.from_env,
        "github": GitHubTransport.from_env,
    }
    default = inspect.signature(from_env[provider]).parameters["token_env"].default
    assert isinstance(default, str) and default
    return default


# --------------------------------------------------------------------------- #
# the model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CiStep:
    """One executable unit: a GitLab job script, or one GitHub step."""

    kind: str  # script | run | checkout | setup-python | cache-restore | cache-save
    name: str
    run: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    always: bool = False
    with_: Mapping[str, Any] = field(default_factory=dict)
    fetch_depth: int | None = None
    shell: tuple[str, ...] = ()
    skipped_install: tuple[str, ...] = ()


@dataclass(frozen=True)
class CiJob:
    """A job resolved against one pipeline context, ready to run."""

    provider: str
    name: str
    head: str
    branch: str
    steps: tuple[CiStep, ...]
    predefined: Mapping[str, str]
    stage: str = ""
    when: str = "on_success"
    allow_failure: bool = False
    preds: tuple[str, ...] = ()
    uses_needs: bool = False
    #: GitLab: (name, value, expand) in precedence order (later wins).
    variables: tuple[tuple[str, str, bool], ...] = ()
    #: GitLab project variables (never expanded).
    project: Mapping[str, str] = field(default_factory=dict)
    #: GitLab protected secrets (default branch only, never expanded).
    protected: Mapping[str, str] = field(default_factory=dict)
    #: GitHub repository secrets (reachable only via ``${{ secrets.X }}``).
    secrets: Mapping[str, str] = field(default_factory=dict)
    #: GitHub workflow + job env (evaluated).
    env: Mapping[str, str] = field(default_factory=dict)
    git_depth: int = 0  # 0 = full history
    services: tuple[Any, ...] = ()
    selected: bool = True


@dataclass(frozen=True)
class CiRun:
    """What one executed job did."""

    exit_code: int
    stdout: str
    stderr: str
    requests: tuple[dict, ...]
    central: tuple[dict, ...]
    workspace: Path
    run_dir: Path
    steps: tuple[tuple[str, str], ...]
    cache_events: tuple[dict, ...]


@dataclass(frozen=True)
class CiPipelineRun:
    """What one executed GitLab pipeline did."""

    status: dict[str, str]
    runs: dict[str, CiRun]
    order: tuple[str, ...]
    allowed_failures: tuple[str, ...]


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #


def _load(template: Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(template, Path):
        data = yaml.safe_load(template.read_text(encoding="utf-8"))
    else:
        data = copy.deepcopy(dict(template))
    if not isinstance(data, dict):
        raise NotModelled(f"template is not a mapping: {type(data).__name__}")
    return data


def _lines(value: Any, where: str) -> list[str]:
    """A GitLab script value as a flat list of items (anchors nest one level)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise NotModelled(f"{where}: script must be a string or list")
    out: list[str] = []
    for item in value:
        if isinstance(item, list):
            out.extend(_lines(item, where))
        elif isinstance(item, str):
            out.append(item)
        else:
            raise NotModelled(f"{where}: script item {item!r} is not a string")
    return out


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _filter_install(items: Sequence[str], where: str) -> tuple[str, tuple[str, ...]]:
    """Drop the install lines from ``items``; refuse anything ambiguous.

    Returns the remaining script (items joined by newlines) and the dropped
    lines. Each physical line is examined, so an install line inside a ``|``
    block is handled the same as a list item.
    """
    kept_items: list[str] = []
    skipped: list[str] = []
    for item in items:
        kept_lines: list[str] = []
        prev_continued = False
        for line in item.split("\n"):
            if _is_comment(line):
                kept_lines.append(line)
                prev_continued = False
                continue
            if _BROAD_INSTALL.search(line):
                raise NotModelled(
                    f"{where}: {line.strip()!r} — only `python -m venv .venv`, "
                    "`[.venv/bin/]pip install` and the git bootstrap are modelled"
                )
            continued = line.rstrip().endswith("\\")
            if INSTALL_LINE.match(line):
                if continued or prev_continued:
                    raise NotModelled(f"{where}: continued install line {line!r}")
                if _MENTIONS_CDX.search(line):
                    raise NotModelled(
                        f"{where}: install line names cdx/cdmon: {line!r}"
                    )
                stripped = line.strip()
                if stripped.startswith("command -v git"):
                    if not _GIT_BOOTSTRAP.match(line):
                        raise NotModelled(
                            f"{where}: unrecognised git bootstrap {line!r}"
                        )
                elif _CHAIN.search(line):
                    raise NotModelled(
                        f"{where}: install line does more than install: {line!r}"
                    )
                skipped.append(stripped)
            else:
                kept_lines.append(line)
            prev_continued = continued
        if any(x.strip() for x in kept_lines):
            kept_items.append("\n".join(kept_lines))
    return "\n".join(kept_items), tuple(skipped)


def _scan_provider_refs(
    texts: Iterable[str], allowed: frozenset[str], where: str
) -> None:
    for text in texts:
        for line in text.split("\n"):
            if _is_comment(line):
                continue
            for match in _PROVIDER_REF.finditer(line):
                name = match.group(1)
                if name not in allowed:
                    raise NotModelled(
                        f"{where}: ${name} is not modelled by the executed-CI harness"
                    )


def _check_owned(names: Iterable[str], where: str) -> None:
    for name in names:
        if name in _HARNESS_NAMES or name.startswith(_HARNESS_PREFIX):
            raise NotModelled(f"{where}: harness owns ${name}")


def _yaml_scalar(value: Any, where: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise NotModelled(f"{where}: variable value {value!r} is not a scalar")


def _yaml_vars(raw: Any, where: str) -> list[tuple[str, str, bool]]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise NotModelled(f"{where}: variables must be a mapping")
    out = []
    for name, value in raw.items():
        if isinstance(value, dict):
            extra = set(value) - {"value", "description", "expand", "options"}
            if extra:
                raise NotModelled(f"{where}: variable {name} keys {sorted(extra)}")
            expand = value.get("expand", True)
            if not isinstance(expand, bool):
                raise NotModelled(f"{where}: variable {name} expand must be a bool")
            out.append((str(name), _yaml_scalar(value.get("value", ""), where), expand))
        else:
            out.append((str(name), _yaml_scalar(value, where), True))
    _check_owned((n for n, _, _ in out), where)
    return out


_VAR_TOKEN = re.compile(
    r"\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)|\$\{"
)


def _expand(entries: Mapping[str, tuple[str, bool]]) -> dict[str, str]:
    """GitLab variable expansion to a fixpoint (``$X``, ``${X}``, ``$$``).

    A cycle, or a ``${`` form other than ``${NAME}``, is refused. An undefined
    non-provider name expands to the empty string (provider names were already
    checked by :func:`_scan_provider_refs`).
    """
    done: dict[str, str] = {}

    def resolve(name: str, stack: tuple[str, ...]) -> str:
        if name in done:
            return done[name]
        if name in stack:
            raise NotModelled(f"variable cycle: {' -> '.join((*stack, name))}")
        value, expand = entries[name]
        if not expand:
            done[name] = value
            return value

        def sub(match: re.Match[str]) -> str:
            token = match.group(0)
            if token == "$$":
                return "$"
            ref = match.group(1) or match.group(2)
            if ref is None:
                raise NotModelled(
                    f"unmodelled ${{...}} form in variable {name}: {value!r}"
                )
            if ref not in entries:
                return ""
            return resolve(ref, (*stack, name))

        out = _VAR_TOKEN.sub(sub, value)
        done[name] = out
        return out

    return {name: resolve(name, ()) for name in entries}


def _slug(ref: str) -> str:
    return re.sub(r"[^a-z0-9]", "-", ref.lower())[:63].strip("-")


# --------------------------------------------------------------------------- #
# GitLab: rules
# --------------------------------------------------------------------------- #

_RULE_TOKEN = re.compile(
    r"\s*(?:(==|!=|&&)|\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?|\"([^\"]*)\"|'([^']*)'|(null)\b)"
)


def _rule_tokens(cond: str) -> list[tuple[str, str | None]]:
    pos = 0
    out: list[tuple[str, str | None]] = []
    while pos < len(cond):
        if cond[pos:].strip() == "":
            break
        match = _RULE_TOKEN.match(cond, pos)
        if match is None or match.end() == pos:
            raise NotModelled(f"rules: unmodelled syntax at {cond[pos:]!r} in {cond!r}")
        op, var, dq, sq, null = match.groups()
        if op:
            out.append(("op", op))
        elif var:
            out.append(("var", var))
        elif dq is not None or sq is not None:
            out.append(("lit", dq if dq is not None else sq))
        elif null:
            out.append(("null", None))
        pos = match.end()
    if not out:
        raise NotModelled(f"rules: empty condition {cond!r}")
    return out


def _eval_rule(cond: str, ctx: Mapping[str, str]) -> bool:
    tokens = _rule_tokens(cond)
    terms: list[list[tuple[str, str | None]]] = [[]]
    for tok in tokens:
        if tok == ("op", "&&"):
            terms.append([])
        else:
            terms[-1].append(tok)

    def value(tok: tuple[str, str | None]) -> str | None:
        kind, text = tok
        if kind == "var":
            assert text is not None
            return ctx.get(text)
        if kind == "lit":
            return text
        if kind == "null":
            return None
        raise NotModelled(f"rules: operator where an operand belongs in {cond!r}")

    result = True
    for term in terms:
        if len(term) == 1:
            if term[0][0] != "var":
                raise NotModelled(f"rules: a bare literal is not a condition: {cond!r}")
            val = value(term[0])
            ok = bool(val)
        elif len(term) == 3 and term[1][0] == "op" and term[1][1] in ("==", "!="):
            left, right = value(term[0]), value(term[2])
            ok = (left == right) if term[1][1] == "==" else (left != right)
        else:
            raise NotModelled(f"rules: unmodelled expression shape {cond!r}")
        result = result and ok
    return result


# --------------------------------------------------------------------------- #
# GitLab: pipeline
# --------------------------------------------------------------------------- #


def _gitlab_predefined(
    *,
    source: str,
    branch: str | None,
    ref: str,
    default_branch: str,
    head: str,
    before: str | None,
) -> dict[str, str]:
    pre = {
        "CI": "true",
        "GITLAB_CI": "true",
        "CI_COMMIT_SHA": head,
        "CI_COMMIT_BEFORE_SHA": before or ZERO_SHA,
        "CI_COMMIT_REF_NAME": ref,
        "CI_COMMIT_REF_SLUG": _slug(ref),
        "CI_DEFAULT_BRANCH": default_branch,
        "CI_PROJECT_ID": forge.GITLAB_PROJECT_ID,
        "CI_PROJECT_PATH": forge.GITLAB_PROJECT_PATH,
        "CI_PROJECT_URL": forge.GITLAB_PROJECT_URL,
        "CI_API_V4_URL": forge.GITLAB_API_URL,
        "CI_SERVER_URL": forge.GITLAB_SERVER_URL,
        "CI_PIPELINE_SOURCE": source,
    }
    if branch is not None:
        pre["CI_COMMIT_BRANCH"] = branch
    return pre


def gitlab_pipeline(
    template: Path | Mapping[str, Any],
    *,
    source: str,
    branch: str | None,
    default_branch: str,
    head: str,
    before: str | None,
    variables: Mapping[str, str] | None = None,
    secrets: Mapping[str, str] | None = None,
    ref: str | None = None,
) -> tuple[CiJob, ...]:
    """Evaluate a GitLab template for one pipeline: the selected jobs, run order."""
    if source == "push":
        if branch is None:
            raise ValueError("a push pipeline needs branch=")
        if ref is not None and ref != branch:
            raise ValueError(
                f"push pipeline: ref={ref!r} differs from branch={branch!r}"
            )
        ref_name = branch
    elif source == "merge_request_event":
        if branch is not None:
            raise ValueError("merge_request_event: branch= must be None (pass ref=)")
        if ref is None:
            raise ValueError("merge_request_event needs ref=")
        if before is not None:
            raise ValueError("merge_request_event: before= must be None")
        ref_name = ref
    else:
        raise NotModelled(
            f"pipeline source {source!r} is not modelled (push, merge_request_event)"
        )

    data = _load(template)
    _check_gitlab_top(data)
    stages = data.get("stages", list(_GITLAB_DEFAULT_STAGES))
    if not isinstance(stages, list) or not all(isinstance(s, str) for s in stages):
        raise NotModelled("stages must be a list of names")
    all_stages = [".pre", *stages, ".post"]
    global_vars = _yaml_vars(data.get("variables"), "variables")

    project = dict(variables or {})
    _check_owned(project, "project variables")
    on_default = branch is not None and branch == default_branch
    if secrets is None:
        secrets = {provider_token_env("gitlab"): _FAKE_GITLAB_TOKEN}
    _check_owned(secrets, "protected variables")
    protected = dict(secrets) if on_default else {}

    base_pre = _gitlab_predefined(
        source=source,
        branch=branch,
        ref=ref_name,
        default_branch=default_branch,
        head=head,
        before=before,
    )
    job_names = [
        k for k in data if k not in _GITLAB_TOP_KEYS and not str(k).startswith(".")
    ]
    selected: list[dict[str, Any]] = []
    for index, name in enumerate(job_names):
        body = data[name]
        where = f"job {name!r}"
        if not isinstance(body, dict):
            raise NotModelled(f"{where}: not a mapping")
        extra = set(body) - _GITLAB_JOB_KEYS
        if extra:
            raise NotModelled(f"{where}: keys {sorted(extra)} are not modelled")
        stage = body.get("stage", "test")
        if stage not in all_stages:
            raise NotModelled(f"{where}: stage {stage!r} is not declared")
        job_vars = _yaml_vars(body.get("variables"), where)
        pre = {**base_pre, "CI_JOB_NAME": name, "CI_JOB_STAGE": stage}
        declared = (
            {n for n, _, _ in (*global_vars, *job_vars)} | set(project) | set(protected)
        )
        allowed = frozenset(
            set(pre) | {"CI_PROJECT_DIR"} | declared | _GITLAB_KNOWN_UNSET[source]
        )
        items = [
            *_lines(body.get("before_script"), where),
            *_lines(body.get("script"), where),
        ]
        if not _lines(body.get("script"), where):
            raise NotModelled(f"{where}: no script")
        script, skipped = _filter_install(items, where)
        rules = body.get("rules")
        rule_texts = [str(r.get("if", "")) for r in rules or [] if isinstance(r, dict)]
        _scan_provider_refs(
            [script, *(v for _, v, _ in (*global_vars, *job_vars)), *rule_texts],
            allowed,
            where,
        )
        entries: dict[str, tuple[str, bool]] = {
            **{k: (v, False) for k, v in pre.items()},
            "CI_PROJECT_DIR": ("<workspace>", False),
        }
        for n, v, e in (*global_vars, *job_vars):
            entries[n] = (v, e)
        for n, v in {**project, **protected}.items():
            entries[n] = (v, False)
        ctx = _expand(entries)
        when, allow_failure = _gitlab_when(body, rules, ctx, where)
        if when == "never":
            continue
        depth_raw = ctx.get("GIT_DEPTH")
        for unmodelled in ("GIT_STRATEGY", "GIT_CLONE_PATH"):
            if unmodelled in ctx:
                raise NotModelled(f"{where}: ${unmodelled} is not modelled")
        try:
            depth = DEFAULT_GITLAB_GIT_DEPTH if depth_raw is None else int(depth_raw)
        except ValueError as exc:
            raise NotModelled(f"{where}: GIT_DEPTH {depth_raw!r}") from exc
        services = body.get("services") or []
        selected.append(
            {
                "index": index,
                "name": name,
                "stage": stage,
                "stage_index": all_stages.index(stage),
                "when": when,
                "allow_failure": allow_failure,
                "needs": body.get("needs"),
                "job": CiJob(
                    provider="gitlab",
                    name=name,
                    head=head,
                    branch=ref_name,
                    steps=(
                        CiStep(
                            kind="script",
                            name="script",
                            run=script,
                            skipped_install=skipped,
                        ),
                    ),
                    predefined=pre,
                    stage=stage,
                    when=when,
                    allow_failure=allow_failure,
                    variables=tuple((*global_vars, *job_vars)),
                    project=project,
                    protected=protected,
                    git_depth=depth,
                    services=tuple(services)
                    if isinstance(services, list)
                    else (services,),
                ),
            }
        )
    return _order_gitlab(selected)


def _check_gitlab_top(data: Mapping[str, Any]) -> None:
    for key in _GITLAB_REFUSED_TOP:
        if key in data:
            raise NotModelled(f"top-level {key!r} is not modelled")
    for key in data:
        if str(key).startswith("."):
            continue
        body = data[key]
        if key in _GITLAB_TOP_KEYS:
            continue
        if isinstance(body, dict):
            for bad in (
                "extends",
                "only",
                "except",
                "after_script",
                "retry",
                "parallel",
                "trigger",
                "dependencies",
                "id_tokens",
                "secrets",
            ):
                if bad in body:
                    raise NotModelled(f"job {key!r}: {bad!r} is not modelled")
    include = data.get("include")
    if include is not None:
        items = include if isinstance(include, list) else [include]
        for item in items:
            if not (isinstance(item, dict) and set(item) == {"template"}):
                raise NotModelled(
                    f"include {item!r}: only `template:` entries are modelled"
                )
    default = data.get("default")
    if default is not None and (
        not isinstance(default, dict) or set(default) - {"image"}
    ):
        raise NotModelled("default: only `image` is modelled")


def _gitlab_when(
    body: Mapping[str, Any], rules: Any, ctx: Mapping[str, str], where: str
) -> tuple[str, bool]:
    job_af = body.get("allow_failure")
    if job_af is not None and not isinstance(job_af, bool):
        raise NotModelled(f"{where}: allow_failure must be a bool")
    if rules is None:
        when = body.get("when", "on_success")
        if when not in _GITLAB_WHEN:
            raise NotModelled(f"{where}: when {when!r}")
        if when == "never":
            # GitLab refuses the config: `never` is legal only inside rules.
            raise NotModelled(f"{where}: job-level when 'never' is only valid in rules")
        if job_af is not None:
            return when, job_af
        return when, when == "manual"
    if "when" in body:
        raise NotModelled(f"{where}: job-level `when` with `rules` is not modelled")
    if not isinstance(rules, list):
        raise NotModelled(f"{where}: rules must be a list")
    for rule in rules:
        if not isinstance(rule, dict):
            raise NotModelled(f"{where}: rule {rule!r}")
        extra = set(rule) - _GITLAB_RULE_KEYS
        if extra:
            raise NotModelled(f"{where}: rule keys {sorted(extra)} are not modelled")
        cond = rule.get("if")
        if cond is not None and not isinstance(cond, str):
            raise NotModelled(f"{where}: rule if {cond!r}")
    for rule in rules:
        cond = rule.get("if")
        if cond is not None and not _eval_rule(cond, ctx):
            continue
        when = rule.get("when", "on_success")
        if when not in _GITLAB_WHEN:
            raise NotModelled(f"{where}: rule when {when!r}")
        rule_af = rule.get("allow_failure")
        if rule_af is not None and not isinstance(rule_af, bool):
            raise NotModelled(f"{where}: rule allow_failure must be a bool")
        if rule_af is not None:
            return when, rule_af
        if job_af is not None:
            return when, job_af
        return when, False
    return "never", False


def _order_gitlab(selected: list[dict[str, Any]]) -> tuple[CiJob, ...]:
    names = {s["name"] for s in selected}
    preds: dict[str, tuple[str, ...]] = {}
    for s in selected:
        needs = s["needs"]
        if needs is None:
            preds[s["name"]] = tuple(
                o["name"] for o in selected if o["stage_index"] < s["stage_index"]
            )
            continue
        if not isinstance(needs, list):
            raise NotModelled(f"job {s['name']!r}: needs must be a list")
        got: list[str] = []
        for need in needs:
            if isinstance(need, str):
                target, optional = need, False
            elif isinstance(need, dict) and set(need) <= {
                "job",
                "optional",
                "artifacts",
            }:
                target, optional = need["job"], bool(need.get("optional", False))
            else:
                raise NotModelled(f"job {s['name']!r}: needs entry {need!r}")
            if target not in names:
                if optional:
                    continue
                raise NotModelled(
                    f"job {s['name']!r} needs {target!r}, "
                    "which is absent from the pipeline"
                )
            got.append(target)
        preds[s["name"]] = tuple(got)
    # Kahn's algorithm, ties broken by (stage, template order).
    by_name = {s["name"]: s for s in selected}
    indeg = {n: len(p) for n, p in preds.items()}
    succ: dict[str, list[str]] = {n: [] for n in preds}
    for n, ps in preds.items():
        for p in ps:
            succ[p].append(n)
    heap = [
        (by_name[n]["stage_index"], by_name[n]["index"], n)
        for n, d in indeg.items()
        if d == 0
    ]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        _, _, n = heapq.heappop(heap)
        order.append(n)
        for m in succ[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                heapq.heappush(
                    heap, (by_name[m]["stage_index"], by_name[m]["index"], m)
                )
    if len(order) != len(selected):
        raise NotModelled("needs: dependency cycle")
    out = []
    for n in order:
        s = by_name[n]
        job: CiJob = s["job"]
        out.append(
            CiJob(
                **{
                    **job.__dict__,
                    "preds": preds[n],
                    "uses_needs": s["needs"] is not None,
                }
            )
        )
    return tuple(out)


def gitlab_job(
    template: Path | Mapping[str, Any],
    job: str,
    *,
    head: str,
    branch: str | None,
    before: str | None,
    variables: Mapping[str, str] | None = None,
    secrets: Mapping[str, str] | None = None,
    default_branch: str = "main",
    ref: str | None = None,
    source: str = "push",
) -> CiJob:
    """One GitLab job, as the pipeline for this context would run it."""
    jobs = gitlab_pipeline(
        template,
        source=source,
        branch=branch,
        default_branch=default_branch,
        head=head,
        before=before,
        variables=variables,
        secrets=secrets,
        ref=ref,
    )
    for candidate in jobs:
        if candidate.name == job:
            return candidate
    raise ValueError(
        f"job {job!r} is not in this pipeline (rules excluded it, or no such job)"
    )


# --------------------------------------------------------------------------- #
# GitHub Actions
# --------------------------------------------------------------------------- #


def _gh_eval_text(
    text: str, *, secrets: Mapping[str, str], before: str | None, where: str
) -> str:
    def sub(match: re.Match[str]) -> str:
        expr = match.group(1)
        if expr.startswith("secrets.") and re.fullmatch(
            r"secrets\.[A-Za-z_][A-Za-z0-9_]*", expr
        ):
            return secrets.get(expr[len("secrets.") :], "")
        if expr == "github.event.before":
            return before or ZERO_SHA
        raise NotModelled(f"{where}: unmodelled GitHub expression ${{{{ {expr} }}}}")

    return _GH_EXPR.sub(sub, text)


_GH_IF_TOKEN = re.compile(
    r"\s*(?:(==|!=|&&|\(|\)|,)|'((?:[^']|'')*)'|([A-Za-z_][A-Za-z0-9_.\-]*))"
)


def _gh_job_if(expr: str, ctx: Mapping[str, str]) -> bool:
    """The modelled subset of a GitHub job-level ``if:`` expression."""
    text = expr.strip()
    m = _GH_EXPR.fullmatch(text)
    if m:
        text = m.group(1)
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        if not text[pos:].strip():
            break
        match = _GH_IF_TOKEN.match(text, pos)
        if match is None or match.end() == pos:
            raise NotModelled(f"job if: unmodelled syntax at {text[pos:]!r}")
        op, lit, ident = match.groups()
        if op:
            tokens.append(("op", op))
        elif lit is not None:
            tokens.append(("lit", lit.replace("''", "'")))
        else:
            tokens.append(("id", ident))
        pos = match.end()

    i = 0

    def peek() -> tuple[str, str] | None:
        return tokens[i] if i < len(tokens) else None

    def take() -> tuple[str, str]:
        nonlocal i
        if i >= len(tokens):
            raise NotModelled(f"job if: truncated expression {text!r}")
        tok = tokens[i]
        i += 1
        return tok

    def operand() -> str:
        kind, val = take()
        if kind == "lit":
            return val
        if kind == "id" and val == "format" and peek() == ("op", "("):
            take()
            fmt_kind, fmt = take()
            if fmt_kind != "lit":
                raise NotModelled("job if: format() needs a literal format string")
            args: list[str] = []
            while peek() == ("op", ","):
                take()
                args.append(operand())
            if take() != ("op", ")"):
                raise NotModelled("job if: malformed format()")
            for n, arg in enumerate(args):
                fmt = fmt.replace("{" + str(n) + "}", arg)
            return fmt
        if kind == "id":
            if val not in ctx:
                raise NotModelled(f"job if: context {val!r} is not modelled")
            return ctx[val]
        raise NotModelled(f"job if: unexpected {val!r}")

    def comparison() -> bool:
        left = operand()
        nxt = peek()
        if nxt in (("op", "=="), ("op", "!=")):
            take()
            right = operand()
            same = (
                left.lower() == right.lower()
            )  # GitHub compares strings case-insensitively
            return same if nxt == ("op", "==") else not same
        return bool(left)

    result = comparison()
    while peek() == ("op", "&&"):
        take()
        result = comparison() and result
    if i != len(tokens):
        raise NotModelled(f"job if: unmodelled syntax in {text!r}")
    return result


def github_job(
    template: Path | Mapping[str, Any],
    job: str,
    *,
    head: str,
    branch: str,
    repository: str = forge.GITHUB_REPOSITORY,
    secrets: Mapping[str, str] | None = None,
    before: str | None = None,
    event_name: str = "push",
    default_branch: str = "main",
) -> CiJob:
    """One GitHub Actions job for a push of ``head`` to ``branch``."""
    if event_name != "push":
        raise NotModelled(f"event {event_name!r} is not modelled (push only)")
    data = _load(template)
    extra = set(map(str, data)) - _GH_WORKFLOW_KEYS - {"True"}
    if extra:
        raise NotModelled(f"workflow keys {sorted(extra)} are not modelled")
    raw: dict[Any, Any] = data
    on = raw.get("on", raw.get(True))  # YAML 1.1 reads a bare `on` as True
    triggers = [on] if isinstance(on, str) else list(on or [])
    if "push" not in triggers:
        raise NotModelled("workflow is not triggered by push")
    push = on.get("push") if isinstance(on, dict) else None
    if push not in (None, {}):
        # branches / paths / tags filters decide whether the job runs at all;
        # none is modelled, so a filtered push is refused, never ignored (K8).
        keys = sorted(push) if isinstance(push, dict) else push
        raise NotModelled(f"push filter {keys!r} is not modelled (bare push only)")
    jobs = data.get("jobs") or {}
    if job not in jobs:
        raise ValueError(f"no job {job!r} in workflow")
    body = jobs[job]
    where = f"job {job!r}"
    extra = set(body) - _GH_JOB_KEYS
    if extra:
        raise NotModelled(f"{where}: keys {sorted(extra)} are not modelled")
    # Actions always provides the platform token; adopter secrets (the product's
    # CDMON_* tokens included) exist only when the test declares them.
    secrets = {GITHUB_PLATFORM_SECRET: _FAKE_GITHUB_TOKEN, **(secrets or {})}
    owner = repository.split("/")[0]
    pre = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "GITHUB_SHA": head,
        "GITHUB_REF": f"refs/heads/{branch}",
        "GITHUB_REF_NAME": branch,
        "GITHUB_REF_TYPE": "branch",
        "GITHUB_REPOSITORY": repository,
        "GITHUB_REPOSITORY_OWNER": owner,
        "GITHUB_SERVER_URL": forge.GITHUB_SERVER_URL,
        "GITHUB_API_URL": forge.GITHUB_API_URL,
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_JOB": job,
    }
    selected = True
    if "if" in body:
        ctx = {
            "github.event_name": event_name,
            "github.ref": f"refs/heads/{branch}",
            "github.ref_name": branch,
            "github.event.repository.default_branch": default_branch,
        }
        selected = _gh_job_if(str(body["if"]), ctx)

    def env_block(raw: Any, label: str) -> dict[str, str]:
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise NotModelled(f"{label}: env must be a mapping")
        _check_owned(raw, label)
        for key in map(str, raw):
            # GitHub keeps its own value for these; letting the template's
            # value win would model a run that never happens.
            if key in pre or key.startswith(_GITHUB_RESERVED_PREFIXES):
                raise NotModelled(
                    f"{label}: GitHub sets ${key}; a template cannot override it"
                )
        return {
            str(k): _gh_eval_text(
                _yaml_scalar(v, label), secrets=secrets, before=before, where=label
            )
            for k, v in raw.items()
        }

    job_env = {
        **env_block(data.get("env"), "workflow env"),
        **env_block(body.get("env"), where),
    }
    steps: list[CiStep] = []
    texts: list[str] = [str(v) for v in (data.get("env") or {}).values()]
    texts += [str(v) for v in (body.get("env") or {}).values()]
    for n, raw in enumerate(body.get("steps") or []):
        label = f"{where} step {n}"
        if not isinstance(raw, dict):
            raise NotModelled(f"{label}: not a mapping")
        extra = set(raw) - _GH_STEP_KEYS
        if extra:
            raise NotModelled(f"{label}: keys {sorted(extra)} are not modelled")
        cond = raw.get("if")
        if cond is not None and str(cond).strip() not in _GH_ALWAYS:
            raise NotModelled(f"{label}: step if {cond!r} is not modelled")
        always = cond is not None
        name = str(raw.get("name") or raw.get("uses") or f"run {n}")
        with_ = dict(raw.get("with") or {})
        if "uses" in raw and "run" in raw:
            raise NotModelled(f"{label}: uses + run together")
        if "uses" in raw:
            uses = str(raw["uses"])
            if uses.startswith("actions/checkout@"):
                unknown = sorted(set(with_) - {"fetch-depth"})
                if unknown:
                    raise NotModelled(f"{label}: checkout inputs {unknown}")
                raw_depth = with_.get("fetch-depth", DEFAULT_GITHUB_FETCH_DEPTH)
                if isinstance(raw_depth, bool) or not re.fullmatch(
                    r"\d+", str(raw_depth)
                ):
                    raise NotModelled(f"{label}: fetch-depth {raw_depth!r}")
                depth = int(raw_depth)
                steps.append(
                    CiStep(
                        kind="checkout",
                        name=name,
                        always=always,
                        with_=with_,
                        fetch_depth=depth,
                    )
                )
            elif uses.startswith("actions/setup-python@"):
                steps.append(
                    CiStep(kind="setup-python", name=name, always=always, with_=with_)
                )
            elif uses.startswith("actions/cache/restore@"):
                steps.append(
                    CiStep(kind="cache-restore", name=name, always=always, with_=with_)
                )
            elif uses.startswith("actions/cache/save@"):
                steps.append(
                    CiStep(kind="cache-save", name=name, always=always, with_=with_)
                )
            else:
                raise NotModelled(f"{label}: action {uses!r} is not modelled")
            continue
        if "run" not in raw:
            raise NotModelled(f"{label}: neither uses nor run")
        shell_name = raw.get("shell")
        if shell_name is None:
            shell: tuple[str, ...] = ("-e", "-c")
        elif shell_name == "bash":
            shell = ("--noprofile", "--norc", "-eo", "pipefail", "-c")
        else:
            raise NotModelled(f"{label}: shell {shell_name!r} is not modelled")
        run_text = str(raw["run"])
        texts.append(run_text)
        texts += [str(v) for v in (raw.get("env") or {}).values()]
        script, skipped = _filter_install([run_text], label)
        script = _gh_eval_text(script, secrets=secrets, before=before, where=label)
        steps.append(
            CiStep(
                kind="run",
                name=name,
                run=script,
                always=always,
                shell=shell,
                env=env_block(raw.get("env"), label),
                skipped_install=skipped,
            )
        )
    declared = set(job_env) | {k for s in steps for k in s.env}
    allowed = frozenset(
        set(pre) | {"GITHUB_WORKSPACE"} | declared | _GITHUB_KNOWN_UNSET
    )
    _scan_provider_refs(texts, allowed, where)
    return CiJob(
        provider="github",
        name=job,
        head=head,
        branch=branch,
        steps=tuple(steps),
        predefined=pre,
        secrets=secrets,
        env=job_env,
        selected=selected,
    )


# --------------------------------------------------------------------------- #
# templates: install lines
# --------------------------------------------------------------------------- #


def install_lines(template: Path | Mapping[str, Any]) -> tuple[str, ...]:
    """Every line the harness would drop from ``template`` (all jobs/steps)."""
    data = _load(template)
    found: list[str] = []
    if "jobs" in data:
        for name, body in (data.get("jobs") or {}).items():
            for n, step in enumerate(body.get("steps") or []):
                if "run" in step:
                    _, skipped = _filter_install([str(step["run"])], f"{name} step {n}")
                    found.extend(skipped)
    else:
        for name, body in data.items():
            if (
                name in _GITLAB_TOP_KEYS
                or str(name).startswith(".")
                or not isinstance(body, dict)
            ):
                continue
            items = [
                *_lines(body.get("before_script"), name),
                *_lines(body.get("script"), name),
            ]
            _, skipped = _filter_install(items, f"job {name!r}")
            found.extend(skipped)
    return tuple(found)


# --------------------------------------------------------------------------- #
# the environment
# --------------------------------------------------------------------------- #


def job_env_names(job: CiJob) -> frozenset[str]:
    """Every env name the harness may hand ``job`` (the allowlist, T75)."""
    names = set(_HARNESS_NAMES) | {
        shim.ENV_HTTP_LOG,
        shim.ENV_CENTRAL_LOG,
        shim.ENV_NOW,
        shim.ENV_FORGE_STATE,
    }
    names |= set(job.predefined)
    if job.provider == "gitlab":
        names |= {"CI_PROJECT_DIR"} | {n for n, _, _ in job.variables}
        names |= set(job.project) | set(job.protected)
    else:
        names |= (
            {"GITHUB_WORKSPACE"} | set(job.env) | {k for s in job.steps for k in s.env}
        )
    return frozenset(names)


def _iter_custodex_sources() -> Iterable[Path]:
    yield from sorted((REPO_ROOT / "custodex").rglob("*.py"))


_PRODUCT_PREFIXES = ("CI_", "GITHUB_", "GITLAB_", "CDMON_")


def product_env_names() -> tuple[str, ...]:
    """The env names the product reads, derived by AST-scanning ``custodex/``.

    Collects string literals passed to ``os.environ.get`` / ``os.getenv`` /
    ``os.environ[...]`` with a CI / provider / ``CDMON_`` prefix, plus every
    ``*_env`` parameter's string default (the ``from_env`` token/project/api
    names, the LLM key env names).
    """
    names: set[str] = set()
    for path in _iter_custodex_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                func = ast.unparse(node.func)
                if func.endswith(("environ.get", "getenv", "environ.pop")):
                    arg = node.args[0]
                    if (
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                        and arg.value.startswith(_PRODUCT_PREFIXES)
                    ):
                        names.add(arg.value)
            elif isinstance(node, ast.Subscript) and ast.unparse(node.value).endswith(
                "environ"
            ):
                key = node.slice
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and key.value.startswith(_PRODUCT_PREFIXES)
                ):
                    names.add(key.value)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                positional = [*args.posonlyargs, *args.args]
                pairs = list(
                    zip(
                        positional[len(positional) - len(args.defaults) :],
                        args.defaults,
                        strict=True,
                    )
                )
                pairs += [
                    (a, d)
                    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True)
                    if d is not None
                ]
                for param, default in pairs:
                    if (
                        param.arg.endswith("_env")
                        and isinstance(default, ast.Constant)
                        and isinstance(default.value, str)
                        and default.value
                    ):
                        names.add(default.value)
    return tuple(sorted(names))


def clear_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset every name :func:`product_env_names` finds (the ``no_ci_env`` fixture)."""
    for name in product_env_names():
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- #
# running
# --------------------------------------------------------------------------- #

_STUB = """#!/bin/sh
echo "{name}: not modelled by the executed-CI harness (loud stub, exit {code})" >&2
exit {code}
"""


def _shim_script() -> str:
    """A ``/bin/sh`` wrapper that runs the shim with this interpreter, isolated."""
    code = (
        f"import sys; sys.path.insert(0, {json.dumps(str(REPO_ROOT))}); "
        "from tests._cdx_ci_shim import main; raise SystemExit(main())"
    )
    return f"#!/bin/sh\nexec '{sys.executable}' -I -c '{code}' \"$@\"\n"


def _write_exec(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _host_path() -> str:
    return os.environ.get("PATH", os.defpath)


def _prepare_tmp(tmp: Path, strip_git: bool) -> str:
    """Build ``tmp/bin`` (shims + stubs) and return the job's PATH."""
    bin_dir = tmp / "bin"
    for prog in ("cdx", "cdmon"):
        _write_exec(bin_dir / prog, _shim_script())
    for name in (*LOUD_STUBS, *SERVER_LAUNCHERS):
        _write_exec(bin_dir / name, _STUB.format(name=name, code=STUB_EXIT))
    (tmp / "home").mkdir(parents=True, exist_ok=True)
    (tmp / "tmpdir").mkdir(parents=True, exist_ok=True)
    if not strip_git:
        return f"{bin_dir}:{_host_path()}"
    farm = tmp / "nogit-bin"
    if farm.exists():
        shutil.rmtree(farm)
    farm.mkdir()
    for directory in _host_path().split(":"):
        if not directory or not os.path.isdir(directory):
            continue
        for entry in sorted(os.listdir(directory)):
            if (
                entry.startswith("git")
                or (farm / entry).exists()
                or os.path.islink(farm / entry)
            ):
                continue
            src = os.path.join(directory, entry)
            if os.path.isfile(src) and os.access(src, os.X_OK):
                os.symlink(src, farm / entry)
    return f"{bin_dir}:{farm}"


def _git_env(tmp: Path) -> dict[str, str]:
    return {
        "PATH": _host_path(),
        "HOME": str(tmp / "home"),
        "LANG": "C.UTF-8",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def _git(cwd: Path, env: Mapping[str, str], *args: str) -> None:
    subprocess.run(  # noqa: S603 (fixed git verbs)
        ["git", *args],
        cwd=str(cwd),
        env=dict(env),
        check=True,
        capture_output=True,
        text=True,
    )


def _checkout(
    src: Path, ws: Path, tmp: Path, *, head: str, branch: str, depth: int, detach: bool
) -> None:
    env = _git_env(tmp)
    ws.mkdir(parents=True, exist_ok=True)
    _git(ws, env, "init", "-q")
    _git(ws, env, "remote", "add", "origin", f"file://{src}")
    fetch = [
        "fetch",
        "-q",
        "--no-tags",
        "--upload-pack=git -c uploadpack.allowAnySHA1InWant=true upload-pack",
    ]
    if depth > 0:
        fetch.append(f"--depth={depth}")
    _git(ws, env, *fetch, "origin", head)
    _git(ws, env, "update-ref", f"refs/remotes/origin/{branch}", head)
    if detach:
        _git(ws, env, "checkout", "-q", "--detach", head)
    else:
        _git(ws, env, "checkout", "-q", "-B", branch, head)


def _install_workspace_shims(ws: Path) -> None:
    for prog in ("cdx", "cdmon"):
        _write_exec(ws / ".venv" / "bin" / prog, _shim_script())
    exclude = ws / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as fh:
        fh.write(".venv/\n")


def _next_run_dir(tmp: Path) -> Path:
    runs = tmp / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    n = 1 + max((int(p.name) for p in runs.iterdir() if p.name.isdigit()), default=0)
    run_dir = runs / f"{n:03d}"
    run_dir.mkdir()
    return run_dir


def _read_jsonl(path: Path) -> tuple[dict, ...]:
    if not path.is_file():
        return ()
    return tuple(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    )


def _bash() -> str:
    found = shutil.which("bash", path=_host_path())
    if found is None:
        raise RuntimeError("bash is required to run CI jobs")
    return found


def run_ci_job(
    job: CiJob,
    repo: GitRepo | Path,
    *,
    tmp: Path,
    forge_state: Path | None,
    strip_git: bool = False,
    fake_env: Mapping[str, str | None] | None = None,
    workspace: Path | None = None,
) -> CiRun:
    """Run ``job`` against a fresh checkout of ``repo`` and report what it did."""
    for key in fake_env or {}:
        if not key.startswith(_HARNESS_PREFIX):
            raise ValueError(f"fake_env accepts CDX_FAKE_* keys only, got {key!r}")
        if key in _HARNESS_ONLY_FAKE:
            raise ValueError(
                f"harness owns ${key} (set it through run_ci_job's arguments)"
            )
    if not job.selected:
        raise ValueError(
            f"job {job.name!r} is not selected for this event (its `if:` is false)"
        )
    if job.services:
        raise NotModelled(f"job {job.name!r}: services are not modelled")
    src = repo.path if isinstance(repo, GitRepo) else Path(repo)
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    path_value = _prepare_tmp(tmp, strip_git)
    run_dir = _next_run_dir(tmp)
    http_log = run_dir / "http.jsonl"
    central_log = run_dir / "central.jsonl"
    http_log.touch()
    central_log.touch()
    harness: dict[str, str] = {
        "PATH": path_value,
        "HOME": str(tmp / "home"),
        "LANG": "C.UTF-8",
        "TMPDIR": str(tmp / "tmpdir"),
        shim.ENV_HTTP_LOG: str(http_log),
        shim.ENV_CENTRAL_LOG: str(central_log),
        shim.ENV_NOW: FAKE_NOW_DEFAULT,
    }
    if forge_state is not None:
        harness[shim.ENV_FORGE_STATE] = str(Path(forge_state).resolve())
    for key, value in (fake_env or {}).items():
        if value is None:
            harness.pop(key, None)
        else:
            harness[key] = value

    fresh = workspace is None
    ws = run_dir / "ws" if workspace is None else Path(workspace)
    out: list[str] = []
    err: list[str] = []
    statuses: list[tuple[str, str]] = []
    cache_events: list[dict] = []
    exit_code = 0
    bash = _bash()

    def execute(argv: Sequence[str], env: Mapping[str, str]) -> int:
        proc = subprocess.run(  # noqa: S603 (bash running the template's own script)
            [bash, *argv],
            cwd=str(ws),
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
        )
        out.append(proc.stdout)
        err.append(proc.stderr)
        return proc.returncode

    if job.provider == "gitlab":
        if fresh:
            _checkout(
                src,
                ws,
                tmp,
                head=job.head,
                branch=job.branch,
                depth=job.git_depth,
                detach=True,
            )
            _install_workspace_shims(ws)
        entries: dict[str, tuple[str, bool]] = {
            **{k: (v, False) for k, v in job.predefined.items()},
            "CI_PROJECT_DIR": (str(ws), False),
        }
        for n, v, e in job.variables:
            entries[n] = (v, e)
        for n, v in {**job.project, **job.protected}.items():
            entries[n] = (v, False)
        env = {**_expand(entries), **harness}
        (step,) = job.steps
        code = execute(["-eo", "pipefail", "-c", step.run or ""], env)
        statuses.append((step.name, "success" if code == 0 else "failed"))
        exit_code = code
    else:
        ws.mkdir(parents=True, exist_ok=True)
        base = {**job.predefined, "GITHUB_WORKSPACE": str(ws), **job.env}
        failed = False
        for step in job.steps:
            if failed and not step.always:
                statuses.append((step.name, "skipped"))
                continue
            if step.kind == "checkout":
                _checkout(
                    src,
                    ws,
                    tmp,
                    head=job.head,
                    branch=job.branch,
                    depth=step.fetch_depth or 0,
                    detach=False,
                )
                statuses.append((step.name, "success"))
            elif step.kind in ("setup-python",):
                statuses.append((step.name, "success"))
            elif step.kind in ("cache-restore", "cache-save"):
                action = "restore" if step.kind == "cache-restore" else "save"
                cache_events.append(
                    {
                        "action": action,
                        "hit": False if action == "restore" else None,
                        "key": step.with_.get("key"),
                        "path": step.with_.get("path"),
                    }
                )
                statuses.append((step.name, "success"))
            else:
                env = {**base, **step.env, **harness}
                code = execute([*step.shell, step.run or ""], env)
                statuses.append((step.name, "success" if code == 0 else "failed"))
                if code != 0 and not failed:
                    failed = True
                    exit_code = code
    return CiRun(
        exit_code=exit_code,
        stdout="".join(out),
        stderr="".join(err),
        requests=_read_jsonl(http_log),
        central=_read_jsonl(central_log),
        workspace=ws,
        run_dir=run_dir,
        steps=tuple(statuses),
        cache_events=tuple(cache_events),
    )


def run_ci_pipeline(
    jobs: Sequence[CiJob],
    repo: GitRepo | Path,
    *,
    tmp: Path,
    forge_state: Path | None,
    strip_git: bool = False,
    fake_env: Mapping[str, str | None] | None = None,
) -> CiPipelineRun:
    """Run a GitLab pipeline's jobs in order, propagating skip / block status."""
    status: dict[str, str] = {}
    runs: dict[str, CiRun] = {}
    by_name = {j.name: j for j in jobs}
    allowed: list[str] = []
    for job in jobs:
        verdict = _pipeline_verdict(job, by_name, status)
        if verdict is None and job.when == "manual":
            verdict = "manual"
        if verdict is not None:
            status[job.name] = verdict
            continue
        run = run_ci_job(
            job,
            repo,
            tmp=tmp,
            forge_state=forge_state,
            strip_git=strip_git,
            fake_env=fake_env,
        )
        runs[job.name] = run
        status[job.name] = "success" if run.exit_code == 0 else "failed"
        if run.exit_code != 0 and job.allow_failure:
            allowed.append(job.name)
    return CiPipelineRun(
        status=status,
        runs=runs,
        order=tuple(j.name for j in jobs),
        allowed_failures=tuple(allowed),
    )


def _pipeline_verdict(
    job: CiJob, by_name: Mapping[str, CiJob], status: Mapping[str, str]
) -> str | None:
    """None = run the job; otherwise the status it gets without running.

    Mirrors GitLab's ``Ci::Status::Composite`` over the job's predecessors (its
    ``needs:`` for a DAG job, every earlier-stage job otherwise), then the
    statuses its ``when:`` accepts:

    * a predecessor that never completes — ``blocked`` (waiting) or a blocking
      manual (``allow_failure: false``) — leaves the job waiting: ``blocked``,
      whatever its ``when:``. For a DAG job, a skipped or ignored need (an
      optional manual) outranks this: the DAG composite checks it first.
    * ``when: always`` runs once every predecessor has completed.
    * a DAG job requires ``success``: a skipped need, an ignored need (optional
      manual) or a hard failure (``allow_failure: false``) skips it.
    * a stage job accepts ``success`` or ``skipped``: only a hard failure in an
      earlier stage skips it.
    """
    preds = [(by_name[p], status[p]) for p in job.preds]

    def waiting(pred: CiJob, s: str) -> bool:
        return s == "blocked" or (s == "manual" and not pred.allow_failure)

    def hard_failure(pred: CiJob, s: str) -> bool:
        return s == "failed" and not pred.allow_failure

    if job.uses_needs:
        dag_skipped = any(
            s == "skipped" or (s == "manual" and pred.allow_failure)
            for pred, s in preds
        )
        if dag_skipped:
            return None if job.when == "always" else "skipped"
    if any(waiting(pred, s) for pred, s in preds):
        return "blocked"
    if job.when == "always":
        return None
    if any(hard_failure(pred, s) for pred, s in preds):
        return "skipped"
    return None


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AdopterRepo:
    """examples/external-repo as a git repo with commits A, B, C, B' (B' reverts B)."""

    repo: GitRepo
    A: str  # noqa: N815 (commit labels from the spec)
    B: str  # noqa: N815
    C: str  # noqa: N815
    B_prime: str  # noqa: N815


_EXAMPLE = REPO_ROOT / "examples" / "external-repo"
_B_OLD = "def widget_area(width: int, height: int) -> int:"
_B_NEW = "def widget_area(width: int, height: int, depth: int = 1) -> int:"
_C_OLD = "def make_widget(label: str, *, width: int = DEFAULT_WIDTH) -> str:"
_C_NEW = (
    "def make_widget(label: str, *, width: int = DEFAULT_WIDTH, "
    "padding: int = 0) -> str:"
)


def _replace_once(repo: GitRepo, rel: str, old: str, new: str) -> None:
    path = repo.path / rel
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise AssertionError(f"{rel}: expected exactly one {old!r} (fixture rotted)")
    path.write_text(text.replace(old, new), encoding="utf-8")
    repo.add(rel)


def build_adopter_repo(dest: Path) -> AdopterRepo:
    """Build the adopter fixture at ``dest`` (A clean; B/C code changes; B' revert)."""
    repo = repo_from_tree(_EXAMPLE, dest)
    a = repo.commit_files(
        "chore: ignore runtime state", {".gitignore": ".cdmon/\n.venv/\n"}
    )
    _replace_once(repo, "src/widget.py", _B_OLD, _B_NEW)
    b = repo.commit("feat: widget depth")
    _replace_once(repo, "src/widget.py", _C_OLD, _C_NEW)
    c = repo.commit("feat: widget padding")
    repo.git("revert", "--no-edit", b)
    return AdopterRepo(repo=repo, A=a, B=b, C=c, B_prime=repo.head())


def copy_repo(src: GitRepo, dest: Path) -> GitRepo:
    """A byte-identical copy of ``src`` (working tree + ``.git``) at ``dest``."""
    shutil.copytree(src.path, dest, symlinks=True)
    return GitRepo(path=dest, default_branch=src.default_branch)


def copy_adopter_repo(src: AdopterRepo, dest: Path) -> AdopterRepo:
    return AdopterRepo(
        repo=copy_repo(src.repo, dest), A=src.A, B=src.B, C=src.C, B_prime=src.B_prime
    )
