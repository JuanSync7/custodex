# CONFIG-V2 — multi-file `config/cdmon/` layout, DB-backed sync, demo, per-repo view

This spec governs the evolution from the single root `cdmon.yaml` to a multi-file
`config/cdmon/` layout, a DB-backed document/code-ref store with a Sync button,
a `.rpt` coverage report, writing-style templates, a fully-functional `demo/`
adopter repo, and a per-repo standalone view. It is the source of truth every
CONFIG-V2 slice (epics **N/Y/W/L/M/Z**) implements against. It cites the binding
constraints in `CONSTRAINTS.md` (K0–K10).

> **See also — `.project/spec/EDITOR.md`.** The interactive config editor (epic
> EDITOR) builds directly ON this layout: a per-repo browser Mapping page renders
> the `config/cdmon/*.yaml` document↔code mapping live, stages edits as
> `config_edits` "tickets", and runs a "Generate / make live" action that writes
> the edits back to the on-disk units + index (the CONFIG-V2 serializers/loaders
> here), scaffolds/heals the docs, and re-runs the DB-backed sync defined in §4 so
> the dashboard reflects the live state. It also adds the additive `context_refs`
> unit-file key (generation context, NOT coverage) and a one-click apply-LLM-fix.
> Disk stays the git-tracked source of truth; SQL is the live mirror.

---

## 0. Design decisions (locked)

- **`.rpt` is YAML** with a leading `---` frontmatter block (NOT JSON). Rationale:
  the whole config ecosystem is YAML; frontmatter is a natural YAML/markdown
  idiom; hierarchy reads cleanly. The `.rpt` is GENERATED, never hand-edited (K7
  idempotent: re-running with no change rewrites byte-identical content).
- **Backward compatibility:** `load_config()` keeps loading a single
  `cdmon.yaml`/`.json` file unchanged. A NEW `load_config_dir()` loads the
  `config/cdmon/` layout and merges it into the SAME `MonitorConfig` model, so
  every downstream module (drift, coverage, heal, manifest, server) is untouched.
  The CLI auto-detects: if `config/cdmon/index.yaml` exists it uses the dir
  layout, else it falls back to `--config` single-file (default `cdmon.yaml`).
- **One `MonitorConfig`:** the dir layout is a *projection* — merging all unit
  files + index globals yields exactly one `MonitorConfig`. No downstream code
  learns about units. Units add two new fields per document group used ONLY by
  coverage scoping and the `.rpt`/relationship views: `dir_covered` and
  `source_files_format`.
- **Server reads repos from a local filesystem path.** A registered repo carries
  an optional `local_path`. Git sync reads `git show <branch>:config/cdmon/*`;
  local sync reads the working tree. This keeps the demo fully functional offline
  with real git, no network.

---

## 1. The `config/cdmon/` layout

```
<repo-root>/config/cdmon/
  index.yaml          # globals + index of every unit file (REQUIRED; presence = "use dir layout")
  ignore.yaml         # ignore patterns + .gitignore sync (REQUIRED)
  doc-style.yaml      # maps each document -> 4 writing templates (REQUIRED if templates used)
  <unit>.yaml         # one or more coverage UNITS (e.g. foundation.yaml, agent-workflow.yaml)
  coverage.rpt        # GENERATED coverage report (YAML + frontmatter)
```

Reserved stems that are NOT units: `index`, `ignore`, `doc-style`. Everything
else matching `*.yaml` is a unit. `*.rpt` files are reports, never units.

### 1.1 Unit file — `<unit>.yaml`

```yaml
---
# Frontmatter: traceability metadata (REQUIRED block, fenced by --- ... ---)
cdmon-config-version: "2.0.0"   # REQUIRED, must be "2.0.0"
unit: agent-workflow            # REQUIRED, must equal the filename stem
title: "Remediation agent (LangGraph) coverage"   # REQUIRED, human title
owner: eng-platform             # REQUIRED, team/person accountable
created: "2026-06-07"           # REQUIRED ISO date
updated: "2026-06-07"           # REQUIRED ISO date
---
# Body: coverage scope + documents
dir-covered:                    # REQUIRED, >=1 repo-relative directory this unit owns
  - code_doc_monitor/agent
source-files-format:            # REQUIRED, >=1 extension; only these count toward coverage
  - ".py"
documents:                      # REQUIRED, >=1 DocumentSpec (same schema as today)
  - id: agent-workflow
    path: docs/api/agent-workflow.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: code_doc_monitor/agent/backend.py
      - path: code_doc_monitor/agent/graph.py
      # ...
```

