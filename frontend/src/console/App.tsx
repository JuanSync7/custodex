import { Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import Config from "./pages/Config";
import Repos from "./pages/Repos";
import RepoRoute from "./pages/RepoRoute";

// The base shell (AppShell) frames every view; routes render into it.
//   /                        → Repos — the fleet overview (F-01)
//   /repos/:repoId           → drift timeline (F-02)
//   /repos/:repoId/coverage  → coverage snapshot (F-03)
//   /repos/:repoId/health    → health & telemetry (F-05)
//   /repos/:repoId/documents → documents & relationship view (W-01)
//   /repos/:repoId/mapping   → editable document↔code mapping (EDITOR E-09)
//   /config                  → config/cdmon/ format reference (W-02, GLOBAL)
// The feature wikis are NOW native Astro pages at `/wiki/*` (EPIC ASTRO) — reached
// via a real link in AppShell, not a client route here (no more React Wiki page).
// A repo id may contain a slash (org/name), which a `:param` can't capture, so a
// single `/repos/*` splat lands on `RepoRoute`, which reconstructs the id and
// dispatches to the timeline / coverage / health view.
export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Repos />} />
        <Route path="/config" element={<Config />} />
        <Route path="/repos/*" element={<RepoRoute />} />
      </Routes>
    </AppShell>
  );
}

export default App;
