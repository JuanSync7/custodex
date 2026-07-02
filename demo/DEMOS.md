# demo-taskflow — demo ⇄ feature traceability catalog

This is the **demo→feature traceability catalog** for custodex. Each
`DEMO-NNN` case below is an **observable scenario** — something you can actually
watch happen, by running a step of `demo/walkthrough.py`, an exact
`cdx <cmd> --config demo/config/cdmon` invocation, inspecting a checked-in
config/doc artifact, or following the documented reproducible steps for an
opt-in path (a `cdx serve` + a POST, `scripts/seed_demo.py`, or a live-backend
recipe).

Each case ends with a `Features: <id>[, <id>...]` tag line. Those lines are the
single source of truth `cdx trace` scans (`traceability.scan_refs(demo, DEMO)`)
to prove **every catalogued feature is demonstrated by at least one case** (the
exact count is the header of `feature-doc/FEATURES.md`). The marker `Features:` is
what makes a `FEAT-id` a reference — a bare mention elsewhere in prose is ignored.

**Honesty rule.** A case tags a feature only if the scenario genuinely
demonstrates or observes it (see `feature-doc/FEATURES.md` for each feature's
summary). There is deliberately no single catch-all case. One rich scenario (the
detect→heal loop) honestly tags many features; opt-in features (live LLM, the
Postgres SqlStore, server routes, the agent extra) are demonstrated by a
**documented, reproducible** case describing the exact observable steps.

The runnable backbone is `demo/walkthrough.py` (offline, deterministic, the mock
backend) and the checked-in `demo/config/cdmon` + `demo/docs` tree. Verify the
mapping with:

```bash
cdx trace --catalog feature-doc/catalog --tests-root tests --demo-root demo
```

Cases are grouped by user journey:

- A. Detect → heal loop (the core pipeline)
- B. Apply-fix (the LLM fix, one-click)
- C. Link → generate (the EDITOR mapping flow)
- D. Coverage + gap → issue / ticket
- E. Doctor / adopt
- F. Config-v2 layout / index / sync
- G. Central server + register + dashboard
- H. Backends + agent (offline + opt-in)
- I. Record / log / sinks
- J. Extractor seam + shell
- K. Reference & traceability (cdx documents itself)
- L. Properties (determinism / authority / fingerprint-tier / anchor invariants)
- M. Server-side git sync (clone-on-demand + provider credentials, EPIC GIT)

---

## A. Detect → heal loop

### DEMO-001 — Detect drift after a real source edit
**What it shows.** Editing a tracked source file (a new public `Engine` method)
moves the eng-guide code surface; `cdx check` grades every document against its
freshly-built surface, reports the drift as data (a `DriftReport` summary line),
and exits 1 — without writing anything or calling a backend.
**How to observe.** `demo/walkthrough.py` step `[1/6]` induces the drift, step
`[2/6]` runs `cdx check`; or directly:
`cdx check --config demo/config/cdmon` after appending a public method to
`demo/src/taskflow/core/engine.py`.
Features: FEAT-CLI-005, FEAT-MONITOR-002, FEAT-DRIFT-001, FEAT-DRIFT-002, FEAT-DRIFT-003, FEAT-DRIFT-010, FEAT-EXTRACT-001, FEAT-EXTRACT-002, FEAT-MANIFEST-001, FEAT-MANIFEST-002, FEAT-MANIFEST-004

### DEMO-002 — Which tier moved + anchor classification on the drift
**What it shows.** The HASH drift on `core-api` names which surface tier moved
(signature vs docstring vs body) from the doc's stored per-tier digests, and
classifies the change via the documented symbol anchors — an added public method
shows up as an anchor *added* (a structural change), not a pure internal re-bind.
**How to observe.** Inspect `demo/docs/api/core-api.md` front matter
(`cdm.fingerprint_tiers`, `cdm.region_anchors`) then run
`cdx check --config demo/config/cdmon` after the DEMO-001 edit; the drift detail
reports the moved tier and the anchor delta.
Features: FEAT-DRIFT-005, FEAT-DRIFT-006, FEAT-EXTRACT-004, FEAT-EXTRACT-005, FEAT-MANIFEST-005, FEAT-MANIFEST-008

### DEMO-003 — Heal the drift with the offline mock backend
**What it shows.** `cdx monitor --apply` runs the full orchestration loop
(detect → backend verdict → record → apply FIX → recheck) and regenerates the
managed `symbols` region from the live code surface using the deterministic mock
backend — no network, no API key. Re-running `cdx check` is clean (exit 0): the
recheck-after-apply remaining set is empty, proving convergence.
**How to observe.** `demo/walkthrough.py` steps `[3/6]` (heal) and `[4/6]`
(re-check clean); or `cdx monitor --apply --config demo/config/cdmon`.
Features: FEAT-CLI-007, FEAT-MONITOR-001, FEAT-MONITOR-003, FEAT-MONITOR-006, FEAT-HEAL-001, FEAT-HEAL-002, FEAT-BACKENDS-001, FEAT-BACKENDS-002, FEAT-BACKENDS-003, FEAT-MANIFEST-003, FEAT-MANIFEST-009

### DEMO-004 — Heal stamps fingerprint, per-tier digests, region hash and anchors
**What it shows.** When the engine authors the region it stamps a single shared
truth: the composite `cdm.fingerprint`, the per-tier `cdm.fingerprint_tiers`, the
per-region `cdm.region_hashes`, and the symbol-table `cdm.region_anchors` — all
from one fingerprint computation, so heal never stamps a fingerprint `check`
won't match.
**How to observe.** After `cdx monitor --apply --config demo/config/cdmon`,
read the regenerated `demo/docs/api/core-api.md` front matter; the four `cdm.*`
blocks are present and a subsequent `cdx check` is clean.
Features: FEAT-HEAL-006, FEAT-HEAL-007, FEAT-MANIFEST-006, FEAT-MANIFEST-007

### DEMO-005 — Every verdict is recorded and the review log summarised
**What it shows.** The heal run records a `ReviewRecord` (a `FIX` verdict with a
provenance snapshot and a deterministic record id) into the append-only review
log and emits it to the configured sink; `cdx report` then summarises the log
by verdict/audience/doc-id.
**How to observe.** `demo/walkthrough.py` step `[5/6]` (`cdx report` shows the
recorded `FIX`); or `cdx report --config demo/config/cdmon`.
Features: FEAT-CLI-015, FEAT-MONITOR-004, FEAT-MONITOR-005, FEAT-RECORD-007, FEAT-RECORD-008

---

## B. Apply-fix (the LLM-proposed whole-doc fix)

### DEMO-006 — Apply a captured FIX record to disk (the Mapping-page button)
**What it shows.** The `Apply fix (LLM)` button's engine: induce drift on a
WHOLE-file-documented module, run Monitor without `--apply` to capture a `FIX`
`ReviewRecord` carrying a whole-doc `ProposedFix`, then apply that fix to disk and
print the unified diff. The fix is region-authority-aware and whole-doc precedence
applies. A second apply is an idempotent no-op (empty diff).
**How to observe.** `demo/walkthrough.py` step `[7/8]` — drives
`generate.apply_record_fix` and prints
`--- unified diff for docs/api/core-api.md ---` then the idempotent no-op.
Features: FEAT-SERVER-013, FEAT-RECORD-004, FEAT-HEAL-008, FEAT-HEAL-009, FEAT-MONITOR-009, FEAT-BACKENDS-006

---

## C. Link → generate (the EDITOR mapping flow)

### DEMO-007 — Link the unlinked scheduler.py to a doc → generate to disk
**What it shows.** `scheduler.py` is deliberately UNLINKED (the live Mapping-page
coverage gap). Staging an `add_code_ref` edit linking it to `core-api` and
applying it with the generate-to-disk engine writes the unit yaml + index and
heals the doc mechanically (no LLM) over a SCOPED write surface; `cdx rpt` then
no longer lists `scheduler.py` as undocumented — the gap closes live.
**How to observe.** `demo/walkthrough.py` step `[8/8]` — drives
`generate.apply_edits_to_disk`; before/after `cdx rpt --config-dir
demo/config/cdmon` shows `scheduler.py` leaving the undocumented list.
Features: FEAT-CONFIGV2-013, FEAT-CONFIGV2-014, FEAT-CONFIGV2-009, FEAT-CONFIGV2-011

### DEMO-008 — context_refs: generation glance-through references (not coverage)
**What it shows.** `getting-started` carries a `context_refs:` block — `{path,
note}` glance-through references that feed the generation prompt only. They are
additive: distinct from `code_refs`, never in the coverage denominator, never
drift, never in the `.rpt`. They surface in the editable mapping tree, visually
distinct from `code_refs`.
**How to observe.** Read the `context_refs:` block in
`demo/config/cdmon/core.yaml` (under `getting-started`); load it via
`load_bundle(demo/config/cdmon)` and inspect `spec.context_refs`; or on the
Mapping page (DEMO-019) they appear under the document.
Features: FEAT-CONFIG-003, FEAT-BACKENDS-008, FEAT-SERVER-010

---

## D. Coverage + gap → issue / ticket

### DEMO-009 — Doc coverage report: three baskets and percentages
**What it shows.** `cdx coverage` discovers the repo's code files (glob-scoped),
attaches each file's symbol inventory, resolves file- and symbol-level ownership
against the documents' `code_refs`, and reports documented / undocumented / waived
baskets with file and public-symbol percentages — the two `__init__.py` are waived
out of the denominator, `scheduler.py` is the one real gap.
**How to observe.** `cdx coverage --config demo/config/cdmon` (or `--json`);
`scheduler.py` appears undocumented and the percentages reflect the waivers.
Features: FEAT-CLI-017, FEAT-COVERAGE-001, FEAT-COVERAGE-003, FEAT-COVERAGE-005, FEAT-COVERAGE-006, FEAT-COVERAGE-007, FEAT-COVERAGE-008, FEAT-COVERAGE-010, FEAT-CONFIG-007

### DEMO-010 — Glob scoping + a non-source file under a dir-covered directory
**What it shows.** `core/notes.log` is a deliberate non-source file under a
`dir-covered` directory: because `source-files-format` is `['.py']` and `*.log`
is ignored, cdx never counts it. This exercises the in-house recursive `**`
glob translation and lossless language tagging, and proves a missing/invalid root
fails loud.
**How to observe.** Inspect `demo/src/taskflow/core/notes.log` (present but never
in the coverage universe) and `demo/config/cdmon/ignore.yaml`; run
`cdx coverage --config demo/config/cdmon` — `notes.log` is absent from every
basket.
Features: FEAT-COVERAGE-002, FEAT-COVERAGE-004

### DEMO-011 — coverage.rpt: the dir-layout report with suggested units
**What it shows.** `cdx rpt` builds the per-unit `coverage.rpt` over the SAME
coverage facts as `cdx coverage`, reusing the effective coverage derived from
the dir layout. The committed report shows overall 88.9%, `core` 66.67%, `io` 100%,
`tests` 100%, and lists `scheduler.py` under `undocumented:` with a `suggested_unit`
of `core`.
`--write` is byte-stable / idempotent and round-trips through parse.
**How to observe.** Read the committed `demo/config/cdmon/coverage.rpt`; re-run
`cdx rpt --write --config-dir demo/config/cdmon` (byte-identical); test
`tests/test_demo_e2e.py::test_demo_rpt_matches_committed_coverage_report`.
Features: FEAT-CLI-003, FEAT-QUALITY-005, FEAT-QUALITY-006, FEAT-QUALITY-007, FEAT-CONFIGV2-006

