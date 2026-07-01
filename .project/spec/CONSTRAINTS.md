# custodex — binding constraints

These are non-negotiable rules every slice must uphold. Numbered for citation in
tickets, commits, and the STATUS log.

- **K0 — Standardized & reusable.** Nothing about any specific target codebase
  (helium, genbuild, …) may be hard-coded in the engine. All target knowledge
  enters through the config. The **core** package depends only on `pydantic`,
  `typer`, `pyyaml` (plus dev tools); the default `mock` path and the
  single-shot `claude-code`/`api` backends import nothing else. The LangGraph
  remediation agent (`backend.kind: agent`, the `custodex.agent`
  subpackage) is the one optional, opt-in extra: it adds `langgraph` under the
  `[agent]` extra and is imported lazily, only when that backend is selected, so
  installing without the extra leaves the core dependency surface intact.
- **K1 — Detect-only `check`.** `cdx check` and the `drift` module never mutate
  files or call a backend. Detection is pure and side-effect free.
- **K2 — Single source of truth = the code.** A document's machine-managed
  regions and fingerprint are derived from the extracted surface, never the
  other way round. The doc is graded against the code, not vice-versa.
  *Scope note (EPIC OWN):* K2 governs documentation **content** only. A document's
  **ownership metadata** — who is accountable (`owner`/`team`/`dri`) — is the one
  thing K2 does NOT govern: it is config-as-truth per K0 (it enters through
  `config/cdmon/*.yaml`, never inferred from code annotations), and the central
  server roster only MIRRORS it to flag departed owners. Grading doc *content*
  against code (K2) and pinning a *human* to a doc (config/K0) are orthogonal axes.
- **K3 — Audience changes the verdict.** The same raw code change can be drift
  for an `eng-guide` and a non-event for a `user-guide`. This rule lives in the
  surface filter (what is extracted) AND is passed to the backend (so it can
  INVALIDATE correctly). A user-guide must never be flagged for a comment-only
  or private/local change.
- **K4 — Backend is pluggable and offline by default.** The backend is chosen by
  config and resolved through one factory. The default is `mock` (deterministic,
  no network). Tests never hit a network or a real LLM; the `claude-code` and
  `api` backends are exercised only through mocked subprocess / HTTP.
- **K5 — Human stays in the loop.** Every handled drift produces a review record
  containing BOTH the original drift and the proposed fix; auto-apply is opt-in
  (`monitor --apply`), defaults to off-or-configured, and INVALIDATE/ESCALATE are
  always recorded, never silently dropped.
- **K6 — Public schema is versioned & stable.** The review-record schema carries
  a `schema_version`; fields are additive across versions. `cdx schema` emits
  it from the pydantic models (one source of truth — no hand-written schema).
- **K7 — Safe, idempotent fixes.** Applying a FIX touches only the document's
  managed regions / the file the verdict targets; re-running `monitor` with no
  code change produces no new changes and no new review records for already-clean
  docs.
- **K8 — Loud on malformed input.** A malformed config, an unreadable code ref,
  or a managed region with an unknown id raises a typed error
  (`CodeDocMonitorError` subclass) with a clear message — never a silent pass.
- **K9 — Additive, test-first.** Every slice is TDD (test before code), leaves
  ruff + mypy clean and the suite green, and only adds/ு extends — no slice
  breaks a previous slice's tests. Coverage ≥ 90% (the `fail_under` gate).
- **K10 — Determinism.** Hashes and serialized output are stable across runs
  (sorted keys, normalized whitespace, no wall-clock in hashes). Timestamps live
  only in review records and are injected, not read from the clock inside pure
  functions (so tests are reproducible).
- **K11 — Agents suggest; humans apply.** (Minted by EPIC AGT.) Any
  agent/worker-produced proposal — an inferred doc↔doc edge, a generated config
  plan, a doc draft, a fix/what-to-document suggestion — is **advisory data**
  carrying provenance (a tier/evidence trail, never a bare float) and a
  **deterministic, clock-free dedup key**, so re-running a suggester is
  idempotent (K7) and a re-staged suggestion never duplicates. A proposal never
  mutates config or documents except through an explicit, human-invoked apply
  command (`cdx link`, `cdx onboard --apply`, `cdx write-doc --apply`, …), and
  an applied proposal leaves the same audit trail as the equivalent human
  action. Background loops are thin impure adapters over pure, clock-injected
  tick functions (the `worklist_from_repo` pattern) — the loop leaf is the only
  uncovered line, exactly like a Driver/urlopen leaf (K4).
