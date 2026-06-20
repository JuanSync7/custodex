# Slice OWN-03 — `cdmon ownership` CLI (read-only)

The offline, demonstrable surface: list per-doc ownership and flag orphans without
a server.

## Goal (validable)
```
cdmon ownership [--config DIR] [--roster roster.yaml] [--json] [--fail-on-orphan]
```
1. With no `--roster`: prints a per-doc owner table (doc_id, audience, accountable,
   owner/team/dri), exit 0.
2. With `--roster roster.yaml` (offline `identities: [...]`): also runs
   `detect_orphans` and prints findings; `--fail-on-orphan` ⇒ exit 1 iff any orphan.
3. `--json` emits a stable JSON object (`{owners: [...], findings: [...]}`).
Pure + offline (K1/K4) — no backend, no network.

## Design
- `ownership.py`: `load_roster(path) -> RosterSnapshot` (read a YAML
  `identities: [{name, kind, active, ...}]`; loud `ConfigError`/typed error on
  malformed input, K8). Build `unit_owner` map from the bundle's unit frontmatters.
- `cli.py`: new `@app.command() def ownership(config, roster, as_json,
  fail_on_orphan)` mirroring the `coverage`/`trace` command shape (`_resolve_config`,
  `_known_*` helpers, typer.Option). Pure rendering helper in `ownership.py`
  (`render_ownership_text(owners, findings) -> str`) so the CLI stays thin and the
  render is unit-tested.

## Test plan (TDD red-first)
- `tests/unit/test_ownership.py`: `load_roster` happy + malformed (loud);
  `render_ownership_text` byte-stable.
- `tests/system/test_cli.py` (or `test_ownership_cli.py`): CliRunner — no-roster
  table; roster+orphan findings; `--fail-on-orphan` exit code 1; `--json` shape;
  loud on a bad config.

## Dogfood
`cli.py` is tracked → reheal `docs/api/*` (the cli api doc HASH/REGION). Add
**FEAT-OWNERSHIP-004** (the CLI) to the catalog + DEMOS case + tagged test;
`cdmon wiki`; `cdmon trace --fail-on-gap` exit 0.

## Constraints
K1 (read-only), K4 (offline), K8 (loud on bad config/roster), K9, K10 (stable JSON).
