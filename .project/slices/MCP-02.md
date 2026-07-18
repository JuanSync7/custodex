# MCP-02 — the gated write tools (`custodex_remediate` · `custodex_resolve` · `custodex_sync_docs`)

**Epic:** MCP (the Model Context Protocol read/write surface)
**Depends on:** MCP-01 (the seven read tools + enriched `custodex_status`, merged PR #25)
**Constraints:** K0, K1, K4, K5, K7, K8, K10, K11

## Goal (validable)

Expose Custodex's three WRITE seams as curated MCP tools so an MCP client can
propose, resolve, and preview doc fixes through the standard protocol — WITHOUT
ever mutating a doc it was not explicitly told to. Every write is gated: a per-call
`apply: bool = False` (advisory by default, K11) AND a per-server `read_only`
switch that refuses to mount the write tools at all. Each tool drives an EXISTING
engine seam (`Monitor.run`, `reviewlog.append_resolution`, `syncpr.sync_pr`) — no
re-implemented remediation/resolution/diffing. This is where the user's
"chain custodex's agents" idea lands: `custodex_remediate` IS the remediation
pipeline exposed as a tool, and the orchestrating client is the chain. Full gate
green.

**Done when:**
- `custodex/mcp/tools.py` gains the three pure helpers pinned in
  `ARCHITECTURE §EPIC MCP → MCP-02` (`remediate_drift`/`resolve_drift`/
  `sync_docs`) + their frozen `extra=forbid` result models (`RemediationItem`/
  `RemediationResult`/`ResolutionResult`/`SyncDocsResult`). Each MUTATES via the
  existing seam; the clock is INJECTED (`now: str`), output SHAPED + CAPPED, a
  failed write is LOUD (K8 — never the read overview's honest-partial degrade).
- `custodex/mcp/server.py` registers the three `@server.tool()` wrappers, GUARDED
  by `if not read_only:`; `build_mcp_server` gains `*, read_only: bool = False`;
  `custodex_resolve`'s `resolution` param is typed as the `Resolution` enum
  (schema-advertised). `cdx mcp-serve` gains `--read-only`.
- Unit tests (pure layer, no `mcp`) prove: `apply=False` records but never mutates
  a doc; `apply=True` heals; `resolve_drift` validates record-id + resolution
  loudly; `sync_docs` dry-run leaves the tree byte-identical AFTER; determinism
  under fixed `now`; caps/truncation. Smoke tests: the three tools registered +
  invoked, the `resolution` enum reaches the schema, and `read_only=True`
  registers ONLY the 8 read tools.
- FEAT-MCP-001 catalog prose updated to name the write tools (no new FEAT id, no
  new demo/trace tag — DEMO-112 already tags it). `tools.py`/`server.py` stay
  coverage-waived (edits, not new files); the `mcp` package stays ~100%.
- `ruff format --check` · `ruff check` · `mypy custodex` · `pytest --cov` (≥90,
  mcp package ~100) all clean; `cdx check` / `index --check` / `wiki --check` /
  `trace --fail-on-gap` all green; a core-only import stays extra-free (K0).

## Design (per-tool)

See `ARCHITECTURE §EPIC MCP → MCP-02 — the gated write tools` for the pinned
signatures, models, and the ⟨R⟩ decisions. The load-bearing ones:

1. **Two-layer gate (K11).** Per-call `apply=False` passed THROUGH EXPLICITLY
   (`Monitor.run(apply=apply)`, never `apply=None`) so a repo's `apply_default:
   true` can NEVER be triggered by a remote agent; per-server `read_only=True`
   omits the write tools entirely (an operator's provable no-write guarantee).
2. **The K5 audit write is unconditional and intended.** `Monitor.run` appends one
   `ReviewRecord` per handled drift on EVERY call; only `apply_fix` (triple-guarded
   by `apply and verdict is FIX and fix is not None`) touches a doc. So
   `apply=False` records the proposals (the suggestion made auditable, K5/K11)
   without mutating a doc. The record write is NOT idempotent (`record_id` embeds
   `now`) — documented in the docstring; the pure "what is drifted?" question is
   `custodex_drift` (K1), a different verb.
3. **`now` injected; backend from config (mock offline default, K4/K10).** Helpers
   take `now: str`, build `Monitor(now=lambda: now)`; a live-backend config still
   calls the model even at `apply=False` (dry-run stops applies, not proposes).
4. **Loud, never degraded (K8).** A bad record-id / resolution / config surfaces a
   typed `McpError`/`CodeDocMonitorError`; a write NEVER silently half-degrades.

## Non-goals (later slices)

- Exposing `cli.resolve`'s `--edge` (doc↔doc baseline re-stamp) as a tool — record
  mode only for now.
- The live-MR transport (`open_docs_pr` / GitLab-GitHub) — `sync_docs` returns the
  patch shape only; the MR bot stays CLI/CI. Additive later.
- Streamable-HTTP on the hub — MCP-03. SDK v2 — MCP-04.

## Test plan (TDD)

- **unit** `tests/unit/test_mcp_tools.py`: per helper on a drifted fixture repo
  (mock backend). `remediate_drift`: `apply=False` → verdicts + records written but
  doc bytes UNCHANGED (read the doc before/after); `apply=True` → doc healed,
  `applied` set, a second run clean (K7); `record_id`↔handled join; capped
  `fix_preview` + `fix_truncated`; deterministic under fixed `now`.
  `resolve_drift`: happy path appends a `ResolutionRecord` joinable by
  `resolved_index`; unknown record-id → `McpError`; bad resolution string →
  `McpError` listing the four choices; `resolved_at == now`. `sync_docs`: dry-run
  returns a non-empty patch on a drifted repo yet the tree is byte-identical AFTER
  (incl. a `MISSING_DOC` stub deleted); `apply=True` leaves the heal; clean repo →
  empty patch + `clean`; `patch_truncated` under a tiny `patch_limit`. Import only
  `custodex.mcp.tools` (proves K0 — no `mcp`).
- **smoke** `tests/smoke/test_mcp_server.py`: the three tools registered + invoked
  via `call_tool` (tolerant unpack); `custodex_resolve` advertises the `Resolution`
  enum in `inputSchema`; a `read_only=True` server registers ONLY the 8 read tools
  (the three write names ABSENT). `importorskip("mcp")`.
- **system** `tests/system/test_mcp_cli.py` (if present): `cdx mcp-serve
  --read-only` reaches the same builder with `read_only=True`; per-tool behaviour
  is a smoke concern.

## Reheal order (DoD)

`(no new file — no waivers) → cdx index (if unit change) → cdx monitor --apply →
cdx check → cdx wiki → cdx trace → ruff/mypy/pytest`. Run `cdx wiki` LAST of the
generators (it indexes test functions — adding a test after a wiki regen stales
`TEST_WIKI.md`).
