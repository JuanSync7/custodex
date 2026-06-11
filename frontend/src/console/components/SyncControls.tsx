// W-03: a reusable sync header for the repo pages. Shows the current sync state
// (a signal dot + "In sync"/"N commits ahead"/"M drift", coverage %, last-synced)
// and offers two write actions — Sync (main) → POST {mode:"git"} and Sync (local)
// → POST {mode:"local"} — using the per-repo bearer token (the resolve() pattern).
// After a sync it adopts the returned run and calls `onSynced` so the host page can
// re-fetch. Mounted on both RepoDetail and Documents.
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import { ApiError } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { SyncMode, SyncRun } from "../types";

/** The slice of the API this component needs — fakeable in tests (no network). */
export interface SyncControlsApi {
  syncState(repoId: string, syncKind?: SyncMode): Promise<SyncRun | null>;
  syncRepo(repoId: string, mode: SyncMode, token: string): Promise<SyncRun>;
}

export interface SyncControlsProps {
  repoId: string;
  /** Injected client; per-method, falls back to the shared singleton when a
   * method is absent (lets a host page pass its own partial api or none). */
  api?: Partial<SyncControlsApi>;
  /** A bearer token supplied by the host page. When absent, a token input shows. */
  token?: string;
  /** Scope the loaded sync-state to one source (git vs local). When the host page
   * shows a git/local toggle, it MUST pass its active kind so the header reflects
   * the same source as the data below it. Omitted → the server's latest run. */
  syncKind?: SyncMode;
  /** Called after a successful sync so the host can re-fetch its data. */
  onSynced?: (run: SyncRun) => void;
}

/** Format an ISO timestamp for the "last synced" line; "—" when absent. */
function lastSyncedLabel(run: SyncRun | null): string {
  if (!run?.finished_at) return "never synced";
  return run.finished_at;
}

/** The signal dot + headline for a state: in-sync vs ahead vs drift. */
function statusFor(run: SyncRun): { dot: string; text: string } {
  const driftCount = run.drift?.drift_count ?? 0;
  if (driftCount > 0) {
    return {
      dot: "dot--drift",
      text: `${driftCount} drift`,
    };
  }
  if ((run.commits_ahead ?? 0) > 0) {
    return {
      dot: "dot--review",
      text: `${run.commits_ahead} commits ahead`,
    };
  }
  return { dot: "dot--sync", text: "In sync" };
}

export function SyncControls({
  repoId,
  api,
  token: tokenProp,
  syncKind,
  onSynced,
}: SyncControlsProps) {
  // Each method falls back to the shared singleton when the host omits it; bound
  // to its owner so calling it detached keeps `this`. Memoized on the api prop so
  // the loader stays stable across renders.
  const syncStateFn = useMemo(
    () =>
      api?.syncState
        ? api.syncState.bind(api)
        : apiClient.syncState.bind(apiClient),
    [api],
  );
  const syncRepoFn = useMemo(
    () =>
      api?.syncRepo
        ? api.syncRepo.bind(api)
        : apiClient.syncRepo.bind(apiClient),
    [api],
  );

  // The initial state is loaded on mount and whenever the host's sync kind
  // changes, so the header tracks the same source as the data below it; a
  // successful sync supersedes it.
  const loader = useCallback(
    () => syncStateFn(repoId, syncKind),
    [syncStateFn, repoId, syncKind],
  );
  const initial = useApi<SyncRun | null>(loader, [loader]);

  // The run shown to the user: null until loaded, then the latest of load/sync.
  const [run, setRun] = useState<SyncRun | null>(null);
  // A prior sync's run is for one source; drop it when the host switches kind so
  // the re-loaded sync-state (for the new source) shows instead of a stale run.
  useEffect(() => setRun(null), [syncKind]);
  const [busy, setBusy] = useState<SyncMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  // L-01: the token input is REVEALED only after an auth error (a token-protected
  // repo), not upfront — an OPEN/standalone repo never needs it. The host still
  // hides the input entirely when it supplies the token itself (`tokenProp`).
  const [authRequired, setAuthRequired] = useState(false);
  // A locally-typed token, used only when the host page passes none.
  const [localToken, setLocalToken] = useState("");
  const token = tokenProp ?? localToken;

  // The effective run = a synced run (state) wins, else the loaded one.
  const current = run ?? (initial.phase === "ready" ? initial.data : null);

  const doSync = useCallback(
    async (mode: SyncMode) => {
      // L-01: NOT hard-guarded on an empty token — an OPEN repo syncs with none.
      // `syncRepo` omits the Authorization header when the token is empty; only a
      // 401/403 reveals the token input + auth message (a token-protected repo).
      setError(null);
      setBusy(mode);
      try {
        const result = await syncRepoFn(repoId, mode, token.trim());
        setRun(result);
        onSynced?.(result);
      } catch (err: unknown) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          setAuthRequired(true);
          setError(
            err.status === 401
              ? "Auth required: a valid token is needed to sync."
              : "Auth invalid: that token was rejected.",
          );
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        setBusy(null);
      }
    },
    [syncRepoFn, repoId, token, onSynced],
  );

  return (
    <section className="sync-controls panel" aria-label="sync controls">
      <div className="sync-controls__status">
        {initial.phase === "loading" && run === null ? (
          <span className="sync-status sync-status--loading">
            Loading sync state…
          </span>
        ) : current === null ? (
          <span className="sync-status sync-status--never">
            <span className="dot" aria-hidden="true" />
            Never synced
          </span>
        ) : (
          <SyncStatus run={current} />
        )}
      </div>

      <div className="sync-controls__actions">
        <button
          type="button"
          className="sync-btn"
          disabled={busy !== null}
          onClick={() => doSync("git")}
        >
          {busy === "git" ? "Syncing…" : "Sync (main)"}
        </button>
        <button
          type="button"
          className="sync-btn sync-btn--local"
          disabled={busy !== null}
          onClick={() => doSync("local")}
        >
          {busy === "local" ? "Syncing…" : "Sync (local)"}
        </button>
      </div>

      {tokenProp === undefined && authRequired ? (
        <form
          className="sync-controls__auth"
          aria-label="sync auth"
          onSubmit={(e) => e.preventDefault()}
        >
          <label>
            Token
            <input
              type="password"
              value={localToken}
              placeholder="bearer token for sync"
              onChange={(e) => setLocalToken(e.target.value)}
            />
          </label>
        </form>
      ) : null}

      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}
    </section>
  );
}

/** The status row: a signal dot + headline + coverage % + last-synced time. */
function SyncStatus({ run }: { run: SyncRun }) {
  const { dot, text } = statusFor(run);
  return (
    <span className="sync-status">
      <span className={`dot ${dot}`} aria-hidden="true" />
      <span className="sync-status__head">{text}</span>
      <span className="sync-status__cov">
        {run.drift?.coverage_percent ?? 0}% coverage
      </span>
      <span className="sync-status__time">
        last synced {lastSyncedLabel(run)}
      </span>
    </span>
  );
}

export default SyncControls;