### DEMO-012 — Surface-gaps → a coverage-gap tracker issue (dry-run)
**What it shows.** `cdx surface-gaps` turns the `scheduler.py` coverage gap into
a tracker issue: it discovers → resolves coverage → suggests an owner for the
undocumented public symbol → builds an `IssuePlan` grouping gaps under their
suggested owner. `--dry-run` prints the plan as JSON with no network; the gitlab /
github transports POST it when a provider + CI env is configured.
**How to observe.** `cdx surface-gaps --dry-run --config demo/config/cdmon`
prints the plan JSON naming `scheduler.py`. (Live: set the provider's CI env vars
and drop `--dry-run` to open the issue.)
Features: FEAT-CLI-018, FEAT-COVERAGE-009, FEAT-PR-007, FEAT-PR-008

### DEMO-013 — Surface dump for debugging
**What it shows.** `cdx surface` prints each document's id / audience /
symbol-count and surface hash via `build_document_surface`; `--json` dumps every
symbol of each surface — the debugging view of what cdx thinks each doc
documents.
**How to observe.** `cdx surface --config demo/config/cdmon` (and `--json`)
shows `core-api`, `getting-started`, `io-api` with their hashes and symbols.
Features: FEAT-CLI-004, FEAT-CONFIG-004

### DEMO-014 — A Jira-style DriftTicket from a handled drift
**What it shows.** The handled `core-api` drift can be turned into the frozen,
deterministic `DriftTicket` artifact — title, summary, severity, affected public
symbols, root cause, proposed change + diff, `change_kind`, and a verdict-aware
acceptance checklist — built purely from the drift + verdict + surface with no
clock. Its status maps from the human resolution outcome.
**How to observe.** Reproducible recipe: load `demo/config/cdmon`, run Monitor
(apply=False) on the DEMO-001 drift to get a handled drift + `FIX` verdict, then
`ticket.build_ticket(...)` yields the `DriftTicket`; `ticket.ticket_status(res)`
maps an accepted/overridden/rejected resolution to its `TicketStatus`.
Features: FEAT-PR-009, FEAT-PR-010, FEAT-PR-011

---

## E. Doctor / adopt

### DEMO-015 — Offline adoption preflight (cdx doctor)
**What it shows.** `cdx doctor` is the offline, read-only adoption preflight: it
loads the config then runs ordered checks over config / documents / backend
prereq / central wiring / extras, printing one `STATUS  name — detail` line each.
The demo passes (`PASS  config`, ...). Its grading is WARN-vs-FAIL: a merely
absent prereq is a WARN (config still valid); only a structurally broken config
FAILs the gate.
**How to observe.** `demo/walkthrough.py` step `[6/6]` runs `cdx doctor`; or
`cdx doctor --config demo/config/cdmon` (exit 0, all PASS/WARN).
Features: FEAT-CLI-014, FEAT-QUALITY-008, FEAT-QUALITY-009

### DEMO-016 — Scaffold a conformant doc + layout lint + modes
**What it shows.** `cdx new-doc` scaffolds a fully-conformant, in-sync Markdown
document for a configured doc id from its surface (refusing to clobber without
`--force`); `cdx lint` validates every doc against the Layout Standard, `--fix`
stamps missing static front matter, and `--modes` prints each managed region's
authority mode / lock / advisory state.
**How to observe.** `cdx lint --config demo/config/cdmon` (exit 0),
`cdx lint --modes --config demo/config/cdmon` (prints each region's mode), and
`cdx new-doc <id> --config demo/config/cdmon` scaffolds a conformant file.
Features: FEAT-CLI-020, FEAT-CLI-021, FEAT-LAYOUT-001, FEAT-LAYOUT-002, FEAT-LAYOUT-003, FEAT-LAYOUT-004, FEAT-LAYOUT-007

### DEMO-017 — Build the HTML twins + index landing-page coverage
**What it shows.** `cdx build` renders every `html: true` document to its `.html`
twin via the dependency-free Markdown renderer, wrapping each in a styled page with
a sidebar nav and embedding the body's source hash so the twin is recognised as
derived; the index landing-page rule checks every `index: true` doc links every
other doc; the twin-pairing check flags a missing / non-derived / stale twin.
**How to observe.** `cdx build --config demo/config/cdmon` writes the `.html`
twins for the demo's html docs; `cdx lint --config demo/config/cdmon` runs the
twin-pairing + index-coverage checks.
Features: FEAT-CLI-006, FEAT-LAYOUT-005, FEAT-LAYOUT-006, FEAT-LAYOUT-008, FEAT-LAYOUT-009

### DEMO-018 — Scaffold a v2 config dir + init template (adopt-from-scratch)
**What it shows.** `cdx init --v2` scaffolds the multi-file `config/cdmon/`
directory layout from the four canonical templates (refusing to clobber without
`--force`); the classic `cdx init` writes the documented single-file starter
template (with `--central URL` wiring the HTTP-reporting block). The demo's own
`config/cdmon` is exactly such a scaffold, filled in.
**How to observe.** `cdx init --v2 --config-dir /tmp/new/config/cdmon --repo
demo` produces a `load_bundle`-valid dir mirroring `demo/config/cdmon`'s shape;
`cdx init --central https://central.example /tmp/single.yaml` writes the wired
single-file template.
Features: FEAT-CLI-001, FEAT-CONFIG-010, FEAT-CONFIGV2-011, FEAT-CONFIG-009

---

## F. Config-v2 layout / index / sync

### DEMO-019 — The multi-file config/cdmon bundle the demo runs on
**What it shows.** The demo is monitored through a `config/cdmon/` directory:
`index.yaml` (repo identity, root `../..`, mock backend, `__init__.py` waivers,
the ordered unit index, ignore/doc-style pointers) plus one `<unit>.yaml` per unit
(`core.yaml`, `io.yaml`) with fenced frontmatter, `dir-covered`, and
`source-files-format`, merged by `load_bundle` into ONE `MonitorConfig` wrapped in
a `ConfigBundle`. `load_bundle` enforces the cross-file invariants (unit files
exist, no duplicate doc id, no two units claim the same dir) and the index↔units
reverse invariant. The repo root is the one shared resolver.
**How to observe.** Read `demo/config/cdmon/index.yaml`, `core.yaml`, `io.yaml`,
`tests.yaml`, `ignore.yaml`; load via `load_bundle(demo/config/cdmon)` — one
`MonitorConfig`, eight documents, three units.
Features: FEAT-CONFIGV2-001, FEAT-CONFIGV2-002, FEAT-CONFIGV2-003, FEAT-CONFIGV2-004, FEAT-CONFIGV2-008, FEAT-CONFIGV2-010, FEAT-CONFIG-001, FEAT-CONFIG-002

### DEMO-020 — Nested deepest-wins attribution + ignore translation
**What it shows.** `unit_for_path` attributes a repo-relative path to the unit
whose `dir-covered` is the deepest ancestor by path components (the demo's `core`
and `io` units own their subtrees); `ignore.yaml` turns on `gitignore: true` plus
manual `*.rpt`/`*.log`/`__pycache__` patterns, and the `.gitignore`-to-globs
translation feeds the coverage exclude set so `coverage.rpt` and `notes.log` are
never counted.
**How to observe.** Inspect `demo/config/cdmon/ignore.yaml` and `demo/.gitignore`;
`bundle.unit_for_path("src/taskflow/io/storage.py")` → `io`, `core/...` → `core`;
`cdx coverage --config demo/config/cdmon` excludes the ignored files.
Features: FEAT-CONFIGV2-005, FEAT-CONFIGV2-007

### DEMO-021 — Regenerate the index from on-disk units (cdx index)
**What it shows.** `cdx index` rebuilds `index.yaml`'s `units:` block from the
on-disk unit files (sorted, reserved stems excluded), preserving every other field
byte-for-byte and the frontmatter `updated:` line. `--check` is a read-only CI
gate that exits 1 on a real units-list change (ignoring the wall-clock stamp).
**How to observe.** `cdx index --check --config demo/config/cdmon` (exit 0 — the
committed index matches its units); `cdx index --config demo/config/cdmon`
rewrites only the `units:` block.
Features: FEAT-CLI-002, FEAT-CONFIGV2-009

### DEMO-022 — Pure unit-file serialization + model editors round-trip
**What it shows.** `dump_unit_file` serializes a `UnitFile` back to canonical
fenced YAML that round-trips through `load_unit_file` and re-dumps byte-identically
(only `updated:` refreshed from an injected clock); the pure editors
(`upsert_document`, `add_code_ref`, `remove_code_ref`, `set_context_refs`) each
return a new frozen `UnitFile` so edits compose then dump once — the machinery the
link→generate flow (DEMO-007) drives.
**How to observe.** Reproducible recipe: `load_unit_file(demo/config/cdmon/
core.yaml)` → `add_code_ref(...)` → `dump_unit_file(...)`; re-`load_unit_file` of
the dumped text equals the edited model; an unedited load→dump is byte-identical.
Features: FEAT-CONFIGV2-014

### DEMO-023 — The four writing-template categories (doc-style.yaml)
**What it shows.** `doc-style.yaml` maps each document to one template per the four
categories (document-type, tone, writing-style, vocabulary); the two API refs use
the dense/precise defaults while `getting-started` uses the OTHER value in all four
(tutorial / friendly / narrative / general), so every category uses a non-default
somewhere. The map validates loudly (every named template must resolve to a file),
round-trips byte-identically, and its bodies compose the authoring guidance.
**How to observe.** Read `demo/config/cdmon/doc-style.yaml` and
`demo/templates/writing/`; `load_doc_style(...)` then `style_for("getting-started")`
returns the four non-default names; test
`tests/test_demo_e2e.py::test_demo_doc_style_exercises_all_four_categories`.
Features: FEAT-QUALITY-001, FEAT-QUALITY-002, FEAT-QUALITY-003, FEAT-QUALITY-004

### DEMO-024 — An index-sourced region rendered over the other docs
**What it shows.** A `source: index` managed region renders a Markdown table over
the config's other documents (one row per doc, synthetic columns: doc_id, title
link, summary, link, audience, path) in deterministic config order — the landing
table a `getting-started`-style index doc carries.
**How to observe.** Reproducible recipe: `render_index(bundle.config, ...)` over
the demo bundle produces the ordered table; an `index: true` doc whose `symbols`
region uses `source: index` regenerates to that table under
`cdx monitor --apply`.
Features: FEAT-CONFIGV2-015

### DEMO-025 — Config sync (local) over the working tree (cdx sync)
**What it shows.** `cdx sync --mode local` runs a read-only config sync against
the working tree: it loads the bundle, computes drift and coverage, projects the
document / code-ref rows and a `SyncRun` summary, mutating nothing; `--json` emits
the run. (Git mode materialises the default branch in a throwaway worktree torn
down in a finally — see DEMO-031.)
**How to observe.** `cdx sync --mode local --json --config demo/config/cdmon`
prints the `SyncRun` (8 documents, 11 code refs, fully synced); the working tree is
untouched.
Features: FEAT-CLI-012, FEAT-CONFIGV2-012, FEAT-SERVER-018

---

## G. Central server + register + dashboard

