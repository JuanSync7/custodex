"""Self-tests for the executed-CI harness (S1-CITPL CI-HARNESS: T10, T10e, T10f, T75).

The harness (``tests/_ci_exec.py`` + ``tests/_fake_forge.py`` +
``tests/_cdx_ci_shim.py``) runs the shipped CI templates as real jobs, offline.
These tests pin the harness itself, so that a later template test which uses it
cannot pass vacuously:

* the job env is an ALLOWLIST, never ``os.environ`` (T75 / M50);
* anything the harness does not model is refused loudly with ``NotModelled``,
  never silently skipped or guessed (T10, M16);
* the install filter skips only the documented install lines;
* the fake forge is stateful and as strict as the real one (id != iid, 404 on the
  wrong identifier, duplicates refused, all-or-nothing writes);
* the shim binds the real CLI to the fake forge and records central traffic,
  trips on any unpatched network or LLM call, and its write seam is live (T10e);
* two runs of the same job give byte-identical logs (K7).
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import socket
import types
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from custodex import backends, monitor, pr, registry, sinks, spmirror
from custodex.errors import TransportError
from custodex.pr import GitHubTransport, GitLabTransport, MergeRequestPlan
from tests import _cdx_ci_shim as shim
from tests import _ci_exec as ci
from tests import _fake_forge as forge
from tests._gitrepo import GitRepo, init_repo
from tests._repo import REPO_ROOT

_TEMPLATES = REPO_ROOT / "templates" / "ci"
_GITLAB = _TEMPLATES / "gitlab-ci.adopter.yml"
_GITHUB = _TEMPLATES / "github-actions.adopter.yml"
_DOGFOOD = REPO_ROOT / ".gitlab-ci.yml"
_ALL_TEMPLATES = (_GITLAB, _GITHUB, _DOGFOOD)

_GITLAB_TOKEN_ENV = (
    inspect.signature(GitLabTransport.from_env).parameters["token_env"].default
)
_GITHUB_TOKEN_ENV = (
    inspect.signature(GitHubTransport.from_env).parameters["token_env"].default
)
# The central token NAME is adopter config (examples/external-repo/cdmon.yaml
# `central.auth_env`), read from the fixture, never typed here.
_CENTRAL = "fake-central-token-value"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def adopter_src(tmp_path_factory: pytest.TempPathFactory) -> ci.AdopterRepo:
    """The examples/external-repo adopter with commits A, B, C, B' (built once)."""
    return ci.build_adopter_repo(tmp_path_factory.mktemp("adopter") / "repo")


@pytest.fixture
def adopter(adopter_src: ci.AdopterRepo, tmp_path: Path) -> ci.AdopterRepo:
    """A per-test copy of the adopter fixture (tests never share a working tree)."""
    return ci.copy_adopter_repo(adopter_src, tmp_path / "adopter")


@pytest.fixture
def tiny(tmp_path: Path) -> GitRepo:
    """A three-commit repo for harness tests that run no ``cdx`` at all."""
    repo = init_repo(tmp_path / "tiny")
    for n in (1, 2, 3):
        repo.commit_files(f"c{n}", {"f.txt": f"{n}\n"})
    return repo


def _central_auth_env(adopter: ci.AdopterRepo) -> str:
    import yaml

    cfg = yaml.safe_load((adopter.repo.path / "cdmon.yaml").read_text())
    name = cfg["central"]["auth_env"]
    assert isinstance(name, str) and name
    return name


def _gitlab_tpl(jobs: dict, **top: object) -> dict:
    return {"stages": ["one", "two", "three"], **top, **jobs}


def _gl(tpl: dict | Path, job: str, repo: GitRepo, **kw: object) -> ci.CiJob:
    args: dict = {
        "head": repo.head(),
        "branch": "main",
        "before": None,
    }
    args.update(kw)
    return ci.gitlab_job(tpl, job, **args)


def _gh(tpl: dict | Path, job: str, repo: GitRepo, **kw: object) -> ci.CiJob:
    args: dict = {"head": repo.head(), "branch": "main"}
    args.update(kw)
    return ci.github_job(tpl, job, **args)


def _gh_tpl(steps: list, env: dict | None = None, **job: object) -> dict:
    body: dict = {"runs-on": "ubuntu-latest", "steps": steps, **job}
    if env is not None:
        body["env"] = env
    return {"name": "t", "on": {"push": None}, "jobs": {"j": body}}


def _pipeline_jobs(tpl: dict, repo: GitRepo, **kw: object) -> tuple[ci.CiJob, ...]:
    args: dict = {
        "source": "push",
        "branch": "main",
        "default_branch": "main",
        "head": repo.head(),
        "before": None,
    }
    args.update(kw)
    return ci.gitlab_pipeline(tpl, **args)


# --------------------------------------------------------------------------- #
# T75 / M50 — the job env is an allowlist
# --------------------------------------------------------------------------- #

_POISON = {
    "CI_COMMIT_SHA": "poison-sha",
    "GITHUB_SHA": "poison-gh-sha",
    "CI_API_V4_URL": "https://poison.invalid/api/v4",
    _GITLAB_TOKEN_ENV: "poison-token",
    _GITHUB_TOKEN_ENV: "poison-gh-token",
    "ANTHROPIC_API_KEY": "poison-anthropic",
    "OPENAI_API_KEY": "poison-openai",
    "GIT_DIR": "/poison/git-dir",
    "PYTHONPATH": "/poison/pythonpath",
    "CDX_POISON_MARKER": "poison-marker",
}

# Names bash itself adds to the environment of the `env` command it runs.
_BASH_OWN = {"PWD", "SHLVL", "_", "OLDPWD"}


def _env_of(run: ci.CiRun) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in run.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


