# Slice MCP-00 — `custodex/mcp/`: the Model Context Protocol server skeleton

The first vertical slice of the MCP read/write surface: an external agent
(Claude Code / any MCP client) can launch `cdx mcp-serve` in a repo and call one
real tool, `custodex_status`, to ask "is this repo in sync?". Proves the whole
transport end-to-end — the opt-in `[mcp]` extra, lazy import, config loading,
FastMCP tool registration, and shaped output — with the full gate green. Pinned
contract: `ARCHITECTURE.md` §EPIC MCP.

Why MCP over agent-to-agent chaining (the design question that opened the epic):
the surface survey proved NONE of Custodex's agents are conversational — every
one is a pure function or a single-turn `Backend.propose(FixRequest) ->
BackendResult` (the LangGraph remediation graph is "fully deterministic; the
only non-determinism is the driver"). There is no conversational agent to chain
*to*; the orchestrating MCP client IS the chain. So Custodex capabilities are
exposed AS curated MCP tools, reusing the engine's pure detectors — the MCP
layer never re-implements detection (K1/K2).

## Goal (validable)

1. `[mcp]` optional-dependency (`mcp>=1.8,<2` — the last v1 line; a v2 rework
   lands ~2026-07-28, pinned out until MCP-04) declared in `pyproject.toml` and
   duplicated into `[dev]` so the gate exercises it; `cdx-mcp` entry point; a
   `mcp.*` mypy `ignore_missing_imports` override (the `uvicorn` precedent).
2. `custodex/mcp/` subpackage mirroring `custodex/server/`: `__init__.py` states
   "importing THIS subpackage requires the `mcp` SDK ([mcp] extra); the core
   engine never imports it" (K0) and re-exports `build_mcp_server`. `import
   custodex` pulls in nothing from here.
3. `class McpError(CodeDocMonitorError)` in `errors.py` — a missing config/extra
   is loud (K8), the `SpMirrorError`/`BackendError` precedent.
4. `custodex/mcp/tools.py` (PURE — core deps only): `load_repo_bundle(repo_root)
   -> (MonitorConfig, config_dir)` resolving `config/cdmon/index.yaml` then
   `cdmon.yaml`, loud `McpError` if neither; `StatusSummary` pydantic model
   (`extra=forbid`, frozen); `status_summary(cfg, config_dir) -> StatusSummary`
   that runs `Monitor(cfg, config_dir).check()` (the SAME detect `cdx check`
   runs) and projects the `DriftReport` into counts. No clock, no mutation, no
   network (K1/K4/K10).
5. `custodex/mcp/server.py`: `build_mcp_server(repo_root) -> object` builds a
   `FastMCP("custodex")` (lazy `from mcp.server.fastmcp import FastMCP`) and
   registers `custodex_status` as a thin wrapper that RELOADS the bundle per call
   and returns `status_summary(...).model_dump(mode="json")` (shaped output). A
   `main()` entry point for `cdx-mcp`.
6. `cdx mcp-serve [--repo-root .]` — lazy in-body `from .mcp import
   build_mcp_server` with `try/except ImportError -> Exit(1)` + "install
   custodex[mcp]" (K8), then `_run_mcp(server)  # pragma: no cover` = the stdio
   transport leaf (`server.run()`), so all logic stays in the import-safe
   builder + pure tools and tests NEVER open a transport (the `_run_uvicorn`
   precedent).

## In scope

**New `custodex/mcp/{__init__,tools,server}.py`**; `custodex/errors.py`
(`McpError`); `custodex/cli.py` (`mcp-serve` + `_run_mcp`); `pyproject.toml`
(`[mcp]` + `[dev]` + entry point + mypy override). Tests:
`tests/unit/test_mcp_tools.py` (pure `status_summary`/`load_repo_bundle`) +
`tests/smoke/test_mcp_server.py` (`build_mcp_server` registers the tool,
`importorskip` the SDK, no socket). `docs/api/mcp.md` (dogfood doc for the new
module, born-in-sync).

## Out of scope (recorded follow-ons)

- Every tool beyond `custodex_status` — the read tools are **MCP-01**, the
  gated write/agentic tools **MCP-02**.
- The `_run_mcp` transport leaf is `# pragma: no cover` (K4 — a real transport
  binds stdio; the builder + tools carry the tested logic).
- A `doctor._check_mcp_extra` — deferred until there is an MCP config presence to
  gate it on (an always-on check would churn every repo's `doctor` output for no
  trigger); the CLI's K8 install hint already covers discoverability.
- Streamable-HTTP-on-the-hub (**MCP-03**) and the SDK v2 migration (**MCP-04**).

## DoD bundle

- `feature-doc/catalog/mcp.yaml` (FEAT-MCP-001) + a DEMOS.md case (next free
  DEMO id) + `Feature:`/`Features:` tags in both test modules; `cdx trace
  --fail-on-gap` green.
- `docs/api/mcp.md` born-in-sync (dogfood); `cli.py`/`errors.py` are tracked →
  `cdx monitor --apply` reheal; `cdx wiki` regen; README one-liner.
- Coverage: `custodex/mcp/` referenced by `docs/api/mcp.md` code_ref OR waived
  in `config/cdmon` (the SP-01 choice was a real doc — mirror it).
- Full gate: `ruff format --check`, `ruff check`, `mypy custodex`, `pytest ≥90`
  branch, `cdx check`, `cdx index --check`, `cdx wiki --check`, `cdx trace
  --fail-on-gap`. Verified BOTH with the `[mcp]` extra (real FastMCP) AND without
  (the smoke test skips; `import custodex` + core gate stay mcp-free).
- STATUS.md row + a LESSON_LEARNT entry if the slice teaches one.
