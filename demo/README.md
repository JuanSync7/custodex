# demo-taskflow — a cdmon adopter repo

A small, self-contained adopter repo that **code-doc-monitor** (`cdmon`)
monitors end to end via the multi-file `config/cdmon/` layout. It exists to drive
and demonstrate the CONFIG-V2 features: frontmatter unit files, `dir-covered`
scoping, `source-files-format`, `index.yaml`, `ignore.yaml` (+ a `.gitignore`),
`doc-style.yaml`, the writing templates, and a generated `coverage.rpt`.

## The app — `taskflow`

`src/taskflow/` is a tiny task-dependency engine, split across two packages:

| package | module | what it is |
|---------|--------|------------|
| `core`  | `model.py`  | `Status`, `Task`, `TaskGraph` — the domain model |
| `core`  | `engine.py` | `Engine` — topological ordering (Kahn) + sequential run |
| `core`  | `scheduler.py` | `priority_order` — **undocumented** (a real coverage gap) |
| `io`    | `storage.py`| `save_graph`/`load_graph` — JSON persistence |
| `io`    | `report.py` | `render_report` — a plain-text status table |

`core/notes.log` is a deliberate **non-source** file under a `dir-covered`
directory: because `source-files-format` is `['.py']` (and `*.log` is ignored),
cdmon never counts it toward coverage.

### A real coverage gap — `scheduler.py`

`core/scheduler.py` is a genuine public module that **no document references**.
Because it is `.py` and under the `core` unit's `dir-covered`, it counts toward
the denominator and surfaces as a gap. The committed `coverage.rpt` therefore
reports overall coverage of **80%** (`core` unit 66.67%, `io` unit 100%), with
`scheduler.py` listed under `undocumented:` and a `suggested_unit` of `core`. It
is a COVERAGE gap, not drift — `cdmon check` still exits 0.

It is left unlinked **on purpose**: on the dashboard's **Mapping page** (`/repos/
demo-taskflow/mapping`) `scheduler.py` appears under "Unlinked source files", and
you can click "Link to a document…", pick `core-api`, and hit **Generate / make
live** to watch the gap close — coverage jumps from 80% to 100% and the doc is
regenerated to include `scheduler.py`'s surface. The `walkthrough.py` tour drives
this exact flow offline (its `[8/8] link → generate` section).

## The config — `config/cdmon/`

| file | role |
|------|------|
| `index.yaml`    | repo identity (`demo-taskflow`), `root: "../.."`, mock backend, `__init__.py` waivers, the unit index, ignore/doc-style pointers |
| `core.yaml`     | unit owning `src/taskflow/core` → doc `core-api` |
| `io.yaml`       | unit owning `src/taskflow/io` → doc `io-api` |
| `ignore.yaml`   | `gitignore: true` + `*.rpt`/`*.log`/`__pycache__` patterns |
| `doc-style.yaml`| writing-template map (defaults + per-doc) |
| `coverage.rpt`  | **generated** by `cdmon rpt --write` |

The docs the units carry live under `docs/` with a managed `CDM:BEGIN/END
symbols` region that cdmon keeps in sync with the code surface:

| doc id | path | audience | what it shows |
|--------|------|----------|---------------|
| `core-api` | `docs/api/core-api.md` | `eng-guide` | the full core surface (model + engine) |
| `getting-started` | `docs/guide/getting-started.md` | `user-guide` | a friendly tutorial over the key types |
| `io-api` | `docs/api/io-api.md` | `eng-guide` | the io surface (storage + report) |

`getting-started` is a **user-guide** document (`audience: user-guide`). Its
single `symbols` region uses **symbol-selective** `code_refs` — `Task` from
`model.py` and `Engine` from `engine.py` — so it renders a focused "key types"
table over the two files (already documented by `core-api`, so it adds no gap).

### `context_refs` — generation "glance-through" references

`getting-started` also carries a `context_refs:` block — a list of `{path, note}`
"glance-through" references an author (or the LLM) should refer to when writing
the tour:

```yaml
context_refs:
  - path: docs/api/core-api.md
    note: "the full engine reference"
  - path: src/taskflow/core/engine.py
    note: "scheduling semantics referenced in the tour"
```

`context_refs` are **additive and NOT coverage**: distinct from `code_refs` (the
documented surface), they never enter the coverage denominator, never cause drift,
and never count toward the `.rpt` — adding them leaves the demo's 80% unchanged and
`cdmon check`/`lint`/`rpt` byte-identical. They flow into the editable mapping tree
(shown on the Mapping page under the document, visually distinct from `code_refs`)
and into the generation prompt as reference material.

### The four writing-template categories

`doc-style.yaml` maps each document to one template per category. The two API
references use the dense/precise defaults; `getting-started` exercises the OTHER
value in **all four** categories, so every category now uses a non-default value
somewhere in the demo:

| category | api docs (default) | `getting-started` |
|----------|--------------------|-------------------|
| document-type | `api-reference` / `explanation` | `tutorial` |
| tone | `precise` | `friendly` |
| writing-style | `reference-dense` | `narrative` |
| vocabulary | `engine-domain` | `general` |

Writing templates are vendored under `templates/writing/` so the demo is
self-contained.

## Driving the demo

All commands run **from this `demo/` directory** — cdmon auto-detects
`config/cdmon/index.yaml` relative to the working directory.

```bash
cd demo

# Activate the cdmon venv (adjust the path to your checkout).
source ../.venv/bin/activate

# 1. Is every doc in sync with its code surface? (exit 0 = clean)
python -m code_doc_monitor.cli check

