# Slice ASTRO-03 — the console as React islands under `frontend/`

EPIC ASTRO, phase 3. Move the tested React+Vite console (EPIC F `dashboard/`)
into the Astro app as a `client:only` island, so the whole frontend lives under
`frontend/` with no rewrite of the working, tested components.

## Goal (validable)
1. **Ported verbatim.** `dashboard/src/{api,components,hooks,pages,test,types.ts,
   App.tsx,index.css,routing.ts,schema.review.json}` → `frontend/src/console/`.
   No component logic rewritten.
2. **Mounted as one island.** `src/console/ConsoleApp.tsx` wraps `<App/>` in a
   `HashRouter` (mirrors the retired `main.tsx`); `src/pages/index.astro` mounts
   `<ConsoleApp client:only="react" />` inside `Layout.astro`. Hash routes
   (`#/repos/…`) never shadow the API under the single-origin deploy.
3. **Tests move with it.** The 14 Vitest suites (`*.test.tsx`) run under
   `frontend/vitest.config.ts` (jsdom, Testing Library, `src/console/test/setup.ts`).
   On this shared host the `threads` pool + `singleThread` is used (forks starve).
4. **Single-origin API base.** `defaultBaseUrl()`/`displayBase()`/`apiBase()` read
   `PUBLIC_API_BASE` (Astro), default `""` (same-origin) — fetches hit `/repos`,
   `/health`, … directly. `import.meta.env` typed via `src/env.d.ts`.

## Test plan
- `npm --prefix frontend run build` (`astro check` clean → bundles the island
  chunks) exits 0.
- `npm --prefix frontend run test:run` — the ported Vitest suites green (no
  network: injected `api`/`fetchImpl`; `App.routing.test.tsx` stubs `fetch`).
- Served in-process: `create_app(static_dir=frontend/dist)` → `GET /` is the
  console `index.html`; `/_astro/*` islands served; API routes still win.

## Design
See ARCHITECTURE.md. The console keeps its own components/styles; `Layout.astro`
provides the document shell + design tokens. `astro check` type-checks the
console via the project tsconfig (`types: [node, astro/client, vitest/globals,
@testing-library/jest-dom]`; `vitest.config.ts` excluded). The Wiki nav item
becomes a REAL `<a href="/wiki/features">` (native page, not a client route).

## Out of scope
Deleting `dashboard/` + CI (ASTRO-04). A UI redesign (the port is faithful;
visual reconciliation of the Astro Layout vs the console's own CSS is light).

## Constraints
K0 (Astro frontend-only; no engine dep). No network in tests (K4-analog). The
ported components are unchanged behaviourally — only the build/host/API-base seam
moved.
