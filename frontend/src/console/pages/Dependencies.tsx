import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { DocGraph } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface DependenciesApi {
  docGraphFor(repoId: string): Promise<DocGraph>;
}

export interface DependenciesProps {
  api?: DependenciesApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

/**
 * The doc↔doc dependency graph (EPIC B). Renders the DECLARED `depends_on` edges
 * the central hub mirrors — who-depends-on-what across the repo's documents. The
 * per-edge SUSPECT freshness stays repo-local (the upstream's body must be hashed
 * where it lives, K2), so this hub view shows the structure, not the review status:
 * a reviewer runs `cdx deps` / `cdx check` in the repo for that.
 */
export function Dependencies({
  api = apiClient,
  repoId: repoIdProp,
}: DependenciesProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";

  const loader = useCallback(() => api.docGraphFor(repoId), [api, repoId]);
  const state = useApi<DocGraph>(loader, [loader]);

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        <h1>Dependencies</h1>
        <p role="status">Loading dependency graph…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        <h1>Dependencies</h1>
        <p role="alert" className="error">
          Failed to load dependencies: {state.message}
        </p>
      </section>
    );
  }

  const { edges } = state.data;

  if (edges.length === 0) {
    return (
      <section>
        <h1>
          Dependencies: <span className="repo-id">{repoId}</span>
        </h1>
        <p>No declared doc↔doc dependencies.</p>
      </section>
    );
  }

  const docCount = new Set(edges.map((e) => e.doc_id)).size;

  return (
    <section>
      <h1>
        Dependencies: <span className="repo-id">{repoId}</span>
      </h1>

      <p className="dep-summary">
        {edges.length} dependency edge(s) across {docCount} document(s) — the
        declared doc↔doc graph (who depends on what).
      </p>

      <div className="dep-graph panel">
        <table className="dep-table">
          <thead>
            <tr>
              <th scope="col">Document</th>
              <th scope="col">Depends on</th>
              <th scope="col">Relationship</th>
              <th scope="col">Audience</th>
            </tr>
          </thead>
          <tbody>
            {edges.map((edge) => (
              <tr key={`${edge.doc_id}->${edge.upstream_id}`}>
                <th scope="row">
                  <span className="repo-id" title={edge.doc_path}>
                    {edge.doc_id}
                  </span>
                </th>
                <td>
                  <span className="dep-upstream">{edge.upstream_id}</span>
                </td>
                <td>
                  <span className={`chip dep-type dep-type--${edge.type}`}>
                    {edge.type}
                  </span>
                </td>
                <td>
                  <span
                    className={`chip audience-chip audience-${edge.audience}`}
                  >
                    {edge.audience}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default Dependencies;
