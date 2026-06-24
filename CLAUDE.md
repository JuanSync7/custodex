# CLAUDE.md

Guidance for Claude Code (and any AI agent) working in this repository. Read
`README.md` for the user-facing overview; this file is the operational contract
for *changing* the code.

## What this is

**Custodex** (`cdx`) is a standardized, reusable code-and-docs governance
monitor: it extracts a code surface, fingerprints it, detects drift against the
managed docs (code↔doc and doc↔doc), and — when drift is found — asks an LLM
backend to **fix or invalidate** it, recording every verdict as an auditable
`ReviewRecord`. It also pegs an accountable **owner** to every doc and tracks
**review SLAs** (staleness). It **dogfoods itself**: this repo's own engineering
docs under `docs/api/` are monitored against `custodex/**`.

## Naming (the rebrand)

The tool is **Custodex**; the CLI is **`cdx`** and the Python package is
**`custodex`** (`pip install custodex`, `import custodex`). `cdmon` /
`cdmon-server` are **deprecated aliases** kept working for back-compat — don't
remove them.

These `cdmon`-era **convention names are deliberately kept** (renaming them
breaks deployed adopters for no real gain) — do NOT "fix" them to `cdx`:
- the `config/cdmon/` config directory + the `cdmon.yaml`/`.json` single-file form,
- the `.cdmon/` runtime state directory (review log, resolutions, coverage manifest),
- the `cdmon-config-version` config-format key,
- the `CDMON_*` environment-variable prefix (tokens, DB URL, server tunables).

