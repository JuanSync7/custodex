// EDITOR E-09: the per-repo Mapping page — the live document↔code map rendered
// READ-ONLY. It calls `configEditable(repoId, syncKind)` and shows three sections
// scoped to the repo: the documents (each a collapsible row revealing its
// `code_refs` AND its `context_refs`), the in-scope-but-unlinked source files
// (`undocumented_files`), and a collapsed-by-default `<details>` of ignored files.
//
// Structured so the later slices slot in cleanly WITHOUT reshaping this page:
//   E-10 — the mapping-ticket FORM + the "Generate / make live" button. The
//          per-document "Edit mapping" action and the per-unlinked-file "Link to a
//          document…" action open the form (pre-targeted / pre-filled). A staged-
//          edits list shows the pending tickets; "Generate / make live" applies
//          them and re-fetches the now-live tree + list.
//   E-11 — the apply-fix button lives on RepoDetail's drift timeline, not here.
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { apiClient, ApiError } from "../api/client";
import { useApi } from "../hooks/useApi";
import SyncControls, { type SyncControlsApi } from "../components/SyncControls";
import MappingTicketForm from "../components/MappingTicketForm";
import Modal from "../components/Modal";
import type {
  ConfigEdit,
  EditableConfigTree,
  EditableDocument,
  GenerateRequest,
  GenerateResponse,
  StoredConfigEdit,
} from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). The
 * sync methods are OPTIONAL: when absent, `<SyncControls>` uses the shared client. */
export interface MappingApi {
  configEditable(repoId: string, syncKind?: string): Promise<EditableConfigTree>;
  /** Stage one mapping "ticket" (the form submits this; E-10 WRITE path). */
  stageConfigEdit?(
    repoId: string,
    edit: ConfigEdit,
    token: string,
  ): Promise<{ edit_id: string }>;
  /** List the staged edits (the pending-list loader). */
  listConfigEdits?(repoId: string, status?: string): Promise<StoredConfigEdit[]>;
  /** Make staged edits live (the "Generate / make live" WRITE path). */
  generateConfig?(
    repoId: string,
    body: GenerateRequest,
    token: string,
  ): Promise<GenerateResponse>;
  syncState?: SyncControlsApi["syncState"];
  syncRepo?: SyncControlsApi["syncRepo"];
}

export interface MappingProps {
  api?: MappingApi;
  /** Override the route param (tests render without a Routes wrapper). */
  repoId?: string;
}

/** The two document sources the central server tracks (W-01 contract). The
 * editable tree is most meaningful for the working tree, so it DEFAULTS to local. */
const SYNC_KINDS = ["git", "local"] as const;
type SyncKind = (typeof SYNC_KINDS)[number];

