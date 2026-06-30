// The in-repo tab bar. Once you click into a repo you land on the drift timeline
// (RepoDetail); from there the only other per-repo views (Mapping, Documents,
// Coverage, Health) used to be reachable ONLY via the fleet table. This bar makes
// them reachable from inside any repo. It is presentational — RepoRoute mounts it
// above every per-repo page. The active tab is derived from the SAME url-suffix
// logic RepoRoute uses to dispatch (base `/repos/:id` with no suffix = Drift).
import { Link, useLocation } from "react-router-dom";
import {
  linkToCoverage,
  linkToDependencies,
  linkToDocuments,
  linkToHealth,
  linkToMapping,
  linkToOwnership,
  linkToRepo,
  linkToWorklist,
} from "../routing";

export interface RepoNavProps {
  repoId: string;
}

/** Which view a per-repo pathname resolves to — mirrors RepoRoute's suffix
 * dispatch (and AppShell's `pageLabel`). The base path with no suffix is Drift. */
type View =
  | "drift"
  | "mapping"
  | "documents"
  | "dependencies"
  | "ownership"
  | "worklist"
  | "coverage"
  | "health";

function activeView(pathname: string): View {
  if (pathname.endsWith("/coverage")) return "coverage";
  if (pathname.endsWith("/health")) return "health";
  if (pathname.endsWith("/documents")) return "documents";
  if (pathname.endsWith("/dependencies")) return "dependencies";
  if (pathname.endsWith("/ownership")) return "ownership";
  if (pathname.endsWith("/worklist")) return "worklist";
  if (pathname.endsWith("/mapping")) return "mapping";
  return "drift";
}

export function RepoNav({ repoId }: RepoNavProps) {
  const { pathname } = useLocation();
  const active = activeView(pathname);

  // Mapping is ordered right after Drift so the document↔code hierarchy is the
  // prominent next stop after the timeline.
  const tabs: { view: View; label: string; to: string }[] = [
    { view: "drift", label: "Drift", to: linkToRepo(repoId) },
    { view: "mapping", label: "Mapping", to: linkToMapping(repoId) },
    { view: "documents", label: "Documents", to: linkToDocuments(repoId) },
    {
      view: "dependencies",
      label: "Dependencies",
      to: linkToDependencies(repoId),
    },
    { view: "ownership", label: "Ownership", to: linkToOwnership(repoId) },
    { view: "worklist", label: "Worklist", to: linkToWorklist(repoId) },
    { view: "coverage", label: "Coverage", to: linkToCoverage(repoId) },
    { view: "health", label: "Health", to: linkToHealth(repoId) },
  ];

  return (
    <nav className="repo-nav" aria-label="repo views">
      {tabs.map((tab) => {
        const isActive = tab.view === active;
        return (
          <Link
            key={tab.view}
            to={tab.to}
            className={`repo-nav__tab${isActive ? " repo-nav__tab--active" : ""}`}
            aria-current={isActive ? "page" : undefined}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default RepoNav;
