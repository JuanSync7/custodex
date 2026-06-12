---
cdm:
  audience: user-guide
  fingerprint: 7872066f25632b58
  fingerprint_tiers:
    composite: 7872066f25632b58
    signature: 7872066f25632b58
  schema_version: 1.0.0
---
# code-doc-monitor

> The standardized, self-healing code→documentation drift monitor: extract a code
> surface, detect drift against the managed docs, and **fix, invalidate, or
> escalate** it — recording every verdict for human review. This README is itself
> monitored by `cdmon` against the CLI surface it documents.

A **standardized, reusable** system that keeps documentation in sync with the
code it describes — and, when it drifts, asks an LLM to **fix or invalidate** the
drift while logging every decision for human review.

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
**silently** can't be trusted. code-doc-monitor detects, auto-remediates with an
LLM, and records the **original drift + the proposed fix** so a person (or a
central dashboard) can audit what changed and why — a self-healing monitor that
still keeps a human in the review seat.

## How a project adopts it

Write a config that maps groups of code files — down to functions, line ranges,
or variables — onto **logical documents**, each tagged with an **audience**. The
canonical form is the `config/cdmon/` directory layout (an `index.yaml` plus
per-area unit files; `cdmon` auto-detects it with no `--config`); a single
`cdmon.yaml`/`.json` file is also supported as a back-compat path. Each document
carries an audience:

- `user-guide` — only the externally-visible surface matters; comment / local /
  private changes are *invalidated* (not drift).
- `eng-guide` — the implementation surface matters too; those changes *are*
  flagged.

```bash
# --- set up ---
cdmon init                 # write a single-file config template (offline)
cdmon init --v2            # ...scaffold the multi-file config/cdmon/ layout instead
cdmon init --central URL --repo-id ID   # ...wired for HTTP reporting to a central server (sink=http + url + repo_id + auth_env + outbox); --token-env VAR (default CDMON_CENTRAL_TOKEN), --repo-url URL; ready to `cdmon register` + report (G-01)
cdmon index [--check]      # regenerate config/cdmon/index.yaml's units: from the on-disk unit files; --check is a read-only CI gate (exit 1 on an out-of-sync index)
cdmon doctor               # offline, read-only preflight: PASS/WARN/FAIL on config, documents, backend prereq, central wiring, optional extras; exit 0 unless a structural FAIL (absent runtime prereq/unset token = WARN, never FAIL; no network) (G-02)

# --- author / inspect docs ---
cdmon new-doc <doc-id>     # scaffold a conformant, in-sync doc from config + code
cdmon surface              # dump the extracted per-document surface (debug)
cdmon build                # render every `html: true` doc to its derived `.html` twin (keeps the Layout Standard's HTML pairing fresh)
cdmon lint [--fix]         # validate doc *structure* (Layout Standard); --fix stamps front matter

# --- detect & heal ---
cdmon check                # detect *content* drift; non-zero exit on drift (the warning)
cdmon monitor --apply      # detect → LLM verdict → record → apply fix → re-check
cdmon monitor --ref SHA    # ...and stamp each record's source_sha provenance (else $CI_COMMIT_SHA; C-05)
cdmon sync-pr [--dry-run]  # heal docs + emit a unified-diff patch of the changed docs (the docs-PR content); --dry-run computes the same patch without touching the tree; --out FILE writes it
cdmon open-docs-pr [--dry-run]  # heal docs then open a docs MR (branch+commit+MR) via the default GitLab transport (stdlib urllib; from CI env); clean repo is a no-op; --dry-run prints the MR plan as JSON from a dry sync (no mutation, no network); --target/--ref set the target branch + provenance ref
cdmon should-sync [FILES...]  # loop-safety guard: exit 0 to proceed / 1 to skip a heal; skips when every changed file is a managed doc (a bot doc-only commit). `git diff --name-only | cdmon should-sync` (C-04)

# --- review log & learning ---
cdmon report               # summarize the review log + resolved/unresolved counts (--verdict ESCALATE lists those records)
cdmon resolve REC --resolution accepted [--by NAME] [--text ...] [--note ...]  # record a human outcome (accepted|overridden|rejected|invalidated) as a separate append-only event linked to a review record; the review log stays immutable (K5)
cdmon promotions           # list promotion candidates: shapes (doc_id,drift_kind,audience) whose ≥N resolved records ALL share one DECISION (invalidated|rejected) — promotable to a deterministic rule the monitor applies with ZERO backend calls (--min-count N; --json) (D-05/D-06)

# --- coverage ---
cdmon coverage             # doc-coverage % + gaps/waivers (--json; --fail-under N gates)
cdmon coverage --write     # write a deterministic manifest (payload + gap→owner suggestions) to .cdmon/coverage.json (idempotent; --write PATH for a custom path)
cdmon rpt [--write]        # build the config/cdmon dir-layout coverage report; print it, or --write it to config/cdmon/coverage.rpt
cdmon surface-gaps [--dry-run] [--provider gitlab|github]  # turn undocumented-public-symbol coverage gaps into a tracker issue (grouped by suggested owner); no gaps is a no-op; --dry-run prints the deterministic IssuePlan JSON without building/calling a transport; else opens the issue via the provider's stdlib-urllib transport (from CI env; loud if unset) (H-04)

# --- central server ---
cdmon register [--dry-run] # announce this repo to the central server: POST its identity (RegistrationPayload) to <central url>/repos (bearer from central.auth_env; stdlib only); --dry-run prints the payload without any network call (E-02)
cdmon sync [--mode local|git] [--remote URL --repo-id ID]  # run a config sync. LOCAL (no --remote): read-only against the cwd, prints drift+coverage+commits-ahead (or --json). REMOTE: POST {mode} to <URL>/repos/{ID}/sync (bearer from --token-env) and print the server's run summary
cdmon serve [--host H --port P]  # serve THIS repo's standalone console + API locally over the built Astro frontend — no central access (L-01); needs a config/cdmon/ layout (run `cdmon init --v2` first)

# --- feature catalog & traceability (EPIC R) ---
cdmon wiki [--check]       # regenerate the golden feature-doc/FEATURES.md + feature-doc/wiki/* from their single sources; --check is the CI freshness gate (fails if any wiki is stale)
cdmon trace [--fail-on-gap]  # traceability gate: prove every catalog feature has ≥1 demo AND ≥1 test via inline `Feature:` tags scanned from tests/ and demo/ (--fail-on-gap exits 1 on a gap)

# --- public contract ---
cdmon schema               # emit the public ReviewRecord JSON schema
```