export function Mapping({ api = apiClient, repoId: repoIdProp }: MappingProps) {
  const params = useParams();
  const repoId = repoIdProp ?? params.repoId ?? "";

  // Which document rows are expanded to reveal their code_refs + context_refs.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // The document source; the editable tree defaults to the working tree (local).
  const [syncKind, setSyncKind] = useState<SyncKind>("local");
  // Bumped after a sync/generate so the loader re-runs and picks up fresh rows.
  const [reload, setReload] = useState(0);
  // Bumped after a stage/generate so the staged-edits list re-fetches.
  const [editsReload, setEditsReload] = useState(0);
  // The open ticket form, or null. Pre-targets an existing doc and/or pre-fills a
  // source path depending on which entry point opened it.
  const [form, setForm] = useState<{
    docId?: string;
    sourcePath?: string;
  } | null>(null);
  // The most recent generate result (applied count + fresh gap), shown after it runs.
  const [genResult, setGenResult] = useState<GenerateResponse | null>(null);

  // Per-method API fns, bound to their owner, falling back to the shared client.
  const stageFn = useMemo(
    () =>
      api.stageConfigEdit
        ? api.stageConfigEdit.bind(api)
        : apiClient.stageConfigEdit.bind(apiClient),
    [api],
  );
  const listEditsFn = useMemo(
    () =>
      api.listConfigEdits
        ? api.listConfigEdits.bind(api)
        : apiClient.listConfigEdits.bind(apiClient),
    [api],
  );
  const generateFn = useMemo(
    () =>
      api.generateConfig
        ? api.generateConfig.bind(api)
        : apiClient.generateConfig.bind(apiClient),
    [api],
  );

  const toggleExpanded = (docId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });

  const loader = useCallback(
    () => api.configEditable(repoId, syncKind),
    // `reload` is a deliberate dep: a sync/generate bumps it to force a re-fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [api, repoId, syncKind, reload],
  );
  const state = useApi<EditableConfigTree>(loader, [loader]);

  // The staged edits ("tickets"), re-fetched after a stage or generate.
  const editsLoader = useCallback(
    () => listEditsFn(repoId),
    // `editsReload` forces a re-fetch after stage/generate.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [listEditsFn, repoId, editsReload],
  );
  const editsState = useApi<StoredConfigEdit[]>(editsLoader, [editsLoader]);

  // The pending tickets, used to enable Generate + show the prominent list.
  const stagedEdits = editsState.phase === "ready" ? editsState.data : [];
  const pendingEdits = stagedEdits.filter((e) => e.status === "pending");

  // Generate token UX (mirrors SyncControls): token-less first; reveal input on
  // 401/403; a typed token retries.
  const [genAuthRequired, setGenAuthRequired] = useState(false);
  const [genToken, setGenToken] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  const handleGenerate = useCallback(async () => {
    setGenError(null);
    setGenerating(true);
    try {
      const result = await generateFn(repoId, {}, genToken.trim());
      setGenResult(result);
      // Re-fetch the tree (now live) AND the staged-edits list (now applied).
      setReload((n) => n + 1);
      setEditsReload((n) => n + 1);
    } catch (err: unknown) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setGenAuthRequired(true);
        setGenError(
          err.status === 401
            ? "Auth required: a valid token is needed to generate."
            : "Auth invalid: that token was rejected.",
        );
      } else {
        setGenError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setGenerating(false);
    }
  }, [generateFn, repoId, genToken]);

  const head = (
    <>
      <h1>
        Mapping: <span className="repo-id">{repoId}</span>
      </h1>
      <SyncControls
        repoId={repoId}
        api={api}
        syncKind={syncKind}
        onSynced={() => setReload((n) => n + 1)}
      />
      <form
        className="sync-kind-toggle"
        aria-label="sync kind"
        onSubmit={(e) => e.preventDefault()}
      >
        <label>
          Source
          <select
            value={syncKind}
            onChange={(e) => setSyncKind(e.target.value as SyncKind)}
          >
            {SYNC_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
      </form>
    </>
  );

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        {head}
        <p role="status">Loading mapping…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        {head}
        <p role="alert" className="error">
          Failed to load mapping: {state.message}
        </p>
      </section>
    );
  }

  const tree = state.data;

  const onStaged = () => {
    setEditsReload((n) => n + 1);
    setForm(null);
  };

  return (
    <section className="mapping">
      {head}

      {form ? (
        <Modal title="File a mapping ticket" onClose={() => setForm(null)}>
          <MappingTicketForm
            repoId={repoId}
            documents={tree.documents}
            unitFiles={tree.unit_files}
            docStyles={tree.doc_styles}
            initialDocId={form.docId}
            initialSourcePath={form.sourcePath}
            api={{ stageConfigEdit: stageFn }}
            onStaged={onStaged}
            onClose={() => setForm(null)}
          />
        </Modal>
      ) : null}

      <StagedEditsSection
        state={editsState}
        pending={pendingEdits}
        onGenerate={handleGenerate}
        generating={generating}
        genAuthRequired={genAuthRequired}
        genToken={genToken}
        onGenToken={setGenToken}
        genError={genError}
        genResult={genResult}
      />

      <DocumentsSection
        documents={tree.documents}
        expanded={expanded}
        onToggle={toggleExpanded}
        onEditMapping={(docId) => setForm({ docId })}
      />

      <UnlinkedSection
        files={tree.undocumented_files}
        onLink={(sourcePath) => setForm({ sourcePath })}
      />

      <IgnoredSection files={tree.ignored_files} />
    </section>
  );
}

