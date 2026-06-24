# custodex — EPIC-2 execution process (binding)

How every vertical slice is built. The **main agent is the orchestrator**; each
**vertical slice is executed by one subagent** with a lean, isolated context.

## The slice contract (Definition of Done)

A slice is DONE only when ALL hold:

1. **Test-first (TDD).** Tests are written *before* the implementation and fail
   for the right reason first.
2. **Validable goal met.** The slice's one-line *Goal* (from ROADMAP.md) is
   demonstrably true via an automated assertion — not prose.
3. **Test layers present** (as applicable to the slice):
   - *unit* — pure functions / single module;
   - *integration* — module-to-module seams;
   - *system / e2e* — the CLI or server exercised end to end on a real fixture;
   - **real example fixtures** — concrete, realistic inputs (a fixture repo, a
     real config, a real doc), never only toy stubs.
4. **Gate green** (the repo-wide validation command):
   ```bash
   .venv/bin/ruff format --check .
   .venv/bin/ruff check .
   .venv/bin/mypy custodex
   .venv/bin/pytest -q --cov=custodex --cov-branch
   ```
   ruff + mypy clean; suite green; coverage ≥ 90% (the `fail_under` gate).
5. **Constraints upheld.** All of K0–K10 (CONSTRAINTS.md). If a slice needs a new
   binding rule, it appends it as **K11+** to CONSTRAINTS.md in the same slice and
   cites it.
6. **Dogfood re-healed.** Any change to a tracked module drifts `docs/api/*`;
   run `cdx monitor --apply --config config/cdmon` (cdmon's canonical
   self-config is the CONFIG-V2 dir layout since Z-02 removed the redundant root
   `cdmon.yaml`; `--config` may be omitted — it auto-detects) so `cdx check`
   and `cdx lint` exit 0 before claiming done. (See the dogfood-reheal memory.)
7. **Records updated.** The subagent appends:
   - a STATUS.md row (slice, status, evidence, notes);
   - a LESSON_LEARNT.md entry **whenever** something was non-obvious, a limitation
     was found, or a good practice emerged — write these freely, they are how the
     *next* subagent avoids the same wall;
   - if it discovered a hard problem or known limitation, a
     `.project/problems/<slice>.md` note describing it for future slices.

## The Ralph loop (per slice)

The subagent runs a tight loop until the gate is green:

```
read slice spec + relevant seams
  └─> write a failing test for the next increment
        └─> run the gate (or the focused test)
              └─> implement the minimum to pass
                    └─> run the gate ──(red)──> fix ──┐
                          │                            │
                        (green) ──> next increment ────┘
  └─> when the Goal's assertion + full gate are green ──> write records ──> DONE
```

If a subagent stops before the gate is green, the orchestrator **re-dispatches it
to continue** (the loop resumes from the working tree). A slice is not done on a
subagent's say-so — only on a green gate the orchestrator verifies.

## Just-in-time slice specs

Detailed specs live in `.project/slices/<ID>.md`, written by the orchestrator a
few slices ahead — NOT all 40+ up front (later slices depend on earlier
lessons). Each spec has: Goal (validable), in-scope modules/signatures, test plan
(the layers above), constraints to cite, and explicit out-of-scope.

## Architecture changes

New module signatures go into ARCHITECTURE.md **before** the slice implements
them (the EPIC-CDM discipline: pin the contract so slices compose without
integration drift). Changing an existing public signature is deliberate and
documented, never incidental.

## Orchestrator (main agent) rules

- **One slice in flight per dependency chain.** Independent slices (e.g. A-01 and
  D-01) may run in parallel subagents; dependent ones are sequenced.
- **Verify, don't trust.** After a subagent returns, the orchestrator runs the
  gate itself (or inspects evidence) before marking the slice ✅ in STATUS.md and
  ROADMAP.md.
- **Context hygiene / `/compact`.** When the orchestrator's context exceeds
  ~200k tokens, it `/compact`s (work continues from the summary — slices are
  self-contained in their specs + STATUS/LESSON, so nothing is lost).
- **Keep subagents lean.** Give each subagent only its slice spec, the seams it
  touches, and pointers to PROCESS/CONSTRAINTS — not the whole history.

## Subagent kickoff checklist (what every slice subagent is told)

1. Read: this PROCESS.md, your `.project/slices/<ID>.md`, CONSTRAINTS.md, and the
   specific source/test files named in your spec.
2. Run the gate once to confirm a green baseline before you start.
3. TDD the slice in the Ralph loop above.
4. Re-heal the dogfood; confirm `cdx check` + `cdx lint` exit 0.
5. Run the full gate; paste the evidence.
6. Append STATUS row + LESSON entries (+ a problems note if warranted).
7. Report back: what changed, the gate evidence, and anything the next slice
   should know.
