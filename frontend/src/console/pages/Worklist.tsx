import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { WorkReason, WorkSeverity, Worklist as WorklistData } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface WorklistApi {
  worklistFor(repoId: string): Promise<WorklistData>;
}

export interface WorklistProps {
  api?: WorklistApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

/** Severity → DRIFT CONSOLE signal chip: high→drift, medium→review, low→sync.
 * Mirrors RepoDetail's ticket SEVERITY_CHIP so the worklist reads the same. */
const SEVERITY_CHIP: Record<WorkSeverity, string> = {
  high: "chip--drift",
  medium: "chip--review",
  low: "chip--sync",
};

/** Reason → signal dot: an orphan is a hard drift signal; a stale/suspect doc is
 * a softer review signal. Mirrors the Ownership/Staleness dot mapping. */
const REASON_DOT: Record<WorkReason, string> = {
  orphan: "dot--drift",
  stale: "dot--review",
  suspect: "dot--review",
};

/**
 * WL-01 — the per-owner review worklist. Triages what needs a human's review,
 * grouped by the accountable owner (or the "Unowned" bucket for `null`): orphaned
 * docs (a departed owner), stale docs (past the review SLA), and suspect docs (an
 * upstream changed). Per-edge suspect freshness stays repo-local (K2), so the HUB
 * view sets `includes_suspect = false` and a banner points the reviewer at
 * `cdx worklist` in the repo for the full picture.
 */
export function Worklist({ api = apiClient, repoId: repoIdProp }: WorklistProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";

  const loader = useCallback(() => api.worklistFor(repoId), [api, repoId]);
  const state = useApi<WorklistData>(loader, [loader]);

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        <h1>Worklist</h1>
        <p role="status">Loading review worklist…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        <h1>Worklist</h1>
        <p role="alert" className="error">
          Failed to load worklist: {state.message}
        </p>
      </section>
    );
  }

  const { owners, item_count, doc_count, includes_suspect } = state.data;

  if (item_count === 0) {
    return (
      <section>
        <h1>
          Worklist: <span className="repo-id">{repoId}</span>
        </h1>
        <p className="coverage-summary">
          All clear — nothing needs review. Every document has an active owner and
          is within its review SLA.
        </p>
      </section>
    );
  }

  return (
    <section>
      <h1>
        Worklist: <span className="repo-id">{repoId}</span>
      </h1>

      <p className="dep-summary">
        {item_count} item(s) across {doc_count} document(s) need review — the
        per-owner triage of what is orphaned, stale, or suspect.
      </p>

      {includes_suspect ? null : (
        <p role="status" className="coverage-summary">
          The hub omits <strong>suspect</strong> items: per-edge freshness stays
          repo-local (K2 — the upstream's body is hashed where it lives). Run{" "}
          <code>cdx worklist</code> in the repo for the full picture.
        </p>
      )}

      {owners.map((owner) => {
        const name = owner.accountable ?? "Unowned";
        return (
          <div key={name} className="worklist-owner panel">
            <div className="worklist-owner__head">
              <h2>
                {owner.accountable ? (
                  name
                ) : (
                  <span className="worklist-owner__unowned">Unowned</span>
                )}
              </h2>
              <span className="worklist-owner__counts">
                {owner.item_count} item{owner.item_count === 1 ? "" : "s"} ·{" "}
                {owner.doc_count} doc{owner.doc_count === 1 ? "" : "s"}
              </span>
            </div>

            <table className="worklist-table">
              <thead>
                <tr>
                  <th scope="col">Severity</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Document</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {owner.items.map((item) => (
                  <tr key={`${item.doc_id}:${item.reason}:${item.upstream_id ?? ""}`}>
                    <td>
                      <span className={`chip ${SEVERITY_CHIP[item.severity]}`}>
                        {item.severity}
                      </span>
                    </td>
                    <td>
                      <span className="worklist-reason">
                        <span
                          className={`dot ${REASON_DOT[item.reason]}`}
                          aria-hidden="true"
                        />
                        {item.reason}
                      </span>
                    </td>
                    <th scope="row">
                      <span className="file-name" title={item.doc_path}>
                        {item.doc_id}
                      </span>
                      {item.reason === "suspect" && item.upstream_id ? (
                        <span className="worklist-upstream">
                          {" → "}
                          {item.upstream_id}
                        </span>
                      ) : null}
                    </th>
                    <td>{item.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </section>
  );
}

export default Worklist;
