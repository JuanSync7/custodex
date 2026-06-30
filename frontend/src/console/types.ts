// TypeScript mirrors of the central server's SHARED models (one source of truth =
// the Python server). Hand-written here for the two small shapes F-01 consumes;
// F-02+ can generate ReviewRecord/ResolutionRecord from `cdx schema` (JSON Schema).
//
//   server: custodex/sinks.py::RepoIdentity
//   server: custodex/server/store.py::RegisteredRepo
//   server: custodex/server/app.py::RepoStatus
//   server: custodex/schema.py::Verdict
//   server: custodex/ticket.py::DriftTicket

/** Which repo a review record came from (sinks.RepoIdentity). */
export interface RepoIdentity {
  repo_id: string;
  repo_name?: string | null;
  repo_url?: string | null;
  commit?: string | null;
}

/** A repo the central server knows about (store.RegisteredRepo). */
export interface RegisteredRepo {
  repo: RepoIdentity;
  default_branch?: string | null;
  description?: string | null;
}

/** The three review verdicts (schema.Verdict). */
export type Verdict = "ok" | "review" | "escalate";

/**
 * A COMPUTED status view for one repo (app.RepoStatus). `by_verdict` always
 * carries every verdict key (zero-filled) so the table renders a stable shape.
 */
export interface RepoStatus {
  repo_id: string;
  total_records: number;
  by_verdict: Record<string, number>;
  escalations: number;
  unresolved: number;
  last_detected_at?: string | null;
  coverage_ratio?: number | null;
}

/**
 * A COMPUTED metrics view for one repo (app.RepoHealth, F-05). Like {@link RepoStatus}
 * this is a computed AGGREGATE, NOT the shared wire schema. `mttr_seconds` is the mean
 * detected→resolved delta over resolved records (null when none are resolved).
 */
export interface RepoHealth {
  repo_id: string;
  total: number;
  escalations: number;
  escalation_rate: number;
  unresolved: number;
  overrides: number;
  resolved: number;
  mttr_seconds?: number | null;
}

// ── F-02/F-03: record + resolution + coverage shapes ────────────────────────
//
// `RecordVerdict`/`ProposedFix`/`ReviewRecord` below are GENERATED from the
// real Python schema: `.venv/bin/cdx schema --out src/schema.review.json`
// (schema.py::ReviewRecord, the K6 single source of truth). The JSON lives at
// `src/schema.review.json` and these interfaces mirror its `properties` exactly
// (rendered fields are a subset). `cdx schema` ONLY emits the review record,
// so `Resolution`/`ResolutionRecord` are hand-written from
// schema.py::ResolutionRecord and `CoverageSnapshot` from the server's opaque
// snapshot dict (app.py reads `ratio`; the basket counts are optional) — noted
// honestly here rather than generated.

/** A document's intended reader (schema.review.json#/$defs/Audience). */
export type Audience = "user-guide" | "eng-guide";

/** The backend's per-drift decision (schema.review.json#/$defs/Verdict). */
export type RecordVerdict = "FIX" | "INVALIDATE" | "ESCALATE";

/** A backend-proposed remediation (schema.review.json#/$defs/ProposedFix). */
export interface ProposedFix {
  region_id?: string | null;
  new_region_body?: string | null;
  new_doc_text?: string | null;
  rationale: string;
}

// ── T-03: the human-validatable DriftTicket ─────────────────────────────────
//
// Mirrors `custodex/ticket.py` (T-01): the Jira-style artifact that
// replaces the `ProposedFix.rationale` one-liner. Hand-written here from the
// frozen pydantic models in ticket.py (server: ticket.py::DriftTicket /
// ticket.py::AcceptanceCheck). The `ticket` rides on the existing recordsFor
// response — no new client method.

/** How urgently a human should look at a drift (ticket.py::TicketSeverity). */
export type Severity = "low" | "medium" | "high";

/** One acceptance-criterion line a reviewer confirms (ticket.py::AcceptanceCheck).
 * `auto_satisfied` is the agent's CLAIM that the change already meets it. */
export interface AcceptanceCheck {
  text: string;
  auto_satisfied: boolean;
}

