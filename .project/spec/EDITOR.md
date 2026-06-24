# Interactive Config Editor (EDITOR) — master spec

Source of truth for the EDITOR feature: an in-browser, per-repo page that shows
the full document↔code mapping (the `config/cdmon/*.yaml` rendered live), lets a
user edit that mapping by "filing a ticket", runs document generation that writes
the change back to disk + reindexes + heals + re-syncs ("makes it live"), adds a
one-click "apply the LLM's proposed fix" on drift tickets, and introduces a new
`context_refs` unit-file key for sub-documents / sub-source-files used as
generation context. Slices are `E-NN`; each is a TDD vertical slice.

## 0. Locked decisions (every slice respects these)

- **Disk is the source of truth; SQL is the live mirror.** A web edit is staged
  as a row in a new `config_edits` table (the "ticket"), then a "Generate / make
  live" action APPLIES staged edits to the on-disk `config/cdmon/*.yaml` +
  scaffolds/heals the affected docs + `regenerate_index` + re-runs
  `run_sync(local, mode="local")`, which reprojects `config_documents` /
  `config_code_refs` / `sync_runs` into SQL. After generation the dashboard reads
  the freshly-synced SQL rows → the state is "live". This is why SQL is needed:
  it is the queryable mirror the dashboard reads; disk stays the git-tracked truth.
- **The editor is an explicit WRITE surface (K1 relaxation, scoped).** Unlike
  `check`/`sync` (read-only), the generate action mutates the working tree — but
  ONLY: `config/cdmon/*.yaml` (the unit files + index) and the document `.md`
  files declared in the config. Never arbitrary paths. Every generation appends a
  `sync_run` (audit) and marks the `config_edits` rows applied. Writes require the
  per-repo bearer token; OPEN/standalone repos write token-less (L-01 parity).
- **`context_refs` is additive (K6) and NOT coverage.** It is generation context
  ("glance-through" references), never counted in coverage/`.rpt`, never a
  documented-surface gap. Distinct from `code_refs` (the documented surface).
- **All offline + deterministic (K10).** Mock backend by default; injected `now`;
  no network; generation/heal/serialize idempotent (K7). Loud typed errors (K8).
- **Store parity.** Every new store method works identically over InMemoryStore
  AND SqlStore; new SQL tables/columns are additive (JSON-blob + indexed scalars).
- **Reuse, don't reinvent.** Compose existing helpers: `scaffold_doc` (layout),
  `build_document_surface` (extract), `regenerate_regions`/`apply_fix` (heal),
  `regenerate_index`/`write_index` (config), `run_sync` (configsync),
  `read_style_guidance`/`style_for` (docstyle). The only NEW config primitive is a
  unit-file YAML serializer (see §2).

## 1. The `context_refs` unit-file key (§schema)

A document entry in a unit `.yaml` MAY carry `context_refs:` — a list of
sub-documents / sub-source-files the author should glance through or refer to
when generating this document, but which are NOT its documented surface.

```yaml
documents:
  - id: getting-started
    path: docs/guide/getting-started.md
    audience: user-guide
    code_refs:
      - path: src/taskflow/core/model.py
        symbols: [Task]
    context_refs:                      # NEW (additive, K6)
      - path: docs/api/core-api.md      # a sibling DOC to refer to
        note: "link to the full engine reference"
      - path: src/taskflow/core/engine.py   # a source file to glance through
        note: "scheduling semantics referenced in the tour"
```

- Model: `ContextRef(path: str, note: str | None = None)` (frozen, extra=forbid).
  Add `context_refs: tuple[ContextRef, ...] = ()` to `DocumentSpec` AND to the
  v2 `UnitDocument` parse path. Flows through `MonitorConfig` projection unchanged.
- Loud K8 validation: each `context_refs.path` must be a string; duplicates within
  one document are an error. Paths are repo-root-relative (not resolved for
  existence at load — a context ref MAY point at a not-yet-created doc).
