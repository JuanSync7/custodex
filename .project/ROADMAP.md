# code-doc-monitor — EPIC-2 roadmap (backlog)

Epics → subtasks → **vertical slices**. Each slice is one subagent's job: a TDD
loop (test-first), a single validable goal, additive (never breaks a prior
slice), ruff+mypy clean, ≥90% coverage. See [PROCESS.md](PROCESS.md) for the
binding execution contract and [STATUS.md](STATUS.md) for the live board.

Slice IDs: `A-01`, `B-03`, … Slices may **subdivide** during execution (a slice
that grows past one lean context becomes `A-03a`/`A-03b`); that is expected and
encouraged — keep each subagent's context lean and focused.

Status legend: ☐ todo · ◐ in progress · ✅ done · ⊘ blocked

---

## EPIC A — Lossless coverage & "basket"  (the code↔doc index)

**A1 — Repo code inventory**
- ✅ **A-01** `inventory.py`: enumerate all code files under `root` honoring
  include/exclude globs. Pure, deterministic, sorted. *Goal:* on a fixture tree,
  returns the exact expected file set; ignore patterns honored; loud on bad glob.
  *(custom `_translate` glob→regex — `fnmatch` leaks top-level dot-dirs; symbols
  attach per-file in A-02 via `extract.extract_file`.)*
- ✅ **A-02** symbol-level inventory: every public symbol per file (reuse
  `extract.extract_file`). *Goal:* every public symbol in a fixture file listed;
  audience filter respected; deterministic order. *(loud on unparseable —
  `--skip-unparseable` deferred to EPIC G, see `.project/problems/A-02.md`.)*

**A2 — Ownership mapping**
- ✅ **A-03** `coverage.py` resolver: cross inventory × `config.documents` →
  per-symbol/file ownership (documented vs unowned). *Goal:* fixture with 3
  files, 2 referenced → exactly the unreferenced file/symbols reported as gaps.
  *(ownership ignores audience; gap-% universe = public symbols; reuses
  `extract._select`. `resolve_coverage(config, inv)`.)*
- ✅ **A-04** config `coverage:` section: include/exclude globs + `waive` list
  (path/symbol + reason). *Goal:* config round-trips; waived items excluded from
  gaps; loud on malformed waiver. *(waived items leave numerator+denominator;
  inert non-matching waiver is silent; missing `reason` → ConfigError.)*

**A3 — Reporting & gate**
- ✅ **A-05** `cdmon coverage` CLI: % documented + three baskets, `--json`.
  *Goal:* correct numbers + exit code on a fixture. *(real repo baseline: 18.2%
  public-symbol / 22.2% file documented.)*
- ✅ **A-06** coverage gate: `--fail-under N` (gates on `percent_public_symbols`);
  informational non-blocking CI step. *Goal:* exits nonzero below threshold.

**A4 — Gap remediation assist** — ✅ **EPIC A COMPLETE (A-01…A-08)**
- ✅ **A-07** gap → suggested doc owner. *Decision:* deterministic heuristic in
  `coverage.py` (`suggest_owners`), NOT the Backend Protocol (avoid widening it
  for a coverage concern). Sibling-owned → existing doc; unowned file → proposed
  new doc id `pkg-sub-mod`. LLM-enhanced suggester deferred (`.project/problems/A-07.md`).
- ✅ **A-08** `cdmon coverage --write [PATH]`. *Decision:* writes a dedicated
  regenerable manifest (`.cdmon/coverage.json`, gitignored), NOT into the
  comment-bearing `cdmon.yaml` (would need ruamel = new dep, breaks K0; config
  stays `extra=forbid` hand-owned). Idempotent (K7): 2nd run "unchanged".

## EPIC B — Region authority model (human ⊕ llm ⊕ generated)

**B1 — Authority schema**
- ✅ **B-01** region `mode` field (`generated|llm|human|llm-seeded`), default
  `generated` (back-compat). *Goal:* config round-trips; unknown mode → loud error.
  *(`RegionMode` enum + `DocumentSpec.region_modes` + `mode_for` accessor; modes
  validated against `region_keys` at config-load.)*

