"""CDM-09: multi-language extraction + generic record surfaces.

The engine stays reusable (K0): JSON-record projection, shell/tcl/python CLI
switch extraction, and signature-filtered function selection are all generic
mechanisms driven by config — nothing about any target codebase is hard-coded.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from code_doc_monitor.config import Audience, CodeRef, DocumentSpec
from code_doc_monitor.errors import ExtractionError
from code_doc_monitor.extract import (
    Record,
    build_document_surface,
    extract_argparse_records,
    extract_json_records,
    extract_switches,
)

# --------------------------------------------------------------------------- #
# Record model
# --------------------------------------------------------------------------- #


def test_record_is_frozen_and_normalized():
    r = Record(name="-foo", kind="switch", fields=(("a", "1"),))
    assert r.name == "-foo" and r.kind == "switch"
    with pytest.raises(ValidationError):
        r.name = "x"  # frozen


# --------------------------------------------------------------------------- #
# JSON record projection (generic list-of-dict)
# --------------------------------------------------------------------------- #

_FLAG_JSON = """\
{
  "ius flags translations": [
    {"flag name": "-snapshot_dir", "flag name replacement": "-nclibdirname",
     "action": "replace", "comment": "renamed"},
    {"flag name": "-allowredefinition", "flag name replacement": "",
     "action": "error", "comment": "not allowed"}
  ]
}
"""


def test_extract_json_records_star_key(tmp_path):
    p = tmp_path / "ius_flags_translation.json"
    p.write_text(_FLAG_JSON)
    recs = extract_json_records(p, records_key="*", name_field="flag name")
    assert [r.name for r in recs] == ["-allowredefinition", "-snapshot_dir"]
    snap = next(r for r in recs if r.name == "-snapshot_dir")
    assert dict(snap.fields)["action"] == "replace"
    assert dict(snap.fields)["flag name replacement"] == "-nclibdirname"


def test_extract_json_records_named_key(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(_FLAG_JSON)
    recs = extract_json_records(
        p, records_key="ius flags translations", name_field="flag name"
    )
    assert {r.name for r in recs} == {"-snapshot_dir", "-allowredefinition"}


def test_extract_json_records_loud_on_bad_key(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(_FLAG_JSON)
    with pytest.raises(ExtractionError):
        extract_json_records(p, records_key="nope", name_field="flag name")


def test_extract_json_records_loud_on_malformed(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json")
    with pytest.raises(ExtractionError):
        extract_json_records(p, records_key="*", name_field="name")


def test_extract_json_records_loud_on_missing_file(tmp_path):
    with pytest.raises(ExtractionError):
        extract_json_records(tmp_path / "nope.json", records_key="*", name_field="n")


def test_extract_json_records_loud_on_non_object_top(tmp_path):
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]")
    with pytest.raises(ExtractionError):
        extract_json_records(p, records_key="*", name_field="n")


def test_extract_json_records_star_ambiguous(tmp_path):
    p = tmp_path / "two.json"
    p.write_text('{"a": [1], "b": [2]}')
    with pytest.raises(ExtractionError):
        extract_json_records(p, records_key="*", name_field="n")


def test_extract_json_records_skips_non_dict_rows(tmp_path):
    p = tmp_path / "mixed.json"
    p.write_text('{"rows": [{"name": "ok"}, 7, "x"]}')
    recs = extract_json_records(p, records_key="rows", name_field="name")
    assert [r.name for r in recs] == ["ok"]


def test_extract_switches_loud_on_missing_file(tmp_path):
    with pytest.raises(ExtractionError):
        extract_switches(tmp_path / "nope.sh", lang="shell")


def test_records_ref_without_json_records_is_loud(tmp_path):
    (tmp_path / "f.json").write_text("{}")
    spec = DocumentSpec(
        id="d",
        path="d.md",
        audience=Audience.USER_GUIDE,
        code_refs=(CodeRef(path="f.json", extract="records", lang="json"),),
    )
    with pytest.raises(ExtractionError):
        build_document_surface(spec, tmp_path)


# --------------------------------------------------------------------------- #
# CLI switch extraction — python argv loop / argparse, shell getopts, tcl
# --------------------------------------------------------------------------- #


def test_switches_python_argv_loop(tmp_path):
    p = tmp_path / "tool.py"
    p.write_text(
        "import sys\n"
        "for arg in sys.argv:\n"
        "    if arg == '-comp':\n        pass\n"
        "    elif arg == '-view':\n        pass\n"
        "if any(a in ('-h', '--help') for a in sys.argv[1:]):\n    pass\n"
    )
    recs = extract_switches(p, lang="python")
    names = {r.name for r in recs}
    assert {"-comp", "-view", "-h", "--help"} <= names
    assert all(r.kind == "switch" for r in recs)


def test_switches_python_ignores_non_cli_literals(tmp_path):
    p = tmp_path / "tool.py"
    p.write_text("def w(fp):\n    fp.write('-work lib')\n    fp.write('+incdir+/x')\n")
    assert extract_switches(p, lang="python") == []


def test_switches_python_argparse(tmp_path):
    p = tmp_path / "tool.py"
    p.write_text(
        "import argparse\n"
        "def m():\n"
        "    ap = argparse.ArgumentParser()\n"
        "    ap.add_argument('--mode')\n"
        "    ap.add_argument('--run')\n"
    )
    names = {r.name for r in extract_switches(p, lang="python")}
    assert {"--mode", "--run"} <= names


def test_switches_shell_getopts(tmp_path):
    p = tmp_path / "t.sh"
    p.write_text("#!/bin/bash\nwhile getopts abc:hV: opt\ndo :\ndone\n")
    names = {r.name for r in extract_switches(p, lang="shell")}
    assert names == {"-a", "-b", "-c", "-h", "-V"}


def test_switches_tcl_regexp_charclass(tmp_path):
    p = tmp_path / "t.tcl"
    p.write_text(
        "foreach arg $argv {\n"
        "  if {[regexp {^\\-+[vVdD]} $arg]} {continue}\n"
        "  if {[regexp {^\\-+[hH]} $arg]} {exit 1}\n"
        "}\n"
    )
    names = {r.name for r in extract_switches(p, lang="tcl")}
    assert {"-v", "-V", "-d", "-D", "-h", "-H"} <= names


def test_extract_file_tolerates_non_utf8_bytes(tmp_path):
    # Real-world source files aren't always clean UTF-8 (genbuild has one with a
    # 0x85 byte). Extraction must not crash — bad bytes are replaced, not fatal.
    from code_doc_monitor.extract import extract_file

    p = tmp_path / "legacy.py"
    p.write_bytes(
        b"def plug(all_fileset, tool, view_name):\n    x = '\x85'\n    pass\n"
    )
    syms = {s.name for s in extract_file(p)}
    assert "plug" in syms


def test_extract_argparse_records(tmp_path):
    p = tmp_path / "cli.py"
    p.write_text(
        "import argparse\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--component', action='store', default=None,\n"
        "                help='the component VLNV')\n"
        "ap.add_argument('-v', '--verbose', action='store_true', help='loud')\n"
        "ap.add_argument('positional')\n"  # skipped (no leading -)
    )
    recs = extract_argparse_records(p)
    assert [r.name for r in recs] == ["--component", "--verbose"]
    comp = next(r for r in recs if r.name == "--component")
    assert dict(comp.fields)["help"] == "the component VLNV"
    assert dict(comp.fields)["action"] == "store"
    assert all(r.kind == "option" for r in recs)


def test_extract_argparse_help_is_not_truncated(tmp_path):
    # help is prose meant to be read in full; only long default values are elided.
    long_help = (
        "VLNV of top level component. VLNV should be seperated by comma such as "
        "V,L,N,V, or by colon such as V:L:N:V. Both forms are accepted."
    )
    p = tmp_path / "cli.py"
    p.write_text(
        "import argparse\n"
        "ap = argparse.ArgumentParser()\n"
        f"ap.add_argument('--component', help={long_help!r})\n"
    )
    recs = extract_argparse_records(p)
    assert dict(recs[0].fields)["help"] == long_help  # full, no '...' elision
    assert len(long_help) > 80 and "..." not in dict(recs[0].fields)["help"]


def test_records_python_ref_uses_argparse(tmp_path):
    (tmp_path / "cli.py").write_text(
        "import argparse\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--mode', help='run mode')\n"
    )
    spec = DocumentSpec(
        id="core",
        path="core.md",
        audience=Audience.USER_GUIDE,
        code_refs=(CodeRef(path="cli.py", extract="records", lang="python"),),
    )
    surface = build_document_surface(spec, tmp_path)
    assert [r.name for r in surface.records] == ["--mode"]
    assert surface.records[0].kind == "option"


def test_switches_auto_lang_by_suffix(tmp_path):
    p = tmp_path / "t.sh"
    p.write_text("#!/bin/bash\nwhile getopts hx opt\ndo :\ndone\n")
    names = {r.name for r in extract_switches(p, lang="auto")}
    assert names == {"-h", "-x"}


# --------------------------------------------------------------------------- #
# Signature-filtered selection + surface integration
# --------------------------------------------------------------------------- #

_PLUGINS_PY = """\
def ius(all_fileset, tool, view_name, **kwargs):
    pass

