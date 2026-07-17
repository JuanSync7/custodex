# MCP-01 — the read tools + enriched `custodex_status`

**Epic:** MCP (the Model Context Protocol read/write surface)
**Depends on:** MCP-00 (skeleton + `custodex_status`, merged PR #24)
**Constraints:** K0, K1, K2, K3, K4, K6, K8, K10

## Goal (validable)

Expose Custodex's read detectors as seven curated MCP tools + enrich the
`custodex_status` overview, so an MCP client sees the whole 4-pillar health of a
local repo (drift · coverage · ownership · staleness/SLA · doc↔doc graph · audit
log) without shelling out to `cdx`. Every tool is the pure projection of a
detector `cdx` ALREADY runs (K1/K2 — no re-detection, no mutation), core-deps
only (K0), shaped + capped + deterministically sorted (K10), loud on bad input
(K8). Full gate green.

**Done when:**
- `custodex/mcp/tools.py` gains the eight pure helpers pinned in
  `ARCHITECTURE §EPIC MCP → MCP-01` (`status_summary` enriched;
  `drift_detail`/`coverage_summary`/`ownership_summary`/`staleness_summary`/
  `worklist_summary`/`doc_graph_summary`/`list_records`) + their frozen
  `extra=forbid` wrapper models, reusing `OwnershipFinding`/`StalenessFinding`/
  `SuspectLink` on the wire.
- `custodex/mcp/server.py` registers the seven new `@server.tool()` wrappers
  (reload bundle → resolve id → pure helper → `model_dump(mode="json")`) + a
  private `_now()` for the `now`-taking tools. No CLI change.
- Unit tests (pure layer, no `mcp`), smoke tests (`importorskip mcp`, tolerant
  `call_tool` unpack), and the MCP-00 smoke key-set assertion updated for the
  enriched `custodex_status`.
- FEAT-MCP-001 catalog prose updated to name the shipped tools (no new FEAT id,
  no new demo/trace tag — DEMO-112 already tags it). `tools.py`/`server.py` stay
  coverage-waived (edits, not new files).
- `ruff format --check` · `ruff check` · `mypy custodex` · `pytest --cov` (≥90,
  mcp package ~100) all clean; `cdx check` / `index --check` / `wiki --check` /
  `trace --fail-on-gap` all green.

## Design (per-tool)

See `ARCHITECTURE §EPIC MCP → MCP-01 — the read tools` for the pinned
signatures, models, and the three ⟨R⟩ decisions:
1. `custodex_*`-prefixed names (collision-safe in a multi-server client).
2. `now` injected at the `server.py` impure boundary (K10) — pure helpers never
   read a clock.
3. Local-only surface: orphan detection needs a `roster_path` (else
   `roster_checked=False`, honest partial); the doc-graph is richer locally than
   the hub (we hold the bodies → per-edge SUSPECT status, K2).

## Non-goals (later slices)

- Write/agentic tools (`remediate_drift`/`resolve_drift`/`sync_docs`) — MCP-02.
- The transitive-suspect advisory field on the doc graph — additive, later.
- Streamable-HTTP on the hub — MCP-03. SDK v2 — MCP-04.

## Test plan (TDD)

- **unit** `tests/unit/test_mcp_tools.py`: per helper — a clean/synced case and a
  drifted/gap/stale/suspect/unowned case; deterministic `now`; cap+truncation
  flags; `McpError` on a bad verdict string; empty-log `list_records`. Proves the
  K0 boundary by importing only `custodex.mcp.tools` (no `mcp`).
- **smoke** `tests/smoke/test_mcp_server.py`: each new tool registered +
  invoked via `call_tool` (tolerant tuple/list unpack); enriched
  `custodex_status` key-set. `importorskip("mcp")`.
- **system** `tests/system/test_mcp_cli.py`: unchanged — `cdx mcp-serve` reaches
  the same builder; per-tool behaviour is a smoke concern.

## Reheal order (DoD)

`(waivers if new file) → cdx index (if unit change) → cdx monitor --apply →
cdx check → cdx wiki → cdx trace → ruff/mypy/pytest`. Run `cdx wiki` LAST of the
generators (it indexes test functions — adding a test after a wiki regen stales
`TEST_WIKI.md`).
