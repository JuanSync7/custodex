# Slice OWN-02 — `ownership.detect_orphans` (pure orphan detection)

The clock-free half of accountability: given resolved ownership + a roster
snapshot, classify each document.

## Goal (validable)
`detect_orphans(owners, roster) -> tuple[OwnershipFinding, ...]` (pure, no clock,
sorted by doc_id, K10):
- a doc with no owner/team/dri anywhere ⇒ `UNOWNED`;
- `accountable` identity inactive AND no active `durable` fallback ⇒
  `ORPHAN_OWNER_DEPARTED`;
- `dri` inactive but `durable` (team/owner) still active ⇒ `ORPHAN_DRI_VACANT`
  (soft — the team still owns it);
- otherwise `OK` (OK findings omitted from the default result; an `include_ok`
  flag returns them for the full table).

## Design
`ownership.py`: add `OwnershipStatus` enum + `OwnershipFinding` model +
`detect_orphans(owners, roster, *, include_ok=False)`. Precedence is explicit and
table-tested. `RosterSnapshot.is_active(None)` is False, so an unknown owner name
(in roster but absent) is treated inactive ⇒ orphan (a name no roster knows is a
loud accountability gap, not silently OK — but distinguish UNOWNED = no name at all
from orphan = a name that's departed/unknown).

## Test plan (TDD red-first)
`tests/unit/test_ownership.py`: a table over (owner, team, dri, roster-states) ⇒
expected status, covering each branch + `include_ok` + sorted output + empty
inputs. Property-style: every input doc yields exactly one finding when
`include_ok=True`.

## Dogfood
`ownership.py` not tracked-doc yet (waiver). Add **FEAT-OWNERSHIP-003**
(orphan detection) to the catalog + DEMOS case + tagged test; `cdx wiki`;
`cdx trace --fail-on-gap` exit 0.

## Constraints
K1/K10 (pure, deterministic, no clock), K5 (orphan is a recorded signal, not a
silent drop), K8 (an unknown/departed accountable name is surfaced loud), K9.
