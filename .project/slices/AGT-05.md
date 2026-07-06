# Slice AGT-05 — `docwriter.py`: the doc-writer agent (`cdx write-doc`)

> Provenance note: the contract was pinned in `ARCHITECTURE.md` §EPIC AGT
> BEFORE implementation; the slice was built by the orchestrator in the main
> loop (subagent session-limit death — the PROCESS re-dispatch clause) and
> this spec file committed alongside the PR #20 review fixes. The goals below
> are the ones the implementation was built and tested against.

Authoring, not just healing: point `cdx write-doc` at a SOURCE file and get a
new managed document — drafted from the extracted surface, its overview
authored through the SAME backend seam `monitor --apply` uses (B-06 LLM
region), registered in the unit config by textual splice, and **born in-sync**
(the very next `cdx check` is clean; no heal step needed).

## Goal (validable)

On a dir-layout fixture bundle (one unit, one existing doc, a source module):
1. `proposed_doc_id("pkg/sub/mod.py")` → `"pkg-sub-mod"` (deterministic);
2. `build_doc_spec` pins `region_keys=("symbols", "overview")` and
   `region_modes={"overview": llm}` — the B-06 no-renderer region;
3. `draft_document` scaffolds via `layout.scaffold_doc` and replaces the WHOLE
   `> TODO…` purpose line with a backend-authored one-paragraph overview; a
   non-FIX or bodyless verdict degrades to the placeholder (never crashes);
4. `write_and_register` validates (unknown unit / duplicate id / duplicate
   path — loud K8), splices the DocumentSpec into the unit's `documents:`
   block (bounded textual splice — the AGT-02 authorship rule for
   hand-maintained files), bumps `updated:`, reload-validates + REVERTS on
   failure, writes the drafted doc — and the fixture's next `cdx check`
   exits 0 (born in-sync, e2e);
5. the LIFECYCLE closes: edit the source → `cdx check` reports drift on the
   new doc → `cdx monitor --apply` re-authors the overview region through the
   same seam → `cdx check` clean again;
6. `cdx write-doc SOURCE [--unit][--id][--audience]` derives the doc path from
   the unit's first `dir-covered` sibling `docs/` convention and echoes the
   registered mapping.

## In scope

**New `custodex/docwriter.py`** (pure core + backend seam): `OVERVIEW_REGION`;
`proposed_doc_id(source_path)`; `build_doc_spec(*, doc_id, path, audience,
code_refs)`; `_author_overview` (synthetic B-06 `FixRequest` through
`make_backend` — no new backend API); `draft_document(spec, surface, *,
style_guidance=None, backend=None, include_body=False)`; `unit_snippet(spec)`;
`write_and_register(config_dir, *, unit, spec, backend=None,
style_guidance=None, now)`.

**`custodex/cli.py`** — `cdx write-doc SOURCE [--unit][--id][--audience]
[--config]`.

## DoD bundle

- `feature-doc/catalog/docwriter.yaml` (FEAT-DOCWRITER-001) + DEMO-106.
- coverage.waive for `custodex/docwriter.py`; wiki regen; trace green.
- cli.py is tracked → dogfood reheal; README gains the `cdx write-doc` line.
- Full gate (ruff/mypy/pytest ≥90 branch) + all cdx gates exit 0.

## Test plan

- unit (`test_docwriter.py`): id derivation, spec shape, TODO-line
  replacement (whole line, not prefix), backend-degrade path, snippet
  rendering, splice validation + revert, duplicate/unknown loudness.
- system (`test_docwriter_cli.py`): write → born-in-sync (`cdx check` 0);
  the write → source-edit → drift → heal-re-authors lifecycle; CLI loudness.

## Out of scope

Whole-body LLM authoring by default (`include_body` stays opt-in data, the
human applies — K11), doc DELETION/moves, style-guidance sourcing beyond the
doc-style map, frontend (AGT-07).