**B2 — Heal respects authority**
- ✅ **B-02** heal skips `human` regions (flags drift advisory, never rewrites).
  *Goal:* stale human region reported but byte-unchanged after heal. *(guarantee
  at the heal WRITE boundary via `apply_fix(*, preserve=...)`; human staleness =
  fingerprint moved, not body-vs-render. Finished by orchestrator after subagent
  hit session limit. Known limitation: HASH heal clears the advisory → fixed
  properly by B-03's per-region hash.)*
- ✅ **B-03** `llm-seeded` lock: first heal fills; after human edit (content-hash
  divergence) heal leaves it. *Goal:* two-phase fixture proves fill-then-lock.
  *(per-region `cdm.region_hashes` + shared `region_is_locked` predicate; also
  fixed B-02's advisory-persistence limitation. NOTE: pure-`llm` prose authoring
  — a no-renderer region an LLM writes — deferred to a dedicated slice near the
  backend/EPIC-D work; B-03 treats llm-seeded as generated-until-locked.)*

**B3 — Mixed-authorship doc**
- ✅ **B-04** system test: one doc with all four modes heals correctly together.
  *Goal:* generated rewritten, human preserved, llm-seeded locked, **llm per the
  documented INTERIM rule**. *(`test_system.test_mixed_authorship_four_regions_e2e`:
  four regions — generated + human + llm-seeded + declared llm — in ONE doc;
  generated/llm regenerate, human byte-identical + advisory, llm-seeded
  fill-then-lock. **Interim `llm` == `generated`** (renderer-backed → rendered in
  sync; no-renderer → UNHEALABLE/ESCALATE, never silently stale): the SAFE choice,
  documented in `config.RegionMode` + LAYOUT_STANDARD §7.)*
- ✅ **B-05** LAYOUT_STANDARD + `cdmon lint --modes` surface the per-region `mode`
  + lock/advisory STATE. *Goal:* lint reports each region's mode + state without
  re-validating (a state surface, NOT a new gate — lint's pass/fail is unchanged).
  *(`layout.RegionState`/`region_states`/`config_region_states`; `cdmon lint --modes`
  prints `doc::region — mode [renderer|no-renderer] [locked] [advisory]`.)*
- ✅ **B-06** pure-`llm` (no-renderer) prose authoring — REPLACES the interim
  `llm`==`generated` rule. *Goal:* a `mode: llm` region with no renderer is
  backend-authored prose: re-authored when the code surface moves, idempotent
  no-op when it doesn't, human regions untouched, and loud (never silently stale)
  when there's no authoring path. *(`FixRequest.region_mode` (additive, K6) set
  from `mode_for`; `drift.detect` no-renderer `llm` branch → healable `REGION` on
  fingerprint move, no drift otherwise (non-`llm` stays `UNHEALABLE`);
  `MockBackend` authors a deterministic, audience-aware prose stand-in (K4/K10);
  `build_prompt` prose clause for real backends; the whole-doc HASH heal preserves
  a no-renderer region's body byte-identical (the idempotence point). Proven by
  `test_system.test_pure_llm_no_renderer_authored_e2e` (four-goal e2e) + `[B-06]`
  regression guard.)*

**EPIC B COMPLETE.** generated/human/llm-seeded **and pure-`llm` prose authoring**
all working end to end (B-06 closed the last deferral — the interim `llm`==`generated`
rule is gone; a no-renderer `llm` region is now real backend-authored prose).

## EPIC C — PR-driven loop & trigger

- ✅ **C-01** `docs:gate` MR job in `.gitlab-ci.yml` (offline `cdmon check`+`lint`).
- ✅ **C-02** `cdmon sync-pr` (+`--dry-run`): heals + emits a git-free `difflib`
  patch of changed docs; empty + idempotent when clean; honors region authority
  (human/locked bodies never in the patch). `sync_pr(monitor, *, dry_run)`.
- ✅ **C-03** bot-PR opener `cdmon open-docs-pr` (injected `PRTransport`;
  `GitLabTransport` stdlib-urllib default; deterministic branch from patch hash;
  dry-run prints plan; empty→no-op). `pr.py` 100%, real HTTP the only uncovered leaf.
- ☑ **C-04** loop-safety: doc-only commit produces no re-trigger (simulated).
  *Goal:* guard proven with a fixture commit graph. → `syncpr.should_sync` +
  `cdmon should-sync` (exit 0 proceed / 1 skip) + the `.gitlab-ci.yml` `docs:heal`
  guard; truth-table + CLI-exit-code tests prove doc-only→skip, mixed→proceed,
  empty→skip.
- ☑ **C-05** provenance: doc-PR links source commit/PR; record carries
  `source_sha`. *Goal:* record + trailer assert the link. → additive
  `ReviewRecord.source_sha` (old logs still parse, K6) stamped by
  `Monitor`/`cdmon monitor --ref`; ref precedence: flag → `$CI_COMMIT_SHA` → none.

> **EPIC C COMPLETE** (C-01..C-05). The PR-driven loop is closed end-to-end and
> SAFE: `check`/`sync-pr` produce the docs patch, `open-docs-pr` opens the MR with
> a provenance `ref`, `should_sync` structurally prevents the bot's doc-only commit
> from re-triggering the heal, and every record carries `source_sha` (the same ref
> the MR shows). EPIC D builds the outcome/feedback edge on this same schema
> additivity (`cdmon resolve` + a resolution field).

## EPIC D — Outcome/feedback edge & learning

- ☑ **D-01** outcome edge on the public schema (additive, K6): resolution +
  resolved_text/by/at. *Goal:* versioned-additive; old logs still parse. **DONE**
  — `Resolution` enum + `ResolutionRecord` (frozen, `note` appended last → K6
  back-compat); `resolution_record_schema()`.
- ☑ **D-02** `cdmon resolve <record_id> …`: append a human outcome. *Goal:*
  outcome persisted + queryable. **DONE** — append-only `.cdmon/resolutions.jsonl`
  (`append_resolution`/`read_resolutions`), `resolved_index` (last-write-wins) +
  `summarize_with_resolutions`; `cdmon resolve` (loud K8 on unknown id, injected
  `now`) + `report` resolved/unresolved counts.
- ☑ **D-03** `similar.py`: rank N most-similar past resolved records. Pure.
  *Goal:* a planted near-duplicate ranks first; deterministic.
- ☑ **D-04** agent backend consumes retrieved exemplars (new artifact + select
  rule). *Goal:* prompt includes exemplars when present; offline fake driver.
- ☑ **D-05** promotion detector: recurring shape→identical resolution ≥K →
  promotion candidate. *Goal:* 3 identical resolutions emit one candidate. **DONE**
  — `promotion.py` (pure): `detect_promotions(records, resolutions, *, min_count=3)`
  groups RESOLVED records by the GENERALIZABLE shape `(doc_id, drift_kind, audience)`
  (NOT `surface_hash`); a shape with ≥K resolved records UNANIMOUSLY sharing ONE
  DECISION resolution (`invalidated`/`rejected`) → one `PromotionCandidate`.
  `overridden`/`accepted` excluded; `cdmon promotions [--min-count N] [--json]`.
- ☑ **D-06** rule application: promoted rule resolves that shape with **no
  backend call**. *Goal:* post-promotion, zero backend invocations for it. **DONE**
  — `PromotionRule` + `rule_for(drift, rules)`; `Monitor(..., rules=())` opt-in
  (default ⇒ byte-identical to today). A matched drift synthesizes a `BackendResult`
  (rule verdict, `fix=None`, rule-sourced `cause`/`config_snapshot["resolved_by"]="rule"`)
  WITHOUT calling `backend.propose` — proven by a SPY backend asserting `calls==0`.

**EPIC D COMPLETE** — the outcome/feedback edge (D-01/02), similarity retrieval +
few-shot exemplars (D-03/04), and the promotion detector + zero-backend-call rule
application (D-05/06) close the learning loop: humans resolve, the system mines the
resolutions, and a recurring DECISION is promoted to a deterministic rule so the
LLM is no longer consulted for it — the cost curve bends DOWN as it learns.

## EPIC E — Central server + DB

> **STACK DECISIONS (user-chosen, 2026-06-05):** FastAPI in a
> `code_doc_monitor.server` subpackage behind a `[server]` pip extra (K0: core
> install unchanged; server opt-in, lazy). **Postgres-first** via SQLAlchemy +
> Alembic. **Per-repo bearer token** auth. *Testing reconciliation (K4/K9 offline
> gate is sacred):* SQLAlchemy models use portable column types (JSON/JSONB) so
> the default offline suite runs the data layer on **in-memory SQLite** + FastAPI
> **TestClient** (no socket, no live PG); a `pg` pytest marker (mirroring the
> `live_llm` marker) runs the same suite against a real Postgres in CI only. The
> ONE versioned schema (`ReviewRecord`/`ResolutionRecord`) is shared client↔server
> — no hand-written DTOs (K6).

- ☑ **E-01** `HttpSink`+ repo identity, batching, offline queue + retry
  (injected transport). *Goal:* records carry repo_id/commit; queue flushes; no network.
  *(client-side only — no server deps; first E slice.)* **DONE** — `RepoIdentity`
  + `IngestEnvelope` (shared versioned wire format, K6) in `sinks.py`; `HttpSink`
  wraps→drains-outbox-oldest-first→retries→queues, NEVER raises (K4); `CentralConfig`
  additive repo fields; `make_sink` loud-on-missing-`repo_id` (K8). 583 tests, gate green.
- ☑ **E-02** repo registration payload/client. *Goal:* correct payload via mock transport.
- ☑ **E-03** server skeleton: `code_doc_monitor/server/` ([server] extra, FastAPI),
  `/ingest` + `/repos`, TestClient. *Goal:* posted record stored & retrievable;
  validated by the SHARED schema (K6). DI'd `Store` Protocol (in-memory now →
  Postgres E-04); unknown-repo ingest → 404 (no auto-register); lazy extra
  boundary verified. 596 tests, gate green.