/**
 * The structured, human-validatable artifact for one handled drift
 * (ticket.py::DriftTicket). `change_kind` is "region" | "whole-doc" | "none".
 * `affected_symbols`/`acceptance_criteria` are tuples on the server, arrays here.
 */
export interface DriftTicket {
  schema_version: string;
  ticket_id: string;
  title: string;
  summary: string;
  severity: Severity;
  drift_kind: string;
  doc_id: string;
  doc_path: string;
  region_id?: string | null;
  audience: string;
  affected_symbols: string[];
  root_cause: string;
  proposed_change: string;
  change_kind: string;
  diff: string;
  acceptance_criteria: AcceptanceCheck[];
  verdict: string;
  recommended_action: string;
}

/**
 * The public, versioned payload for one handled drift
 * (schema.review.json → schema.py::ReviewRecord). Mirrors the schema's
 * `properties`; the timeline renders a subset (doc, drift_kind, verdict,
 * detected_at, source_sha).
 */
export interface ReviewRecord {
  schema_version: string;
  record_id: string;
  doc_id: string;
  doc_path: string;
  audience: Audience;
  drift_kind: string;
  drift_detail: string;
  cause: string;
  verdict: RecordVerdict;
  fix?: ProposedFix | null;
  surface_hash: string;
  backend_kind: string;
  detected_at: string;
  resolved_at: string;
  config_snapshot: Record<string, unknown>;
  source_sha?: string | null;
  /** The structured ticket the human validates (ticket.py::build_ticket).
   * Null/absent on older records — the page falls back to `cause`/`fix`. */
  ticket?: DriftTicket | null;
}

/** The human OUTCOME of a handled drift (schema.py::Resolution). */
export type Resolution =
  | "accepted"
  | "overridden"
  | "rejected"
  | "invalidated";

/**
 * The public outcome for one handled drift (schema.py::ResolutionRecord).
 * Hand-written — `cdx schema` emits ONLY the review record, not this. Linked
 * to a {@link ReviewRecord} by `record_id`.
 */
export interface ResolutionRecord {
  schema_version: string;
  record_id: string;
  resolution: Resolution;
  resolved_text?: string | null;
  resolved_by?: string | null;
  resolved_at: string;
  note?: string | null;
}

/**
 * One file in a coverage snapshot (server: the config-driven snapshot `files`
 * entries from T-02). `status` is "documented" | "undocumented" | "waived";
 * `owners` are doc ids; `waived_reason` is set only for waived files.
 */
export interface CoverageFile {
  path: string;
  language: string;
  owners: string[];
  status: "documented" | "undocumented" | "waived";
  waived_reason?: string | null;
}

/**
 * One coverage snapshot for a repo. The server stores snapshots as OPAQUE JSON
 * (`store.coverage_for → list[dict]`); only `ratio` is contractual (app.py reads
 * it). The basket counts are the conventional A-04 shape (documented /
 * undocumented / waived files+symbols) and are optional/defensively rendered.
 * T-02 adds a `files` array (the per-file breakdown) — absent on older snapshots.
 */
export interface CoverageSnapshot {
  /** Documented fraction in [0, 1] (app.py reads this for RepoStatus). */
  ratio?: number | null;
  /** ISO timestamp the snapshot was taken, when present. */
  detected_at?: string | null;
  documented?: number | null;
  undocumented?: number | null;
  waived?: number | null;
  /** Per-file breakdown (T-02 config-driven snapshot); absent on older snapshots. */
  files?: CoverageFile[] | null;
  // Snapshots are opaque on the server, so tolerate extra keys.
  [key: string]: unknown;
}

// ── W-01: config documents + relationship view ──────────────────────────────
//
// Mirrors the Y-02 sync endpoints' rows (server: the config-v2 documents/code_refs
// the central server holds per repo; see .project/spec/CONFIGV2.md §5). A document
// owns a set of code_refs (the code surfaces it documents) — the relationship view.
// `sync_kind` is "git" | "local" (the unfiltered endpoint mixes both).

/**
 * One generation-context reference on a {@link ConfigDocument}
 * (server: store.ConfigContextRef, EDITOR E-03). A "glance-through" reference
 * (a sibling doc or a source file to refer to when authoring) — NEVER a
 * documented surface or coverage (K6). Additive on the document.
 */