### DEMO-026 — Standalone per-repo dashboard (cdx serve)
**What it shows.** `cdx serve`, run from `demo/`, launches the SAME FastAPI +
React dashboard the central server uses, scoped to ONLY this repo, with no
registration and no network: it builds an in-memory store holding just
`demo-taskflow` (auto-registered OPEN, token-less), pre-syncs the local view, and
serves the dashboard SPA at `/` (or a friendly JSON landing payload if the SPA
isn't built) with `/health` as an unauthenticated liveness probe. The same app
exposes the public, no-auth `GET /wiki`, which serves the committed EPIC-R wikis
(Feature Reference / Traceability / Test / Source) rendered to HTML by the
engine's own `render_markdown` (no new dep), so the console's Wiki page reads them
from the running server.
**How to observe.** From `demo/`: `cdx serve` → open `http://127.0.0.1:8000`
(the Documents view + token-less Sync button); `GET /wiki` returns
`{"sections":[{"id","title","html"}...]}` for the console Wiki page; the README
"Standalone dashboard" section documents it. Test:
`tests/test_demo_e2e.py::test_standalone_demo_app_one_repo_and_documents`.
Features: FEAT-CLI-013, FEAT-SERVER-001, FEAT-SERVER-014, FEAT-SERVER-015, FEAT-SERVER-019

### DEMO-027 — Register the repo with a central server (cdx register)
**What it shows.** `cdx register` announces the repo to a central server by
POSTing a `RegistrationPayload` (a `RepoIdentity` built from the config) to
`<url>/repos`; `--dry-run` prints the exact payload it would send with no network
call. The server's `POST /repos` validates the same shared schema and persists it.
**How to observe.** `cdx register --dry-run --config <a config with a central:
block>` prints the `RegistrationPayload`. (Live: point `central.url` at a running
`cdx` server, set the auth env token, and drop `--dry-run`.)
Features: FEAT-CLI-011, FEAT-SERVER-002, FEAT-SERVER-017, FEAT-RECORD-010

### DEMO-028 — Seed the central demo dashboard (scripts/seed_demo.py)
**What it shows.** `scripts/seed_demo.py` registers `demo-taskflow` into a live
central demo dashboard on `:33333` with its `local_path`, pre-syncs the local
view, and seeds its own heal records (a drift timeline) and a coverage snapshot
showing the `scheduler.py` gap. The dashboard then lists the repo and exposes the
computed status / health / telemetry aggregate views and the documents
relationship tree.
**How to observe.** From the repo root: `python scripts/seed_demo.py` serves the
seeded dashboard on `:33333`; open `demo-taskflow` to see its documents, records,
coverage and Sync button. Tests:
`tests/test_demo_e2e.py::test_central_seeded_app_lists_demo_taskflow`,
`::test_central_seeded_demo_has_records_and_coverage`.
Features: FEAT-SERVER-005, FEAT-SERVER-008, FEAT-COVERAGE-010

### DEMO-029 — Ingest a heal record + bearer-token auth on writes
**What it shows.** The central server's `POST /ingest` consumes the shared
`IngestEnvelope` and stores its `ReviewRecord`, never auto-registering (an envelope
for an unknown repo is a loud 404). Writes are guarded by a per-repo bearer token
whose sha256 is the only thing stored — a missing header on a protected repo is
401, a wrong token 403, a token-less repo stays open, reads are always open.
**How to observe.** Reproducible recipe: `cdx serve` from `demo/`, then
`POST /repos/demo-taskflow/sync {"mode":"local"}` succeeds token-less (the demo is
registered OPEN). For auth: register a repo WITH a token, then POST `/ingest` an
`IngestEnvelope` with no / wrong / correct `Authorization: Bearer` header to
observe 401 / 403 / 201. (Tested over both stores in `tests/test_server*`.)
Features: FEAT-SERVER-003, FEAT-SERVER-004

### DEMO-030 — Stage a config edit ticket and generate it via the server
**What it shows.** The server-side EDITOR flow: `POST /config/edits` stages one
typed `ConfigEdit` (e.g. `add_code_ref` linking `scheduler.py` to `core-api`) as a
pending `StoredConfigEdit`; `GET /config/edits` lists them; `POST /config/generate`
makes selected edits live by applying them to disk (offline, no-LLM), re-syncing,
and returning the applied ids + fresh `SyncRun` + recomputed undocumented files —
the server twin of the walkthrough's link→generate.
**How to observe.** Reproducible recipe: `cdx serve` from `demo/`, then
`POST /repos/demo-taskflow/config/edits` an `add_code_ref` for `scheduler.py`,
`GET .../config/edits` to see it pending, `POST .../config/generate` to apply it;
the editable tree's `undocumented_files` no longer lists `scheduler.py`. Tests:
`tests/test_demo_e2e.py::test_standalone_editable_tree_shows_context_refs_and_unlinked_scheduler`.
Features: FEAT-SERVER-009, FEAT-SERVER-011, FEAT-SERVER-012, FEAT-SERVER-016

### DEMO-031 — Git-mode sync over the committed demo subdir
**What it shows.** The server reads a repo two ways. `local` sync reads the
working tree (DEMO-025). `git` sync reads the default branch via a read-only
throwaway worktree and resolves the demo's `config/cdmon` even though it lives in a
subdir of the outer repo — and leaves no stray worktree behind. Until the demo is
committed to the default branch, git-mode sync raises a loud, actionable error
while local-mode keeps working.
**How to observe.** Tests
`tests/test_demo_e2e.py::test_git_mode_reads_config_in_subdir`,
`::test_git_mode_subdir_leaves_no_worktree`,
`::test_git_mode_uncommitted_subdir_is_loud` commit the demo into a temp git repo
subdir and run `run_sync(..., mode="git")`. README "A note on git-mode sync".
Features: FEAT-CONFIGV2-012

### DEMO-032 — Persistent SqlStore (Postgres-first, SQLite offline twin)
**What it shows.** The persistence seam has two interchangeable backends behind
one `Store` Protocol. `store_from_env` reads `$CDMON_DATABASE_URL`: when set it
runs Alembic `upgrade head` and returns a persistent `SqlStore` (JSONB on
Postgres, JSON on SQLite via the same migration scripts); when unset it returns a
transient `InMemoryStore` and logs a LOUD warning that ingested data is lost on
restart. The full HTTP suite runs every route over BOTH stores.
**How to observe.** Reproducible recipe: `export
CDMON_DATABASE_URL=sqlite:////tmp/cdmon.db` then `cdx serve` (or launch the
central server) — it migrates and persists across restarts; unset it to see the
loud in-memory warning. The `pg`-marked CI twin runs the same suite on Postgres;
`tests/test_server*` assert store-parity for every route.
Features: FEAT-SERVER-006, FEAT-SERVER-007

---

## H. Backends + agent (offline default + opt-in)

### DEMO-033 — The deterministic offline MockBackend (the demo's default)
**What it shows.** The demo runs on the `mock` backend: it FIXes a healable region
from the surface, authors idempotent prose for a no-renderer `llm` region,
INVALIDATEs a user-guide docstring/comment/private HASH drift, FIXes a surface
HASH drift via a whole-doc correction, and ESCALATEs anything else — all
deterministic, offline, ignoring the additive authoring inputs to stay
reproducible.
**How to observe.** Every `cdx monitor`/`check` in this catalog uses it (see
`backend: { kind: mock }` in `demo/config/cdmon/index.yaml`); the walkthrough's
`[3/6]` heal exercises the FIX path with zero network.
Features: FEAT-BACKENDS-003, FEAT-CONFIG-008

### DEMO-034 — Headless ClaudeCodeBackend (opt-in, injected runner)
**What it shows.** Switching `backend.kind` to `claude-code` drives the headless
Claude Code CLI: `ClaudeCodeBackend` builds the shared prompt, assembles argv
(`claude -p <prompt>` or a `{prompt}`-token template), and runs an injected
`ProcessRunner` (a stdlib subprocess runner built lazily) — any failure/timeout is
a loud `BackendError`. The factory keeps it behind the same `propose` contract.
**How to observe.** Reproducible recipe: set `backend: { kind: claude-code }` in a
config and ensure the `claude` CLI is on `$PATH`, then `cdx monitor --apply`
drives it; `cdx doctor` WARNs if `claude` is absent. (Tests inject a fake
`ProcessRunner` so no `claude` is spawned.)
Features: FEAT-BACKENDS-004, FEAT-BACKENDS-007

### DEMO-035 — Anthropic ApiBackend (opt-in, injected client)
**What it shows.** Switching `backend.kind` to `api` calls the Anthropic Messages
API through an injected `ApiClient` (a stdlib `urllib` client built lazily — no
`anthropic` package), requiring an API key from `api_key_env` or raising a loud
`BackendError`; any client failure is wrapped. Behind the same `propose` contract,
the orchestrator is unchanged.
**How to observe.** Reproducible recipe: set `backend: { kind: api, api_key_env:
ANTHROPIC_API_KEY }`, export the key, then `cdx monitor --apply`; `cdx doctor`
WARNs on an unset key. (Tests inject a fake `ApiClient` so no network is hit.)
Features: FEAT-BACKENDS-005

### DEMO-036 — The LangGraph remediation agent (opt-in [agent] extra)
**What it shows.** Switching `backend.kind` to `agent` drives a deterministic
LangGraph workflow behind the same `propose` contract: `build_graph` compiles a
four-node state graph (select → compose → invoke → parse) plus a bounded re-ask
loop that nudges a malformed reply back to compose until retries are spent, then
fails loudly; the only non-determinism is the injected `Driver`, which
`resolve_driver` builds from config (Claude Code CLI / Anthropic API / a local
OpenAI-compatible endpoint).
**How to observe.** Reproducible recipe: `pip install
custodex[agent]`, set `backend: { kind: agent }` + an `agent:` block, then
`cdx monitor --apply`. `cdx doctor` WARNs if the `langgraph` extra is missing.
(Tests drive the graph offline with a fake driver.)
Features: FEAT-AGENT-001, FEAT-AGENT-002, FEAT-AGENT-003, FEAT-AGENT-008, FEAT-BACKENDS-002

### DEMO-037 — Composable Markdown prompt artifacts + drift context
**What it shows.** The agent's prompt is assembled from separated Markdown
artifacts (AGENT / PROTOCOL / TOOL / PERSONA / EXEMPLARS), lazily loaded and
cached (a missing required artifact is a loud `BackendError`); `select_artifacts`
loads only what a drift needs (TOOL only for a healable drift, PERSONA only when
enabled, EXEMPLARS only when the request carries exemplars); `render_context`
appends the per-drift block (audience, doc, drift, current text, symbol table)
with exemplars/style LAST so an exemplar-/style-free request is byte-identical.
**How to observe.** Read the packaged artifacts under
`custodex/agent/prompts/` (incl. `EXEMPLARS.md`); the agent recipe
(DEMO-036) composes them. Reproducible: build a `FixRequest` for the demo's
`core-api` drift, call `select_artifacts`/`render_context` — TOOL is selected,
PERSONA/EXEMPLARS are not (no exemplars), output is stable.
Features: FEAT-AGENT-004, FEAT-AGENT-005, FEAT-AGENT-006

### DEMO-038 — Few-shot exemplars: similarity retrieval + framing
**What it shows.** With `use_exemplars` on, the monitor reads the review +
resolutions logs once and, per drift, ranks the most-similar PAST RESOLVED records
via an embedding-free weighted feature-match score (surface_hash 5 / doc_id 3 /
drift_kind 2 / audience 1) into frozen `Exemplar` payloads pairing a record with
its human resolution; the agent's `render_context` frames each under `EXEMPLARS.md`
as precedent the live surface still overrides. With no exemplars the prompt is
byte-identical to pre-exemplar output.
**How to observe.** Reproducible recipe: build a small review log + resolutions
over the demo's `core-api` drifts, call `similar.rank_similar(target, ...)` → the
top-N `Exemplar`s in a stable score/recency/id order; run the monitor with
`use_exemplars=True` to attach them on the `FixRequest`.
Features: FEAT-AGENT-007, FEAT-MONITOR-008, FEAT-LEARN-001, FEAT-LEARN-002, FEAT-LEARN-003

### DEMO-039 — Promotion: recurring resolved drifts → a deterministic rule
**What it shows.** `cdx promotions` lists read-only promotion CANDIDATES: each
`(doc_id, drift_kind, audience)` shape whose resolved records (≥ min-count)
unanimously share one DECISION resolution (only the content-free `invalidated` /
`rejected` auto-promote; `overridden`/`accepted` are excluded). A candidate maps to
a frozen `PromotionRule`, and at run time `rule_for` resolves a matching drift with
ZERO backend calls.
**How to observe.** `cdx promotions --config demo/config/cdmon --json` (over a
review log seeded with repeated resolved invalidations). Reproducible:
`detect_promotions(records, resolutions)` → a `PromotionCandidate`;
`rule_from_candidate(...)` → a rule; `monitor.run(rules=(rule,))` resolves the
matching drift with no backend.
Features: FEAT-CLI-016, FEAT-MONITOR-007, FEAT-LEARN-004, FEAT-LEARN-005, FEAT-LEARN-006

---

## I. Record / log / sinks

### DEMO-040 — The public review record + schema export (cdx schema)
**What it shows.** `cdx schema` emits the public review-record JSON Schema — the
one contract the central system consumes — straight from the pydantic model
(never hand-written). The `ReviewRecord` is a frozen/extra-forbid versioned payload
carrying the drift, cause, verdict, proposed fix and an audience/config/hash
snapshot; it grows only by appending optional fields, so an old `1.0.0` line still
parses. Its record id is a deterministic sha256 prefix of the drift identity.
**How to observe.** `cdx schema` (or `--out file`) prints the schema; the heal
run (DEMO-005) writes a `ReviewRecord` whose `schema_version` and deterministic id
are visible in the review log JSONL.
Features: FEAT-CLI-022, FEAT-RECORD-001, FEAT-RECORD-002, FEAT-RECORD-003, FEAT-RECORD-005

### DEMO-041 — Record a human resolution outcome (cdx resolve)
**What it shows.** `cdx resolve RECORD_ID --resolution {accepted|overridden|
rejected|invalidated}` records the human OUTCOME of a handled drift as a SEPARATE
append-only `ResolutionRecord` linked by record_id, validating the id exists (loud)
and leaving the immutable review record untouched. `cdx report` then joins
resolved-vs-unresolved last-write-wins, and `--verdict V` lists the individual
records of a verdict (e.g. the ESCALATEs a human must act on).
**How to observe.** After DEMO-005, grab the `FIX` record id from `cdx report
--json` and run `cdx resolve <id> --resolution accepted --config
demo/config/cdmon`; re-run `cdx report` to see the resolved/unresolved split, and
`cdx report --verdict ESCALATE` to list escalations.
Features: FEAT-CLI-019, FEAT-RECORD-006, FEAT-RECORD-009

### DEMO-042 — Offline sinks vs the resilient HTTP sink with outbox
**What it shows.** A sink emits a `ReviewRecord` to the central system. The
default `NullSink` emits nowhere and `FileSink` appends JSONL — so reporting runs
in CI with zero network (the demo uses the offline default). The opt-in `HttpSink`
POSTs an `IngestEnvelope` with an injected stdlib client, drains a JSONL outbox
oldest-first, retries within a bounded budget, and queues to the outbox on final
failure — `emit` NEVER raises, so a down central system can't break a heal run.
`make_sink` resolves the `central:` config to the right sink (loud on a missing
field).
**How to observe.** The demo's heal (DEMO-003) emits to the offline default.
Reproducible: set a `central: { kind: http, url: ..., repo_id: ... }` block →
`make_sink(cfg)` builds an `HttpSink`; with the URL unreachable, `emit` queues to
the outbox and returns without raising. (Tests inject a fake client.)
Features: FEAT-RECORD-011, FEAT-RECORD-012, FEAT-RECORD-013

---

## J. Extractor seam + shell

### DEMO-043 — The pluggable extractor seam + the Python AST default
**What it shows.** A new language is a registration, not an engine edit: an
`Extractor` Protocol + language-keyed registry (`register_extractor` /
`get_extractor`, loud on an unknown language) sits under `build_document_surface`;
the Python AST extractor is the default registration that parses the demo's
`taskflow` modules.
**How to observe.** Every `cdx surface`/`check` over the demo's `.py` files goes
through `get_extractor("python")`. Reproducible: `register_extractor(stub,
suffixes=(".x",))` then a `lang: auto` ref to a `.x` file resolves the stub with
no engine edit; `get_extractor("nope")` raises loudly.
Features: FEAT-EXTRACT-003

### DEMO-044 — The shell extractor (sh/bash) — a real second language
**What it shows.** `ShellExtractor` statically parses sh/bash function definitions
(`name() {…}` and `function name {…}`) via the stdlib `re` module only, registered
by default for `.sh`/`.bash` — proving a non-Python language is a registration, and
never sourcing or executing the script (read as text). An eng-guide folds the
leading-comment docstring in; a user-guide drops `_`-prefixed helpers and excludes
docstrings.
**How to observe.** Reproducible recipe: add a small `.sh` file with a
`deploy() { ... }` function, point a `lang: shell` (or `lang: auto`) `code_ref` at
it, and `cdx surface` lists the `deploy` function — with ZERO engine edit. (18
shell tests in `tests/test_extract.py`.)
Features: FEAT-EXTRACT-006

---

## K. Reference & traceability (cdx documents itself)

### DEMO-045 — This catalog proves the demo↔feature mapping (cdx trace)
**What it shows.** cdx documents its own documentation system. The golden
feature catalog (`feature-doc/catalog/*.yaml`) is a typed, loadable
`FeatureCatalog` (loud on a duplicate id / bad pattern / non-existent module), and
`render_features_md` renders the human `feature-doc/FEATURES.md`. `cdx trace`
crosses that catalog against the inline `Features:` tags in THIS file (and in
`tests/`) and reports demo coverage — for R-04 the demo side is COMPLETE (every
feature has ≥1 demo case), with zero unknown refs.
**How to observe.** `cdx trace --catalog feature-doc/catalog --tests-root tests
--demo-root demo` (the demo column is fully covered; `--json` emits the matrix);
test `tests/test_demo_traceability.py` asserts
`build_matrix(...).features_without_demo() == ()`.
Features: FEAT-REFERENCE-001, FEAT-REFERENCE-002

### DEMO-052 — Traceability matrix + test wiki (cdx documents its own coverage)
**What it shows.** `traceability.build_matrix` crosses the catalog against the
inline `Features:` tags scanned (as text — never imported) from `tests/` and
`demo/`, and `TraceMatrix.is_complete()` is the 1:1 guarantee that EVERY feature
has at least one test AND one demo, with zero unknown refs (a tagged id not in the
catalog is a loud gap). `testwiki.collect_tests` AST-parses every `test_*.py`
(never executing it) into a boundary-grouped wiki with a per-feature "tested by"
index, drawing each test's "what it asserts" from its own docstring.
**How to observe.** Reproducible recipe: `build_matrix(load_catalog(...),
tests_root=tests, demo_root=demo).is_complete()` is `True`; `render_matrix_md` and
`render_test_wiki_md` are byte-stable (same input → identical Markdown).
Features: FEAT-REFERENCE-003, FEAT-REFERENCE-004

### DEMO-053 — Source index: no orphan public capability (cdx proves it covers itself)
**What it shows.** `srcindex.build_source_index` inventories the whole
`custodex` package (reusing `inventory.discover_files`/`discover_symbols`
— no AST re-impl), folds every file into its top-level module, attaches each
module's public symbols, and joins each module to the catalog features that name
it. `SourceIndex.modules_without_feature()` is the "no orphan public capability"
check (a public module with zero catalog features) and
`features_without_module_match()` catches a catalog feature naming a vanished
module — both are EMPTY over the real tree, proving the golden reference covers
the entire public surface. `render_source_wiki_md` emits the byte-stable SOURCE
wiki (per-module path, symbols, implementing features + a coverage summary).
**How to observe.** Reproducible recipe: build the index over `custodex`
with the real catalog → `features_without_module_match() == ()` AND
`modules_without_feature() == ()`; `render_source_wiki_md(index)` is byte-stable.
Features: FEAT-REFERENCE-005, FEAT-REFERENCE-006

### DEMO-054 — One command regenerates every wiki + the freshness gate (cdx wiki)
**What it shows.** `cdx wiki` regenerates ALL of EPIC R's derived artifacts from
their single sources in ONE command — `feature-doc/FEATURES.md` (from the catalog
yaml) plus `feature-doc/wiki/TEST_WIKI.md`, `SOURCE_WIKI.md`, and `TRACEABILITY.md`
(from the tests' docstrings and the source AST) — via a shared `WIKI_TARGETS`
mapping, so write-mode and `--check` can never diverge. A second `cdx wiki` is a
no-op (every target reported `unchanged` — idempotent K7). `cdx wiki --check` is
the read-only CI freshness gate: it lists every stale file and exits nonzero
WITHOUT writing (K8). Paired with `cdx trace --fail-on-gap` (which exits 0 only
when every feature has a demo AND a test), CI fails the moment the reference drifts
from the code, demos, or tests.
**How to observe.** `cdx wiki` regenerates the four artifacts; a second
`cdx wiki` prints `unchanged` for all four; `cdx wiki --check` exits 0 on the
fresh tree and nonzero after a wiki is touched; `cdx trace --fail-on-gap` exits 0
on the real tree.
Features: FEAT-REFERENCE-007

---

## L. Properties (determinism / authority / fingerprint-tier / anchor invariants)

### DEMO-046 — Audience-aware surface + drift suppression (user-guide vs eng-guide)
**What it shows.** `getting-started` is a `user-guide` doc; the two API refs are
`eng-guide`. A docstring/comment- or private-symbol-only change does NOT move the
user-guide surface hash (the extraction filter excludes those) so it produces no
HASH drift for the user-guide, while the same change does drift an eng-guide. The
audience drives what counts as a documented surface and what counts as drift.
**How to observe.** Edit only a docstring in a `core` symbol and run `cdx check
--config demo/config/cdmon`: `core-api` (eng-guide) drifts, `getting-started`
(user-guide) does not. The two API hashes vs the user-guide hash differ in
`cdx surface`.
Features: FEAT-DRIFT-004, FEAT-EXTRACT-001

### DEMO-047 — Authority modes: human/llm/llm-seeded regions never clobbered
**What it shows.** Per-region authority modes (`generated` / `llm` / `human` /
`llm-seeded`) declare who owns each region and how heal treats it. A `human`
region (or a `llm-seeded` region locked once a human edited it, via the shared
lock predicate) is reported for manual review but `healable=False` so the engine
never auto-edits it; for a whole-doc fix, the write boundary re-injects the
preserved region's current body. An unlocked `llm-seeded` region is still filled;
a locked one is left untouched. A pure-`llm` region is re-authored only when the
whole-doc fingerprint diverges; a human region carries a persistent review
advisory across a fingerprint heal until acknowledged.
**How to observe.** Reproducible recipe: add a `region_modes` entry marking a
region `human` (or `llm-seeded`) on a demo doc, edit that region by hand, then
`cdx monitor --apply` — the human/locked region is preserved while the
`generated` region heals; `cdx lint --modes` prints each region's mode/lock/
advisory state.
Features: FEAT-CONFIG-005, FEAT-CONFIG-006, FEAT-DRIFT-007, FEAT-DRIFT-008, FEAT-DRIFT-009, FEAT-HEAL-003, FEAT-HEAL-004, FEAT-HEAL-005

### DEMO-048 — Opt-in body-tier fingerprint (detect a body-only change)
**What it shows.** `MonitorConfig.fingerprint_body_tier` is an opt-in flag
(default OFF to keep stored fingerprints valid) that folds function/method bodies
into non-user-guide surface hashes, so an eng-guide can detect an implementation
change that leaves the signature untouched. With the flag OFF a body-only edit is
byte-invisible to the hash; ON it moves the eng-guide surface.
**How to observe.** Reproducible recipe: with `fingerprint_body_tier: false`
(the demo default), change only the BODY of a `core` method and `cdx check` is
clean; set it `true`, re-stamp via `cdx monitor --apply`, then the same body-only
edit drifts `core-api`.
Features: FEAT-CONFIG-011, FEAT-EXTRACT-004

### DEMO-049 — Deterministic surface fingerprint + symbol anchor identity
**What it shows.** `DocumentSurface.surface_hash()` is a stable `sha256[:16]` over
the audience-filtered symbols (sorted keys, normalized whitespace, no wall-clock),
so an unchanged surface always hashes identically; `anchor_id(name)` is a
lineno-free hash of a symbol's qualified name, stable across a pure code move and
changed by a rename — so drift tells a structural add/remove/rename from a purely
internal change.
**How to observe.** Reproducible recipe: `build_document_surface` over `core-api`
twice → identical `surface_hash`; move a documented symbol's definition (no
rename) → its `anchor_id` is unchanged and `cdx check` reports an empty anchor
delta (a re-bind), whereas a rename shows it added+removed.
Features: FEAT-EXTRACT-002, FEAT-EXTRACT-005

### DEMO-050 — The typed loud-error hierarchy (every failure is classifiable)
**What it shows.** `errors.py` defines one `CodeDocMonitorError` base plus typed
subclasses (`ConfigError`, `ExtractionError`, `DriftError`, `BackendError`,
`SchemaError`, `InventoryError`, `TransportError`, `SyncError`, `CatalogError`) so
every failure mode is a loud, classifiable exception, never a silent pass — the
backbone behind every "loud on …" behaviour in this catalog.
**How to observe.** Reproducible recipe: feed a malformed `index.yaml` to
`load_bundle` → `ConfigError`; an unparseable `.py` to `discover_symbols` →
`ExtractionError`; a corrupt review-log line to `read_all` → `SchemaError`. Each is
a distinct typed subclass of the one base.
Features: FEAT-CONFIG-012

### DEMO-051 — Docs heal patch / loop-safety / docs-MR (the PR family)
**What it shows.** `cdx sync-pr` heals the docs and emits a unified-diff patch of
exactly the changed docs (`--dry-run` computes the same patch with byte-for-byte
tree restore; a clean/second run is an empty patch — idempotent). The plan is a
frozen `MergeRequestPlan` whose branch is stable per unchanged patch; an injected
`PRTransport` seam drives the flow (the GitLab transport does the canonical 3-call
REST flow). `cdx open-docs-pr` heals then opens the docs MR (`--dry-run` prints
the plan JSON with no transport built). The `cdx should-sync` guard
(`should_sync`) is the loop-breaker that stops a bot doc-only commit re-triggering
another docs heal/MR: every changed path being a managed doc returns "skip", any
file outside returns "proceed", an empty set skips.
**How to observe.** After the DEMO-001 drift on the demo copy:
`cdx sync-pr --dry-run --config demo/config/cdmon` prints the doc patch and
restores the tree; `cdx open-docs-pr --dry-run --config demo/config/cdmon`
prints the MR plan JSON. `echo "demo/docs/api/core-api.md" | cdx should-sync
--config demo/config/cdmon` exits 1 (a doc-only change → skip), while a source path
exits 0 (proceed). (Live: set GitLab CI env and drop `--dry-run`.)
Features: FEAT-CLI-008, FEAT-CLI-009, FEAT-CLI-010, FEAT-PR-001, FEAT-PR-002, FEAT-PR-003, FEAT-PR-004, FEAT-PR-005, FEAT-PR-006

---

## M. Server-side git sync (clone-on-demand + provider credentials, EPIC GIT)

The central server here is handed a repo it does NOT hold on disk — only a
`provider` + `remote_url` (and, for a private repo, a sealed credential). It clones
the repo on demand, syncs it, and can open a docs PR upstream. The demo proves this
end to end with NO network by using the committed `demo/` tree as a real `file://`
git origin (exercised by `tests/system/test_demo_gitsync_e2e.py`).

### DEMO-095 — Clone-on-demand: sync a repo the server does not hold
**What it shows.** `gitfetch.cloned_repo(RemoteSpec(...), secret)` shallow-clones a
remote into a throwaway temp tree and yields it for `run_sync(mode="local")`, then
tears it down (the user/server tree is never mutated). The token reaches git only
via an ephemeral `GIT_ASKPASS` env helper — never argv or the clone URL. The
`POST /repos/{id}/sync` route uses this when a repo has a `provider`+`remote_url`
but no `local_path`, so the demo's documents + coverage surface exactly as for a
local repo — and adding a file upstream then re-syncing shows it.
**How to observe.** Git-init a copy of `demo/` as a `file://` origin, register a
repo with that `remote_url` + `provider: github` (no `local_path`), and
`POST /repos/<id>/sync` — the response is `fully_synced` with the demo's docs +
a coverage snapshot. See `test_demo_gitsync_e2e.py::test_demo_clone_on_demand_sync_*`
and `::test_demo_add_file_to_origin_then_resync_sees_it`.
Features: FEAT-GITSYNC-001

### DEMO-096 — At-rest sealed credential: seal at register, open at sync
**What it shows.** A per-repo git PAT is WRITE-ONLY at register and stored
AES-256-GCM-sealed (`secrets.SecretBox` under `$CDMON_SECRET_KEY`) — never as
plaintext (the payload JSON is sanitized; the store keeps opaque bytes and never
imports cryptography). At sync/docs-PR the route opens it and hands the plaintext to
the clone/transport; a missing/wrong KEK is a loud 500, never a silent downgrade.
**How to observe.** Register with `provider_secret` + `$CDMON_SECRET_KEY` set; the
sealed bytes round-trip via `repo_provider_secret` and the plaintext is absent from
the stored payload. See `test_secrets.py` (seal/open + tamper/KEK failures) and
`test_server_gitsync.py::test_provider_secret_sealed_then_opened_and_passed_to_cloner`.
Features: FEAT-GITSYNC-002

### DEMO-097 — Minted short-lived App/OAuth token (the hot token is never stored)
**What it shows.** For a `provider_kind` of `github-app`/`gitlab-oauth`, the sealed
credential is a longer-lived secret (an App private key / OAuth refresh token); the
route mints a SHORT-LIVED access token from it on each op (`gitauth`: an RS256 App
JWT exchanged for an installation token, or an OAuth refresh grant) and uses THAT to
clone — so the hot token is never persisted.
**How to observe.** Register a `github-app` repo with a sealed credential JSON and
`POST /sync`; the minted token (not the credential) reaches the cloner. See
`test_gitauth.py` (JWT + mint dispatch) and
`test_server_gitsync.py::test_phase2_github_app_mints_short_lived_token_then_clones`.
Features: FEAT-GITSYNC-003

### DEMO-055 — Open a docs PR upstream (GitHub or GitLab)
**What it shows.** `POST /repos/{id}/docs-pr` clones the repo, heals its docs
(`syncpr.sync_pr` — region authority honored), plans the PR from the healed docs,
and opens it through the provider transport. `GitHubTransport` runs the atomic
git-data flow (ref → tree → commit → branch ref → pull) with no local checkout;
`from_repo(remote_url, token)` builds either transport from the repo URL; `?dry_run`
plans without calling the provider.
**How to observe.** After an upstream drift on the demo origin,
`POST /repos/<id>/docs-pr` returns `opened: true` with the changed doc paths. See
`test_pr.py` (the GitHub atomic flow) and
`test_demo_gitsync_e2e.py::test_demo_docs_pr_after_upstream_drift_opens_pr`.
Features: FEAT-GITSYNC-004

### DEMO-056 — Put the demo in git: clone-on-demand works for any real repo
**What it shows.** The clone-on-demand flow is repo-agnostic — it works against
ANY real git repository, with an authentic multi-commit history, not just a
single-commit fixture. `scripts/demo_as_git.py` materializes the committed
`demo/` tree into a genuine standalone git repo (one commit per stage of the
project's evolution, mirroring `CHANGELOG.md`) plus a bare `file://` origin,
fully offline and reproducibly (pinned git identity + a fixed commit date). The
server then clones that origin on demand and surfaces the demo's documents +
its pinned 88.9% coverage off the real default-branch tip — and the same holds
for synthetic one-/two-unit repos and a repo whose default branch is `trunk`,
not `main`.
**How to observe.** Run `python scripts/demo_as_git.py /tmp/demo-as-git` to build
the repo, then run the offline sync recipe it prints (an in-process `TestClient`
that registers the `file://` origin and `POST`s `/sync`) — no network, no `curl`.
See `tests/system/test_gitrepo_sync_e2e.py` (the parametrized any-repo matrix,
the git-mode baseline, and `::test_demo_as_git_materializes_a_syncable_repo`).
Features: FEAT-GITSYNC-005

### DEMO-057 — A README is a monitored narrative document
**What it shows.** A narrative Markdown file — a `README.md` — is a first-class
monitored document, not just engineering reference pages. The demo declares its
OWN `README.md` as a `readme` document in `demo/config/cdmon/core.yaml`
(`audience: user-guide`) whose `code_refs` name the source it describes
(`src/taskflow/core/model.py`) and which carries NO managed region, so cdx
tracks it by the whole-doc fingerprint over that surface and never rewrites its
prose (K2). Because it is a `user-guide`, a comment/docstring/private change to
`model.py` is a non-event (K3) — only a real public-surface change drifts the
README, surfacing a `ReviewRecord` for a human (K5); `cdx monitor --apply` then
refreshes only its fingerprint. cdx dogfoods the very same pattern on its OWN
`README.md` (tracked against `custodex/cli.py`), where an eng-only
`api-index` is NOT forced to list the user-guide README because the
`INDEX_INCOMPLETE` lint honors the index region's `kind: eng-guide` audience.
**How to observe.** Inspect the `readme` document in `demo/config/cdmon/core.yaml`
and the `cdm:` front matter atop `demo/README.md`, then run
`cdx check --config demo/config/cdmon` (the README is reported in sync). It also
shows in the console: open the `demo-taskflow` repo and the **README files**
section appears under both Documents and Mapping. Tests:
`tests/system/test_demo_e2e.py` (the demo's 8-document / 11-code-ref mapping incl.
`readme`) and
`tests/system/test_dogfood.py::test_dogfood_readme_is_a_monitored_user_guide_doc`.
Features: FEAT-CONFIGV2-016

### DEMO-058 — Tests are monitored too: the test→test-doc mirror
**What it shows.** Test files are monitored exactly like source: the `tests`
unit (`demo/config/cdmon/tests.yaml`, `dir-covered: [tests]`) maps every demo test
file under `demo/tests/` to **exactly one** test-doc under `demo/test-docs/` (1:1),
each an `eng-guide` document with a managed `symbols` region listing that file's
`test_*` functions. It is the SAME machinery as source → docs (no engine change —
a test file is just a `.py` file, K0): add/rename/remove a test and its test-doc
drifts for a human to review (K5); `cdx monitor --apply` heals it (K7). The unit
is fully documented (100%), so the demo's only gap stays the deliberate
`scheduler.py` SOURCE gap — note the symmetry that `scheduler.py`'s source is
undocumented yet its tests are documented in `test-docs/test_scheduler.md`. cdx
dogfoods the same pattern on its own `tests/smoke/` boundary.
**How to observe.** Inspect `demo/config/cdmon/tests.yaml` and the four
`demo/test-docs/test_*.md` files, then run `cdx check --config demo/config/cdmon`
(the test-docs are reported in sync) and `cdx coverage --config demo/config/cdmon`
(the `tests` unit is 100%). It also shows in the console: open `demo-taskflow` and
the **Test docs** section appears under Documents, Drift, and Mapping. Tests:
`tests/system/test_demo_e2e.py` (the four `test-*` docs in the 8-document mapping)
and `tests/system/test_testdoc_mirror.py` (the mirror's engine-level contract).
Features: FEAT-CONFIGV2-017

### DEMO-059 — Per-document ownership-of-record (config = truth)
**What it shows.** A monitored document declares WHO is accountable for it, in
config — the single source of truth for ownership (K0). `demo/config/cdmon/core.yaml`
gives the `core-api` doc `owner: demo-team`, `team: demo-team`, `dri: dana`: the
team owns it durably, with Dana as the current Directly-Responsible-Individual. The
keys are optional and additive (K6) — `getting-started` declares none and inherits
the unit's frontmatter owner — and they round-trip byte-identically through
`dump_unit_file`/`load_unit_file` (K7), so reassigning an owner is a clean,
idempotent config rewrite.
**How to observe.** Inspect `demo/config/cdmon/core.yaml` (the `core-api`
`owner`/`team`/`dri` block); `load_unit_file` then `dump_unit_file` of that unit is
byte-identical (the round-trip pinned by `tests/unit/test_ownership.py`).
Features: FEAT-OWNERSHIP-001

### DEMO-060 — Resolve accountable + durable owner (pure, clock-free)
**What it shows.** `ownership.resolve_ownership` turns the demo config into one
`EffectiveOwner` per document: for `core-api` it computes `accountable = dana` (the
current DRI) and `durable = demo-team` (the part that survives a person leaving);
for the unowned `getting-started` it inherits the unit owner. The roster
(`Identity`/`RosterSnapshot`) is the injected mirror — `is_active` reads an
unknown-or-departed name as inactive, the basis for orphan detection (OWN-02). All
pure, sorted, no clock (K1/K10).
**How to observe.** `resolve_ownership(load_bundle('demo/config/cdmon').config)`
yields `accountable=dana`/`durable=demo-team` for `core-api`; precedence + the
roster's inactive-on-unknown rule are pinned by `tests/unit/test_ownership.py`.
Features: FEAT-OWNERSHIP-002

### DEMO-061 — Departure → orphan detection (pure, offline)
**What it shows.** When a person leaves, the documents they were the DRI for must
not go silently ownerless. `ownership.detect_orphans` crosses the resolved
ownership of the demo config against a roster snapshot: with `dana` marked departed
but `demo-team` still active, the `core-api` doc (dri: dana, team: demo-team) is
flagged `ORPHAN_DRI_VACANT` — a SOFT orphan: the team still owns it, a new DRI just
needs assigning. Mark `demo-team` inactive too and it escalates to
`ORPHAN_OWNER_DEPARTED`. An unowned doc is `UNOWNED`; an active owner is omitted
(only what needs a human is returned, K5). All pure + offline (K1/K10) — no server.
**How to observe.** `detect_orphans(resolve_ownership(load_bundle('demo/config/cdmon').config), RosterSnapshot(identities=(Identity(name='dana', active=False), Identity(name='demo-team', active=True))))` flags `core-api` as `ORPHAN_DRI_VACANT`; the branch table is pinned by `tests/unit/test_ownership.py`.
Features: FEAT-OWNERSHIP-003

### DEMO-062 — `cdx ownership` lists owners + flags departed-owner orphans
**What it shows.** `cdx ownership --config demo/config/cdmon` prints all 8 demo
documents with their accountable owner — `core-api` is accountable=dana (its DRI),
while the docs that declare no owner of their own inherit the unit owner
`demo-team` (the per-doc fallback). Pass an offline roster that marks `dana`
departed and `cdx ownership --roster roster.yaml --fail-on-orphan` flags
`core-api` as `orphan_dri_vacant` and exits nonzero — an accountability gate you
can wire into CI. Read-only, offline (K1/K4), no backend.
**How to observe.** From the repo root: `cdx ownership --config demo/config/cdmon`
prints the per-document table; with a roster YAML `{identities: [{name: dana, active: false}, {name: demo-team, active: true}]}`, `cdx ownership --config demo/config/cdmon --roster roster.yaml --fail-on-orphan` exits 1 and names `core-api`. Pinned by `tests/system/test_ownership_cli.py`.
Features: FEAT-OWNERSHIP-004

### DEMO-063 — Central roster mirror persists over both stores (+ migration 0006)
**What it shows.** The central server keeps a roster of identities (people/teams) as
the accountability MIRROR, persisted identically over the in-memory store AND the
SqlStore (Postgres-first; SQLite is the offline twin). Alembic migration 0006
creates the `roster` table; the per-document `owner`/`team`/`dri` + resolved
`accountable`/`durable` ride in the existing `config_documents` JSON column
(additive, K6 — no column migration). `upsert_identity`/`list_roster`/
`mark_identity_departed` round-trip through both backends (insertion-ordered, K10).
**How to observe.** `alembic upgrade head` over a SQLite/Postgres URL creates the
`roster` table; `store.upsert_identity(Identity(name="dana"))` then `store.list_roster()`
returns it on both `InMemoryStore` and `SqlStore`. Pinned by
`tests/integration/test_ownership_server.py` (parametrized over both stores) and
`tests/integration/test_db.py::test_alembic_migration_0006_roster_up_then_down`.
Features: FEAT-OWNERSHIP-005

### DEMO-064 — Admin-token roster routes (a global token, not a per-repo token)
**What it shows.** Mutating the roster is a GLOBAL action (it re-flags orphans in
every repo), so `POST /admin/roster` and `POST /admin/roster/{name}/departed` are
gated by a SEPARATE admin token (`$CDMON_ADMIN_TOKEN`), never a per-repo token — a
leaked repo token must not grant roster access. Missing → 401, wrong → 403, right →
201; `GET /roster` is an open read; marking an unknown name departed is a loud 404.
**How to observe.** With `create_app(store, admin_token="s3cret")`,
`POST /admin/roster` with no `Authorization` returns 401, a wrong bearer 403, and the
right bearer 201; `GET /roster` needs no token. Pinned by
`tests/integration/test_ownership_server.py`.
Features: FEAT-OWNERSHIP-006

### DEMO-065 — One departure cascades to every repo's /ownership (read-time)
**What it shows.** `GET /repos/{id}/ownership` crosses each repo's synced document
ownership against the LIVE roster through `detect_orphans`, returning
`{owners, findings, orphan_count}`. Because the orphan check runs on READ, a single
`POST /admin/roster/dana/departed` flips every document Dana is accountable for — in
this repo and every other — to an orphan on the next read, with no re-sync. While
the `demo-team` stays active her `core-api` shows `orphan_dri_vacant` (a soft orphan:
reassign a DRI), not a hard loss.
**How to observe.** Register a repo, sync config with owners, `GET /ownership`
(orphan_count 0); `POST /admin/roster/dana/departed`; `GET /ownership` again →
`core-api` is `orphan_dri_vacant`, orphan_count 1. Pinned by
`tests/integration/test_ownership_server.py::test_ownership_view_and_departure_cascade`.
Features: FEAT-OWNERSHIP-007

### DEMO-066 — Reassign a document's owner (the orphan fix, config = truth)
**What it shows.** When an orphan surfaces (a departed DRI), the fix is a
reassignment — and config is the single source of truth, so it is written to disk.
A `reassign_owner` edit (`ReassignOwnerEdit`) carries the new owner/team/dri; the
pure `config.set_document_owner` editor applies it (a provided value sets that
field, `None` leaves it — so reassigning just the DRI keeps the team), and
`apply_edits_to_disk` rewrites `config/cdmon/<unit>.yaml` (byte-stable, idempotent
K7) before re-mirroring. Reassigning a departed DRI to an active person clears the
orphan on the next `GET /ownership`.
**How to observe.** On a copy of the demo, `apply_edits_to_disk(repo,
[ReassignOwnerEdit(unit="core", doc_id="core-api", dri="erin")], now=...)` rewrites
`core.yaml` so `core-api`'s dri is `erin` (owner/team unchanged); a second identical
apply is byte-identical. Pinned by `tests/integration/test_generate.py` and
`tests/unit/test_unit_serializer.py`.
Features: FEAT-OWNERSHIP-008

### DEMO-067 — Live demo shows a real departed-DRI orphan (out of the box)
**What it shows.** Launching the demo (`scripts/seed_demo.py`, :33333) seeds the
central roster: the teams that own the demo + dogfood configs are active, and `dana`
— the DRI of the demo's `core-api` doc — is DEPARTED. So opening `demo-taskflow` and
`GET /repos/demo-taskflow/ownership` shows a REAL soft orphan (`core-api`
`orphan_dri_vacant`: the `demo-team` still owns it, a new DRI just needs assigning),
while the dogfood repo (owned by the active `cdmon-team`) is clean — visible and
clickable on first load, not an empty state.
**How to observe.** With the seeded app, `GET /roster` shows `dana` inactive;
`GET /repos/demo-taskflow/ownership` returns `orphan_count: 1` with `core-api` →
`orphan_dri_vacant`; `GET /repos/custodex/ownership` returns `orphan_count: 0`.
Pinned by `tests/system/test_demo_e2e.py::test_central_ownership_view_shows_departed_dri_orphan`.
Features: FEAT-OWNERSHIP-009

### DEMO-068 — Settings model defaults reproduce today's server behavior
**What it shows.** `Settings()` with no file present is exactly the un-hardened
server: host `0.0.0.0`, port `33333`, CORS off, TrustedHost off (`["*"]`), no rate
limit, the `github.com`/`gitlab.com` git allowlist with `file://` allowed. The model
is frozen + `extra="forbid"`, so a typo'd key or an out-of-range port is loud.
**How to observe.** `Settings().server.port == 33333`; a bad key raises. Pinned by
`tests/unit/test_settings.py`.
Features: FEAT-SETTINGS-001

### DEMO-069 — Loud settings loader
**What it shows.** `load_settings(config/settings.yaml)` validates the file and turns
any malformed input (bad suffix, unreadable, bad yaml, non-mapping, unknown key,
out-of-range value) into a typed `ConfigError`; an empty file is the defaults.
**How to observe.** `load_settings(config/settings.yaml) == Settings()` (the shipped
file encodes the defaults). Pinned by `tests/unit/test_settings.py`.
Features: FEAT-SETTINGS-002

### DEMO-070 — Env overrides the file; secrets only ever report presence
**What it shows.** `CDMON_SERVER_PORT=7007` (and the other `CDMON_*` knobs) override
the file value (env wins); `secret_presence()` reports whether the admin token / DB
url / KEK are set — never their values.
**How to observe.** `cdx settings` with `CDMON_SERVER_PORT=7007` prints
`server.port: 7007`; with `CDMON_ADMIN_TOKEN` set prints `admin_token_configured: set`
but never the token. Pinned by `tests/unit/test_settings.py` + `tests/system/test_settings_cli.py`.
Features: FEAT-SETTINGS-003

### DEMO-071 — Hardening middleware appears only when configured
**What it shows.** With default settings the app installs NO CORS/TrustedHost/rate-limit
middleware (identical to before); set `trusted_hosts` and a spoofed `Host` is a 400;
list `cors.allow_origins` and a cross-origin preflight is answered; set
`rate_limit.requests_per_minute` and requests past the cap get 429.
**How to observe.** `GET /health` with a bad `Host` → 400 when `trusted_hosts` is set.
Pinned by `tests/integration/test_server_settings.py`.
Features: FEAT-SETTINGS-004

### DEMO-072 — Git SSRF allowlist + clone timeout from settings
**What it shows.** `server.git.extra_allowed_hosts` adds a self-hosted GHE/GitLab host
to the clone/PR allowlist, `allow_file_scheme: false` forbids `file://` in a shared
deployment, and `clone_timeout_seconds` makes a hung clone a loud `SyncError`.
**How to observe.** `_check_remote_allowed("https://ghe.corp.io/x", git=...)` passes
when listed; a clone that exceeds the timeout raises. Pinned by
`tests/integration/test_server_settings.py` + `tests/integration/test_gitfetch.py`.
Features: FEAT-SETTINGS-005

### DEMO-073 — The central server binds from settings
**What it shows.** `main()` reads host/port/log level from the resolved settings
instead of the hardcoded `0.0.0.0:33333`, and the app version is single-sourced from
the package metadata (it was duplicated).
**How to observe.** The FastAPI `app.version` and the `/` landing `version` are the
same single value. Pinned by `tests/integration/test_server_settings.py`.
Features: FEAT-SETTINGS-006

### DEMO-074 — Redacted GET /settings
**What it shows.** `GET /settings` returns the effective non-secret settings plus the
secret presence booleans — the payload the console Settings page renders — and never
leaks a secret value even when the env secrets are set.
**How to observe.** On the live demo, `GET /settings` returns `{settings, secrets}`
with `secrets.admin_token_configured` a boolean and no token string anywhere. Pinned
by `tests/integration/test_server_settings.py`.
Features: FEAT-SETTINGS-007

### DEMO-075 — cdx settings shows the effective configuration
**What it shows.** `cdx settings` prints the resolved host/port + hardening knobs and
the secret presence (never values); `--json` emits the same; a malformed file exits 1.
**How to observe.** `cdx settings --json` emits `{settings, secrets}`; a bad
`--settings` file exits 1 with `error:`. Pinned by `tests/system/test_settings_cli.py`.
Features: FEAT-SETTINGS-008

### DEMO-076 — Pure staleness grading
**What it shows.** `grade_doc`/`detect_stale` grade a document's `reviewed` date against
an INJECTED `now` — never the wall clock — so the verdict is deterministic and testable.
**How to observe.** `detect_stale([...], now="2026-06-22T00:00:00Z", default_days=90)`
returns the same findings every run. Pinned by `tests/unit/test_staleness.py`.
Features: FEAT-STALENESS-001

### DEMO-077 — Fresh / stale / never-reviewed
**What it shows.** A doc reviewed within its SLA is FRESH (omitted from the report), one
reviewed longer ago is STALE (with the age in days), one with no `reviewed` stamp is
NEVER_REVIEWED; findings are sorted by doc_id and a bad date is loud.
**How to observe.** Three docs (reviewed 172 days ago / 2 days ago / never) → STALE +
NEVER_REVIEWED, FRESH omitted. Pinned by `tests/unit/test_staleness.py`.
Features: FEAT-STALENESS-002

### DEMO-078 — Config-as-truth review stamp + audience-aware SLA
**What it shows.** The document's `reviewed` date lives in config (the source of truth),
and `staleness.audience_days` gives a `user-guide` a longer SLA than an `eng-guide` — the
SAME old review date is fresh for one audience and stale for the other.
**How to observe.** With `audience_days: {user-guide: 365}`, a user-guide reviewed 172
days ago is FRESH while an eng-guide is STALE. Pinned by `tests/unit/test_staleness.py`.
Features: FEAT-STALENESS-003

### DEMO-079 — cdx staleness CLI
**What it shows.** `cdx staleness --now <ISO>` lists the docs needing a review; `--json`
shows all; `--fail-on-stale` turns it into a CI review gate (exit 1 on any stale/never).
**How to observe.** `cdx staleness --config <cfg> --now 2026-06-22T00:00:00Z` prints the
stale/never docs; `--fail-on-stale` exits 1. Pinned by `tests/system/test_staleness_cli.py`.
Features: FEAT-STALENESS-004

### DEMO-080 — Reviewed + resolved SLA mirrored at sync
**What it shows.** A sync projects each document's `reviewed` date plus the audience-resolved
`sla_days` into the server mirror, so the server grades against the mirror without
re-deriving the policy.
**How to observe.** `_build_rows` over a config with `staleness.default_days: 30` +
`audience_days: {user-guide: 365}` yields ConfigDocuments carrying `reviewed` + the resolved
`sla_days`. Pinned by `tests/integration/test_configsync.py`.
Features: FEAT-STALENESS-005

### DEMO-081 — Read-time GET /staleness
**What it shows.** `GET /repos/{id}/staleness` grades the synced docs against the app clock
at read time (deduped, FRESH omitted unless `include_fresh`), so a doc goes stale on the
next read with no re-sync.
**How to observe.** With a fixed clock, `GET /repos/acme%2Fwidget/staleness` returns the
stale + never-reviewed docs and a `stale_count`. Pinned by
`tests/integration/test_staleness_server.py`.
Features: FEAT-STALENESS-006

### DEMO-082 — Declare a doc↔doc dependency (config = truth)
**What it shows.** A document declares it `depends_on` an upstream document (a typed edge:
depends/refines/implements/verifies) in config — the source of truth (K2) — and the whole
policy (enable/gate/default-type/inference) is a `docdeps` config block, nothing hardcoded.
A self-edge, a duplicate upstream, or an edge to an unknown doc id is a loud ConfigError.
**How to observe.** The demo's `getting-started` user-guide declares `depends_on: [{doc:
core-api, type: refines}]`; a config with an unknown upstream id fails to load. Pinned by
`tests/unit/test_docdeps_config.py`.
Features: FEAT-DOCDEPS-001

### DEMO-083 — Suspect-link detection (the two-fingerprint model)
**What it shows.** The downstream stores a per-edge baseline hash of the upstream's BODY in
its `cdm.upstream_hashes` front matter (separate from its own `cdm.fingerprint`); when the
upstream's body changes the stamp no longer matches and the edge is SUSPECT. Hashing the
body (not the front matter) means the upstream's own code↔doc re-stamp never trips it.
**How to observe.** `detect_suspect_links` returns OK after stamping, then SUSPECT once the
upstream body is edited; the verdict is pure + sorted. Pinned by `tests/unit/test_docdeps.py`.
Features: FEAT-DOCDEPS-002

### DEMO-084 — Infer edges from Markdown links + per-edge baseline
**What it shows.** Rather than draw the graph by hand, `infer_edges_from_links` proposes
edges from the relative Markdown cross-links docs already contain (author→approve), and
`stamp_edges` writes one edge's baseline idempotently (never on the detect-only check).
**How to observe.** A doc linking `[overview](overview.md)` yields one inferred edge;
re-stamping an unchanged edge writes nothing. Pinned by `tests/unit/test_docdeps.py`.
Features: FEAT-DOCDEPS-003

### DEMO-085 — SUSPECT_LINK through cdx check (audience-scoped)
**What it shows.** A suspect link surfaces through the normal drift path as
`DriftKind.SUSPECT_LINK` (healable=False — never auto-edited), carrying the downstream
doc's audience, so `cdx check` reports it with zero extra wiring; `docdeps.enabled` gates
whether it is computed at all.
**How to observe.** After an upstream edit, `detect` reports a SUSPECT_LINK for the
downstream; disabling docdeps suppresses it. Pinned by `tests/unit/test_drift_suspect_link.py`.
Features: FEAT-DOCDEPS-004

### DEMO-086 — cdx deps + cdx resolve --edge + the gate
**What it shows.** `cdx deps` shows the graph + suspect status, `cdx deps --suggest` prints
paste-ready config from inferred links, and `cdx resolve --edge DOWN UP` re-stamps exactly
one edge (the Doorstop `clear`). `cdx check` gates on a suspect link by default (unlike
Doorstop, which exits 0) — tunable via `docdeps.gate`.
**How to observe.** `cdx check` exits 1 on a suspect edge, then 0 after `cdx resolve --edge`;
with `docdeps.gate: false` it stays 0 but still reports. Pinned by
`tests/system/test_docdeps_cli.py`.
Features: FEAT-DOCDEPS-005

### DEMO-087 — Monitor records suspect links + baselines new edges
**What it shows.** The Monitor never sends a suspect link to the backend (a fix would
clobber the downstream); on `--apply` it baselines a brand-new UNSTAMPED edge (recorded as
a FIX) but ESCALATEs a genuinely changed upstream to a human and never auto-edits the
downstream. A re-run with no change is a no-op (K7).
**How to observe.** `monitor --apply` baselines the new edge then is idempotent; after an
upstream change it records an ESCALATE and leaves the downstream untouched. Pinned by
`tests/integration/test_monitor_docdeps.py`.
Features: FEAT-DOCDEPS-006

### DEMO-088 — Central hub mirrors the doc↔doc graph
**What it shows.** A sync projects each document's declared `depends_on` edges into the
server mirror (additive — it rides in the ConfigDocument JSON, no migration, both stores),
and `GET /repos/{id}/doc-graph` serves the cross-repo dependency graph (who-depends-on-what)
so a reverse query is answerable centrally; suspect status stays repo-local (K2).
**How to observe.** After a sync, `GET /repos/acme%2Fwidget/doc-graph` returns the
downstream→upstream edges with their type; an unknown repo is 404. Pinned by
`tests/integration/test_docdeps_server.py`.
Features: FEAT-DOCDEPS-007

### DEMO-089 — Indexed reverse lookup: who depends on X
**What it shows.** The hub flattens every document's `depends_on` into the indexed
`config_doc_edges` table (Alembic 0007, mirrored derive-on-read by the in-memory store),
so "which docs depend on X" is an indexed `WHERE upstream_id = X` instead of a JSON scan.
`GET /repos/{id}/doc-graph/reverse?doc=X` serves the direct dependents (deduped, sorted).
**How to observe.** After a sync, `GET /repos/acme%2Fwidget/doc-graph/reverse?doc=io-api`
returns the documents that depend on `io-api`; a leaf returns an empty list; a missing
`doc` query is 422 and an unknown repo is 404. Pinned by
`tests/integration/test_docdeps_server.py` + `tests/integration/test_db.py`.
Features: FEAT-DOCDEPS-008

### DEMO-090 — Blast radius: `cdx deps --impact`
**What it shows.** The proactive complement to suspect detection: BEFORE editing a
document, `cdx deps --impact DOC` walks the dependents reverse-reachable from `DOC`
(transitive, cycle-safe) and lists every document that would need re-review — turning the
"what will I break" question into one read-only command (no backend, no network, K1/K4).
**How to observe.** `cdx deps --impact io-api` prints the documents that depend on
`io-api`; a leaf prints "safe to change"; an unknown id is a loud error; `--json` emits
the machine form. Pinned by `tests/system/test_docdeps_cli.py` +
`tests/unit/test_docdeps.py`.
Features: FEAT-DOCDEPS-009

### DEMO-091 — Breaking-change severity on a HASH drift
**What it shows.** A code↔doc HASH drift now carries a Griffe-style severity classified
from the tier + anchor signals Custodex already captures: a removed/renamed symbol or an
in-place signature change is **breaking**, a purely added symbol is **additive**, and a
docstring/body-only move is **cosmetic** — so a reviewer (and the central audit) can tell
an API-breaking doc drift from a harmless prose update at a glance.
**How to observe.** Change a tracked module's public signature and `cdx check` annotates
the HASH line `[breaking]`; add a new public symbol and it reads `[additive]`; edit only a
docstring and it reads `[cosmetic]`. The verdict rides on the `ReviewRecord`'s additive
`change_severity` field (schema 1.2.0). Pinned by `tests/unit/test_drift.py` +
`tests/integration/test_monitor.py`.
Features: FEAT-DRIFT-011

### DEMO-092 — Transitive suspect advisory (`cdx deps --transitive`)
**What it shows.** The EAGER complement to direct suspect detection, kept HYBRID: in a
chain `top → mid → leaf`, changing `leaf` flags `mid` DIRECTLY suspect (the only edge that
gates `cdx check`), while `top` — whose upstream `mid` is now itself pending review — is
surfaced as a **transitive** advisory. It never mints a drift (a transitive edge has no
changed upstream body to stamp, K1/K7) and never changes the gate; it just shows the full
blast radius NOW. Default OFF (the `docdeps.transitive` knob), shown on demand.
**How to observe.** `cdx deps --transitive` lists the directly-suspect edges and then a
clearly-labelled "transitively suspect (pending wavefront; does NOT gate)" advisory
section; `cdx check` still exits non-zero only on the DIRECT suspect. Centrally,
`GET /repos/{id}/doc-graph/reverse?doc=X&transitive=true` returns the whole reverse-reachable
closure as pure graph reachability (never a suspect verdict, K2). Pinned by
`tests/system/test_docdeps_cli.py` + `tests/integration/test_docdeps_server.py` +
`tests/unit/test_docdeps.py`.
Features: FEAT-DOCDEPS-010

### DEMO-093 — Per-symbol digests close the masked breaking change
**What it shows.** Before DIG-01, adding a new public symbol AND changing an existing
symbol's signature in the SAME edit graded **additive** — the aggregate tier signals
could not separate the in-place break from the addition. Now Custodex stamps a per-symbol
signature digest (`cdm.symbol_sigs`, keyed by the stable `anchor_id`, hashing only the
signature payload) at heal, and `detect` diffs the SURVIVING symbols' digests: a moved
signature is **breaking** even alongside an addition. A pure addition stays additive and a
docstring/body-only change stays cosmetic (no over-fire); a doc that predates DIG-01
degrades to the old aggregate behaviour and never crashes.
**How to observe.** Sync a doc, then in ONE edit add a public function AND change a
parameter on an existing one: `cdx check` annotates the HASH line `[breaking]` (was
`[additive]`), and the `ReviewRecord`'s `change_severity` reads `breaking` — no schema
change, just a more accurate verdict. Pinned by `tests/unit/test_drift.py` +
`tests/unit/test_extract.py` + `tests/unit/test_manifest.py`.
Features: FEAT-DRIFT-012

### DEMO-094 — Per-owner review worklist (`cdx worklist`)
**What it shows.** The accountability JOIN: instead of running `cdx ownership`,
`cdx staleness` and `cdx deps` separately, ONE command buckets every document needing
attention — an ownership **orphan** (EPIC OWN), a **stale** review (EPIC SLA), or a
doc↔doc **suspect** link (Pillar B) — under its accountable owner, as one prioritised
queue per person. A document with several problems is several items but ONE document
(distinct item/doc counts); `--owner` filters to one queue; `--fail-on-work` is an
opt-in CI gate. The central hub serves the same join from the mirror (orphans +
staleness) but OMITS suspect links (it has the dependency graph, not the bodies to hash
an upstream, K2) and says so via `includes_suspect:false`.
**How to observe.** Against the demo, `cdx worklist --roster roster.yaml` prints each
owner's queue with a `[severity] reason` line per item (the demo's `core-api` is both
stale and — once its DRI departs — orphaned); `cdx worklist --owner demo-team` shows
just that queue; `--no-include-suspect` drops the suspect items; the central
`GET /repos/{id}/worklist` returns the hub's partial join. Pinned by
`tests/unit/test_worklist.py` + `tests/system/test_worklist_cli.py` +
`tests/integration/test_worklist_server.py`.
Features: FEAT-WORKLIST-001

## N. The task-agent layer (EPIC AGT — entities, mapping, graph, suggesters)

### DEMO-098 — Deterministic entity mentions (`cdx entities`)
**What it shows.** The AGT-01 mention layer: every backticked symbol / path /
env-var span and markdown link in a managed doc's PROSE, linked against a closed
registry built from the code surface + the managed-doc set + the full repo tree —
deterministically, offline, with no LLM anywhere (the LazyGraphRAG split: the index
is pure; a model only ever consumes it). Machine text never mints a mention (CDM
regions and code fences are stripped), and the precision rules never guess: a
backticked `Class.method` or unique snake_case name resolves to its defining file
(`symbol <path>#<name>`), a module name resolves as a PATH mention, an HTTP route,
glob, or CLI invocation mints nothing, and a bare word that collides with a module
stem (the `app`/`coverage`/`index` trap) is blocked rather than misresolved.
**How to observe.** Against the demo repo, `cdx entities` prints each doc's
mentions with file-accurate line numbers (`L42 \`TaskFlow\` [symbol] → symbol
src/taskflow/core/engine.py#TaskFlow`); `cdx entities getting-started` filters to
one doc; `--json` emits the sorted structured lists. Two consecutive runs are
byte-identical (K10). Pinned by `tests/unit/test_entities.py` +
`tests/system/test_entities_cli.py`.
Features: FEAT-ENTITIES-001

### DEMO-099 — The clean rot signal (`cdx entities --unresolved` + the stoplist)
**What it shows.** Unresolved mentions are first-class data — the graph-rot
detector: a prose reference to a symbol or file that no longer exists (or never
did) surfaces as `UNRESOLVED`, while everything ambiguous is ignored rather than
guessed. The signal is trustworthy because it starts EMPTY: target-specific noise
enters through config (K0) — the `entities:` block's `ignore` stoplist and
`env_prefixes` gate — and Custodex's own dogfood corpus is pinned at ZERO
unresolved mentions by an integration test, so any regression (or any real rot)
fails loudly. The registry is resilient: one unparseable source file becomes a
warning, never an abort.
**How to observe.** `cdx entities --unresolved --config config/cdmon` on this repo
prints `0 unresolved`; rename a public symbol that the README mentions in backticks
(or delete a file a doc references) and the mention flips to `UNRESOLVED` on the
next run. `CDMON_`-prefixed backticked spans resolve as env-var entities because
`config/cdmon/index.yaml` seeds `entities.env_prefixes: [CDMON_]`; an enum-name-like
`SOME_CONSTANT` mints nothing. Pinned by `tests/integration/test_entities_dogfood.py`
+ `tests/unit/test_entities_config.py` + `tests/smoke/test_demo_ids.py` (the
DEMOS.md id-uniqueness lint that ships with this slice).
Features: FEAT-ENTITIES-002, FEAT-ENTITIES-003

### DEMO-100 — Entity-grounded edge suggestions (`cdx deps --suggest`, AGT-02)
**What it shows.** Doc↔doc mapping stops being hand-authored: the suggester
proposes `depends_on` edges with a provenance TIER and evidence — `resolved_link`
when one doc's prose markdown-links another, `shared_symbol` when doc A's prose
mentions a code symbol that EXACTLY ONE doc B covers via `code_refs` (so the
direction is principled: the mentioning doc depends on the documenting doc).
Machine text cannot suggest (CDM regions/fences are stripped by the mention
layer); an `index: true` doc's mandated navigation links are excluded; a symbol
covered by two docs is ambiguous and never guessed. Each code-tracked upstream
carries a churn note warning that reheals will flip the edge SUSPECT under the
default `body` baseline — and that `docdeps.baseline: prose` (which this repo's
own config uses) makes machine reheals hash-invisible so only human prose changes
trip dependents.
**How to observe.** Against the demo, `cdx deps --suggest` prints the tiered
suggestions with paste-ready YAML + evidence + churn notes; `--json` items carry
`{doc_id, upstream_id, via, tier, evidence, score}` (a key-superset of the legacy
shape). With `docdeps.infer_from_links: true`, plain `cdx deps` appends a one-line
advisory summary. Pinned by `tests/unit/test_docmap.py` +
`tests/unit/test_docdeps_baseline.py` + `tests/system/test_docmap_cli.py`.
Features: FEAT-DOCMAP-001, FEAT-DOCMAP-002

### DEMO-101 — Accept or reject a suggestion (`cdx link`, the K11 loop closed)
**What it shows.** The human verbs: `cdx link DOWN UP` DECLARES the suggested edge
in the unit YAML by a comment-preserving textual splice (hand-written YAML comments
survive byte-for-byte — never a model re-serialization), self-validates the spliced
config, and stamps the new edge's baseline so it arrives reviewed (`cdx check`
stays green; the suggestion disappears from the next `--suggest` run, K7).
`cdx link --reject DOWN UP` records a durable verdict in
`.cdmon/edge-rejections.jsonl` so a declined suggestion NEVER re-surfaces — the
rejection memory with an audit trail (who/when/why).
**How to observe.** On a scratch copy of the demo: `cdx deps --suggest` → pick a
pair → `cdx link <down> <up>` → the unit file gains the `depends_on:` entry with
every comment intact and `cdx deps` shows the edge OK; re-run `--suggest` → gone.
`cdx link --reject <down> <up> --by you --note "not a real dependency"` → gone
forever. Pinned by `tests/system/test_docmap_cli.py` (accept e2e incl. the
comment-preservation byte assertion + reject durability).
Features: FEAT-DOCMAP-003