- ☑ **E-04** SQLAlchemy models + Alembic migrations (Postgres-first; offline tests
  on in-memory SQLite; `pg` marker for real PG): repos/records/resolutions/coverage.
  *Goal:* migrate up/down; CRUD round-trip on SQLite + (CI) Postgres. DONE — `SqlStore`
  behind the same `Store` Protocol (E-03 server tests re-run against it), "indexed
  columns + full JSON" hybrid (K6), Alembic up/down proven, `tests:pg` CI job; offline
  suite SQLite-only (`pg` deselected). 623 passed/2 deselected, db.py 100%, pkg 98.12%.
- ☑ **E-05** JSON query API: drifts/actions/logs/status/coverage per repo + filters.
  *Goal:* endpoints return expected fixtures (TestClient). DONE — `GET .../records`
  filters via the E-04 indexed columns (`verdict`/`drift_kind`/`audience`/`doc_id` +
  `limit`/`offset`, re-validated from the JSON column), plus `.../resolutions`,
  `.../coverage`, and `.../status` → a computed `RepoStatus` view model (the one
  allowed response DTO; not the shared schema, K6). Store Protocol grew on BOTH
  InMemoryStore + SqlStore.
- ☑ **E-06** per-repo bearer-token auth on ingest. *Goal:* unauthorized rejected,
  authorized accepted (TestClient + fakes). DONE — client-provides-token-at-register,
  server stores the **sha256 hash** on a new nullable `repos.token_hash` column
  (additive Alembic `0002`, up/down proven). `require_repo_token` on `POST /ingest`
  + re-register: 404 unknown / 401 missing / 403 mismatch / pass on match; token-less
  repos stay open; **reads are open** (dashboard needs no token for GETs). 648 passed
  / 2 deselected, server pkg ~100%, pkg 98.16%.

