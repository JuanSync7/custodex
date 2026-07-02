"""AGT-02 — `cdx link` (accept/reject) + the upgraded `cdx deps --suggest` e2e.

Drives the whole loop on a real tmp dir-layout repo: suggest → accept via
`cdx link` (comment-preserving splice + auto-stamped baseline → `cdx check`
stays green, K7) → the suggestion disappears; reject via `cdx link --reject`
→ the pair never returns; `deps --suggest --json` items stay a key-superset
of the legacy shape (K6); `infer_from_links: true` appends the one-line
advisory summary to `cdx deps`. Offline, no backend, no network (K4).

Features: FEAT-DOCMAP-001, FEAT-DOCMAP-002, FEAT-DOCMAP-003
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from custodex.cli import app

runner = CliRunner()

_UNIT = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "core docs"
owner: eng
created: "2026-07-01"
updated: "2026-07-01"
---
# Hand comment: must survive `cdx link`.
dir-covered:
  - src
source-files-format:
  - .py
documents:
  - id: guide
    path: docs/guide.md
    audience: eng-guide
  - id: api
    path: docs/api.md
    audience: eng-guide
    code_refs:
      - path: src/alpha.py
"""

_INDEX = """\
---
cdmon-config-version: "2.0.0"
repo: t
generated-by: cdx
updated: "2026-07-01"
---
root: "../.."
version: "2.0.0"
backend: {kind: mock}
@EXTRA@units:
  - file: core.yaml
"""


def _setup(tmp_path: Path, *, infer_from_links: bool = False) -> Path:
    cfg_dir = tmp_path / "config" / "cdmon"
    cfg_dir.mkdir(parents=True)
    extra = "docdeps:\n  infer_from_links: true\n" if infer_from_links else ""
    (cfg_dir / "index.yaml").write_text(
        _INDEX.replace("@EXTRA@", extra), encoding="utf-8"
    )
    (cfg_dir / "core.yaml").write_text(_UNIT, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alpha.py").write_text(
        'def solve_widget(x):\n    """Doc."""\n    return x\n', encoding="utf-8"
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# Guide\n\nCall `solve_widget` to start.\n", encoding="utf-8"
    )
    (docs / "api.md").write_text("# API\n\nReference prose.\n", encoding="utf-8")
    return cfg_dir


def test_suggest_accept_loop_end_to_end(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    # Bring the fixture docs code↔doc-clean first (mock backend, offline) so
    # the final `cdx check` asserts THIS slice's edge stamping, not stale
    # fixture fingerprints.
    result = runner.invoke(app, ["monitor", "--apply", "--config", str(cfg_dir)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["deps", "--suggest", "--config", str(cfg_dir)])
    assert result.exit_code == 0
    assert "- doc: api" in result.output
    assert "shared_symbol" in result.output
    assert "code-tracked" in result.output  # the churn note

    result = runner.invoke(app, ["link", "guide", "api", "--config", str(cfg_dir)])
    assert result.exit_code == 0, result.output
    assert "declared 'guide' → 'api'" in result.output
    assert "baseline stamped" in result.output

    unit_text = (cfg_dir / "core.yaml").read_text(encoding="utf-8")
    assert "# Hand comment: must survive `cdx link`." in unit_text
    assert "depends_on:" in unit_text and "- doc: api" in unit_text

    # The accepted edge disappears from a re-run (K7)...
    result = runner.invoke(app, ["deps", "--suggest", "--config", str(cfg_dir)])
    assert "no new doc↔doc edges suggested" in result.output
    # ...and the freshly-stamped edge keeps `cdx check` green.
    result = runner.invoke(app, ["check", "--config", str(cfg_dir)])
    assert result.exit_code == 0, result.output


def test_reject_silences_the_pair_durably(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    result = runner.invoke(
        app,
        ["link", "--reject", "guide", "api", "--by", "me", "--config", str(cfg_dir)],
    )
    assert result.exit_code == 0
    assert "rejected" in result.output
    assert (cfg_dir / ".cdmon" / "edge-rejections.jsonl").is_file()

    result = runner.invoke(app, ["deps", "--suggest", "--config", str(cfg_dir)])
    assert "no new doc↔doc edges suggested" in result.output


def test_suggest_json_is_key_superset_of_legacy(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    result = runner.invoke(
        app, ["deps", "--suggest", "--json", "--config", str(cfg_dir)]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list) and payload  # bare list preserved (K6)
    for item in payload:
        assert {"doc_id", "upstream_id", "via"} <= set(item)
        assert {"tier", "evidence", "score"} <= set(item)


def test_infer_from_links_advisory_summary(tmp_path: Path) -> None:
    on = _setup(tmp_path / "on", infer_from_links=True)
    result = runner.invoke(app, ["deps", "--config", str(on)])
    assert result.exit_code == 0
    assert "advisory — 1 suggested edge(s)" in result.output
    assert "cdx deps --suggest" in result.output

    off = _setup(tmp_path / "off", infer_from_links=False)
    result = runner.invoke(app, ["deps", "--config", str(off)])
    assert result.exit_code == 0
    assert "advisory —" not in result.output.replace("transitively suspect", "")


def test_link_is_loud_on_unknowns_and_single_file(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    result = runner.invoke(app, ["link", "guide", "ghost", "--config", str(cfg_dir)])
    assert result.exit_code == 1 and "ghost" in result.output

    result = runner.invoke(
        app, ["link", "guide", "api", "--type", "bogus", "--config", str(cfg_dir)]
    )
    assert result.exit_code == 1 and "bogus" in result.output

    # Single-file config: accept is loud, reject still works.
    single = tmp_path / "single"
    single.mkdir()
    (single / "a.md").write_text("# A\n", encoding="utf-8")
    (single / "b.md").write_text("# B\n", encoding="utf-8")
    cfg = single / "cdmon.yaml"
    cfg.write_text(
        'version: "1.0.0"\nroot: .\ndocuments:\n'
        "  - id: a\n    path: a.md\n    audience: eng-guide\n"
        "  - id: b\n    path: b.md\n    audience: eng-guide\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["link", "a", "b", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "single file" in result.output
    result = runner.invoke(app, ["link", "--reject", "a", "b", "--config", str(cfg)])
    assert result.exit_code == 0
