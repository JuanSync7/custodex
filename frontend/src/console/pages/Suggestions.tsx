import { useCallback, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { SuggestionsData, WorkSeverity } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface SuggestionsApi {
  suggestionsFor(
    repoId: string,
    includeClosed?: boolean,
  ): Promise<SuggestionsData>;
  dismissSuggestion(
    repoId: string,
    key: string,
    token: string,
  ): Promise<{ repo_id: string; key: string; status: string }>;
}

export interface SuggestionsProps {
  api?: SuggestionsApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

/** Severity → signal chip — the SAME mapping the Worklist uses. */
const SEVERITY_CHIP: Record<WorkSeverity, string> = {
  high: "chip--drift",
  medium: "chip--review",
  low: "chip--sync",
};

/**
 * AGT-06/AGT-07 — the worker suggestion inbox. Pending items are CURRENT
 * reality (the server reconciles every tick: vanished items auto-resolve,
 * reappearing ones reopen); the closed section (resolved + dismissed) is the
 * visibly-separated audit trail (the pinned contract). Dismiss is the durable
 * human 'no' (K11) — token-less first, the token input reveals on 401/403
 * (the Mapping/SyncControls UX).
 */
export function Suggestions({
  api = apiClient,
  repoId: repoIdProp,
}: SuggestionsProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";
  const [token, setToken] = useState("");
  const [needsToken, setNeedsToken] = useState(false);
  const [dismissError, setDismissError] = useState<string | null>(null);
  const [dismissedKeys, setDismissedKeys] = useState<Set<string>>(new Set());

  const loader = useCallback(
    () => api.suggestionsFor(repoId, true),
    [api, repoId],
  );
  const state = useApi<SuggestionsData>(loader, [loader]);

  const dismiss = useCallback(
    async (key: string) => {
      setDismissError(null);
      try {
        await api.dismissSuggestion(repoId, key, token.trim());
        setDismissedKeys((prev) => new Set(prev).add(key));
        setNeedsToken(false);
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          setNeedsToken(true);
          setDismissError(
            error.status === 401
              ? "Auth required: a valid repo token is needed to dismiss."
              : "Auth invalid: that token was rejected.",
          );
        } else {
          setDismissError(
            error instanceof Error ? error.message : "dismiss failed",
          );
        }
      }
    },
    [api, repoId, token],
  );

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        <h1>Suggestions</h1>
        <p role="status">Loading suggestion inbox…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        <h1>Suggestions</h1>
        <p role="alert" className="error">
          Failed to load suggestions: {state.message}
        </p>
      </section>
    );
  }

  const all = state.data.suggestions;
  const pending = all.filter(
    (s) => s.status === "pending" && !dismissedKeys.has(s.key),
  );
  const closed = all.filter(
    (s) => s.status !== "pending" || dismissedKeys.has(s.key),
  );

  if (all.length === 0) {
    return (
      <section>
        <h1>
          Suggestions: <span className="repo-id">{repoId}</span>
        </h1>
        <p className="coverage-summary">
          The inbox is empty — the background suggesters found nothing to fix,
          resolve, document or map (or the workers have not run yet:{" "}
          <code>server.workers.enabled</code> arms them, and{" "}
          <code>cdx suggest</code> runs the same ticks in the repo).
        </p>
      </section>
    );
  }

  return (
    <section>
      <h1>
        Suggestions: <span className="repo-id">{repoId}</span>
      </h1>

      <p className="dep-summary">
        {pending.length} pending suggestion(s) — advisory only: every item
        embeds the exact next human command (agents suggest; humans apply,
        K11). Items that stop being true auto-resolve on the next worker tick.
      </p>

      {dismissError ? (
        <p role="alert" className="error">
          {dismissError}
        </p>
      ) : null}
      {needsToken ? (
        <p className="coverage-summary">
          <label>
            Repo token{" "}
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="bearer token"
            />
          </label>{" "}
          — dismissing is a write; retry after typing the token.
        </p>
      ) : null}

      {pending.length === 0 ? (
        <p className="coverage-summary">
          Nothing pending — the inbox equals current reality and it is clear.
        </p>
      ) : (
        <div className="panel">
          <h2>Pending</h2>
          <table className="worklist-table">
            <thead>
              <tr>
                <th scope="col">Severity</th>
                <th scope="col">Kind</th>
                <th scope="col">Subject</th>
                <th scope="col">Next step</th>
                <th scope="col" aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {pending.map((s) => (
                <tr key={s.key}>
                  <td>
                    <span
                      className={`chip ${SEVERITY_CHIP[s.severity] ?? "chip--review"}`}
                    >
                      {s.severity}
                    </span>
                  </td>
                  <td>{s.kind}</td>
                  <th scope="row">
                    <span className="file-name" title={s.target}>
                      {s.doc_id ?? s.target}
                    </span>
                  </th>
                  <td>{s.detail}</td>
                  <td>
                    <button type="button" onClick={() => dismiss(s.key)}>
                      Dismiss
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {closed.length > 0 ? (
        <div className="panel">
          <h2>Closed (audit trail)</h2>
          <p className="coverage-summary">
            Resolved items stopped being true on a later tick; dismissed items
            are a durable human &lsquo;no&rsquo; — neither ever resurfaces.
          </p>
          <table className="worklist-table">
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Kind</th>
                <th scope="col">Subject</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((s) => (
                <tr key={s.key}>
                  <td>
                    <span className="chip chip--sync">
                      {dismissedKeys.has(s.key) ? "dismissed" : s.status}
                    </span>
                  </td>
                  <td>{s.kind}</td>
                  <th scope="row">
                    <span className="file-name" title={s.target}>
                      {s.doc_id ?? s.target}
                    </span>
                  </th>
                  <td>{s.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export default Suggestions;
