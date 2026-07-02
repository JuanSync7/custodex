---
cdm:
  audience: user-guide
  fingerprint: a127fbf2054d5d16
  fingerprint_tiers:
    composite: a127fbf2054d5d16
    signature: a127fbf2054d5d16
  schema_version: 1.0.0
  symbol_sigs:
    01b8016fdce455c4: 2557e4d98b703179
    0c9d51b72e16a207: 468c2620ca834755
    0d6e4079e36703eb: 14346d3eb68974a0
    12a435ec8454c6d1: a2ca2be3282d0600
    1a4e31eebbd1771e: 7bd3f0f4e54746a8
    1bc04b5291c26a46: 76a6557de9f6049e
    1d3c8aff2168435b: 7f757c94419dec88
    20f65c28671b4093: 195057ec33efc577
    24c458cfb46d9a45: 953d02f5d1ac5781
    2cc497857559ff85: 6724a3e462f7b17d
    44575cf5b28512d7: deba6b00c018c6ab
    602fda589448378a: 8afb4765b2d48e0c
    72f4be89d6ebab14: 82cdb795b1cfefb7
    75c75efe327a8ef3: 41b3443a5133331f
    763cdc62a869262b: 3209114b9963834b
    7de97367c9cdc3c6: 44bb81b499473b41
    845e91831319e89c: 9b02c4079bd0db59
    87780fa5de684e87: 1f59070663e4290f
    9185806e77b1178b: 8446552e330a2629
    a172cedcae47474b: c411ee4fd4d39f0a
    a1c1adc663fbd6f0: 0064962060915ac9
    bb54068aea85faa7: defb9df3f00a5f13
    c3a3091b9d32267d: f236e1b17349fc02
    cde0fb0dec1400c5: 6602cc7d080e1dca
    d3a3ed1c7e737699: aa2501b9d4a86c13
    da966368ea663ea5: f39ba256826afdf5
    df0ad6e43880f09c: 3019fb39391d3113
    eafe895eb8119e6e: 2492d10714d01761
    eb2554c8c13b73f9: 34e432f7557b73ab
    edcc4b4214b84e54: 1fc512bec079aec4
    f93464a48a2b9281: df997f7601a0a995
    fdf09cdfc26cccf6: 09c649f44a9a9980
    fe494651a43235a5: 783cc1ef26d8217f
---
# Custodex

> **Custodex** — keeps your code and docs in sync, owned, and accountable.
> It catches drift across **code↔doc *and* doc↔doc**, pegs an **owner** to every
> doc, tracks **review SLAs**, and — when something drifts — **fixes, invalidates,
> or escalates** it, recording every verdict for human review. This README is
> itself monitored by `cdx` against the CLI surface it documents.

