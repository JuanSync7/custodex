import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { RepoHealth } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface HealthApi {
  healthFor(repoId: string): Promise<RepoHealth>;
}

export interface HealthProps {
  api?: HealthApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

function formatPct(ratio: number): string {
  return `${(ratio * 100).toFixed(0)}%`;
}

/** Humanise a duration in seconds; "—" when the metric is absent (no resolutions). */
function formatMttr(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export function Health({ api = apiClient, repoId: repoIdProp }: HealthProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";

  const loader = useCallback(() => api.healthFor(repoId), [api, repoId]);
  const state = useApi<RepoHealth>(loader, [loader]);

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        <h1>Health</h1>
        <p role="status">Loading health…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        <h1>Health</h1>
        <p role="alert" className="error">
          Failed to load health: {state.message}
        </p>
      </section>
    );
  }

  const h = state.data;
  const cards: { label: string; testid: string; value: string | number }[] = [
    { label: "Total records", testid: "stat-total", value: h.total },
    { label: "Escalations", testid: "stat-escalations", value: h.escalations },
    {
      label: "Escalation rate",
      testid: "stat-escalation-rate",
      value: formatPct(h.escalation_rate),
    },
    { label: "Resolved", testid: "stat-resolved", value: h.resolved },
    { label: "Unresolved", testid: "stat-unresolved", value: h.unresolved },
    { label: "Overrides", testid: "stat-overrides", value: h.overrides },
    { label: "MTTR", testid: "stat-mttr", value: formatMttr(h.mttr_seconds) },
  ];

  return (
    <section>
      <h1>
        Health: <span className="repo-id">{repoId}</span>
      </h1>
      <dl className="health-stats">
        {cards.map((card) => (
          <div key={card.testid} className="stat-card">
            <dt>{card.label}</dt>
            <dd data-testid={card.testid}>{card.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export default Health;
