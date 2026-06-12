import { useCallback, useState, type CSSProperties } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import { buildCoverageRows, dirPaths, isRowVisible } from "../lib/grouping";
import type { CoverageFile, CoverageSnapshot } from "../types";

/** Indentation (rem) applied per tree level so the hierarchy reads as a tree. */
const INDENT_REM = 1.25;

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

  // Collapse/expand the directory hierarchy: a set of COLLAPSED dir paths (empty
  // ⇒ fully expanded, the default). A row is hidden when an ancestor dir is
  // collapsed (see isRowVisible). Declared before the early returns (Rules of Hooks).
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggleDir = (path: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

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
  const rows = files ? buildCoverageRows(files) : [];
  const visibleRows = rows.filter((row) => isRowVisible(row, collapsed));
  const allDirs = dirPaths(rows);

  return (
    <section>
      <h1>
        Coverage: <span className="repo-id">{repoId}</span>
      </h1>

      <p
        className="coverage-pct"
        style={{ "--ratio": latest.ratio ?? 0 } as CSSProperties}
      >
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
          <div className="coverage-files__head">
            <p className="coverage-summary">
              {basket(latest.documented)} documented ·{" "}
              {basket(latest.undocumented)} gaps · {basket(latest.waived)} waived
            </p>
            {allDirs.length > 0 ? (
              <div className="coverage-tree__controls" role="group" aria-label="hierarchy">
                <button type="button" onClick={() => setCollapsed(new Set())}>
                  Expand all
                </button>
                <button type="button" onClick={() => setCollapsed(new Set(allDirs))}>
                  Collapse all
                </button>
              </div>
            ) : null}
          </div>
          <table className="coverage-tree">
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Status</th>
                <th scope="col">Owners</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {/* Files are shown as a COLLAPSIBLE directory hierarchy (a tree)
                  rather than a flat list of repo-relative paths: each directory is
                  a clickable header row (toggles its subtree) with a status
                  roll-up, its files indented beneath it. Only rows whose ancestor
                  directories are all expanded are rendered (isRowVisible). */}
              {visibleRows.map((row) =>
                row.kind === "dir" ? (
                  <tr key={`dir:${row.path}`} className="coverage-dir-row">
                    <th scope="row" colSpan={4}>
                      <button
                        type="button"
                        className="coverage-dir"
                        aria-expanded={!collapsed.has(row.path)}
                        onClick={() => toggleDir(row.path)}
                        style={{ paddingLeft: `${row.depth * INDENT_REM}rem` }}
                      >
                        <span className="coverage-dir__chevron" aria-hidden="true">
                          {collapsed.has(row.path) ? "▸" : "▾"}
                        </span>
                        <span className="coverage-dir__name">{row.name}/</span>
                        <span className="coverage-dir__counts">
                          {row.counts!.documented} documented ·{" "}
                          {row.counts!.undocumented} gaps · {row.counts!.waived}{" "}
                          waived
                        </span>
                      </button>
                    </th>
                  </tr>
                ) : (
                  <tr key={`file:${row.path}`}>
                    <th scope="row">
                      <span
                        className="file-name"
                        style={{
                          paddingLeft: `${row.depth * INDENT_REM}rem`,
                        }}
                        title={row.path}
                      >
                        {row.name}
                      </span>
                    </th>
                    <td>
                      <span className={`file-status status-${row.file!.status}`}>
                        <span
                          className={`dot ${STATUS_DOT[row.file!.status]}`}
                          aria-hidden="true"
                        />
                        {row.file!.status}
                      </span>
                    </td>
                    <td>
                      {row.file!.owners.length > 0 ? (
                        <span className="owner-chips">
                          {row.file!.owners.map((owner) => (
                            <span key={owner} className="chip owner-chip">
                              {owner}
                            </span>
                          ))}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {row.file!.status === "waived"
                        ? row.file!.waived_reason ?? ""
                        : ""}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export default Coverage;
