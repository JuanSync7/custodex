"""X-CONTAIN — the CLI agrees with itself on a dotdot doc path (offline).

`cdx check`, `cdx okf`, `cdx monitor --apply`, `cdx build` and `cdx open-docs-pr`
all name a doc by ``doc_path(root, spec.path)`` = ``normpath(root / spec.path)``, so a
config spelling ``nope/../docs/guide.md`` or ``link/../docs/guide.md`` grades,
heals, exports and commits ONE file — the one a reader of the config means.

Features: FEAT-CONFIGV2-019
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from custodex import cli
from custodex.cli import app
from custodex.reviewlog import read_all

runner = CliRunner()

_CONFIG = (
    'version: "1.0.0"\n'
    'root: "."\n'
    "documents:\n"
    "  - id: guide\n"
    "    path: {path}\n"
    "    audience: user-guide\n"
    "    region_keys: [symbols]\n"
    "    code_refs: [{{path: src/lib.py}}]\n"
)
_LIB = 'def connect(host: str) -> None:\n    """Open."""\n'
_DOC = (
    "# Guide\n\n> How to connect.\n\n"
    "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
)
_DECOY = (
    "# Decoy\n\n> Not this file.\n\n"
    "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
)
FORMS = {"nope": "nope/../docs/guide.md", "link": "link/../docs/guide.md"}


def _project(tmp_path: Path, form: str, *, path: str | None = None) -> Path:
    """An unhealed single-file project at ``tmp_path / "proj"``."""
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "docs").mkdir()
    (proj / "src" / "lib.py").write_text(_LIB, encoding="utf-8")
    (proj / "docs" / "guide.md").write_text(_DOC, encoding="utf-8")
    if form == "link":
        hub = tmp_path / "hub"
        (hub / "sub").mkdir(parents=True)
        (hub / "docs").mkdir()
        (hub / "docs" / "guide.md").write_text(_DECOY, encoding="utf-8")
        (proj / "link").symlink_to(hub / "sub", target_is_directory=True)
    (proj / "cdmon.yaml").write_text(
        _CONFIG.format(path=path or FORMS[form]), encoding="utf-8"
    )
    return proj


def _decoy(tmp_path: Path) -> bytes | None:
    hub_doc = tmp_path / "hub" / "docs" / "guide.md"
    return hub_doc.read_bytes() if hub_doc.is_file() else None


def _ok(args: list[str]) -> str:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.parametrize("form", FORMS)
def test_check_and_okf_agree_on_a_dotdot_doc_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    """The contract flip of the old ``[unnormalized]`` okf case: a healed,
    human-accepted doc re-pointed through dotdot stays clean AND verified."""
    # Feature: FEAT-CONFIGV2-019
    proj = _project(tmp_path, form, path="docs/guide.md")
    monkeypatch.chdir(proj)
    _ok(["monitor", "--apply"])
    records = read_all(proj / ".cdmon" / "review-log.jsonl")
    record_id = next(r.record_id for r in records if r.drift_kind == "HASH")
    _ok(["resolve", record_id, "--resolution", "accepted", "--by", "alice"])
    cfg = proj / "cdmon.yaml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace("docs/guide.md", FORMS[form]),
        encoding="utf-8",
    )
    _ok(["check"])
    _ok(["okf"])
    bundle_doc = proj / ".cdmon" / "okf" / "docs" / "guide.md"
    text = bundle_doc.read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---\n")[1])
    assert [e["by"] for e in front.get("verified") or ()] == ["human:alice"]
    assert "How to connect." in text


@pytest.mark.parametrize("form", FORMS)
def test_monitor_apply_twice_after_a_code_change_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    """K7 on the dotdot path: heal, change code, heal, then a no-op run."""
    # Feature: FEAT-CONFIGV2-019
    proj = _project(tmp_path, form)
    decoy = _decoy(tmp_path)
    monkeypatch.chdir(proj)
    _ok(["monitor", "--apply"])
    _ok(["check"])
    (proj / "src" / "lib.py").write_text(
        _LIB + "\n\ndef close(handle: int) -> None:\n    pass\n", encoding="utf-8"
    )
    _ok(["monitor", "--apply"])
    _ok(["check"])
    log = proj / ".cdmon" / "review-log.jsonl"
    lines = log.read_text(encoding="utf-8").count("\n")
    _ok(["monitor", "--apply"])
    assert log.read_text(encoding="utf-8").count("\n") == lines
    text = (proj / "docs" / "guide.md").read_text(encoding="utf-8")
    assert "close" in text and "> How to connect." in text
    assert _decoy(tmp_path) == decoy
    assert not (proj / "nope").exists()


def test_a_leading_dotdot_doc_under_a_symlinked_root_is_lexical(
    tmp_path: Path,
) -> None:
    """The documented behaviour change: the repo root is lexical (N-06), so a
    ``../shared`` doc is the sibling OF THAT ROOT AS NAMED — not the sibling of
    wherever a symlinked root physically lives."""
    # Feature: FEAT-CONFIGV2-019
    real = tmp_path / "real"
    proj_real = real / "proj"
    (proj_real / "src").mkdir(parents=True)
    (proj_real / "src" / "lib.py").write_text(_LIB, encoding="utf-8")
    (proj_real / "cdmon.yaml").write_text(
        _CONFIG.format(path="../shared/guide.md"), encoding="utf-8"
    )
    (real / "shared").mkdir()
    (real / "shared" / "guide.md").write_text(_DECOY, encoding="utf-8")
    named = tmp_path / "named"
    (named / "shared").mkdir(parents=True)
    (named / "shared" / "guide.md").write_text(_DOC, encoding="utf-8")
    (named / "proj").symlink_to(proj_real, target_is_directory=True)
    decoy = (real / "shared" / "guide.md").read_bytes()

    cfg = str(named / "proj" / "cdmon.yaml")
    _ok(["monitor", "--apply", "--config", cfg])
    _ok(["check", "--config", cfg])
    healed = (named / "shared" / "guide.md").read_text(encoding="utf-8")
    assert "connect" in healed.split("CDM:BEGIN symbols", 1)[1]
    assert (real / "shared" / "guide.md").read_bytes() == decoy


class _FakeTransport:
    def __init__(self) -> None:
        self.plans: list[Any] = []

    def submit(self, plan: Any) -> dict:
        self.plans.append(plan)
        return {"web_url": "https://provider/mr/1"}


@pytest.mark.parametrize("form", FORMS)
def test_open_docs_pr_commits_the_healed_doc_at_its_normalised_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    # Feature: FEAT-CONFIGV2-019
    proj = _project(tmp_path, form)
    decoy = _decoy(tmp_path)
    monkeypatch.chdir(proj)
    fake = _FakeTransport()
    monkeypatch.setattr(cli.GitLabTransport, "from_env", classmethod(lambda c: fake))
    out = _ok(["open-docs-pr"])
    assert "opened docs MR" in out
    (plan,) = fake.plans
    healed = (proj / "docs" / "guide.md").read_text(encoding="utf-8")
    assert plan.files == (("docs/guide.md", healed),)
    assert "Decoy" not in healed
    assert _decoy(tmp_path) == decoy


@pytest.mark.parametrize("form", FORMS)
def test_build_renders_the_twin_of_the_file_check_grades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    """`cdx build` built NO twin for a ``nope/..`` doc that check grades (silent
    skip) and, across ``link/..``, published the DECOY outside the repo as the
    doc's page. It now renders ``doc_path(root, path)`` beside that file."""
    # Feature: FEAT-CONFIGV2-019
    proj = _project(tmp_path, form)
    cfg = proj / "cdmon.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "    html: true\n", "utf-8")
    monkeypatch.chdir(proj)
    _ok(["monitor", "--apply"])
    _ok(["check"])
    out = _ok(["build"])
    assert "built 1 HTML twin(s)" in out
    twin = (proj / "docs" / "guide.html").read_text(encoding="utf-8")
    assert "How to connect." in twin and "Decoy" not in twin
    assert not (tmp_path / "hub" / "docs" / "guide.html").exists()
    assert not (proj / "nope").exists()
    _ok(["build"])
    assert (proj / "docs" / "guide.html").read_text(encoding="utf-8") == twin
