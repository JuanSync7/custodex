# Slice AGT-02 — `docmap.py`: entity-based edge suggestions + the `cdx link` approve verb

Builds on AGT-01. Upgrades doc↔doc mapping from lexical link-inference to
entity-grounded suggestions with provenance tiers, and adds the missing ACCEPT
path (`cdx link`) so a suggestion becomes a declared edge without hand-editing
YAML. Everything advisory until the human applies (K11).

## Goal (validable)

Fixture: doc A's prose backtick-mentions symbol `S` (resolved by AGT-01); doc B
covers `S` via `code_refs`; doc C markdown-links doc B.
1. `suggest_edges` returns EXACTLY two suggestions: `C→B` tier RESOLVED_LINK
   (via the link) and `A→B` tier SHARED_SYMBOL with `S`'s entity id in
   `evidence` (score = 1);
2. after `cdx link A B` the `A→B` suggestion DISAPPEARS from a re-run
   (declared edges excluded) and `cdx deps` shows the edge with a stamped
   baseline (`cdx check` stays exit 0 — the fresh stamp is OK, K7);
3. a doc that mentions a symbol IT ALSO covers itself yields NO self-edge;
4. the same pair found by both rules yields ONE suggestion at the stronger
   tier (RESOLVED_LINK) with merged evidence;
5. with `docdeps.infer_from_links: true`, `cdx deps` appends the advisory
   suggestions section; with the default `false` it does not (byte-identical
   to today — K6).

## In scope

**New `custodex/docmap.py`** — the pinned contract: `SuggestionTier`
(RESOLVED_LINK > SHARED_SYMBOL), `ScoredEdge{doc_id, upstream_id, tier,
evidence, score}`, `suggest_edges(config, root)` (pure; unifies
`infer_edges_from_links` output as the RESOLVED_LINK feed + the entity rule:
downstream MENTIONS a symbol the upstream DOCUMENTS via the coverage join;
principled direction only, no guessing; declared/self/dup excluded; sorted),
`render_suggestions_text(edges)` (keeps the paste-ready YAML block + tier/
evidence lines), `declare_edge(config_dir, downstream_id, upstream_id, *,
type, now) -> Path` (the ONE writer: pure editor + `dump_unit_file`;
dir-layout only, loud otherwise — K8).

**`custodex/config.py`** — new pure editor
`add_doc_edge(unit: UnitFile, doc_id: str, upstream: str, *, type:
DocEdgeType = DocEdgeType.DEPENDS) -> UnitFile` (loud on unknown doc /
self-edge / duplicate edge, mirroring the DocumentSpec validators); round-trip
via the existing `_docedge_to_yaml`. ALSO: fix the `DocDepsConfig.
infer_from_links` docstring to describe the REAL behavior below (closing the
documented-but-unimplemented drift found in review).

**`custodex/cli.py`** —
- `cdx deps --suggest` now prints `suggest_edges` (tier/evidence lines added;
  `--json` items gain additive keys `tier`/`evidence`/`score`, bare-LIST shape
  preserved — K6). The old links-only output is a strict subset, so existing
  consumers see the same edges plus new ones.
- `cdx deps` (report): when `config.docdeps.infer_from_links` is true, append
  a clearly-labelled advisory suggestions section (never gates — K11).
- NEW `cdx link DOWN UP [--type depends|refines|implements|verifies]`:
  `declare_edge` then `stamp_edges(..., only=UP)` so the new edge is baselined
  (no immediate UNSTAMPED noise); prints the declared edge + stamp result.
  Loud on unknown ids / single-file config / already-declared (K8).

**Back-compat:** `docdeps.infer_edges_from_links` stays public and untouched
(K6/K9); `docmap` imports it.

## DoD bundle

- `feature-doc/catalog/docmap.yaml` (FEAT-DOCMAP-001…): modules
  `[docmap, config, cli]`; constraints K1/K6/K8/K10/K11.
- Feature-tagged tests + DEMOS.md case(s) (next free DEMO ids after AGT-01).
- coverage.waive for `custodex/docmap.py`; wiki regen; dogfood reheal
  (**config.py IS tracked** → `docs/api/*` will drift → `cdx monitor --apply`).
- Full gate + trace.

## Test plan

- unit (`test_docmap.py`): the goal matrix above + direction principle (B
  mentions S but ALSO covers S → no B→B; A and B both cover S → no suggestion,
  ambiguous ownership meaning: symbol covered by ≥2 docs is excluded from the
  rule — precision first, document it), tier merge, evidence sorting,
  determinism double-run.
- unit (`test_config.py` additions): `add_doc_edge` round-trip + loud paths.
- system (`test_docmap_cli.py`): `cdx link` end-to-end on a tmp dir-layout
  repo (declare → stamp → deps shows it → suggestion gone → check exit 0);
  `deps --suggest` text + `--json` shapes; `infer_from_links` on/off.
- regression guard: `deps --json` bare-list shape unchanged (K6).

## Out of scope

The graph artifact (AGT-03), SHARED_ENTITY tiers beyond symbols (paths/env
vars as edge evidence — follow-on), undirected/symmetric suggestions, hub
mirroring of suggestions, LLM edge proposals.
