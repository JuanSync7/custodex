# Slice OWN-00 — EPIC OWN plan & pin (ownership & accountability)

The planning slice for EPIC OWN: peg a **human (or team)** to every monitored
document so a code→doc drift always has an accountable owner, and a person leaving
can never silently leave a document ownerless. This slice pins the design — it
ships **no engine code** (docs only), so the gate is unaffected.

## Goal (validable)
`.project/spec/ARCHITECTURE.md` carries the full EPIC OWN section (pinned
signatures for `ownership.py`, the config fields, the `ReassignOwnerEdit`, the
server roster/mirror + migration 0006 + admin token + routes, the CLI, the
frontend page, the demo); `.project/spec/CONSTRAINTS.md` K2 gains the scope note
(ownership = config-as-truth per K0, orthogonal to K2); slice specs OWN-01..OWN-06
exist; STATUS.md carries the EPIC OWN planning row. `ruff/mypy/pytest` untouched
(no code changed).

## The two-tier design (the load-bearing decision)
- **Ownership-of-record = per-repo config (TRUTH).** `DocumentSpec.owner/team/dri`
  (additive, K6). Own by **team** with a person as the current **DRI** so a
  departure demotes to "DRI vacant" (soft), not "orphaned". This is K0 (config is
  the entry point), explicitly **not** a K2 inversion.
- **Central roster = mirror.** Identities + active/departed status live centrally;
  marking one person departed cascades orphan detection across every repo. Disk =
  truth, SQL = mirror (the EDITOR contract reused).
- **Orphan = a drift-shaped signal**, surfaced through the existing
  issues/ReviewRecord vocabulary; never healable (no code change fixes it) —
  resolved by **reassignment** (`ReassignOwnerEdit` → generate-to-disk).

## Central Postgres — confirmed already working (no new infra needed)
`store_from_env()` → `$CDMON_DATABASE_URL` → Alembic `upgrade head` → `SqlStore`;
the offline SQLite twin runs the SAME migrations (`render_as_batch=True`); the
`pg`-marked suite is the real-Postgres twin. EPIC OWN adds migration `0006` (two
tables) and keeps the store-parity suite green on both backends.

## Slice map (each: TDD red-first, full gate green, STATUS row + LESSON)
| slice | scope | new catalog features |
|-------|-------|----------------------|
| OWN-01 | `DocumentSpec.owner/team/dri` + serialization round-trip + `ownership.resolve_ownership` + `Identity`/`RosterSnapshot`/`EffectiveOwner` | FEAT-OWNERSHIP-001/002 |
| OWN-02 | `ownership.detect_orphans` + `OwnershipFinding`/`OwnershipStatus` | FEAT-OWNERSHIP-003 |
| OWN-03 | `cdmon ownership` CLI (read-only) + offline roster-file loader | FEAT-OWNERSHIP-004 |
| OWN-04 | server roster + ownership mirror + migration 0006 + admin token + 4 routes (store parity, `pg` twin) | FEAT-OWNERSHIP-005/006/007 |
| OWN-05 | `ReassignOwnerEdit` + `config.set_document_owner` + generate dispatch | FEAT-OWNERSHIP-008 |
| OWN-06 | demo roster (with a departure) + demo config owners + Ownership frontend page + e2e | FEAT-OWNERSHIP-009/010 |

Catalog entries are added **in the slice that also adds their demo + test tag** so
`cdmon trace --fail-on-gap` / `cdmon wiki --check` stay green throughout (never
add a feature ahead of its evidence).

## Out of scope (whole epic, v1)
Code-ref-level direct ownership (covered transitively via code→doc→human);
staleness/SLA (`detect_stale` seam pinned, deferred — needs a `last_reviewed`
field); auto-emitting GitLab/GitHub orphan issues via the PR transports (the
`/ownership` view + `cdmon ownership --fail-on-orphan` are the v1 surfaces);
real OIDC/JWT admin auth (a hashed global token is the v1).

## Constraints
K0 (config is the only ownership entry point; core stays pydantic/typer/pyyaml),
K1 (`cdmon ownership` + `detect_orphans` are pure/read-only), K2 (scope note),
K4 (offline default — roster is a file/InMemoryStore offline; `pg` opt-in),
K5 (orphans are recorded, reassignment is the human-in-the-loop fix),
K6 (every new field/route additive), K10 (sorted, clock injected).

## Records to update
ARCHITECTURE.md (done — EPIC OWN section), CONSTRAINTS.md K2 (done), this slice
set, STATUS.md EPIC OWN row. LESSON_LEARNT.md entries per slice as they teach.
