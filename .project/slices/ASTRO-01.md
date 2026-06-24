# Slice ASTRO-01 — Astro foundation + single-origin serving rewire

EPIC ASTRO, phase 1. Stand up the `frontend/` Astro app and make the FastAPI
server serve its static build on the same port as the API — the foundation every
later slice (native wiki, console islands, dashboard retirement) builds on. No
content or console migration yet; this slice proves the toolchain + serving end
to end. (NB: "EPIC F" is the existing React+Vite dashboard epic — this re-platform
is EPIC ASTRO.)

## Goal (validable)
1. **An Astro app builds.** `frontend/` is an Astro project (`@astrojs/react` +
   `@astrojs/mdx`, `output: 'static'`). `npm --prefix frontend run build`
   (`astro check && astro build`) exits 0 and writes `frontend/dist/index.html`
   + `frontend/dist/_astro/*`. A base `Layout.astro` (design system: fonts,
   tokens, app chrome) + an `index.astro` landing render.
2. **The server serves it, single-origin.** `create_app(static_dir=...)` mounts
   the built site with `StaticFiles(html=True)` at `/` **after** every API route,
   so `/` → `index.html` and `/_astro/*` assets are served while every API route
   (`/health`, `/repos*`, `/config*`, `/wiki`, `/openapi.json`) still wins.
   `_default_static_dir()` resolves `<repo>/frontend/dist` first (falling back to
   `dashboard/dist` through ASTRO-03 so nothing breaks mid-migration).
3. **No engine dependency (K0).** Astro is frontend-only; no Python package gains
   a dep. `frontend/{node_modules,dist}` gitignored.

## Test plan (TDD)
- **integration (tests/integration/test_server.py):** over a `TestClient` with
  `static_dir` = a tmp dir holding a fake `index.html` + `_astro/app.js`:
  - `GET /` → 200, serves the `index.html` bytes (single-origin console).
  - `GET /_astro/app.js` → 200, the asset bytes (the new asset dir, not `assets`).
  - `GET /health` → 200 `{"status":"ok"}` — an API route still wins under the
    catch-all mount (declaration-order precedence).
  - `GET /openapi.json` → 200 (Swagger schema not shadowed).
  - no `static_dir` → `GET /` is the JSON landing payload (unchanged back-compat).
- **unit/integration:** `_default_static_dir()` prefers a present
  `frontend/dist/index.html`; falls back to `dashboard/dist`; `None` when neither.
- **frontend build smoke (manual + CI):** `npm --prefix frontend run build`
  exits 0; `frontend/dist/index.html` exists. Verified in-process (no curl).
- **gate:** ruff/mypy/pytest ≥90% branch green; `cdx check`/`lint` exit 0. No
  catalog change yet (serving is internal); FEAT-FRONTEND-* land in ASTRO-02/03.

## Design
See ARCHITECTURE.md `frontend/ Astro application` pin. The ONLY engine change is
the serving block in `server/app.py` (replace the `/assets` mount + `@app.get("/")`
FileResponse with a trailing `app.mount("/", StaticFiles(..., html=True))`) and
`_default_static_dir()`. The JSON `/wiki` endpoint stays in ASTRO-01 (retired in
ASTRO-02) so this slice is a pure additive serving change.

## Out of scope
Native wiki pages (ASTRO-02); porting the console pages/components/tests
(ASTRO-03); deleting `dashboard/` + CI rewire (ASTRO-04). No console UI redesign.

## Constraints
K0 (no engine dep; Astro frontend-only), K8 (absent build → graceful JSON landing,
never a crash), K10 (deterministic serving). Keep the API authoritative: the static
mount is LAST so it can never shadow a route.