### DEMO-102 — The knowledge graph (`cdx graph`)
**What it shows.** One deterministic fold of everything Custodex already knows
into a typed, provenance-tiered graph: which doc DOCUMENTS which symbols (the
code_refs join), which doc DEPENDS_ON which (declared edges), what each doc
MENTIONS and LINKS_TO in its prose (the AGT-01 layer), each doc's sections
(PART_OF) and accountable owner (OWNED_BY) — with the per-doc unresolved-mention
counts riding along as the rot signal. Zero LLM: the graph is base facts; derived
queries (neighbors, centrality) recompute from them. Section names are slugs, so
the artifact carries no doc-body prose — safe to mirror centrally (K2).
**How to observe.** Against the demo, `cdx graph` prints the summary (node/edge
counts by kind); `cdx graph --focus "doc docs/getting-started.md"` shows every
edge around that doc; `--json` emits the whole artifact; `--write` produces the
regenerable `.cdmon/graph.json` and prints "unchanged" on an immediate re-run
(K7). Two builds are byte-identical (K10). Pinned by `tests/unit/test_kgraph.py`
+ `tests/system/test_kgraph_cli.py`.
Features: FEAT-KGRAPH-001

### DEMO-103 — What to document next (`cdx graph --rank`) + the hub mirror
**What it shows.** The graph turns coverage gaps into a PRIORITISED queue: a
symbol that many docs mention but NO doc covers is the best-justified thing to
document next — `--rank` lists exactly those (count = distinct mentioning docs,
so one doc can't stuff the ballot). And the hub gets the same picture without
ever seeing a doc body: the repo pushes the graph as an opaque versioned snapshot
(`POST /repos/{id}/graph`, token-gated) and the console reads the latest
(`GET /repos/{id}/graph`) — the coverage-snapshot pattern applied to the graph.
**How to observe.** Against the demo, mention an uncovered symbol in two docs'
prose and `cdx graph --rank` puts it on top; push with an authorized token → the
GET returns the latest snapshot; an unknown repo 404s, a wrong token 403s (the
E-06 matrix), and both stores serve identical results (parity-tested). Pinned by
`tests/integration/test_server_store_parity.py` (graph trio) +
`tests/integration/test_db.py` (Alembic 0008 up/down) +
`tests/system/test_kgraph_cli.py`.
Features: FEAT-KGRAPH-002
