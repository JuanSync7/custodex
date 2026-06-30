# EPIC B — Pillar B: document↔document dependency mapping + suspect-link drift

**Goal.** Give Custodex the one pillar it lacks (per `.project/COMPETITORS.md`): a
doc can declare it *depends on* another doc, and when the upstream changes the
downstream is flagged **suspect** until a human re-confirms it. Adopt the proven
Doorstop model (two separate fingerprints; per-edge human ack) and the ALM
"suspect link" semantics — **without** inventing a new drift model.

**Design north star — kill the tedium (the Jama lesson).** The reason ALM
traceability tools become shelfware is hand-authoring and hand-maintaining links.
So Pillar B must make the human job *approve, not author*:
- **Don't make people draw the graph by hand.** `cdx deps --suggest` infers edges
  from the relative Markdown links docs already contain between each other, and
  prints ready-to-apply config — author→approve, like the rest of Custodex.
- **One-command authoring + baseline.** `cdx link DOWN UP` adds the edge to config
  (K2 source of truth) and stamps the baseline in one step.
- **One-command resolution.** `cdx resolve --edge DOWN UP` re-stamps exactly one
  edge after review (the Doorstop `clear` analogue) — never re-bless the whole doc.
- **Loud but not noisy.** Suspect links are audience-scoped (K3) and gating is a
  config knob (`docdeps.gate`) — default gating (Custodex fails CI on drift,
  unlike Doorstop which exits 0), but tunable.
- **Nothing hardcoded.** Every behaviour — enable, gate, default edge type,
  link-inference — is a `docdeps:` config block; no literals in the engine.

## Constraints honoured
- **K0** core-only: `docdeps.py` is pure stdlib + pydantic, no new dependency; the
  server `doc_edges` mirror is behind the `[server]` extra.
- **K1** `cdx check`/`drift`/`detect_suspect_links` are **detect-only** — no file
  write, no backend. Stamping is only in the mutation commands (`link`, `resolve`,
  `monitor --apply`).
- **K2** config is the source of truth: the **edge declaration** lives in
  `DocumentSpec.depends_on` (config); the **baseline stamp** lives in the
  downstream doc's `cdm.upstream_hashes` front-matter (machine-managed, exactly
  like the existing `cdm.fingerprint`). The DB `doc_edges` table is a rebuildable
  mirror, never truth.
- **K3** a suspect link carries the downstream doc's audience.
- **K5** every handled suspect produces a `ReviewRecord` (drift + the upstream
  change) and a per-edge `ResolutionRecord` on ack — the anti-rubber-stamp trail.
- **K6** every model field / config key / DB column / schema is **additive**; old
  configs, docs, and records validate unchanged (no `depends_on` ⇒ no Pillar B).
- **K7** idempotent: re-running with no upstream change re-stamps nothing and
  records nothing; a no-op `monitor` is a no-op.
- **K8** loud: an edge to an unknown doc id, a self-edge, or a duplicate edge is a
  `ConfigError` at load.
- **K10** deterministic: the upstream fingerprint is a normalized `sha256[:16]` of
  the upstream **body** (not its churny front-matter); all outputs sorted; no clock
  in the pure core (timestamps injected).

## Sub-slices (each independently validable; TDD test-first)

- **B-01 config models.** `DocEdgeType`, `DocEdge`, `DocDepsConfig`;
  `DocumentSpec.depends_on`; `MonitorConfig.docdeps`; validators (unknown-id /
  self-edge / duplicate-edge are loud); YAML round-trip in `_document_to_yaml`.
  *Validable:* a config with `depends_on` loads, round-trips byte-stable, and a bad
  edge raises `ConfigError`.
- **B-02 manifest stamps.** `stored_upstream_hashes` / `set_upstream_hash` /
  `drop_upstream_hash` under `cdm.upstream_hashes` (additive; survives a fingerprint
  heal because `set_fingerprint` copies the whole `cdm` map).
  *Validable:* round-trip + survives `set_fingerprint`.
- **B-03 docdeps pure core.** `upstream_fingerprint`, `SuspectStatus`,
  `SuspectLink`, `detect_suspect_links`, `infer_edges_from_links`,
  `render_deps_text`. *Validable:* unit tests for OK / SUSPECT / UNSTAMPED /
  MISSING_UPSTREAM and the link-inference scan; fully pure.
- **B-04 drift integration.** `DriftKind.SUSPECT_LINK`; `detect()` appends
  suspect-link drifts (healable=False) when `config.docdeps.enabled`.
  *Validable:* `detect()` reports a suspect link after an upstream edit; suppressed
  when `enabled=False`.
- **B-05 CLI.** `cdx deps` (graph + suspect view), `cdx deps --suggest`
  (link-inference → paste-ready config), `cdx link DOWN UP` (config write +
  baseline stamp), `cdx resolve --edge DOWN UP` (per-edge re-stamp + ResolutionRecord),
  and `cdx check`'s exit honours `docdeps.gate`. *Validable:* CLI tests for each.
- **B-06 monitor + records.** A SUSPECT_LINK produces a `ReviewRecord`; an
  UNSTAMPED edge is baselined by `monitor --apply` (a one-time "establish baseline"
  with a record); re-run is a no-op (K7). *Validable:* monitor test.
- **B-07 server mirror.** `doc_edges` table + Alembic `0007`; `configsync` projects
  every edge (both directions materialized for O(1) reverse lookup); store methods
  + `GET /repos/{id}/doc-graph` read-time route; Store-parity over InMemory + Sql.
  *Validable:* store-parity + route tests over both stores.
- **B-08 e2e + dogfood + catalog + demo + frontend.** Add real `depends_on` edges
  to this repo's own `config/cdmon` (dogfood) + reheal; `feature-doc/catalog` entry
  + `Feature:` tags on a demo + a test so `cdx trace --fail-on-gap` stays green;
  enrich `demo/` with a doc↔doc edge; a light frontend "Dependencies" view; one
  end-to-end test (declare → upstream change → suspect → resolve → green). Update
  `scripts/seed_demo.py` / `scripts/demo_as_git.py` as needed. *Validable:* the
  full gate + `cdx trace` green.

## The two-fingerprint model (the Doorstop lesson, made Custodex-native)
- The downstream doc already carries its **own** code↔doc identity in
  `cdm.fingerprint` (P-tier). Pillar B adds, in the SAME front-matter, a per-edge
  map `cdm.upstream_hashes: {<upstream_id>: <hash-of-upstream-body>}`.
- `detect_suspect_links` recomputes each upstream's body hash and compares to the
  stored stamp: equal ⇒ OK; differ ⇒ SUSPECT; absent ⇒ UNSTAMPED; upstream file
  gone ⇒ MISSING_UPSTREAM.
- `cdx resolve --edge` re-stamps exactly that one upstream's hash (the per-edge ack),
  leaving the doc's own `cdm.fingerprint` and sibling edge stamps untouched.
