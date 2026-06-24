# Golden example — one tool, five languages, one `cdx check`

A tiny **greeter** tool implemented across five source languages, each mapped by
[`cdmon.yaml`](cdmon.yaml) onto a managed document. It is the reference example
for custodex's multi-language support: a single `cdx check` keeps every
document honest, and `cdx build` renders the human-facing HTML twins.

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
into custodex.

## Try it

```bash
cd examples/multilang
cdx surface              # what each language yields
cdx check                # are the docs still true? (exit 1 on drift)
cdx monitor --apply      # regenerate the tables + fingerprints to close drift
cdx build                # render docs/*.html twins (humans) from the .md (LLMs)
```

### See drift get caught and closed

Add an option to `code/cli.py` (e.g. `parser.add_argument("--quiet", ...)`),
then `cdx check` — `cli.md` is flagged as drifted. `cdx monitor --apply`
regenerates its options table and `cdx build` refreshes `cli.html`.

### Audience matters

`library.md` is an **eng-guide**, so editing a docstring in `greeter.py` *is*
drift. The user-guides only track the externally-visible surface, so a comment
or private-symbol change to their sources is a non-event.

The example is covered by `tests/system/test_example_multilang.py`.
