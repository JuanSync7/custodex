# Slice AGT-01 — `entities.py`: deterministic entity extraction + mention linking

First slice of EPIC AGT. The mention layer everything else builds on: parse each
managed doc's PROSE deterministically and LINK the mentions against a registry
built from the code surface + the managed-doc set. **No LLM anywhere in this
slice** (the LazyGraphRAG split — index-time is pure; K1/K4/K10). Unresolved
mentions are first-class data, not errors (the Obsidian rule) — they are the
graph-rot signal AGT-03 surfaces.

## Goal (validable)

On a fixture corpus (two managed docs + two source files), `corpus_entities`:
1. resolves a backticked qualified symbol mention (`` `mod.func` `` /
   `` `Class.method` ``) to the SYMBOL entity of a file in the repo inventory;
2. resolves a relative markdown link to another managed doc as a DOC mention
   (and an absolute `https://` link as URL);
3. yields an ENV_VAR mention for a backticked `CDMON_LIKE_VAR`;
4. yields an UNRESOLVED symbol mention for a backticked identifier that matches
   nothing (`resolved is False`, `entity_id is None`);
5. NEVER mints a mention from inside a fenced code block or a `CDM:BEGIN/END`
   region (prove with a symbol name planted inside both);
6. is byte-deterministic: two runs give identical tuples; mentions sorted
   `(line, text)`; `cdx entities --json` output stable (K10).

## In scope

**New `custodex/entities.py`** — exactly the pinned ARCHITECTURE.md contract
(EPIC AGT section): `EntityKind` (DOC/SECTION/SYMBOL/PATH/ENV_VAR/URL, closed),
`Entity` (SCIP-style string `id`, e.g. `symbol custodex/drift.py#detect_drift`,
`doc docs/api/drift.md`, `env CDMON_SECRET_KEY`), `Mention` (doc_id, entity_id
| None, kind, text, line, resolved), `DocEntities` (mentions sorted, sections),
`EntityRegistry`, `build_registry(config, root)`,
`extract_doc_entities(doc_id, doc_path, body, registry)` (PURE),
`corpus_entities(config, root, *, doc_id=None)`,
`render_entities_text(results, *, unresolved_only=False)`.

Parsing rules (deterministic, documented in the module docstring):
- Strip fenced code blocks (``` / ~~~) and `<!-- CDM:BEGIN -->…<!-- CDM:END -->`
  regions BEFORE scanning (replace with blank lines so `line` numbers survive).
- Headings `#`..`######` → the doc's own SECTION entities (id
  `section <doc_path>#<slug>`, slug = lowercase-hyphenated text).
- Inline markdown links (skip images `![..](..)`, skip `mailto:`): relative →
  resolve against managed-doc paths (DOC mention, resolved) else PATH mention
  against the repo file inventory (resolved iff the file exists in the
  inventory) — otherwise unresolved PATH; absolute `://` → URL (self-evident,
  resolved).
- Inline backtick spans: `[A-Z][A-Z0-9_]{2,}` containing `_` → ENV_VAR
  (self-evident); contains `/` or ends `.py`/`.md`/known suffix → PATH
  (resolved against inventory / managed docs); identifier-like (dotted /
  snake_case / CamelCase, python-identifier chars only) → SYMBOL, resolved by
  exact match against the registry (qualified `Class.method` and bare names;
  bare-name match requires GLOBAL uniqueness in the registry, else unresolved —
  precision over recall, no fuzzy matching, K11); anything else → ignored (not
  a mention).
- Registry: doc paths→ids + doc ids (DOC), every inventory file path (PATH),
  every public symbol per file with qualified names (SYMBOL) via
  `inventory.discover_files` + `extract.extract_file` — never imports the
  target (K0). Symbol entity id embeds the defining file:
  `symbol <path>#<qualified_name>`; a bare name mapping to ≥2 files is AMBIGUOUS
  → excluded from bare-name resolution (kept for qualified resolution when the
  qualifier disambiguates).

**`custodex/cli.py`** — `cdx entities [DOC_ID] [--json] [--unresolved]`
(read-only, K1; loud on unknown DOC_ID, K8). Plain text via
`render_entities_text`; `--json` = sorted list of DocEntities dumps.

**Hardening rider (small, this slice):** DEMOS.md id-uniqueness — dedup the
existing duplicate `DEMO-052/053/054` headers (renumber the section-M trio to
fresh ids) and add a smoke test asserting `### DEMO-NNN` headers are unique
(`tests/smoke/`), so the epic's new demos can't collide.

## DoD bundle (the new-core-module checklist)

- `feature-doc/catalog/entities.yaml` (FEAT-ENTITIES-001…): modules
  `[entities, cli]`; constraints K0/K1/K10/K11.
- Feature-tagged tests (`tests/unit/test_entities.py`,
  `tests/system/test_entities_cli.py`) + DEMOS.md case(s) `DEMO-095+`.
- `config/cdmon/index.yaml` coverage.waive entry for `custodex/entities.py`
  (reason → catalog yaml), like worklist.
- `cdx wiki` regen; dogfood reheal if any tracked module drifts (cli.py is NOT
  tracked; config.py untouched here).
- Full gate + `cdx trace --fail-on-gap`.

## Test plan

- unit: registry build (docs/paths/symbols; ambiguity exclusion), each parsing
  rule + each exclusion (fence, CDM region, image link, mailto), resolution
  matrix (resolved/unresolved per kind), section slugging, determinism
  (double-run equality), sorted order, loud unknown doc id.
- integration: `corpus_entities` over a real tmp fixture repo (config + docs +
  sources on disk).
- system: `cdx entities` text + `--json` + `--unresolved` + exit codes.

## Out of scope

Edge suggestion (AGT-02), the graph (AGT-03), any cdm.* front-matter caching of
entities, fuzzy/LLM resolution, reference-style `[text][ref]` links (note as a
documented limitation), non-Python symbol registries beyond what
`extract_file` already yields.
