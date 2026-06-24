"""Generate a genbuild cdmon.yaml + migrate its docs into cdx format.

Run with the custodex venv python. Discovers genbuild plugins by the
SAME signature rule docsync used (functions whose positional args are
[all_fileset, tool, view_name]), reads the companion-tool registry, and emits:

  <GB>/cdmon.yaml                         (root=".")
  <GB>/docs/userguide/cdmon-src/...       (docs migrated from docsync src/, prose
                                           preserved, markers DOCSYNC: -> CDM:)

The existing docsync tree under docs/userguide/{src,docsync,build} is left
untouched, so docsync keeps working until it is retired.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

GB = Path("/home/Juan.Kok/my_rnd/genbuild_test/local_genbuild")
SRC = GB / "docs" / "userguide" / "src"
DST = GB / "docs" / "userguide" / "cdmon-src"
DST_REL = "docs/userguide/cdmon-src"  # relative to GB (the cdx root)

# custodex's extractor (installed in this venv)
sys.path.insert(0, "/home/Juan.Kok/my_rnd/code-doc-monitor")
from custodex.extract import extract_file  # noqa: E402

PLUGIN_SIG = ("all_fileset", "tool", "view_name")

TOOL_REGISTRY = {
    "cmped": ("ComponentEditor/ComponentEditor.tcl", "tcl"),
    "crt": ("svntools/crt.py", "python"),
    "crt_pathfinder": ("crt_code/crt_pathfinder.sh", "shell"),
    "filelist_extraction": ("bin/filelist_extraction", "python"),
    "hdiff": ("utils/hdiff2cmds.tcl", "tcl"),
    "psl": ("utils/pslister.tcl", "tcl"),
    "read_write_ipxact": ("hdl_build/read_write_ipxact.py", "python"),
    "rel_tool": ("svntools/rel_tool.py", "python"),
    "sacc": ("svntools/svn_access.tcl", "tcl"),
}


def discover_plugins() -> list[dict]:
    """Find plugins by genbuild's own signature rule; return sorted metadata."""
    plugins = []
    for py in sorted((GB / "hdl_plugins").glob("*.py")):
        try:
            symbols = extract_file(py)
        except Exception:
            continue
        for sym in symbols:
            if sym.kind == "function" and sym.arg_names == PLUGIN_SIG:
                name = sym.name
                help_name = f"{name}_help"
                has_help = any(s.name == help_name for s in symbols)
                flags = GB / "hdl_plugins" / f"{name}_flags_translation.json"
                plugins.append(
                    {
                        "name": name,
                        "py": f"hdl_plugins/{py.name}",
                        "help_name": help_name if has_help else None,
                        "flags": (
                            f"hdl_plugins/{name}_flags_translation.json"
                            if flags.is_file()
                            else None
                        ),
                    }
                )
    return sorted(plugins, key=lambda p: p["name"])


def region_templates() -> dict:
    return {
        "options": {
            "source": "records",
            "kind": "option",
            "columns": [
                {"header": "Option", "field": "name"},
                {"header": "Action", "field": "action"},
                {"header": "Default", "field": "default"},
                {"header": "Help", "field": "help"},
            ],
        },
        "flags": {
            "source": "records",
            "columns": [
                {"header": "Flag", "field": "name"},
                {"header": "Replaced by", "field": "flag name replacement"},
                {"header": "Action", "field": "action"},
                {"header": "Comment", "field": "comment"},
            ],
        },
        "tool-args": {
            "source": "records",
            "kind": "switch",
            "columns": [{"header": "Switch", "field": "name"}],
        },
    }


def build_config(plugins: list[dict]) -> dict:
    docs = []

    # getting-started: a hand-authored concepts/onboarding page (no code refs).
    # Lives in cdmon-src and is maintained by hand; the generator only declares
    # it in the config so a regen keeps it wired into nav + the index.
    docs.append(
        {
            "id": "getting-started",
            "path": f"{DST_REL}/getting-started.md",
            "audience": "user-guide",
            "html": True,
            "nav_section": "Genbuild",
            "nav_label": "Getting started",
            "code_refs": [],
        }
    )

    # core
    docs.append(
        {
            "id": "genbuild-core",
            "path": f"{DST_REL}/genbuild-core.md",
            "audience": "user-guide",
            "html": True,
            "nav_section": "Genbuild",
            "nav_label": "Genbuild core",
            "region_keys": ["options"],
            "code_refs": [
                {"path": "bin/genbuild", "extract": "records", "lang": "python"}
            ],
        }
    )

    # plugins
    for p in plugins:
        symbols = [p["name"]]
        if p["help_name"]:
            symbols.append(p["help_name"])
        refs = [{"path": p["py"], "symbols": symbols}]
        region_keys = []
        if p["flags"]:
            refs.append(
                {
                    "path": p["flags"],
                    "extract": "records",
                    "lang": "json",
                    "json_records": "*",
                    "record_name_field": "flag name",
                }
            )
            region_keys = ["flags"]
        docs.append(
            {
                "id": f"plugin-{p['name']}",
                "path": f"{DST_REL}/plugins/{p['name']}.md",
                "audience": "user-guide",
                "html": True,
                "nav_section": "Plugins",
                "nav_label": p["name"],
                "region_keys": region_keys,
                "code_refs": refs,
            }
        )

    # tools
    for name, (target, lang) in sorted(TOOL_REGISTRY.items()):
        docs.append(
            {
                "id": f"tool-{name}",
                "path": f"{DST_REL}/tools/{name}.md",
                "audience": "user-guide",
                "html": True,
                "nav_section": "Companion tools",
                "nav_label": name,
                "region_keys": ["tool-args"],
                "code_refs": [{"path": target, "extract": "switches", "lang": lang}],
            }
        )

    # index (static landing page: no managed regions, no code refs).
    # index=True makes `cdx lint` assert it links every other doc, so a
    # plugin/tool added to the config without a landing-page link is caught.
    # The index renders as a headingless link at the top of the sidebar (no
    # nav_section), labelled as the guide home.
    docs.append(
        {
            "id": "index",
            "path": f"{DST_REL}/index.md",
            "audience": "user-guide",
            "html": True,
            "index": True,
            "nav_label": "Genbuild User Guide",
            "code_refs": [],
        }
    )

    return {
        "version": "1.0.0",
        "root": ".",
        "region_templates": region_templates(),
        "documents": docs,
    }


