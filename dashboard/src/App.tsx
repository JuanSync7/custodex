import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import Config from "./pages/Config";
import Repos from "./pages/Repos";
import RepoRoute from "./pages/RepoRoute";

// The full Feature Wiki page is code-split: its bundle (and its `api.wiki()`
// fetch) load ONLY when the Wiki nav item is clicked ("show Wiki first, switch
// on click" — R-09). `React.lazy` + the `<Suspense>` boundary below.
const Wiki = lazy(() => import("./pages/Wiki"));

// The base shell (AppShell) frames every view; routes render into it.
//   /                       → Repos — the fleet overview (F-01)
//   /repos/:repoId          → drift timeline (F-02)
//   /repos/:repoId/coverage  → coverage snapshot (F-03)
//   /repos/:repoId/health    → health & telemetry (F-05)
//   /repos/:repoId/documents → documents & relationship view (W-01)
//   /repos/:repoId/mapping   → editable document↔code mapping (EDITOR E-09)
//   /config                  → config/cdmon/ format reference (W-02, GLOBAL)
//   /wiki                    → the EPIC-R feature wikis (R-09, GLOBAL, lazy)
// A repo id may contain a slash (org/name), which a `:param` can't capture, so a
// single `/repos/*` splat lands on `RepoRoute`, which reconstructs the id and
// dispatches to the timeline / coverage / health view.
export function App() {
  return (
    <AppShell>
      <Suspense fallback={<p role="status">Loading…</p>}>
        <Routes>
          <Route path="/" element={<Repos />} />
          <Route path="/config" element={<Config />} />
          <Route path="/wiki" element={<Wiki />} />
          <Route path="/repos/*" element={<RepoRoute />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}

export default App;
