# code-doc-monitor — tickets

Each slice is TDD (tests before code), leaves ruff+mypy clean and the suite
green (≥90% coverage, K9), and implements its modules' contracts from
ARCHITECTURE.md exactly. Cite constraints (Kn) in the STATUS evidence.

## CDM-00 — bootstrap  ✅
Skeleton, venv, tooling, `.project` specs. Goal: tooling green + smoke test.

## CDM-01 — config + init
`errors.py`, `config.py`, `cdmon init`.
Goal: `load_config` reads a YAML *and* a JSON config into `MonitorConfig`;
unknown/invalid fields raise `ConfigError` (K8); `write_template`/`cdmon init`
emit a documented `CONFIG_TEMPLATE` that itself round-trips through
`load_config`. Tests: valid yaml, valid json, bad path, malformed body, template
round-trip, defaults.

## CDM-02 — extract
`extract.py`. Goal: `extract_file` returns Symbols from AST (functions/classes/
methods/module-vars) with signatures + public flag + docstring; 
`build_document_surface` applies the audience filter (K3) and sub-file selection
(symbols/lines/names); `surface_hash` is stable (K10) and *does not move* for a
user-guide when only a comment/docstring/private symbol changes, but *does* move
for an eng-guide. Tests cover each selector, both audiences, and hash stability.

## CDM-03 — drift + heal
`manifest.py`, `blocks.py`, `drift.py`, `heal.py`. Goal: parse docs with
`CDM:BEGIN/END` regions + front-matter fingerprint; `detect` reports
MISSING_DOC/HASH/REGION/UNHEALABLE with correct `healable` + `audience`; a
comment-only change drifts an eng-guide doc but not a user-guide doc; `apply_fix`
/`regenerate_regions` are idempotent (K7) and touch only managed regions. `check`
path is side-effect-free (K1).

## CDM-04 — schema + reviewlog + sinks
`schema.py`, `reviewlog.py`, `sinks.py`. Goal: `ReviewRecord` with
`schema_version` (K6); `review_record_schema()` returns valid JSON Schema;
append/read round-trips JSONL; `summarize` counts by verdict/audience/doc;
`NullSink`/`FileSink` work offline, `HttpSink` constructed but never called in
tests (K4). Timestamps injected (K10).

## CDM-05 — backends
`backends.py`. Goal: `make_backend` resolves kind→backend; `MockBackend` is
deterministic (user-guide comment-only→INVALIDATE, healable region→FIX,
else→ESCALATE); `ClaudeCodeBackend` builds a prompt and runs an injected
subprocess runner, parsing the JSON verdict contract; `ApiBackend` uses an
injected HTTP client. No network/LLM in tests (K4). Shared `build_prompt` is
audience-aware.

## CDM-06 — monitor + cli
`monitor.py`, `cli.py`. Goal: `Monitor.run` does detect→backend→record→sink→
(apply)→recheck with injected backend/sink/now; `MonitorResult` exposes handled/
remaining/records; full `cdmon` CLI (init/surface/check/monitor/report/schema)
with correct exit codes. Integration tests with the mock backend, offline.

## CDM-07 — e2e + dogfood + docs
System tests on a fixture repo (shared files → user-guide + eng-guide docs)
proving the audience-split acceptance from SPEC; dogfood: a `cdmon.yaml` mapping
code-doc-monitor's own source onto its own docs, exercised in tests; ≥90%
coverage; README + a generated schema doc; STATUS/LESSON finalized.

## CDM-08 — document layout standard + lint
`docs/LAYOUT_STANDARD.md`, `layout.py`, `cli.py` (+`config.py`/`manifest.py`).
Goal: standardize the *file structure* of managed .md (and derived .html) docs —
one canonical skeleton (front matter → title → purpose → prose → CDM:BEGIN/END
regions), one marker grammar (helium's AUTOGEN markers as a documented alias),
the managed front-matter schema (schema_version/audience/fingerprint), and the
html-twin pairing rule (1:1 path, embedded body hash, derived-not-edited) —
**machine-checked** by `cdmon lint [--fix]` (orthogonal to `check`) and
scaffolded by `cdmon new-doc`. Pure linter; offline; dogfood docs conform.
