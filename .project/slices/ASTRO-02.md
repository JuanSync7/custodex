# Slice ASTRO-02 — native Astro docs/wiki under `/wiki/*`

EPIC ASTRO, phase 2. Render the EPIC-R wikis NATIVELY with Astro's markdown
pipeline — retiring the React `Wiki.tsx` island + the `dangerouslySetInnerHTML`
prose pane (the "so many HTML" smell on the frontend).

## Goal (validable)
1. **Content collection.** `src/content.config.ts` defines a `wiki` collection
   via the glob loader over the committed `feature-doc/` markdown
   (`FEATURES.md` + `wiki/*.md`) — read in place, no copy/duplication, no
   frontmatter/schema.
2. **Native pages.** `src/pages/wiki/[...slug].astro` renders each doc with a
   section rail (Feature Reference / Traceability / Test / Source) at
   `/wiki/features`, `/wiki/traceability`, `/wiki/tests`, `/wiki/source` —
   Astro's markdown → headings, tables, code, all in the `.prose` style. No
   `render_markdown`, no `dangerouslySetInnerHTML`.
3. **React wiki retired (frontend).** `pages/Wiki.tsx`/`Wiki.test.tsx` deleted;
   `api.wiki()`, `WikiSection`/`WikiPayload`, the `/wiki` client route, and the
   `wikiPayload` fixture removed. The AppShell **Wiki** nav is a real
   `<a href="/wiki/features">`.

## Test plan
- `astro build` renders the `/wiki/*` static pages (incl. the ~1.2 MB Test Wiki)
  from `feature-doc/*.md`; served in-process via the catch-all static mount.
- The console Vitest suites stay green after the wiki removal (no dangling
  `wiki()`/`WikiPayload` refs).

## Design
The native pages avoid the EXACT `/wiki` path so they do not collide with the
server's existing `GET /wiki` JSON route (declared before the static mount); the
canonical entry is `/wiki/features`. `metaFor()` maps a collection entry id to a
slug by substring (robust to the loader's id casing).

## Out of scope / follow-up
**Retiring the server `GET /wiki` JSON endpoint + `WIKI_SECTIONS`/`_wiki_dir`/
`_load_wiki_sections` + `build.render_markdown`'s wiki use + the catalog
FEAT-SERVER-019 (and its demo/test) is a FOLLOW-UP** — it cascades into the
golden catalog + `cdx trace`/`wiki` dogfood, which warrants its own slice on a
non-contended host. The endpoint stays as a now-unused API; the FRONTEND is fully
native-Astro (the user-visible "so many HTML" is resolved).

## Constraints
K0 (no engine dep). Deterministic static render (K10). The wikis remain the
single source — `cdx wiki` regenerates `feature-doc/*.md`, the Astro build
renders them.
