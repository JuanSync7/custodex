# Slice OWN-06 — demo + Ownership frontend page + e2e (show it working)

Make the whole feature visible and clickable on the live :33333 demo.

## Goal (validable)
1. `demo/config/cdmon/*` docs carry real owners (a team + a DRI); committed, so
   every clone (and `demo_as_git`) has them.
2. `seed_demo.py` seeds a central roster (a team + ≥2 people) with **one person
   marked departed**, and upserts the ownership mirror — so the live Ownership page
   shows a genuine orphan, not an empty state.
3. Frontend: `GET /repos/:repoId/ownership` → `pages/Ownership.tsx` (a sibling tab
   in `RepoNav`), docs grouped by accountable owner with active/departed/orphan
   chips + an orphan banner; `OwnershipData`/`RosterPerson` types; `api.ownershipFor`.
4. e2e (`tests/system/test_demo_e2e.py` + `test_demo_gitsync_e2e.py`): the seeded
   app's `/repos/demo-taskflow/ownership` lists owners; after `POST
   /admin/roster/{name}/departed`, that person's docs appear as orphans.

## Design
- `seed_demo.py`: `_seed_roster(store)` (deterministic, uses the frozen `_NOW`),
  called in `build_seeded_store`; set the admin token; upsert mirror from the synced
  config.
- Frontend (Astro/React island, CI-Vitest but local `astro check`+`astro build`):
  thin page reading the COMPUTED `/ownership` payload (groupby + findings done
  server-side, OWN-04), following the Documents/Coverage page pattern; types.ts
  mirror; RepoNav entry.

## Test plan (TDD red-first)
- Python e2e as above (TestClient, InMemoryStore — no network, K4).
- Frontend: a `Ownership.test.tsx` (CI Vitest) + `client.test.ts` `ownershipFor`;
  locally gate on `astro check` + `astro build` (host load starves local Vitest).

## Dogfood
`seed_demo.py`/`demo_as_git.py` are scripts (not tracked-doc); demo config change
ripples the demo trace count (`cdx trace` over `demo/`). Add **FEAT-OWNERSHIP-009**
(demo roster + ownership view) + **FEAT-OWNERSHIP-010** (reassignment-clears-orphan
demo) to the catalog + DEMOS cases + tagged tests; `cdx wiki`; `cdx trace
--fail-on-gap` exit 0; demo 1:1 restored. Mark **EPIC OWN COMPLETE** in STATUS.

## Constraints
K4 (offline e2e), K5 (orphan visible, reassignment fixes it), K9 (full gate +
astro), K10 (deterministic seed via `_NOW`).
