# Slice AGT-01 — `entities.py`: deterministic entity extraction + mention linking

> **REVISED 2026-07-02** after the 3-lens adversarial design review. The review
> measured the original rules against THIS repo's corpus and found four
> precision failures (module-stem misresolution, unresolved-noise floor, PATH
> universe mismatch, unpinned identifier rule) plus a false DoD claim. The
> rules below are the corrected, binding versions — see ARCHITECTURE.md
> `EPIC AGT` ⟨R⟩ markers. Do not weaken them during implementation.

First slice of EPIC AGT. The mention layer everything else builds on: parse each
managed doc's PROSE deterministically and LINK the mentions against a registry
built from the code surface + the managed-doc set + the full repo file tree.
**No LLM anywhere in this slice** (the LazyGraphRAG split; K1/K4/K10).
Unresolved mentions are first-class data (the Obsidian rule) — but ONLY when
the rules below say a span may be unresolved: **precision beats recall; an
ambiguous mention is unresolved-or-ignored, never guessed.**

## Goal (validable)

On a fixture corpus (two managed docs + two source files + a nested package):
1. a backticked `Class.method`, a module-qualified `mod.func` (unique stem),
   and a full-dotted `pkg.sub.mod.func` each resolve to the right SYMBOL
   entity (`symbol <repo-rel-path>#<qualified>`);
2. a relative markdown link to another managed doc → DOC resolved; to an
   existing non-managed file → PATH resolved; to an existing directory
   (trailing `/`) → PATH resolved; absolute `https://` → URL;
3. a backticked `CDMON_LIKE_VAR` → ENV_VAR **only** with `entities.
   env_prefixes: [CDMON_]` configured; an unprefixed `SOME_ENUM_NAME` that
   matches no registry symbol is IGNORED (not unresolved);
4. a backticked snake_case identifier matching nothing → UNRESOLVED SYMBOL;
   a plain single word (`check`) matching nothing → IGNORED; a bare name that
   is ALSO a file stem (`app`) → UNRESOLVED (ambiguous), even when the symbol
   is globally unique; two files with the same stem make `stem.func`
   UNRESOLVED (stem-collision fixture);
5. NO mention minted from inside a fenced code block, a `CDM:BEGIN/END`
   region, an image link, a span with whitespace/`{}`/glob metachars, or a
   span listed in `entities.ignore`;
6. byte-deterministic: two runs identical; mentions sorted `(line, text)`;
   `line` is FILE-accurate (front-matter height included — prove with a doc
   whose front matter is ≥5 lines);
7. **dogfood precision budget:** `corpus_entities` over THIS repo's managed
   corpus (with the seeded dogfood stoplist + `env_prefixes: [CDMON_]`)
   yields UNRESOLVED mentions containing NO glob/dir/route/enum-name/plain-
   word false positives — assert the unresolved set is exactly the (small,
   enumerated) expected set, so precision regressions fail loudly.

## In scope

**New `custodex/entities.py`** — implement exactly the ⟨R⟩-revised
ARCHITECTURE.md contract: `EntityKind` (DOC/SECTION/SYMBOL/PATH/ENV_VAR/URL),
`Entity` (SECTION `name` = slug, dedup `-2`/`-3`), `Mention` (file-accurate
`line`), `DocEntities`, `EntityRegistry` (docs + per-file symbols with
qualified AND module-qualified forms + FULL repo file/dir tree + module stems
+ `warnings`), `build_registry` (language-guarded extractor dispatch by
suffix; unparseable/unregistered → warning + no symbols, NEVER an abort),
`extract_doc_entities` (PURE), `corpus_entities`, `render_entities_text`.

**`custodex/config.py`** — new `EntitiesConfig{ignore: tuple[str,...] = (),
env_prefixes: tuple[str,...] = ()}` + `MonitorConfig.entities` (additive,
default ⇒ old configs load unchanged — K6). Round-trips in both config forms.

**`config/cdmon/index.yaml`** — seed the dogfood `entities:` section
(`env_prefixes: [CDMON_]` + the measured stoplist, e.g. `cdx`, `mock`, `pg`,
`live_llm`, config keys like `code_refs`/`context_refs` if still needed after
the strict rules — keep the list MINIMAL and justified by the goal-7 test).

**`custodex/cli.py`** — `cdx entities [DOC_ID] [--json] [--unresolved]`
(read-only, K1; loud on unknown DOC_ID, K8).

**Hardening rider:** DEMOS.md id-uniqueness — renumber the duplicated
section-M trio to DEMO-095/096/097 (grep first: the old ids must not be
referenced elsewhere) + a smoke test asserting `### DEMO-NNN` headers unique.
New AGT-01 demos start at DEMO-098.

## DoD bundle (the new-core-module checklist)

- `feature-doc/catalog/entities.yaml` (FEAT-ENTITIES-001…): modules
  `[entities, config, cli]`; constraints K0/K1/K10/K11.
- Feature-tagged tests + DEMOS.md case(s) `DEMO-098+`.
- coverage.waive entry for `custodex/entities.py` (reason → catalog yaml).
- **cli.py IS TRACKED** (ops eng-guide + readme user-guide) and config.py IS
  TRACKED: adding the command + config section WILL drift `docs/api/ops.md`,
  `docs/api/foundation.md` and the README fingerprint → run
  `cdx monitor --apply --config config/cdmon` + `cdx check`, commit the
  rehealed docs, and add a README prose line for the new `cdx entities`
  command (it is a user-guide doc).
- `cdx wiki` regen; full gate + `cdx trace --fail-on-gap`.

## Test plan

- unit (`tests/unit/test_entities.py`): every goal rule + every exclusion +
  the resolution matrix + stem-collision + module-qualified forms + slug
  dedup + stoplist + env-prefix gate + registry resilience (a planted
  syntax-error file → warning + scan continues) + determinism double-run.
- unit (`tests/unit/test_config.py` additions): EntitiesConfig round-trip +
  default-absent back-compat.
- integration: `corpus_entities` over a real tmp fixture repo; PLUS the
  goal-7 dogfood precision assertion over THIS repo.
- system (`tests/system/test_entities_cli.py`): text/`--json`/`--unresolved`/
  exit codes/unknown-doc loud.
- smoke: DEMO header uniqueness.

## Out of scope

Edge suggestion (AGT-02), the graph (AGT-03), cdm.* entity caching, fuzzy/LLM
resolution, reference-style `[text][ref]` links (documented limitation),
non-Python symbol languages beyond what the extractor registry already
resolves (shell functions come free via the language-guarded dispatch).
