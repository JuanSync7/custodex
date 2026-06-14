# Slice TDOC-04 — Frontend "Test docs" section

EPIC TDOC. Surfaces test-docs in the console exactly the way README files are
surfaced: a dedicated **Test docs** section on the Documents, Drift, and Mapping
pages, partitioned purely by path (mirrors the README pattern). Delivered by a
parallel subagent (clean `frontend/`-only boundary).

## Why
The user asked for "all the sections for it" in the web app. Source docs, README
files, and now test-docs are distinct categories the operator should see
separately — without conflating them in one list.

## Goal (validable)
1. **Helpers.** `frontend/src/console/lib/grouping.ts` gains `isTestDocPath(path)`
   (first path segment `test-docs`) and `partitionDocs<T>(items, pathOf)` → a
   three-way `{main, readme, tests}` split, order-preserving, precedence
   test→README→main. `isReadmePath`/`partitionReadme` are kept for back-compat.
2. **Sections.** Documents, RepoDetail (Drift), and Mapping each render a "Test
   docs" section after the README section, reusing the existing row renderers; an
   empty `tests` bucket renders nothing.
3. **Pure presentational.** No new API/route/store/schema surface — test-docs flow
   through the existing document endpoints, distinguished only by path.
4. **Verified.** `astro check` 0 errors; the production bundle (`frontend/dist`)
   rebuilds; the grouping test cases are Node-verified (vitest cannot run on this
   EDR host — worker starvation), plus vitest specs for CI.

## Design
- `isTestDocPath`: `/^test-docs\//.test(path) || path === "test-docs"`.
- `partitionDocs`: reuse `isTestDocPath` + `isReadmePath`; test-doc precedence.
- Pages swap `partitionReadme` → `partitionDocs` and add a `<h2>Test docs</h2>`
  panel via the same `DocumentsTable`/`renderRecordRows`/`DocumentsSection`.

## Test plan
- `grouping.test.ts`: `isTestDocPath` true/false cases + `partitionDocs` three-way
  split with order + precedence (a `test-docs/README.md` goes to tests, not readme).
- Page tests (`Documents.test.tsx`/`RepoDetail.test.tsx`/`Mapping.test.tsx`): a
  test-doc renders under a "Test docs" heading.
- `astro check` clean; build succeeds.

## Out of scope
Coverage page (the test files already appear in the collapse/expand tree once the
`tests` unit is a coverage scope — no change needed). Backend (untouched).

## Constraints
K0 (presentation only; the engine has no notion of "test doc"), K10 (deterministic
partition). vitest cannot run locally — Node-verify the pure helpers.
