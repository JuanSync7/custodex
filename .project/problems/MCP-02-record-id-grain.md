# MCP-02 — known limitation: `record_id` is per-review-record, not per-drift

## What

`schema.new_record_id(doc_id, surface_hash, detected_at)` derives a `ReviewRecord`'s
id from the DOCUMENT's surface hash + the run's injected stamp. So when one document
has more than one drift in a single run — the everyday case of a public-signature
change that drifts BOTH the surface fingerprint (`HASH`) and a managed region
(`REGION`) — every one of that doc's drifts gets the **same** `record_id`. The
`.cdmon/review-log.jsonl` then holds multiple lines with an identical id, and
`reviewlog.resolved_index` (keyed purely on `record_id`) maps them to one
resolution.

`cdx resolve <id>` and `custodex_resolve(record_id=…)` therefore both act at the
**review-record grain**: resolving one of a doc's simultaneous drifts marks them all
resolved. This is a pre-existing engine property (not introduced by MCP-02); the
mock/real backend usually proposes a whole-doc `FIX` for a `HASH` drift that heals
the whole doc anyway, so in the common flow the coarser grain is harmless.

## Why MCP-02 did not "fix" it

The MCP-02 adversarial review flagged this HIGH because `custodex_remediate`'s
docstrings over-claimed a 1:1 per-drift FK. The **in-scope** fix was to make the
contract truthful (the `record_id` is per-review-record; `drift_kind`/`region_id`
disambiguate the facets) + a pinning test `len({it.record_id}) == 1` for two
same-doc items. Re-deriving `new_record_id` to include `drift.kind`/`region_id` — so
each drift gets a distinct id — is the "correct at the source" fix BUT is a
cross-cutting change to the audit-record IDENTITY: it touches `monitor`, `reviewlog`,
the central server's dedup, and the `similar.py` learning loop, and would invalidate
every existing record id. That belongs to its own engine ticket with a K6
breaking-vs-additive review, not a tool slice (K9: additive, focused).

## The fix, if ever wanted

Add `drift.kind` + `drift.region_id` to `new_record_id`'s hash inputs (stays
deterministic, K10) so each handled drift on a doc gets a distinct id; then
`custodex_resolve`/`cdx resolve` become genuinely per-drift. Gate it behind a schema
version bump and migrate/accept old ids. Until then, per-drift resolution is not
available and the MCP contract says so honestly.

See the MCP-02 STATUS row + `LESSON_LEARNT.md [MCP-02]`.