### Drop-in CI + a worked example (EPIC G)

- **`templates/ci/`** — copy-paste CI for adopters: `gitlab-ci.adopter.yml`
  (GitLab) and `github-actions.adopter.yml` (GitHub Actions), each with a
  `cdmon-gate` job (`doctor` → `check` → `lint`, offline) and a default-branch
  `cdmon-docs-pr` job (`should-sync` guard → `monitor --apply` → `open-docs-pr`).
  See `templates/ci/README.md`; set `CDMON_CENTRAL_TOKEN` as a CI secret (E-06). A
  repo test keeps the templates honest — they reference only real `cdmon`
  subcommands.
- **`examples/external-repo/`** — a small self-contained repo that ADOPTS cdmon
  (its own `src/widget.py` + `docs/api.md` + `cdmon.yaml`). Its test heals it and
  reports the healed records to an in-process central server (`TestClient`) with a
  bearer token, proving the whole client→server loop offline (the capstone, G-04).
  (See also `examples/multilang/` for cross-language extraction.)

## Document Layout Standard

Beyond keeping content in sync, code-doc-monitor standardizes **how a managed
doc is written** so every adopting project lays its docs out the same way: a
canonical skeleton (front matter → `#` title → `>` purpose → prose →
`CDM:BEGIN/END` regions), a managed front-matter schema
(`cdm.schema_version` / `audience` / `fingerprint`), and an HTML-twin pairing
rule (`X.md` → `X.html`, derived-not-edited, carrying an embedded source hash).
helium's `HELIUM:AUTOGEN … START/END` markers are a documented alias of the same
grammar. The standard is **machine-checked** — `cdmon lint` is a structure gate
orthogonal to `check`'s content gate (run both in CI), `cdmon new-doc` scaffolds
a conformant file, and `cdmon build` (re)renders the `.html` twins. See
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

- [`AGENT.md`](code_doc_monitor/agent/prompts/AGENT.md) — the recipe + audience-aware judgement rules,
- [`PROTOCOL.md`](code_doc_monitor/agent/prompts/PROTOCOL.md) — the strict JSON verdict contract,
- [`TOOL.md`](code_doc_monitor/agent/prompts/TOOL.md) — the two fix shapes (loaded only for a healable drift),
- [`PERSONA.md`](code_doc_monitor/agent/prompts/PERSONA.md) — voice (loaded only when `use_persona`),
- [`EXEMPLARS.md`](code_doc_monitor/agent/prompts/EXEMPLARS.md) — few-shot exemplars from past resolved drift (loaded only when similar records are retrieved; D-04).

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
`code_doc_monitor.server` that ingests repo registrations + review records over
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
`cdmon-server` or `uvicorn code_doc_monitor.server.app:create_app --factory`.

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
source of truth for every feature of code-doc-monitor (19 subsystems; the exact
feature count is the header of `feature-doc/FEATURES.md`). From it,
`cdmon wiki` regenerates four artifacts — never hand-edited:

- `feature-doc/FEATURES.md` — the rendered feature reference,
- `feature-doc/wiki/SOURCE_WIKI.md` — per-module public symbols + feature links,
- `feature-doc/wiki/TEST_WIKI.md` — every test case grouped by boundary,
- `feature-doc/wiki/TRACEABILITY.md` — the feature × demo × test matrix.

`cdmon wiki --check` is the CI freshness gate (fails if any wiki is stale).
`cdmon trace --fail-on-gap` proves every feature traces 1:1 to a demo **and** a
test by scanning inline `Feature: <id>` tags in `tests/` and `demo/` (currently
complete — every catalogued feature has both). Both run offline in CI (the
`docs:gate` job).

## Public schema

Every handled drift becomes a versioned `ReviewRecord` (the public contract for
the central monitoring system). The JSON Schema is generated from the model —
`cdmon schema` — and a snapshot lives at
[`docs/REVIEW_RECORD_SCHEMA.json`](docs/REVIEW_RECORD_SCHEMA.json).

## Dogfooding

code-doc-monitor monitors **its own** source against its own engineering docs:
the shipped [`config/cdmon/`](config/cdmon) dir layout (an `index.yaml` plus the
per-area unit files) maps this package's modules onto the docs under `docs/api/`
(with `schema.py` as a shared, multiply-referenced file). Run `cdmon check` here
(it auto-detects `config/cdmon/`) to see it in action; the dogfood is asserted in
`tests/system/test_dogfood.py`. Any edit to a tracked module drifts the matching
`docs/api/*` doc — reheal with `cdmon monitor --apply` before the suite is green.

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
.venv/bin/mypy code_doc_monitor
.venv/bin/pytest -q --cov=code_doc_monitor --cov-branch
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
- **`docs:gate`** — the offline doc gates: `cdmon check` + `cdmon lint` + the
  EPIC-R `cdmon wiki --check` + `cdmon trace --fail-on-gap`.
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