**Live demo & docs:** [custodex.juansync.dev](https://custodex.juansync.dev) — a
clickable demo of the console (on sample data), the feature wiki, and a
getting-started tutorial. No install required.

A **standardized, reusable** system that keeps documentation in sync with the
code (and other docs) it describes — and, when it drifts, asks an LLM to **fix or
invalidate** the drift while logging every decision for human review. Custodex is
the *custodian* of your documentation: it keeps the record straight, and keeps
someone answerable for it.

It generalizes the `docsync` pattern (extract a code surface → fingerprint it →
detect drift against the docs) into a project-agnostic tool, and closes the loop
with automatic, auditable remediation.

```
config ──> extract ──> drift ──┬─> clean → exit 0
                               └─> LLM backend → FIX | INVALIDATE | ESCALATE
                                        │
                                        ├─ apply fix to the doc (opt-in, idempotent)
                                        ├─ append a ReviewRecord to the JSONL review log
                                        └─ emit the record to a central monitoring system
```

## Why

A detector that only **warns** still needs a human to act; a fixer that acts
**silently** can't be trusted. Custodex detects, auto-remediates with an
LLM, and records the **original drift + the proposed fix** so a person (or a
central dashboard) can audit what changed and why — a self-healing monitor that
still keeps a human in the review seat.

## How a project adopts it

Write a config that maps groups of code files — down to functions, line ranges,
or variables — onto **logical documents**, each tagged with an **audience**. The
canonical form is the `config/cdmon/` directory layout (an `index.yaml` plus
per-area unit files; `cdx` auto-detects it with no `--config`); a single
`cdmon.yaml`/`.json` file is also supported as a back-compat path. Each document
carries an audience:

- `user-guide` — only the externally-visible surface matters; comment / local /
  private changes are *invalidated* (not drift).
- `eng-guide` — the implementation surface matters too; those changes *are*
  flagged.

```bash
# --- set up ---
cdx init                 # write a single-file config template (offline)
cdx init --v2            # ...scaffold the multi-file config/cdmon/ layout instead
cdx init --central URL --repo-id ID   # ...wired for HTTP reporting to a central server (sink=http + url + repo_id + auth_env + outbox); --token-env VAR (default CDMON_CENTRAL_TOKEN), --repo-url URL; ready to `cdx register` + report (G-01)
cdx index [--check]      # regenerate config/cdmon/index.yaml's units: from the on-disk unit files; --check is a read-only CI gate (exit 1 on an out-of-sync index)
cdx doctor               # offline, read-only preflight: PASS/WARN/FAIL on config, documents, backend prereq, central wiring, optional extras; exit 0 unless a structural FAIL (absent runtime prereq/unset token = WARN, never FAIL; no network) (G-02)

# --- author / inspect docs ---
cdx new-doc <doc-id>     # scaffold a conformant, in-sync doc from config + code
cdx surface              # dump the extracted per-document surface (debug)
cdx build                # render every `html: true` doc to its derived `.html` twin (keeps the Layout Standard's HTML pairing fresh)
cdx lint [--fix]         # validate doc *structure* (Layout Standard); --fix stamps front matter

# --- detect & heal ---
cdx check                # detect *content* drift; non-zero exit on drift (the warning)
cdx monitor --apply      # detect → LLM verdict → record → apply fix → re-check

# --- doc↔doc dependencies (EPIC B) ---
cdx deps                 # show the doc→doc dependency graph + suspect status (a doc `depends_on` another; when the upstream changes the downstream is flagged SUSPECT until re-confirmed) — read-only
cdx deps --suggest       # infer edges from Markdown cross-links between managed docs → paste-ready `depends_on` config (author→approve, not author-by-hand)
cdx deps --impact DOC    # the proactive blast radius: which documents (transitively) depend on DOC and would need re-review if you change it (read-only; an empty radius reads "safe to change")
cdx resolve --edge DOWN UP  # re-confirm exactly one doc↔doc edge after reviewing the upstream change (re-stamps just that edge's baseline; `docdeps.gate` decides whether a suspect link fails `cdx check`)
cdx entities [DOC] [--unresolved]  # the AGT-01 mention layer: every backticked symbol/path/env-var span + markdown link in a doc's PROSE, linked deterministically against the code surface + repo tree; --unresolved shows the graph-rot signal (a mention whose referent is gone); read-only, no LLM
cdx monitor --ref SHA    # ...and stamp each record's source_sha provenance (else $CI_COMMIT_SHA; C-05)
cdx sync-pr [--dry-run]  # heal docs + emit a unified-diff patch of the changed docs (the docs-PR content); --dry-run computes the same patch without touching the tree; --out FILE writes it
cdx open-docs-pr [--dry-run]  # heal docs then open a docs MR (branch+commit+MR) via the default GitLab transport (stdlib urllib; from CI env); clean repo is a no-op; --dry-run prints the MR plan as JSON from a dry sync (no mutation, no network); --target/--ref set the target branch + provenance ref
cdx should-sync [FILES...]  # loop-safety guard: exit 0 to proceed / 1 to skip a heal; skips when every changed file is a managed doc (a bot doc-only commit). `git diff --name-only | cdx should-sync` (C-04)

# --- review log & learning ---
cdx report               # summarize the review log + resolved/unresolved counts (--verdict ESCALATE lists those records)
cdx resolve REC --resolution accepted [--by NAME] [--text ...] [--note ...]  # record a human outcome (accepted|overridden|rejected|invalidated) as a separate append-only event linked to a review record; the review log stays immutable (K5)
cdx promotions           # list promotion candidates: shapes (doc_id,drift_kind,audience) whose ≥N resolved records ALL share one DECISION (invalidated|rejected) — promotable to a deterministic rule the monitor applies with ZERO backend calls (--min-count N; --json) (D-05/D-06)

# --- coverage ---
cdx coverage             # doc-coverage % + gaps/waivers (--json; --fail-under N gates)
cdx coverage --write     # write a deterministic manifest (payload + gap→owner suggestions) to .cdmon/coverage.json (idempotent; --write PATH for a custom path)
cdx rpt [--write]        # build the config/cdmon dir-layout coverage report; print it, or --write it to config/cdmon/coverage.rpt
cdx surface-gaps [--dry-run] [--provider gitlab|github]  # turn undocumented-public-symbol coverage gaps into a tracker issue (grouped by suggested owner); no gaps is a no-op; --dry-run prints the deterministic IssuePlan JSON without building/calling a transport; else opens the issue via the provider's stdlib-urllib transport (from CI env; loud if unset) (H-04)

# --- central server ---
cdx register [--dry-run] # announce this repo to the central server: POST its identity (RegistrationPayload) to <central url>/repos (bearer from central.auth_env; stdlib only); --dry-run prints the payload without any network call (E-02)
cdx sync [--mode local|git] [--remote URL --repo-id ID]  # run a config sync. LOCAL (no --remote): read-only against the cwd, prints drift+coverage+commits-ahead (or --json). REMOTE: POST {mode} to <URL>/repos/{ID}/sync (bearer from --token-env) and print the server's run summary
cdx serve [--host H --port P]  # serve THIS repo's standalone console + API locally over the built Astro frontend — no central access (L-01); needs a config/cdmon/ layout (run `cdx init --v2` first)

# --- feature catalog & traceability (EPIC R) ---
cdx wiki [--check]       # regenerate the golden feature-doc/FEATURES.md + feature-doc/wiki/* from their single sources; --check is the CI freshness gate (fails if any wiki is stale)
cdx trace [--fail-on-gap]  # traceability gate: prove every catalog feature has ≥1 demo AND ≥1 test via inline `Feature:` tags scanned from tests/ and demo/ (--fail-on-gap exits 1 on a gap)

# --- public contract ---
cdx schema               # emit the public ReviewRecord JSON schema
```

### Drop-in CI + a worked example (EPIC G)

- **`templates/ci/`** — copy-paste CI for adopters: `gitlab-ci.adopter.yml`
  (GitLab) and `github-actions.adopter.yml` (GitHub Actions), each with a
  `cdmon-gate` job (`doctor` → `check` → `lint`, offline) and a default-branch
  `cdmon-docs-pr` job (`should-sync` guard → `monitor --apply` → `open-docs-pr`).
  See `templates/ci/README.md`; set `CDMON_CENTRAL_TOKEN` as a CI secret (E-06). A
  repo test keeps the templates honest — they reference only real `cdx`
  subcommands.
- **`examples/external-repo/`** — a small self-contained repo that ADOPTS cdx
  (its own `src/widget.py` + `docs/api.md` + `cdmon.yaml`). Its test heals it and
  reports the healed records to an in-process central server (`TestClient`) with a
  bearer token, proving the whole client→server loop offline (the capstone, G-04).
  (See also `examples/multilang/` for cross-language extraction.)

## Document Layout Standard

Beyond keeping content in sync, custodex standardizes **how a managed
doc is written** so every adopting project lays its docs out the same way: a
canonical skeleton (front matter → `#` title → `>` purpose → prose →
`CDM:BEGIN/END` regions), a managed front-matter schema
(`cdm.schema_version` / `audience` / `fingerprint`), and an HTML-twin pairing
rule (`X.md` → `X.html`, derived-not-edited, carrying an embedded source hash).
helium's `HELIUM:AUTOGEN … START/END` markers are a documented alias of the same
grammar. The standard is **machine-checked** — `cdx lint` is a structure gate
orthogonal to `check`'s content gate (run both in CI), `cdx new-doc` scaffolds
a conformant file, and `cdx build` (re)renders the `.html` twins. See
[`docs/LAYOUT_STANDARD.md`](docs/LAYOUT_STANDARD.md).

## Backends (pluggable, offline by default)

The LLM backend is chosen entirely by config:

- `mock` — deterministic, offline; the default, and what the test suite uses.
- `claude-code` — runs a headless `claude -p` session as a subprocess.
- `api` — calls the Anthropic Messages API.
- `agent` — a deterministic **LangGraph** remediation workflow (see below).

Switching between them is a config edit, never a code change. The engine is
backend-agnostic: all four return the same `BackendResult` JSON contract.

## The LangGraph remediation agent

`backend.kind: agent` runs remediation as a deterministic LangGraph
`StateGraph` (`select → compose → invoke → parse`, with a bounded re-ask loop)
instead of a single monolithic prompt. Its prompt is **composed from separated
Markdown artifacts**, loaded *only when a node needs them*:

- [`AGENT.md`](custodex/agent/prompts/AGENT.md) — the recipe + audience-aware judgement rules,
- [`PROTOCOL.md`](custodex/agent/prompts/PROTOCOL.md) — the strict JSON verdict contract,
- [`TOOL.md`](custodex/agent/prompts/TOOL.md) — the two fix shapes (loaded only for a healable drift),
- [`PERSONA.md`](custodex/agent/prompts/PERSONA.md) — voice (loaded only when `use_persona`),
- [`EXEMPLARS.md`](custodex/agent/prompts/EXEMPLARS.md) — few-shot exemplars from past resolved drift (loaded only when similar records are retrieved; D-04).

The agent's **runtime** is a second config-only choice — *the one knob the brief
asked for*: the agent uses the headless Claude Code CLI by default, and can be
pointed at an Anthropic API key or a local model endpoint with no code change:

```yaml
backend:
  kind: agent
agent:
  driver: claude-code            # headless `claude -p` (default)
  # driver: api                  # Anthropic API; key from $api_key_env
  # driver: local                # any OpenAI-compatible endpoint
  #   base_url: http://localhost:11434/v1
  model: claude-sonnet-4
  use_persona: true
  max_parse_retries: 1
```

The graph is fully deterministic (K10); only the injected runtime *driver*
touches a process or socket, so the whole workflow runs offline in tests (K4).
The agent ships behind an opt-in extra: `pip install -e '.[agent]'` (or `[dev]`).

## Central server (optional `[server]` extra)

The central side of the sink/registry is a FastAPI app in
`custodex.server` that ingests repo registrations + review records over
the **same** versioned schemas the client sends — no DTOs. It ships behind an
opt-in extra (`pip install -e '.[server]'`) and is imported lazily, so the core
engine pulls in no `fastapi`. `create_app()` registers ~two dozen routes; the
main groups:

| group | routes |
|---|---|
| liveness / reference | `GET /` (the console when a frontend build is mounted, else a JSON landing), `GET /health`, `GET /config/templates`, `GET /wiki` |
| registry + ingest | `POST /repos` (`RegistrationPayload` → `201 {repo_id}`), `POST /ingest` (`IngestEnvelope` → `202 {record_id}`; unknown repo → 404), `GET /repos`, `GET /repos/{id}/records` |
| review outcomes + coverage | `POST`/`GET /repos/{id}/resolutions`, `GET`/`POST /repos/{id}/coverage` |
| computed views | `GET /repos/{id}/status`, `GET /repos/{id}/health` (`RepoHealth`), `GET /repos/{id}/telemetry` (per-`(drift_kind, audience)` underperformer view + promotion candidates, H-01), `GET /repos/{id}/documents`, `GET /repos/{id}/sync-state` |
| server-side git | `POST /repos/{id}/sync` (clone-on-demand sync), `POST /repos/{id}/docs-pr` (heal + open a docs PR upstream) |
| in-browser editing | `GET /repos/{id}/config/editable`, `GET`/`POST /repos/{id}/config/edits`, `POST /repos/{id}/config/generate`, `POST /repos/{id}/records/{record_id}/apply-fix` |

Reads are open; writes are protected by a per-repo bearer token (E-06). A
malformed body is a `422` (pydantic against the shared model). Run it with
`cdx-server` or `uvicorn custodex.server.app:create_app --factory`.

**Storage** is selected from the environment by `store_from_env()`: with
`$CDMON_DATABASE_URL` set, the schema is migrated to head (Alembic) and a
persistent `SqlStore` (SQLAlchemy 2.0, Postgres-first; a stdlib-SQLite stand-in
offline) is used so records / resolutions / coverage survive a restart; unset, it
loud-warns and falls back to a transient `InMemoryStore`. Both sit behind the same
`Store` Protocol. When the Astro frontend is built (`frontend/dist`), the same
FastAPI process serves the React console at `/` and the native wikis at `/wiki/*`
from one `StaticFiles(html=True)` mount placed after the API routes — a
single-origin deploy.

### Server-side git sync (EPIC GIT)

The server can clone, sync, and open a docs PR for a repo it does **not** hold
locally. A per-repo provider credential is sealed at rest with AES-256-GCM
(`secrets.py`; the `[server]` extra pulls in `cryptography`, and the engine core
never imports it). On demand the server clones the repo read-only
(`gitfetch.py`, via an ephemeral `GIT_ASKPASS` helper so the token never reaches
argv/URL) for `POST /repos/{id}/sync`, or heals and opens a docs PR upstream
through `GitHubTransport` / `GitLabTransport` (`pr.py`'s `from_repo`) for
`POST /repos/{id}/docs-pr` — minting a short-lived GitHub App / GitLab OAuth token
when configured (`gitauth.py`), so the hot token is never stored. Clone / PR hosts
are constrained by an SSRF allowlist (`$CDMON_ALLOWED_GIT_HOSTS`, plus
github.com / gitlab.com).

## Interactive editing — the console's Mapping view

The frontend is one **Astro app** under `frontend/` (`output: static`): the
interactive console is a client-only React island mounted at `/`, and the native
wikis render at `/wiki/*`. The console's per-repo **Mapping view** (client route
`/repos/:repoId/mapping`) shows and edits the repo's `config/cdmon/*.yaml`
document↔code mapping from the browser:

- **View the config live.** Each document is a dropdown listing its `code_refs`
  (the documented surface — path + symbols/lines or "whole file") and its
  `context_refs` (generation-context references, shown distinctly). In-scope but
  **unlinked** source files appear as a flat list; **ignored** files sit in a
  closed `<details>` tab at the bottom.
- **File a mapping "ticket".** "Link to a document…" / "Edit mapping" opens a form
  — target document (existing or new id + path + audience), source file, scope
  (whole file / a `start-end` line range / specific symbols), the four doc-style
  category selections, and `context_refs`. Submitting stages a `config_edit`
  (nothing is written to disk yet); staged edits show as a pending list.
- **Generate / make live.** One button applies the staged edits to the on-disk
  units + index, scaffolds/heals the affected docs, and re-runs the sync so the
  page reflects the now-live state. Disk stays the git-tracked source of truth;
  the SQL store is the live mirror the console reads.
- **One-click apply-fix.** On a drift ticket with a `FIX` verdict, an
  **"Apply fix (LLM)"** button applies the record's proposed fix to the doc on
  disk, records the acceptance, re-syncs, and shows the diff.

**`context_refs`** is a unit-file key for sub-documents / sub-source-files the
author should glance through when generating a doc. It is **generation context
only** — surfaced to the authoring prompt, never counted in coverage or drift,
distinct from `code_refs`.

Try it on the demo: `demo/` ships with `scheduler.py` intentionally **unlinked**
— open the console's Mapping view, link it to a document via the ticket form, hit
**Generate**, and watch it become documented live. `demo/walkthrough.py` drives
the apply-fix and link→generate flows end-to-end, offline.

## Feature catalog & traceability (EPIC R)

A golden **feature catalog** under `feature-doc/catalog/*.yaml` is the single
source of truth for every feature of custodex (19 subsystems; the exact
feature count is the header of `feature-doc/FEATURES.md`). From it,
`cdx wiki` regenerates four artifacts — never hand-edited:

- `feature-doc/FEATURES.md` — the rendered feature reference,
- `feature-doc/wiki/SOURCE_WIKI.md` — per-module public symbols + feature links,
- `feature-doc/wiki/TEST_WIKI.md` — every test case grouped by boundary,
- `feature-doc/wiki/TRACEABILITY.md` — the feature × demo × test matrix.

`cdx wiki --check` is the CI freshness gate (fails if any wiki is stale).
`cdx trace --fail-on-gap` proves every feature traces 1:1 to a demo **and** a
test by scanning inline `Feature: <id>` tags in `tests/` and `demo/` (currently
complete — every catalogued feature has both). Both run offline in CI (the
`docs:gate` job).

## Public schema

Every handled drift becomes a versioned `ReviewRecord` (the public contract for
the central monitoring system). The JSON Schema is generated from the model —
`cdx schema` — and a snapshot lives at
[`docs/REVIEW_RECORD_SCHEMA.json`](docs/REVIEW_RECORD_SCHEMA.json).

## Dogfooding

Custodex monitors **its own** source against its own engineering docs:
the shipped [`config/cdmon/`](config/cdmon) dir layout (an `index.yaml` plus the
per-area unit files) maps this package's modules onto the docs under `docs/api/`
(with `schema.py` as a shared, multiply-referenced file). Run `cdx check` here
(it auto-detects `config/cdmon/`) to see it in action; the dogfood is asserted in
`tests/system/test_dogfood.py`. Any edit to a tracked module drifts the matching
`docs/api/*` doc — reheal with `cdx monitor --apply` before the suite is green.

## Status

The core engine (CDM-00…CDM-11) and the EPIC-2 program have shipped: the central
FastAPI server with persistent Postgres-first storage, the per-repo in-browser
config editor (EDITOR), server-side git sync + docs-PRs (EPIC GIT), the golden
feature catalog + traceability wikis (EPIC R), and the single Astro frontend
(EPIC ASTRO). The suite is offline (mock backend, no network), ruff + mypy clean,
with branch coverage gated ≥ 90%. [`.project/STATUS.md`](.project/STATUS.md) is
the live slice-by-slice status board; see `.project/` for the spec, the binding
constraints (K0–K10), and the architecture.

## Development

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'  # [dev] includes both extras
.venv/bin/ruff format --check . && .venv/bin/ruff check .
.venv/bin/mypy custodex
.venv/bin/pytest -q --cov=custodex --cov-branch
```

The LangGraph agent backend is an opt-in extra; for a runtime-only install use
`pip install -e '.[agent]'` (the core engine and its `mock` default need neither).
The central FastAPI server is a second opt-in extra: `pip install -e '.[server]'`
(`[dev]` includes both extras so the gate exercises the server tests). Tests live
under `tests/{unit,integration,system,smoke,regression}/` (the EPIC-R boundary
taxonomy; markers are auto-applied by path).

### Continuous integration

[`.gitlab-ci.yml`](.gitlab-ci.yml) runs five jobs across a `test` + `live`
pipeline (plus GitLab's SAST + Secret-Detection templates):

- **`tests:offline`** — the default offline suite on every push/MR (mock backend,
  no network, no DB; coverage-gated).
- **`docs:gate`** — the offline doc gates: `cdx check` + `cdx lint` + the
  EPIC-R `cdx wiki --check` + `cdx trace --fail-on-gap`.
- **`docs:heal`** — the default-branch docs-PR loop (`should-sync` → `monitor
  --apply` → `open-docs-pr`).
- **`tests:pg`** — the DB store contract against a **real Postgres** (`-m pg`); the
  offline suite runs the same contract on stdlib SQLite, so nothing else touches a
  database (K4).
- **`tests:live-llm`** — the opt-in real-LLM test (`-m live_llm`) on a schedule /
  on demand, gated on an `ANTHROPIC_API_KEY` CI/CD variable.

### Testing against a real LLM (CI/CD)

The default suite is **offline** (K4): a bare `pytest` excludes the `live_llm` and
`pg` markers, so it never spawns a model or connects to a database. One opt-in
end-to-end test (`tests/system/test_live_llm.py`) drives a **real** backend —
resolved from a config file exactly like production — and asserts `monitor
--apply` self-heals a doc in a single pass:

```bash
# backend.kind comes from the config the test writes (CDMON_LIVE_BACKEND)
CDMON_LIVE_LLM=1 CDMON_LIVE_BACKEND=claude-code .venv/bin/pytest -m live_llm
```

This guards a real-vs-mock divergence the offline suite can't see: a live model
may return a fix that fills *both* the region and whole-doc shapes at once, so
`apply_fix` prefers the whole-doc text (the only shape that refreshes the
fingerprint) to keep `monitor --apply` single-pass idempotent.
