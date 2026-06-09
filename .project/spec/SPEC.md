# code-doc-monitor — specification

`spec_version 1.0.0`

## Purpose

A **standardized, reusable** system that keeps documentation in sync with the
code it describes. It is *not* tied to any one codebase: a project adopts it by
writing a config that maps groups of code files (down to functions / line ranges
/ variables) onto **logical documents**, each tagged with an **audience**.

It generalizes the `docsync` pattern (used in genbuild and in helium's
`helium docs`) — extract a code surface, fingerprint it, detect drift against the
docs — and adds an **automatic remediation loop**: when drift is found, an LLM is
asked to explain the cause and either **fix** the document or **invalidate** the
drift (decide the change is irrelevant to that document's audience). Every drift
and every verdict is logged for human review and emitted to a central monitoring
system through a public, versioned schema.

## The problem it solves

Docs rot. A detector that only *warns* still needs a human to act, and a fixer
that acts *silently* can't be trusted. code-doc-monitor closes the loop while
keeping a human in the review seat: it **detects**, **auto-remediates with an
LLM**, and **records the original drift + the proposed fix** so a person (or a
central dashboard) can audit what changed and why.

## Core concepts

* **Logical document** — one output doc (e.g. a user guide page). Has an `id`, a
  `path`, an `audience`, and a list of **code references**.
* **Code reference** — a pointer to code that the document depends on: a whole
  file, or a sub-file selection (`symbols`, `lines`, `names`). A code file may be
  referenced by *several* documents (a *shared* file); each document sees only
  the slice it references.
* **Audience** — `user-guide` or `eng-guide`. Drives both *what* is extracted
  (the surface) and *how* drift is judged:
  * `user-guide` — only the externally-visible surface matters (public function
    signatures, CLI options, public constants). Comment edits, local-variable
    renames, and private/`_`-prefixed changes are **invalidatable** (not drift).
  * `eng-guide` — the implementation surface matters too; comment and internal
    changes **are** flagged.
* **Surface** — the audience-filtered, normalized facts extracted from a
  document's code references, plus a stable `surface_hash`.
* **Drift** — a discrepancy between a document's stored fingerprint / managed
  regions and the current surface.
* **Verdict** — the LLM backend's decision for one drift: `FIX` (with new doc
  content / patch), `INVALIDATE` (with a reason), or `ESCALATE` (needs a human).
* **Backend** — the thing that produces a verdict. Pluggable: `mock` (default,
  deterministic, offline), `claude-code` (headless `claude -p` subprocess),
  `api` (Anthropic API), and `agent` (a deterministic **LangGraph** workflow
  whose prompt is composed from separated Markdown artifacts and whose runtime
  is itself chosen by an `agent:` config block — the headless Claude Code CLI by
  default, or an API key, or a local model endpoint). Selected entirely by
  config; the `agent` backend is an opt-in `[agent]` extra (K0).
* **Review record** — the public, versioned payload for one handled drift:
  the drift, the cause, the proposed fix, the verdict, an audience+config
  snapshot, hashes, and timestamps. Appended to a local JSONL review log and
  emittable to a central system.

## Functional requirements

1. **Config-driven** — everything (documents, groupings, audience, backend,
   central endpoint) lives in one YAML or JSON file. A template ships, and
   `cdmon init` writes it.
2. **Audience-aware extraction** — the surface for a document reflects its
   audience (FR per *Audience* above).
3. **Sub-file granularity** — a code reference can select whole files, named
   symbols, line ranges, or named variables; shared files contribute only their
   selected slice to each document.
4. **Drift detection** — `cdmon check` reports drift and exits non-zero (the
   warning signal). It never mutates anything.
5. **Auto-remediation** — `cdmon monitor` detects drift, calls the configured
   backend per drift, applies `FIX` results (when auto-apply is enabled),
   records `INVALIDATE`/`ESCALATE`, and re-checks.
6. **Human-reviewable log** — every handled drift is appended to a JSONL review
   log with the original drift *and* the fix, so a human can review both.
