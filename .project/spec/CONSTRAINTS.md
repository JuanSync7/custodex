# code-doc-monitor — binding constraints

These are non-negotiable rules every slice must uphold. Numbered for citation in
tickets, commits, and the STATUS log.

- **K0 — Standardized & reusable.** Nothing about any specific target codebase
  (helium, genbuild, …) may be hard-coded in the engine. All target knowledge
  enters through the config. The package depends only on `pydantic`, `typer`,
  `pyyaml` (plus dev tools).
- **K1 — Detect-only `check`.** `cdmon check` and the `drift` module never mutate
  files or call a backend. Detection is pure and side-effect free.
- **K2 — Single source of truth = the code.** A document's machine-managed
  regions and fingerprint are derived from the extracted surface, never the
  other way round. The doc is graded against the code, not vice-versa.
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
  a `schema_version`; fields are additive across versions. `cdmon schema` emits
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
