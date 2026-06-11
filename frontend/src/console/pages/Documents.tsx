import { useCallback, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import SyncControls, { type SyncControlsApi } from "../components/SyncControls";
import type { ConfigDocumentTree } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). The
 * sync methods are OPTIONAL: when absent, `<SyncControls>` uses the shared client. */
export interface DocumentsApi {
  documentsFor(repoId: string, syncKind?: string): Promise<ConfigDocumentTree[]>;
  syncState?: SyncControlsApi["syncState"];
  syncRepo?: SyncControlsApi["syncRepo"];
}

export interface DocumentsProps {
  api?: DocumentsApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

/** The two document sources the central server tracks (W-01 contract). */
const SYNC_KINDS = ["git", "local"] as const;
type SyncKind = (typeof SYNC_KINDS)[number];

export function Documents({ api = apiClient, repoId: repoIdProp }: DocumentsProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";

  // Which document rows are expanded to reveal their code_refs (doc_id set).
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // The document source; ALWAYS sent to the endpoint (it mixes git+local rows).
  const [syncKind, setSyncKind] = useState<SyncKind>("git");
  // Bumped after a sync so the loader re-runs and picks up freshly-synced docs.
  const [reload, setReload] = useState(0);

  const toggleExpanded = (docId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });

  const loader = useCallback(
    () => api.documentsFor(repoId, syncKind),
    // `reload` is a deliberate dep: a sync bumps it to force a re-fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [api, repoId, syncKind, reload],
  );
  const state = useApi<ConfigDocumentTree[]>(loader, [loader]);

  const head = (
    <>
      <h1>
        Documents: <span className="repo-id">{repoId}</span>
      </h1>
      <SyncControls
        repoId={repoId}
        api={api}
        syncKind={syncKind}
        onSynced={() => setReload((n) => n + 1)}
      />
      <form
        className="sync-kind-toggle"
        aria-label="sync kind"
        onSubmit={(e) => e.preventDefault()}
      >
        <label>
          Source
          <select
            value={syncKind}
            onChange={(e) => setSyncKind(e.target.value as SyncKind)}
          >
            {SYNC_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
      </form>
    </>
  );

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        {head}
        <p role="status">Loading documents…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        {head}
        <p role="alert" className="error">
          Failed to load documents: {state.message}
        </p>
      </section>
    );
  }

  if (state.data.length === 0) {
    return (
      <section>
        {head}
        <p>No documents configured for this repo.</p>
      </section>
    );
  }

  return (
    <section>
      {head}
      <div className="documents-table panel">
        <table>
          <thead>
            <tr>
              <th scope="col">Document</th>
              <th scope="col">Audience</th>
              <th scope="col">Unit</th>
              <th scope="col">Regions</th>
              <th scope="col">Code refs</th>
            </tr>
          </thead>
          <tbody>
            {state.data.map((tree) => {
              const doc = tree.document;
              const isOpen = expanded.has(doc.doc_id);
              const refCount = tree.code_refs.length;
              return (
                <RowFragment key={doc.doc_id}>
                  <tr>
                    <th scope="row">
                      <span className="doc-id">{doc.doc_id}</span>
                      <span className="doc-path"> ({doc.path})</span>
                    </th>
                    <td>
                      <span className="badge audience-badge">{doc.audience}</span>
                    </td>
                    <td>
                      <span className="chip unit-chip">{doc.unit}</span>
                    </td>
                    <td>
                      {doc.region_keys.length > 0 ? (
                        <span className="region-chips">
                          {doc.region_keys.map((key) => (
                            <span key={key} className="chip region-chip">
                              {key}
                            </span>
                          ))}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="ticket-toggle"
                        aria-expanded={isOpen}
                        onClick={() => toggleExpanded(doc.doc_id)}
                      >
                        {`${isOpen ? "Hide" : "View"} ${refCount} ref${
                          refCount === 1 ? "" : "s"
                        }`}
                      </button>
                    </td>
                  </tr>
                  {isOpen ? (
                    <tr className="code-refs-row">
                      <td colSpan={5}>
                        <CodeRefs tree={tree} />
                      </td>
                    </tr>
                  ) : null}
                </RowFragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** A transparent grouping so a document can render its row + an optional detail row. */
function RowFragment({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

/** The expanded relationship view: the code surfaces a document owns. */
function CodeRefs({ tree }: { tree: ConfigDocumentTree }) {
  if (tree.code_refs.length === 0) {
    return (
      <div className="code-refs panel">
        <p className="code-refs__empty">No code refs for this document.</p>
      </div>
    );
  }
  return (
    <div className="code-refs panel">
      <ul className="code-refs__list">
        {tree.code_refs.map((ref) => (
          <li key={ref.path} className="code-refs__item">
            <span className="file-path">{ref.path}</span>
            {ref.symbols.length > 0 ? (
              <span className="symbol-chips">
                {ref.symbols.map((sym) => (
                  <span key={sym} className="chip symbol-chip">
                    {sym}
                  </span>
                ))}
              </span>
            ) : (
              <span className="code-refs__nosymbols">whole file</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default Documents;