7. **Public schema** — review records serialize to a versioned, documented JSON
   schema; the schema is exportable (`cdmon schema`) and records are emittable to
   a central system (HTTP sink, or file sink for offline/tests).
8. **Backend-agnostic** — switching `claude-code` ↔ `api` ↔ `mock` ↔ `agent` is
   a config edit, no code change. The `agent` backend runs a deterministic
   LangGraph workflow built from separated `AGENT.md` / `PROTOCOL.md` /
   `TOOL.md` / `PERSONA.md` artifacts (composed only when needed), and its model
   runtime is a second config-only choice (`agent.driver`: the Claude Code CLI
   headless, an Anthropic API key, or a local OpenAI-compatible endpoint).
9. **Offline-testable** — the default backend and central sink are offline; the
   whole pipeline (incl. `monitor`) runs in CI with zero network and no LLM.
10. **Dogfooding** — code-doc-monitor ships a config that maps *its own* source
    onto *its own* docs, and that config is exercised in the test suite.

## CLI surface (`cdmon`)

| command | does |
|---|---|
| `cdmon init [--path cdmon.yaml] [--central URL --repo-id ID --token-env VAR --repo-url URL]` | write a config template. WITHOUT `--central` the offline starter template is written byte-identical; WITH `--central URL` the `central:` block is wired for HTTP reporting (`sink: http` + url + repo_id + auth_env + outbox), ready to `cdmon register` + report — round-trips through `load_config` and satisfies `make_sink` (G-01). `--repo-id` defaults to the cwd dir name; `--token-env` defaults to `CDMON_CENTRAL_TOKEN` |
| `cdmon doctor [--config ...]` | offline, read-only preflight (G-02): loads the config (malformed → loud K8, exit 1) then runs deterministic, network-free checks (config / documents / backend prereq / central wiring / optional `[agent]` extra) and prints one `STATUS  name — detail` line each. A merely-absent runtime prereq (no `claude` CLI, unset `$ANTHROPIC_API_KEY`/token, optional extra not installed) is WARN; only a structurally-broken config (http sink missing url/repo_id) is FAIL. Exit 0 unless any FAIL. A `--ping` connectivity probe is future/out-of-scope (default is offline, K1/K4/K10) |
| `cdmon surface [--config ...]` | dump the extracted per-document surface (debug) |
| `cdmon check [--config ...]` | detect drift; exit non-zero on drift (warn) |
| `cdmon monitor [--config ...] [--apply/--no-apply] [--ref/--source-sha REF]` | detect → backend verdict → record → (apply) → re-check; `--ref`/`--source-sha` stamps each record's `source_sha` provenance (precedence: flag, else `$CI_COMMIT_SHA`, else none — C-05) |
| `cdmon report [--config ...] [--verdict V] [--json]` | summarize the review log; the aggregate view also joins resolutions to show `resolved`/`unresolved` counts + `by_resolution` (D-01/D-02); `--verdict` lists the individual records of that verdict (e.g. the `ESCALATE`s needing a human) |
| `cdmon resolve RECORD_ID --resolution {accepted\|overridden\|rejected\|invalidated} [--by NAME] [--text TEXT] [--note NOTE] [--config ...] [--log PATH]` | record the human OUTCOME of a handled drift as a SEPARATE append-only event linked to a review record by `record_id` (the review log stays immutable, K5). Validates the id exists (loud K8 on unknown id). `--text` stores the human's final body for `overridden`. Default log `.cdmon/resolutions.jsonl`; timestamp injected (K10). The substrate D-03..D-06 mine (D-01/D-02) |
| `cdmon promotions [--config ...] [--min-count N] [--json]` | list promotion CANDIDATES from the local logs (read-only, D-05): each generalizable shape `(doc_id, drift_kind, audience)` whose RESOLVED records (≥ `--min-count`, default 3) ALL share ONE *decision* resolution (`invalidated`/`rejected`) — a decision promotable to a deterministic rule the monitor applies with ZERO backend calls (D-06). `overridden` (human prose) and `accepted` (already LLM-free) are excluded. Pure + read-only (K1/K10) |
| `cdmon coverage [--config ...] [--json] [--fail-under N] [--write [PATH]]` | report doc coverage: file/public-symbol percentages + documented/undocumented/waived baskets; `--fail-under N` gates on public-symbol coverage (exit 1 below N), else informational; `--write [PATH]` writes a deterministic manifest (payload + gap→owner suggestions) to `PATH` (default `.cdmon/coverage.json`), idempotent (rewrites nothing / prints "unchanged" when content is identical) |
| `cdmon sync-pr [--config ...] [--out FILE] [--dry-run]` | heal the docs and emit a unified-diff patch of exactly the changed docs (the docs-PR content C-03 turns into an MR); applies + prints the patch by default (or writes it to `--out`), `--dry-run` computes the SAME patch with NO mutation (K1), a clean/second run is an empty patch (idempotent, K7); offline + deterministic (K4/K10) |
| `cdmon open-docs-pr [--config ...] [--dry-run] [--target BRANCH] [--ref REF]` | heal the docs then open a docs merge request (branch + commit of the healed docs + MR) via the default GitLab transport (stdlib urllib, K0; built from CI env, loud on a missing var, K8); a clean repo is a no-op ("nothing to open"); `--dry-run` computes + prints the MR plan as JSON from a DRY sync (NO mutation, K1; no transport built/called); deterministic branch from a hash of the patch (K10); offline in `--dry-run` (K4) |
| `cdmon should-sync [--config ...] [FILES...]` | loop-safety guard (C-04): exit 0 to PROCEED with a heal, 1 to SKIP. Skips when every changed file is a managed doc path (a bot doc-only commit) or the set is empty; reads FILES from args or newline-separated stdin (`git diff --name-only \| cdmon should-sync`). Pure + read-only (K1); breaks the PR→heal→PR loop structurally |
| `cdmon register [--config ...] [--dry-run]` | announce this repo to the central server (E-02): POST a versioned `RegistrationPayload` (its `RepoIdentity` from `central.repo_id`/`repo_name`/`repo_url` + commit from `central.repo_commit` else `$CI_COMMIT_SHA`) to `<central url>/repos` via the default stdlib transport (bearer from `central.auth_env`, K0); loud K8 if `central.repo_id`/`url` missing; `--dry-run` prints the payload it WOULD send with NO network call (K4). The server `/repos` endpoint (E-03) consumes this same payload — ONE shared schema, no DTOs (K6) |
| `cdmon surface-gaps [--config ...] [--dry-run] [--provider gitlab\|github]` | turn doc coverage gaps into a tracker issue (H-04): runs discover→`resolve_coverage`→`suggest_owners`, builds a deterministic `IssuePlan` listing every undocumented public symbol grouped by its suggested owner (A-07). No gaps is a no-op ("no coverage gaps"); `--dry-run` prints the plan as JSON with NO transport built/called (K4); else opens the issue via the provider's stdlib-urllib transport built from CI env (GitLab `CI_PROJECT_ID`/`CDMON_GITLAB_TOKEN`/`CI_API_V4_URL`; GitHub `GITHUB_REPOSITORY`/`CDMON_GITHUB_TOKEN`/`GITHUB_API_URL`; loud K8 on a missing var). Deterministic payload (K10) |
| `cdmon schema [--out FILE]` | emit the public review-record JSON schema |