export interface ConfigContextRef {
  path: string;
  note: string | null;
}

/** One config document the central server tracks for a repo (W-01 contract). */
export interface ConfigDocument {
  repo_id: string;
  doc_id: string;
  path: string;
  audience: string;
  unit: string;
  region_keys: string[];
  /** Generation-context references (EDITOR E-03 — additive, K6; never coverage). */
  context_refs: ConfigContextRef[];
  sync_kind: string;
  ref: string;
  synced_at: string;
}

/** One code surface a {@link ConfigDocument} documents (W-01 contract). */
export interface ConfigCodeRef {
  repo_id: string;
  doc_id: string;
  path: string;
  symbols: string[];
  unit: string;
  sync_kind: string;
}

/** A document plus the code surfaces it owns — one row of the relationship view. */
export interface ConfigDocumentTree {
  document: ConfigDocument;
  code_refs: ConfigCodeRef[];
}

// ── W-03: sync run + sync-state ──────────────────────────────────────────────
//
// Mirrors the Y-02 sync endpoints (server: the SyncRun summary returned by
// `POST /repos/{id}/sync` and `GET /repos/{id}/sync-state`; see
// .project/spec/CONFIGV2.md §5). `sync_kind` is "git" (sync the default branch)
// or "local" (sync from the registered local_path).

/** Which sync a button triggers / a state row reflects (Y-02). */
export type SyncMode = "git" | "local";

/** The drift summary embedded in a {@link SyncRun} (Y-02). */
export interface SyncDrift {
  ok: boolean;
  drift_count: number;
  /** Per-drift-kind counts (KIND → count). */
  by_kind: Record<string, number>;
  coverage_percent: number;
}

/**
 * The summary of one sync (server: the Y-02 `POST /sync` 201 body, also the
 * `GET /sync-state` body). `commits_ahead` is how far the head is past main;
 * `fully_synced` is the server's "in sync" verdict. Returned by `syncRepo`;
 * `syncState` returns this OR `null` when a repo has never been synced.
 */
export interface SyncRun {
  sync_kind: SyncMode;
  fully_synced: boolean;
  commits_ahead: number;
  document_count: number;
  code_ref_count: number;
  drift: SyncDrift;
  branch: string;
  head_commit: string;
  main_commit: string;
  ref: string;
  started_at: string;
  finished_at: string;
  repo_id: string;
}

// ── EDITOR (E-04..E-08): editable config tree + staged edits + generate/apply ─
//
// TypeScript mirrors of the EDITOR server models:
//   server: custodex/server/app.py::EditableConfigTree / EditableDocument
//            / DocStyleOptions / GenerateRequest / GenerateResponse / ApplyFixResponse
//   server: custodex/server/edits.py::ConfigEdit (tagged union) / StoredConfigEdit
// The editable tree is a COMPUTED VIEW (documents + the working-tree-derived gap +
// selectable doc-style options); a `ConfigEdit` is one staged "mapping ticket".

/**
 * One document in the editable tree (app.EditableDocument) — the SHARED
 * {@link ConfigDocument} (carrying its `context_refs`) plus the
 * {@link ConfigCodeRef} surfaces it owns. Same JOIN shape as
 * {@link ConfigDocumentTree}; named distinctly to mirror the editor route.
 */
export interface EditableDocument {
  document: ConfigDocument;
  code_refs: ConfigCodeRef[];
}

/**
 * The selectable doc-style options per category (app.DocStyleOptions) — the
 * available writing-template stems under `templates/writing/<category>/`, keyed
 * by the four fixed selection dimensions. An absent category yields `[]`.
 */
export interface DocStyleOptions {
  document_type: string[];
  tone: string[];
  writing_style: string[];
  vocabulary: string[];
}

/**
 * The full editable config tree for one repo (app.EditableConfigTree) — what the
 * Mapping page renders: the stored `documents` (each with code_refs + context_refs),
 * the in-scope-but-unlinked `undocumented_files` (the coverage gap), the
 * `ignored_files`, the on-disk `unit_files` stems, and the selectable `doc_styles`.
 */
