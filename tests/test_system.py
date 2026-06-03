"""System / end-to-end acceptance tests (CDM-07).

These exercise the whole pipeline offline (mock backend, file/null sinks) on a
fixture repo and assert the SPEC acceptance criteria:

* a SHARED code file grouped into a ``user-guide`` doc and an ``eng-guide`` doc;
* a public-signature change drifts BOTH docs and ``monitor --apply`` closes both;
* a docstring-only change drifts ONLY the eng-guide (audience-level invalidation
  in the extractor — the strongest form of "this change doesn't affect the user
  guide"), and ``monitor --apply`` closes the eng-guide;
* an unknown managed region ESCALATEs and stays in ``remaining``;
* every handled drift is recorded (original drift + fix) and emitted to a
  central sink;
* swapping the backend ``mock`` -> ``claude-code`` changes only which subprocess
  runs (injected fake runner), not the orchestration.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from code_doc_monitor import cli
from code_doc_monitor.backends import BackendResult, ClaudeCodeBackend, FixRequest
from code_doc_monitor.blocks import expected_region
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.drift import DriftKind
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.heal import regenerate_regions, render_corrected
from code_doc_monitor.monitor import Monitor
from code_doc_monitor.reviewlog import read_all
from code_doc_monitor.schema import ProposedFix, Verdict
from code_doc_monitor.sinks import FileSink

_NOW = "2026-06-01T00:00:00Z"

_SHARED_V1 = '''\
def compute(a, b):
    """Add two numbers."""
    return a + b


def _private_helper(x):
    """Internal only."""
    return x * 2
'''

_DOC_STUB = """\
# {title}

Prose written by a human.

