# Slice AGT-06 — `workers.py`: the two background suggesters

The "two running parallel in Custodex": a **fixes** suggester (what's broken /
suspect / promotable right now) and a **docs** suggester (what to document and
map next), each a PURE tick over the existing detectors (K1/K10) with a
default-OFF server loop (K4) — agents suggest, humans apply (K11). Pinned
contract: `ARCHITECTURE.md` §EPIC AGT `workers.py`.

## Goal (validable)

1. `SuggestionKind` = FIX_DRIFT / RESOLVE_EDGE (EVENT: key embeds the
   occurrence — surface hash / upstream fingerprint — so a recurrence AFTER a
   heal is a NEW key) + ADD_EDGE / DOCUMENT_GAP / PROMOTE_RULE (STANDING:
   occurrence-free key; dismiss = durable opt-out; ADD_EDGE honors the
   repo-side EdgeRejection file);
2. `Suggestion.key` = sha256[:16] over PINNED STRUCTURED FIELDS per kind —
   detail/evidence/severity/now EXCLUDED (a reworded detail keeps the key; a
   different occurrence changes it — regression-guarded);
3. `suggest_fixes_tick(config, config_dir, *, now)` — FIX_DRIFT (per drifted
   doc, SUSPECT_LINK excluded — RESOLVE_EDGE owns edges), RESOLVE_EDGE (per
   non-OK suspect link), PROMOTE_RULE (per detect_promotions candidate);
   `suggest_docs_tick(config, config_dir, *, now)` — DOCUMENT_GAP (per
   mentioned-but-undocumented ranked symbol), ADD_EDGE (per suggest_edges
   suggestion, rejections honored). Both PURE in the K1 sense (read-only FS,
   no clock — `now` is reserved for the stored envelope, never in a key),
   sorted by key;
4. `cdx suggest [--kind fixes|docs|all] [--json] [--write]` prints the CURRENT
   tick output (the inbox IS current reality); `--write` appends NEW keys to
   `.cdmon/suggestions.jsonl` — an append-only LOG (reviewlog precedent),
   never read back as pending state; second `--write` with no change appends
   nothing (K7);
5. Server: `WorkerSettings(enabled=False, interval_seconds=900, kinds)` under
   `ServerSettings.workers` + `CDMON_WORKER_*` env overlays; loops start via
   lifespan ONLY when enabled, in a daemon thread, `threading.Event.wait`
   shutdown (never a bare sleep), per-repo error isolation (one repo's tick
   failure logs and continues); a repo with no readable `local_path` config is
   skipped;
6. Store reconciliation, NOT insert-only: `sync_suggestions(repo_id,
   suggestions, *, now)` inserts new keys as `pending`, keeps existing,
   REOPENS a `resolved` key that reappears, marks non-dismissed keys absent
   from the tick `resolved` (kept for audit, excluded from the default read),
   and NEVER resurrects a `dismissed` key; `suggestions_for(repo_id, *,
   include_closed=False)`; `dismiss_suggestion(repo_id, key)`; BOTH stores +
   Alembic `0009_suggestions` (up/down proven); stored envelopes carry
   `source: "worker"` provenance;
7. Routes: `GET /repos/{id}/suggestions` (open read, `?include_closed=`) +
   `POST /repos/{id}/suggestions/{key}/dismiss` (repo token, E-06 matrix),
   parity over both stores.

## In scope

**New `custodex/workers.py`**; **`custodex/settings.py`** `WorkerSettings` +
env overlay; **`custodex/cli.py`** `cdx suggest`; **server**
store.py/db.py/app.py + `alembic/versions/0009_suggestions.py`.

## DoD bundle

- `feature-doc/catalog/workers.yaml` (FEAT-WORKERS-001/002) + DEMO-107/108.
- coverage.waive for `custodex/workers.py`; wiki regen; trace green.
- cli.py/settings.py/server/app.py tracked → dogfood reheal; README line.
- Full gate + parity + Alembic up/down; the thread leaf is the ONLY
  uncovered code.

## Test plan

- unit (`test_workers.py`): key discipline per kind (reworded detail → same
  key; healed-then-recurred drift → new key; standing keys occurrence-free),
  each kind fires on a fixture, SUSPECT_LINK exclusion, rejections honored,
  sorted-by-key determinism, double-run equality.
- unit (`test_settings.py` additions): defaults + CDMON_WORKER_* overlay.
- system (`test_suggest_cli.py`): text/json/write + append-only idempotency.
- integration (parity additions): sync/reconcile lifecycle (pending →
  resolved → reopen; dismissed never resurrects), routes + auth matrix,
  Alembic 0009 up/down; app-level worker-pass test over a tmp local repo +
  a lifespan arm/stop test with an injected pass counter.

## Out of scope

Server-side clone-on-demand ticks for git-only repos (workers read
`local_path` trees only — the GIT sync route materializes those), suggestion
PUSH ingest from repos, LLM-generated suggestion prose (K4), frontend
(AGT-07).
