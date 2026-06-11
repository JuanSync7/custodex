"""CDM-10: config-driven, template-rendered managed regions.

A region's body can be a table whose columns are declared in config and whose
rows come from the document's records (or symbols). Generic and reusable (K0);
deterministic (K10); the code surface stays the single source of truth (K2).

Features: FEAT-CONFIG-006, FEAT-MONITOR-001, FEAT-MONITOR-002, FEAT-MONITOR-003
Features: FEAT-HEAL-003
"""

from __future__ import annotations

import textwrap

from code_doc_monitor.blocks import known_region_ids, render_template
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    RegionColumn,
    RegionTemplate,
    load_config,
)
from code_doc_monitor.extract import DocumentSurface, Record, Symbol
from code_doc_monitor.monitor import Monitor

# --------------------------------------------------------------------------- #
# render_template unit
# --------------------------------------------------------------------------- #


def _surface_with_records(*records: Record) -> DocumentSurface:
    return DocumentSurface(
        doc_id="d", audience=Audience.USER_GUIDE, symbols=(), records=records
    )


def test_render_template_records_table():
    tmpl = RegionTemplate(
        source="records",
        columns=(
            RegionColumn(header="Flag", field="name"),
            RegionColumn(header="Action", field="action"),
            RegionColumn(header="Comment", field="comment"),
        ),
    )
    surface = _surface_with_records(
        Record(
            name="-x", kind="flag", fields=(("action", "replace"), ("comment", "c"))
        ),
        Record(name="-y", kind="flag", fields=(("action", "error"), ("comment", ""))),
    )
    out = render_template(tmpl, surface)
    assert "| Flag | Action | Comment |" in out
    assert "| -x | replace | c |" in out
    assert "| -y | error |  |" in out
    # rows follow surface order (records sorted by (kind, name))
    assert out.index("-x") < out.index("-y")


def test_render_template_kind_filter():
    tmpl = RegionTemplate(
        source="records",
        kind="switch",
        columns=(RegionColumn(header="Switch", field="name"),),
    )
    surface = _surface_with_records(
        Record(name="-h", kind="switch"),
        Record(name="-flag", kind="flag"),
    )
    out = render_template(tmpl, surface)
    assert "-h" in out and "-flag" not in out


def test_render_template_empty_text():
    tmpl = RegionTemplate(
        source="records",
        columns=(RegionColumn(header="Switch", field="name"),),
        empty_text="_No switches._",
    )
    out = render_template(tmpl, _surface_with_records())
    assert out == "_No switches._"


def test_render_template_symbols_source():
    tmpl = RegionTemplate(
        source="symbols",
        columns=(
            RegionColumn(header="Symbol", field="name"),
            RegionColumn(header="Signature", field="signature"),
        ),
    )
    surface = DocumentSurface(
        doc_id="d",
        audience=Audience.USER_GUIDE,
        symbols=(
            Symbol(
                name="foo",
                kind="function",
                signature="def foo(a)",
                lineno=1,
                end_lineno=1,
                is_public=True,
                docstring=None,
            ),
        ),
    )
    out = render_template(tmpl, surface)
    assert "| Symbol | Signature |" in out
    assert "| foo | def foo(a) |" in out


def test_render_template_escapes_pipes():
    tmpl = RegionTemplate(
        source="records", columns=(RegionColumn(header="V", field="v"),)
    )
    surface = _surface_with_records(Record(name="r", kind="x", fields=(("v", "a|b"),)))
    assert r"a\|b" in render_template(tmpl, surface)


def test_known_region_ids_includes_templates():
    ids = known_region_ids({"flags": RegionTemplate(columns=())})
    assert "flags" in ids and "symbols" in ids


# --------------------------------------------------------------------------- #
# config round-trip
# --------------------------------------------------------------------------- #


def test_region_templates_round_trip(tmp_path):
    cfg_text = textwrap.dedent(
        """
        version: "1.0.0"
        root: "."
        region_templates:
          flags:
            source: records
            kind: flag
            columns:
              - {header: Flag, field: name}
              - {header: Action, field: action}
        documents:
          - id: d
            path: d.md
            audience: user-guide
            region_keys: [flags]
            code_refs:
              - path: f.json
                extract: records
                lang: json
                json_records: "*"
                record_name_field: "flag name"
        """
    )
    p = tmp_path / "cdmon.yaml"
    p.write_text(cfg_text)
    cfg = load_config(p)
    assert "flags" in cfg.region_templates
    assert cfg.region_templates["flags"].columns[0].header == "Flag"


# --------------------------------------------------------------------------- #
# end-to-end: templated region drifts and self-heals
# --------------------------------------------------------------------------- #

_FLAG_JSON = """\
{
  "ius flags translations": [
    {"flag name": "-snapshot_dir", "action": "replace"},
    {"flag name": "-allowredefinition", "action": "error"}
  ]
}
"""


def _genbuild_like_config(root: str) -> MonitorConfig:
    return MonitorConfig(
        version="1.0.0",
        root=root,
        region_templates={
            "flags": RegionTemplate(
                source="records",
                columns=(
                    RegionColumn(header="Flag", field="name"),
                    RegionColumn(header="Action", field="action"),
                ),
            )
        },
        documents=(
            DocumentSpec(
                id="ius",
                path="ius.md",
                audience=Audience.USER_GUIDE,
                region_keys=("flags",),
                code_refs=(
                    CodeRef(
                        path="ius_flags_translation.json",
                        extract="records",
                        lang="json",
                        json_records="*",
                        record_name_field="flag name",
                    ),
                ),
            ),
        ),
    )


def test_templated_region_drifts_and_self_heals(tmp_path):
    (tmp_path / "ius_flags_translation.json").write_text(_FLAG_JSON)
    # a doc whose 'flags' region is stale (empty table)
    (tmp_path / "ius.md").write_text(
        "---\ncdm:\n  fingerprint: stale\n---\n\n# IUS\n\n> The IUS plugin.\n\n"
        "<!-- CDM:BEGIN flags -->\n| Flag | Action |\n|---|---|\n"
        "<!-- CDM:END flags -->\n"
    )
    cfg = _genbuild_like_config(".")
    mon = Monitor(cfg, tmp_path, now=lambda: "2026-06-02T00:00:00+00:00")

    report = mon.check()
    assert not report.ok  # drift detected (HASH + stale region)

    result = mon.run(apply=True)
    assert mon.check().ok, "templated region should fully self-heal"
    doc = (tmp_path / "ius.md").read_text()
    assert "| -snapshot_dir | replace |" in doc
    assert "| -allowredefinition | error |" in doc
    assert result.handled  # something was handled
