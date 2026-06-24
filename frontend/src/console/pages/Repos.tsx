import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../api/client";
import {
  linkToCoverage,
  linkToDocuments,
  linkToHealth,
  linkToMapping,
  linkToRepo,
} from "../routing";
import type { RegisteredRepo, RepoStatus } from "../types";

/** The slice of the API the page needs — fakeable in tests (no network). */
export interface ReposApi {
  listRepos(): Promise<RegisteredRepo[]>;
  repoStatus(repoId: string): Promise<RepoStatus>;
}

export interface ReposProps {
  /** Injected client; defaults to the shared singleton. */
  api?: ReposApi;
}

interface RepoRow {
  repo: RegisteredRepo;
  status: RepoStatus;
}

type LoadState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; rows: RepoRow[] };

type Signal = "sync" | "review" | "drift";

/** A repo's overall signal: drift if it has escalations, review if anything is
 *  unresolved, otherwise in-sync. */
function repoSignal(s: RepoStatus): Signal {
  if (s.escalations > 0) return "drift";
  if (s.unresolved > 0) return "review";
  return "sync";
}

function coverageSignal(ratio: number | null | undefined): Signal {
  if (ratio === null || ratio === undefined) return "review";
  if (ratio >= 0.9) return "sync";
  if (ratio >= 0.6) return "review";
  return "drift";
}

function formatCoverage(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "—";
  return `${(ratio * 100).toFixed(0)}%`;
}

export function Repos({ api = apiClient }: ReposProps) {
  const [state, setState] = useState<LoadState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });

    (async () => {
      try {
        const repos = await api.listRepos();
        const statuses = await Promise.all(
          repos.map((r) => api.repoStatus(r.repo.repo_id)),
        );
        if (cancelled) return;
        const rows: RepoRow[] = repos.map((repo, i) => ({
          repo,
          status: statuses[i],
        }));
        setState({ phase: "ready", rows });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err);
        setState({ phase: "error", message });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [api]);

  const head = (
    <div className="page-head">
      <div>
        <h1>Repositories</h1>
        <p className="lede">
          Every repository reporting to this central server, and how fresh its
          documentation is right now.
        </p>
      </div>
    </div>
  );

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        {head}
        <div className="panel">
          <div className="state" role="status">
            <span className="spinner" aria-hidden />
            Loading repositories…
          </div>
        </div>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        {head}
        <div className="panel">
          <p role="alert" className="state state--error">
            Failed to load repositories: {state.message}
          </p>
        </div>
      </section>
    );
  }

  if (state.rows.length === 0) {
    return (
      <section>
        {head}
        <div className="panel">
          <div className="empty">
            <div className="empty__mark">⌀</div>
            No repositories registered yet. Point a repo at this server with{" "}
            <code>cdx init --central</code> and it will appear here.
          </div>
        </div>
      </section>
    );
  }

  const { rows } = state;
  const inSync = rows.filter((r) => repoSignal(r.status) === "sync").length;
  const review = rows.filter((r) => repoSignal(r.status) === "review").length;
  const drift = rows.filter((r) => repoSignal(r.status) === "drift").length;
  const escalations = rows.reduce((n, r) => n + r.status.escalations, 0);

  return (
    <section>
      {head}

      <div className="metrics">
        <div className="metric">
          <span className="metric__k">Repositories</span>
          <span className="metric__v">{rows.length}</span>
          <span className="metric__foot">reporting in</span>
        </div>
        <div className="metric">
          <span className="metric__k">
            <span className="dot dot--sync" /> In sync
          </span>
          <span className="metric__v" data-tone="sync">
            {inSync}
          </span>
          <span className="metric__foot">docs fresh</span>
        </div>
        <div className="metric">
          <span className="metric__k">
            <span className="dot dot--review" /> Needs review
          </span>
          <span className="metric__v" data-tone="review">
            {review}
          </span>
          <span className="metric__foot">unresolved drift</span>
        </div>
        <div className="metric">
          <span className="metric__k">
            <span className="dot dot--drift" /> Escalations
          </span>
          <span className="metric__v" data-tone={escalations > 0 ? "drift" : undefined}>
            {escalations}
          </span>
          <span className="metric__foot">{drift} repo(s) drifting</span>
        </div>
      </div>

      <div className="panel">
        <div className="panel__head">
          <span className="panel__title">Fleet</span>
          <span className="panel__count">{rows.length} repos</span>
        </div>
        <table>
          <thead>
            <tr>
              <th scope="col">Repository</th>
              <th scope="col">Records</th>
              <th scope="col">OK</th>
              <th scope="col">Review</th>
              <th scope="col">Escalate</th>
              <th scope="col">Unresolved</th>
              <th scope="col">Coverage</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ repo, status }) => {
              const sig = repoSignal(status);
              const covSig = coverageSignal(status.coverage_ratio);
              const pct =
                status.coverage_ratio != null
                  ? Math.round(status.coverage_ratio * 100)
                  : 0;
              return (
                <tr key={repo.repo.repo_id}>
                  <th scope="row">
                    <div className="repo-cell">
                      <span className={`dot dot--${sig}`} aria-hidden />
                      <span>
                        <Link className="repo-id" to={linkToRepo(repo.repo.repo_id)}>
                          {repo.repo.repo_id}
                        </Link>
                        {repo.repo.repo_name ? (
                          <span className="repo-name"> ({repo.repo.repo_name})</span>
                        ) : null}
                        <span className="repo-links">
                          <Link
                            className="coverage-link"
                            to={linkToCoverage(repo.repo.repo_id)}
                          >
                            coverage
                          </Link>
                          <Link
                            className="health-link"
                            to={linkToHealth(repo.repo.repo_id)}
                          >
                            health
                          </Link>
                          <Link
                            className="documents-link"
                            to={linkToDocuments(repo.repo.repo_id)}
                          >
                            documents
                          </Link>
                          <Link
                            className="mapping-link"
                            to={linkToMapping(repo.repo.repo_id)}
                          >
                            mapping
                          </Link>
                        </span>
                      </span>
                    </div>
                  </th>
                  <td>{status.total_records}</td>
                  <td data-tone={(status.by_verdict.ok ?? 0) === 0 ? "zero" : undefined}>
                    {status.by_verdict.ok ?? 0}
                  </td>
                  <td data-tone={(status.by_verdict.review ?? 0) === 0 ? "zero" : undefined}>
                    {status.by_verdict.review ?? 0}
                  </td>
                  <td data-tone={status.escalations > 0 ? "drift" : "zero"}>
                    {status.escalations}
                  </td>
                  <td data-tone={status.unresolved === 0 ? "zero" : undefined}>
                    {status.unresolved}
                  </td>
                  <td>
                    <div className="cov">
                      <span className="cov__track">
                        <span
                          className="cov__fill"
                          data-tone={covSig}
                          style={{ width: `${pct}%` }}
                        />
                      </span>
                      <span className="cov__pct">{formatCoverage(status.coverage_ratio)}</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default Repos;
