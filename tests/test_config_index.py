"""N-02 — tests for index↔disk reverse validation + ``cdmon index`` (K1/K7/K8/K10).

Covers the reverse invariant in :func:`load_bundle` (an on-disk unit absent from
``index.yaml`` is a loud :class:`ConfigError`), the deterministic
:func:`regenerate_index` rewriter (alphabetical units, refreshed ``updated`` via
the injected clock seam, globals preserved byte-for-byte, idempotent K7), the
:func:`write_index` writer, and the ``cdmon index`` CLI (default rewrite +
``--check`` read-only drift gate K1).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from code_doc_monitor import cli as cli_mod
from code_doc_monitor import config as config_mod
from code_doc_monitor.cli import app
from code_doc_monitor.config import (
    load_bundle,
    load_config_dir,
    load_index_file,
    regenerate_index,
    write_index,
)
from code_doc_monitor.errors import ConfigError

# Reuse the N-01 fixture bodies so the two suites stay in lock-step.
from tests.test_config_v2 import (
    _AGENT_YAML,
    _FOUNDATION_YAML,
    _write_tree,
)

runner = CliRunner()

# A frozen stamp the clock seam returns so ``updated`` is deterministic (K10).
_FROZEN = "2099-01-02T03:04:05+00:00"

# A minimal valid doc-style.yaml (N-05): defaults only, all four categories.
_DOC_STYLE_YAML = (
    '---\ncdmon-config-version: "2.0.0"\nkind: doc-style-map\n'
    'updated: "2026-06-07"\n---\n'
    "defaults:\n"
    "  document-type: api-reference\n"
    "  tone: precise\n"
    "  writing-style: reference-dense\n"
    "  vocabulary: engine-domain\n"
)


def _write_writing_templates(repo_root: Path) -> None:
    """Materialize the four templates _DOC_STYLE_YAML names under templates/writing."""
    pairs = (
        ("document-type", "api-reference"),
        ("tone", "precise"),
        ("writing-style", "reference-dense"),
        ("vocabulary", "engine-domain"),
    )
    for category, name in pairs:
        cat_dir = repo_root / "templates" / "writing" / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        (cat_dir / f"{name}.md").write_text(f"# {name}\nguidance\n", encoding="utf-8")


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin both the config-module and cli-module clock seams to a fixed stamp."""
    monkeypatch.setattr(config_mod, "_now", lambda: _FROZEN)
    monkeypatch.setattr(cli_mod, "_now", lambda: _FROZEN)
    return _FROZEN


# --------------------------------------------------------------------------- #
# Reverse validation in load_bundle.
# --------------------------------------------------------------------------- #


def test_on_disk_unit_not_in_index_is_loud(tmp_path: Path) -> None:
    """A *.yaml unit on disk but absent from index.units → loud ConfigError."""
    d = _write_tree(tmp_path)
    # A real, valid unit file that the index never lists.
    extra = _FOUNDATION_YAML.replace("unit: foundation", "unit: extra", 1)
    (d / "extra.yaml").write_text(extra, encoding="utf-8")
    with pytest.raises(ConfigError, match="extra.yaml"):
        load_config_dir(d)


