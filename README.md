# code-doc-monitor

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

Write one config (`cdmon.yaml`) that maps groups of code files — down to
functions, line ranges, or variables — onto **logical documents**, each tagged
with an **audience**:

- `user-guide` — only the externally-visible surface matters; comment / local /
  private changes are *invalidated* (not drift).
- `eng-guide` — the implementation surface matters too; those changes *are*
  flagged.

```bash
cdmon init                 # write a config template
cdmon new-doc <doc-id>     # scaffold a conformant, in-sync doc from config + code
cdmon surface              # dump the extracted per-document surface (debug)
cdmon lint [--fix]         # validate doc *structure* (Layout Standard); --fix stamps front matter
cdmon check                # detect *content* drift; non-zero exit on drift (the warning)
cdmon monitor --apply      # detect → LLM verdict → record → apply fix → re-check
cdmon report               # summarize the review log
cdmon schema               # emit the public ReviewRecord JSON schema
```

## Document Layout Standard

Beyond keeping content in sync, code-doc-monitor standardizes **how a managed
doc is written** so every adopting project lays its docs out the same way: a
canonical skeleton (front matter → `#` title → `>` purpose → prose →
`CDM:BEGIN/END` regions), a managed front-matter schema
(`cdm.schema_version` / `audience` / `fingerprint`), and an HTML-twin pairing
rule (`X.md` → `X.html`, derived-not-edited, carrying an embedded source hash).
helium's `HELIUM:AUTOGEN … START/END` markers are a documented alias of the same
grammar. The standard is **machine-checked** — `cdmon lint` is a structure gate
orthogonal to `check`'s content gate (run both in CI) — and `cdmon new-doc`
scaffolds a conformant file. See [`docs/LAYOUT_STANDARD.md`](docs/LAYOUT_STANDARD.md).

## Backends (pluggable, offline by default)

The LLM backend is chosen entirely by config:

- `mock` — deterministic, offline; the default, and what the test suite uses.
- `claude-code` — runs a headless `claude -p` session as a subprocess.
- `api` — calls the Anthropic Messages API.

Switching between them is a config edit, never a code change. The engine is
backend-agnostic: all three return the same `BackendResult` JSON contract.

## Public schema

Every handled drift becomes a versioned `ReviewRecord` (the public contract for
the central monitoring system). The JSON Schema is generated from the model —
`cdmon schema` — and a snapshot lives at
[`docs/REVIEW_RECORD_SCHEMA.json`](docs/REVIEW_RECORD_SCHEMA.json).

## Dogfooding

code-doc-monitor monitors **its own** source against its own engineering docs:
the shipped [`cdmon.yaml`](cdmon.yaml) maps this package's modules onto the docs
under `docs/api/` (with `schema.py` as a shared, multiply-referenced file). Run
`cdmon check` here to see it in action; the dogfood is asserted in
`tests/test_dogfood.py`.

## Status

**Complete.** All slices CDM-00…CDM-08 are done: config + audience-aware
extraction + drift detection + heal + public schema + review log + central sinks
+ pluggable backends (mock / claude-code / api) + the monitor orchestration and
`cdmon` CLI + the Document Layout Standard (`lint` / `new-doc`), with system/e2e
tests and dogfooding. The suite is offline (mock backend, no network), ruff +
mypy clean, coverage ≥ 90% (224 tests). See `.project/`
for the spec, the binding constraints (K0–K10), the architecture, and the
slice-by-slice status board.

## Development

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff format --check . && .venv/bin/ruff check .
.venv/bin/mypy code_doc_monitor
.venv/bin/pytest -q --cov=code_doc_monitor --cov-branch
```

### Testing against a real LLM (CI/CD)

The default suite is **offline** (K4): a bare `pytest` excludes the `live_llm`
marker, so it never spawns a model. One opt-in end-to-end test
(`tests/test_live_llm.py`) drives a **real** backend — resolved from a config
file exactly like production — and asserts `monitor --apply` self-heals a doc in
a single pass:

```bash
# backend.kind comes from the config the test writes (CDMON_LIVE_BACKEND)
CDMON_LIVE_LLM=1 CDMON_LIVE_BACKEND=claude-code .venv/bin/pytest -m live_llm
```

[`.gitlab-ci.yml`](.gitlab-ci.yml) wires this as a two-gate pipeline: `tests:offline`
runs on every push/MR, and `tests:live-llm` runs the real-LLM test on a schedule
(and on-demand), gated on an `ANTHROPIC_API_KEY` CI/CD variable. This guards a
real-vs-mock divergence the offline suite can't see: a live model may return a
fix that fills *both* the region and whole-doc shapes at once, so `apply_fix`
prefers the whole-doc text (the only shape that refreshes the fingerprint) to
keep `monitor --apply` single-pass idempotent.
