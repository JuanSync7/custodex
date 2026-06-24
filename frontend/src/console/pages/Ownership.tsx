import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { OwnershipData, StalenessData } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface OwnershipApi {
  ownershipFor(repoId: string): Promise<OwnershipData>;
  stalenessFor(repoId: string): Promise<StalenessData>;
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

/** Staleness status → signal dot + colour class (stale is a hard signal). */
const SLA_DOT: Record<string, string> = {
  fresh: "dot--sync",
  stale: "dot--drift",
  never_reviewed: "dot--review",
};
const SLA_STATUS: Record<string, string> = {
  fresh: "status-documented",
  stale: "status-undocumented",
  never_reviewed: "status-waived",
};

export function Ownership({ api = apiClient, repoId: repoIdProp }: OwnershipProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";

  const loader = useCallback(() => api.ownershipFor(repoId), [api, repoId]);
  const state = useApi<OwnershipData>(loader, [loader]);

  const slaLoader = useCallback(() => api.stalenessFor(repoId), [api, repoId]);
  const slaState = useApi<StalenessData>(slaLoader, [slaLoader]);

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
          an accountable owner has departed. Reassign by updating the document's{" "}
          <code>owner</code>/<code>team</code>/<code>dri</code> in{" "}
          <code>config/cdmon</code> (the <code>reassign_owner</code> config edit
          writes it to disk).
        </p>
      ) : (
        <p className="coverage-summary">
          Every document has an active accountable owner.
        </p>
      )}

      <table className="coverage-tree ownership-table">
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
            const departed = status.startsWith("orphan_");
            return (
              <tr key={o.doc_id}>
                <th scope="row">
                  <span className="file-name" title={o.doc_path}>
                    {o.doc_id}
                  </span>
                </th>
                <td>
                  {departed ? (
                    <span className="owner-departed">
                      <s>{o.accountable ?? "—"}</s>
                      <span className="badge departed">departed</span>
                    </span>
                  ) : (
                    (o.accountable ?? "—")
                  )}
                </td>
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
                  {finding?.detail ? (
                    <span className="sr-only">{finding.detail}</span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h2>Review SLA</h2>
      {slaState.phase === "loading" ? (
        <p role="status">Loading review status…</p>
      ) : slaState.phase === "error" ? (
        <p role="alert" className="error">
          Failed to load review status: {slaState.message}
        </p>
      ) : slaState.data.stale_count > 0 ? (
        <>
          <p role="status" className="error">
            {slaState.data.stale_count} document
            {slaState.data.stale_count === 1 ? "" : "s"} need a review — past the SLA
            or never reviewed. The accountable owner should re-review (stamp{" "}
            <code>reviewed</code> in <code>config/cdmon</code> or run{" "}
            <code>cdx staleness</code>).
          </p>
          <ul className="settings-secrets">
            {slaState.data.findings
              .filter((f) => f.status !== "fresh")
              .map((f) => (
                <li key={f.doc_id}>
                  <span
                    className={`file-status ${SLA_STATUS[f.status] ?? ""}`}
                    title={f.detail}
                  >
                    <span
                      className={`dot ${SLA_DOT[f.status] ?? "dot--sync"}`}
                      aria-hidden="true"
                    />
                    {f.doc_id}: {statusLabel(f.status)}
                  </span>
                  <span className="sr-only">{f.detail}</span>
                </li>
              ))}
          </ul>
        </>
      ) : (
        <p className="coverage-summary">
          Every document is within its review SLA.
        </p>
      )}
    </section>
  );
}

export default Ownership;