**EPIC E COMPLETE** (2026-06-05): the central server now ingests (auth-gated),
persists (SQLAlchemy/Postgres-first, offline SQLite), and serves a filtered JSON
query API + per-repo status view — the data plane EPIC F's SPA consumes.

## EPIC F — Web dashboard  (React + Vite SPA over the EPIC-E JSON API)

> **STACK DECISION (user-chosen):** a `dashboard/` React + Vite + TypeScript SPA
> consuming the EPIC-E JSON API. Its OWN test gate (Vitest component tests; optional
> Playwright e2e) — separate from the Python `pytest` gate, which is unaffected.
> The server may serve the built static assets, but the API is the contract.

- ☑ **F-01** Vite+React+TS scaffold + API client + repos-with-status page. *Goal:*
  renders repos from a mocked API; Vitest green; `npm run build` clean. **DONE** —
  `dashboard/` SPA; lint clean, 9 Vitest tests green (no network), build → `dist/`
  zero TS errors; Python gate still 648 passed + `cdmon check` exit 0.
- ☑ **F-02** per-repo drift/action/log timeline view. *Goal:* renders records (mocked API). — DONE (RepoDetail filterable timeline + resolution badges; 26 frontend tests green).
- ☑ **F-03** coverage view (% + baskets per repo). *Goal:* renders snapshot. — DONE (Coverage % + 3 baskets + empty state).
- ☑ **F-04** resolve/escalate from UI → POST → outcome record. *Goal:* action persists (mocked API + a server integration test). — DONE (`POST /repos/{id}/resolutions` of the SHARED `ResolutionRecord`, token-protected via the E-06 `_verify_token`, 404 on unknown repo/record → 202; RepoDetail resolve form POSTs with a Bearer + reflects the new badge; TestClient auth+persist matrix + Vitest capture tests green).
- ☑ **F-05** health overview (MTTR, escalation/override-rate trends). *Goal:*
  metrics computed (server-side endpoint + UI render). — DONE (`GET /repos/{id}/health` → computed `RepoHealth` {total, escalations, escalation_rate, unresolved, overrides, resolved, mttr_seconds}; exact arithmetic test (mttr=90.0, rate=0.25); `Health.tsx` stat cards + routing/link).

