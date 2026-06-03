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
  `api` (Anthropic API). Selected entirely by config.
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
8. **Backend-agnostic** — switching `claude-code` ↔ `api` ↔ `mock` is a config
   edit, no code change.
9. **Offline-testable** — the default backend and central sink are offline; the
   whole pipeline (incl. `monitor`) runs in CI with zero network and no LLM.
10. **Dogfooding** — code-doc-monitor ships a config that maps *its own* source
    onto *its own* docs, and that config is exercised in the test suite.

## CLI surface (`cdmon`)

| command | does |
|---|---|
| `cdmon init [--path cdmon.yaml]` | write a config template |
| `cdmon surface [--config ...]` | dump the extracted per-document surface (debug) |
| `cdmon check [--config ...]` | detect drift; exit non-zero on drift (warn) |
| `cdmon monitor [--config ...] [--apply/--no-apply]` | detect → backend verdict → record → (apply) → re-check |
| `cdmon report [--config ...]` | summarize the review log |
| `cdmon schema [--out FILE]` | emit the public review-record JSON schema |

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