Rules:
- `unit` MUST equal the filename stem (loud `ConfigError` otherwise, K8).
- `dir-covered` directories MAY NEST across units (a parent unit + a child unit
  whose `dir-covered` is under the parent's) — **nesting is allowed, deepest-wins**
  (Z-01a). A file is attributed to the DEEPEST unit whose `dir-covered` contains
  it (the longest matching directory prefix, compared BY PATH COMPONENTS — so
  `a/agent` never covers `a/agentry`). Only two units sharing an IDENTICAL
  (normalized) `dir-covered` path genuinely conflict and raise a loud
  `ConfigError` (K8); equivalent spellings — trailing slash, `./`, `//` — count
  as identical. `config.unit_for_path(bundle, path)` is the single resolver every
  consumer (coverage scoping, the `.rpt` per-unit breakdown, `suggested_unit`)
  shares.
- `source-files-format` lists the extensions (with leading dot) that count toward
  coverage for files under `dir-covered`. A file under `dir-covered` whose
  extension is NOT in `source-files-format` is EXCLUDED from the coverage
  denominator (this is how `.log`/`.rpt` etc. avoid being "uncovered"). With
  nested units the format scoping is **deepest-wins too**: a file under a child
  unit is scoped by the CHILD's `source-files-format`, not the parent's — so a
  `.py` file under a child that scopes only `.log` is excluded even though the
  parent (scoping `.py`) would have kept it (and vice-versa). Files outside every
  unit's `dir-covered` are not scoped to any unit.
- Each document's `code_refs[].path` SHOULD live under this unit's `dir-covered`
  (warning, not error, in the `.rpt`).
- All `DocumentSpec` fields (`id`, `path`, `audience`, `code_refs`,
  `region_keys`, `region_modes`, `html`, `index`, `nav_section`, `nav_label`) are
  unchanged from `config.py`.

### 1.2 `index.yaml` — globals + unit index

```yaml
---
cdmon-config-version: "2.0.0"   # REQUIRED
repo: code-doc-monitor          # REQUIRED, repo id/name
generated-by: cdmon             # REQUIRED provenance string
updated: "2026-06-07"           # REQUIRED
---
root: "../.."                   # repo root relative to config/cdmon/ (default "../..")
version: "2.0.0"
apply_default: false
backend: {kind: mock}           # global BackendConfig
agent: {driver: claude-code}    # global AgentConfig (optional)
central: {sink: none}           # global CentralConfig
region_templates:               # global region templates (same schema as today)
  api-index: {source: index, columns: [...]}
coverage:
  waive:                        # global waivers (same WaiverEntry schema)
    - {path: "code_doc_monitor/__init__.py", reason: "re-export aggregator"}
units:                          # index of every unit file (REQUIRED)
  - file: foundation.yaml
  - file: agent-workflow.yaml
ignore: ignore.yaml             # pointer (default "ignore.yaml")
doc-style: doc-style.yaml       # pointer (default "doc-style.yaml")
```

Rules:
- `root` is the repo root **relative to the directory the config lives in**
  (`config/cdmon/` for the dir layout, so the default is `../..`; the repo root
  for a single file, so the default is `.`). There is ONE resolver,
  `resolve_repo_root(config_dir, root) = normpath(config_dir / root)`, shared by
  every consumer (`Monitor`, `drift.detect`, `effective_coverage`, the doc-style
  `templates_root`, and `cdmon rpt`) so the two layouts can never diverge.
- `units[].file` MUST list every `*.yaml` unit present in the dir, and every
  listed file MUST exist — a missing-from-index unit OR an indexed-but-absent
  file is a loud `ConfigError` (K8). `cdmon index` regenerates this list.
- The merge: `MonitorConfig.documents` = concatenation of every unit's
  `documents` (stable order = index `units` order, then in-file order).
  `version/root/backend/agent/central/apply_default/region_templates/coverage`
  come from `index.yaml`. Duplicate document `id` across units is a loud K8.

### 1.3 `ignore.yaml`

```yaml
---
cdmon-config-version: "2.0.0"   # REQUIRED
source: ".gitignore + manual"   # REQUIRED provenance
updated: "2026-06-07"           # REQUIRED
---
gitignore: true                 # if true, the repo .gitignore patterns are merged in
patterns:                       # manual ignore globs (same ** semantics as inventory)
  - "**/__pycache__/**"
  - "**/.venv/**"
  - "*.rpt"
```

The effective ignore set = `patterns` ∪ (parsed `.gitignore` globs if
`gitignore: true`). It feeds the coverage scan's `exclude` (a file matching the
ignore set is removed from the coverage universe — never "uncovered").

