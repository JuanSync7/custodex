# RTE-03a — one renderer, not two (heal must not author an index region)

**Epic:** RTE (the apply-tier router)
**Depends on:** RTE-01 (`ApplyTier`) — merged
**Constraints:** K2, K7, K8, K9, K10
**Status:** DONE

## Goal (validable)

`heal` must never author a region body that `detect` grades as WRONG. Today it
does, and it deletes data doing it.

**Reproduced on this repo's own `docs/api/index.md`, not asserted:**

```
render_index (what detect expects) -> 16 lines
expected_region (what heal writes) ->  2 lines   EQUAL=False
heal.regenerate_regions changed=True    api-index rows: 16 -> 2   (14 rows deleted)
```

`drift.detect` renders a `source: index` region with the index-aware layer
(`drift.py:596-600`); `heal._corrected` has only `expected_region`
(`heal.py:115`), which falls through `render_template`'s **records** branch and
returns a header-only table — even though `render_template`'s own docstring says
`source='index'` is *"rendered by the index-aware layer (it needs other
documents' surfaces), not here"*. Nothing enforced that sentence, and the layer
that WRITES was the one that could not render.

It is live today, unattended: `generate.apply_edits_to_disk` →
`regenerate_regions` (`generate.py:459`) is the `cdx write-doc` / server
config-editor path. RTE-03d would have opened a second, fully-unattended one.

**Done when:**
- `expected_region` returns `None` for a `source: index` template, so
  `heal._corrected` hits its existing `if expected is None: continue`
  (`heal.py:116-117`) and SKIPS the region instead of corrupting it.
- Both write shapes are pinned byte-identical (`regenerate_regions` and
  `render_corrected` — the latter is the RTE-03d path).
- A corpus guard pins the CLASS, not the instance.
- Full gate green; all four configs clean; dogfood rehealed.

## Design

⟨R⟩ **`expected_region`, not `render_template`.** `render_template`'s contract is
"render a table FROM A SURFACE". An index table is a function of the config's
*other* documents, so it is not renderable there at all — the honest place to
decline is the selector that promises "the body this region should hold, or
`None` if unknown". Blast radius is nil at the other three call sites:
`drift.py:600` and `backends.py:459` are both already inside the `else` of an
explicit `source == "index"` test, and `layout.py:520` passes no template.

⟨R⟩ **Skipping does not bless it.** The per-document fold (RTE-01) exists because
heal stamps the fingerprint even when it skips a region, and for a `mode: llm`
no-renderer region that stamp is the ONLY staleness trigger (`drift.py:576` gates
it on `stored != current`). An index region is the FOIL: `detect` grades it
against `render_index` **unconditionally** (`drift.py:601`), so a skipped index
region still drifts on the very next `cdx check`. Verified by a test, not by
inspection.

⟨R⟩ **Decline with `None`, never with `""`.** `""` is a body, and heal would
write it — replacing 14 rows with nothing is the same data loss with a different
diff. Pinned by mutation M3.

## Tests (TDD, red first)

| test | pins |
|---|---|
| `test_expected_region_declines_an_index_source_template` | the selector returns `None`; `records`/`symbols` still render (the foil) |
| `test_regenerate_regions_never_corrupts_an_index_region` | the live `generate.py` write path leaves the body byte-identical |
| `test_render_corrected_never_corrupts_an_index_region` | the whole-doc shape (RTE-03d's path) too |
| `test_skipping_an_index_region_does_not_bless_it` | a STALE index body survives the heal **and** `detect` still reports `REGION` |
| `test_heal_never_writes_a_region_body_detect_would_call_wrong` (corpus) | the CLASS: for every configured template, heal authors exactly what detect expects — or nothing |

## Mutation verification (ralph loop) — 5/5 killed, 0 survivors

Run first-hand, serially, with byte-level `cp` backup/restore (never
`git checkout` — the epic's work is uncommitted).

| # | mutation | killed by |
|---|---|---|
| M1 | drop the decline branch (the pre-fix state) | corpus + all 3 heal tests |
| M2 | decline the WRONG source (`records` instead of `index`) | corpus |
| M3 | decline with `""` instead of `None` (heal writes an empty body) | corpus + unit |
| M4 | heal drops its `expected is None -> skip` guard | all 3 heal tests |
| M5 | `detect` drops its index-aware branch (blind to index drift) | `test_skipping_an_index_region_does_not_bless_it` |

M5 is the one that matters most: it proves the guard is two-sided. Declining in
heal is only safe *because* detect still looks.

## EPIC-R

**FEAT-HEAL-010** + **DEMO-121**; `cdx trace --fail-on-gap` 261/261.