- It feeds GENERATION: `context_refs` are surfaced to the backend prompt as
  reference material (see §3). It does NOT enter `code_refs`, coverage, or drift.
- Surfaced in the API `documents` tree (a `context_refs` array on each document)
  and shown in the UI under the document (separate from code_refs).

## 2. NEW config primitive — unit-file serializer (E-01)

`config.py` (or `templates_v2.py`): `dump_unit_file(unit: UnitFile, *, now: str) -> str`
returns the full `---`-fenced frontmatter + body YAML for a unit, such that
`load_unit_file(write(dump_unit_file(u)))` round-trips to an equal model.
Deterministic key order; idempotent. Plus pure editors operating on the MODEL:

- `upsert_document(unit: UnitFile, doc: <doc-entry>) -> UnitFile` — add or replace
  a document entry (by id) including its `code_refs`, `context_refs`, audience,
  region_keys.
- `add_code_ref(unit, doc_id, ref) -> UnitFile`, `remove_code_ref(...)`.
- `set_context_refs(unit, doc_id, refs) -> UnitFile`.

These return new frozen models (no mutation). The server writes
`dump_unit_file(...)` to `config_dir / f"{unit}.yaml"` then `regenerate_index`.

## 3. Generation consumes `context_refs` (E-02)

When building a `FixRequest`/agent context for AUTHORING (scaffold or an `llm`
region), include the document's `context_refs` as a reference block in the prompt
(`backends.build_prompt` / `agent/graph.render_context`): list each
`context_refs.path` (+ note), and for source-file context refs, include a short
glance (e.g., the public symbol names) so the author can refer to them. The mock
backend stays deterministic (it may ignore the block; tests assert the block is
PRESENT in the built prompt, and that scaffolding still succeeds).

## 4. SQL: pending edits (E-03)

New table `config_edits` (additive): `id` (K10 order), `repo_id` (indexed),
`edit_id` (indexed), `status` (`pending`|`applied`|`discarded`, indexed),
`created_at`, `applied_at`, `edit` (JSON blob = the typed edit). Store methods
(InMemory + Sql parity): `add_config_edit`, `config_edits_for(repo_id, status=None)`,
`mark_config_edits(repo_id, edit_ids, status, *, at)`. The edit JSON is a tagged
union (`action`): `create_doc`, `add_code_ref`, `remove_code_ref`,
`set_context_refs`, `set_doc_style`, each carrying the unit + doc + payload.

## 5. Routes (E-04..E-07)

| Method | Path | Auth | Body | Purpose |
|---|---|---|---|---|
| GET | `/repos/{id}/config/editable?sync_kind=` | open | — | The editable tree: documents (with code_refs + context_refs), `undocumented_files` (in-scope, unlinked), `ignored_files`, `unit_files`, `doc_styles` (selectable category options). |
| POST | `/repos/{id}/config/edits` | token | `ConfigEdit` (tagged union) | Stage one mapping ticket → a `pending` row. Returns `{edit_id}`. |
| GET | `/repos/{id}/config/edits?status=` | open | — | List staged edits. |
| POST | `/repos/{id}/config/generate` | token | `{edit_ids?: [], now?, mode?}` | Apply pending edits to disk (write unit yaml + index), scaffold/heal docs, re-run local sync, mark edits applied. Returns `{applied: [...], sync_run, undocumented_files}`. |
| POST | `/repos/{id}/records/{record_id}/apply-fix` | token | `{}` | Apply the record's `ProposedFix` to the doc on disk (`apply_fix`), record an `accepted` resolution, re-sync. Returns `{applied: bool, doc_path, diff}`. |

- The editable tree's `undocumented_files` = the coverage `undocumented` list
  (in-scope `.py`/format files not in any `code_refs`); `ignored_files` from the
  ignore.yaml/gitignore globs. Reuse `effective_coverage` + the report machinery.