@pytest.mark.parametrize("platform", ["gitlab", "github"])
def test_harness_env_is_an_allowlist(
    platform: str,
    tiny: GitRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T75/M50: a poisoned host env never reaches the job; only the allowlist does."""
    if platform == "gitlab":
        job = _gl(
            _gitlab_tpl({"dump": {"stage": "one", "script": ["env"]}}), "dump", tiny
        )
    else:
        job = _gh(_gh_tpl([{"uses": "actions/checkout@v4"}, {"run": "env"}]), "j", tiny)
    head = tiny.head()
    for name, value in _POISON.items():
        monkeypatch.setenv(name, value)
    run = ci.run_ci_job(job, tiny, tmp=tmp_path / "ci", forge_state=None)
    assert run.exit_code == 0, run.stderr
    env = _env_of(run)
    assert env, "the env dump is empty — the test would pass vacuously"
    poisoned = {k for k, v in env.items() if v in _POISON.values()}
    assert poisoned == set(), poisoned
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GIT_DIR", "PYTHONPATH"):
        assert name not in env
    assert "CDX_POISON_MARKER" not in env
    # Exactly the allowlist: harness-owned + modelled CI vars + declared secrets.
    expected = set(ci.job_env_names(job)) | _BASH_OWN
    assert set(env) - expected == set(), sorted(set(env) - expected)
    assert env["HOME"].startswith(str(tmp_path))
    assert env["LANG"] == "C.UTF-8"
    if platform == "gitlab":
        assert env["CI_COMMIT_SHA"] == head
        assert env["CI_API_V4_URL"] == forge.GITLAB_API_URL
        assert "GITHUB_SHA" not in env
    else:
        assert env["GITHUB_SHA"] == head
        assert "CI_COMMIT_SHA" not in env


def test_fake_env_accepts_only_cdx_fake_keys(tiny: GitRepo, tmp_path: Path) -> None:
    """fake_env cannot smuggle a host variable in, nor override a harness-owned one."""
    job = _gl(_gitlab_tpl({"j": {"stage": "one", "script": ["env"]}}), "j", tiny)
    with pytest.raises(ValueError, match="CDX_FAKE_"):
        ci.run_ci_job(
            job, tiny, tmp=tmp_path / "a", forge_state=None, fake_env={"PATH": "/x"}
        )
    with pytest.raises(ValueError, match="harness owns"):
        ci.run_ci_job(
            job,
            tiny,
            tmp=tmp_path / "b",
            forge_state=None,
            fake_env={shim.ENV_HTTP_LOG: "/x"},
        )
    run = ci.run_ci_job(
        job,
        tiny,
        tmp=tmp_path / "c",
        forge_state=None,
        fake_env={"CDX_FAKE_EXTRA": "1", shim.ENV_NOW: None},
    )
    env = _env_of(run)
    assert env["CDX_FAKE_EXTRA"] == "1"
    assert shim.ENV_NOW not in env


@pytest.mark.parametrize("name", ["PATH", "HOME", "LANG", "TMPDIR", "CDX_FAKE_NOW"])
def test_templates_cannot_set_harness_owned_names(name: str, tiny: GitRepo) -> None:
    tpl = _gitlab_tpl(
        {"j": {"stage": "one", "variables": {name: "x"}, "script": ["true"]}}
    )
    with pytest.raises(ci.NotModelled, match=f"harness owns \\${name}"):
        _gl(tpl, "j", tiny)
    gh = _gh_tpl([{"run": "true"}], env={name: "x"})
    with pytest.raises(ci.NotModelled, match=f"harness owns \\${name}"):
        _gh(gh, "j", tiny)


@pytest.fixture
def no_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every CI / provider / token env name the product reads (in-process)."""
    ci.clear_ci_env(monkeypatch)


@pytest.mark.parametrize("platform", ["gitlab", "github"])
def test_harness_names_win_past_the_template_checks(
    platform: str, tiny: GitRepo, tmp_path: Path
) -> None:
    """Defence in depth: a harness-owned name that slipped past the template
    checks still loses to the harness value at run time (harness spread last)."""
    import dataclasses

    if platform == "gitlab":
        job = _gl(_gitlab_tpl({"j": {"stage": "one", "script": ["env"]}}), "j", tiny)
        job = dataclasses.replace(
            job,
            variables=(("HOME", "/evil", False), ("LANG", "evil", True)),
            project={"TMPDIR": "/evil"},
        )
    else:
        job = _gh(_gh_tpl([{"run": "env"}]), "j", tiny)
        (step,) = job.steps
        job = dataclasses.replace(
            job,
            env={"HOME": "/evil", "LANG": "evil"},
            steps=(dataclasses.replace(step, env={"TMPDIR": "/evil"}),),
        )
    run = ci.run_ci_job(job, tiny, tmp=tmp_path / "ci", forge_state=None)
    assert run.exit_code == 0, run.stderr
    env = _env_of(run)
    assert env["HOME"].startswith(str(tmp_path))
    assert env["LANG"] == "C.UTF-8"
    assert env["TMPDIR"].startswith(str(tmp_path))


def test_product_env_names_reads_every_access_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subscript, .get, getenv and *_env defaults are all collected; only the
    product prefixes count for direct reads."""
    src = tmp_path / "probe.py"
    src.write_text(
        "import os\n"
        'A = os.environ["CI_PROBE_SUB"]\n'
        'B = os.environ.get("GITLAB_PROBE_GET")\n'
        'C = os.getenv("GITHUB_PROBE_GETENV")\n'
        'D = os.environ.pop("CDMON_PROBE_POP", None)\n'
        'E = os.environ["HOME"]\n'
        'def f(token_env="ANY_PROBE_TOKEN", *, key_env="ANY_PROBE_KEY"): ...\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ci, "_iter_custodex_sources", lambda: iter([src]))
    assert ci.product_env_names() == (
        "ANY_PROBE_KEY",
        "ANY_PROBE_TOKEN",
        "CDMON_PROBE_POP",
        "CI_PROBE_SUB",
        "GITHUB_PROBE_GETENV",
        "GITLAB_PROBE_GET",
    )


def test_no_ci_env_clears_the_names_the_product_reads(no_ci_env: None) -> None:
    """The fixture clears CI_COMMIT_SHA and the from_env defaults (derived names)."""
    names = ci.product_env_names()
    assert "CI_COMMIT_SHA" in names
    assert _GITLAB_TOKEN_ENV in names and _GITHUB_TOKEN_ENV in names
    for name in names:
        assert name not in os.environ


# --------------------------------------------------------------------------- #
# T10 — the install filter
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("template", _ALL_TEMPLATES, ids=lambda p: p.name)
def test_harness_install_filter_matches_every_template(template: Path) -> None:
    """Every shipped template has install lines, and only those lines are skipped."""
    skipped = ci.install_lines(template)
    assert skipped, f"{template.name}: no install line matched — the filter rotted"
    for line in skipped:
        assert ci.INSTALL_LINE.match(line), line


def test_install_filter_drops_only_install_lines(adopter: ci.AdopterRepo) -> None:
    job = _gl(_GITLAB, "cdx-docs-pr", adopter.repo)
    script = job.steps[0].run or ""
    assert "pip install" not in script and "python -m venv" not in script
    assert ".venv/bin/cdx register" in script
    assert job.steps[0].skipped_install == (
        "python -m venv .venv",
        ".venv/bin/pip install custodex",
    )


@pytest.mark.parametrize(
    "line",
    [
        "pip install custodex && echo hi",
        "pip install custodex; echo hi",
        "pip install custodex | tee log",
        "pip install `echo custodex`",
        "pip install $(echo custodex)",
        "pip install custodex & echo hi",
        "pip install cdx-plugin",
        "python -m venv .venv \\",
    ],
)
def test_install_line_that_does_more_is_refused(line: str, tiny: GitRepo) -> None:
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": [line, "true"]}})
    with pytest.raises(ci.NotModelled):
        _gl(tpl, "j", tiny)


@pytest.mark.parametrize(
    "item", ["echo a \\\npip install x", "python -m venv .venv \\\necho b"]
)
def test_continued_install_lines_are_refused(item: str, tiny: GitRepo) -> None:
    """An install line that ends with, or follows, a line continuation is refused."""
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": [item, "true"]}})
    with pytest.raises(ci.NotModelled, match="continued install line"):
        _gl(tpl, "j", tiny)


@pytest.mark.parametrize(
    "line",
    [
        "pip install custodex 2>&1",
        "pip install custodex &>/dev/null",
        "command -v git >/dev/null 2>&1 || "
        "{ apt-get update -qq && apt-get install -y -qq --no-install-recommends git; }",
    ],
)
def test_install_line_redirects_and_the_git_bootstrap_are_skipped(
    line: str, tiny: GitRepo
) -> None:
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": [line, "true"]}})
    job = _gl(tpl, "j", tiny)
    assert job.steps[0].skipped_install == (line,)


@pytest.mark.parametrize(
    "line",
    [
        "pip3 install custodex",
        "python -m pip install custodex",
        "uv pip install custodex",
        "python -m custodex check",
        "python3 -m custodex check",
    ],
)
def test_broader_install_or_module_forms_are_refused(line: str, tiny: GitRepo) -> None:
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": [line]}})
    with pytest.raises(ci.NotModelled):
        _gl(tpl, "j", tiny)


@pytest.mark.parametrize(
    "line",
    [
        "command -v git >/dev/null 2>&1 || { apt-get install -y git",
        "command -v git >/dev/null 2>&1 || { apt-get install -y git; }; echo EXTRA",
    ],
)
def test_unrecognised_git_bootstrap_is_refused(line: str, tiny: GitRepo) -> None:
    """A bootstrap that is unclosed or chains more work is refused, not dropped."""
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": [line, "true"]}})
    with pytest.raises(ci.NotModelled, match="git bootstrap"):
        _pipeline_jobs(tpl, tiny)


def test_comment_lines_are_kept_not_judged(tiny: GitRepo) -> None:
    """An install command inside a comment is neither skipped nor refused."""
    script = "# pip3 install foo\n# python -m pip install bar\ntrue"
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": [script]}})
    (job,) = _pipeline_jobs(tpl, tiny)
    assert "# pip3 install foo" in (job.steps[0].run or "")
    assert job.steps[0].skipped_install == ()


# --------------------------------------------------------------------------- #
# T10 — GitHub expressions; provider variables
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "where",
    ["run", "step_env", "job_env", "workflow_env"],
)
@pytest.mark.parametrize(
    "expr", ["github.sha", "github.ref_name", "env.X", "format('{0}', 'x')", "vars.X"]
)
def test_harness_refuses_an_unmodelled_github_expression(
    where: str, expr: str, tiny: GitRepo
) -> None:
    text = "${{ " + expr + " }}"
    step: dict = {"run": "true"}
    tpl = _gh_tpl([step])
    if where == "run":
        step["run"] = f"echo {text}"
    elif where == "step_env":
        step["env"] = {"V": text}
    elif where == "job_env":
        tpl["jobs"]["j"]["env"] = {"V": text}
    else:
        tpl["env"] = {"V": text}
    with pytest.raises(ci.NotModelled, match="expression"):
        _gh(tpl, "j", tiny)


def test_github_modelled_expressions_and_static_with(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gh_tpl(
        [
            {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
            {
                "uses": "actions/cache/restore@v4",
                "with": {"path": ".cdmon", "key": "k-${{ github.sha }}"},
            },
            {"run": 'echo "S=${{ secrets.MISSING }}|B=$B|T=$T"'},
        ],
        env={"B": "${{ github.event.before }}", "T": "${{ secrets.TOK }}"},
    )
    job = _gh(tpl, "j", tiny, secrets={"TOK": "tok"}, before=None)
    run = ci.run_ci_job(job, tiny, tmp=tmp_path / "ci", forge_state=None)
    assert run.exit_code == 0, run.stderr
    assert run.stdout.strip() == f"S=|B={ci.ZERO_SHA}|T=tok"
    # `with:` is static: kept raw, never evaluated.
    assert run.cache_events[0]["key"] == "k-${{ github.sha }}"


@pytest.mark.parametrize("scope", ["workflow", "job", "step"])
@pytest.mark.parametrize(
    "name", ["GITHUB_SHA", "GITHUB_WORKSPACE", "GITHUB_HEAD_REF", "RUNNER_OS", "CI"]
)
def test_github_env_cannot_override_platform_names(
    scope: str, name: str, tiny: GitRepo
) -> None:
    """GitHub ignores an env override of its GITHUB_*/RUNNER_* names; the harness
    refuses one rather than let the template's value win."""
    step: dict = {"run": 'echo "SHA=$GITHUB_SHA"'}
    if scope == "workflow":
        tpl = _gh_tpl([step])
        tpl["env"] = {name: "spoof"}
    elif scope == "job":
        tpl = _gh_tpl([step], env={name: "spoof"})
    else:
        tpl = _gh_tpl([{**step, "env": {name: "spoof"}}])
    with pytest.raises(ci.NotModelled, match=f"GitHub sets \\${name}"):
        _gh(tpl, "j", tiny)


def test_github_refuses_a_non_push_event(tiny: GitRepo) -> None:
    with pytest.raises(ci.NotModelled, match="event"):
        _gh(_gh_tpl([{"run": "true"}]), "j", tiny, event_name="pull_request")


@pytest.mark.parametrize(
    "filters",
    [
        {"branches": ["main"]},
        {"branches-ignore": ["x"]},
        {"paths": ["docs/**"]},
        {"paths-ignore": ["x"]},
        {"tags": ["v*"]},
        {"tags-ignore": ["v*"]},
        {"branches": ["main"], "paths": ["docs/**"]},
    ],
)
def test_github_push_filters_are_refused(filters: dict, tiny: GitRepo) -> None:
    """A push filter decides whether the job runs at all; it is never ignored."""
    tpl = _gh_tpl([{"run": "echo RAN"}])
    tpl["on"] = {"push": filters}
    with pytest.raises(ci.NotModelled, match="push filter"):
        _gh(tpl, "j", tiny, branch="feature")


@pytest.mark.parametrize("on", [{"push": None}, {"push": {}}, "push", ["push"]])
def test_github_bare_push_trigger_is_accepted(on: object, tiny: GitRepo) -> None:
    tpl = _gh_tpl([{"run": "true"}])
    tpl["on"] = on
    assert _gh(tpl, "j", tiny).selected is True


def test_github_token_is_an_always_present_platform_secret(
    tiny: GitRepo, tmp_path: Path
) -> None:
    """Actions always provides secrets.GITHUB_TOKEN; adopter secrets are declared."""
    tpl = _gh_tpl(
        [{"run": 'echo "G=[$G]|C=[$C]|T=[$T]"'}],
        env={
            "G": "${{ secrets." + ci.GITHUB_PLATFORM_SECRET + " }}",
            "C": "${{ secrets." + _GITHUB_TOKEN_ENV + " }}",
            "T": "${{ secrets.TOK }}",
        },
    )
    for secrets in (None, {"TOK": "tok"}):
        run = ci.run_ci_job(
            _gh(tpl, "j", tiny, secrets=secrets),
            tiny,
            tmp=tmp_path / f"ci-{secrets is None}",
            forge_state=None,
        )
        assert run.exit_code == 0, run.stderr
        g, c, t = run.stdout.strip().split("|")
        assert g != "G=[]"  # the platform token is always there
        assert c == "C=[]"  # an adopter secret exists only when declared
        assert t == ("T=[]" if secrets is None else "T=[tok]")


def test_github_needs_is_refused(tiny: GitRepo) -> None:
    """There is no GitHub job graph, so `needs:` would be silently ignored."""
    with pytest.raises(ci.NotModelled, match="needs"):
        _gh(_gh_tpl([{"run": "true"}], needs="a"), "j", tiny)


def test_github_checkout_depth_expression_is_refused(tiny: GitRepo) -> None:
    step = {"uses": "actions/checkout@v4", "with": {"fetch-depth": "${{ env.D }}"}}
    with pytest.raises(ci.NotModelled, match="fetch-depth"):
        _gh(_gh_tpl([step]), "j", tiny)


@pytest.mark.parametrize(
    "ref",
    [
        "$CI_JOB_TOKEN",
        "${CI_JOB_TOKEN}",
        "${CI_JOB_TOKEN:-}",
        "${#CI_JOB_TOKEN}",
        "${!CI_JOB_TOKEN}",
        "$GITLAB_USER_LOGIN",
        "$GITHUB_TOKEN",
        "$RUNNER_TEMP",
    ],
)
def test_unmodelled_provider_variables_are_refused(ref: str, tiny: GitRepo) -> None:
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": [f'echo "{ref}"']}})
    with pytest.raises(ci.NotModelled, match="not modelled"):
        _gl(tpl, "j", tiny)
    with pytest.raises(ci.NotModelled, match="not modelled"):
        _gh(_gh_tpl([{"run": f'echo "{ref}"'}]), "j", tiny)


def test_unmodelled_provider_ref_in_rules_if_is_refused(tiny: GitRepo) -> None:
    tpl = _gitlab_tpl(
        {
            "j": {
                "stage": "one",
                "rules": [{"if": '$CI_JOB_TOKEN == "x"'}],
                "script": ["true"],
            }
        }
    )
    with pytest.raises(ci.NotModelled, match="CI_JOB_TOKEN"):
        _gl(tpl, "j", tiny)


@pytest.mark.parametrize("scope", ["job", "job-mapping", "global"])
def test_unmodelled_provider_ref_in_variables_is_refused(
    scope: str, tiny: GitRepo
) -> None:
    if scope == "job":
        tpl = _echo_job({"A": "$CI_JOB_TOKEN"}, "true")
    elif scope == "job-mapping":
        tpl = _echo_job({"A": {"value": "${CI_JOB_TOKEN}"}}, "true")
    else:
        tpl = _gitlab_tpl(
            {"j": {"stage": "one", "script": ["true"]}},
            variables={"A": "$CI_JOB_TOKEN"},
        )
    with pytest.raises(ci.NotModelled, match="CI_JOB_TOKEN"):
        _gl(tpl, "j", tiny)


def test_modelled_and_known_unset_provider_variables_are_accepted(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gitlab_tpl(
        {
            "j": {
                "stage": "one",
                "script": ['echo "[${CI_MERGE_REQUEST_IID:-none}][$CI_COMMIT_BRANCH]"'],
            }
        }
    )
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.stdout.strip() == "[none][main]"


# --------------------------------------------------------------------------- #
# GitLab variables
# --------------------------------------------------------------------------- #


def _echo_job(variables: dict, line: str, **job: object) -> dict:
    return _gitlab_tpl(
        {"j": {"stage": "one", "variables": variables, "script": [line], **job}}
    )


def test_gitlab_yaml_variables_layer_and_expand_at_run_time(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gitlab_tpl(
        {
            "j": {
                "stage": "one",
                "variables": {"LAYER": "job", "CACHE": "$CI_PROJECT_DIR/.cache"},
                "script": ['echo "$LAYER|$CACHE|$GLOBAL"'],
            }
        },
        variables={"LAYER": "global", "GLOBAL": "g"},
    )
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.stdout.strip() == f"job|{run.workspace}/.cache|g"


def test_project_variables_override_yaml_and_are_never_expanded(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _echo_job({"LAYER": "yaml"}, 'echo "$LAYER"')
    job = _gl(tpl, "j", tiny, variables={"LAYER": "p$NOPE"})
    run = ci.run_ci_job(job, tiny, tmp=tmp_path / "ci", forge_state=None)
    assert run.stdout.strip() == "p$NOPE"


def test_chained_variables_reach_a_fixpoint_and_a_cycle_is_refused(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _echo_job({"A": "${B}-a", "B": "$C-b", "C": "c"}, 'echo "$A"')
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.stdout.strip() == "c-b-a"
    cyc = _echo_job({"A": "$B", "B": "$A"}, 'echo "$A"')
    with pytest.raises(ci.NotModelled, match="cycle"):
        ci.run_ci_job(_gl(cyc, "j", tiny), tiny, tmp=tmp_path / "ci2", forge_state=None)


def test_expand_false_inserts_the_value_verbatim(tiny: GitRepo, tmp_path: Path) -> None:
    tpl = _gitlab_tpl(
        {
            "j": {
                "stage": "one",
                "variables": {"RAW": {"value": "$CI_COMMIT_SHA", "expand": False}},
                "script": ["printf '%s\\n' \"$RAW\""],
            }
        },
        variables={"RAW": "$CI_COMMIT_SHA"},
    )
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.stdout.strip() == "$CI_COMMIT_SHA"


def test_gitlab_predefined_variables(tiny: GitRepo) -> None:
    head = tiny.head()
    job = _gl(_echo_job({}, "true"), "j", tiny, branch="Feature/X_1", before=None)
    pre = job.predefined
    assert pre["CI_COMMIT_SHA"] == head
    assert pre["CI_COMMIT_BEFORE_SHA"] == ci.ZERO_SHA
    assert pre["CI_COMMIT_REF_NAME"] == "Feature/X_1"
    assert pre["CI_COMMIT_REF_SLUG"] == "feature-x-1"
    assert pre["CI_DEFAULT_BRANCH"] == "main"
    assert pre["CI_PIPELINE_SOURCE"] == "push"
    assert pre["CI_PROJECT_ID"] == forge.GITLAB_PROJECT_ID
    assert pre["CI_API_V4_URL"] == forge.GITLAB_API_URL
    assert pre["CI_PROJECT_URL"] == forge.GITLAB_PROJECT_URL
    with pytest.raises(ValueError, match="ref"):
        _gl(_echo_job({}, "true"), "j", tiny, ref="other")


def test_gitlab_ref_slug_is_cut_at_63_then_stripped(tiny: GitRepo) -> None:
    job = _gl(_echo_job({}, "true"), "j", tiny, branch="f" * 62 + "-tail-beyond-63")
    assert job.predefined["CI_COMMIT_REF_SLUG"] == "f" * 62


def test_protected_secrets_reach_only_the_default_branch(tiny: GitRepo) -> None:
    on_main = _gl(_echo_job({}, "true"), "j", tiny)
    assert on_main.protected[_GITLAB_TOKEN_ENV]
    on_topic = _gl(_echo_job({}, "true"), "j", tiny, branch="topic")
    assert _GITLAB_TOKEN_ENV not in on_topic.protected
    gh_main = _gh(_gh_tpl([{"run": "true"}]), "j", tiny)
    assert gh_main.secrets[ci.GITHUB_PLATFORM_SECRET]
    assert _GITHUB_TOKEN_ENV not in gh_main.secrets  # adopter-declared only


def _mr_pipeline(tpl: dict, repo: GitRepo, ref: str) -> tuple[ci.CiJob, ...]:
    return ci.gitlab_pipeline(
        tpl,
        source="merge_request_event",
        branch=None,
        ref=ref,
        default_branch="main",
        head=repo.head(),
        before=None,
    )


def test_merge_request_pipeline_branch_is_known_unset(
    tiny: GitRepo, tmp_path: Path
) -> None:
    """$CI_COMMIT_BRANCH is accepted in an MR pipeline and expands empty."""
    (job,) = _mr_pipeline(_echo_job({}, 'echo "[$CI_COMMIT_BRANCH]"'), tiny, "topic")
    assert "CI_COMMIT_BRANCH" not in job.predefined
    run = ci.run_ci_job(job, tiny, tmp=tmp_path / "ci", forge_state=None)
    assert run.exit_code == 0, run.stderr
    assert run.stdout == "[]\n"


def test_merge_request_pipeline_on_the_default_ref_gets_no_protected_secrets(
    tiny: GitRepo,
) -> None:
    """Fail closed: protected secrets go only to push pipelines on the default."""
    (job,) = _mr_pipeline(_echo_job({}, "true"), tiny, "main")
    assert job.protected == {}
    (push,) = _pipeline_jobs(_echo_job({}, "true"), tiny)
    assert push.protected  # non-vacuous: the same template on a push gets them


def test_provider_token_names_are_derived_from_the_transports() -> None:
    assert ci.provider_token_env("gitlab") == _GITLAB_TOKEN_ENV
    assert ci.provider_token_env("github") == _GITHUB_TOKEN_ENV


@pytest.mark.parametrize("kw", ["variables", "secrets"])
@pytest.mark.parametrize("name", ["CDX_FAKE_DECLINE_WRITE", "PATH"])
def test_project_and_protected_variables_cannot_set_harness_names(
    kw: str, name: str, tiny: GitRepo
) -> None:
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": ["true"]}})
    with pytest.raises(ci.NotModelled, match="harness owns"):
        _pipeline_jobs(tpl, tiny, **{kw: {name: "*"}})


def test_undefined_expands_empty_and_double_dollar_escapes(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _echo_job({"A": "x$UNDEF_NAME", "B": "a$$b"}, 'echo "$A|$B"')
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.exit_code == 0, run.stderr
    assert run.stdout.strip() == "x|a$b"


def test_merge_request_pipeline_refuses_before(tiny: GitRepo) -> None:
    """An MR pipeline has no CI_COMMIT_BEFORE_SHA; passing one is a test bug."""
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": ["true"]}})
    with pytest.raises(ValueError, match="before"):
        _pipeline_jobs(
            tpl,
            tiny,
            source="merge_request_event",
            branch=None,
            ref="topic",
            before=tiny.head(),
        )


def test_default_gitlab_depth_is_shallow(tmp_path: Path) -> None:
    """With no GIT_DEPTH, the clone holds exactly the platform default commits."""
    depth = ci.DEFAULT_GITLAB_GIT_DEPTH
    assert depth > 0
    repo = init_repo(tmp_path / "long")
    for n in range(depth + 5):
        repo.commit_files(f"c{n}", {"f.txt": f"{n}\n"})
    tpl = _echo_job({}, "git rev-list --count HEAD")
    job = _gl(tpl, "j", repo)
    assert job.git_depth == depth
    run = ci.run_ci_job(job, repo, tmp=tmp_path / "ci", forge_state=None)
    assert run.exit_code == 0, run.stderr
    assert run.stdout.strip() == str(depth)


@pytest.mark.parametrize("name", ["GIT_STRATEGY", "GIT_CLONE_PATH"])
def test_git_strategy_variables_are_refused(name: str, tiny: GitRepo) -> None:
    tpl = _gitlab_tpl(
        {"j": {"stage": "one", "script": ["true"], "variables": {name: "fetch"}}}
    )
    with pytest.raises(ci.NotModelled, match=name):
        _pipeline_jobs(tpl, tiny)


# --------------------------------------------------------------------------- #
# T10 (rev 3) — the rules evaluator and the pipeline graph
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "cond",
    [
        "$A =~ /x/",
        "$A !~ /x/",
        "$A || $B",
        "($A)",
        "$A == 'x' || $B",
        '"lit"',
        "!$A",
        "$A == x",
    ],
)
def test_rules_evaluator_refuses_unmodelled_syntax(cond: str, tiny: GitRepo) -> None:
    tpl = _gitlab_tpl(
        {"j": {"stage": "one", "script": ["true"], "rules": [{"if": cond}]}}
    )
    with pytest.raises(ci.NotModelled):
        ci.gitlab_pipeline(
            tpl,
            source="push",
            branch="main",
            default_branch="main",
            head=tiny.head(),
            before=None,
        )


@pytest.mark.parametrize(
    "rule_key",
    [{"changes": ["x"]}, {"exists": ["x"]}, {"variables": {"X": "1"}}],
)
def test_rules_evaluator_refuses_unmodelled_rule_keys(
    rule_key: dict, tiny: GitRepo
) -> None:
    tpl = _gitlab_tpl(
        {"j": {"stage": "one", "script": ["true"], "rules": [{"if": "$A", **rule_key}]}}
    )
    with pytest.raises(ci.NotModelled):
        ci.gitlab_pipeline(
            tpl,
            source="push",
            branch="main",
            default_branch="main",
            head=tiny.head(),
            before=None,
        )


@pytest.mark.parametrize(
    ("cond", "variables", "expected"),
    [
        ("$DEPLOY", {}, False),
        ("$DEPLOY", {"DEPLOY": ""}, False),
        ("$DEPLOY", {"DEPLOY": "1"}, True),
        ('$CI_PIPELINE_SOURCE == "push"', {}, True),
        ("$CI_PIPELINE_SOURCE == 'schedule'", {}, False),
        ("$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH", {}, True),
        ("$CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH", {}, False),
        ('$CI_COMMIT_BRANCH && $CI_PIPELINE_SOURCE == "push"', {}, True),
        ("$CI_COMMIT_BRANCH && $DEPLOY", {}, False),
        ("$DEPLOY == null", {}, True),
        ("$DEPLOY == null", {"DEPLOY": ""}, False),
        ('$DEPLOY == ""', {}, False),
        ('$DEPLOY == ""', {"DEPLOY": ""}, True),
    ],
)
def test_rules_evaluator_grammar(
    cond: str, variables: dict, expected: bool, tiny: GitRepo
) -> None:
    tpl = _gitlab_tpl(
        {"j": {"stage": "one", "script": ["true"], "rules": [{"if": cond}]}}
    )
    jobs = ci.gitlab_pipeline(
        tpl,
        source="push",
        branch="main",
        default_branch="main",
        head=tiny.head(),
        before=None,
        variables=variables,
    )
    assert bool(jobs) is expected


def test_job_level_when_never_without_rules_is_refused(tiny: GitRepo) -> None:
    """GitLab rejects `when: never` outside rules; the harness must not drop the job."""
    tpl = _gitlab_tpl(
        {
            "j": {"stage": "one", "script": ["true"], "when": "never"},
            "k": {"stage": "one", "script": ["true"]},
        }
    )
    with pytest.raises(ci.NotModelled, match="never"):
        ci.gitlab_pipeline(
            tpl,
            source="push",
            branch="main",
            default_branch="main",
            head=tiny.head(),
            before=None,
        )


def test_rules_first_match_wins_and_never_or_manual(tiny: GitRepo) -> None:
    tpl = _gitlab_tpl(
        {
            "never": {
                "stage": "one",
                "script": ["true"],
                "rules": [
                    {"if": "$CI_COMMIT_BRANCH", "when": "never"},
                    {"when": "always"},
                ],
            },
            "manual": {
                "stage": "one",
                "script": ["true"],
                "rules": [{"if": "$CI_COMMIT_BRANCH", "when": "manual"}],
            },
        }
    )
    jobs = ci.gitlab_pipeline(
        tpl,
        source="push",
        branch="main",
        default_branch="main",
        head=tiny.head(),
        before=None,
    )
    assert [(j.name, j.when, j.allow_failure) for j in jobs] == [
        ("manual", "manual", False)
    ]


@pytest.mark.parametrize(
    "bad",
    [
        {
            "j": {
                "stage": "one",
                "script": ["true"],
                "rules": [{"if": "$A"}],
                "when": "manual",
            }
        },
        {"j": {"stage": "one", "script": ["true"], "retry": 2}},
        {"j": {"stage": "one", "script": ["true"], "extends": ".x"}},
        {"j": {"stage": "one", "script": ["true"], "only": ["main"]}},
        {"j": {"stage": "one", "script": ["true"], "after_script": ["true"]}},
        {"j": {"stage": "nope", "script": ["true"]}},
        {"include": [{"local": "x.yml"}], "j": {"stage": "one", "script": ["true"]}},
        {"include": "x.yml", "j": {"stage": "one", "script": ["true"]}},
        {"workflow": {"rules": []}, "j": {"stage": "one", "script": ["true"]}},
    ],
)
def test_pipeline_refuses_unmodelled_job_shapes(bad: dict, tiny: GitRepo) -> None:
    with pytest.raises(ci.NotModelled):
        ci.gitlab_pipeline(
            _gitlab_tpl(bad),
            source="push",
            branch="main",
            default_branch="main",
            head=tiny.head(),
            before=None,
        )


def test_only_include_template_is_accepted(tiny: GitRepo) -> None:
    tpl = _gitlab_tpl(
        {
            "include": [{"template": "Security/SAST.gitlab-ci.yml"}],
            "j": {"stage": "one", "script": ["true"]},
        }
    )
    jobs = ci.gitlab_pipeline(
        tpl,
        source="push",
        branch="main",
        default_branch="main",
        head=tiny.head(),
        before=None,
    )
    assert [j.name for j in jobs] == ["j"]


def test_pipeline_sources(tiny: GitRepo) -> None:
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": ["true"]}})
    with pytest.raises(ci.NotModelled, match="source"):
        ci.gitlab_pipeline(
            tpl,
            source="schedule",
            branch="main",
            default_branch="main",
            head=tiny.head(),
            before=None,
        )
    with pytest.raises(ValueError, match="branch"):
        ci.gitlab_pipeline(
            tpl,
            source="merge_request_event",
            branch="main",
            default_branch="main",
            head=tiny.head(),
            before=None,
        )
    (job,) = ci.gitlab_pipeline(
        tpl,
        source="merge_request_event",
        branch=None,
        ref="topic",
        default_branch="main",
        head=tiny.head(),
        before=None,
    )
    assert "CI_COMMIT_BRANCH" not in job.predefined
    assert job.predefined["CI_COMMIT_REF_NAME"] == "topic"
    assert job.predefined["CI_COMMIT_BEFORE_SHA"] == ci.ZERO_SHA


def test_dogfood_pipeline_evaluates(tiny: GitRepo) -> None:
    """The repo's own .gitlab-ci.yml is inside the modelled subset."""
    jobs = ci.gitlab_pipeline(
        _DOGFOOD,
        source="push",
        branch="main",
        default_branch="main",
        head=tiny.head(),
        before=None,
    )
    by = {j.name: j for j in jobs}
    assert by["docs:heal"].when == "manual" and by["docs:heal"].allow_failure
    assert by["tests:pg"].when == "manual" and by["tests:pg"].allow_failure
    assert by["tests:offline"].when == "on_success"


def _pipeline(tpl: dict, tiny: GitRepo, tmp: Path) -> ci.CiPipelineRun:
    jobs = ci.gitlab_pipeline(
        tpl,
        source="push",
        branch="main",
        default_branch="main",
        head=tiny.head(),
        before=None,
    )
    return ci.run_ci_pipeline(jobs, tiny, tmp=tmp, forge_state=None)


def test_pipeline_skip_and_block_propagate_down_a_chain(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gitlab_tpl(
        {
            "gate": {"stage": "one", "script": ["exit 3"]},
            "after_gate": {"stage": "two", "needs": ["gate"], "script": ["echo WRONG"]},
            "third_gate": {
                "stage": "three",
                "needs": ["after_gate"],
                "script": ["echo WRONG"],
            },
            "hold": {
                "stage": "one",
                "script": ["true"],
                "when": "manual",
                "allow_failure": False,
            },
            "after_hold": {"stage": "two", "needs": ["hold"], "script": ["echo WRONG"]},
            "third_hold": {
                "stage": "three",
                "needs": ["after_hold"],
                "script": ["echo WRONG"],
            },
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status["gate"] == "failed"
    assert res.status["after_gate"] == "skipped"
    assert res.status["third_gate"] == "skipped"
    assert res.status["hold"] == "manual"
    # A blocking manual (allow_failure false) never completes, so its DAG
    # successors wait (GitLab: composite 'manual' is not a completed status).
    assert res.status["after_hold"] == "blocked"
    assert res.status["third_hold"] == "blocked"
    assert all("WRONG" not in r.stdout for r in res.runs.values())


def test_pipeline_stage_successor_of_a_blocking_manual_is_blocked(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gitlab_tpl(
        {
            "hold": {"stage": "one", "script": ["true"], "rules": [{"when": "manual"}]},
            "later": {"stage": "two", "script": ["echo WRONG"]},
            "last": {"stage": "three", "script": ["echo WRONG"]},
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status == {"hold": "manual", "later": "blocked", "last": "blocked"}


def test_pipeline_rule_allow_failure_wins(tiny: GitRepo, tmp_path: Path) -> None:
    tpl = _gitlab_tpl(
        {
            "hold": {
                "stage": "one",
                "script": ["true"],
                "allow_failure": False,
                "rules": [{"when": "manual", "allow_failure": True}],
            },
            "later": {"stage": "two", "script": ["echo RAN"]},
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status == {"hold": "manual", "later": "success"}
    assert res.runs["later"].stdout.strip() == "RAN"


def test_pipeline_job_level_allow_failure_holds_under_rules(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gitlab_tpl(
        {
            "flaky": {
                "stage": "one",
                "script": ["exit 4"],
                "allow_failure": True,
                "rules": [{"if": "$CI_COMMIT_BRANCH"}],
            },
            "later": {"stage": "two", "script": ["echo RAN"]},
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status == {"flaky": "failed", "later": "success"}
    assert res.allowed_failures == ("flaky",)


def test_pipeline_needs_and_stages(tiny: GitRepo, tmp_path: Path) -> None:
    """needs: [] runs although the gate fails; .pre/.post bracket; optional needs."""
    tpl = _gitlab_tpl(
        {
            "post": {"stage": ".post", "script": ["echo post"], "when": "always"},
            "gate": {"stage": "one", "script": ["exit 1"]},
            "docs": {"stage": "two", "needs": [], "script": ["echo docs"]},
            "opt": {
                "stage": "three",
                "needs": [{"job": "absent", "optional": True}, "docs"],
                "script": ["echo opt"],
            },
            "pre": {"stage": ".pre", "script": ["echo pre"]},
            "staged": {"stage": "two", "script": ["echo WRONG"]},
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.order == ("pre", "gate", "docs", "staged", "opt", "post")
    assert res.status == {
        "pre": "success",
        "gate": "failed",
        "docs": "success",
        "staged": "skipped",
        "opt": "success",
        "post": "success",
    }
    missing = _gitlab_tpl(
        {"j": {"stage": "two", "needs": ["absent"], "script": ["true"]}}
    )
    with pytest.raises(ci.NotModelled, match="absent"):
        ci.gitlab_pipeline(
            missing,
            source="push",
            branch="main",
            default_branch="main",
            head=tiny.head(),
            before=None,
        )


def test_adopter_gitlab_pipeline_shape(adopter: ci.AdopterRepo) -> None:
    """Today's adopter template: the docs job sits behind the gate stage."""
    jobs = ci.gitlab_pipeline(
        _GITLAB,
        source="push",
        branch="main",
        default_branch="main",
        head=adopter.B,
        before=adopter.A,
    )
    by = {j.name: j for j in jobs}
    assert set(by) == {"cdx-gate", "cdx-docs-pr"}
    assert by["cdx-docs-pr"].preds == ("cdx-gate",)
    topic = ci.gitlab_pipeline(
        _GITLAB,
        source="push",
        branch="topic",
        default_branch="main",
        head=adopter.B,
        before=adopter.A,
    )
    assert [j.name for j in topic] == ["cdx-gate"]


@pytest.mark.parametrize("cond", ["$A $B", "$A ==", "$A == $B == $C", "  "])
def test_rules_unmodelled_shapes_are_refused(cond: str, tiny: GitRepo) -> None:
    """A condition shape outside the grammar is refused, never read as false."""
    tpl = _gitlab_tpl(
        {"j": {"stage": "one", "script": ["true"], "rules": [{"if": cond}]}}
    )
    with pytest.raises(ci.NotModelled):
        _pipeline_jobs(tpl, tiny)


def test_rules_empty_condition_message(tiny: GitRepo) -> None:
    tpl = _gitlab_tpl(
        {"j": {"stage": "one", "script": ["true"], "rules": [{"if": "  "}]}}
    )
    with pytest.raises(ci.NotModelled, match="empty condition"):
        _pipeline_jobs(tpl, tiny)


def test_job_level_manual_defaults_to_allow_failure(tiny: GitRepo) -> None:
    tpl = _gitlab_tpl(
        {
            "m": {"stage": "one", "script": ["true"], "when": "manual"},
            "o": {"stage": "one", "script": ["true"]},
        }
    )
    by = {j.name: j for j in _pipeline_jobs(tpl, tiny)}
    assert by["m"].allow_failure is True
    assert by["o"].allow_failure is False


def test_pipeline_needs_successor_of_a_blocked_job_is_blocked(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gitlab_tpl(
        {
            "hold": {"stage": "one", "script": ["true"], "rules": [{"when": "manual"}]},
            "later": {"stage": "two", "script": ["echo WRONG"]},
            "last": {"stage": "three", "needs": ["later"], "script": ["echo WRONG"]},
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status == {"hold": "manual", "later": "blocked", "last": "blocked"}
    assert res.runs == {}


def test_pipeline_allowed_failures_lists_only_allow_failure_jobs(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gitlab_tpl({"bad": {"stage": "one", "script": ["exit 3"]}})
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status == {"bad": "failed"}
    assert res.allowed_failures == ()


def test_pipeline_same_stage_ties_follow_template_order(tiny: GitRepo) -> None:
    """Ties break by template order, both at the start and after a release."""
    tpl = _gitlab_tpl(
        {
            "zeta": {"stage": "one", "script": ["true"]},
            "alpha": {"stage": "one", "script": ["true"]},
            "root": {"stage": "two", "script": ["true"], "needs": []},
            "ymir": {"stage": "three", "script": ["true"], "needs": ["root"]},
            "beta": {"stage": "three", "script": ["true"], "needs": ["root"]},
        }
    )
    order = [j.name for j in _pipeline_jobs(tpl, tiny)]
    assert order.index("zeta") < order.index("alpha")
    assert order.index("ymir") < order.index("beta")


def test_pipeline_needs_cycle_is_refused(tiny: GitRepo) -> None:
    tpl = _gitlab_tpl(
        {
            "a": {"stage": "one", "script": ["true"], "needs": ["b"]},
            "b": {"stage": "one", "script": ["true"], "needs": ["a"]},
        }
    )
    with pytest.raises(ci.NotModelled, match="cycle"):
        _pipeline_jobs(tpl, tiny)


def test_pipeline_dag_need_on_a_blocking_manual_waits(
    tiny: GitRepo, tmp_path: Path
) -> None:
    """A blocking manual need leaves the job waiting, even under when: always."""
    tpl = _gitlab_tpl(
        {
            "hold": {
                "stage": "one",
                "script": ["true"],
                "when": "manual",
                "allow_failure": False,
            },
            "after": {"stage": "two", "needs": ["hold"], "script": ["echo WRONG"]},
            "notify": {
                "stage": "two",
                "needs": ["hold"],
                "when": "always",
                "script": ["echo WRONG"],
            },
            "staged": {"stage": "three", "when": "always", "script": ["echo WRONG"]},
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status == {
        "hold": "manual",
        "after": "blocked",
        "notify": "blocked",
        "staged": "blocked",
    }
    assert res.runs == {}


def test_pipeline_stage_job_after_a_dag_skipped_job_runs(
    tiny: GitRepo, tmp_path: Path
) -> None:
    """A skipped earlier-stage job does not stop a stage-ordered (no needs) job.

    GitLab: the prior-stage composite of {ignored, skipped} is 'skipped', which
    an on_success non-DAG job accepts; only a DAG job requires 'success'.
    """
    tpl = _gitlab_tpl(
        {
            "opt": {"stage": "one", "script": ["true"], "when": "manual"},
            "dag": {"stage": "two", "needs": ["opt"], "script": ["echo WRONG"]},
            "final": {"stage": "three", "script": ["echo RAN"]},
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status == {"opt": "manual", "dag": "skipped", "final": "success"}
    assert res.runs["final"].stdout.strip() == "RAN"
    assert "dag" not in res.runs


def test_pipeline_dag_always_job_on_an_optional_manual_runs(
    tiny: GitRepo, tmp_path: Path
) -> None:
    """when: always accepts a skipped DAG composite; on_success does not."""
    tpl = _gitlab_tpl(
        {
            "opt": {"stage": "one", "script": ["true"], "when": "manual"},
            "notify": {
                "stage": "two",
                "needs": ["opt"],
                "when": "always",
                "script": ["echo RAN"],
            },
            "plain": {"stage": "two", "needs": ["opt"], "script": ["echo WRONG"]},
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status == {"opt": "manual", "notify": "success", "plain": "skipped"}
    assert res.runs["notify"].stdout.strip() == "RAN"


def test_pipeline_dag_skipped_need_outranks_a_waiting_need(
    tiny: GitRepo, tmp_path: Path
) -> None:
    """GitLab's DAG composite checks skipped/ignored needs before waiting ones."""
    tpl = _gitlab_tpl(
        {
            "opt": {"stage": "one", "script": ["true"], "when": "manual"},
            "hold": {
                "stage": "one",
                "script": ["true"],
                "when": "manual",
                "allow_failure": False,
            },
            "both": {
                "stage": "two",
                "needs": ["hold", "opt"],
                "script": ["echo WRONG"],
            },
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status["both"] == "skipped"


def test_pipeline_stage_job_failure_beats_skips_and_always_still_runs(
    tiny: GitRepo, tmp_path: Path
) -> None:
    """A stage job is skipped only by a hard failure; when: always runs anyway."""
    tpl = _gitlab_tpl(
        {
            "opt": {"stage": "one", "script": ["true"], "when": "manual"},
            "bad": {"stage": "one", "script": ["exit 2"]},
            "next": {"stage": "two", "script": ["echo WRONG"]},
            "notify": {"stage": "two", "when": "always", "script": ["echo RAN"]},
        }
    )
    res = _pipeline(tpl, tiny, tmp_path)
    assert res.status == {
        "opt": "manual",
        "bad": "failed",
        "next": "skipped",
        "notify": "success",
    }


# --------------------------------------------------------------------------- #
# the runner: GitHub steps, checkout depth, stubs, strip_git, cache (T10f)
# --------------------------------------------------------------------------- #


def test_github_job_stops_at_the_first_failed_step(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gh_tpl(
        [
            {"run": "echo one"},
            {"run": "exit 5"},
            {"run": "echo after"},
            {"run": "echo always", "if": "always()"},
        ]
    )
    run = ci.run_ci_job(
        _gh(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.exit_code == 5
    assert run.stdout.split() == ["one", "always"]
    assert [s for _, s in run.steps] == ["success", "failed", "skipped", "success"]


def test_github_step_env_overrides_job_env_for_that_step_only(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _gh_tpl(
        [{"run": 'echo "one $X"', "env": {"X": "step"}}, {"run": 'echo "two $X"'}],
        env={"X": "job"},
    )
    run = ci.run_ci_job(
        _gh(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.stdout.splitlines() == ["one step", "two job"]


@pytest.mark.parametrize(("with_", "count"), [({}, "1"), ({"fetch-depth": 0}, "3")])
def test_github_checkout_depth(
    with_: dict, count: str, tiny: GitRepo, tmp_path: Path
) -> None:
    step: dict = {"uses": "actions/checkout@v4"}
    if with_:
        step["with"] = with_
    tpl = _gh_tpl([step, {"run": "git rev-list --count HEAD"}])
    run = ci.run_ci_job(
        _gh(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.stdout.strip() == count


@pytest.mark.parametrize(("depth", "count"), [(None, "3"), ("1", "1"), ("0", "3")])
def test_gitlab_checkout_depth_and_detached_head(
    depth: str | None, count: str, tiny: GitRepo, tmp_path: Path
) -> None:
    variables = {} if depth is None else {"GIT_DEPTH": depth}
    tpl = _echo_job(
        variables, "git rev-list --count HEAD; git rev-parse --abbrev-ref HEAD"
    )
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.stdout.split() == [count, "HEAD"]


def test_job_runs_at_an_older_head(tiny: GitRepo, tmp_path: Path) -> None:
    older = tiny.git("rev-parse", "HEAD~1").strip()
    tpl = _echo_job({}, "cat f.txt; echo $CI_COMMIT_SHA")
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny, head=older), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.stdout.split() == ["2", older]


def test_fresh_gitlab_workspace_is_clean(tiny: GitRepo, tmp_path: Path) -> None:
    """The harness's own .venv shims are git-excluded, so a fresh checkout of a
    repo with no .gitignore reports a clean tree."""
    tpl = _gitlab_tpl({"j": {"stage": "one", "script": ["git status --porcelain"]}})
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.exit_code == 0, run.stderr
    assert not (run.workspace / ".gitignore").exists()
    assert (run.workspace / ".venv" / "bin" / "cdx").is_file()  # shims are there
    assert run.stdout == ""


def test_strip_git_hides_git_and_keeps_path_precedence(
    tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _echo_job({}, "command -v git || echo NOGIT; command -v bash")
    job = _gl(tpl, "j", tiny)
    stripped = ci.run_ci_job(
        job, tiny, tmp=tmp_path / "s", forge_state=None, strip_git=True
    )
    assert stripped.exit_code == 0, stripped.stderr
    first, bash_path = stripped.stdout.split()
    assert first == "NOGIT"
    assert os.path.realpath(bash_path) == os.path.realpath(shutil.which("bash") or "")
    plain = ci.run_ci_job(job, tiny, tmp=tmp_path / "p", forge_state=None)
    assert "NOGIT" not in plain.stdout


@pytest.mark.parametrize("tool", [*ci.LOUD_STUBS, *ci.SERVER_LAUNCHERS])
def test_unmodelled_tools_are_loud_stubs(
    tool: str, tiny: GitRepo, tmp_path: Path
) -> None:
    tpl = _echo_job({}, f"{tool} --version")
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.exit_code == ci.STUB_EXIT
    assert "not modelled by the executed-CI harness" in run.stderr


def test_harness_models_the_state_cache_steps(tiny: GitRepo, tmp_path: Path) -> None:
    """T10f: cache steps are recorded, always miss, and never restore state."""
    tpl = _gh_tpl(
        [
            {"uses": "actions/checkout@v4"},
            {
                "uses": "actions/cache/restore@v4",
                "with": {"path": ".cdmon", "key": "cdx-state-${{ github.ref_name }}"},
            },
            {
                "run": "ls .cdmon 2>/dev/null && echo RESTORED; mkdir -p .cdmon; "
                "echo x > .cdmon/state"
            },
            {"run": "exit 2"},
            {
                "uses": "actions/cache/save@v4",
                "if": "always()",
                "with": {"path": ".cdmon", "key": "cdx-state-${{ github.sha }}"},
            },
        ]
    )
    job = _gh(tpl, "j", tiny)
    first = ci.run_ci_job(job, tiny, tmp=tmp_path / "ci", forge_state=None)
    second = ci.run_ci_job(job, tiny, tmp=tmp_path / "ci", forge_state=None)
    for run in (first, second):
        assert run.exit_code == 2
        assert "RESTORED" not in run.stdout
        assert [(e["action"], e["hit"]) for e in run.cache_events] == [
            ("restore", False),
            ("save", None),
        ]
    assert first.workspace != second.workspace
    with pytest.raises(ci.NotModelled, match="actions/cache@"):
        _gh(_gh_tpl([{"uses": "actions/cache@v4", "with": {"path": "x"}}]), "j", tiny)


def test_github_unmodelled_step_shapes_are_refused(tiny: GitRepo) -> None:
    for step in (
        {"uses": "actions/upload-artifact@v4"},
        {"run": "true", "working-directory": "x"},
        {"run": "true", "if": "success() && github.ref == 'x'"},
        {"run": "true", "shell": "pwsh"},
        {"uses": "actions/checkout@v4", "with": {"ref": "x"}},
    ):
        with pytest.raises(ci.NotModelled):
            _gh(_gh_tpl([step]), "j", tiny)


def test_exit_code_is_the_first_failure(tiny: GitRepo, tmp_path: Path) -> None:
    tpl = _gh_tpl([{"run": "exit 5"}, {"run": "exit 7", "if": "always()"}])
    run = ci.run_ci_job(
        _gh(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None
    )
    assert run.exit_code == 5
    assert [s for _, s in run.steps] == ["failed", "failed"]


def test_unselected_github_job_is_not_run(tiny: GitRepo, tmp_path: Path) -> None:
    tpl = _gh_tpl([{"run": "echo RAN"}])
    tpl["jobs"]["j"]["if"] = "github.ref_name == 'other'"
    job = _gh(tpl, "j", tiny)
    assert job.selected is False
    with pytest.raises(ValueError, match="not selected"):
        ci.run_ci_job(job, tiny, tmp=tmp_path / "ci", forge_state=None)


@pytest.mark.parametrize(
    ("expr", "want"),
    [
        ("github.ref_name == 'main' && github.ref_name == 'other'", False),
        ("github.ref_name == 'other' && github.ref_name == 'main'", False),
        ("github.ref_name == 'main' && github.event_name == 'push'", True),
        ("github.ref == 'REFS/HEADS/MAIN'", True),
        ("github.ref != 'Refs/Heads/Main'", False),
    ],
)
def test_github_job_if_and_is_case_insensitive(
    expr: str, want: bool, tiny: GitRepo
) -> None:
    """`&&` needs both sides; GitHub string comparison ignores case."""
    tpl = _gh_tpl([{"run": "true"}])
    tpl["jobs"]["j"]["if"] = expr
    assert _gh(tpl, "j", tiny).selected is want


def test_services_are_refused_at_run_time(tiny: GitRepo, tmp_path: Path) -> None:
    tpl = _gitlab_tpl(
        {"j": {"stage": "one", "script": ["echo RAN"], "services": ["postgres:16"]}}
    )
    job = _gl(tpl, "j", tiny)
    with pytest.raises(ci.NotModelled, match="services"):
        ci.run_ci_job(job, tiny, tmp=tmp_path / "ci", forge_state=None)


def test_strip_git_keeps_path_order_and_hides_git_helpers(
    tiny: GitRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first PATH dir still wins, and git-* helpers vanish with git."""
    first, second = tmp_path / "first", tmp_path / "second"
    for d, word in ((first, "one"), (second, "two")):
        d.mkdir()
        tool = d / "probetool"
        tool.write_text(f"#!/bin/sh\necho {word}\n")
        tool.chmod(0o755)
    helper = first / "git-probehelper"
    helper.write_text("#!/bin/sh\necho HELPER\n")
    helper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{first}:{second}:{os.environ['PATH']}")
    tpl = _echo_job({}, "probetool; command -v git-probehelper || echo NOHELPER")
    run = ci.run_ci_job(
        _gl(tpl, "j", tiny), tiny, tmp=tmp_path / "ci", forge_state=None, strip_git=True
    )
    assert run.exit_code == 0, run.stderr
    assert run.stdout.split() == ["one", "NOHELPER"]


# --------------------------------------------------------------------------- #
# the fake forge (in-process)
# --------------------------------------------------------------------------- #


@pytest.fixture
def ff(tiny: GitRepo, tmp_path: Path) -> forge.FakeForge:
    state = tmp_path / "forge.json"
    forge.seed_forge(state, tiny)
    return forge.FakeForge(state, log_path=tmp_path / "http.jsonl")


def _gl_url(rest: str) -> str:
    return f"{forge.GITLAB_API_URL}/projects/{forge.GITLAB_PROJECT_ID}/{rest}"


def _gh_url(rest: str) -> str:
    return f"{forge.GITHUB_API_URL}/repos/{forge.GITHUB_REPOSITORY}/{rest}"


def _plan(branch: str = "cdmon/docs-sync-abc", path: str = "f.txt") -> MergeRequestPlan:
    return MergeRequestPlan(
        source_branch=branch,
        target_branch="main",
        title="docs: sync",
        description="d",
        files=((path, "healed\n"),),
    )


def test_fake_forge_rejects_a_duplicate_branch(ff: forge.FakeForge) -> None:
    body = {"branch": "b1", "ref": "main"}
    ff.request("POST", _gl_url("repository/branches"), body=body, token="t")
    with pytest.raises(TransportError) as err:
        ff.request("POST", _gl_url("repository/branches"), body=body, token="t")
    assert isinstance(err.value, forge.FakeForgeHTTPError) and err.value.status == 400
    # the same refusal through the real transport, end to end
    transport = GitLabTransport(
        project_id=forge.GITLAB_PROJECT_ID,
        token="t",
        api_url=forge.GITLAB_API_URL,
        http=ff,
    )
    transport.submit(_plan())
    with pytest.raises(TransportError):
        transport.submit(_plan())
    gh = GitHubTransport(
        owner="acme", repo="widget", token="t", api_url=forge.GITHUB_API_URL, http=ff
    )
    gh.submit(_plan("gh-b"))
    with pytest.raises(TransportError) as gh_err:
        gh.submit(_plan("gh-b"))
    assert isinstance(gh_err.value, forge.FakeForgeHTTPError)
    assert gh_err.value.status == 422


def test_fake_forge_ids_differ_from_iids_and_the_wrong_one_is_404(
    ff: forge.FakeForge,
) -> None:
    gl = GitLabTransport(
        project_id=forge.GITLAB_PROJECT_ID,
        token="t",
        api_url=forge.GITLAB_API_URL,
        http=ff,
    )
    mr = gl.submit(_plan())
    assert mr["id"] != mr["iid"]
    assert mr["web_url"] == f"{forge.GITLAB_PROJECT_URL}/-/merge_requests/{mr['iid']}"
    assert (
        ff.request("GET", _gl_url(f"merge_requests/{mr['iid']}"), body=None, token="t")[
            "id"
        ]
        == mr["id"]
    )
    with pytest.raises(forge.FakeForgeHTTPError) as err:
        ff.request("GET", _gl_url(f"merge_requests/{mr['id']}"), body=None, token="t")
    assert err.value.status == 404
    gh = GitHubTransport(
        owner="acme", repo="widget", token="t", api_url=forge.GITHUB_API_URL, http=ff
    )
    pr = gh.submit(_plan("gh-b"))
    assert pr["id"] != pr["number"]
    with pytest.raises(forge.FakeForgeHTTPError) as gh_err:
        ff.request("GET", _gh_url(f"pulls/{pr['id']}"), body=None, token="t")
    assert gh_err.value.status == 404
    with pytest.raises(forge.FakeForgeHTTPError):
        ff.request(
            "POST",
            _gh_url(f"issues/{pr['id']}/comments"),
            body={"body": "x"},
            token="t",
        )


def test_fake_forge_duplicate_open_mr_is_refused_until_closed(
    ff: forge.FakeForge,
) -> None:
    ff.request(
        "POST",
        _gl_url("repository/branches"),
        body={"branch": "s", "ref": "main"},
        token="t",
    )
    mr_body = {
        "source_branch": "s",
        "target_branch": "main",
        "title": "t",
        "description": "d",
    }
    mr = ff.request("POST", _gl_url("merge_requests"), body=mr_body, token="t")
    with pytest.raises(forge.FakeForgeHTTPError) as err:
        ff.request("POST", _gl_url("merge_requests"), body=mr_body, token="t")
    assert err.value.status == 409
    ff.close("gitlab", mr["iid"])
    again = ff.request("POST", _gl_url("merge_requests"), body=mr_body, token="t")
    assert again["iid"] == mr["iid"] + 1
    # GitHub: 422 for a duplicate open PR from the same head
    ff.request(
        "POST",
        _gh_url("git/refs"),
        body={"ref": "refs/heads/s", "sha": ff.branch_head("github", "main")},
        token="t",
    )
    pr_body = {"title": "t", "head": "s", "base": "main", "body": "d"}
    pr = ff.request("POST", _gh_url("pulls"), body=pr_body, token="t")
    with pytest.raises(forge.FakeForgeHTTPError) as gh_err:
        ff.request("POST", _gh_url("pulls"), body=pr_body, token="t")
    assert gh_err.value.status == 422
    ff.close("github", pr["number"])
    ff.request("POST", _gh_url("pulls"), body=pr_body, token="t")


def test_fake_forge_listing(ff: forge.FakeForge) -> None:
    for n in range(3):
        ff.request(
            "POST",
            _gl_url("repository/branches"),
            body={"branch": f"s{n}", "ref": "main"},
            token="t",
        )
        ff.request(
            "POST",
            _gl_url("merge_requests"),
            body={
                "source_branch": f"s{n}",
                "target_branch": "main",
                "title": "t",
                "description": "d",
            },
            token="t",
        )
    ff.close("gitlab", 1)

    def iids(query: str) -> list[int]:
        res = ff.request("GET", _gl_url(f"merge_requests{query}"), body=None, token="t")
        return [m["iid"] for m in res]

    assert iids("") == [3, 2, 1]  # GitLab default: every state
    assert iids("?state=opened") == [3, 2]
    assert iids("?state=opened&source_branch=s1") == [2]
    assert iids("?per_page=2") == [3, 2]
    assert iids("?per_page=2&page=2") == [1]
    assert iids("?per_page=1000&page=1") == [3, 2, 1]
    assert ff.page_limits("gitlab") == (20, 100)
    assert ff.page_limits("github") == (30, 100)
    main = ff.branch_head("github", "main")
    for n in range(2):
        ff.request(
            "POST",
            _gh_url("git/refs"),
            body={"ref": f"refs/heads/h{n}", "sha": main},
            token="t",
        )
        ff.request(
            "POST",
            _gh_url("pulls"),
            body={"title": "t", "head": f"h{n}", "base": "main", "body": ""},
            token="t",
        )
    ff.close("github", 1)

    def numbers(query: str) -> list[int]:
        res = ff.request("GET", _gh_url(f"pulls{query}"), body=None, token="t")
        return [p["number"] for p in res]

    assert numbers("") == [2]  # GitHub default: open only
    assert numbers("?state=all") == [2, 1]
    assert numbers("?state=all&head=acme:h0") == [1]
    assert numbers("?state=all&head=someone-else:h0") == []
    with pytest.raises(forge.FakeForgeHTTPError) as err:
        ff.request("GET", _gh_url("pulls?head=h0"), body=None, token="t")
    assert err.value.status == 422


def test_fake_forge_gitlab_commit_refreshes_the_open_mr_sha(
    ff: forge.FakeForge,
) -> None:
    """A commit on an open MR's source branch moves that MR's sha, as on GitLab.

    A closed MR on the same branch and an open MR on another branch keep theirs.
    """

    def open_mr(source: str) -> dict:
        res: dict = ff.request(
            "POST",
            _gl_url("merge_requests"),
            body={"source_branch": source, "target_branch": "main", "title": source},
            token="t",
        )
        return res

    for name in ("b", "o"):
        ff.request(
            "POST",
            _gl_url("repository/branches"),
            body={"branch": name, "ref": "main"},
            token="t",
        )
    stale = open_mr("b")
    ff.close("gitlab", stale["iid"])
    mr = open_mr("b")
    other = open_mr("o")
    commit = ff.request(
        "POST",
        _gl_url("repository/commits"),
        body={
            "branch": "b",
            "commit_message": "m",
            "actions": [{"action": "update", "file_path": "f.txt", "content": "9"}],
        },
        token="t",
    )
    got = ff.request(
        "GET", _gl_url(f"merge_requests/{mr['iid']}"), body=None, token="t"
    )
    assert got["sha"] == commit["id"] == ff.branch_head("gitlab", "b")
    for kept in (stale, other):
        now = ff.request(
            "GET", _gl_url(f"merge_requests/{kept['iid']}"), body=None, token="t"
        )
        assert now["sha"] == kept["sha"] != commit["id"]


def test_fake_forge_git_data_semantics(ff: forge.FakeForge) -> None:
    main = ff.branch_head("github", "main")
    base = ff.request("GET", _gh_url(f"git/commits/{main}"), body=None, token="t")
    entries = [{"path": "f.txt", "mode": "100644", "type": "blob", "content": "x"}]
    t1 = ff.request(
        "POST",
        _gh_url("git/trees"),
        body={"base_tree": base["tree"]["sha"], "tree": entries},
        token="t",
    )
    t2 = ff.request(
        "POST",
        _gh_url("git/trees"),
        body={"base_tree": base["tree"]["sha"], "tree": entries},
        token="t",
    )
    assert t1["sha"] == t2["sha"]  # content-addressed
    c = ff.request(
        "POST",
        _gh_url("git/commits"),
        body={"message": "m", "tree": t1["sha"], "parents": [main]},
        token="t",
    )
    ff.request(
        "POST",
        _gh_url("git/refs"),
        body={"ref": "refs/heads/x", "sha": c["sha"]},
        token="t",
    )
    # a non-fast-forward update is refused unless forced
    other = ff.request(
        "POST",
        _gh_url("git/commits"),
        body={"message": "o", "tree": t1["sha"], "parents": [main]},
        token="t",
    )
    with pytest.raises(forge.FakeForgeHTTPError) as err:
        ff.request(
            "PATCH", _gh_url("git/refs/heads/x"), body={"sha": other["sha"]}, token="t"
        )
    assert err.value.status == 422
    ff.request(
        "PATCH",
        _gh_url("git/refs/heads/x"),
        body={"sha": other["sha"], "force": True},
        token="t",
    )
    # an MR/PR needs existing branches
    with pytest.raises(forge.FakeForgeHTTPError):
        ff.request(
            "POST",
            _gh_url("pulls"),
            body={"title": "t", "head": "nope", "base": "main", "body": ""},
            token="t",
        )
    with pytest.raises(forge.FakeForgeHTTPError):
        ff.request(
            "POST",
            _gl_url("merge_requests"),
            body={
                "source_branch": "nope",
                "target_branch": "main",
                "title": "t",
                "description": "",
            },
            token="t",
        )
    # a GitLab update of a path absent from the branch is refused
    ff.request(
        "POST",
        _gl_url("repository/branches"),
        body={"branch": "s", "ref": "main"},
        token="t",
    )
    with pytest.raises(forge.FakeForgeHTTPError) as gl_err:
        ff.request(
            "POST",
            _gl_url("repository/commits"),
            body={
                "branch": "s",
                "commit_message": "m",
                "actions": [
                    {"action": "update", "file_path": "nope.md", "content": "x"}
                ],
            },
            token="t",
        )
    assert gl_err.value.status == 400


def test_fake_forge_hooks_and_all_or_nothing(
    ff: forge.FakeForge, tmp_path: Path
) -> None:
    gl = GitLabTransport(
        project_id=forge.GITLAB_PROJECT_ID,
        token="t",
        api_url=forge.GITLAB_API_URL,
        http=ff,
    )
    mr = gl.submit(_plan())
    before = ff.mr("gitlab", mr["iid"])["sha"]
    moved = ff.human_commit("gitlab", mr["iid"])
    assert moved != before and ff.mr("gitlab", mr["iid"])["sha"] == moved
    snapshot = ff.state_path.read_bytes()
    with pytest.raises(forge.FakeForgeHTTPError) as err:
        ff.request(
            "POST",
            _gl_url("merge_requests"),
            body={
                "source_branch": "nope",
                "target_branch": "main",
                "title": "t",
                "description": "",
            },
            token="t",
        )
    assert ff.state_path.read_bytes() == snapshot
    with pytest.raises(forge.FakeForgeHTTPError) as auth:
        ff.request("GET", _gl_url("merge_requests"), body=None, token="")
    assert auth.value.status == 401
    with pytest.raises(forge.FakeForgeHTTPError) as wrong:
        ff.request(
            "GET",
            "https://elsewhere.invalid/api/v4/projects/1/merge_requests",
            body=None,
            token="t",
        )
    assert wrong.value.status == 404
    del err
    log = [json.loads(x) for x in (tmp_path / "http.jsonl").read_text().splitlines()]
    assert log and all(e.get("token") != "t" for e in log)
    assert log[-1]["status"] == 404 and log[-2]["authorized"] is False
    assert [e["method"] for e in log[:3]] == ["POST", "POST", "POST"]


@pytest.mark.parametrize("provider", ["gitlab", "github"])
def test_fake_forge_per_page_is_capped(provider: str, ff: forge.FakeForge) -> None:
    _default, cap = ff.page_limits(provider)
    items = [{"n": n} for n in range(cap + 50)]
    got = forge.FakeForge._page(items, {"per_page": str(cap * 10)}, provider)
    assert len(got) == cap


def test_fake_forge_github_duplicate_ref_is_422(ff: forge.FakeForge) -> None:
    main = ff.branch_head("github", "main")
    body = {"ref": "refs/heads/dup", "sha": main}
    ff.request("POST", _gh_url("git/refs"), body=body, token="t")
    with pytest.raises(forge.FakeForgeHTTPError, match="already exists") as err:
        ff.request("POST", _gh_url("git/refs"), body=body, token="t")
    assert err.value.status == 422


def test_fake_forge_tree_sha_ignores_entry_order(ff: forge.FakeForge) -> None:
    """Content addressing is order-independent (K10)."""
    main = ff.branch_head("github", "main")
    base = ff.request("GET", _gh_url(f"git/commits/{main}"), body=None, token="t")
    a = {"path": "a.txt", "mode": "100644", "type": "blob", "content": "A"}
    b = {"path": "b.txt", "mode": "100644", "type": "blob", "content": "B"}
    shas = [
        ff.request(
            "POST",
            _gh_url("git/trees"),
            body={"base_tree": base["tree"]["sha"], "tree": entries},
            token="t",
        )["sha"]
        for entries in ([a, b], [b, a])
    ]
    assert shas[0] == shas[1]


# --------------------------------------------------------------------------- #
# the shim (in-process)
# --------------------------------------------------------------------------- #


def test_shim_tripwires_in_process(tmp_path: Path) -> None:
    from custodex import pr, registry, sinks

    real = (
        urllib.request.urlopen,
        socket.socket.connect,
        backends._default_process_runner,
    )

    # Each layer is pinned by its OWN message: the layers overlap (urlopen does
    # a name lookup; create_connection does too), so matching only the shared
    # mark would let a removed layer hide behind the one beneath it.
    def trip(layer: str) -> Any:
        return pytest.raises(AssertionError, match=f"{shim.TRIPWIRE_MARK}: {layer}")

    with shim.installed({}):
        with trip(r"urllib\.request\.urlopen\("):
            urllib.request.urlopen("https://example.invalid/")
        for family, addr in (
            (socket.AF_INET, ("192.0.2.1", 443)),
            (socket.AF_INET6, ("2001:db8::1", 443, 0, 0)),
        ):
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                with trip(r"socket\.connect\("):
                    sock.connect(addr)
                with trip(r"socket\.connect_ex\("):
                    sock.connect_ex(addr)
        with trip(r"socket\.getaddrinfo\("):
            socket.getaddrinfo("example.invalid", 443)
        assert socket.getaddrinfo("localhost", 443)  # loopback lookups stay usable
        with trip("LLM process runner"):
            backends._default_process_runner(["claude", "-p"], "", 1)
        with pytest.raises(AssertionError, match="has no fake forge"):
            pr._UrllibGitLabHttp().request("GET", "https://x", body=None, token="t")
        with pytest.raises(AssertionError, match="CDX_FAKE_CENTRAL_LOG"):
            registry._UrllibRegisterHttp().request(
                "POST", "https://x", body={}, token=""
            )
        with pytest.raises(AssertionError, match="CDX_FAKE_CENTRAL_LOG"):
            sinks._UrllibClient().post("https://x", data=b"{}", headers={})
        # AF_UNIX stays usable (local IPC is not network)
        path = str(tmp_path / "s.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(path)
        client.close()
        server.close()
    assert (
        urllib.request.urlopen,
        socket.socket.connect,
        backends._default_process_runner,
    ) == real


def test_shim_guards_the_agent_runtime_alias() -> None:
    runtime = pytest.importorskip("custodex.agent.runtime")
    real = runtime._default_process_runner
    with (
        shim.installed({}),
        pytest.raises(AssertionError, match=f"{shim.TRIPWIRE_MARK}: LLM process"),
    ):
        runtime._default_process_runner(["claude"], "", 1)
    assert runtime._default_process_runner is real


def test_shim_origin_guard_refuses_a_decoy_custodex(tmp_path: Path) -> None:
    import types

    shim.assert_custodex_origin()  # the real modules come from this checkout
    decoy = types.ModuleType("custodex.decoy")
    decoy.__file__ = str(tmp_path / "elsewhere" / "custodex" / "decoy.py")
    import sys

    modules = {**sys.modules, "custodex.decoy": decoy}
    with pytest.raises(AssertionError, match="custodex.decoy"):
        shim.assert_custodex_origin(modules)
    # A sibling directory sharing the checkout's name as a prefix is outside it.
    sibling = types.ModuleType("custodex.decoy")
    sibling.__file__ = str(shim.REPO_ROOT) + "-decoy/custodex/decoy.py"
    with pytest.raises(AssertionError, match="custodex.decoy"):
        shim.assert_custodex_origin({**sys.modules, "custodex.decoy": sibling})


def test_shim_pins_the_clock() -> None:
    from custodex import cli, config

    stamp = "2030-01-01T00:00:00+00:00"
    reals = (monitor._default_now, cli._now, config._now)
    with shim.installed({shim.ENV_NOW: stamp}):
        assert monitor._default_now() == stamp
        assert cli._now() == stamp
        assert config._now() == stamp
    assert monitor._default_now is reals[0]
    assert cli._now is reals[1]
    assert config._now is reals[2]


@pytest.mark.parametrize(
    ("spec", "path", "declined"),
    [
        ("*", "docs/api.md", True),
        ("docs/api.md", "docs/api.md", True),
        ("docs/api.md", "/abs/ws/docs/api.md", True),
        ("docs/api.md", "/abs/ws/other/docs/api.mdx", False),
        ("docs/api.md", "/abs/xdocs/api.md", False),
        ("docs/api.md", "docs/other.md", False),
        ("api.md", "docs/api.md", False),
        ("", "docs/api.md", False),
        ("a.md,docs/api.md", "docs/api.md", True),
    ],
)
def test_shim_decline_matching(spec: str, path: str, declined: bool) -> None:
    assert shim.declined(Path(path), spec) is declined


def test_shim_central_recorder_kind_and_auth(tmp_path: Path) -> None:
    log = tmp_path / "central.jsonl"
    with shim.installed({shim.ENV_CENTRAL_LOG: str(log)}):
        sinks._UrllibClient().post("https://c/ingest", data=b"{}", headers={})
        sinks._UrllibClient().post(
            "https://c/ingest", data=b"{}", headers={"Authorization": "Bearer x"}
        )
        registry._UrllibRegisterHttp().request(
            "POST", "https://c/api/repos/sync/", body={}, token="t"
        )
        registry._UrllibRegisterHttp().request(
            "POST", "https://c/api/repos", body={}, token=""
        )
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert [(r["kind"], r["authorized"]) for r in rows] == [
        ("ingest", False),
        ("ingest", True),
        ("sync", True),
        ("register", False),
    ]


def test_shim_origin_guard_refuses_a_fileless_custodex() -> None:
    with pytest.raises(AssertionError, match="no __file__"):
        shim.assert_custodex_origin({"custodex": types.ModuleType("custodex")})


def test_shim_trips_spmirror_at_the_urlopen_layer() -> None:
    """The urlopen layer itself fires (the lower socket layers would also stop it)."""
    real = spmirror._urlopen
    with (
        shim.installed({}),
        pytest.raises(
            AssertionError, match=f"{shim.TRIPWIRE_MARK}: urllib.request.urlopen"
        ),
    ):
        spmirror._urlopen("https://example.invalid/", timeout=1)
    assert spmirror._urlopen is real


def test_shim_binds_the_github_leaf_to_the_fake_forge(ff: forge.FakeForge) -> None:
    with shim.installed({shim.ENV_FORGE_STATE: str(ff.state_path)}):
        res = pr._UrllibGitHubHttp().request(
            "GET", _gh_url("pulls?state=all"), body=None, token="t"
        )
    assert res == []


@pytest.mark.parametrize(("code", "want"), [("boom", 1), (3, 3), (None, 0)])
def test_shim_main_maps_system_exit(
    code: object, want: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from custodex import cli

    def fake_app(**_kw: object) -> None:
        raise SystemExit(code)

    monkeypatch.setattr(shim, "install", lambda env: lambda: None)
    monkeypatch.setattr(cli, "app", fake_app)
    assert shim.main([]) == want


# --------------------------------------------------------------------------- #
# executed: the shim through real jobs (T10, T10e) and K7
# --------------------------------------------------------------------------- #


def _cdx_job(adopter: ci.AdopterRepo, lines: list[str], **kw: object) -> ci.CiJob:
    tpl = {
        "stages": ["docs"],
        "variables": {"CDMON_CONFIG": "cdmon.yaml"},
        "j": {"stage": "docs", "script": lines},
    }
    args: dict = {"head": adopter.B, "branch": "main", "before": adopter.A}
    args.update(kw)
    return ci.gitlab_job(tpl, "j", **args)


def test_shim_tripwire_fails_an_unpatched_network_call(
    adopter: ci.AdopterRepo, tmp_path: Path
) -> None:
    """An unpatched leaf (the coverage-issue transport) trips the urlopen tripwire."""
    repo = adopter.repo
    repo.commit_files(
        "orphan", {"src/extra.py": "def orphan() -> int:\n    return 1\n"}
    )
    job = _cdx_job(
        adopter,
        ['.venv/bin/cdx surface-gaps --config "$CDMON_CONFIG"'],
        head=repo.head(),
    )
    run = ci.run_ci_job(job, repo, tmp=tmp_path / "ci", forge_state=None)
    assert run.exit_code != 0
    # the urlopen layer's own message, not just the shared mark (a name-lookup
    # trip beneath it would also carry the mark)
    assert f"{shim.TRIPWIRE_MARK}: urllib.request.urlopen(" in run.stderr


def test_shim_forge_call_without_forge_state_is_loud(
    adopter: ci.AdopterRepo, tmp_path: Path
) -> None:
    job = _cdx_job(adopter, ['.venv/bin/cdx open-docs-pr --config "$CDMON_CONFIG"'])
    run = ci.run_ci_job(job, adopter.repo, tmp=tmp_path / "ci", forge_state=None)
    assert run.exit_code != 0
    assert "has no fake forge" in run.stderr
    assert run.requests == ()


def test_shim_binds_the_real_transport_to_the_fake_forge(
    adopter: ci.AdopterRepo, tmp_path: Path
) -> None:
    state = tmp_path / "forge.json"
    forge.seed_forge(state, adopter.repo, heads={"main": adopter.B})
    job = _cdx_job(
        adopter,
        ['.venv/bin/cdx open-docs-pr --config "$CDMON_CONFIG" --ref "$CI_COMMIT_SHA"'],
    )
    run = ci.run_ci_job(job, adopter.repo, tmp=tmp_path / "ci", forge_state=state)
    assert run.exit_code == 0, run.stderr
    paths = [(r["method"], r["path"].split("?")[0]) for r in run.requests]
    base = f"/projects/{forge.GITLAB_PROJECT_ID}"
    assert paths == [
        ("POST", f"{base}/repository/branches"),
        ("POST", f"{base}/repository/commits"),
        ("POST", f"{base}/merge_requests"),
    ]
    assert all(r["authorized"] for r in run.requests)
    (mr,) = forge.FakeForge(state).merge_requests("gitlab")
    assert run.stdout.strip() == f"opened docs MR: {mr['web_url']}"
    assert mr["web_url"].startswith(job.predefined["CI_PROJECT_URL"] + "/")
    commit = run.requests[1]["body"]
    assert [a["file_path"] for a in commit["actions"]] == ["docs/api.md"]
    assert "depth: int = 1" in commit["actions"][0]["content"]
    assert adopter.B in mr["title"]


def test_shim_records_central_traffic_without_the_token(
    adopter: ci.AdopterRepo, tmp_path: Path
) -> None:
    auth_env = _central_auth_env(adopter)
    job = _cdx_job(
        adopter,
        [
            '.venv/bin/cdx register --config "$CDMON_CONFIG"',
            '.venv/bin/cdx monitor --apply --config "$CDMON_CONFIG"',
        ],
        variables={auth_env: _CENTRAL},
    )
    run = ci.run_ci_job(job, adopter.repo, tmp=tmp_path / "ci", forge_state=None)
    assert run.exit_code == 0, run.stderr
    kinds = [c["kind"] for c in run.central]
    assert kinds[0] == "register" and "ingest" in kinds
    assert all(c["authorized"] is True for c in run.central)
    assert run.central[0]["body"]["repo"]["commit"] == adopter.B
    ingest = [c for c in run.central if c["kind"] == "ingest"]
    assert ingest[0]["body"]["record"]["detected_at"] == ci.FAKE_NOW_DEFAULT
    raw = (run.run_dir / "central.jsonl").read_text()
    assert _CENTRAL not in raw
    # unauthenticated when the token is absent
    bare = _cdx_job(adopter, ['.venv/bin/cdx register --config "$CDMON_CONFIG"'])
    run2 = ci.run_ci_job(bare, adopter.repo, tmp=tmp_path / "ci2", forge_state=None)
    assert [c["authorized"] for c in run2.central] == [False]


@pytest.mark.parametrize("config", ["relative", "absolute"])
@pytest.mark.parametrize("spec", ["*", "docs/api.md"])
def test_shim_write_seam_is_live(
    config: str, spec: str, adopter: ci.AdopterRepo, tmp_path: Path
) -> None:
    """T10e: CDX_FAKE_DECLINE_WRITE declines the heal write; without it, it lands."""
    cfg = "cdmon.yaml" if config == "relative" else "$CI_PROJECT_DIR/cdmon.yaml"
    line = f'.venv/bin/cdx monitor --apply --config "{cfg}"; git diff --stat'
    job = _cdx_job(adopter, [line])
    declined = ci.run_ci_job(
        job,
        adopter.repo,
        tmp=tmp_path / "d",
        forge_state=None,
        fake_env={shim.ENV_DECLINE: spec},
    )
    # The drift WAS handled (a FIX was proposed) but the write was declined, so
    # the doc bytes are unchanged and the drift remains (monitor exits 1).
    assert "api: HASH -> FIX" in declined.stdout, declined.stdout
    assert "(applied)" not in declined.stdout
    assert declined.exit_code == 1
    assert "drift(s) remaining" in declined.stderr
    ws_doc = declined.workspace / "docs" / "api.md"
    src_doc = adopter.repo.git("show", f"{adopter.B}:docs/api.md")
    assert ws_doc.read_text() == src_doc
    healed = ci.run_ci_job(job, adopter.repo, tmp=tmp_path / "h", forge_state=None)
    assert healed.exit_code == 0, healed.stderr
    assert "api: HASH -> FIX (applied)" in healed.stdout
    assert "docs/api.md" in healed.stdout


def test_shim_nondet_salt_appends_only_after_a_real_write(
    adopter: ci.AdopterRepo, tmp_path: Path
) -> None:
    line = '.venv/bin/cdx monitor --apply --config "$CDMON_CONFIG"; cat docs/api.md'
    out = {}
    for salt in ("s1", "s2"):
        run = ci.run_ci_job(
            _cdx_job(adopter, [line]),
            adopter.repo,
            tmp=tmp_path / salt,
            forge_state=None,
            fake_env={shim.ENV_SALT: salt},
        )
        assert run.exit_code == 0, run.stderr
        out[salt] = run.stdout
        assert shim.salt_line(salt) in run.stdout
    assert out["s1"] != out["s2"]
    clean = ci.run_ci_job(
        _cdx_job(adopter, [line], head=adopter.A, before=None),
        adopter.repo,
        tmp=tmp_path / "clean",
        forge_state=None,
        fake_env={shim.ENV_SALT: "s3"},
    )
    assert (
        "clean — no drift remaining" in clean.stdout or "(applied)" not in clean.stdout
    )
    assert shim.salt_line("s3") not in clean.stdout


@pytest.mark.parametrize("changed", [False, True])
def test_shim_salt_needs_a_write_that_changed_bytes(
    changed: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The salt stands in for a nondeterministic backend: only a real write gets it.

    The seam wraps whatever ``monitor.apply_fix`` is at install time, so a stub
    that reports "no bytes changed" must leave the doc unsalted.
    """
    doc = tmp_path / "d.md"
    doc.write_text("x\n", encoding="utf-8")

    def stub(path: Path, fix: object, **kwargs: object) -> bool:
        return changed

    monkeypatch.setattr(monitor, "apply_fix", stub)
    with shim.installed({shim.ENV_SALT: "s"}):
        assert monitor.apply_fix(doc, object()) is changed  # type: ignore[arg-type]
    assert (shim.salt_line("s") in doc.read_text(encoding="utf-8")) is changed


def test_server_launchers_are_not_run_through_the_shim(
    adopter: ci.AdopterRepo, tmp_path: Path
) -> None:
    job = _cdx_job(adopter, ["cdx-server --help"])
    run = ci.run_ci_job(job, adopter.repo, tmp=tmp_path / "ci", forge_state=None)
    assert run.exit_code == ci.STUB_EXIT


def _normalise(run: ci.CiRun, tmp: Path) -> dict:
    def norm(text: str) -> str:
        return text.replace(str(tmp), "<TMP>")

    return {
        "exit": run.exit_code,
        "stdout": norm(run.stdout),
        "stderr": norm(run.stderr),
        "requests": norm(json.dumps(run.requests, sort_keys=True)),
        "central": norm(json.dumps(run.central, sort_keys=True)),
        "steps": run.steps,
    }


def _k7_job(kind: str, adopter: ci.AdopterRepo) -> ci.CiJob:
    auth = {_central_auth_env(adopter): _CENTRAL}
    if kind == "gitlab":
        return ci.gitlab_job(
            _GITLAB,
            "cdx-docs-pr",
            head=adopter.B,
            branch="main",
            before=adopter.A,
            variables=auth,
        )
    if kind == "github":
        return ci.github_job(
            _GITHUB,
            "cdx-docs-pr",
            head=adopter.B,
            branch="main",
            secrets={**auth, _GITHUB_TOKEN_ENV: "fake-gh"},
            before=adopter.A,
        )
    return _cdx_job(
        adopter,
        ['.venv/bin/cdx open-docs-pr --config "$CDMON_CONFIG" --ref "$CI_COMMIT_SHA"'],
        variables=auth,
    )


@pytest.mark.parametrize("kind", ["gitlab", "github", "gitlab-open"])
def test_two_runs_give_identical_logs(
    kind: str, adopter_src: ci.AdopterRepo, tmp_path: Path
) -> None:
    """K7: the same job on the same inputs gives byte-identical logs and state."""
    results = []
    for n in (1, 2):
        root = tmp_path / f"run{n}"
        adopter = ci.copy_adopter_repo(adopter_src, root / "adopter")
        state = root / "forge.json"
        forge.seed_forge(state, adopter.repo, heads={"main": adopter.B})
        run = ci.run_ci_job(
            _k7_job(kind, adopter), adopter.repo, tmp=root / "ci", forge_state=state
        )
        results.append((_normalise(run, root), state.read_bytes(), run))
    (one, s1, r1), (two, s2, _) = results
    assert one == two
    assert s1 == s2
    # never vacuous: the job really did something observable
    assert r1.stdout.strip()
    if kind != "github":
        # (today's GitHub template opens its PR through the GitLab transport and
        # exits 1 at that step — a template defect owned by CI-TEMPLATES; K7 here
        # is about the run being reproducible, which it is either way)
        assert r1.exit_code == 0, r1.stderr
    if kind == "gitlab-open":
        assert len(r1.requests) == 3
    else:
        assert r1.central, "no central traffic — the comparison would be vacuous"
