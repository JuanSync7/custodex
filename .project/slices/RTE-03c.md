# RTE-03c — the restraint: `--tiered` never writes a document that needs intent

**Epic:** RTE (the apply-tier router)
**Depends on:** RTE-03b (`mechanical_docs`) — merged
**Constraints:** K5, K6, K7, K8, K9, K11
**Status:** DONE

## Goal (validable)

**Strictly safer than today, shippable alone, with no engine-authored write
anywhere in the slice.** `--tiered` confines `--apply` to the documents the ENGINE
alone could close. A document carrying any drift that needs human intent is still
sent to the backend — the reviewer gets a `ReviewRecord` with both the drift and a
proposed fix (K5) — but nothing on it is written.

### The bug, reproduced before and after

Against a backend that FIXes the mechanical HASH and ESCALATEs the prose (exactly
what a real LLM does when it will not invent a WHY):

```
BEFORE (--apply)                          AFTER (--apply --tiered)
HASH   -> FIX      applied=True           HASH   -> FIX      applied=False
REGION -> ESCALATE applied=False          REGION -> ESCALATE applied=False
remaining: []                             remaining: [HASH, REGION, REGION]
NEXT CYCLE: clean — no drift detected     NEXT CYCLE: 3 drift(s) detected
                                          routing: 0/1 mechanical, 1 need human intent
```

A human was asked to author that prose. Applying its sibling's mechanical fix
stamped `cdm.fingerprint`, and for a no-renderer `mode: llm` region that stamp is
the **only** staleness trigger it has (`drift.py` gates it on `stored != current`).
So `cdx check` was green forever and the human was never asked again — the exact
inversion of "nothing is missed".

**Done when:** `MonitorConfig.apply_tiered` (+ index mirror + merge lift) ·
`Monitor.run(*, apply=None, tiered=None)` · `cdx monitor --tiered/--no-tiered` ·
the knob passed EXPLICITLY at every non-CLI call site · full gate green · four
configs clean.

## Design

⟨R-CORRECTED⟩ **`--tiered` is NOT a subset of `--apply`, and an earlier draft of
this epic claimed it was — in six places.** It is a REPLACEMENT of authority on the
mechanical path and a RESTRAINT everywhere else. Reproduced against a backend that
declines:

```
--apply            backend verdict=['INVALIDATE']  WROTE=False
--apply --tiered   backend verdict=['FIX']         WROTE=True
```

Held documents are strictly narrower (nothing is written where `--apply` would apply
a backend FIX). Mechanical documents are DIFFERENT: no backend is consulted at all,
so a backend that would have declined never gets the chance. That is the epic's
thesis working as designed — on the CODE_DERIVED path there is no model judgement to
defer to — but it means an adopter whose backend is deliberately conservative can see
`--tiered` write where `--apply` did not. Default OFF, and stated rather than claimed
away. K3 is not at risk: it is enforced upstream in the fingerprint, so a user-guide
never gets a HASH drift for a docstring/private change in the first place.

It is OFF by default, so the slice is additive (K6).

⟨R⟩ **The write gate is per-DOCUMENT and the fold is computed ONCE**, from the
opening report, so it is a property of the run rather than of the write order.

⟨R⟩ **No new exit code.** A held document still exits 1 through the pre-existing
remaining-drift gate (`cli.py`), already pinned by
`test_monitor_no_apply_leaves_drift`. A second `typer.Exit` would be redundant, and
claiming "exit 0 under `--tiered`" would be a K9 regression.

⟨R⟩ **The knob must be passed EXPLICITLY off the CLI.** `tiered=None → config`
mirrors `apply`, but that convenience is a hole: **every call site that omits the
argument opts in by omission**, and six do. MCP-02 ratified the opposite rule in
writing for `apply`, and `server/app.py` loads the config of a CLONED, untrusted
repo — an adopter's config must not decide the server's authoring authority.
`sync_pr` gains an explicit `tiered: bool = False` (covering `sync-pr`,
`open-docs-pr`, the server route and MCP `sync_docs` in one place); MCP
`remediate` forces it OFF; `onboard`'s arrive-green forces the FULL apply. A
**source-level** guard asserts no `Monitor.run(apply=...)` elsewhere omits
`tiered=`, because a leak is invisible at runtime — the call simply inherits.

⟨R⟩ **The suspect-link edge baseline is a deliberate carve-out.** `stamp_edges`
writes a held document's `cdm.upstream_hashes` even under `--tiered`. Kept, because
it touches neither a managed region nor `cdm.fingerprint` and so destroys no
code↔doc staleness trigger — establishing a baseline is not blessing a change.
RTE-01's "never calls `apply_fix`" is true but is NOT "never writes"; pinned by a
byte-level test so the difference is explicit rather than accidental.

⟨R-LEARNED⟩ **The first fixture was wrong in an instructive way.** It wrote only a
COMPOSITE `cdm.fingerprint`, so the HASH graded `UNKNOWN` → `NEEDS_INTENT` and the
"mechanical" foil was held for the wrong reason. Fixed by stamping the doc through
`regenerate_regions`, i.e. the state a real run leaves it in.

## Tests

6 monitor tests (held / recorded-anyway + MCP lockstep / mechanical foil /
default-off / config-knob resolution / never-writes-without-apply) · 3 leak tests
(sync_pr defaults off, sync_pr CAN opt in, the source-level gate) · 1 suspect-link
carve-out · 3 CLI tests · 1 config merge-lift class guard · 1 corpus guard.

## Mutation verification (ralph loop) — 7/7 killed, 0 survivors

| # | mutation | killed by |
|---|---|---|
| P1 | drop the tiered write gate | 6 tests |
| P2 | route per-DRIFT instead of per-DOCUMENT (the blessing returns) | 4 tests |
| P3 | fold over `auto_routable_docs` instead of `mechanical_docs` | 9 tests |
| P4 | ignore the config knob | `test_tiered_defaults_to_the_config_knob` |
| P5 | `sync_pr` inherits the config knob (the leak) | the leak test |
| P6 | the merge lift dropped | the config guard |
| P7 | `--tiered` wired to a constant (dead flag) | the CLI test |

## EPIC-R

**FEAT-MONITOR-010**, **FEAT-MONITOR-011**, **FEAT-CLI-023**,
**FEAT-CONFIGV2-018** + **DEMO-123/124/125**; `cdx trace --fail-on-gap` 266/266.
