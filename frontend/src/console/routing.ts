// Repo ids may be the `org/name` form (a slash), but a react-router `:param`
// captures only ONE path segment. So the repo routes use a splat (`*`) and
// `RepoRoute` reconstructs the full id from the matched tail. `linkToRepo`/
// `linkToCoverage` are the inverse — they build the hrefs the splat route
// matches (each segment encoded, slashes preserved).

/** Build the detail href for a repo id (slashes preserved, segments encoded). */
export function linkToRepo(repoId: string): string {
  return `/repos/${encodePath(repoId)}`;
}

/** Build the coverage href for a repo id. */
export function linkToCoverage(repoId: string): string {
  return `/repos/${encodePath(repoId)}/coverage`;
}

/** Build the health href for a repo id. */
export function linkToHealth(repoId: string): string {
  return `/repos/${encodePath(repoId)}/health`;
}

/** Build the documents href for a repo id (W-01 relationship view). */
export function linkToDocuments(repoId: string): string {
  return `/repos/${encodePath(repoId)}/documents`;
}

/** Build the mapping href for a repo id (EDITOR E-09 — the document↔code map). */
export function linkToMapping(repoId: string): string {
  return `/repos/${encodePath(repoId)}/mapping`;
}

/** Build the href for the GLOBAL config/template reference page (W-02, not per-repo). */
export function linkToConfig(): string {
  return "/config";
}

/** Build the href for the GLOBAL server settings page (EPIC SVR, not per-repo). */
export function linkToSettings(): string {
  return "/settings";
}

function encodePath(repoId: string): string {
  return repoId
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}

/** Build the ownership href for a repo id (EPIC OWN — accountability view). */
export function linkToOwnership(repoId: string): string {
  return `/repos/${encodePath(repoId)}/ownership`;
}

/** Build the dependencies href for a repo id (EPIC B — the doc↔doc graph view). */
export function linkToDependencies(repoId: string): string {
  return `/repos/${encodePath(repoId)}/dependencies`;
}

/** Build the worklist href for a repo id (WL-01 — the per-owner review triage). */
export function linkToWorklist(repoId: string): string {
  return `/repos/${encodePath(repoId)}/worklist`;
}
