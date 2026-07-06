import { useCallback, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { GraphEdge, GraphSnapshot } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface GraphApi {
  graphFor(repoId: string): Promise<GraphSnapshot>;
}

export interface GraphProps {
  api?: GraphApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

/** Count graph items per `kind` — the summary strip (deterministic order). */
function countByKind(items: { kind: string }[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const item of items) {
    counts.set(item.kind, (counts.get(item.kind) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

/** The client-side twin of kgraph.rank_centrality(undocumented_only=True):
 * MENTIONS in-degree per SYMBOL node with NO incoming DOCUMENTS edge — the
 * what-to-document feed, straight from the mirrored snapshot (edges are a set
 * upstream, so the count is DISTINCT mentioning docs, same as the CLI). */
function rankUndocumented(
  nodes: { id: string; kind: string }[],
  edges: GraphEdge[],
): [string, number][] {
  const symbolIds = new Set(
    nodes.filter((n) => n.kind === "symbol").map((n) => n.id),
  );
  const documented = new Set(
    edges.filter((e) => e.kind === "documents").map((e) => e.target),
  );
  const counts = new Map<string, number>();
  for (const e of edges) {
    if (e.kind !== "mentions") continue;
    if (!symbolIds.has(e.target) || documented.has(e.target)) continue;
    counts.set(e.target, (counts.get(e.target) ?? 0) + 1);
  }
  return [...counts.entries()].sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
  );
}

/**
 * AGT-03/AGT-07 — the knowledge-graph mirror view. Renders the LATEST snapshot
 * the repo pushed (`cdx graph` + `POST /repos/{id}/graph`): node/edge counts by
 * kind, the per-doc unresolved-mention rot signal, the top
 * mentioned-but-undocumented symbols (the what-to-document feed), and a
 * focus-node picker listing in/out edges — tables only, deliberately no
 * graph-viz dependency (the pinned AGT-07 contract).
 */
export function Graph({ api = apiClient, repoId: repoIdProp }: GraphProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";
  const [focus, setFocus] = useState<string>("");

  const loader = useCallback(() => api.graphFor(repoId), [api, repoId]);
  const state = useApi<GraphSnapshot>(loader, [loader]);

  const snapshot = state.phase === "ready" ? state.data : undefined;
  const nodes = useMemo(() => snapshot?.nodes ?? [], [snapshot]);
  const edges = useMemo(() => snapshot?.edges ?? [], [snapshot]);
  const ranked = useMemo(() => rankUndocumented(nodes, edges), [nodes, edges]);
  const focusEdges = useMemo(
    () =>
      focus
        ? edges.filter((e) => e.source === focus || e.target === focus)
        : [],
    [edges, focus],
  );

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        <h1>Knowledge Graph</h1>
        <p role="status">Loading knowledge graph…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        <h1>Knowledge Graph</h1>
        <p role="alert" className="error">
          Failed to load graph: {state.message}
        </p>
      </section>
    );
  }

  if (nodes.length === 0) {
    return (
      <section>
        <h1>
          Knowledge Graph: <span className="repo-id">{repoId}</span>
        </h1>
        <p className="coverage-summary">
          No graph snapshot yet — the repo computes it where the doc bodies
          live (K2). Run <code>cdx graph</code> in the repo and push the
          snapshot to <code>POST /repos/&#123;id&#125;/graph</code>.
        </p>
      </section>
    );
  }

  const unresolved = Object.entries(snapshot?.unresolved ?? {}).sort();
  const rotTotal = unresolved.reduce((sum, [, n]) => sum + n, 0);

  return (
    <section>
      <h1>
        Knowledge Graph: <span className="repo-id">{repoId}</span>
      </h1>

      <p className="dep-summary">
        {nodes.length} node(s), {edges.length} edge(s) — one deterministic fold
        of coverage (documents), dependencies (depends_on), prose mentions and
        links, sections and owners.
        {snapshot?.captured_at ? ` Captured ${snapshot.captured_at}.` : null}
      </p>

      <div className="panel">
        <h2>Nodes &amp; edges by kind</h2>
        <table className="worklist-table">
          <thead>
            <tr>
              <th scope="col">Node kind</th>
              <th scope="col">Count</th>
              <th scope="col">Edge kind</th>
              <th scope="col">Count</th>
            </tr>
          </thead>
          <tbody>
            {(() => {
              const nk = countByKind(nodes);
              const ek = countByKind(edges);
              const rows = Math.max(nk.length, ek.length);
              return [...Array(rows).keys()].map((i) => (
                <tr key={nk[i]?.[0] ?? ek[i]?.[0] ?? i}>
                  <th scope="row">{nk[i]?.[0] ?? ""}</th>
                  <td>{nk[i]?.[1] ?? ""}</td>
                  <td>{ek[i]?.[0] ?? ""}</td>
                  <td>{ek[i]?.[1] ?? ""}</td>
                </tr>
              ));
            })()}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Rot signal</h2>
        {rotTotal === 0 ? (
          <p className="coverage-summary">
            0 unresolved mentions — every prose reference resolves to a real
            referent. A nonzero count here is graph rot: prose pointing at
            code or files that no longer exist.
          </p>
        ) : (
          <table className="worklist-table">
            <thead>
              <tr>
                <th scope="col">Document</th>
                <th scope="col">Unresolved mentions</th>
              </tr>
            </thead>
            <tbody>
              {unresolved
                .filter(([, n]) => n > 0)
                .map(([docId, n]) => (
                  <tr key={docId}>
                    <th scope="row">{docId}</th>
                    <td>
                      <span className="chip chip--drift">{n}</span>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h2>What to document next</h2>
        {ranked.length === 0 ? (
          <p className="coverage-summary">
            No mentioned-but-undocumented symbols — everything the prose talks
            about is covered by a document.
          </p>
        ) : (
          <table className="worklist-table">
            <thead>
              <tr>
                <th scope="col">Symbol</th>
                <th scope="col">Mentioning docs</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map(([nodeId, count]) => (
                <tr key={nodeId}>
                  <th scope="row">
                    <span className="file-name">{nodeId}</span>
                  </th>
                  <td>{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h2>Focus a node</h2>
        <label>
          Node{" "}
          <select
            value={focus}
            onChange={(event) => setFocus(event.target.value)}
          >
            <option value="">— pick a node —</option>
            {[...nodes]
              .sort((a, b) => a.id.localeCompare(b.id))
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.id}
                </option>
              ))}
          </select>
        </label>
        {focus ? (
          focusEdges.length === 0 ? (
            <p className="coverage-summary">No edges touch this node.</p>
          ) : (
            <table className="worklist-table">
              <thead>
                <tr>
                  <th scope="col">Direction</th>
                  <th scope="col">Edge</th>
                  <th scope="col">Other node</th>
                  <th scope="col">Tier</th>
                </tr>
              </thead>
              <tbody>
                {focusEdges.map((e) => (
                  <tr key={`${e.source}:${e.kind}:${e.target}`}>
                    <td>{e.source === focus ? "out" : "in"}</td>
                    <td>{e.kind}</td>
                    <th scope="row">
                      <span className="file-name">
                        {e.source === focus ? e.target : e.source}
                      </span>
                    </th>
                    <td>{e.tier}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : null}
      </div>
    </section>
  );
}

export default Graph;