### 1.4 `doc-style.yaml` — writing-template mapping

```yaml
---
cdmon-config-version: "2.0.0"   # REQUIRED
kind: doc-style-map             # REQUIRED literal
updated: "2026-06-07"           # REQUIRED
---
defaults:                       # used when a doc has no explicit mapping
  document-type: api-reference
  tone: precise
  writing-style: reference-dense
  vocabulary: engine-domain
mappings:
  - doc: agent-workflow         # a document id
    document-type: api-reference
    tone: precise
    writing-style: reference-dense
    vocabulary: engine-domain
```

Each name resolves to `templates/writing/<category>/<name>.md`. A mapping naming
a missing template file is a loud K8. The agent composes these 4 files into its
authoring prompt.

---

## 2. Writing templates — `templates/writing/`

```
templates/writing/
  document-type/   api-reference.md  tutorial.md  how-to.md  explanation.md  ...
  tone/            precise.md  friendly.md  formal.md  ...
  writing-style/   reference-dense.md  narrative.md  concise.md  ...
  vocabulary/      engine-domain.md  general.md  ...
```

Each is a short markdown guidance file the agent injects when authoring a doc.
Four independent categories, many templates each. `doc-style.yaml` selects one
per category per document.

---

## 3. `coverage.rpt` — the report

GENERATED by `cdmon rpt` (and emitted during `cdmon sync`). YAML + frontmatter:

```yaml
---
cdmon-report-version: "1.0.0"   # REQUIRED
kind: coverage                  # REQUIRED literal
repo: code-doc-monitor          # REQUIRED
ref: main                       # branch/commit the report reflects
generated-by: cdmon rpt         # REQUIRED provenance
---
summary:
  scanned_files: 42             # files under some unit dir-covered, format-matched, minus ignore
  documented_files: 39
  waived_files: 1
  ignored_files: 7
  uncovered_files: 2
  percent: 92.86                # 100 * documented / (scanned - waived)
units:
  - unit: agent-workflow
    file: agent-workflow.yaml
    scanned: 5
    documented: 5
    percent: 100.0
    uncovered: []
undocumented:                   # files needing doc-sync, with where to declare them
  - path: code_doc_monitor/agent/newnode.py
    suggested_unit: agent-workflow.yaml
    reason: "under dir-covered 'code_doc_monitor/agent' and format '.py'"
```

`percent` math matches `CoverageReport.percent_files` semantics (waived removed
from both sides). `undocumented[].suggested_unit` = the unit whose `dir-covered`
contains the file AND whose `source-files-format` includes its extension; if none
matches, `suggested_unit: null` with a reason.

---

## 4. DB tables + sync (epic Y)

New SQLAlchemy tables (additive migration `0003`), mirrored in InMemoryStore:

- **config_documents**: `id` PK, `repo_id`, `doc_id`, `path`, `audience`,
  `unit`, `region_keys`(json), `ref`(branch/commit synced from),
  `sync_kind`('git'|'local'), `synced_at`. UNIQUE(`repo_id`,`doc_id`,`sync_kind`).
- **config_code_refs**: `id` PK, `repo_id`, `doc_id`, `path`, `symbols`(json),
  `unit`, `sync_kind`. (children of a document)
- **sync_runs**: `id` PK, `repo_id`, `sync_kind`, `ref`, `branch`,
  `head_commit`, `main_commit`, `commits_ahead`, `fully_synced`(bool),
  `documents`, `code_refs`, `drift`(json summary), `started_at`, `finished_at`.

