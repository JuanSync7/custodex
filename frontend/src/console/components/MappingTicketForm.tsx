// EDITOR E-10: the mapping-ticket FORM — an inline panel that builds and submits
// ONE `ConfigEdit` (the "ticket"). Opened from the Mapping page two ways:
//   • "Edit mapping…" on a document → pre-targets that doc_id + unit (existing doc).
//   • "Link to a document…" on an unlinked file → pre-fills the source file path and
//     lets the user pick a target document (existing or new).
//
// Edit assembly (form fields → the right tagged `ConfigEdit` action):
//   • New document                       → `create_doc` (unit, doc_id, path, audience,
//                                            code_refs from source+scope, context_refs,
//                                            doc_style).
//   • Existing doc + a source file       → `add_code_ref` (unit, doc_id, ref).
//   • Existing doc + only context refs    → `set_context_refs`.
//   • Existing doc + only a doc-style      → `set_doc_style`.
// When several aspects change at once on an EXISTING doc we stage them as multiple
// sequential single-action edits (each is its own ticket; predictable + tested).
//
// Token UX mirrors <SyncControls> (L-01): submit token-less first; only a 401/403
// reveals a token input + an auth message; a typed token retries.
import { useMemo, useState } from "react";
import { apiClient, ApiError } from "../api/client";
import type {
  ConfigEdit,
  DocStyleOptions,
  EditCodeRef,
  EditContextRef,
  EditDocStyle,
  EditableDocument,
} from "../types";

/** The slice of the API this form needs — fakeable in tests (no network). */
export interface MappingTicketFormApi {
  stageConfigEdit(
    repoId: string,
    edit: ConfigEdit,
    token: string,
  ): Promise<{ edit_id: string }>;
}

export interface MappingTicketFormProps {
  repoId: string;
  /** The existing documents (target dropdown) — each gives doc_id + unit. */
  documents: EditableDocument[];
  /** Existing unit stems (the unit dropdown when creating a NEW document). */
  unitFiles: string[];
  /** The selectable doc-style options per category (the four dropdowns). */
  docStyles: DocStyleOptions;
  /** Pre-target an EXISTING document (the "Edit mapping…" entry point). */
  initialDocId?: string;
  /** Pre-fill the source file path (the "Link to a document…" entry point). */
  initialSourcePath?: string;
  /** Injected client; falls back to the shared singleton when absent. */
  api?: MappingTicketFormApi;
  /** Called after every successful stage so the host can refresh the list. */
  onStaged?: (editIds: string[]) => void;
  /** Close the form (Cancel, or after a successful submit). */
  onClose?: () => void;
}

const AUDIENCES = ["eng-guide", "user-guide"] as const;
type Scope = "all" | "lines" | "symbols";

/** "" sentinel = the "new document" choice in the target dropdown. */
const NEW_DOC = "";

const STYLE_CATEGORIES = [
  ["document_type", "Document type"],
  ["tone", "Tone"],
  ["writing_style", "Writing style"],
  ["vocabulary", "Vocabulary"],
] as const;

