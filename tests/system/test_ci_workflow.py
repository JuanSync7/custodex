"""The GitHub pull-request gate (``.github/workflows/ci.yml``) runs every gate (X-GATE).

Every PR to the default branch must run the full CLAUDE.md gate, so that a red
gate blocks the merge once branch protection requires the checks (``gate``,
``floor`` while the floor is below the gate, ``frontend``).

**How the pin works: exact equality, not membership.** The test builds the WHOLE
expected workflow from the repo's own sources and requires the committed
``ci.yml`` to equal it, key for key and string for string. So the file is a
closed set: an extra step (a ``$GITHUB_ENV``/``$GITHUB_PATH`` injection, a
``touch .coveragerc``, an ``rm -rf tests``), an extra key (``env``,
``container``, ``needs``, ``continue-on-error``, a checkout ``ref``), a widened
trigger or permission, or a re-quoted command all fail. Changing the gate is
always a two-file edit (ci.yml plus this pin) that review sees.

**Nothing is hard-coded that the repo already states.** Each value is read from
its single source:

* the gate interpreter: the GitLab gate's ``default.image`` (``.gitlab-ci.yml``);
* the floor interpreter: ``[project] requires-python`` (``pyproject.toml``, read
  as TOML); when the floor is raised to the gate's version the floor job folds
  into the gate job, and every check below holds in both shapes; a floor above
  the gate (a gate job that could not install the package) is loud;
* the Python install and the gate commands: the GitLab gate jobs' single
  ``.venv/bin/pip install`` line (both jobs must agree) and their scripts after
  it, so the two CIs cannot drift; plus a ``cdx check`` for every shipped config
  (tracked ``config/cdmon/index.yaml`` or ``cdmon.yaml``/``.json`` outside the
  top-level ``tests/``) and ``cdx index --check``;
* the action refs, the Node setup, the npm install and the frontend directory:
  ``deploy-pages.yml`` (checkout, setup-node, its one ``npm ci`` step) and the
  adopter template ``templates/ci/github-actions.adopter.yml`` (setup-python);
* the frontend gate commands: the ``build`` and ``test:run`` scripts of that
  directory's ``package.json``, one step per ``&&`` part.

**How the YAML is read.** PyYAML's YAML 1.1 turns ``on``/``On``/``yes`` into the
boolean ``True`` and silently keeps the last of two duplicate keys. The loader
here changes exactly two things: only the lowercase ``true``/``false`` are
booleans (``True``/``TRUE``/``yes`` stay strings), and a duplicate key (by
constructed value, so ``3.10:`` and ``3.1:`` collide) raises. It still resolves
YAML 1.1 integers and floats (``010`` is 8, ``1:20`` is 80, an unquoted ``3.10``
is 3.1), which GitHub's YAML 1.2 reads differently. That is safe only because
every leaf of the expected workflow is a string or ``True`` (pinned below): any
place where this loader and GitHub disagree loads as a number, a string or a
key the expected workflow does not hold, and is rejected. The loader is
stricter than GitHub, never looser.

**Not covered (by design).** This pins the workflow file. Committed repository
content that changes what a gate command does (a ``conftest.py``, a
``pytest.toml``/``.coveragerc``/``.npmrc``, an edited ``fail_under``, a deleted
test, a ``package.json`` script body) is ordinary code under review, like any
other change a PR makes; no pin on the workflow can close that class, and this
one does not claim to.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml

from custodex.cli import app
from tests._repo import REPO_ROOT

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - the 3.10 floor: pytest itself depends on tomli there
    import tomli as tomllib  # type: ignore[import-not-found, unused-ignore]

# --- where each value comes from ---------------------------------------------

_CI = Path(".github") / "workflows" / "ci.yml"
_GITLAB = Path(".gitlab-ci.yml")
_PYPROJECT = Path("pyproject.toml")
_DEPLOY_PAGES = Path(".github") / "workflows" / "deploy-pages.yml"
_ADOPTER_GITHUB = Path("templates") / "ci" / "github-actions.adopter.yml"
_PACKAGE_JSON = "package.json"

# The GitLab jobs that make up its blocking gate (docs:heal and the live/pg jobs
# are manual or scheduled, so they are not gates).
_GITLAB_GATE_JOBS = ("tests:offline", "docs:gate")
# The GitLab scripts run tools out of a venv; GitHub runs them from setup-python,
# so `.venv/bin/<tool>` becomes `<tool>` and `.venv/bin/pip` becomes `python -m pip`.
_GITLAB_VENV_BIN = ".venv/bin/"
_GITHUB_PIP = "python -m pip"

# npm's own install verbs: the deploy-pages step running one of them is the
# frontend install (its run line and working-directory are read from there).
_NPM_INSTALL_VERBS = (("npm", "ci"), ("npm", "install"))
# The package.json scripts that make up the frontend gate (deploy-pages runs
# `build`; `test:run` is the non-watch vitest run).
_FRONTEND_GATE_SCRIPTS = ("build", "test:run")
# Shell syntax a gate script part may not carry: each `&&` part becomes its own
# step, so anything that changes control flow or the environment is refused.
_SHELL_SYNTAX = re.compile(r"[|;&$<>`()\\\n]")

# The branch PRs gate into (CLAUDE.md: "Branch off main").
_DEFAULT_BRANCH = "main"
_RUNNER = "ubuntu-latest"

# Every step after the install carries this guard: it still runs after an
# earlier gate step went red (so one push shows every red gate; the job stays
# failed), but never after a failed install or a cancelled run.
_GUARD = "${{ !cancelled() && steps.install.outcome == 'success' }}"

# The floor job runs the plain suite: coverage is graded once, in `gate`.
_FLOOR_TEST = "pytest"
# `cdx index --check` guards config/cdmon/index.yaml's units list; the GitLab
# gate does not run it, GitHub does.
_EXTRA_GATES_AFTER_CHECKS = ("cdx index --check",)


# --- a loader that reads YAML (stricter than) the way GitHub does --------------


class _WorkflowLoader(yaml.SafeLoader):
    """SafeLoader with only lowercase ``true``/``false`` as booleans and no
    duplicate keys (compared by constructed value). See the module docstring
    for why the YAML 1.1 numbers it still resolves can only fail closed."""

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)  # type: ignore[arg-type]


_BOOL_TAG = "tag:yaml.org,2002:bool"
_WorkflowLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != _BOOL_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_WorkflowLoader.add_implicit_resolver(
    _BOOL_TAG, re.compile(r"^(?:true|false)$"), list("tf")
)


def _load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_WorkflowLoader)  # noqa: S506 - SafeLoader subclass


def _load(path: Path) -> Any:
    return _load_yaml(path.read_text(encoding="utf-8"))


# --- reading the sources -------------------------------------------------------


@dataclass(frozen=True)
class _Sources:
    gate_python: str
    floor_python: str
    py_install: str
    gitlab_gate: tuple[str, ...]
    configs: tuple[str, ...]
    checkout: str
    setup_python: str
    setup_node: str
    node_with: dict[str, Any]
    frontend_dir: str
    npm_install: str
    frontend_gates: tuple[str, ...]


def _gate_python(gitlab: dict[str, Any]) -> str:
    image = str(gitlab.get("default", {}).get("image", ""))
    m = re.fullmatch(r"python:(\d+\.\d+)(?:-[\w.-]+)?", image)
    if m is None:
        raise ValueError(f"{_GITLAB}: default.image {image!r} is not python:X.Y[-tag]")
    return m.group(1)


def _version(x_y: str) -> tuple[int, int]:
    major, minor = x_y.split(".")
    return int(major), int(minor)


def _floor_python(pyproject_text: str) -> str:
    """``[project] requires-python``, which must be a bare ``>=X.Y`` lower bound."""
    try:
        data = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{_PYPROJECT}: not valid TOML ({exc})") from exc
    project = data.get("project")
    spec = project.get("requires-python") if isinstance(project, dict) else None
    if not isinstance(spec, str):
        raise ValueError(f"{_PYPROJECT}: no [project] requires-python string")
    m = re.fullmatch(r">=\s*(\d+\.\d+)", spec.strip())
    if m is None:
        raise ValueError(f"{_PYPROJECT}: requires-python {spec!r} is not >=X.Y")
    return m.group(1)


def _is_pip_install(line: str) -> bool:
    return {"pip", "install"} <= {Path(t).name for t in shlex.split(line)}


def _gitlab_gate(gitlab: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    """The GitLab gate jobs' shared install (as a GitHub command) and their
    commands after it, venv prefix removed."""
    installs: list[str] = []
    out: list[str] = []
    for job_name in _GITLAB_GATE_JOBS:
        job = gitlab.get(job_name)
        if not isinstance(job, dict) or not isinstance(job.get("script"), list):
            raise ValueError(f"{_GITLAB}: gate job {job_name!r} has no script list")
        script = [str(line).strip() for line in job["script"]]
        at = [i for i, line in enumerate(script) if _is_pip_install(line)]
        if len(at) != 1:
            raise ValueError(f"{_GITLAB}: {job_name} needs exactly one pip install")
        for line in script[at[0] :]:
            if "\n" in line:
                raise ValueError(
                    f"{_GITLAB}: {job_name} line {line!r} spans several lines; "
                    "the gate is read one command per script entry"
                )
        install = script[at[0]]
        if not install.startswith(f"{_GITLAB_VENV_BIN}pip "):
            raise ValueError(
                f"{_GITLAB}: {job_name} install {install!r} is not a "
                f"{_GITLAB_VENV_BIN}pip install"
            )
        installs.append(install)
        for line in script[at[0] + 1 :]:
            if not line.startswith(_GITLAB_VENV_BIN):
                raise ValueError(
                    f"{_GITLAB}: {job_name} gate line {line!r} is not a "
                    f"{_GITLAB_VENV_BIN}<tool> command"
                )
            out.append(line.removeprefix(_GITLAB_VENV_BIN))
    if len(set(installs)) != 1:
        raise ValueError(f"{_GITLAB}: the gate jobs install differently: {installs}")
    if not out:
        raise ValueError(f"{_GITLAB}: the gate jobs run no command")
    pip_args = installs[0].removeprefix(f"{_GITLAB_VENV_BIN}pip")
    return f"{_GITHUB_PIP}{pip_args}", tuple(out)


def _shipped_configs(root: Path) -> tuple[str, ...]:
    """Every tracked adopter config outside the top-level ``tests/`` (the suite's
    own fixtures), as a ``--config`` value. A ``tests/`` deeper down (an example
    project's own tests) is shipped content and is checked."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    configs: set[str] = set()
    for rel in filter(None, listed.split("\0")):
        p = Path(rel)
        if p.parts[0] == "tests":
            continue
        if p.name in ("cdmon.yaml", "cdmon.json"):
            configs.add(p.as_posix())
        elif p.parts[-3:] == ("config", "cdmon", "index.yaml"):
            configs.add(p.parent.as_posix())
    if not configs:
        raise ValueError(f"{root}: no shipped cdmon config is tracked")
    return tuple(sorted(configs))


def _steps(doc: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for job in doc.get("jobs", {}).values():
        yield from job.get("steps", [])


def _action_steps(doc: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [s for s in _steps(doc) if str(s.get("uses", "")).split("@")[0] == action]


def _action_ref(doc: dict[str, Any], action: str, where: Path) -> str:
    """The one ``<action>@<ref>`` a workflow uses (every step must agree)."""
    refs = sorted({str(s["uses"]) for s in _action_steps(doc, action)})
    if len(refs) != 1:
        raise ValueError(f"{where}: expected one ref for {action}, found {refs}")
    return refs[0]


def _action_with(doc: dict[str, Any], action: str, where: Path) -> dict[str, Any]:
    """The one ``with:`` every ``<action>`` step of a workflow passes."""
    withs: list[Any] = []
    for step in _action_steps(doc, action):
        if step.get("with") not in withs:
            withs.append(step.get("with"))
    if len(withs) != 1 or not isinstance(withs[0], dict):
        raise ValueError(f"{where}: expected one `with` for {action}, found {withs}")
    return dict(withs[0])


def _npm_install(deploy: dict[str, Any]) -> tuple[str, str]:
    """deploy-pages' one npm install step: (its working-directory, its run)."""
    hits = [
        s
        for s in _steps(deploy)
        if isinstance(s.get("run"), str)
        and tuple(shlex.split(s["run"])[:2]) in _NPM_INSTALL_VERBS
    ]
    if len(hits) != 1:
        runs = [s["run"] for s in hits]
        raise ValueError(
            f"{_DEPLOY_PAGES}: expected one npm install step, found {runs}"
        )
    workdir, run = hits[0].get("working-directory"), hits[0]["run"].strip()
    if not isinstance(workdir, str) or not workdir.strip():
        raise ValueError(
            f"{_DEPLOY_PAGES}: the npm install step has no working-directory"
        )
    if _SHELL_SYNTAX.search(run):  # the class includes the newline
        raise ValueError(
            f"{_DEPLOY_PAGES}: npm install {run!r} is not one plain command"
        )
    return workdir.strip(), run


def _frontend_gates(package_json: Path) -> tuple[str, ...]:
    """One ``npx`` step per ``&&`` part of each frontend gate script."""
    try:
        scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts")
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError(f"{package_json}: cannot read its scripts ({exc})") from exc
    out: list[str] = []
    for name in _FRONTEND_GATE_SCRIPTS:
        script = scripts.get(name) if isinstance(scripts, dict) else None
        if not isinstance(script, str):
            raise ValueError(f"{package_json}: no {name!r} script")
        for part in (p.strip() for p in script.split("&&")):
            if not part or _SHELL_SYNTAX.search(part):
                raise ValueError(
                    f"{package_json}: script {name!r} part {part!r} is not one "
                    "plain command (only `&&` chains are split into steps)"
                )
            out.append(f"npx {part}")
    return tuple(out)


def _sources(root: Path) -> _Sources:
    gitlab = _load(root / _GITLAB)
    deploy = _load(root / _DEPLOY_PAGES)
    adopter = _load(root / _ADOPTER_GITHUB)
    node_with = _action_with(deploy, "actions/setup-node", _DEPLOY_PAGES)
    if "node-version" not in node_with:
        raise ValueError(f"{_DEPLOY_PAGES}: setup-node has no node-version")
    py_install, gitlab_gate = _gitlab_gate(gitlab)
    frontend_dir, npm_install = _npm_install(deploy)
    gate_python = _gate_python(gitlab)
    floor_python = _floor_python((root / _PYPROJECT).read_text(encoding="utf-8"))
    if _version(floor_python) > _version(gate_python):
        raise ValueError(
            f"{_PYPROJECT}: requires-python floor {floor_python} is above the gate "
            f"interpreter {gate_python} ({_GITLAB} default.image): the gate job "
            "could not install the package"
        )
    return _Sources(
        gate_python=gate_python,
        floor_python=floor_python,
        py_install=py_install,
        gitlab_gate=gitlab_gate,
        configs=_shipped_configs(root),
        checkout=_action_ref(deploy, "actions/checkout", _DEPLOY_PAGES),
        setup_python=_action_ref(adopter, "actions/setup-python", _ADOPTER_GITHUB),
        setup_node=_action_ref(deploy, "actions/setup-node", _DEPLOY_PAGES),
        node_with=node_with,
        frontend_dir=frontend_dir,
        npm_install=npm_install,
        frontend_gates=_frontend_gates(root / frontend_dir / _PACKAGE_JSON),
    )


# --- the expected workflow -----------------------------------------------------


def _gate_commands(src: _Sources) -> list[str]:
    """GitLab's gate, then a check per other shipped config, then the extras."""
    cmds = list(src.gitlab_gate)
    cmds += [f"cdx check --config {c}" for c in src.configs]
    cmds += list(_EXTRA_GATES_AFTER_CHECKS)
    return list(dict.fromkeys(cmds))  # de-duplicate, keep first position


def _python_job(src: _Sources, python: str, commands: list[str]) -> dict[str, Any]:
    return {
        "runs-on": _RUNNER,
        "steps": [
            {"uses": src.checkout},
            {
                "uses": src.setup_python,
                "with": {
                    "python-version": python,
                    "cache": "pip",
                    "cache-dependency-path": str(_PYPROJECT),
                },
            },
            {"id": "install", "run": src.py_install},
            *({"if": _GUARD, "run": cmd} for cmd in commands),
        ],
    }


def _expected_workflow(src: _Sources) -> dict[str, Any]:
    gate = _python_job(src, src.gate_python, _gate_commands(src))
    jobs: dict[str, Any] = {"gate": gate}
    if src.floor_python != src.gate_python:
        jobs["floor"] = _python_job(src, src.floor_python, [_FLOOR_TEST])
    jobs["frontend"] = {
        "runs-on": _RUNNER,
        "defaults": {"run": {"working-directory": src.frontend_dir}},
        "steps": [
            {"uses": src.checkout},
            {"uses": src.setup_node, "with": dict(src.node_with)},
            {"id": "install", "run": src.npm_install},
            *({"if": _GUARD, "run": cmd} for cmd in src.frontend_gates),
        ],
    }
    return {
        "name": "ci",
        "on": {"pull_request": {"branches": [_DEFAULT_BRANCH]}},
        "permissions": {"contents": "read"},
        "concurrency": {
            "group": "ci-${{ github.ref }}",
            "cancel-in-progress": True,
        },
        "jobs": jobs,
    }


def _diff(actual: Any, expected: Any, path: str = "ci.yml") -> list[str]:
    """Every difference, type-strict (``True`` is not ``1``, ``3.1`` not ``"3.10"``)."""
    if type(actual) is not type(expected):
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    if isinstance(expected, dict):
        out: list[str] = []
        for key in sorted(set(expected) | set(actual), key=repr):
            sub = f"{path}.{key}"
            if key not in actual:
                out.append(f"{sub}: missing")
            elif key not in expected:
                out.append(f"{sub}: unexpected (the workflow is a closed set)")
            else:
                out += _diff(actual[key], expected[key], sub)
        return out
    if isinstance(expected, list):
        out = []
        for i, (a, e) in enumerate(zip(actual, expected, strict=False)):
            out += _diff(a, e, f"{path}[{i}]")
        if len(actual) != len(expected):
            out.append(f"{path}: expected {len(expected)} items, got {len(actual)}")
        return out
    if actual == expected:
        return []
    return [f"{path}: expected {expected!r}, got {actual!r}"]


def _committed() -> Any:
    return _load(REPO_ROOT / _CI)


# --- the two shapes of the workflow --------------------------------------------

# The floor is below the gate today; raising requires-python to the gate's
# version (PLAN §7.2(b)) folds `floor` into `gate`. Every check that does not
# read the committed file runs in BOTH shapes, so the fold is green end to end
# whichever shape the repo is in.
_SHAPES = ("floor-below-gate", "floor-folded")


def _shaped(src: _Sources, shape: str) -> _Sources:
    if shape == "floor-folded":
        return dataclasses.replace(src, floor_python=src.gate_python)
    if src.floor_python != src.gate_python:
        return src
    major, minor = _version(src.gate_python)
    if minor == 0:
        raise ValueError(
            f"gate {src.gate_python} is at minor 0: there is no minor below it to "
            "build the floor-below-gate shape from"
        )
    return dataclasses.replace(src, floor_python=f"{major}.{minor - 1}")


def _floor_job(doc: dict[str, Any]) -> str:
    """The job that runs the floor suite: ``floor``, or ``gate`` once folded."""
    return "floor" if "floor" in doc["jobs"] else "gate"


def _leaves(node: Any) -> Iterator[Any]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _leaves(value)
    elif isinstance(node, list):
        for item in node:
            yield from _leaves(item)
    else:
        yield node


def _not_string_or_true(doc: Any) -> list[Any]:
    """Every key or leaf that is not a string or ``True``."""
    return [x for x in _leaves(doc) if not (type(x) is str or x is True)]


def _cdx_problems(lines: Iterable[str]) -> list[str]:
    """Every ``cdx`` line naming a subcommand or a ``--option`` the CLI lacks."""
    commands = typer.main.get_command(app).commands  # type: ignore[attr-defined]
    problems: list[str] = []
    for line in lines:
        tokens = shlex.split(line)
        if tokens[:1] != ["cdx"]:
            continue
        if len(tokens) < 2 or tokens[1] not in commands:
            problems.append(f"{line}: no such cdx subcommand")
            continue
        opts = {o for p in commands[tokens[1]].params for o in p.opts}
        for tok in tokens[2:]:
            if tok.startswith("--") and tok.split("=", 1)[0] not in opts:
                problems.append(f"{line}: {tok} is not an option of cdx {tokens[1]}")
    return problems


# --- the pin -------------------------------------------------------------------


def test_ci_workflow_runs_every_gate_command() -> None:
    """ci.yml equals the workflow built from the repo's sources: one PR trigger
    to the default branch, read-only token, and the gate / floor / frontend jobs
    each running exactly their gate commands (closed set, exact strings)."""
    src = _sources(REPO_ROOT)
    assert _diff(_committed(), _expected_workflow(src)) == []


@pytest.mark.parametrize("shape", _SHAPES)
def test_the_pinned_gate_covers_the_slice_contract(shape: str) -> None:
    """The derived gate is not vacuous: it holds every command the slice names,
    every shipped config, and a floor suite: its own job while the floor is
    below the gate, the gate's own pytest once the floor is folded."""
    src = _shaped(_sources(REPO_ROOT), shape)
    expected = _expected_workflow(src)
    jobs = expected["jobs"]
    gate_runs = [s["run"] for s in jobs["gate"]["steps"] if "run" in s]
    for needle in (
        "python -m pip install -e '.[dev]'",
        "ruff format --check .",
        "ruff check .",
        "mypy custodex",
        "pytest --cov=custodex --cov-branch",
        "cdx coverage --config config/cdmon --fail-under",
        "cdx lint --config config/cdmon",
        "cdx index --check",
        "cdx wiki --check",
        "cdx trace --fail-on-gap",
    ):
        assert any(r.startswith(needle) for r in gate_runs), needle
    assert len(src.configs) >= 4
    for config in src.configs:
        assert f"cdx check --config {config}" in gate_runs
    front_runs = [s["run"] for s in jobs["frontend"]["steps"] if "run" in s]
    assert front_runs == [
        "npm ci",
        "npx astro check",
        "npx astro build",
        "npx vitest run",
    ]
    if shape == "floor-folded":
        assert list(jobs) == ["gate", "frontend"]
    else:
        assert src.floor_python != src.gate_python
        assert list(jobs) == ["gate", "floor", "frontend"]
        floor = jobs["floor"]["steps"]
        assert floor[1]["with"]["python-version"] == src.floor_python
        assert [s["run"] for s in floor[2:]] == [src.py_install, _FLOOR_TEST]


def test_every_cdx_gate_command_and_flag_exists() -> None:
    """Each ``cdx`` gate line names a real subcommand and real options, so a
    renamed command breaks this test, not CI weeks later."""
    cdx_lines = [c for c in _gate_commands(_sources(REPO_ROOT)) if c.startswith("cdx ")]
    assert len(cdx_lines) >= 5
    assert _cdx_problems(cdx_lines) == []


def test_the_cdx_command_check_can_fail() -> None:
    """Fault injection for the check above: an unknown subcommand, an unknown
    option (also in ``--opt=value`` form) and a bare ``cdx`` are each reported;
    a real line and a non-``cdx`` line are not."""
    # `mypy custodex` is skipped as a non-cdx line, not read as `cdx custodex`
    assert _cdx_problems(["cdx check --config config/cdmon", "mypy custodex"]) == []
    assert _cdx_problems(["cdx coverage --config c --fail-under=95"]) == []
    for bad in (
        "cdx nosuchcmd",
        "cdx check --no-such-flag",
        "cdx check --no-such-flag=1",
        "cdx",
    ):
        assert len(_cdx_problems([bad])) == 1, bad


@pytest.mark.parametrize("shape", _SHAPES)
def test_the_expected_workflow_holds_only_strings_and_true(shape: str) -> None:
    """Every key and leaf is a string or ``True``. This is what makes the
    loader's leftover YAML 1.1 number rules (``010`` is 8, ``1:20`` is 80, an
    unquoted ``3.10`` is 3.1) fail closed: a number never equals a string, and
    ``True`` is written ``true``, the one spelling both readers agree on."""
    expected = _expected_workflow(_shaped(_sources(REPO_ROOT), shape))
    assert len(list(_leaves(expected))) > 20
    assert _not_string_or_true(expected) == []


def test_the_leaf_type_check_can_fail() -> None:
    """Fault injection for the check above: numbers, ``False``, ``None`` and
    non-string keys are all reported, wherever they sit."""
    doc = {"a": 1, "b": [3.1, {"c": False}], 2: "x", "d": None, "e": True, "f": "y"}
    assert _not_string_or_true(doc) == [1, 3.1, False, 2, None]


# --- the closed set rejects every fail-open edit -------------------------------


def _step(doc: dict[str, Any], job: str, run: str) -> dict[str, Any]:
    hits = [s for s in doc["jobs"][job]["steps"] if s.get("run", "").startswith(run)]
    assert len(hits) == 1, f"{job}: no single step running {run!r}"
    return hits[0]


def _insert_before(
    doc: dict[str, Any], job: str, run: str, step: dict[str, Any]
) -> None:
    steps = doc["jobs"][job]["steps"]
    steps.insert(steps.index(_step(doc, job, run)), step)


def _unquote_version(doc: dict[str, Any]) -> None:
    setup = doc["jobs"][_floor_job(doc)]["steps"][1]["with"]
    setup["python-version"] = float(setup["python-version"])  # "3.10" -> 3.1


_FAIL_OPEN: dict[str, Callable[[dict[str, Any]], object]] = {
    "github-env-injection": lambda d: _insert_before(
        d, "gate", "pytest", {"run": 'echo "PYTEST_ADDOPTS=--co" >> "$GITHUB_ENV"'}
    ),
    "github-path-shim": lambda d: _insert_before(
        d, "gate", "ruff format", {"run": 'echo "$PWD/.shim" >> "$GITHUB_PATH"'}
    ),
    "touch-coveragerc": lambda d: _insert_before(
        d, "gate", "pytest", {"if": _GUARD, "run": "touch .coveragerc"}
    ),
    "rm-tests-in-floor": lambda d: _insert_before(
        d, _floor_job(d), "pytest", {"if": _GUARD, "run": "rm -rf tests/unit"}
    ),
    "pytest-or-true": lambda d: _step(d, "gate", "pytest").update(
        run="pytest --cov=custodex --cov-branch || true"
    ),
    "step-env": lambda d: _step(d, "gate", "pytest").update(
        env={"PYTEST_ADDOPTS": "--co"}
    ),
    "continue-on-error": lambda d: _step(d, "gate", "mypy").update(
        {"continue-on-error": True}
    ),
    "step-if-false": lambda d: _step(d, "gate", "mypy").update({"if": "false"}),
    "guard-dropped": lambda d: _step(d, "gate", "mypy").pop("if"),
    "guard-always": lambda d: _step(d, "frontend", "npx vitest").update(
        {"if": "${{ always() }}"}
    ),
    "install-extra-unquoted": lambda d: _step(d, "gate", "python -m pip").update(
        run="python -m pip install -e .[dev]"
    ),
    "install-id-moved": lambda d: (
        _step(d, "gate", "python -m pip").pop("id"),
        d["jobs"]["gate"]["steps"][0].update(id="install"),
    ),
    "checkout-ref-main": lambda d: d["jobs"]["gate"]["steps"][0].update(
        {"with": {"ref": "main"}}
    ),
    "checkout-arbitrary-sha": lambda d: d["jobs"]["gate"]["steps"][0].update(
        uses="actions/checkout@" + "0" * 37 + "bad"
    ),
    "floor-second-setup-python": lambda d: d["jobs"][_floor_job(d)]["steps"].insert(
        2,
        {
            "uses": d["jobs"][_floor_job(d)]["steps"][1]["uses"],
            "with": {"python-version": "3.12"},
        },
    ),
    "floor-version-unquoted": _unquote_version,
    "trigger-types-closed": lambda d: d["on"]["pull_request"].update(types=["closed"]),
    "trigger-paths": lambda d: d["on"]["pull_request"].update(paths=["custodex/**"]),
    "trigger-pull-request-target": lambda d: d["on"].update(
        pull_request_target={"branches": ["main"]}
    ),
    "trigger-other-branch": lambda d: d["on"]["pull_request"].update(
        branches=["release"]
    ),
    "permissions-write-all": lambda d: d.update(permissions="write-all"),
    "container-env": lambda d: d["jobs"]["gate"].update(
        container={"image": "python:3.11-slim", "env": {"PYTEST_ADDOPTS": "--co"}}
    ),
    "job-needs": lambda d: d["jobs"]["gate"].update(needs=["frontend"]),
    "job-renamed": lambda d: d["jobs"]["gate"].update(name="gate (3.11)"),
    "job-env": lambda d: d["jobs"][_floor_job(d)].update(
        env={"PYTEST_ADDOPTS": "--co"}
    ),
    "workflow-defaults": lambda d: d.update(
        defaults={"run": {"working-directory": "demo"}}
    ),
    "workflow-env": lambda d: d.update(env={"PYTEST_ADDOPTS": "--co"}),
    "frontend-workdir": lambda d: d["jobs"]["frontend"]["defaults"]["run"].update(
        {"working-directory": "demo"}
    ),
    "cancel-in-progress-off": lambda d: d["concurrency"].update(
        {"cancel-in-progress": False}
    ),
    "frontend-merged-into-gate": lambda d: d["jobs"].pop("frontend"),
}


@pytest.mark.parametrize("shape", _SHAPES)
@pytest.mark.parametrize("edit", sorted(_FAIL_OPEN))
def test_ci_workflow_cannot_turn_a_red_gate_green(edit: str, shape: str) -> None:
    """Each known fail-open edit to ci.yml (from the prior run's mutation and
    review rounds) is rejected by the equality pin, in both workflow shapes."""
    expected = _expected_workflow(_shaped(_sources(REPO_ROOT), shape))
    doc = copy.deepcopy(expected)
    assert _diff(doc, expected) == []
    _FAIL_OPEN[edit](doc)
    assert _diff(doc, expected) != []


@pytest.mark.parametrize("shape", _SHAPES)
def test_dropping_any_gate_step_or_job_is_rejected(shape: str) -> None:
    """Removing any single step, or any whole job, fails the pin."""
    expected = _expected_workflow(_shaped(_sources(REPO_ROOT), shape))
    removals = 0
    for job, body in expected["jobs"].items():
        for i in range(len(body["steps"])):
            doc = copy.deepcopy(expected)
            del doc["jobs"][job]["steps"][i]
            assert _diff(doc, expected) != [], f"{job}.steps[{i}]"
            removals += 1
        doc = copy.deepcopy(expected)
        del doc["jobs"][job]
        assert any("missing" in line for line in _diff(doc, expected)), job
    assert removals == sum(len(b["steps"]) for b in expected["jobs"].values()) > 0


# --- the loader --------------------------------------------------------------


@pytest.mark.parametrize("spelling", ["On", "ON", "yes", "true", "True"])
def test_trigger_key_must_be_spelled_on(spelling: str) -> None:
    """GitHub reads only a literal ``on:``; any YAML 1.1 alias of it would leave
    the workflow without a trigger, so it must not load as the key ``on``."""
    doc = _load_yaml(f"{spelling}:\n  pull_request: {{branches: [main]}}\n")
    assert "on" not in doc


def test_unquoted_versions_and_yaml11_booleans_stay_distinct() -> None:
    """An unquoted 3.10 is the float 3.1 (wrong interpreter); ``yes`` is a string;
    the lowercase ``true``/``false`` are the only booleans (``fail-fast: false``
    must load as ``False``)."""
    doc = _load_yaml("a: 3.10\nb: yes\nc: true\nd: false\n")
    assert doc == {"a": 3.1, "b": "yes", "c": True, "d": False}
    assert type(doc["d"]) is bool
    assert _diff(doc["a"], "3.10") != []


def test_capitalised_booleans_stay_strings() -> None:
    """``True``/``TRUE``/``False`` load as strings, so a re-spelled
    ``cancel-in-progress: True`` differs from the pinned ``true`` instead of
    depending on how GitHub's reader treats that spelling."""
    doc = _load_yaml("a: True\nb: TRUE\nc: False\n")
    assert doc == {"a": "True", "b": "TRUE", "c": "False"}
    assert _diff(doc["a"], True) != []


def test_the_comparison_is_type_strict() -> None:
    """``1 == True`` and ``"x" in "xy"`` in Python; the pin must not accept them."""
    assert _diff(1, True) != []
    assert _diff(True, 1) != []
    assert _diff("write-all", {"contents": "read"}) != []
    assert _diff([], {}) != []
    assert _diff({"a": [1, 2]}, {"a": [1, 2]}) == []


@pytest.mark.parametrize(
    ("first", "second"),
    [("jobs", "jobs"), ("jobs", "'jobs'"), ("3.10", "3.1"), ("1", "0x1")],
)
def test_duplicate_keys_are_loud(first: str, second: str) -> None:
    """A duplicate key raises instead of keeping the last one silently, also when
    two spellings construct the same key (``3.10`` and ``3.1`` are both 3.1)."""
    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        _load_yaml(f"{first}: {{a: 1}}\n{second}: {{b: 2}}\n")


# --- the sources are read, not assumed ----------------------------------------


def _write_sources(root: Path, *, floor: str = ">=3.10", gate: str = "3.11") -> None:
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "templates" / "ci").mkdir(parents=True)
    (root / "web").mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nrequires-python = "{floor}"\n', encoding="utf-8"
    )
    (root / ".gitlab-ci.yml").write_text(
        f"default:\n  image: python:{gate}-slim\n"
        "tests:offline:\n  script:\n    - python -m venv .venv\n"
        "    - .venv/bin/pip install -e '.[dev,x]'\n    - .venv/bin/ruff check .\n"
        "docs:gate:\n  script:\n    - .venv/bin/pip install -e '.[dev,x]'\n"
        "    - .venv/bin/cdx check --config config/cdmon\n"
        "    - .venv/bin/cdx newgate\n",
        encoding="utf-8",
    )
    (root / ".github" / "workflows" / "deploy-pages.yml").write_text(
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v9\n"
        "      - uses: actions/setup-node@v8\n        with:\n"
        '          node-version: "24"\n          cache: npm\n'
        "      - working-directory: web\n        run: npm install --no-audit\n"
        "      - working-directory: web\n        run: npm run build\n",
        encoding="utf-8",
    )
    (root / "templates" / "ci" / "github-actions.adopter.yml").write_text(
        "jobs:\n  a:\n    steps:\n      - uses: actions/setup-python@v7\n"
        '        with: {python-version: "3.9"}\n'
        "  b:\n    steps:\n      - uses: actions/setup-python@v7\n",
        encoding="utf-8",
    )
    (root / "web" / "package.json").write_text(
        json.dumps(
            {"scripts": {"build": "tsc --noEmit && vite build", "test:run": "vt run"}}
        ),
        encoding="utf-8",
    )
    for rel in (
        "config/cdmon/index.yaml",
        "sub/config/cdmon/index.yaml",
        "ex/cdmon.json",
        "ex/tests/cdmon.yaml",
        "tests/fixture/cdmon.yaml",
        "tests/config/cdmon/index.yaml",
        "docs/index.yaml",
        "x/cdmon/index.yaml",
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x: 1\n", encoding="utf-8")
    (root / "untracked").mkdir()
    (root / "untracked" / "cdmon.yaml").write_text("x: 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", ".", ":!untracked"], check=True)


def test_every_value_is_read_from_its_source(tmp_path: Path) -> None:
    """Changing a source changes the expected workflow: nothing is hard-coded.
    The fixture differs from the repo in every value (interpreters, install
    extras, refs, Node, npm verb, frontend dir and scripts); a config under the
    top-level ``tests/`` is a suite fixture, one under ``ex/tests/`` is shipped;
    a setup-python ``with`` that differs between jobs is never read."""
    _write_sources(tmp_path, floor=">=3.12", gate="3.13")
    src = _sources(tmp_path)
    assert src == _Sources(
        gate_python="3.13",
        floor_python="3.12",
        py_install="python -m pip install -e '.[dev,x]'",
        gitlab_gate=("ruff check .", "cdx check --config config/cdmon", "cdx newgate"),
        configs=(
            "config/cdmon",
            "ex/cdmon.json",
            "ex/tests/cdmon.yaml",
            "sub/config/cdmon",
        ),
        checkout="actions/checkout@v9",
        setup_python="actions/setup-python@v7",
        setup_node="actions/setup-node@v8",
        node_with={"node-version": "24", "cache": "npm"},
        frontend_dir="web",
        npm_install="npm install --no-audit",
        frontend_gates=("npx tsc --noEmit", "npx vite build", "npx vt run"),
    )
    assert _gate_commands(src) == [
        "ruff check .",
        "cdx check --config config/cdmon",
        "cdx newgate",
        "cdx check --config ex/cdmon.json",
        "cdx check --config ex/tests/cdmon.yaml",
        "cdx check --config sub/config/cdmon",
        "cdx index --check",
    ]
    wf = _expected_workflow(src)
    for job, version in (("gate", "3.13"), ("floor", "3.12")):
        steps = wf["jobs"][job]["steps"]
        assert steps[1]["with"]["python-version"] == version
        assert steps[2] == {
            "id": "install",
            "run": "python -m pip install -e '.[dev,x]'",
        }
    frontend = wf["jobs"]["frontend"]
    assert frontend["defaults"] == {"run": {"working-directory": "web"}}
    assert frontend["steps"][1] == {
        "uses": "actions/setup-node@v8",
        "with": {"node-version": "24", "cache": "npm"},
    }
    assert [s["run"] for s in frontend["steps"][2:]] == [
        "npm install --no-audit",
        "npx tsc --noEmit",
        "npx vite build",
        "npx vt run",
    ]


@pytest.mark.parametrize(
    ("floor", "gate", "loud"), [(">=3.9", "3.10", False), (">=3.10", "3.9", True)]
)
def test_floor_and_gate_compare_as_versions(
    tmp_path: Path, floor: str, gate: str, loud: bool
) -> None:
    """3.9 is below 3.10 (as a version, not as text): that floor is read, and a
    3.10 floor over a 3.9 gate is loud."""
    _write_sources(tmp_path, floor=floor, gate=gate)
    if loud:
        with pytest.raises(ValueError, match="above the gate"):
            _sources(tmp_path)
    else:
        src = _sources(tmp_path)
        assert (src.floor_python, src.gate_python) == ("3.9", "3.10")


def test_a_floor_raised_to_the_gate_folds_into_the_gate_job(tmp_path: Path) -> None:
    """§7.2 option (b): with requires-python at the gate's version the gate's own
    pytest covers the floor, so only ``gate`` and ``frontend`` remain (branch
    protection must then stop requiring ``floor``)."""
    _write_sources(tmp_path, floor=">=3.11", gate="3.11")
    wf = _expected_workflow(_sources(tmp_path))
    assert list(wf["jobs"]) == ["gate", "frontend"]
    assert wf["jobs"]["gate"]["steps"][1]["with"]["python-version"] == "3.11"


def test_the_gate_python_image_tag_is_optional() -> None:
    """``python:X.Y`` and ``python:X.Y-<tag>`` both name the interpreter."""
    assert _gate_python({"default": {"image": "python:3.12"}}) == "3.12"
    assert _gate_python({"default": {"image": "python:3.12-slim-bookworm"}}) == "3.12"


def test_a_block_scalar_gate_line_with_one_command_is_read() -> None:
    """A ``- |`` entry holding one command keeps only its trailing newline,
    which is stripped; several commands in one entry are refused (below)."""
    gitlab = _load_yaml(
        "tests:offline:\n  script:\n    - .venv/bin/pip install -e .\n"
        "    - |\n      .venv/bin/ruff check .\n"
        "docs:gate:\n  script:\n    - .venv/bin/pip install -e .\n"
        "    - .venv/bin/cdx lint\n"
    )
    assert _gitlab_gate(gitlab) == (
        "python -m pip install -e .",
        ("ruff check .", "cdx lint"),
    )


def test_requires_python_is_read_from_the_project_table_only() -> None:
    """A ``requires-python`` key in another table is not the project's floor."""
    text = (
        '[project]\nrequires-python = ">=3.10"\n[tool.x]\nrequires-python = ">=3.12"\n'
    )
    assert _floor_python(text) == "3.10"


@pytest.mark.parametrize("text", ["[tool.x]\na = 1\n", 'project = "x"\n'])
def test_a_pyproject_without_a_project_table_is_loud(text: str) -> None:
    """No ``[project]`` table, or a ``project`` key that is not a table, has no
    floor to read."""
    with pytest.raises(ValueError, match=re.escape("no [project] requires-python")):
        _floor_python(text)


@pytest.mark.parametrize(
    "image", ["python:3.12.1", "python:3.12@sha256:ab", "python:3.12rc1"]
)
def test_the_gate_python_image_must_be_python_x_y(image: str) -> None:
    """Only ``python:X.Y`` with an optional ``-<tag>`` names the interpreter: a
    patch version, a digest or a pre-release suffix is not read as ``X.Y``."""
    with pytest.raises(ValueError, match="default.image"):
        _gate_python({"default": {"image": image}})


def test_a_multi_line_install_entry_is_loud() -> None:
    """The install entry itself is read one command per entry: a ``- |`` block
    holding the install and a second command is refused, like any gate line."""
    entry = "    - |\n      .venv/bin/pip install -e .\n      rm -rf tests\n"
    gitlab = _load_yaml(
        "tests:offline:\n  script:\n" + entry + "    - .venv/bin/ruff check .\n"
        "docs:gate:\n  script:\n" + entry + "    - .venv/bin/cdx lint\n"
    )
    with pytest.raises(ValueError, match="spans several lines"):
        _gitlab_gate(gitlab)


def test_the_below_gate_shape_is_built_once_the_repo_is_folded() -> None:
    """Once the repo itself is folded, the below-gate shape is still checked: it
    is built one minor below the gate, with its own ``floor`` job. A source that
    is already below the gate is used as it is, and a gate at minor 0 has no
    minor below it, so building that shape is loud."""
    src = dataclasses.replace(
        _sources(REPO_ROOT), floor_python="3.11", gate_python="3.11"
    )
    below = _shaped(src, "floor-below-gate")
    assert below.floor_python == "3.10"
    assert list(_expected_workflow(below)["jobs"]) == ["gate", "floor", "frontend"]
    already = dataclasses.replace(src, floor_python="3.9")
    assert _shaped(already, "floor-below-gate") is already
    with pytest.raises(ValueError, match="minor 0"):
        _shaped(
            dataclasses.replace(src, floor_python="4.0", gate_python="4.0"),
            "floor-below-gate",
        )


def test_setup_node_steps_that_agree_on_with_are_read(tmp_path: Path) -> None:
    """Two setup-node steps with the same ref and the same ``with`` are one
    source, so the ``with`` is read (only a disagreement is loud)."""
    _write_sources(tmp_path)
    _edit(
        _DP,
        "  build:\n",
        "  other:\n    steps:\n      - uses: actions/setup-node@v8\n"
        '        with: {node-version: "24", cache: npm}\n  build:\n',
    )(tmp_path)
    src = _sources(tmp_path)
    assert (src.setup_node, src.node_with) == (
        "actions/setup-node@v8",
        {"node-version": "24", "cache": "npm"},
    )


def test_an_action_is_matched_by_its_exact_name(tmp_path: Path) -> None:
    """``actions/checkout-cache`` is another action, not a second checkout ref."""
    _write_sources(tmp_path)
    _edit(
        _DP,
        "  build:\n",
        "  other:\n    steps:\n      - uses: actions/checkout-cache@v2\n  build:\n",
    )(tmp_path)
    assert _sources(tmp_path).checkout == "actions/checkout@v9"


# One script per character `_SHELL_SYNTAX` refuses, each holding only that one
# character, so dropping any single character from the class is caught.
_SHELL_PAYLOADS = {
    "|": "vt run | cat",
    ";": "vt run; true",
    "&": "vt run & true",
    "$": "vt $X",
    "<": "vt < x",
    ">": "vt run > x",
    "`": "vt `x",
    "(": "vt (x",
    ")": "vt x)",
    "\\": "vt \\x",
    "\n": "vt\nrun",
}


def test_the_shell_payloads_cover_exactly_the_refused_characters() -> None:
    """Each payload carries its one refused character, and the payload keys are
    exactly the characters the class refuses (over printable ASCII + newline)."""
    for char, payload in _SHELL_PAYLOADS.items():
        assert _SHELL_SYNTAX.findall(payload) == [char], payload
    candidates = [*map(chr, range(32, 127)), "\n"]
    assert {c for c in candidates if _SHELL_SYNTAX.search(c)} == set(_SHELL_PAYLOADS)


@pytest.mark.parametrize("char", sorted(_SHELL_PAYLOADS))
def test_a_package_json_gate_with_shell_syntax_is_loud(
    tmp_path: Path, char: str
) -> None:
    """``vitest run & true`` would background the gate and exit 0: every shell
    character in a gate script part is refused, one by one."""
    _write_sources(tmp_path)
    scripts = {"build": "b", "test:run": _SHELL_PAYLOADS[char]}
    _write(_PJ, json.dumps({"scripts": scripts}))(tmp_path)
    with pytest.raises(ValueError, match="not one plain command"):
        _sources(tmp_path)


@pytest.mark.parametrize("char", sorted(_SHELL_PAYLOADS))
def test_an_npm_install_with_shell_syntax_is_loud(tmp_path: Path, char: str) -> None:
    """The same refusal holds for deploy-pages' npm install line."""
    _write_sources(tmp_path)
    run = "npm install --no-audit " + _SHELL_PAYLOADS[char]
    _edit(_DP, "run: npm install --no-audit", f"run: {json.dumps(run)}")(tmp_path)
    with pytest.raises(ValueError, match="not one plain command"):
        _sources(tmp_path)


def _edit(rel: str, old: str, new: str) -> Callable[[Path], object]:
    def corrupt(root: Path) -> None:
        text = (root / rel).read_text(encoding="utf-8")
        assert text.count(old) == 1, (rel, old)
        (root / rel).write_text(text.replace(old, new), encoding="utf-8")

    return corrupt


def _write(rel: str, text: str) -> Callable[[Path], object]:
    return lambda root: (root / rel).write_text(text, encoding="utf-8")


def _untrack(*rels: str) -> Callable[[Path], object]:
    return lambda root: subprocess.run(
        ["git", "-C", str(root), "rm", "-q", "--cached", *rels], check=True
    )


_GL, _DP, _PJ = (
    ".gitlab-ci.yml",
    ".github/workflows/deploy-pages.yml",
    "web/package.json",
)
_PROJECT = '[project]\nname = "x"\n'


@pytest.mark.parametrize(
    ("label", "corrupt", "message"),
    [
        (
            "floor-not-a-floor",
            _edit("pyproject.toml", ">=3.10", "~=3.10"),
            "is not >=X.Y",
        ),
        (
            "floor-with-upper-bound",
            _edit("pyproject.toml", ">=3.10", ">=3.10,<4"),
            "is not >=X.Y",
        ),
        (
            "floor-with-patch",
            _edit("pyproject.toml", ">=3.10", ">=3.10.1"),
            "is not >=X.Y",
        ),
        (
            "floor-with-marker",
            _edit("pyproject.toml", ">=3.10", ">=3.10; extra"),
            "is not >=X.Y",
        ),
        (
            "no-requires-python",
            _write("pyproject.toml", _PROJECT),
            "no [project] requires-python",
        ),
        (
            "requires-python-outside-project",
            _write(
                "pyproject.toml", _PROJECT + '[tool.x]\nrequires-python = ">=3.10"\n'
            ),
            "no [project] requires-python",
        ),
        (
            "floor-above-gate",
            _edit("pyproject.toml", ">=3.10", ">=3.12"),
            "above the gate",
        ),
        (
            "requires-python-twice",
            _write("pyproject.toml", _PROJECT + 'requires-python = ">=3.10"\n' * 2),
            "not valid TOML",
        ),
        (
            "requires-python-not-a-string",
            _write("pyproject.toml", _PROJECT + "requires-python = 3.10\n"),
            "no [project] requires-python",
        ),
        (
            "gitlab-image-not-python",
            _edit(_GL, "python:3.11-slim", "node:22"),
            "default.image",
        ),
        (
            "gitlab-image-versioned-not-python",
            _edit(_GL, "python:3.11-slim", "node:22.11-slim"),
            "default.image",
        ),
        (
            "gitlab-gate-line-outside-venv",
            _edit(_GL, ".venv/bin/ruff check .", "ruff check . || true"),
            "is not a",
        ),
        (
            "gitlab-gate-job-missing",
            _edit(_GL, "docs:gate:", "docs:other:"),
            "docs:gate",
        ),
        (
            "gitlab-gate-without-install",
            _edit(
                _GL,
                "    - .venv/bin/pip install -e '.[dev,x]'\n    - .venv/bin/cdx",
                "    - .venv/bin/cdx",
            ),
            "exactly one pip install",
        ),
        (
            "gitlab-gate-installs-twice",
            _edit(
                _GL,
                "'.[dev,x]'\n    - .venv/bin/ruff",
                "'.[dev,x]'\n    - .venv/bin/pip install ruff==0.0.1\n"
                "    - .venv/bin/ruff",
            ),
            "exactly one pip install",
        ),
        (
            "gitlab-gate-jobs-install-differently",
            _edit(
                _GL, "'.[dev,x]'\n    - .venv/bin/cdx", "'.[dev]'\n    - .venv/bin/cdx"
            ),
            "install differently",
        ),
        (
            "gitlab-install-outside-venv",
            _edit(
                _GL,
                "    - .venv/bin/pip install -e '.[dev,x]'\n    - .venv/bin/ruff",
                "    - pip install -e '.[dev,x]'\n    - .venv/bin/ruff",
            ),
            "is not a .venv/bin/pip install",
        ),
        (
            "gitlab-gate-line-spans-lines",
            _edit(
                _GL,
                "    - .venv/bin/cdx newgate\n",
                "    - |\n      .venv/bin/cdx newgate\n      rm -rf tests\n",
            ),
            "spans several lines",
        ),
        (
            "gitlab-gate-runs-nothing",
            _write(
                _GL,
                "default:\n  image: python:3.11-slim\n"
                "tests:offline:\n  script:\n    - .venv/bin/pip install -e .\n"
                "docs:gate:\n  script:\n    - .venv/bin/pip install -e .\n",
            ),
            "run no command",
        ),
        (
            "no-shipped-config",
            _untrack(
                "config/cdmon/index.yaml",
                "sub/config/cdmon/index.yaml",
                "ex/cdmon.json",
                "ex/tests/cdmon.yaml",
            ),
            "no shipped cdmon config",
        ),
        (
            "two-checkout-refs",
            _edit(
                _DP,
                "  build:\n",
                "  other:\n    steps:\n      - uses: actions/checkout@v1\n  build:\n",
            ),
            "one ref for actions/checkout",
        ),
        (
            "no-checkout",
            _edit(_DP, "actions/checkout@v9", "actions/other@v9"),
            "one ref for actions/checkout",
        ),
        (
            "setup-node-steps-disagree-on-with",
            _edit(
                _DP,
                "  build:\n",
                "  other:\n    steps:\n      - uses: actions/setup-node@v8\n"
                '        with:\n          node-version: "20"\n  build:\n',
            ),
            "one `with` for actions/setup-node",
        ),
        (
            "setup-node-without-with",
            _edit(
                _DP,
                '        with:\n          node-version: "24"\n          cache: npm\n',
                "",
            ),
            "one `with` for actions/setup-node",
        ),
        (
            "setup-node-without-version",
            _edit(_DP, 'node-version: "24"', 'other: "24"'),
            "node-version",
        ),
        (
            "no-npm-install",
            _edit(_DP, "run: npm install --no-audit", "run: echo hi"),
            "one npm install step",
        ),
        (
            "two-npm-installs",
            _edit(_DP, "run: npm run build", "run: npm ci"),
            "one npm install step",
        ),
        (
            "npm-install-without-working-directory",
            _edit(
                _DP,
                "      - working-directory: web\n        run: npm install",
                "      - run: npm install",
            ),
            "no working-directory",
        ),
        (
            "npm-install-with-shell-syntax",
            _edit(_DP, "run: npm install --no-audit", "run: npm install || true"),
            "not one plain command",
        ),
        (
            "package-json-missing",
            lambda r: (r / _PJ).unlink(),
            "cannot read its scripts",
        ),
        ("package-json-not-json", _write(_PJ, "{scripts"), "cannot read its scripts"),
        ("package-json-not-an-object", _write(_PJ, "[]"), "cannot read its scripts"),
        (
            "package-json-no-gate-script",
            _write(_PJ, '{"scripts": {"build": "b"}}'),
            "no 'test:run' script",
        ),
        (
            "package-json-script-with-shell-syntax",
            _write(_PJ, '{"scripts": {"build": "b", "test:run": "vt run || true"}}'),
            "not one plain command",
        ),
        (
            "package-json-script-empty-part",
            _write(_PJ, '{"scripts": {"build": "b &&", "test:run": "vt"}}'),
            "not one plain command",
        ),
    ],
)
def test_an_unreadable_source_is_loud(
    tmp_path: Path, label: str, corrupt: Callable[[Path], object], message: str
) -> None:
    """A source the derivation cannot read raises; it never falls back to a guess."""
    _write_sources(tmp_path)
    corrupt(tmp_path)
    with pytest.raises(ValueError, match=re.escape(message)):
        _sources(tmp_path)