## Adopting cdmon (EPIC G — drop into any repo)

cdmon is droppable into any repo with three pieces (none specific to a target
codebase — K0):

1. **Bootstrap a config.** `cdmon init --central <url> --repo-id <id>` writes a
   `cdmon.yaml` with an HTTP-reporting `central:` block (`sink: http` + url +
   repo_id + auth_env + outbox). Map your code → docs in it. A worked example
   lives in `examples/external-repo/cdmon.yaml`.
2. **Wire CI.** `templates/ci/` ships drop-in workflows (G-03):
   - `gitlab-ci.adopter.yml` (GitLab) and `github-actions.adopter.yml` (GitHub
     Actions) — each with a **`cdmon-gate`** job (`cdmon doctor` → `check` → `lint`,
     offline, fails the pipeline on drift) and a default-branch **`cdmon-docs-pr`**
     job (`cdmon register` → a `cdmon should-sync` loop-guard over
     `git diff --name-only` → `cdmon monitor --apply --ref` → `cdmon open-docs-pr
     --ref`). See `templates/ci/README.md`. A repo test parses every template
     script line and fails if it ever names a `cdmon` command the CLI doesn't
     expose, so the templates can't silently drift from the CLI.
3. **Set the central bearer token as a CI secret** (`CDMON_CENTRAL_TOKEN`,
   protected/masked on GitLab or a repo secret on GitHub — E-06). The central URL +
   repo_id are committed in `cdmon.yaml`; only the token is secret.

