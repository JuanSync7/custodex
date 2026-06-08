# code-doc-monitor dashboard

A Vite + React + TypeScript SPA that reads the central server (EPIC-E) and
visualises registered repos and their drift status. Frontend-only — it is not a
Python module and is not tracked by `cdmon`.

## Develop

```bash
cd dashboard
npm install            # first time (commits package-lock.json)
npm run dev            # Vite dev server (default http://localhost:5173)
```

`npm run dev` proxies `/api/*` to the FastAPI server at `http://127.0.0.1:8000`
(the `/api` prefix is stripped). Run the server alongside it:

```bash
# from the repo root
.venv/bin/uvicorn code_doc_monitor.server.app:app --reload
```

The API base URL is `import.meta.env.VITE_API_BASE` (default `/api`); set
`VITE_API_BASE` to point at a different deployment.

## Gate

```bash
cd dashboard
npm install
npm run lint           # ESLint, clean
npm run test:run       # Vitest (jsdom), all green, no network (API is mocked)
npm run build          # tsc -b && vite build → dist/, zero TS errors
```

## Layout

- `src/types.ts` — TS mirrors of the server models (`RegisteredRepo`,
  `RepoStatus`, `Verdict`). F-02+ can generate record types from `cdmon schema`.
- `src/api/client.ts` — typed `ApiClient` over the OPEN read endpoints
  (`GET /repos`, `GET /repos/{id}/status`). `fetch` is injectable for tests.
- `src/pages/Repos.tsx` — the repos+status table with loading/error/empty states.
  The API client is injectable (prop) so component tests pass a fake — no network.
- `src/App.tsx` — single route (F-01); F-02/03/04 add routes.