export function MappingTicketForm({
  repoId,
  documents,
  unitFiles,
  docStyles,
  initialDocId,
  initialSourcePath,
  api,
  onStaged,
  onClose,
}: MappingTicketFormProps) {
  const stageFn = useMemo(
    () =>
      api?.stageConfigEdit
        ? api.stageConfigEdit.bind(api)
        : apiClient.stageConfigEdit.bind(apiClient),
    [api],
  );

  // Target document: an existing doc_id, or NEW_DOC ("") for a new document.
  const [targetDocId, setTargetDocId] = useState<string>(
    initialDocId ?? (documents.length > 0 ? documents[0].document.doc_id : NEW_DOC),
  );
  const isNewDoc = targetDocId === NEW_DOC;

  // New-document fields.
  const [newDocId, setNewDocId] = useState("");
  const [newDocPath, setNewDocPath] = useState("");
  const [newAudience, setNewAudience] = useState<string>(AUDIENCES[0]);
  const [newUnit, setNewUnit] = useState<string>(
    unitFiles.length > 0 ? unitFiles[0] : "",
  );

  // Source file + its scope.
  const [sourcePath, setSourcePath] = useState(initialSourcePath ?? "");
  const [scope, setScope] = useState<Scope>("all");
  const [lines, setLines] = useState("");
  const [symbols, setSymbols] = useState("");

  // Doc-style selection (each "" = "— default —").
  const [style, setStyle] = useState<Record<string, string>>({
    document_type: "",
    tone: "",
    writing_style: "",
    vocabulary: "",
  });

  // Context references (a repeatable add-row).
  const [contextRefs, setContextRefs] = useState<EditContextRef[]>([]);
  const [ctxPath, setCtxPath] = useState("");
  const [ctxNote, setCtxNote] = useState("");

  // Token UX (mirror SyncControls): token-less first; reveal input on 401/403.
  const [authRequired, setAuthRequired] = useState(false);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const targetDoc = documents.find((d) => d.document.doc_id === targetDocId);

  /** Build the EditCodeRef from the source path + the chosen scope. */
  function buildCodeRef(): EditCodeRef | null {
    const path = sourcePath.trim();
    if (!path) return null;
    if (scope === "lines") {
      const range = lines.trim();
      return range ? { path, lines: range } : { path };
    }
    if (scope === "symbols") {
      const names = symbols
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      return names.length > 0 ? { path, symbols: names } : { path };
    }
    return { path };
  }

  /** Build the chosen doc-style payload, or null when no dimension is set. */
  function buildDocStyle(): EditDocStyle | null {
    const ds: EditDocStyle = {};
    if (style.document_type) ds.document_type = style.document_type;
    if (style.tone) ds.tone = style.tone;
    if (style.writing_style) ds.writing_style = style.writing_style;
    if (style.vocabulary) ds.vocabulary = style.vocabulary;
    return Object.keys(ds).length > 0 ? ds : null;
  }

  /**
   * Assemble the form into one or more `ConfigEdit`s. A new document is always a
   * single `create_doc`. An existing doc may yield up to three single-action edits
   * (add_code_ref, set_context_refs, set_doc_style) — each its own ticket.
   */
  function assembleEdits(): ConfigEdit[] {
    const codeRef = buildCodeRef();
    const docStyle = buildDocStyle();

    if (isNewDoc) {
      const edit: ConfigEdit = {
        action: "create_doc",
        unit: newUnit,
        doc_id: newDocId.trim(),
        path: newDocPath.trim(),
        audience: newAudience,
        ...(codeRef ? { code_refs: [codeRef] } : {}),
        ...(contextRefs.length > 0 ? { context_refs: contextRefs } : {}),
        ...(docStyle ? { doc_style: docStyle } : {}),
      };
      return [edit];
    }

    // An existing document: one ticket per changed aspect, in a predictable order.
    if (!targetDoc) return [];
    const unit = targetDoc.document.unit;
    const docId = targetDoc.document.doc_id;
    const edits: ConfigEdit[] = [];
    if (codeRef) {
      edits.push({ action: "add_code_ref", unit, doc_id: docId, ref: codeRef });
    }
    if (contextRefs.length > 0) {
      edits.push({
        action: "set_context_refs",
        unit,
        doc_id: docId,
        context_refs: contextRefs,
      });
    }
    if (docStyle) {
      edits.push({ action: "set_doc_style", doc_id: docId, doc_style: docStyle });
    }
    return edits;
  }

  function addContextRef() {
    const path = ctxPath.trim();
    if (!path) return;
    const note = ctxNote.trim();
    setContextRefs((prev) => [...prev, note ? { path, note } : { path }]);
    setCtxPath("");
    setCtxNote("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const edits = assembleEdits();
    if (edits.length === 0) {
      setError("Nothing to stage: add a source file, context ref, or doc style.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const ids: string[] = [];
      // Stage sequentially so each ticket is its own row, in a predictable order.
      for (const edit of edits) {
        const { edit_id } = await stageFn(repoId, edit, token.trim());
        ids.push(edit_id);
      }
      onStaged?.(ids);
      onClose?.();
    } catch (err: unknown) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setAuthRequired(true);
        setError(
          err.status === 401
            ? "Auth required: a valid token is needed to stage this edit."
            : "Auth invalid: that token was rejected.",
        );
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="mapping-ticket-form"
      aria-label="mapping ticket form"
      onSubmit={handleSubmit}
    >

      <label className="ticket-field">
        Target document
        <select
          value={targetDocId}
          onChange={(e) => setTargetDocId(e.target.value)}
        >
          <option value={NEW_DOC}>+ New document…</option>
          {documents.map((d) => (
            <option key={d.document.doc_id} value={d.document.doc_id}>
              {d.document.doc_id} ({d.document.unit})
            </option>
          ))}
        </select>
      </label>

      {isNewDoc ? (
        <fieldset className="ticket-newdoc">
          <legend>New document</legend>
          <label className="ticket-field">
            Doc id
            <input
              type="text"
              value={newDocId}
              placeholder="guide/scheduling"
              onChange={(e) => setNewDocId(e.target.value)}
            />
          </label>
          <label className="ticket-field">
            Path
            <input
              type="text"
              value={newDocPath}
              placeholder="docs/guide/scheduling.md"
              onChange={(e) => setNewDocPath(e.target.value)}
            />
          </label>
          <label className="ticket-field">
            Audience
            <select
              value={newAudience}
              onChange={(e) => setNewAudience(e.target.value)}
            >
              {AUDIENCES.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
          <label className="ticket-field">
            Unit
            <select value={newUnit} onChange={(e) => setNewUnit(e.target.value)}>
              {unitFiles.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
      ) : null}

      <fieldset className="ticket-source">
        <legend>Source file</legend>
        <label className="ticket-field">
          Path
          <input
            type="text"
            value={sourcePath}
            placeholder="src/taskflow/core/scheduler.py"
            onChange={(e) => setSourcePath(e.target.value)}
          />
        </label>
        <label className="ticket-field">
          Scope
          <select value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
            <option value="all">whole file</option>
            <option value="lines">line range</option>
            <option value="symbols">specific symbols</option>
          </select>
        </label>
        {scope === "lines" ? (
          <label className="ticket-field">
            Lines (start-end)
            <input
              type="text"
              value={lines}
              placeholder="10-42"
              onChange={(e) => setLines(e.target.value)}
            />
          </label>
        ) : null}
        {scope === "symbols" ? (
          <label className="ticket-field">
            Symbols (comma-separated)
            <input
              type="text"
              value={symbols}
              placeholder="Scheduler, run"
              onChange={(e) => setSymbols(e.target.value)}
            />
          </label>
        ) : null}
      </fieldset>

      <fieldset className="ticket-docstyle">
        <legend>Doc style</legend>
        {STYLE_CATEGORIES.map(([cat, label]) => {
          const options = docStyles[cat as keyof DocStyleOptions];
          return (
            <label key={cat} className="ticket-field">
              {label}
              <select
                value={style[cat]}
                onChange={(e) =>
                  setStyle((prev) => ({ ...prev, [cat]: e.target.value }))
                }
              >
                <option value="">— default —</option>
                {options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </label>
          );
        })}
      </fieldset>

      <fieldset className="ticket-context">
        <legend>Context references</legend>
        {contextRefs.length > 0 ? (
          <ul className="ticket-context__list">
            {contextRefs.map((ref, i) => (
              <li key={`${ref.path}-${i}`} className="ticket-context__item">
                <span className="file-path">{ref.path}</span>
                {ref.note ? (
                  <span className="ticket-context__note">{ref.note}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="ticket-context__add">
          <label className="ticket-field">
            Context path
            <input
              type="text"
              value={ctxPath}
              placeholder="docs/api/core-api.md"
              onChange={(e) => setCtxPath(e.target.value)}
            />
          </label>
          <label className="ticket-field">
            Note
            <input
              type="text"
              value={ctxNote}
              placeholder="optional"
              onChange={(e) => setCtxNote(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="ticket-context__add-btn"
            onClick={addContextRef}
          >
            Add context ref
          </button>
        </div>
      </fieldset>

      {authRequired ? (
        <label className="ticket-field ticket-auth">
          Token
          <input
            type="password"
            value={token}
            placeholder="bearer token to stage"
            onChange={(e) => setToken(e.target.value)}
          />
        </label>
      ) : null}

      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}

      <div className="ticket-actions">
        <button type="submit" className="ticket-submit-btn" disabled={busy}>
          {busy ? "Staging…" : "Stage ticket"}
        </button>
        <button
          type="button"
          className="ticket-cancel-btn"
          onClick={() => onClose?.()}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default MappingTicketForm;
