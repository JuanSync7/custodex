"""Adopter CI templates stay valid + honest (G-03).

The shipped templates under ``templates/ci/`` are drop-in CI for repos adopting
cdmon. These tests keep them HONEST against the real CLI:

* both YAML files ``yaml.safe_load`` cleanly (a malformed template would break an
  adopter's pipeline silently);
* every ``cdmon <subcommand>`` named in any script line is a REAL command the CLI
  exposes — so renaming/removing a command (e.g. ``check`` -> ``verify``) breaks
  this test, not the adopter's pipeline weeks later;
* the gate job references ``doctor`` + ``check`` + ``lint`` and the docs-PR job
  references ``should-sync`` + ``sync-pr``/``open-docs-pr`` (the documented flow).

Nothing here executes CI — the templates are shipped + validated, not run (K4).
"""

from __future__ import annotations

import re
from pathlib import Path

import typer
import yaml

from code_doc_monitor.cli import app

_TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "ci"
_GITLAB = _TEMPLATES / "gitlab-ci.adopter.yml"
_GITHUB = _TEMPLATES / "github-actions.adopter.yml"

# Every `cdmon <token>` occurrence in a script line. `<token>` is the first
# non-flag word after `cdmon`; the `--config`/`--apply` flags are skipped.
_CDMON_CALL = re.compile(r"\bcdmon\s+([a-z][a-z0-9-]*)")


def _real_commands() -> set[str]:
    """The canonical click command names the `cdmon` CLI exposes (one source)."""
    return set(typer.main.get_command(app).commands.keys())


def _strip_comment(line: str) -> str:
    """Drop a trailing shell ``#`` comment so prose in comments is not parsed.

    Only the actual command text counts toward the honesty check; a ``#`` that is
    not preceded by whitespace/line-start (e.g. a URL fragment) is left intact.
    """
    out = re.sub(r"(^|\s)#.*$", "", line)
    return out


def _script_lines(path: Path) -> list[str]:
    """The actual command/script lines of a template (NOT YAML comments/prose).

    Parses the YAML and collects GitLab ``script`` lists (incl. the shared
    ``&cdmon-setup`` anchor) and GitHub ``steps[].run`` blocks. Comment-only lines
    and trailing ``# ...`` comments are stripped so the honesty check sees only the
    commands an adopter's shell would actually run.
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw: list[str] = []

    def _collect(value: object) -> None:
        if isinstance(value, str):
            raw.extend(value.splitlines())
        elif isinstance(value, list):
            for item in value:
                _collect(item)

    def _scan_job(job: object) -> None:
        if not isinstance(job, dict):
            return
        # GitLab: a job carries `script`; the .cdmon-setup anchor does too.
        if "script" in job:
            _collect(job["script"])
        # GitHub: job.steps[].run
        steps = job.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and "run" in step:
                    _collect(step["run"])

    # GitLab jobs live at the top level; GitHub jobs live under `jobs:`.
    for job in doc.values():
        _scan_job(job)
    for job in (doc.get("jobs") or {}).values():
        _scan_job(job)

    return [_strip_comment(ln) for ln in raw]


def _referenced_subcommands(path: Path) -> set[str]:
    """Every distinct subcommand token in a template's actual command lines."""
    found: set[str] = set()
    for line in _script_lines(path):
        found.update(_CDMON_CALL.findall(line))
    return found


def test_templates_are_valid_yaml() -> None:
    for path in (_GITLAB, _GITHUB):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict), f"{path.name} did not parse to a mapping"


def test_templates_reference_only_real_subcommands() -> None:
    real = _real_commands()
    for path in (_GITLAB, _GITHUB):
        referenced = _referenced_subcommands(path)
        assert referenced, f"{path.name} referenced no cdmon subcommands"
        unknown = referenced - real
        assert not unknown, (
            f"{path.name} references cdmon command(s) the CLI does not expose: "
            f"{sorted(unknown)} (known: {sorted(real)})"
        )


def test_gate_job_runs_doctor_check_lint() -> None:
    for path in (_GITLAB, _GITHUB):
        referenced = _referenced_subcommands(path)
        assert {"doctor", "check", "lint"} <= referenced, (
            f"{path.name} gate must run doctor + check + lint"
        )


def test_docs_pr_job_guards_with_should_sync_and_opens_a_pr() -> None:
    for path in (_GITLAB, _GITHUB):
        referenced = _referenced_subcommands(path)
        assert "should-sync" in referenced, f"{path.name} must guard with should-sync"
        assert "monitor" in referenced, f"{path.name} must heal with monitor --apply"
        assert "open-docs-pr" in referenced, f"{path.name} must open a docs PR"


def test_gitlab_template_has_both_jobs() -> None:
    doc = yaml.safe_load(_GITLAB.read_text(encoding="utf-8"))
    assert "cdmon-gate" in doc
    assert "cdmon-docs-pr" in doc


def test_github_template_has_both_jobs() -> None:
    doc = yaml.safe_load(_GITHUB.read_text(encoding="utf-8"))
    jobs = doc.get("jobs", {})
    assert "cdmon-gate" in jobs
    assert "cdmon-docs-pr" in jobs