def migrate_doc(src_path: Path, dst_path: Path, audience: str) -> None:
    """Copy a docsync doc to cdx format: cdm front matter + CDM markers."""
    raw = src_path.read_text(encoding="utf-8")
    # strip docsync front matter (--- ... ---) entirely; keep the body
    body = raw
    if raw.startswith("---\n"):
        end = raw.find("\n---\n", 4)
        if end != -1:
            body = raw[end + 5 :]
    body = body.replace("<!-- DOCSYNC:BEGIN ", "<!-- CDM:BEGIN ").replace(
        "<!-- DOCSYNC:END ", "<!-- CDM:END "
    )
    fm = (
        "---\ncdm:\n"
        '  schema_version: "1.0.0"\n'
        f"  audience: {audience}\n"
        "  fingerprint: TODO\n"
        "---\n\n"
    )
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_text(fm + body.lstrip("\n"), encoding="utf-8")


def build_index_links(plugins: list[dict]) -> str:
    lines = [
        "## Genbuild",
        "",
        "- [Getting started & concepts](getting-started.md) — start here if "
        "genbuild is new to you.",
        "- [Genbuild core](genbuild-core.md)",
        "",
        "## Plugins",
        "",
    ]
    for p in plugins:
        lines.append(f"- [{p['name']}](plugins/{p['name']}.md)")
    lines += ["", "## Companion tools", ""]
    for name in sorted(TOOL_REGISTRY):
        lines.append(f"- [{name}](tools/{name}.md)")
    return "\n".join(lines)


def migrate_index(plugins: list[dict]) -> None:
    """The index becomes a static landing page (its aggregate tables were
    docsync's plugin-index/tool-index; cdmon's collection feature will replace
    them once available — for now we emit a static, hand-maintainable link list)."""
    dst = DST / "index.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    intro = (
        "**Genbuild** is Sondrel/Aion's generic build driver. From a component's "
        "IP-XACT\nmetadata it produces a tool-ready filelist and then runs an EDA "
        "flow —\nsimulation, lint, CDC, synthesis, formal, memory-BIST, packaging "
        "and more —\nthrough a uniform command-line interface. Each EDA flow is "
        "implemented as a\n**plugin**; you pick one with `--tool` and genbuild "
        "does the rest.\n\n"
        "This guide is split cleanly into one page per part:\n\n"
        "- **[Genbuild core](genbuild-core.md)** — the `genbuild` command itself: "
        "every\n  command-line option, what it means, and the common invocation "
        "patterns.\n"
        "- **One page per plugin** (below) — what each plugin does, when to use "
        "it, how to\n  invoke it, and its flag-translation rules.\n"
        "- **One page per companion tool** — the standalone helpers shipped in "
        "`bin/`\n  (component editor, CRT/release tooling, IP-XACT and filelist "
        "utilities) that\n  are run directly rather than through "
        "`genbuild --tool`.\n\n"
        "> Every page exists in two forms: a human-friendly **.html** build and "
        "the\n> **.md** source (ideal for an LLM). Both are generated from — and "
        "kept in sync\n> with — the genbuild source code by `custodex`, "
        "so the human and LLM\n> versions can never disagree, and a plugin or "
        "flag change that outdates the docs\n> is caught immediately.\n\n"
    )
    body = (
        "---\ncdm:\n"
        '  schema_version: "1.0.0"\n'
        "  audience: user-guide\n"
        "  fingerprint: static\n"
        "---\n\n"
        "# Genbuild User Guide\n\n"
        "> Generated, always-in-sync documentation for genbuild, its plugins, "
        "and its companion tools.\n\n" + intro + build_index_links(plugins) + "\n"
    )
    dst.write_text(body, encoding="utf-8")


def main() -> None:
    plugins = discover_plugins()
    print(f"discovered {len(plugins)} plugins, {len(TOOL_REGISTRY)} tools")

    cfg = build_config(plugins)
    (GB / "cdmon.yaml").write_text(
        yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"wrote {GB / 'cdmon.yaml'} ({len(cfg['documents'])} documents)")

    # migrate core + plugin + tool docs (prose preserved)
    migrate_doc(SRC / "genbuild-core.md", DST / "genbuild-core.md", "user-guide")
    for p in plugins:
        s = SRC / "plugins" / f"{p['name']}.md"
        if s.is_file():
            migrate_doc(s, DST / "plugins" / f"{p['name']}.md", "user-guide")
    for name in TOOL_REGISTRY:
        s = SRC / "tools" / f"{name}.md"
        if s.is_file():
            migrate_doc(s, DST / "tools" / f"{name}.md", "user-guide")
    migrate_index(plugins)
    print(f"migrated docs into {DST}")


if __name__ == "__main__":
    main()