# 2. Coverage: file/symbol percentages + documented/undocumented/waived baskets.
#    The .log/.rpt files are NOT in the universe.
python -m code_doc_monitor.cli coverage

# 3. (Re)generate the deterministic coverage report.
python -m code_doc_monitor.cli rpt --write   # writes config/cdmon/coverage.rpt

# 4. Heal drift after editing the source (regenerates managed regions).
python -m code_doc_monitor.cli monitor --apply

# 5. Serve the standalone, per-repo dashboard for this repo (no central server).
python -m code_doc_monitor.cli serve
```

Try it: change a signature in `src/taskflow/core/engine.py`, run
`cdmon check` (it now reports drift, exit 1), then `cdmon monitor --apply` to
heal the `symbols` table back in sync.

## Guided tour: see the heal loop

Want to watch the whole detect → heal loop without touching the checked-in demo?
Run the deterministic, offline walkthrough from the **repo root**:

```bash
source .venv/bin/activate
python demo/walkthrough.py
```

It copies this demo into a temp directory (it never mutates the canonical demo),
induces real drift on `engine.py`, then drives `cdmon` through its core loop on
the copy, printing a clear section header for each stage:

1. **drift detected** — `cdmon check` reports the drift and exits non-zero.
2. **healed** — `cdmon monitor --apply` regenerates the managed region with the
   offline mock backend (no network, no API key).
3. **clean** — `cdmon check` is clean again (exit 0).
4. **review log** — `cdmon report` shows the recorded `FIX` verdict/provenance.
5. **coverage gap** — `cdmon rpt` shows the undocumented `scheduler.py`.
6. **doctor pass** — `cdmon doctor` preflight passes.
7. **apply-fix** — the `Apply fix (LLM)` button's engine
   (`generate.apply_record_fix`): induce drift, capture a `FIX` record carrying a
   proposed fix, apply it (prints the unified diff), and prove a second call is an
   idempotent no-op.
8. **link → generate** — the Mapping page's `Link a file → Generate / make live`
   flow (`generate.apply_edits_to_disk`): stage an `add_code_ref` linking the
   unlinked `scheduler.py` to `core-api`, apply it, and show `cdmon rpt` no longer
   lists `scheduler.py` as undocumented — the coverage gap is closed live.

The script exits 0 on success.

## Standalone dashboard — `cdmon serve`

`cdmon serve` (run from this `demo/` directory) launches the SAME FastAPI +
React dashboard the central server uses, scoped to ONLY this repo, with no
registration and no network. It auto-registers `demo-taskflow` with its
`local_path = <repo>/demo`, pre-syncs the **local** view (the working tree), and
opens the Documents relationship view + a token-less **Sync** button:

```bash
cd demo
source ../.venv/bin/activate
python -m code_doc_monitor.cli serve            # http://127.0.0.1:8000
```

The "Sync (local)" button works against the working tree immediately. "Sync
(main)" (git mode) needs the demo committed to the repo's default branch — see
below.

## Central dashboard — `scripts/seed_demo.py`

`scripts/seed_demo.py` registers `demo-taskflow` into the live central demo
dashboard on `:33333` with its `local_path` so the **Sync** button works live
(token-less, the demo is registered OPEN). It pre-syncs the local view so the
Documents relationship view + sync-state are populated on first load:

```bash
source .venv/bin/activate          # from the repo root
python scripts/seed_demo.py        # serves the seeded central dashboard on :33333
```

`demo-taskflow` appears alongside the other seeded repos; open it to see the two
units' documents (`core-api`, `io-api`) and their `code_refs`, then click
**Sync (local)** to re-run the sync against this `local_path`.

## A note on git-mode sync

cdmon's server reads a repo two ways:

- **local** sync reads the **working tree** — it works against the demo as it
  sits on disk right now (this is what `seed_demo.py` pre-runs and what the Sync
  (local) button uses), even when the demo is not committed.
- **git** sync reads the repo's **default branch** (`main`) via a read-only
  worktree. Because the demo lives in a **subdir** of the outer repo
  (`demo/config/cdmon`), git-mode sync resolves that subdir on the default
  branch — so "Sync (main)" only works once the demo is **committed to the
  repo's default branch**. Until then git-mode sync raises a loud, actionable
  error (and the standalone/seed launchers treat git as best-effort and skip it),
  while local-mode sync keeps working against the working tree.

## Put the demo in git — `scripts/demo_as_git.py`

Want a *real, standalone* git repo to point the **central server** at — the
clone-on-demand path the server uses for a repo it does **not** hold on disk?
The demo can't host its own `.git` (it is a subdir of the outer repo), so a small
launcher exports it to one:

```bash
python scripts/demo_as_git.py /tmp/demo-as-git   # from the repo root
```

This materializes the demo into a genuine git repository with an **authentic,
multi-commit history** (one commit per stage of the project's evolution, mirroring
`CHANGELOG.md`) plus a **bare `file://` origin** — all offline and reproducibly
(pinned git identity + a fixed commit date). It then prints a network-free recipe
(an in-process `TestClient`, no `curl`) that registers the `file://` origin with
the server and runs a clone-on-demand `POST /sync` over it. The server clones the
origin, surfaces the demo's three documents, and reports the same **80%** coverage
(the lone `scheduler.py` gap) it does for the local tree.

The same flow is proven for *any* git repo — not just the demo — in
`tests/system/test_gitrepo_sync_e2e.py` (a one-unit repo, a two-unit repo on a
`trunk` default branch, and the demo, each over a real `file://` origin).
