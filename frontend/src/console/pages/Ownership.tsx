import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { OwnershipData } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface OwnershipApi {
  ownershipFor(repoId: string): Promise<OwnershipData>;
}

export interface OwnershipProps {
  api?: OwnershipApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

/** Ownership status → DRIFT CONSOLE signal dot. A departed-owner orphan is a hard
 * drift signal; a vacant-DRI / unowned doc is a softer review signal; ok is sync. */
const STATUS_DOT: Record<string, string> = {
  ok: "dot--sync",
  unowned: "dot--review",
  orphan_dri_vacant: "dot--review",
  orphan_owner_departed: "dot--drift",
};

function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

export function Ownership({ api = apiClient, repoId: repoIdProp }: OwnershipProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";

  const loader = useCallback(() => api.ownershipFor(repoId), [api, repoId]);
  const state = useApi<OwnershipData>(loader, [loader]);

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        <h1>Ownership</h1>
        <p role="status">Loading ownership…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        <h1>Ownership</h1>
        <p role="alert" className="error">
          Failed to load ownership: {state.message}
        </p>
      </section>
    );
  }

  const { owners, findings, orphan_count } = state.data;
  const findingByDoc = new Map(findings.map((f) => [f.doc_id, f]));

  if (owners.length === 0) {
    return (
      <section>
        <h1>
          Ownership: <span className="repo-id">{repoId}</span>
        </h1>
        <p>
          No ownership recorded yet — declare an <code>owner</code>/<code>team</code>/
          <code>dri</code> in <code>config/cdmon/*.yaml</code>.
        </p>
      </section>
    );
  }

  return (
    <section>
      <h1>
        Ownership: <span className="repo-id">{repoId}</span>
      </h1>

      {orphan_count > 0 ? (
        <p role="status" className="error">
          {orphan_count} document{orphan_count === 1 ? "" : "s"} need a new owner —
          an accountable owner has departed. Reassign on the Mapping page.
        </p>
      ) : (
        <p className="coverage-summary">
          Every document has an active accountable owner.
        </p>
      )}

      <table className="coverage-tree">
        <thead>
          <tr>
            <th scope="col">Document</th>
            <th scope="col">Accountable</th>
            <th scope="col">Team</th>
            <th scope="col">DRI</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {owners.map((o) => {
            const finding = findingByDoc.get(o.doc_id);
            const status = finding ? finding.status : "ok";
            return (
              <tr key={o.doc_id}>
                <th scope="row">
                  <span className="file-name" title={o.doc_path}>
                    {o.doc_id}
                  </span>
                </th>
                <td>{o.accountable ?? "—"}</td>
                <td>{o.team ?? "—"}</td>
                <td>{o.dri ?? "—"}</td>
                <td>
                  <span
                    className={`file-status status-${status}`}
                    title={finding?.detail}
                  >
                    <span
                      className={`dot ${STATUS_DOT[status] ?? "dot--sync"}`}
                      aria-hidden="true"
                    />
                    {statusLabel(status)}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

export default Ownership;
