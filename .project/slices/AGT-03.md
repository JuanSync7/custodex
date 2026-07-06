# Slice AGT-03 — `kgraph.py`: the unified knowledge-graph artifact + hub snapshot

Builds on AGT-01 (mentions) + AGT-02 (edges). One deterministic fold of the
edges Custodex already computes into a typed, provenance-tiered graph — base
facts only (the Glean split); every derived quantity (neighbors, centrality)
is recomputed, never stored. Repo-side computation, opaque snapshot to the
hub (the coverage-snapshot precedent — K2-safe: no doc-body text rides it;
SECTION names are slugs).

## Goal (validable)

On a fixture repo (2 docs with code_refs, 1 declared depends_on edge, prose
mentions incl. one unresolved, headings, an owner):
1. `build_graph` yields every expected node kind (DOC/SECTION/SYMBOL/OWNER —
   PATH/ENV_VAR/URL when mentioned) and every edge kind with the right tier:
   DOCUMENTS (declared — from code_refs), DEPENDS_ON (declared), MENTIONS
   (resolved), LINKS_TO (resolved), PART_OF (resolved), OWNED_BY (declared);
2. `unresolved` maps exactly the fixture's one unresolved-mention doc to 1;
3. rebuild is byte-identical (double-run JSON equality, K10);
4. `graph_neighbors` returns in+out edges for a focus node; loud K8 on an
   unknown id;
5. `rank_centrality(undocumented_only=True)` puts a fixture symbol that is
   mentioned twice but covered by no doc at the top;
6. `cdx graph --write` emits `.cdmon/graph.json`; second run byte-identical
   (K7); the file is gitignored;
7. hub: `POST /repos/{id}/graph` (token-gated per the E-06 matrix) stores the
   snapshot; `GET /repos/{id}/graph` returns it on BOTH stores (parity);
   Alembic 0008 up/down proven on temp SQLite;
8. one unparseable source file in the fixture → graph still builds, a warning
   is carried (the AGT-01 resilient registry).

## In scope

**New `custodex/kgraph.py`** — the pinned ⟨R⟩ contract: NodeKind/EdgeKind/
EdgeTier/GraphNode/GraphEdge/KnowledgeGraph (schema_version "1.0.0"),
`build_graph(config, root, *, unit_owner=None)` (folds: coverage join →
DOCUMENTS declared; docdeps → DEPENDS_ON declared; AGT-01 mentions →
MENTIONS/LINKS_TO/PART_OF resolved; ownership accountable projection →
OWNED_BY declared), `graph_neighbors`, `rank_centrality`,
`render_graph_text`.

**`custodex/cli.py`** — `cdx graph [--focus ID] [--rank] [--json] [--write]`
(read-only except --write which writes only `.cdmon/graph.json`).

**Server** (`custodex/server/store.py` + `db.py` + `app.py`):
`add_graph_snapshot(repo_id, snapshot: dict)` / `graph_for(repo_id)` on BOTH
stores (mirror the coverage-snapshot methods exactly); Alembic
`0008_graph_snapshots` (mirror `coverage_snapshots` table shape);
`POST /repos/{id}/graph` (token) + `GET /repos/{id}/graph` (open read);
parity tests via the test_server_store_parity client fixture.

**`.gitignore`** — `.cdmon/graph.json` (follow the coverage.json precedent).

## DoD bundle

- `feature-doc/catalog/kgraph.yaml` (FEAT-KGRAPH-001…): modules
  `[kgraph, cli, server]`; constraints K1/K2/K6/K7/K10/K11.
- Feature-tagged tests + DEMOS.md cases (next free ids).
- coverage.waive for `custodex/kgraph.py`; wiki regen.
- **cli.py + server/app.py are tracked** → reheal + commit rehealed docs;
  README prose line for `cdx graph`.
- Full gate + trace + parity (both stores) + Alembic up/down test.

## Test plan

- unit (`test_kgraph.py`): every fold rule, tiers, unresolved counts, slug
  names only (no raw heading text anywhere in the graph — assert), neighbors
  depth/loud, centrality ranking + undocumented_only cross, determinism.
- integration: build over a real tmp fixture repo; resilience (bad file).
- integration (`test_server_store_parity.py` additions): POST/GET graph on
  both stores + auth matrix + unknown repo 404; `test_db.py`: Alembic 0008
  up/down.
- system (`test_kgraph_cli.py`): --focus/--rank/--json/--write + idempotent
  rewrite + gitignore honored.

## Out of scope

Cross-repo graph fusion, graph diffing, BROKEN_REF as a gating DriftKind
(unresolved stays advisory data), any frontend work (AGT-07), LLM concept
entities, persistence of derived quantities.
