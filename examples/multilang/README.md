# Golden example — one tool, five languages, one `cdmon check`

A tiny **greeter** tool implemented across five source languages, each mapped by
[`cdmon.yaml`](cdmon.yaml) onto a managed document. It is the reference example
for code-doc-monitor's multi-language support: a single `cdmon check` keeps every
document honest, and `cdmon build` renders the human-facing HTML twins.

| Source | Language | Extracted as | Document | Audience | Table |
|---|---|---|---|---|---|
| `code/greeter.py` | Python | symbols (AST) | `docs/library.md` | eng-guide | symbol table |
| `code/cli.py` | Python / argparse | option records | `docs/cli.md` | user-guide | Option / Default / Help |
| `code/flags.json` | JSON | row records | `docs/flags.md` | user-guide | Flag / Replaced by / Action / Comment |
| `code/batch.sh` | Shell / getopts | switch records | `docs/tools.md` | user-guide | Switch |
| `code/gui.tcl` | Tcl / regexp | switch records | `docs/tools.md` | user-guide | Switch |

`docs/tools.md` is harvested from **two languages at once** (shell + tcl) into a
single table — one document can track a multi-language surface.

Every language-specific detail lives in `cdmon.yaml` (selectors + region
templates), never in the engine (constraint **K0**). Nothing here is hard-coded
into code-doc-monitor.

## Try it

```bash
cd examples/multilang
cdmon surface              # what each language yields
cdmon check                # are the docs still true? (exit 1 on drift)
cdmon monitor --apply      # regenerate the tables + fingerprints to close drift
cdmon build                # render docs/*.html twins (humans) from the .md (LLMs)
```

### See drift get caught and closed

Add an option to `code/cli.py` (e.g. `parser.add_argument("--quiet", ...)`),
then `cdmon check` — `cli.md` is flagged as drifted. `cdmon monitor --apply`
regenerates its options table and `cdmon build` refreshes `cli.html`.

### Audience matters

`library.md` is an **eng-guide**, so editing a docstring in `greeter.py` *is*
drift. The user-guides only track the externally-visible surface, so a comment
or private-symbol change to their sources is a non-event.

The example is covered by `tests/test_example_multilang.py`.