Store methods (Protocol + InMemory + Sql, parity-tested):
`replace_config(repo_id, sync_kind, docs, code_refs, ref)`,
`config_documents_for(repo_id, sync_kind=None)`,
`code_refs_for(repo_id, doc_id, sync_kind=None)`,
`add_sync_run(run)`, `latest_sync_run(repo_id, sync_kind=None)`.

Routes (app.py):
- `POST /repos/{repo_id}/sync` body `{mode: "git"|"local"}` (bearer-auth like
  other writes). Server resolves the repo `local_path`, reads `config/cdmon/`
  (git: `git show <main>:...`; local: working tree), merges to `MonitorConfig`,
  upserts `config_documents`/`config_code_refs`, computes drift + coverage,
  records a `sync_runs` row, returns the run summary `{fully_synced, mode,
  counts, commits_ahead, drift}`.
- `GET /repos/{repo_id}/documents?sync_kind=` → documents + nested code_refs (the
  relationship view).
- `GET /repos/{repo_id}/sync-state?sync_kind=` → latest `sync_runs` row.

`RepoIdentity`/`RegistrationPayload` gain optional `local_path` + `default_branch`
(additive, K6).

**Two sync types:**
- **Git sync (global / main):** `mode=git`. Reads config at the repo's default
  branch (`main`). The central system's guaranteed baseline. `fully_synced` =
  DB rows == config at main AND zero drift at main.
- **Local sync:** `mode=local`. Reads the working tree (feature branch). Reports
  `commits_ahead` (`git rev-list --count main..HEAD`) and the drift the branch
  introduces — so a user gets "code PR now, docs PR next".

CLI (client-side, no central access required):
- `cdmon sync [--mode git|local] [--remote URL --repo-id ID]` — parse local
  `config/cdmon/`, and either POST to a central `--remote` or, with no remote,
  print the sync summary locally.
- `cdmon index` — regenerate `config/cdmon/index.yaml` units list.
- `cdmon rpt [--write]` — compute + print/write `config/cdmon/coverage.rpt`.

---

## 5. Front-end (epic W) + per-repo standalone (epic L)

Central dashboard new pages (React, match existing conventions):
- **Documents page** (`/repos/:id/documents`): the full document list (id,
  audience, region_keys, unit); expand a doc to see its `code_refs` (the
  relationship view). Data from `GET /repos/{id}/documents`.
- **Config page** (`/repos/:id/config` or a global `/config`): indexes cdmon's
  own source config and shows the full unit `.yaml` template (the canonical
  format from §1.1) so adopters can copy it.
- **Sync button**: in the repo header — two actions "Sync (main)" and
  "Sync (local)" → `POST /repos/{id}/sync`; shows fully-synced state +
  commits-ahead + drift count from the returned run.

**Per-repo standalone view (epic L):** `cdmon serve [--port 0] [--repo-id ID]`
launches the SAME FastAPI app + dashboard backed by an InMemoryStore
auto-registered with ONLY the local repo (its `local_path` = cwd). The user gets
the identical Documents page, relationship graph, and Sync button — scoped to
their one repo, no central access. Ships in `demo/` and is e2e-tested.

---

## 6. Demo (epic M)

`demo/` is a self-contained adopter repo (its own git history is the OUTER repo's
history; the demo lives in a subdir with its own `config/cdmon/`). It contains:
- real source (a small multi-module Python app) + docs,
- a full `config/cdmon/` (index, ignore, doc-style, 2–3 units, generated
  coverage.rpt),
- writing templates reference (uses the repo-level `templates/writing/`),
- a README showing: `cdmon check`, `cdmon rpt --write`, `cdmon serve` (standalone
  view), and registration into the central demo (`scripts/seed_demo.py`).
`seed_demo.py` registers the demo repo with its `local_path` so the central
dashboard's Sync button works against it live on :33333.

---

## 7. Cleanup (epic Z) — DONE

The dir layout dogfoods cdmon's own repo (Z-01b) and Z-02 completed the cleanup:
the root `cdmon.yaml` was REMOVED; `config/cdmon/` (units mirroring the 12
documents) is cdmon's only self-config. `cdmon check`/`coverage`/`rpt`
auto-detect it from the repo root, CI uses `--config config/cdmon`, and the
single-file `load_config` path is retained ONLY as the documented back-compat
capability (`cdmon init`, `examples/`, tested against a separate fixture — not
cdmon's own config). No behavior the test suite asserts regressed.