export interface EditableConfigTree {
  repo_id: string;
  sync_kind: string;
  documents: EditableDocument[];
  undocumented_files: string[];
  ignored_files: string[];
  unit_files: string[];
  doc_styles: DocStyleOptions;
}

// ── ConfigEdit — the staged "mapping ticket" tagged union (edits.ConfigEdit) ──

/**
 * A code_ref payload inside an edit (edits.EditCodeRef): a repo-relative `path`,
 * the optional `symbols` it owns (empty/omitted = whole file), and an optional
 * 1-based inclusive `lines` range string (e.g. "10-42").
 */
export interface EditCodeRef {
  path: string;
  symbols?: string[];
  lines?: string | null;
}

/**
 * A context_ref payload inside an edit (edits.EditContextRef): a repo-relative
 * `path` and an optional human `note`. Generation context, never coverage (K6).
 */
export interface EditContextRef {
  path: string;
  note?: string | null;
}

/**
 * A doc-style selection payload (edits.EditDocStyle): the four category options,
 * all optional so an edit may set only the dimensions the author changed.
 */
export interface EditDocStyle {
  document_type?: string;
  tone?: string;
  writing_style?: string;
  vocabulary?: string;
}

/** Create (or fully define) a document entry under a unit (edits.CreateDocEdit). */
export interface CreateDocEdit {
  action: "create_doc";
  unit: string;
  doc_id: string;
  path: string;
  audience: string;
  code_refs?: EditCodeRef[];
  context_refs?: EditContextRef[];
  doc_style?: EditDocStyle;
}

/** Add one code_ref to an existing document (edits.AddCodeRefEdit). */
export interface AddCodeRefEdit {
  action: "add_code_ref";
  unit: string;
  doc_id: string;
  ref: EditCodeRef;
}

/** Remove a code_ref by `path` from a document (edits.RemoveCodeRefEdit). */
export interface RemoveCodeRefEdit {
  action: "remove_code_ref";
  unit: string;
  doc_id: string;
  path: string;
}

/** Replace a document's `context_refs` wholesale (edits.SetContextRefsEdit). */
export interface SetContextRefsEdit {
  action: "set_context_refs";
  unit: string;
  doc_id: string;
  context_refs: EditContextRef[];
}

/** Set/override a document's doc-style selection (edits.SetDocStyleEdit). */
export interface SetDocStyleEdit {
  action: "set_doc_style";
  doc_id: string;
  doc_style: EditDocStyle;
}

/**
 * The staged "mapping ticket" — a discriminated union on `action` (edits.ConfigEdit).
 * The POST /config/edits body and the `edit` envelope on {@link StoredConfigEdit}.
 */
export type ConfigEdit =
  | CreateDocEdit
  | AddCodeRefEdit
  | RemoveCodeRefEdit
  | SetContextRefsEdit
  | SetDocStyleEdit;

/** The lifecycle status of a staged edit (edits.StoredConfigEdit.status). */
export type ConfigEditStatus = "pending" | "applied" | "discarded";

/**
 * A persisted pending-edit envelope (edits.StoredConfigEdit): the typed `edit`
 * plus its lifecycle — the `edit_id` ticket handle, the `status`, the injected
 * `created_at`, and the nullable `applied_at` stamped when it is made live.
 */
export interface StoredConfigEdit {
  edit_id: string;
  status: ConfigEditStatus;
  created_at: string;
  applied_at: string | null;
  edit: ConfigEdit;
}

/**
 * The POST /config/generate body (app.GenerateRequest). `edit_ids` selects which
 * PENDING edits to apply (omitted = every pending edit); `mode` is the sync mode
 * re-run after writing ("local" by default).
 */
export interface GenerateRequest {
  edit_ids?: string[];
  mode?: string;
}

/**
 * The POST /config/generate response (app.GenerateResponse): the `applied` edit
 * ids, the FRESH `sync_run` from the post-generate re-sync (null only for a no-op
 * generate with no prior sync), and the recomputed `undocumented_files` gap.
 */
export interface GenerateResponse {
  applied: string[];
  sync_run: SyncRun | null;
  undocumented_files: string[];
}

