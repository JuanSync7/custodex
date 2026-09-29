# CIX-02 — the stdlib SCIP reader + xrefs artifact + kgraph REFERENCES tier

**Epic:** CIX (the persisted code index, cross-references, and impact)
**Depends on:** CIX-01 (the code index provides spans for attribution and the
module→path map for symbol resolution)
**Constraints:** K0, K1, K6, K7, K8, K9, K10, K11

## Goal (validable)

Consume an externally produced SCIP index (scip-python et al.) with a
pure-stdlib protobuf wire decoder — no `protobuf` dependency (K0) — and
project it into `.cdmon/xrefs.json`: symbol→symbol REFERENCES edges in the
EXISTING entity id scheme (`symbol <posix-path>#<Class.method>`), with a
per-language `coverage` honesty map and an `unmapped` count. Fold the edges
into the knowledge graph additively (schema_version 1.0.0 → 1.1.0).

**Done when:**
- `custodex/scip.py` matches the pinned `ARCHITECTURE §EPIC CIX → CIX-02`
  signatures. Decoder handles: varints, LEN fields, packed AND unpacked
  repeated int32, deprecated `range`=1/`enclosing_range`=7 AND typed range
  fields 8–11 (typed wins when both present), unknown-field skip by wire
  type, groups rejected loudly. Malformed input → `ExtractionError` (K8).
- `scip_symbol_to_dotted`: full grammar (double-space escapes, backtick
  identifiers with doubled backticks, all descriptor suffixes, `local …` and
  parameter/type-parameter descriptors → None), module `__init__:` meta
  descriptor dropped.
- `build_xrefs`: dotted→(path, qualname) resolution by module-suffix match
  over the CodeIndex paths (the scip-python `src.foo.bar` vs `foo.bar` quirk);
  reference attribution by narrowest containing span from the code index;
  public endpoints only; self-edges dropped; `count` tallies occurrences;
  edges sorted (source, target) (K10).
- kgraph: `EdgeKind.REFERENCES`/`EdgeTier.INDEXED` added, `schema_version`
  "1.1.0", `build_graph(..., xrefs=())` additive default keeps prior output
  byte-identical; `cdx graph` folds `.cdmon/xrefs.json` in when present;
  `tests/system/test_kgraph_cli.py` schema_version assert updated.
- `cdx scip INDEX_FILE`: summary default; `--write` persists (K7 idempotent);
  `--json`. Custodex never shells out to an indexer (K11 — the human runs
  scip-python and hands us the file).
- Governance: waiver for `custodex/scip.py`; `feature-doc/catalog/scip.yaml`
  (FEAT-SCIP-001, modules `[scip, kgraph, cli]`); DEMO-114; tagged tests;
  wiki regen; kgraph doc reheal.
- Full gate green (as CIX-01).

## Design

See `ARCHITECTURE §EPIC CIX` ⟨R⟩3. The test fixture is a hand-encoded SCIP
index built by a tiny test-only encoder (`tests/_scip.py`) — the suite stays
offline (K4); scip-python itself is never a test dependency.

## Non-goals (later slices)

- Running scip-python from custodex (never — K11).
- Non-python SCIP indexes (decoder is language-agnostic; mapper resolves only
  paths present in the code index — others count into `unmapped`).
- REFERENCES/MENTIONS dedup (different kinds, deliberately co-present).

## Test plan (TDD)

- **unit** `tests/unit/test_scip.py`: wire decoder against hand-encoded bytes
  (packed + unpacked ranges, 3- and 4-element ranges, typed_range precedence,
  unknown fields skipped, truncated/garbage input → `ExtractionError`);
  symbol grammar table-test (module/class/method/function/term/param/local/
  backticked); `build_xrefs` attribution + suffix-match + public filter +
  self-edge drop; xrefs read/write roundtrip + idempotency; kgraph fold
  (REFERENCES edges present, prior edges unchanged, no-xrefs call
  byte-identical to 1.0.0 content modulo schema_version).
- **system** `tests/system/test_scip_cli.py` (CliRunner): fixture .scip →
  summary; `--write` twice → `wrote`/`unchanged`; corrupt file → K8 error
  line; `cdx graph --write` picks up xrefs.

## Reheal order (DoD)

`(waiver) → cdx monitor --apply → cdx check → cdx wiki → cdx trace →
ruff/mypy/pytest`.
