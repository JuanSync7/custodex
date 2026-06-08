// The `/repos/*` splat lands here. Because a repo id may contain slashes, we
// can't use a fixed `:repoId/coverage` route — so this dispatcher inspects the
// captured tail: a `…/coverage` suffix renders Coverage, anything else renders
// the drift timeline. (See routing.ts for the link/parse helpers.)
import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import RepoNav from "../components/RepoNav";
import Coverage from "./Coverage";
import Documents from "./Documents";
import Health from "./Health";
import Mapping from "./Mapping";
import RepoDetail from "./RepoDetail";

function decodePath(tail: string): string {
  return tail
    .replace(/\/$/, "")
    .split("/")
    .map((seg) => decodeURIComponent(seg))
    .join("/");
}

/** Resolve the repo id (suffix-stripped) and the page to render for a given tail. */
function dispatch(tail: string): { repoId: string; page: ReactNode } {
  if (tail.endsWith("/coverage")) {
    const repoId = decodePath(tail.slice(0, -"/coverage".length));
    return { repoId, page: <Coverage repoId={repoId} /> };
  }
  if (tail.endsWith("/health")) {
    const repoId = decodePath(tail.slice(0, -"/health".length));
    return { repoId, page: <Health repoId={repoId} /> };
  }
  if (tail.endsWith("/documents")) {
    const repoId = decodePath(tail.slice(0, -"/documents".length));
    return { repoId, page: <Documents repoId={repoId} /> };
  }
  if (tail.endsWith("/mapping")) {
    const repoId = decodePath(tail.slice(0, -"/mapping".length));
    return { repoId, page: <Mapping repoId={repoId} /> };
  }
  const repoId = decodePath(tail);
  return { repoId, page: <RepoDetail repoId={repoId} /> };
}

export function RepoRoute() {
  const params = useParams();
  const tail = params["*"] ?? "";
  // The in-repo tab bar is rendered ABOVE every per-repo view so the other repo
  // pages (Mapping/Documents/Coverage/Health) stay reachable from inside a repo.
  // It only lives here, under the `/repos/*` route — never on `/` or `/config`.
  const { repoId, page } = dispatch(tail);
  return (
    <>
      <RepoNav repoId={repoId} />
      {page}
    </>
  );
}

export default RepoRoute;