def ius_help(view, tool):
    pass

def _private(all_fileset, tool, view_name):
    pass

def helper(a, b):
    pass
"""


def test_arg_signature_selects_matching_functions(tmp_path):
    p = tmp_path / "plug.py"
    p.write_text(_PLUGINS_PY)
    spec = DocumentSpec(
        id="plugins",
        path="plugins.md",
        audience=Audience.USER_GUIDE,
        code_refs=(
            CodeRef(path="plug.py", arg_signature=("all_fileset", "tool", "view_name")),
        ),
    )
    surface = build_document_surface(spec, tmp_path)
    names = {s.name for s in surface.symbols}
    # 'ius' matches; '_private' matches the signature but is dropped by the
    # user-guide audience filter; 'helper'/'ius_help' do not match the signature.
    assert "ius" in names
    assert "helper" not in names and "ius_help" not in names
    assert "_private" not in names  # private dropped for user-guide


def test_records_move_the_surface_hash(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(_FLAG_JSON)
    spec = DocumentSpec(
        id="d",
        path="d.md",
        audience=Audience.USER_GUIDE,
        code_refs=(
            CodeRef(
                path="f.json",
                extract="records",
                lang="json",
                json_records="*",
                record_name_field="flag name",
            ),
        ),
    )
    s1 = build_document_surface(spec, tmp_path)
    assert {r.name for r in s1.records} == {"-snapshot_dir", "-allowredefinition"}
    h1 = s1.surface_hash()

    p.write_text(_FLAG_JSON.replace("-allowredefinition", "-newflag"))
    s2 = build_document_surface(spec, tmp_path)
    assert s2.surface_hash() != h1  # a changed record moves the hash


def test_switch_refs_build_surface(tmp_path):
    p = tmp_path / "t.sh"
    p.write_text("#!/bin/bash\nwhile getopts hx: opt\ndo :\ndone\n")
    spec = DocumentSpec(
        id="tool",
        path="tool.md",
        audience=Audience.USER_GUIDE,
        code_refs=(CodeRef(path="t.sh", extract="switches"),),
    )
    surface = build_document_surface(spec, tmp_path)
    assert {r.name for r in surface.records} == {"-h", "-x"}
    assert surface.symbols == ()