/** Section 1: the documents, each a collapsible row revealing code_refs + context_refs. */
function DocumentsSection({
  documents,
  expanded,
  onToggle,
  onEditMapping,
}: {
  documents: EditableDocument[];
  expanded: Set<string>;
  onToggle: (docId: string) => void;
  onEditMapping: (docId: string) => void;
}) {
  return (
    <div className="mapping-documents panel">
      <h2>Documents</h2>
      {documents.length === 0 ? (
        <p className="mapping-documents__empty">
          No documents configured for this repo.
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Document</th>
              <th scope="col">Audience</th>
              <th scope="col">Unit</th>
              <th scope="col">Regions</th>
              <th scope="col">Refs</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((entry) => {
              const doc = entry.document;
              const isOpen = expanded.has(doc.doc_id);
              const codeCount = entry.code_refs.length;
              const ctxCount = doc.context_refs.length;
              return (
                <RowFragment key={doc.doc_id}>
                  <tr>
                    <th scope="row">
                      <span className="doc-id">{doc.doc_id}</span>
                      <span className="doc-path"> ({doc.path})</span>
                    </th>
                    <td>
                      <span className="badge audience-badge">{doc.audience}</span>
                    </td>
                    <td>
                      <span className="chip unit-chip">{doc.unit}</span>
                    </td>
                    <td>
                      {doc.region_keys.length > 0 ? (
                        <span className="region-chips">
                          {doc.region_keys.map((key) => (
                            <span key={key} className="chip region-chip">
                              {key}
                            </span>
                          ))}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="ticket-toggle"
                        aria-expanded={isOpen}
                        onClick={() => onToggle(doc.doc_id)}
                      >
                        {`${isOpen ? "Hide" : "View"} ${codeCount} code · ${ctxCount} context`}
                      </button>
                      <button
                        type="button"
                        className="edit-mapping-btn"
                        onClick={() => onEditMapping(doc.doc_id)}
                      >
                        Edit mapping…
                      </button>
                    </td>
                  </tr>
                  {isOpen ? (
                    <tr className="mapping-refs-row">
                      <td colSpan={5}>
                        <DocumentRefs entry={entry} />
                      </td>
                    </tr>
                  ) : null}
                </RowFragment>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** A transparent grouping so a document can render its row + an optional detail row. */
function RowFragment({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

/** The expanded relationship view: TWO clearly-separated sub-lists — the documented
 * surface (`code_refs`) and the generation-context references (`context_refs`). */
function DocumentRefs({ entry }: { entry: EditableDocument }) {
  return (
    <div className="mapping-refs panel">
      <CodeRefs entry={entry} />
      <ContextRefs entry={entry} />
    </div>
  );
}

/** Sub-list A: the documented surface — each path + its symbol chips, or "whole file". */
function CodeRefs({ entry }: { entry: EditableDocument }) {
  return (
    <div className="code-refs">
      <h3 className="code-refs__label">Linked source files</h3>
      {entry.code_refs.length === 0 ? (
        <p className="code-refs__empty">No code refs for this document.</p>
      ) : (
        <ul className="code-refs__list">
          {entry.code_refs.map((ref) => (
            <li key={ref.path} className="code-refs__item">
              <span className="file-path">{ref.path}</span>
              {ref.symbols.length > 0 ? (
                <span className="symbol-chips">
                  {ref.symbols.map((sym) => (
                    <span key={sym} className="chip symbol-chip">
                      {sym}
                    </span>
                  ))}
                </span>
              ) : (
                <span className="code-refs__nosymbols">whole file</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Sub-list B: the generation-context references — VISUALLY DISTINCT from code_refs
 * (a separate "Context (glance-through)" section), each path + its note. NOT coverage. */
function ContextRefs({ entry }: { entry: EditableDocument }) {
  const refs = entry.document.context_refs;
  return (
    <div className="context-refs">
      <h3 className="context-refs__label">Context (glance-through)</h3>
      {refs.length === 0 ? (
        <p className="context-refs__empty">none</p>
      ) : (
        <ul className="context-refs__list">
          {refs.map((ref) => (
            <li key={ref.path} className="context-refs__item">
              <span className="chip context-chip">context</span>
              <span className="file-path">{ref.path}</span>
              {ref.note ? (
                <span className="context-refs__note">{ref.note}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Section 2: the in-scope-but-unlinked source files (the coverage gap), flat. */
function UnlinkedSection({
  files,
  onLink,
}: {
  files: string[];
  onLink: (sourcePath: string) => void;
}) {
  return (
    <div className="mapping-unlinked panel">
      <h2>Unlinked source files ({files.length})</h2>
      {files.length === 0 ? (
        <p className="mapping-unlinked__empty">
          Every in-scope source file is linked to a document.
        </p>
      ) : (
        <ul className="mapping-unlinked__list">
          {files.map((path) => (
            <li key={path} className="mapping-unlinked__item">
              <span className="file-path">{path}</span>
              <button
                type="button"
                className="link-to-doc-btn"
                onClick={() => onLink(path)}
              >
                Link to a document…
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Section 0: the staged "tickets" + the "Generate / make live" action. Shows the
 * pending edits prominently; Generate is enabled only when there ARE pending edits;
 * on success the result (applied count + fresh gap) is shown and the host re-fetches. */
function StagedEditsSection({
  state,
  pending,
  onGenerate,
  generating,
  genAuthRequired,
  genToken,
  onGenToken,
  genError,
  genResult,
}: {
  state: ReturnType<typeof useApi<StoredConfigEdit[]>>;
  pending: StoredConfigEdit[];
  onGenerate: () => void;
  generating: boolean;
  genAuthRequired: boolean;
  genToken: string;
  onGenToken: (v: string) => void;
  genError: string | null;
  genResult: GenerateResponse | null;
}) {
  const edits = state.phase === "ready" ? state.data : [];
  return (
    <div className="mapping-staged panel" aria-label="staged edits">
      <h2>Staged edits ({pending.length} pending)</h2>

      {state.phase === "loading" ? (
        <p role="status">Loading staged edits…</p>
      ) : state.phase === "error" ? (
        <p role="alert" className="error">
          Failed to load staged edits: {state.message}
        </p>
      ) : edits.length === 0 ? (
        <p className="mapping-staged__empty">No staged edits yet.</p>
      ) : (
        <ul className="mapping-staged__list">
          {edits.map((e) => (
            <li
              key={e.edit_id}
              className={`mapping-staged__item mapping-staged__item--${e.status}`}
            >
              <span className="edit-id">{e.edit_id}</span>
              <span className="chip edit-action">{e.edit.action}</span>
              <span className={`chip edit-status edit-status--${e.status}`}>
                {e.status}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="mapping-staged__actions">
        <button
          type="button"
          className="generate-btn"
          disabled={generating || pending.length === 0}
          onClick={onGenerate}
        >
          {generating ? "Generating…" : "Generate / make live"}
        </button>
      </div>

      {genAuthRequired ? (
        <form
          className="mapping-staged__auth"
          aria-label="generate auth"
          onSubmit={(e) => e.preventDefault()}
        >
          <label>
            Token
            <input
              type="password"
              value={genToken}
              placeholder="bearer token to generate"
              onChange={(e) => onGenToken(e.target.value)}
            />
          </label>
        </form>
      ) : null}

      {genError ? (
        <p role="alert" className="error">
          {genError}
        </p>
      ) : null}

      {genResult ? (
        <p className="mapping-staged__result" role="status">
          Applied {genResult.applied.length} edit
          {genResult.applied.length === 1 ? "" : "s"} ·{" "}
          {genResult.sync_run?.fully_synced ? "fully synced" : "not fully synced"} ·{" "}
          {genResult.undocumented_files.length} undocumented file
          {genResult.undocumented_files.length === 1 ? "" : "s"}
        </p>
      ) : null}
    </div>
  );
}

/** Section 3: ignored files — a collapsed-by-default `<details>` at the bottom. */
function IgnoredSection({ files }: { files: string[] }) {
  return (
    <details className="mapping-ignored panel">
      <summary>Ignored files ({files.length})</summary>
      {files.length === 0 ? (
        <p className="mapping-ignored__empty">No ignored files.</p>
      ) : (
        <ul className="mapping-ignored__list">
          {files.map((path) => (
            <li key={path} className="mapping-ignored__item">
              <span className="file-path">{path}</span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

export default Mapping;
