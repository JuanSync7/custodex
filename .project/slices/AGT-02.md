# Slice AGT-02 — `docmap.py`: entity-based edge suggestions + `cdx link` accept/reject

> **REVISED 2026-07-02** after the adversarial design review. Confirmed fixes
> folded in: index-doc noise exclusion (measured 13/13 false suggestions on
> the dogfood), comment-destroying `dump_unit_file` write replaced by textual
> splice, `via` key kept for K6, repo-side rejections, the heal-path-churn
> decision (`docdeps.baseline: prose` knob + churn notes). Binding — see
> ARCHITECTURE.md `EPIC AGT` ⟨R⟩ markers.

Builds on AGT-01. Upgrades doc↔doc mapping from lexical link-inference to
entity-grounded suggestions with provenance tiers, and adds BOTH human verbs:
accept (`cdx link DOWN UP`) and reject (`cdx link --reject DOWN UP`).
Everything advisory until a human applies (K11).

## Goal (validable)

Fixture: doc A's prose backtick-mentions symbol `S` (resolved per AGT-01);
doc B covers `S` via `code_refs`; doc C markdown-links doc B; doc IDX is an
`index: true` doc linking everything.
1. `suggest_edges` returns EXACTLY two suggestions: `C→B` RESOLVED_LINK
   (`via` = the link target) and `A→B` SHARED_SYMBOL (`via=None`, evidence =
   `S`'s entity id, score 1). IDX yields NOTHING (index exclusion);
2. a link planted inside a fenced block or CDM region yields NO suggestion
   (the AGT-01 stripping — the legacy `infer_edges_from_links` would have
   minted it; docmap must not);
3. after `cdx link A B`: the edge is declared in the unit YAML **with every
   pre-existing YAML comment in the file byte-preserved** (textual splice),
   the baseline is stamped (`cdx check` exit 0 — K7), and the suggestion
   disappears from a re-run;
4. after `cdx link --reject C B`: the rejection is appended to
   `.cdmon/edge-rejections.jsonl` and the `C→B` suggestion never returns;
5. a symbol covered by ≥2 docs produces NO suggestion; a doc mentioning a
   symbol it covers itself produces NO self-edge; same pair via both rules ⇒
   ONE suggestion at RESOLVED_LINK tier with merged evidence;
6. `--json` items are a key-SUPERSET of today's `{doc_id, upstream_id, via}`
   (regression guard);
7. with `docdeps.baseline: prose`, a HEAL of the upstream (CDM region
   rewrite, prose untouched) does NOT trip the downstream edge, while a
   prose edit DOES; with the default `body`, behavior is byte-identical to
   today (back-compat guard);
8. every suggestion whose upstream carries code_refs renders a churn note;
   `cdx link` echoes it before writing.

## In scope

**New `custodex/docmap.py`** — the ⟨R⟩-revised contract: `SuggestionTier`,
`ScoredEdge{doc_id, upstream_id, via, tier, evidence, score}`,
`EdgeRejection`, `suggest_edges(config, root, *, rejections=())` (RESOLVED_LINK
from AGT-01 DOC mentions; SHARED_SYMBOL from the mentions × coverage join with
the exactly-one-covering-doc rule; exclusions: declared/self/rejected/
index-downstream/dup), `churn_note`, `render_suggestions_text`,
`declare_edge` (model-validated, TEXTUAL-SPLICE write — never
`dump_unit_file`; loud K8 when the `- id:` entry can't be located),
`reject_edge`/`read_rejections` (`.cdmon/edge-rejections.jsonl`, append-only,
injected `now` — the reviewlog precedent).

**`custodex/config.py`** —
- `DocDepsConfig.baseline: Literal["body", "prose"] = "body"` (additive, K6);
- fix the `infer_from_links` docstring to describe the REAL behavior (advisory
  summary line in `cdx deps`) — closes the documented-but-unimplemented drift.

**`custodex/docdeps.py`** — `upstream_fingerprint(doc, *, baseline="body")`:
`"prose"` hashes the region-STRIPPED body (reuse the manifest region parser to
drop `CDM:BEGIN/END` bodies). Thread the knob through `detect_suspect_links` +
`stamp_edges` (one shared truth — stamps and detection must use the SAME
baseline or every edge is permanently suspect). `infer_edges_from_links`
itself UNTOUCHED (back-compat, K9).

**`config/cdmon/index.yaml` + `demo/config/cdmon/index.yaml`** — flip to
`baseline: prose`; restamp the existing few edges (deliberate re-baseline,
documented in the commit).

**`custodex/cli.py`** —
- `cdx deps --suggest`: prints `suggest_edges` + churn notes (loads rejections
  from `.cdmon/`); `--json` superset shape;
- `cdx deps` report: `infer_from_links: true` ⇒ ONE advisory summary line
  (count + "run `cdx deps --suggest`"), never the full list;
- NEW `cdx link DOWN UP [--type depends|refines|implements|verifies]
  [--reject] [--by NAME] [--note TEXT]`: accept = `declare_edge` +
  `stamp_edges(..., only=UP)`; `--reject` = `reject_edge`. Loud on unknown
  ids / single-file config / already-declared / already-rejected (K8).

## DoD bundle

- `feature-doc/catalog/docmap.yaml` (FEAT-DOCMAP-001…): modules
  `[docmap, docdeps, config, cli]`; constraints K1/K6/K7/K8/K10/K11.
- Feature-tagged tests + DEMOS.md cases (next ids after AGT-01's).
- coverage.waive for `custodex/docmap.py`; wiki regen.
- **config.py, docdeps.py AND cli.py are ALL tracked** → reheal
  (`cdx monitor --apply --config config/cdmon` + `cdx check`), commit rehealed
  docs/api/*, README prose line for `cdx link`.
- Full gate + trace.

## Test plan

- unit (`test_docmap.py`): the goal matrix + direction/ambiguity rules +
  index exclusion + rejection exclusion + tier merge + churn note content +
  determinism; `declare_edge` splice on a comment-rich fixture unit
  (byte-compare everything except the inserted block) + loud paths.
- unit (`test_docdeps.py` additions): prose-baseline fingerprint (region
  rewrite → unchanged; prose edit → changed) + body default byte-identical.
- unit (`test_config.py`): baseline knob round-trip + default.
- system (`test_docmap_cli.py`): `cdx link` accept + reject e2e on a tmp
  dir-layout repo; `deps --suggest` text/json; `deps` advisory summary
  on/off; single-file-config loud.
- regression: `deps --json` bare-list shape + `--suggest` key-superset.

## Out of scope

The graph artifact (AGT-03), SHARED_ENTITY tiers beyond symbols, undirected
suggestions, hub mirroring of suggestions/rejections (workers slice), LLM
edge proposals, migrating existing `body` stamps automatically (flip =
documented manual re-baseline).