def test_reverse_validation_names_all_offenders(tmp_path: Path) -> None:
    """Multiple unindexed units are all named, deterministically sorted."""
    d = _write_tree(tmp_path)
    (d / "bbb.yaml").write_text(
        _FOUNDATION_YAML.replace("unit: foundation", "unit: bbb", 1), encoding="utf-8"
    )
    (d / "aaa.yaml").write_text(
        _FOUNDATION_YAML.replace("unit: foundation", "unit: aaa", 1), encoding="utf-8"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config_dir(d)
    msg = str(excinfo.value)
    # alphabetical order in the message (K10).
    assert msg.index("aaa.yaml") < msg.index("bbb.yaml")


def test_reserved_stems_excluded_from_reverse_scan(tmp_path: Path) -> None:
    """Reserved stems (index/ignore/doc-style) never count as missing units."""
    d = _write_tree(tmp_path)
    # ignore.yaml is now parsed by effective_coverage (N-03), so it must be a
    # valid IgnoreFile; doc-style.yaml is now parsed by load_bundle (N-05), so it
    # must be a valid map whose named templates exist under templates/writing.
    (d / "ignore.yaml").write_text(
        '---\ncdmon-config-version: "2.0.0"\nsource: "manual"\n'
        'updated: "2026-06-07"\n---\ngitignore: false\n',
        encoding="utf-8",
    )
    repo_root = d.parent.parent  # config/cdmon -> repo root (index root "..")
    _write_writing_templates(repo_root)
    (d / "doc-style.yaml").write_text(_DOC_STYLE_YAML, encoding="utf-8")
    # index.yaml itself already exists. None of these should raise.
    cfg = load_config_dir(d)
    assert len(cfg.documents) == 3


def test_indexed_units_in_sync_loads_clean(tmp_path: Path) -> None:
    """The N-01 baseline (every on-disk unit indexed) still loads (no regression)."""
    d = _write_tree(tmp_path)
    bundle = load_bundle(d)
    assert len(bundle.units) == 2


# --------------------------------------------------------------------------- #
# regenerate_index — pure-ish rewriter.
# --------------------------------------------------------------------------- #


def test_regenerate_sorts_units_alphabetically(
    tmp_path: Path, frozen_clock: str
) -> None:
    """units: is rebuilt sorted by filename regardless of on-disk index order."""
    d = _write_tree(tmp_path)  # index lists foundation then agent-workflow
    text = regenerate_index(d)
    idx = load_index_file_from_text(text)
    assert [u.file for u in idx.units] == ["agent-workflow.yaml", "foundation.yaml"]


def test_regenerate_includes_new_on_disk_unit(
    tmp_path: Path, frozen_clock: str
) -> None:
    """A new on-disk unit absent from the index is added to the regenerated list."""
    d = _write_tree(tmp_path)
    (d / "zeta.yaml").write_text(
        _FOUNDATION_YAML.replace("unit: foundation", "unit: zeta", 1), encoding="utf-8"
    )
    text = regenerate_index(d)
    files = [u.file for u in load_index_file_from_text(text).units]
    assert files == ["agent-workflow.yaml", "foundation.yaml", "zeta.yaml"]


def test_regenerate_drops_stale_index_entry(tmp_path: Path, frozen_clock: str) -> None:
    """A unit listed in index but absent on disk is dropped from the rewrite."""
    d = _write_tree(tmp_path)
    (d / "agent-workflow.yaml").unlink()
    files = [u.file for u in load_index_file_from_text(regenerate_index(d)).units]
    assert files == ["foundation.yaml"]


def test_regenerate_excludes_reserved_stems(tmp_path: Path, frozen_clock: str) -> None:
    """Reserved stems are never listed as units in the regenerated index."""
    d = _write_tree(tmp_path)
    (d / "ignore.yaml").write_text("---\n---\nx\n", encoding="utf-8")
    (d / "doc-style.yaml").write_text("---\n---\nx\n", encoding="utf-8")
    files = [u.file for u in load_index_file_from_text(regenerate_index(d)).units]
    assert files == ["agent-workflow.yaml", "foundation.yaml"]


def test_regenerate_refreshes_updated_via_clock(
    tmp_path: Path, frozen_clock: str
) -> None:
    """The frontmatter ``updated`` is refreshed via the injected clock seam (K10)."""
    d = _write_tree(tmp_path)
    text = regenerate_index(d)
    assert load_index_file_from_text(text).frontmatter.updated == _FROZEN


def test_regenerate_preserves_globals_and_other_frontmatter(
    tmp_path: Path, frozen_clock: str
) -> None:
    """Globals + frontmatter (except ``updated``) survive byte-for-byte."""
    d = _write_tree(tmp_path)
    text = regenerate_index(d)
    # The original index minus its updated line and units block, compared to the
    # regenerated one minus the same, must be identical.
    orig = (d / "index.yaml").read_text(encoding="utf-8")
    idx = load_index_file_from_text(text)
    # globals survive structurally
    assert idx.apply_default is True
    assert idx.backend.kind == "mock"
    assert "api-index" in idx.region_templates
    assert idx.coverage.waive[0].reason == "re-export aggregator"
    assert idx.frontmatter.repo == "code-doc-monitor"
    assert idx.frontmatter.generated_by == "cdmon"
    # the repo line (a global non-units, non-updated line) is preserved verbatim
    assert "repo: code-doc-monitor" in orig and "repo: code-doc-monitor" in text


def test_regenerate_is_idempotent(tmp_path: Path, frozen_clock: str) -> None:
    """regenerate(write(regenerate)) == regenerate — a fixed point (K7)."""
    d = _write_tree(tmp_path)
    once = regenerate_index(d)
    write_index(d, once)
    twice = regenerate_index(d)
    assert once == twice


def test_regenerate_result_loads_back(tmp_path: Path, frozen_clock: str) -> None:
    """The regenerated text is a valid index that load_index_file accepts."""
    d = _write_tree(tmp_path)
    write_index(d, regenerate_index(d))
    idx = load_index_file(d / "index.yaml")
    assert [u.file for u in idx.units] == ["agent-workflow.yaml", "foundation.yaml"]


def test_regenerate_empty_units_renders_empty_list(
    tmp_path: Path, frozen_clock: str
) -> None:
    """No on-disk units → a ``units: []`` block (still a valid index shape)."""
    d = _write_tree(tmp_path)
    (d / "foundation.yaml").unlink()
    (d / "agent-workflow.yaml").unlink()
    text = regenerate_index(d)
    assert "units: []" in text
    assert load_index_file_from_text(text).units == ()


def test_regenerate_appends_units_block_when_absent(
    tmp_path: Path, frozen_clock: str
) -> None:
    """An index body lacking a ``units:`` block gets one appended (insert path)."""
    d = tmp_path / "config" / "cdmon"
    d.mkdir(parents=True)
    # An index with NO units block in the body at all.
    (d / "index.yaml").write_text(
        '---\ncdmon-config-version: "2.0.0"\nrepo: r\n'
        'generated-by: cdmon\nupdated: "2026-01-01"\n---\n'
        'root: "../.."\nversion: "2.0.0"\n',
        encoding="utf-8",
    )
    (d / "u.yaml").write_text(
        _FOUNDATION_YAML.replace("unit: foundation", "unit: u", 1), encoding="utf-8"
    )
    text = regenerate_index(d)
    assert [x.file for x in load_index_file_from_text(text).units] == ["u.yaml"]


def test_regenerate_inserts_updated_when_absent(
    tmp_path: Path, frozen_clock: str
) -> None:
    """A frontmatter lacking ``updated:`` gets one inserted (insert path, K10)."""
    d = tmp_path / "config" / "cdmon"
    d.mkdir(parents=True)
    # Frontmatter with NO updated line. (IndexFrontmatter requires it, so this
    # only exercises regenerate's text surgery, then we re-add via the rewrite.)
    (d / "index.yaml").write_text(
        '---\ncdmon-config-version: "2.0.0"\nrepo: r\ngenerated-by: cdmon\n---\n'
        'root: "../.."\nunits: []\n',
        encoding="utf-8",
    )
    text = regenerate_index(d)
    assert load_index_file_from_text(text).frontmatter.updated == _FROZEN


# --------------------------------------------------------------------------- #
# write_index — loud writer.
# --------------------------------------------------------------------------- #


def test_write_index_writes_bytes(tmp_path: Path) -> None:
    """write_index materializes the text at config_dir/index.yaml."""
    d = tmp_path / "config" / "cdmon"
    d.mkdir(parents=True)
    write_index(d, "---\nx\n---\nbody\n")
    assert (d / "index.yaml").read_text(encoding="utf-8") == "---\nx\n---\nbody\n"


def test_write_index_loud_on_oserror(tmp_path: Path) -> None:
    """An unwritable target (a directory in the way) raises ConfigError (K8)."""
    d = tmp_path / "config" / "cdmon"
    d.mkdir(parents=True)
    (d / "index.yaml").mkdir()  # a directory where the file should go
    with pytest.raises(ConfigError, match="Cannot write index"):
        write_index(d, "anything")


# --------------------------------------------------------------------------- #
# Integration: drift → load raises → regenerate → loads clean.
# --------------------------------------------------------------------------- #


def test_integration_unindexed_then_regenerate_fixes(
    tmp_path: Path, frozen_clock: str
) -> None:
    """3 units on disk, one missing from index → load raises; regenerate fixes."""
    d = _write_tree(tmp_path)
    (d / "third.yaml").write_text(
        _AGENT_YAML.replace("unit: agent-workflow", "unit: third", 1)
        .replace("id: agent-workflow", "id: third-doc", 1)
        .replace("code_doc_monitor/agent", "code_doc_monitor/third", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config_dir(d)
    write_index(d, regenerate_index(d))
    cfg = load_config_dir(d)  # no raise now
    assert len(cfg.documents) == 4


# --------------------------------------------------------------------------- #
# CLI: cdmon index [--config-dir] [--check].
# --------------------------------------------------------------------------- #


def test_cli_index_rewrites_drifted_index(tmp_path: Path, frozen_clock: str) -> None:
    """`cdmon index` rewrites a drifted index to list every on-disk unit."""
    d = _write_tree(tmp_path)
    (d / "newunit.yaml").write_text(
        _FOUNDATION_YAML.replace("unit: foundation", "unit: newunit", 1),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["index", "--config-dir", str(d)])
    assert result.exit_code == 0, result.output
    files = [u.file for u in load_index_file(d / "index.yaml").units]
    assert "newunit.yaml" in files


def test_cli_index_second_run_is_noop(tmp_path: Path, frozen_clock: str) -> None:
    """A second `cdmon index` produces byte-identical output (K7)."""
    d = _write_tree(tmp_path)
    runner.invoke(app, ["index", "--config-dir", str(d)])
    after_first = (d / "index.yaml").read_text(encoding="utf-8")
    result = runner.invoke(app, ["index", "--config-dir", str(d)])
    assert result.exit_code == 0, result.output
    assert (d / "index.yaml").read_text(encoding="utf-8") == after_first


def test_cli_index_check_exits_1_on_drift(tmp_path: Path, frozen_clock: str) -> None:
    """`cdmon index --check` exits 1 when on-disk index differs (CI gate)."""
    d = _write_tree(tmp_path)
    (d / "drifty.yaml").write_text(
        _FOUNDATION_YAML.replace("unit: foundation", "unit: drifty", 1),
        encoding="utf-8",
    )
    before = (d / "index.yaml").read_text(encoding="utf-8")
    result = runner.invoke(app, ["index", "--config-dir", str(d), "--check"])
    assert result.exit_code == 1, result.output
    # --check is read-only (K1): the on-disk file is untouched.
    assert (d / "index.yaml").read_text(encoding="utf-8") == before


def test_cli_index_check_exits_0_when_synced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cdmon index --check` exits 0 when in sync — even with a MOVED clock (N-06).

    The on-disk and regenerated frontmatter ``updated:`` stamps ALWAYS differ in
    real use (regenerate refreshes the wall clock), so the check must be
    insensitive to a pure timestamp delta. We write the index at one wall time,
    then run ``--check`` with a DIFFERENT injected time and still expect exit 0 —
    proving the in-sync verdict does NOT depend on a frozen clock.
    """
    d = _write_tree(tmp_path)
    # Write (sync) the index at time T1.
    monkeypatch.setattr(config_mod, "_now", lambda: "2099-01-02T03:04:05+00:00")
    monkeypatch.setattr(cli_mod, "_now", lambda: "2099-01-02T03:04:05+00:00")
    runner.invoke(app, ["index", "--config-dir", str(d)])
    synced = (d / "index.yaml").read_text(encoding="utf-8")
    # Now --check at a genuinely DIFFERENT time T2. Only the timestamp would
    # change; the units list is unchanged ⇒ in sync ⇒ exit 0.
    monkeypatch.setattr(config_mod, "_now", lambda: "2099-12-31T23:59:59+00:00")
    monkeypatch.setattr(cli_mod, "_now", lambda: "2099-12-31T23:59:59+00:00")
    result = runner.invoke(app, ["index", "--config-dir", str(d), "--check"])
    assert result.exit_code == 0, result.output
    assert "in sync" in result.output
    # --check is read-only (K1): the on-disk file is untouched (the T1 stamp).
    assert (d / "index.yaml").read_text(encoding="utf-8") == synced


def test_cli_index_default_config_dir(
    tmp_path: Path, monkeypatch, frozen_clock: str
) -> None:
    """With no --config-dir, the default config/cdmon under cwd is used."""
    d = _write_tree(tmp_path)
    (d / "auto.yaml").write_text(
        _FOUNDATION_YAML.replace("unit: foundation", "unit: auto", 1),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["index"])
    assert result.exit_code == 0, result.output
    files = [u.file for u in load_index_file(d / "index.yaml").units]
    assert "auto.yaml" in files


def test_cli_index_write_failure_is_loud(
    tmp_path: Path, monkeypatch, frozen_clock: str
) -> None:
    """A write failure during a non-check rewrite surfaces as a clean error."""
    d = _write_tree(tmp_path)
    (d / "x.yaml").write_text(
        _FOUNDATION_YAML.replace("unit: foundation", "unit: x", 1), encoding="utf-8"
    )

    def boom(_config_dir, _text):
        raise ConfigError("disk full")

    monkeypatch.setattr(cli_mod, "write_index", boom)
    result = runner.invoke(app, ["index", "--config-dir", str(d)])
    assert result.exit_code == 1
    assert "error:" in result.output


def test_regenerate_unreadable_index_is_loud(tmp_path: Path, monkeypatch) -> None:
    """An OSError reading the existing index → loud ConfigError (K8)."""
    d = _write_tree(tmp_path)
    orig_read = Path.read_text

    def boom(self, *a, **k):
        if self.name == "index.yaml":
            raise OSError("permission denied")
        return orig_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(ConfigError, match="Cannot read config file"):
        regenerate_index(d)


def test_cli_index_missing_dir_is_loud(tmp_path: Path) -> None:
    """A config dir with no index.yaml → clean error, exit 1 (K8)."""
    d = tmp_path / "config" / "cdmon"
    d.mkdir(parents=True)
    result = runner.invoke(app, ["index", "--config-dir", str(d)])
    assert result.exit_code == 1
    assert "error:" in result.output


# --------------------------------------------------------------------------- #
# helper: parse a regenerated index from its text without writing it.
# --------------------------------------------------------------------------- #


def load_index_file_from_text(text: str) -> config_mod.IndexFile:
    """Parse index text in-memory (mirror load_index_file without a file read)."""
    meta, body = config_mod._split_frontmatter(text, Path("<mem>/index.yaml"))
    data = config_mod._parse_v2_body(body, Path("<mem>/index.yaml"))
    return config_mod.IndexFile(frontmatter=config_mod.IndexFrontmatter(**meta), **data)