## The validation gate (run before declaring any change done)

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy custodex
.venv/bin/pytest -q --cov=custodex --cov-branch   # branch coverage, fail_under=90
```

All four must be clean. This is the same gate `.project/STATUS.md` records for
every slice. Install with `pip install -e '.[dev]'` (the `[dev]` extra pulls both
the `[agent]` and `[server]` extras so the gate exercises everything).

## The dogfood reheal rule (the #1 gotcha)

Editing any **tracked module** changes its extracted surface, which drifts the
matching `docs/api/*.md` doc — and the dogfood test (`tests/system/test_dogfood.py`)
will then fail. After changing a tracked module:

```bash
.venv/bin/cdx monitor --apply --config config/cdmon   # reheal the docs/api/* regions + fingerprints
.venv/bin/cdx check --config config/cdmon             # confirm 0 drift
```

Commit the rehealed docs alongside the code change. Which modules are tracked is
declared in `config/cdmon/*.yaml` (`code_refs`).

## Binding constraints (K0–K10)

Every change must uphold these (full text in `.project/spec/CONSTRAINTS.md`; cite
them in commits/PRs):

- **K0** — Standardized & reusable: no target-specific knowledge in the engine; it
  enters through config. The **core** depends only on `pydantic`, `typer`,
  `pyyaml`. `langgraph` (`[agent]`), `fastapi`/`sqlalchemy`/`cryptography`
  (`[server]`) are opt-in extras, imported lazily — a core-only install must stay
  minimal.
- **K1** — `cdx check` and `drift` are detect-only: pure, no file mutation, no
  backend call.
- **K2** — Single source of truth = the code; docs are graded against the surface,
  never the reverse.
- **K3** — Audience changes the verdict: a `user-guide` is never flagged for a
  comment-only / private / local change; an `eng-guide` is.
- **K4** — Backend pluggable, offline by default (`mock`). Tests never hit a network
  or a real LLM/DB.
- **K5** — Human in the loop: every handled drift produces a `ReviewRecord` with
  BOTH the original drift and the proposed fix; auto-apply is opt-in.
- **K6** — Public schema is versioned & additive; `cdx schema` emits it from the
  pydantic models (no hand-written schema).
- **K7** — Safe, idempotent fixes: re-running `monitor` with no code change
  produces no new changes/records.
- **K8** — Loud on malformed input: raise a typed `CodeDocMonitorError` subclass,
  never a silent pass.
- **K9** — Additive, test-first (TDD); leave ruff + mypy clean and the suite green;
  no slice breaks a previous slice's tests; coverage ≥ 90%.
- **K10** — Determinism: sorted keys, normalized whitespace, no wall-clock in
  hashes; timestamps are injected, not read from the clock inside pure functions.

## Repository layout

```
custodex/        the engine (one module per concern)
  cli.py                 the `cdx` Typer CLI (24 subcommands)
  config.py / _v2base.py / configsync.py   config models + config/cdmon loader + sync engine
  extract.py             AST/registry extraction → per-document surface (never imports the target)
  drift.py / blocks.py / manifest.py / heal.py   detect drift, manage regions/fingerprints, heal
  schema.py / reviewlog.py / sinks.py    ReviewRecord contract, JSONL log, central sinks
  backends.py / agent/   pluggable LLM backends + the LangGraph remediation agent ([agent])
  monitor.py             the detect→verdict→record→apply→recheck orchestrator
  coverage.py / inventory.py / srcindex.py / issues.py   doc-coverage + gap→issue
  similar.py / promotion.py   learning loop (few-shot exemplars + promotable rules)
  pr.py / syncpr.py      docs-PR loop (GitLab + GitHub transports)
  gitfetch.py / secrets.py / gitauth.py   server-side git sync: clone-on-demand, sealed creds, token minting ([server])
  featurecatalog.py / traceability.py / testwiki.py / wiki.py   EPIC R feature catalog + wikis
  layout.py / build.py / index.py / templates_v2.py / docstyle.py   Layout Standard + rendering
  server/                the central FastAPI app ([server]): app, store, db (SqlStore), edits, standalone
config/cdmon/            this repo's OWN config (dogfood): index.yaml + per-area unit files
docs/api/                dogfood-generated engineering docs (DO NOT hand-edit regions; reheal instead)
feature-doc/             EPIC R: catalog/*.yaml (source of truth) → FEATURES.md + wiki/* (generated)
frontend/                the single Astro app (console island at /, native wikis at /wiki/*)
templates/               adopter CI templates + writing templates
examples/                worked adopter (external-repo) + multi-language (multilang) examples
demo/                    an authentic standalone repo fixture (used by demo-as-git e2e tests)
tests/{unit,integration,system,smoke,regression}/   the suite (markers auto-applied by path)
.project/                the planning substrate — see below
```

## Config (`config/cdmon/`)

The canonical config form is the multi-file `config/cdmon/` directory (an
`index.yaml` frontmatter+globals file plus per-area unit files: `core.yaml`,
`agent.yaml`, `server.yaml`, …). A single `cdmon.yaml`/`.json` file is a supported
back-compat path (used by `examples/`). `cdx` auto-detects `config/cdmon/` with
no `--config`. After adding/removing unit files, run `cdx index` to regenerate
`index.yaml`'s `units:` list (`cdx index --check` is the CI guard).

## Do NOT hand-edit generated docs

- `docs/api/*.md` — dogfood-generated. Reheal with `cdx monitor --apply`; the
  prose blockquotes are human-maintained but the `CDM:BEGIN/END` regions and
  fingerprints are machine-managed.
- `feature-doc/FEATURES.md` and `feature-doc/wiki/*` — generated by `cdx wiki`
  from `feature-doc/catalog/*.yaml` + test docstrings + source. Edit the catalog
  yaml (the single source) and regenerate; `cdx wiki --check` is the CI gate.
- New feature? Add it to `feature-doc/catalog/<subsystem>.yaml` AND tag its demo +
  test with an inline `Feature: <FEAT-ID>` comment, or `cdx trace --fail-on-gap`
  will fail (it requires every feature to trace 1:1 to a demo and a test).

## Tests

The default suite is **offline** (K4): `pytest` excludes the `live_llm` and `pg`
markers. Tests live under `tests/{unit,integration,system,smoke,regression}/` and
markers are auto-applied by path (EPIC-R taxonomy). The `regression/` corpus is
one durable guard per learned failure mode (see `tests/regression/README.md`).
Opt-in suites: `-m live_llm` (real LLM), `-m pg` (real Postgres — the offline
suite runs the same store contract on stdlib SQLite).

## The `.project/` planning substrate

Planning and history live in `.project/`, not in the code:

- `spec/` — `SPEC.md`, `CONSTRAINTS.md` (K0–K10), `ARCHITECTURE.md` (module
  boundaries + exact signatures, pinned BEFORE implementation), plus `VISION.md`,
  `CONFIGV2.md`, `EDITOR.md`.
- `slices/` — one vertical slice spec per ticket (TDD, each with a validable goal).
- `STATUS.md` — **the live slice-by-slice status board** (the authoritative
  "what's done" record; far more current than any prose summary).
- `ROADMAP.md`, `LESSON_LEARNT.md`, `PROCESS.md`, `tickets/`, `problems/`.

When you finish a slice, add a row to `STATUS.md` and (if it taught something
durable) a `LESSON_LEARNT.md` entry. Pin new module signatures in
`ARCHITECTURE.md` before writing them.

## Conventions

- **Commits/PRs** use Conventional Commits with an epic scope, e.g.
  `feat(gitsync): …`, `docs(project): …`, `chore(frontend): …`.
- **Branch off `main`**; open a PR rather than pushing to `main` directly.
- **Frontend** (`frontend/`) is Astro + React islands; `astro check` and `astro
  build` are the type/build gates. Vitest is run in CI (host load can starve the
  local worker startup).

## Environment caveat (EDR-monitored host)

These hosts run CrowdStrike Falcon, which can **kill** `curl`/`wget` invocations
from the shell (even loopback) as suspected "malicious file download". Do **not**
use `curl`/`wget` for local health checks, HTTP probing, or smoke-testing a dev
server. Use an in-process method instead (Python `urllib.request` in a `python3
-c`, the app's own CLI/endpoints, or call the handler directly). The FastAPI
`TestClient` (used throughout the server tests) needs no socket. Reserve
`curl`/`wget` for genuine remote-file downloads, and say so explicitly.
