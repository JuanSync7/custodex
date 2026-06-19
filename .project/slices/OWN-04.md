# Slice OWN-04 — server roster + ownership mirror (migration 0006, admin token, routes)

The central mirror: mark a person departed once, see orphans across every repo.
Store-parity (InMemoryStore + SqlStore), offline SQLite + `pg` twin.

## Goal (validable)
1. Migration `0006_roster_and_ownership.py` creates `roster` + `ownership_mirror`;
   `alembic upgrade head` is idempotent on both SQLite and Postgres.
2. Store Protocol gains (BOTH impls, parity-tested): `upsert_identity`,
   `list_roster`, `mark_identity_departed(name, *, at)`,
   `replace_ownership_mirror(repo_id, sync_kind, entries)`,
   `ownership_mirror_for`, `set_admin_token_hash`, `admin_token_hash`.
3. Routes: `POST /admin/roster` + `POST /admin/roster/{name}/departed` (admin
   token, 401 missing / 403 wrong); `GET /roster` (open); `GET /repos/{id}/ownership`
   (open) returns `{owners: [...], findings: [...], orphan_count: N}` computed by
   `detect_orphans(mirror, roster)`.
4. `configsync._build_rows` carries owner/team/dri into `ConfigDocument`; the
   `/sync` route upserts the ownership mirror after a successful sync.
5. Marking the accountable owner of a synced repo departed ⇒ that repo's
   `GET /ownership` shows the doc as an orphan (the cross-repo cascade).

## Design
- `db.py`: `RosterRow` (id, name unique+indexed, kind, active, identity JSON),
  `OwnershipMirrorRow` (id, repo_id+doc_id+sync_kind indexed, owner/team/dri/
  accountable, synced_at, entry JSON). Admin token: reuse `RepoRow`? No — a single
  global row; add `admin_token_hash` via a tiny `MetaRow`(key,value) or a dedicated
  column on a singleton. Pick `MetaRow` (key='admin_token_hash') — generic + future
  global settings.
- `store.py`: `ConfigDocument` += owner/team/dri (additive); reuse `ownership.Identity`
  as the roster model; `OwnershipMirrorEntry` model. Protocol + InMemoryStore impls.
- `app.py`: `_verify_admin_token(store, authorization)` mirrors `_verify_token`
  against `store.admin_token_hash()` (set from `$CDMON_ADMIN_TOKEN` in
  `create_app`/`store_from_env`); the 4 routes; the `/sync` mirror upsert.

## Test plan (TDD red-first)
- `tests/integration/test_db.py` (+ `pg` twin): the 7 new store methods over
  InMemoryStore AND SqlStore (parity); migration up/down; idempotent re-upsert.
- `tests/integration/test_server.py`: admin auth (missing/wrong/right); roster CRUD;
  `/ownership` computed view; the departed-owner cascade; open vs protected routes.

## Dogfood
`server/*`, `configsync.py`, `store.py`, `db.py` tracked → reheal `docs/api/*`.
Add **FEAT-OWNERSHIP-005** (roster mirror tables/migration), **-006** (admin-token
roster routes), **-007** (computed `/ownership` view + cascade) to the catalog +
DEMOS cases + tagged tests; `cdmon wiki`; `cdmon trace --fail-on-gap` exit 0.

## Constraints
K0 (`[server]` extra, lazy), K4 (offline SQLite default; `pg` opt-in), K5 (orphan
recorded), K6 (additive fields/routes/migration), K8 (loud auth), K9, K10
(insertion-order/sorted, injected `at`).
