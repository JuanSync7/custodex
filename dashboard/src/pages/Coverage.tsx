import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { CoverageFile, CoverageSnapshot } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface CoverageApi {
  coverageFor(repoId: string): Promise<CoverageSnapshot[]>;
}

export interface CoverageProps {
  api?: CoverageApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

function formatPct(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "—";
  return `${(ratio * 100).toFixed(0)}%`;
}

function basket(value: number | null | undefined): number | string {
  return value === null || value === undefined ? "—" : value;
}

/** File status → DRIFT CONSOLE signal dot: documented→sync, undocumented→drift, waived→review. */
const STATUS_DOT: Record<CoverageFile["status"], string> = {
  documented: "dot--sync",
  undocumented: "dot--drift",
  waived: "dot--review",
};

export function Coverage({ api = apiClient, repoId: repoIdProp }: CoverageProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";

  const loader = useCallback(
    () => api.coverageFor(repoId),
    [api, repoId],
  );
  const state = useApi<CoverageSnapshot[]>(loader, [loader]);

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        <h1>Coverage</h1>
        <p role="status">Loading coverage…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        <h1>Coverage</h1>
        <p role="alert" className="error">
          Failed to load coverage: {state.message}
        </p>
      </section>
    );
  }

  if (state.data.length === 0) {
    return (
      <section>
        <h1>Coverage</h1>
        <p>No coverage reported yet.</p>
      </section>
    );
  }

  // The server returns snapshots latest-last; the dashboard shows the latest.
  const latest = state.data[state.data.length - 1];
  const files = latest.files;

  return (
    <section>
      <h1>
        Coverage: <span className="repo-id">{repoId}</span>
      </h1>

      <p className="coverage-pct">
        <strong>{formatPct(latest.ratio)}</strong> documented
      </p>

      <dl className="coverage-baskets">
        <div>
          <dt>Documented</dt>
          <dd className="basket-documented">{basket(latest.documented)}</dd>
        </div>
        <div>
          <dt>Undocumented</dt>
          <dd className="basket-undocumented">{basket(latest.undocumented)}</dd>
        </div>
        <div>
          <dt>Waived</dt>
          <dd className="basket-waived">{basket(latest.waived)}</dd>
        </div>
      </dl>

      {files && files.length > 0 ? (
        <div className="coverage-files panel">
          <p className="coverage-summary">
            {basket(latest.documented)} documented · {basket(latest.undocumented)}{" "}
            gaps · {basket(latest.waived)} waived
          </p>
          <table>
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Status</th>
                <th scope="col">Owners</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.path}>
                  <th scope="row">
                    <span className="file-path">{file.path}</span>
                  </th>
                  <td>
                    <span className={`file-status status-${file.status}`}>
                      <span
                        className={`dot ${STATUS_DOT[file.status]}`}
                        aria-hidden="true"
                      />
                      {file.status}
                    </span>
                  </td>
                  <td>
                    {file.owners.length > 0 ? (
                      <span className="owner-chips">
                        {file.owners.map((owner) => (
                          <span key={owner} className="chip owner-chip">
                            {owner}
                          </span>
                        ))}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{file.status === "waived" ? file.waived_reason ?? "" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export default Coverage;