- `generate` and `apply-fix` operate on `store.get_repo(id).repo.local_path`;
  loud 409/400 if the repo has no `local_path` (a central-only repo can't be
  generated server-side). Deterministic via injected `clock`.

## 6. Frontend — the Mapping page + apply-fix (E-08..E-11)

- New route `/repos/:repoId/mapping` (add to nav). Shows, scoped to the repo:
  - **Documents**: each document a collapsible row; expanded reveals its
    `code_refs` (path + symbols/lines or "whole file") AND its `context_refs`
    (path + note, visually distinct). A per-document "Edit mapping" action.
  - **Unlinked source files**: the `undocumented_files` as a flat list, each with
    a "Link to a document…" action that opens the mapping-ticket form.
  - **Ignored files**: a collapsed (closed-by-default) `<details>` tab at the
    bottom listing `ignored_files`.
  - **Mapping-ticket form** (modal/inline): fields — target document (existing id
    or new: id + path + audience), source file, scope (`all` | line range
    `start-end` | specific symbols), doc-style selection (the 4 category dropdowns
    from `doc_styles`), and context_refs (add path + note). Submits a
    `POST /config/edits`. Staged edits show as a pending list.
  - **"Generate / make live"** button → `POST /config/generate`; on success
    re-fetch the tree + sync-state so the page reflects the live state.
- **Apply-fix button**: on the drift timeline / ticket card (`RepoDetail`), a
  record with a FIX verdict + a `fix` gains an "Apply fix (LLM)" button →
  `POST /records/{id}/apply-fix`; on success show applied + refresh records.
- Reuse the injected-`api?`-prop test pattern; Vitest for every component.

## 7. Demo (E-12)

- Add `context_refs` to a demo document (e.g. `getting-started` refers to
  `docs/api/core-api.md` + glances `engine.py`). Keep `scheduler.py` UNLINKED so
  the Mapping page shows it under "unlinked" and a reader can link it via the
  ticket form + Generate to watch it become documented live. Wire an apply-fix
  path into `walkthrough.py`/seed so the demo shows the button's effect.
- Update `seed_demo.py`, demo `core.yaml`/`doc-style.yaml`, demo README, the demo
  e2e tests, and the dogfood config (cdmon's own) to exercise `context_refs`.

## 8. Cleanup + invariants (E-13)

- Update `.project/spec/CONFIGV2.md` cross-ref, `ARCHITECTURE.md`, READMEs.
- Reheal dogfood docs after any tracked-source edit (`cdx monitor --apply`).
- Final gates: full pytest `-m "not live_llm and not pg"` green; ruff + mypy
  (`custodex`) clean; dashboard vitest + build green; `cdx check`/`lint`/
  `index --check`/`rpt`(idempotent)/`coverage --fail-under` over `config/cdmon` and
  `demo/config/cdmon` all pass; the new editable/generate/apply-fix flows covered
  by e2e tests over a temp repo (write → generate → live) on BOTH stores.

## Phases & slices (sequential subagent dispatch; validation between phases)

- **Phase A — schema + write primitives:** E-01 (context_refs schema + unit
  serializer + model editors), E-02 (context_refs into generation prompt).
- **Phase B — server:** E-03 (config_edits table + store parity + editable-tree
  computation), E-04 (GET editable tree route), E-05 (POST edits + GET edits),
  E-06 (POST generate — the integration slice), E-07 (POST apply-fix).
- **Phase C — frontend:** E-08 (api client + types), E-09 (Mapping page: docs +
  unlinked + ignored tabs + context_refs), E-10 (mapping-ticket form + Generate),
  E-11 (apply-fix button).
- **Phase D — demo + cleanup:** E-12 (demo + seed + dogfood context_refs), E-13
  (docs, reheal, final validation).

Each slice: write/adjust tests first, implement, run the relevant gate, leave the
suite green. A validation agent runs at each phase boundary (e2e over real
on-disk artifacts, not just unit tests).
