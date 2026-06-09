# code-doc-monitor — EPIC-2 vision

`vision_version 1.0.0` — builds on the finished EPIC-CDM (CDM-00..11). This is
the second program: turn the local drift monitor into a **lossless, self-closing,
centrally-observable** code↔doc system that can be deployed into any repo and
that keeps improving *itself*.

## The eight pillars

1. **Lossless coverage / "basket" (EPIC A).** Enumerate *every* code file and
   public symbol in a repo and sort each into a basket: **documented** (owned by
   ≥1 logical document), **waived** (explicitly ignored, with a reason), or
   **undocumented** (a coverage gap). Coverage % is computed and can be gated
   toward 100%. The config gains a `coverage:` section that is the **index
   between code and docs** — the unmapped basket lives there, in the open.

2. **Region authority: human ⊕ llm ⊕ generated (EPIC B).** Each managed region
   declares a `mode`:
   - `generated` — pure projection of code (symbol table / index / fingerprint).
     Healed mechanically, **no LLM**. The engine owns it; humans must not edit it.
   - `llm` — prose the model authors and re-proposes when the code it describes
     drifts.
   - `human` — a human writes it. The engine only *flags* drift (advisory),
     **never overwrites**. This is "let me choose how to write this section".
   - `llm-seeded` — the model drafts it once; the first human edit (detected by a
     content hash diverging from the last generated body) **locks** it to
     `human`. Best of both: a fast first draft, then human ownership.
   Bytes outside markers are always pure human prose (K7).

3. **Mechanical vs LLM healing.** A doc change is *mechanical* (free, deterministic,
   runs on every commit) when it is a pure projection of code — that is what
   `generated` regions and the fingerprint are. It needs the *LLM* only for
   meaning-shaped prose (`llm`/`llm-seeded`), `UNHEALABLE` regions, and
   `INVALIDATE`/`ESCALATE` judgment. Tiering the loop this way is what stops it
   being expensive or exponential.

4. **PR-driven loop (EPIC C).** The trigger boundary is **a commit that passed
   CI**, not a filesystem change. On merge to the default branch, a post-merge
   job runs `monitor --apply` and opens a **separate docs PR** ("code change →
   doc change", clean and simple). Loop safety is structural: doc-only commits
   (touching the heal output paths) are excluded from re-triggering, and heal is
   idempotent (K7). A human merges the docs PR — the human gate sits exactly
   where prose correctness matters.

5. **Feedback edge & learning substrate (EPIC D).** Today the review log is
   write-only audit. Add an **outcome edge** (additive to the versioned schema,
   K6): when a human accepts / overrides / rejects a proposed fix, record it.
   Then (a) **retrieve** the N most-similar past resolutions as few-shot
   exemplars for the agent backend, and (b) **promote** recurring
   drift-shape→identical-resolution patterns into deterministic rules — so the
   LLM is removed from that path and the system's cost curve bends *down* as it
   learns.

6. **Central server + DB (EPIC E).** code-doc-monitor reports records to a
   central service (it already has the `HttpSink` seam and a versioned schema).
   The service owns a database of repos, records, outcomes, and coverage
   snapshots — one place to see every code↔doc sync it monitors.

7. **Web dashboard (EPIC F).** One UI over the DB: per-repo drift, actions, logs,
   status, coverage, and health metrics (MTTR, escalation/override-rate trends).

8. **Self-improvement of the monitor itself (EPIC H).** "Self-improving" here
   means **code-doc-monitor improves code-doc-monitor** — telemetry shows which
   prompts/rules underperform; lessons-learnt become regression tests; it
   dogfoods its own growing codebase toward 100% coverage. Surfacing items back
   to a *monitored* repo (e.g. opening a gap issue) is a welcome secondary
   output, not the definition.

   Deployability (EPIC G) makes pillars 6–8 real for *other* repos: a single
   `cdmon init --central <url>` drops the client into any codebase.

## Non-negotiables carried forward

All of K0–K10 (see CONSTRAINTS.md) still bind. New constraints introduced by
this program are appended there as **K11+** by the slice that first needs them
(e.g. "the central server shares the ONE versioned schema; no hand-written
DTOs"). Offline-by-default and test-first remain absolute: the server and
dashboard are tested with in-process test clients and fixtures, never a live
network or a real LLM in the default suite.