> **EPIC F COMPLETE** (F-01…F-05). The `dashboard/` React+Vite+TS SPA reads the OPEN
> EPIC-E endpoints (repos/status/records/resolutions/coverage/health) and writes the ONE
> Bearer-protected mutation (resolve). Python gate 658 passed/2 deselected, whole-pkg
> 98.19%; frontend gate lint+38 Vitest+build all green; `cdmon check` exit 0.

## EPIC G — Deployability (drop into any repo)

- ☑ **G-01** `cdmon init --central <url>`: wires HttpSink + registration. *Goal:*
  working client config for a fresh fixture repo.
- ☑ **G-02** packaging + `cdmon doctor` prereq check. *Goal:* fresh-venv install + doctor green.
- ☑ **G-03** shipped CI templates (GitLab + GitHub Actions) for adopters. *Goal:*
  template lints; dry-run. *(Done: `templates/ci/{gitlab-ci,github-actions}.adopter.yml`
  + README; a `cdmon-gate` job (doctor+check+lint) and a default-branch `cdmon-docs-pr`
  job (should-sync guard → monitor --apply → open-docs-pr); a template-honesty test
  parses every script line and fails if a template names a command the CLI doesn't expose.)*
- ☑ **G-04** external example repo adopting cdmon end-to-end (not the dogfood).
  *Goal:* external fixture reports to a TestClient server. *(Done: `examples/external-repo/`
  — widget.py + docs/api.md managed `symbols` region + cdmon.yaml http central block;
  `tests/test_example_external.py` copies it, drifts the source, heals (check→monitor
  --apply), registers + reports the healed records to an in-process TestClient server via
  HttpSink (bearer E-06), asserts repo+records land, and a WRONG token is 403'd.)*

**EPIC G COMPLETE** — cdmon is droppable into any repo: `init --central` bootstraps the
client config, `doctor` is the CI preflight, the shipped CI templates wire the gate +
docs-PR jobs, and an external example proves the whole client→server loop offline.

## EPIC H — Self-improvement of the monitor

- ☑ **H-01** telemetry aggregation: which prompts/rules underperform (ESCALATE/
  override rate). *Goal:* metric correct on fixtures. **DONE** — `GET /repos/{id}/
  telemetry` → `RepoTelemetry` (per `(drift_kind, audience)` shape: count,
  escalation_rate, override_rate + `detect_promotions` candidates), worst-first;
  computed in `app.py` from store reads (InMemoryStore + SqlStore, no new method);
  TestClient tests assert exact rates + ordering.
- ☑ **H-02** self-dogfood expansion: cdmon covers its OWN new modules toward
  100%. *Goal:* `cdmon coverage` on own repo ≥ threshold. **DONE** — engine-scoped
  self-coverage 42.2%→100% public symbols (316/316; 4 re-export `__init__`
  symbols waived); CI gate flipped to `--fail-under 95`; `tests/test_dogfood.py`
  asserts the floor so it can't silently regress.
- ☑ **H-03** regression corpus: each captured lesson/limitation → a test. *Goal:*
  corpus runs in CI. **DONE** — `tests/regression/` is a curated, executable INDEX
  of the program's durable invariants (22 cases, each tagged with the lesson it
  guards: [CDM-03/07/08], [B-02/03], [C-04/05], [D-01/06], [E-01], [H-01/02/04]).
  Auto-tagged `regression` via a package `conftest.py` so it is INCLUDED in the
  default suite AND `pytest -m regression` selects exactly the corpus; the marker is
  registered in `pyproject`. One genuinely NEW guard (the unlisted-engine-module gap,
  per the H-01/H-04 finding); the rest are thin re-assertions against existing seams.
  Break-it confirmed bites for the top invariants (documented, not committed). No
  engine code changed; gate green (744 tests, ruff+mypy clean, 98.2% coverage);
  dogfood `check`/`coverage --fail-under 95`/`lint` all exit 0.
- ☑ **H-04** (secondary) surface gaps back to a monitored repo (dry-run issue).
  *Goal:* issue payload asserted, no live call. **DONE** — new `issues.py`
  (`IssuePlan`, injected `IssueTransport`, GitLab/GitHub stdlib-urllib transports with
  the real POST the only `# pragma: no cover` leaf, `plan_coverage_issue`/
  `open_coverage_issue`) + `cdmon surface-gaps [--config] [--dry-run]
  [--provider gitlab|github]`; fake-transport + dry-run-no-call tests; deterministic
  payload; `issues.py` added to `cdmon.yaml` so the self-coverage gate stays green.

**EPIC H COMPLETE** (H-01…H-04). The monitor now observes its own performance
(telemetry), documents its own surface to 100% behind a hard coverage gate, surfaces
gaps back as dry-run tracker issues, and pins every hard-won lesson as a runnable
regression corpus. **EPIC-2 PROGRAM COMPLETE** — see STATUS "EPIC H + EPIC-2 PROGRAM
COMPLETE" for the closing summary.

---

## EPIC P — Tiered fingerprints & pluggable extractors

The surface fingerprint is one opaque `sha256[:16]` that sees signatures
(user-guide) and +docstrings (eng-guide) but **not implementation/body changes**,
and extraction is hardcoded to Python `ast`. This epic adds a pluggable extractor
seam, makes the fingerprint *tiered* (signature / docstring / body), and anchors
managed regions to symbol identity. Every step is additive and holds the
user-guide signature-hash bytes constant (K3); the body tier is opt-in
(`MonitorConfig.fingerprint_body_tier`, default OFF) so stored fingerprints stay
valid until a deliberate re-baseline.

**P1 — Extractor protocol + flag-gated body-AST dimension**
- ✅ **P-01** `extract.py`: (a) an `Extractor` Protocol + language-keyed registry,
  with the existing Python AST extractor as the default behind the seam (pure
  refactor, byte-identical); (b) an opt-in `Symbol.body_hash` body-AST tier folded
  into `surface_hash(*, include_body=...)` as an additive key — byte-invisible when
  OFF, NEVER applied to user-guide. *Goal:* OFF → frozen golden `surface_hash` for
  both audiences; ON → an eng-guide body-only change moves the hash while the same
  user-guide change does not; body hash insensitive to comments/formatting/docstring
  (K10). Flag threads identically through drift/heal/layout/monitor (one-shared-truth).
  See `.project/slices/P-01.md`.

**P2 — Tiered fingerprint structure + which-tier-moved reporting**
- ✅ **P-02** `SurfaceFingerprint` (per-tier `signature`/`docstring`/`body` digests
  + `composite`); `DocumentSurface.fingerprint(*, include_body)` whose `composite`
  IS the unchanged `surface_hash()` identity (no re-baseline); per-tier digests
  stamped ADDITIVELY in `cdm.fingerprint_tiers` (composite stays in `cdm.fingerprint`).
  `drift.detect` reports `Drift.drifted_tiers` (which tier moved; () fallback for an
  old doc); `ReviewRecord.drifted_tiers` (additive) → `schema_version` → `1.1.0`.
  Heal/layout stamp both from one `fingerprint()` call (one-shared-truth). See
  `.project/slices/P-02.md`. *(1354 passed, 97.44% branch; dogfood check+lint exit 0.)*

**P3 — Additional extractors via the protocol**
- ✅ **P-03** symbol extraction routes through the P-01 registry by language:
  `_symbols_for_ref` → `get_extractor(_symbol_language(ref)).extract(...)` (the
  hardcoded Python path is gone); `register_extractor(ext, *, suffixes=...)`
  self-maps `suffix → language` for `lang: auto`; `CodeRef.lang` opened to `str`
  (back-compat loosening). A new language is a registration, NEVER an engine edit —
  proven by a test-registered non-Python stub extractor (explicit + auto-suffix
  resolution, unknown → `ExtractionError`), zero engine change. See
  `.project/slices/P-03.md`.

**P4 — Anchors (region ⇄ symbol identity)**
- ✅ **P-04** `extract.anchor_id(name)` + `Symbol.anchor_id` (sha256[:16] of the
  qualified name, lineno-free → stable across a code move); heal/layout stamp
  `cdm.region_anchors[id]` (additive) for the symbol-table region; `drift.detect`
  adds `Drift.anchors_added`/`anchors_removed` on a HASH drift — an EMPTY delta =
  same symbol identities (a move/reorder or an internal change, re-bind; combine
  with P2 `drifted_tiers` to see "body changed"), a nonempty delta = a symbol
  added/removed/renamed. Pre-P4 docs (no stored anchors) → empty delta. See
  `.project/slices/P-04.md`. **EPIC P COMPLETE.**

**P5 — Additional real extractors behind the proven seam**
- ✅ **P-05** the FIRST real, production-registered non-Python extractor:
  `extract.ShellExtractor` (`language="shell"`) parses sh/bash function defs —
  `name() {…}` and `function name {…}` — via the stdlib `re` module ONLY (no heavy
  dep → core dep surface unchanged, offline gate intact; K0/K4). Each def →
  `Symbol(kind="function", signature=f"{name}()", is_public=leaf-name rule,
  docstring=leading `#` comment block (shebang excluded), brace-matched span,
  body_hash=None)`; pure & import-free (read as text, never sourced). Registered by
  DEFAULT (`register_extractor(ShellExtractor(), suffixes=(".sh", ".bash"))`), so a
  `.sh`/`.bash` ref with `lang: shell` OR `lang: auto` resolves it with ZERO engine
  edit (`_symbol_language`/`_symbols_for_ref`/`build_document_surface` untouched —
  the K0 proof). K3 holds e2e: eng-guide folds the comment docstring in, user-guide
  drops `_`-helpers + excludes docstrings. See `.project/slices/P-05.md`.
  *(1390 passed, 97.48% branch; dogfood check/lint/coverage --fail-under 95 exit 0.)*

**EPIC P COMPLETE** (P-01…P-05). The opaque single-hash, Python-only fingerprint is
now a pluggable, tiered, anchored model — every step additive and holding the
composite (`surface_hash`) bytes constant so no stored `cdm.fingerprint` was
invalidated: **P-01** seam (`Extractor` Protocol + registry) and opt-in body-AST
tier; **P-02** structured `SurfaceFingerprint` (signature/docstring/body +
composite) with which-tier-moved reporting and the `schema_version` 1.1.0 bump;
**P-03** symbol extraction routed through the registry by `CodeRef.lang` (a new
language is a registration, not an engine edit — K0); **P-04** stable lineno-free
`anchor_id`s recorded per region so drift tells a structural symbol add/remove/
rename from an internal (body/docstring) change; **P-05** the first REAL non-Python
extractor (`ShellExtractor`, stdlib-regex sh/bash) registered by default — proving
a new language is a registration, not an engine edit (K0). A shell body tier, real
heavy parsers (tcl/tree-sitter), and `lines`-ref re-binding remain follow-on
registrations behind the now-proven seam.

---

## Dependency order (high level)

```
A (coverage) ─┐
B (authority) ─┼─> C (PR loop) ──> G (deploy)
              │
D (feedback) ─┴─> E (server+DB) ──> F (dashboard) ──> H (self-improve)
```

A and B are local and foundational — start there. D's schema edit (D-01) can land
early in parallel. E/F/G/H follow once the local engine is coverage-aware and
authority-aware. Detailed slice specs are written **just-in-time** (a few ahead
of execution) in `.project/slices/<ID>.md`, not all up front — later slices
depend on earlier lessons.