<!-- CDM:BEGIN symbols -->
PLACEHOLDER
<!-- CDM:END symbols -->
"""


def _make_repo(tmp_path: Path) -> tuple[Path, MonitorConfig]:
    """A fixture repo: one shared code file referenced by two docs."""
    root = tmp_path
    (root / "shared.py").write_text(_SHARED_V1, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "user.md").write_text(
        _DOC_STUB.format(title="User guide"), encoding="utf-8"
    )
    (root / "docs" / "eng.md").write_text(
        _DOC_STUB.format(title="Engineering guide"), encoding="utf-8"
    )
    user = DocumentSpec(
        id="user",
        path="docs/user.md",
        audience=Audience.USER_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
    )
    eng = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
    )
    cfg = MonitorConfig(documents=(user, eng))
    # Heal to a clean baseline.
    for spec in (user, eng):
        regenerate_regions(root / spec.path, build_document_surface(spec, root))
    return root, cfg


def _monitor(root: Path, cfg: MonitorConfig, **kw: object) -> Monitor:
    return Monitor(cfg, root, now=lambda: _NOW, **kw)  # type: ignore[arg-type]


def test_baseline_is_clean(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    assert _monitor(root, cfg).check().ok


def test_public_signature_change_drifts_both_and_heals(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    # change the PUBLIC signature -> affects every audience
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    report = _monitor(root, cfg).check()
    drifted_docs = {d.doc_id for d in report.drifts}
    assert drifted_docs == {"user", "eng"}

    result = _monitor(root, cfg).run(apply=True)
    assert all(h.result.verdict is Verdict.FIX for h in result.handled)
    assert result.remaining == ()
    assert _monitor(root, cfg).check().ok  # fully self-healed


def test_docstring_change_drifts_only_eng_guide(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    # change ONLY a docstring -> invisible to the user guide (extractor filters
    # it out), but real drift for the eng guide.
    (root / "shared.py").write_text(
        _SHARED_V1.replace(
            '"""Add two numbers."""', '"""Add two integers together."""'
        ),
        encoding="utf-8",
    )
    report = _monitor(root, cfg).check()
    drifted_docs = {d.doc_id for d in report.drifts}
    assert drifted_docs == {"eng"}, "user guide must NOT drift on a docstring edit"

    _monitor(root, cfg).run(apply=True)
    assert _monitor(root, cfg).check().ok


def test_private_symbol_change_invisible_to_user_guide(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("return x * 2", "return x * 3"), encoding="utf-8"
    )
    drifted_docs = {d.doc_id for d in _monitor(root, cfg).check().drifts}
    # _private_helper body change: eng-guide tracks it, user-guide does not.
    assert "user" not in drifted_docs


def test_records_written_and_emitted_to_central_sink(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    central = root / "central.jsonl"
    log = root / "review-log.jsonl"
    result = _monitor(root, cfg, sink=FileSink(central), log_path=log).run(apply=True)
    # every handled drift produced a record carrying the original drift + fix
    assert len(result.records) == len(result.handled) >= 2
    on_disk = read_all(log)
    assert len(on_disk) == len(result.records)
    assert all(r.drift_detail for r in on_disk)
    fixes = [r for r in on_disk if r.verdict is Verdict.FIX]
    assert fixes and all(r.fix is not None for r in fixes)
    # the central system received the same records (offline file sink)
    central_lines = central.read_text(encoding="utf-8").strip().splitlines()
    assert len(central_lines) == len(result.records)


def test_unknown_region_escalates_and_remains(tmp_path: Path) -> None:
    root, _ = _make_repo(tmp_path)
    # A doc that DECLARES it manages a region the engine has no renderer for is
    # UNHEALABLE -> the backend ESCALATEs (a human must resolve it), so it stays
    # in `remaining` even after monitor --apply.
    eng = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols", "mystery"),
    )
    cfg = MonitorConfig(documents=(eng,))
    doc = root / "docs" / "eng.md"
    doc.write_text(
        doc.read_text(encoding="utf-8")
        + "\n<!-- CDM:BEGIN mystery -->\nx\n<!-- CDM:END mystery -->\n",
        encoding="utf-8",
    )
    result = _monitor(root, cfg).run(apply=True)
    kinds = {d.kind for d in result.remaining}
    assert DriftKind.UNHEALABLE in kinds
    escalated = [h for h in result.handled if h.result.verdict is Verdict.ESCALATE]
    assert escalated


def test_backend_swap_only_changes_the_subprocess(tmp_path: Path) -> None:
    """mock -> claude-code: same orchestration, just an injected runner.

    The fake runner stands in for a headless `claude -p` call and returns the
    JSON verdict contract. No real subprocess is spawned (K4).
    """
    root, cfg = _make_repo(tmp_path)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], prompt: str, timeout: int) -> str:
        calls.append(argv)
        # stand in for a headless `claude -p` session that reviewed the drift
        # and returned the JSON verdict contract (no real subprocess, K4).
        return json.dumps(
            {
                "verdict": "ESCALATE",
                "cause": "fake claude session reviewed the drift",
                "fix": None,
            }
        )

    backend = ClaudeCodeBackend(command=("claude", "-p"), runner=fake_runner)
    result = _monitor(root, cfg, backend=backend).run(apply=True)
    # the claude-code backend was actually invoked (the subprocess runner ran)
    assert calls, "the injected runner (the headless claude session) was not called"
    assert all(argv[:2] == ["claude", "-p"] for argv in calls)
    # orchestration still recorded a verdict per drift
    assert len(result.records) == len(result.handled) >= 2


def test_both_shapes_fix_self_heals_in_one_pass(tmp_path: Path) -> None:
    """A real-LLM reply that fills BOTH fix shapes still closes the loop once.

    The headless `claude -p` demo showed a real model returning, for a HASH
    drift, the regenerated region AND a full corrected document. apply_fix must
    prefer the whole-doc text (the only shape that refreshes the fingerprint) so
    ``monitor --apply`` self-heals in a single pass instead of leaving a residual
    HASH drift. This reproduces that reply offline and guards the regression.
    """
    root, cfg = _make_repo(tmp_path)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )

    class _BothShapesBackend:
        """Stands in for a real LLM that returns a region body AND whole-doc text."""

        def propose(self, req: FixRequest) -> BackendResult:
            corrected = (
                render_corrected(req.doc_text, req.surface) if req.doc_text else None
            )
            return BackendResult(
                verdict=Verdict.FIX,
                cause="both shapes (region + whole-doc), as a real LLM may reply",
                fix=ProposedFix(
                    region_id="symbols",
                    new_region_body=expected_region("symbols", req.surface),
                    new_doc_text=corrected,
                    rationale="returned both a region body and the full document",
                ),
            )

    result = _monitor(root, cfg, backend=_BothShapesBackend()).run(apply=True)
    assert all(h.result.verdict is Verdict.FIX for h in result.handled)
    assert result.remaining == ()  # single-pass heal despite both-shapes fixes
    assert _monitor(root, cfg).check().ok


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------

runner = CliRunner()


def _write_config(root: Path, cfg: MonitorConfig) -> Path:
    cfg_path = root / "cdmon.yaml"
    cfg_path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return cfg_path


def test_cli_check_then_monitor_then_report(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    cfg_path = _write_config(root, cfg)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    # check -> drift -> exit 1
    r = runner.invoke(cli.app, ["check", "--config", str(cfg_path)])
    assert r.exit_code == 1, r.output
    # monitor --apply -> heals -> exit 0
    r = runner.invoke(cli.app, ["monitor", "--config", str(cfg_path), "--apply"])
    assert r.exit_code == 0, r.output
    # check is clean now
    r = runner.invoke(cli.app, ["check", "--config", str(cfg_path)])
    assert r.exit_code == 0, r.output
    # report shows the verdicts
    r = runner.invoke(cli.app, ["report", "--config", str(cfg_path)])
    assert r.exit_code == 0
    assert "FIX" in r.output


def test_cli_schema_emits_versioned_json(tmp_path: Path) -> None:
    out = tmp_path / "schema.json"
    r = runner.invoke(cli.app, ["schema", "--out", str(out)])
    assert r.exit_code == 0
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert schema["type"] == "object"
    assert "schema_version" in schema["properties"]


def test_cli_bad_config_is_clean_error(tmp_path: Path) -> None:
    r = runner.invoke(cli.app, ["check", "--config", str(tmp_path / "nope.yaml")])
    assert r.exit_code != 0
    assert "Traceback" not in r.output


# --- CDM-08: end-to-end Document Layout Standard lifecycle --------------------


def test_layout_standard_end_to_end_with_html_twin(tmp_path: Path) -> None:
    """Scaffold -> lint clean -> html pairing (missing/derived/stale) -> clean."""
    from code_doc_monitor.layout import (
        embedded_md_hash,
        lint_config,
        md_source_hash,
        scaffold_doc,
    )
    from code_doc_monitor.manifest import parse_doc

    (tmp_path / "mod.py").write_text(
        '"""m."""\n\n\ndef api(x: int) -> int:\n    return x\n', encoding="utf-8"
    )
    spec = DocumentSpec(
        id="guide",
        path="docs/guide.md",
        audience=Audience.USER_GUIDE,
        code_refs=(CodeRef(path="mod.py"),),
        region_keys=("symbols",),
        html=True,
    )
    cfg = MonitorConfig(root=".", documents=(spec,))

    # Scaffold the .md — it is structurally conformant and content-clean...
    surface = build_document_surface(spec, tmp_path)
    md_path = tmp_path / "docs" / "guide.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(scaffold_doc(spec, surface), encoding="utf-8")

    # ...but the declared HTML twin is missing.
    issues = lint_config(cfg, tmp_path)
    assert [i.code.value for i in issues] == ["HTML_MISSING"]

    # Render a derived HTML twin embedding the current body hash -> clean.
    body = parse_doc(md_path).body
    html_path = tmp_path / "docs" / "guide.html"
    html_path.write_text(
        "<!-- generated; do not edit -->\n"
        f'<meta name="code-doc-md-sha256" content="{md_source_hash(body)}">\n'
        "<h1>guide</h1>\n",
        encoding="utf-8",
    )
    assert lint_config(cfg, tmp_path) == []

    # Edit the Markdown body (a reader-visible change) -> the HTML is now stale.
    md_path.write_text(
        md_path.read_text(encoding="utf-8").replace(
            "TODO: one-line purpose", "A real one-line purpose"
        ),
        encoding="utf-8",
    )
    stale = lint_config(cfg, tmp_path)
    assert [i.code.value for i in stale] == ["HTML_STALE"]

    # Re-deriving the HTML from the new body restores sync.
    new_body = parse_doc(md_path).body
    assert embedded_md_hash(html_path.read_text(encoding="utf-8")) != md_source_hash(
        new_body
    )
    html_path.write_text(
        f'<meta name="code-doc-md-sha256" content="{md_source_hash(new_body)}">\n',
        encoding="utf-8",
    )
    assert lint_config(cfg, tmp_path) == []