`examples/external-repo/` is the capstone PROOF (G-04): a self-contained adopter
(`src/widget.py` + `docs/api.md` managed `symbols` region + `cdmon.yaml`) whose
test heals it and reports the healed records to an in-process central server
(FastAPI `TestClient`, `HttpSink`'s injected client wired to it) with a bearer
token, asserting the repo + records land server-side and a WRONG token is
rejected — the whole client→server loop, entirely offline (K4).

## Central server (`code_doc_monitor.server`, optional `[server]` extra — E-03)

The CENTRAL side of the client sink/registry: a FastAPI app that ingests repo
registrations + review records over the SHARED, versioned schemas (no DTOs, K6).
It lives behind the `[server]` pip extra (`fastapi`, `uvicorn[standard]`, `httpx`)
and is imported lazily — installing/importing the core engine pulls in nothing
from it, so the core dependency surface stays minimal (K0, like the `[agent]`
extra). Run it with `cdmon-server` or `uvicorn code_doc_monitor.server.app:create_app --factory`.

| method + route | body / response | notes |
|---|---|---|
| `POST /repos` | `RegistrationPayload` → `201 {"repo_id": ...}` | registers a repo (E-02's payload, validated directly) |
| `POST /ingest` | `IngestEnvelope` → `202 {"record_id": ...}` | stores a record under its repo; **unknown `repo_id` → 404** (registration is explicit, never auto-registered) |
| `GET /repos` | → `list[RegisteredRepo]` | deterministic (insertion) order (K10) |
| `GET /repos/{repo_id}/records` | → `list[ReviewRecord]` | the repo's records in arrival order; **filters** `verdict`/`drift_kind`/`audience`/`doc_id` + `limit`/`offset` (E-05, via the indexed columns); unknown repo → 404 |
| `GET /repos/{repo_id}/resolutions` | → `list[ResolutionRecord]` | the repo's resolutions; optional `record_id` filter; unknown repo → 404 (E-05) |
| `GET /repos/{repo_id}/coverage` | → `list[dict]` | coverage snapshots (latest last); unknown repo → 404 (E-05) |
| `GET /repos/{repo_id}/status` | → `RepoStatus` | a **computed view**: `total_records`, `by_verdict`, `escalations`, `unresolved`, `last_detected_at`, `coverage_ratio`; unknown repo → 404 (E-05) |
| `GET /repos/{repo_id}/health` | → `RepoHealth` | a **computed metrics view**: `total`, `escalations`, `escalation_rate`, `unresolved`, `overrides`, `resolved`, `mttr_seconds`; unknown repo → 404 (F-05) |
| `GET /repos/{repo_id}/telemetry` | → `RepoTelemetry` | a **computed underperformer view** (H-01): per `(drift_kind, audience)` shape — `count`, `escalations`/`escalation_rate`, `overrides`/`override_rate` — sorted WORST-FIRST (escalation_rate desc, then override_rate desc), plus `promotion_candidates` (`detect_promotions` server-side); unknown repo → 404 |

A malformed body is a `422` (FastAPI/pydantic validation against the shared
model; the models are `extra="forbid"`, so an unexpected key is rejected too —
K8). Storage is the `Store` Protocol: E-03 ships an in-memory store; **E-04 swaps
in SQLAlchemy/Postgres behind the same Protocol** without touching the routes.

**Query API (E-05).** The `GET .../records` filters map 1:1 to the E-04 indexed
scalar columns (SQL `WHERE` on the DB store; equivalent dict filtering in memory),
then the matching rows are re-validated from the FULL JSON column (K6 source of
truth on read). `limit`/`offset` paginate over the deterministic insertion order
(K10); a non-positive `limit` or negative `offset` is a `422`. **`RepoStatus` is a
computed AGGREGATE response model** — the one place a response DTO is acceptable,
because it is a *view*, not a parallel copy of a stored shared model (K6 governs the
stored `ReviewRecord`/`ResolutionRecord`, which these endpoints still return AS the
shared schema).

**Per-repo bearer auth (E-06).** Writes (`POST /ingest` and re-register of an
existing repo) require a valid per-repo bearer token; **reads (`GET …`) are open**
(the dashboard needs no token to display data; tightening reads is future work).
The token is **client-provided at register** and stored **only as a sha256 hash**
(`repos.token_hash`, an additive nullable column + Alembic migration `0002`) — never
plaintext, never returned. It travels on `RegistrationPayload` as a write-only
`auth_token` (additive, K6; absent from every read serialization). The
`require_repo_token` dependency: unknown repo → `404`; repo has a token but the
`Authorization: Bearer` header is missing → `401`; header present but the hash
mismatches → `403`; match (or the repo registered without a token) → pass. The
client (`HttpSink`/`registry`) already sends `Authorization: Bearer <auth_env>`.

### Database + migrations (E-04, `server/db.py` + `alembic/`)

The production store is **SQLAlchemy 2.0, Postgres-first** (`SqlStore(engine)`,
implementing the same `Store` Protocol plus resolution + coverage-snapshot
methods). Persistence is **portable**: the default offline test suite runs the
identical contract on **in-memory/temp-file SQLite** (K4/K9, no driver needed —
SQLite is stdlib), and a `pg` pytest marker (mirroring `live_llm`, skipped by
default via `addopts = -m "not live_llm and not pg"`) runs it against
`$CDMON_DATABASE_URL` Postgres in the `tests:pg` CI job.

Each record/resolution row uses an **"indexed columns + full JSON" hybrid**: the
FULL shared pydantic model is stored in a JSON column (`JSONB` on Postgres, JSON
on SQLite via `with_variant`) so an **additive schema field round-trips with no
migration** (K6) — old rows still parse — while indexed scalar columns
(`repo_id`, `doc_id`, `verdict`, `drift_kind`, `audience`, `detected_at`,
`source_sha`) mirror the queryable fields for E-05's SQL filters. Tables:
`repos`, `records`, `resolutions`, `coverage_snapshots`. `sqlalchemy>=2.0` +
`alembic` (+ `psycopg[binary]` for real PG) ship under the `[server]` extra, so
the core engine's dependency surface is unchanged (K0). The Alembic env reads
`$CDMON_DATABASE_URL`; the initial migration mirrors the models 1:1 (`upgrade
head` creates the tables, `downgrade base` drops them).

## Acceptance (system level, all offline)

* A fixture repo with shared files grouped into a `user-guide` doc and an
  `eng-guide` doc: editing a public signature drifts **both**; editing only a
  comment drifts **only the eng-guide** (the user-guide change is INVALIDATE-able
  and is invalidated by the mock backend).
* `cdmon monitor` on that fixture: drift detected → backend verdict → review log
  grows with original-drift + fix → re-check is clean for FIX'd / INVALIDATE'd
  items; ESCALATE items remain and are reported.
* Switching backend `mock`→`claude-code` in config changes only which subprocess
  is invoked (proven by a mocked subprocess), not the orchestration.
* `cdmon schema` emits a valid JSON Schema; every review record validates.
* code-doc-monitor's own config (dogfood) is in sync (or its drift is explained).
* ruff + mypy clean; coverage ≥ 90%.