/**
 * The POST /records/{id}/apply-fix response (app.ApplyFixResponse): `applied` is
 * true only when the doc changed (an already-applied fix is a no-op, K7);
 * `doc_path` is the repo-relative doc; `diff` is the unified before→after diff
 * (empty when unchanged); `sync_run` is the FRESH post-apply re-sync.
 */
export interface ApplyFixResponse {
  applied: boolean;
  doc_path: string;
  diff: string;
  sync_run: SyncRun | null;
}

// NB: the feature wikis are NOW native Astro pages at `/wiki/*` (EPIC ASTRO) —
// rendered from `feature-doc/*.md` at build time, not fetched as JSON. The old
// `WikiSection`/`WikiPayload` types + the `GET /wiki` JSON read were retired.

/**
 * EPIC OWN — the GET /repos/{id}/ownership view: each monitored document's
 * resolved owner (accountable = current point of contact, durable = survives a
 * departure) plus the orphan findings (a document whose accountable owner has
 * departed) and a count. Mirrors the python ownership.EffectiveOwner /
 * OwnershipFinding shapes.
 */
export interface OwnershipOwner {
  doc_id: string;
  doc_path: string;
  audience: string;
  owner: string | null;
  team: string | null;
  dri: string | null;
  accountable: string | null;
  durable: string | null;
}

export interface OwnershipFinding {
  doc_id: string;
  doc_path: string;
  audience: string;
  status: string;
  detail: string;
  accountable: string | null;
  owner: string | null;
  team: string | null;
  dri: string | null;
}

export interface OwnershipData {
  owners: OwnershipOwner[];
  findings: OwnershipFinding[];
  orphan_count: number;
}

// ── EPIC SVR — operator runtime settings (GET /settings) ────────────────────
// server: custodex/settings.py::Settings (mirrored field-for-field).
export interface CorsSettings {
  allow_origins: string[];
  allow_credentials: boolean;
  allow_methods: string[];
  allow_headers: string[];
}

export interface RateLimitSettings {
  requests_per_minute: number | null;
}

export interface GitSettings {
  allowed_hosts: string[];
  extra_allowed_hosts: string[];
  allow_file_scheme: boolean;
  clone_timeout_seconds: number | null;
}

export interface ServerSettings {
  host: string;
  port: number;
  log_level: string;
  trusted_hosts: string[];
  cors: CorsSettings;
  rate_limit: RateLimitSettings;
  git: GitSettings;
}

export interface Settings {
  version: string;
  server: ServerSettings;
}

// server: custodex/settings.py::secret_presence — PRESENCE only, never values.
export interface SecretPresence {
  admin_token_configured: boolean;
  database_url_set: boolean;
  secret_key_set: boolean;
}

// server: GET /settings → {settings, secrets}.
export interface SettingsData {
  settings: Settings;
  secrets: SecretPresence;
}

// ── EPIC SLA — review staleness (GET /repos/:id/staleness) ──────────────────
// server: custodex/staleness.py::StalenessFinding
export interface StalenessFinding {
  doc_id: string;
  doc_path: string;
  audience: string;
  status: string; // "fresh" | "stale" | "never_reviewed"
  reviewed: string | null;
  sla_days: number;
  age_days: number | null;
  detail: string;
}

// server: GET /repos/:id/staleness → {findings, stale_count, now}
export interface StalenessData {
  findings: StalenessFinding[];
  stale_count: number;
  now: string;
}

// ── EPIC B — the doc↔doc dependency graph (GET /repos/:id/doc-graph) ─────────
// The role one document plays toward an upstream it `depends_on` (config.DocEdgeType).
export type DocEdgeType = "depends" | "refines" | "implements" | "verifies";

// One downstream→upstream edge of the declared dependency graph.
export interface DocGraphEdge {
  doc_id: string;
  doc_path: string;
  audience: Audience;
  upstream_id: string;
  type: DocEdgeType;
}

// server: GET /repos/:id/doc-graph → {edges, edge_count}. The DECLARED dependency
// graph (who-depends-on-what); suspect freshness stays repo-local (K2), so this hub
// view shows the structure, not the per-edge review status.
export interface DocGraph {
  edges: DocGraphEdge[];
  edge_count: number;
}
