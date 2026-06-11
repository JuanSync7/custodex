# Slice ASTRO-04 — retire `dashboard/`, finalize serving + docs

EPIC ASTRO, phase 4 (close-out). With the console + native wiki living under
`frontend/` and served single-origin, remove the superseded EPIC-F `dashboard/`
SPA and finalize the wiring.

## Goal (validable)
1. **Delete `dashboard/`.** The React+Vite SPA is fully ported to
   `frontend/src/console/`; remove the directory. No Python code outside it
   referenced it (only `server/app.py::_default_static_dir`'s fallback string).
2. **Drop the legacy fallback.** `_default_static_dir()` resolves ONLY
   `frontend/dist` now (the `dashboard/dist` fallback existed to keep serving
   mid-migration; the dashboard is gone). Its test drops the dashboard case.
3. **Docs/packaging.** README points at `frontend/` (build/dev/test). `.gitignore`
   keeps `frontend/{node_modules,dist,.astro}` ignored; the `dashboard/*` ignores
   are removed with the dir. No pyproject change (it never referenced dashboard).
4. **CI (optional, parity).** The dashboard had NO CI job; a `frontend:build`
   GitLab job (npm ci + `astro build` + `vitest run`) is a nice-to-have, gated on
   a runner with Node — added if it does not destabilize the offline default.

## Test plan
- Full Python gate green after the `_default_static_dir` change (its test now
  asserts `frontend/dist` only; `dashboard/dist` no longer resolved).
- `git grep -n dashboard` outside `.project/` history + `feature-doc/wiki/` shows
  no live code reference.
- Frontend build + Vitest still green; in-process serve of `frontend/dist` works.

## Out of scope
The server `GET /wiki` JSON retirement (the ASTRO-02 follow-up — cascades into the
golden catalog dogfood). Historical `.project/slices/F-*.md` are NOT rewritten
(they record the dashboard era faithfully).

## Constraints
K0/K8/K10 unchanged. The deletion must not red the Python gate (the serving tests
use tmp dirs; `_default_static_dir` is the only dashboard touchpoint).
