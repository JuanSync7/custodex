import { useCallback, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { ApiError, apiClient, type RecordFilters } from "../api/client";
import { useApi } from "../hooks/useApi";
import SyncControls, { type SyncControlsApi } from "../components/SyncControls";
import { partitionReadme } from "../lib/grouping";
import type {
  ApplyFixResponse,
  Audience,
  DriftTicket,
  RecordVerdict,
  Resolution,
  ResolutionRecord,
  ReviewRecord,
  Severity,
} from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface RepoDetailApi {
  recordsFor(repoId: string, filters?: RecordFilters): Promise<ReviewRecord[]>;
  resolutionsFor(repoId: string): Promise<ResolutionRecord[]>;
  resolve(
    repoId: string,
    rec: ResolutionRecord,
    token: string,
  ): Promise<{ record_id: string }>;
  /** EDITOR E-11: apply a record's LLM-proposed fix to the doc on disk (WRITE). */
  applyRecordFix(
    repoId: string,
    recordId: string,
    token: string,
  ): Promise<ApplyFixResponse>;
  /** OPTIONAL sync methods for `<SyncControls>`; absent → the shared client. */
  syncState?: SyncControlsApi["syncState"];
  syncRepo?: SyncControlsApi["syncRepo"];
}

export interface RepoDetailProps {
  /** Injected client; defaults to the shared singleton. */
  api?: RepoDetailApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

const VERDICTS: RecordVerdict[] = ["FIX", "INVALIDATE", "ESCALATE"];
const AUDIENCES: Audience[] = ["user-guide", "eng-guide"];
const RESOLUTIONS: Resolution[] = [
  "accepted",
  "overridden",
  "rejected",
  "invalidated",
];

interface Filters {
  verdict: string;
  drift_kind: string;
  audience: string;
}

interface Loaded {
  records: ReviewRecord[];
  /** record_id → its resolution, when present. */
  resolutions: Map<string, ResolutionRecord>;
}

function shortSha(sha: string | null | undefined): string {
  if (!sha) return "—";
  return sha.length > 8 ? sha.slice(0, 8) : sha;
}

/** Severity → DRIFT CONSOLE signal chip: high→drift, medium→review, low→sync. */
const SEVERITY_CHIP: Record<Severity, string> = {
  high: "chip--drift",
  medium: "chip--review",
  low: "chip--sync",
};

/** Mirror of ticket.py::ticket_status, expressed as a human-facing label. */
function ticketStatusLabel(resolution: ResolutionRecord | undefined): string {
  if (!resolution) return "awaiting review"; // PROPOSED
  switch (resolution.resolution) {
    case "accepted":
      return "validated"; // VALIDATED
    case "overridden":
      return "changes requested"; // CHANGES_REQUESTED
    default:
      return "rejected"; // REJECTED (rejected | invalidated)
  }
}

export function RepoDetail({ api = apiClient, repoId: repoIdProp }: RepoDetailProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";

  const [filters, setFilters] = useState<Filters>({
    verdict: "",
    drift_kind: "",
    audience: "",
  });
  // The bearer token for the WRITE path (F-04) — a single field, applies to all rows.
  const [token, setToken] = useState("");
  // Optimistic resolutions added since load (record_id → ResolutionRecord) + an error.
  const [posted, setPosted] = useState<Map<string, ResolutionRecord>>(new Map());
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [tokenMissing, setTokenMissing] = useState(false);
  // L-01: a 401/403 (on resolve OR apply-fix) REVEALS an auth message; the token
  // input is the page's existing field — there is no second token mechanism.
  const [authMessage, setAuthMessage] = useState<string | null>(null);
  // Which record rows have their ticket/details panel expanded (record_id set).
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // Bumped after a sync so the records loader re-runs against fresh state.
  const [reload, setReload] = useState(0);
  // EDITOR E-11: per-record apply-fix progress + the returned result/error.
  const [applyingFix, setApplyingFix] = useState<Set<string>>(new Set());
  const [fixResults, setFixResults] = useState<Map<string, ApplyFixResponse>>(
    new Map(),
  );
  const [fixError, setFixError] = useState<string | null>(null);

  const toggleExpanded = (recordId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(recordId)) next.delete(recordId);
      else next.add(recordId);
      return next;
    });

  const loader = useCallback(async (): Promise<Loaded> => {
    const recordFilters: RecordFilters = {
      verdict: filters.verdict || undefined,
      drift_kind: filters.drift_kind || undefined,
      audience: filters.audience || undefined,
    };
    const [records, resolutionList] = await Promise.all([
      api.recordsFor(repoId, recordFilters),
      api.resolutionsFor(repoId),
    ]);
    const resolutions = new Map<string, ResolutionRecord>();
    for (const r of resolutionList) resolutions.set(r.record_id, r);
    return { records, resolutions };
    // `reload` is a deliberate dep: a sync bumps it to force a re-fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, repoId, filters.verdict, filters.drift_kind, filters.audience, reload]);

  const state = useApi<Loaded>(loader, [loader]);

  const setFilter = (key: keyof Filters) => (value: string) =>
    setFilters((prev) => ({ ...prev, [key]: value }));

  const submitResolution = useCallback(
    async (recordId: string, resolution: Resolution, note: string) => {
      setResolveError(null);
      if (!token.trim()) {
        setTokenMissing(true);
        return;
      }
      setTokenMissing(false);
      const rec: ResolutionRecord = {
        schema_version: "1.0.0",
        record_id: recordId,
        resolution,
        resolved_text: null,
        resolved_by: null,
        // Injected at the page edge (NOT in pure code) so it stays deterministic there.
        resolved_at: new Date().toISOString(),
        note: note.trim() || null,
      };
      try {
        await api.resolve(repoId, rec, token);
        setPosted((prev) => new Map(prev).set(recordId, rec));
      } catch (err: unknown) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          setAuthMessage(
            err.status === 401
              ? "Auth required: a valid token is needed to write."
              : "Auth invalid: that token was rejected.",
          );
        } else {
          setResolveError(err instanceof Error ? err.message : String(err));
        }
      }
    },
    [api, repoId, token],
  );

  const applyFix = useCallback(
    async (recordId: string) => {
      setFixError(null);
      setAuthMessage(null);
      setApplyingFix((prev) => new Set(prev).add(recordId));
      try {
        const result = await api.applyRecordFix(repoId, recordId, token.trim());
        setFixResults((prev) => new Map(prev).set(recordId, result));
        // The fix mutated the doc → re-fetch records (and sync-state below) so the
        // timeline reflects the healed/cleared state.
        setReload((n) => n + 1);
      } catch (err: unknown) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          setAuthMessage(
            err.status === 401
              ? "Auth required: a valid token is needed to write."
              : "Auth invalid: that token was rejected.",
          );
        } else {
          setFixError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        setApplyingFix((prev) => {
          const next = new Set(prev);
          next.delete(recordId);
          return next;
        });
      }
    },
    [api, repoId, token],
  );

  // record_id → resolution, available regardless of phase (empty until ready) so
  // the row renderer below can be a plain closure.
  const resolutions =
    state.phase === "ready"
      ? state.data.resolutions
      : new Map<string, ResolutionRecord>();

  const recordsHead = (
    <thead>
      <tr>
        <th scope="col">Doc</th>
        <th scope="col">Drift kind</th>
        <th scope="col">Verdict</th>
        <th scope="col">Detected</th>
        <th scope="col">Source</th>
        <th scope="col">Resolution</th>
        <th scope="col">Details</th>
      </tr>
    </thead>
  );

  // One <tbody>'s worth of rows for a list of records — rendered once for the main
  // timeline and again for the README files section (FEAT-CONFIGV2-016).
  const renderRecordRows = (recs: ReviewRecord[]): ReactNode =>
    recs.map((rec) => {
      const resolution =
        posted.get(rec.record_id) ?? resolutions.get(rec.record_id);
      const isOpen = expanded.has(rec.record_id);
      const hasTicket = !!rec.ticket;
      const verb = isOpen ? "Hide" : "View";
      const noun = hasTicket ? "ticket" : "details";
      return (
        <RowFragment key={rec.record_id}>
          <tr>
            <th scope="row">
              <span className="doc-id">{rec.doc_id}</span>
              <span className="doc-path"> ({rec.doc_path})</span>
            </th>
            <td>{rec.drift_kind}</td>
            <td>
              <span className={`verdict verdict-${rec.verdict.toLowerCase()}`}>
                {rec.verdict}
              </span>
            </td>
            <td>{rec.detected_at}</td>
            <td>{shortSha(rec.source_sha)}</td>
            <td>
              {resolution ? (
                <span
                  className={`badge resolution resolution-${resolution.resolution}`}
                >
                  {resolution.resolution}
                </span>
              ) : (
                <ResolveControl
                  onResolve={(res, note) =>
                    submitResolution(rec.record_id, res, note)
                  }
                />
              )}
            </td>
            <td>
              <button
                type="button"
                className="ticket-toggle"
                aria-expanded={isOpen}
                onClick={() => toggleExpanded(rec.record_id)}
              >
                {`${verb} ${noun}`}
              </button>
            </td>
          </tr>
          {isOpen ? (
            <tr className="ticket-detail-row">
              <td colSpan={7}>
                {rec.ticket ? (
                  <TicketCard
                    ticket={rec.ticket}
                    statusLabel={ticketStatusLabel(resolution)}
                  />
                ) : (
                  <LegacyDetail record={rec} />
                )}
                {rec.verdict === "FIX" && rec.fix ? (
                  <ApplyFixControl
                    applying={applyingFix.has(rec.record_id)}
                    result={fixResults.get(rec.record_id)}
                    onApply={() => applyFix(rec.record_id)}
                  />
                ) : null}
              </td>
            </tr>
          ) : null}
        </RowFragment>
      );
    });

  return (
    <section>
      <h1>
        Drift timeline: <span className="repo-id">{repoId}</span>
      </h1>

      <SyncControls
        repoId={repoId}
        api={api}
        token={token}
        onSynced={() => setReload((n) => n + 1)}
      />

      <form aria-label="filters" onSubmit={(e) => e.preventDefault()}>
        <label>
          Verdict
          <select
            value={filters.verdict}
            onChange={(e) => setFilter("verdict")(e.target.value)}
          >
            <option value="">All</option>
            {VERDICTS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Audience
          <select
            value={filters.audience}
            onChange={(e) => setFilter("audience")(e.target.value)}
          >
            <option value="">All</option>
            {AUDIENCES.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label>
          Drift kind
          <input
            type="text"
            value={filters.drift_kind}
            placeholder="e.g. signature_changed"
            onChange={(e) => setFilter("drift_kind")(e.target.value)}
          />
        </label>
      </form>

      <form aria-label="auth" onSubmit={(e) => e.preventDefault()}>
        <label>
          Token
          <input
            type="password"
            value={token}
            placeholder="bearer token for writes"
            onChange={(e) => setToken(e.target.value)}
          />
        </label>
      </form>

      {tokenMissing ? (
        <p role="alert" className="error">
          A token is required to resolve a record.
        </p>
      ) : null}
      {resolveError ? (
        <p role="alert" className="error">
          Failed to resolve: {resolveError}
        </p>
      ) : null}
      {authMessage ? (
        <p role="alert" className="error">
          {authMessage}
        </p>
      ) : null}
      {fixError ? (
        <p role="alert" className="error">
          Failed to apply fix: {fixError}
        </p>
      ) : null}

      {state.phase === "loading" ? (
        <p role="status" aria-busy="true">
          Loading records…
        </p>
      ) : state.phase === "error" ? (
        <p role="alert" className="error">
          Failed to load records: {state.message}
        </p>
      ) : state.data.records.length === 0 ? (
        <p>No records match these filters.</p>
      ) : (
        (() => {
          // README / narrative-doc drift is shown in its OWN section, separate
          // from the engineering timeline (FEAT-CONFIGV2-016).
          const { main, readme } = partitionReadme(
            state.data.records,
            (r) => r.doc_path,
          );
          return (
            <>
              {main.length > 0 ? (
                <table>
                  {recordsHead}
                  <tbody>{renderRecordRows(main)}</tbody>
                </table>
              ) : null}
              {readme.length > 0 ? (
                <div className="drift-readme panel">
                  <h2>README files</h2>
                  <table>
                    {recordsHead}
                    <tbody>{renderRecordRows(readme)}</tbody>
                  </table>
                </div>
              ) : null}
            </>
          );
        })()
      )}
    </section>
  );
}

interface ResolveControlProps {
  onResolve: (resolution: Resolution, note: string) => void;
}

/** The per-row resolve form: a resolution choice + an optional note + submit. */
function ResolveControl({ onResolve }: ResolveControlProps) {
  const [resolution, setResolution] = useState<Resolution>("accepted");
  const [note, setNote] = useState("");
  return (
    <form
      className="resolve-control"
      onSubmit={(e) => {
        e.preventDefault();
        onResolve(resolution, note);
      }}
    >
      <span className="badge unresolved">unresolved</span>
      <label>
        Resolution
        <select
          value={resolution}
          onChange={(e) => setResolution(e.target.value as Resolution)}
        >
          {RESOLUTIONS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
      <label>
        Note
        <input
          type="text"
          value={note}
          placeholder="optional note / text"
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <button type="submit">Validate</button>
    </form>
  );
}

/** A transparent grouping so a record can render its row + an optional detail row. */
function RowFragment({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

interface TicketCardProps {
  ticket: DriftTicket;
  statusLabel: string;
}

/** The Jira-style ticket card shown in a record's expanded detail row. */
function TicketCard({ ticket, statusLabel }: TicketCardProps) {
  const chipClass = SEVERITY_CHIP[ticket.severity] ?? "chip--review";
  return (
    <article className="ticket-card panel">
      <header className="ticket-card__head">
        <span className={`chip ${chipClass}`}>{ticket.severity}</span>
        <h2 className="ticket-card__title">{ticket.title}</h2>
        <span className="badge ticket-status">{statusLabel}</span>
      </header>

      <dl className="ticket-card__body">
        <div className="ticket-section">
          <dt>Summary</dt>
          <dd>{ticket.summary}</dd>
        </div>
        <div className="ticket-section">
          <dt>Root cause</dt>
          <dd>{ticket.root_cause}</dd>
        </div>
        <div className="ticket-section">
          <dt>Proposed change</dt>
          <dd>
            {ticket.proposed_change}{" "}
            <span className="chip change-kind">{ticket.change_kind}</span>
          </dd>
        </div>
        <div className="ticket-section">
          <dt>Recommended action</dt>
          <dd>{ticket.recommended_action}</dd>
        </div>
        {ticket.affected_symbols.length > 0 ? (
          <div className="ticket-section">
            <dt>Affected symbols</dt>
            <dd className="symbol-chips">
              {ticket.affected_symbols.map((sym) => (
                <span key={sym} className="chip symbol-chip">
                  {sym}
                </span>
              ))}
            </dd>
          </div>
        ) : null}
        {ticket.diff.trim() ? (
          <div className="ticket-section">
            <dt>Diff</dt>
            <dd>
              <pre className="ticket-diff">{ticket.diff}</pre>
            </dd>
          </div>
        ) : null}
      </dl>

      <section className="acceptance" aria-label="Acceptance checklist">
        <h3 className="acceptance__title">Acceptance checklist</h3>
        <ul className="acceptance__list">
          {ticket.acceptance_criteria.map((check, i) => (
            <li key={i} className="acceptance__item">
              <span
                className={`dot ${check.auto_satisfied ? "dot--sync" : "dot--review"}`}
                aria-hidden="true"
              />
              <span className="acceptance__text">{check.text}</span>
              <span
                className={`chip ${check.auto_satisfied ? "chip--sync" : "chip--review"}`}
              >
                {check.auto_satisfied ? "agent asserts" : "needs confirmation"}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </article>
  );
}

/** The legacy fallback for records with no structured ticket (cause + rationale). */
function LegacyDetail({ record }: { record: ReviewRecord }) {
  return (
    <div className="legacy-detail panel">
      <dl className="ticket-card__body">
        <div className="ticket-section">
          <dt>Drift detail</dt>
          <dd>{record.drift_detail}</dd>
        </div>
        <div className="ticket-section">
          <dt>Cause</dt>
          <dd>{record.cause}</dd>
        </div>
        {record.fix?.rationale ? (
          <div className="ticket-section">
            <dt>Proposed fix</dt>
            <dd>{record.fix.rationale}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

interface ApplyFixControlProps {
  applying: boolean;
  result: ApplyFixResponse | undefined;
  onApply: () => void;
}

/** EDITOR E-11: the "Apply fix (LLM)" button + its result affordance. Shown only
 * for a FIX record that carries an applicable proposed fix (the host gates this).
 * On success it shows an "applied" indicator + the unified diff in a collapsible;
 * an `applied:false` (idempotent no-op) shows a muted "no change" message. */
function ApplyFixControl({ applying, result, onApply }: ApplyFixControlProps) {
  return (
    <div className="apply-fix">
      <button
        type="button"
        className="apply-fix__btn"
        disabled={applying}
        onClick={onApply}
      >
        {applying ? "Applying…" : "Apply fix (LLM)"}
      </button>
      {result ? (
        result.applied ? (
          <div className="apply-fix__result">
            <p className="apply-fix__applied">
              Applied to <code>{result.doc_path}</code>
            </p>
            {result.diff.trim() ? (
              <details className="apply-fix__diff">
                <summary>View diff</summary>
                <pre>{result.diff}</pre>
              </details>
            ) : null}
          </div>
        ) : (
          <p className="apply-fix__nochange muted">
            No change — the fix was already applied.
          </p>
        )
      ) : null}
    </div>
  );
}

export default RepoDetail;
