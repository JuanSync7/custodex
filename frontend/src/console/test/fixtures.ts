// Realistic fixtures mirroring the server's RegisteredRepo / RepoStatus shapes
// (code_doc_monitor/server/store.py + app.py). Used by the component tests.
import type {
  ApplyFixResponse,
  ConfigDocumentTree,
  CoverageSnapshot,
  EditableConfigTree,
  EditableDocument,
  GenerateResponse,
  RegisteredRepo,
  RepoHealth,
  RepoStatus,
  ResolutionRecord,
  ReviewRecord,
  StoredConfigEdit,
  SyncRun,
} from "../types";

export const repos: RegisteredRepo[] = [
  {
    repo: {
      repo_id: "acme/widget",
      repo_name: "Widget",
      repo_url: "https://example.com/acme/widget",
      commit: "abc1234",
    },
    default_branch: "main",
    description: "The widget service",
  },
  {
    repo: { repo_id: "octo/docs", repo_name: null, repo_url: null, commit: null },
    default_branch: null,
    description: null,
  },
];

export const statuses: Record<string, RepoStatus> = {
  "acme/widget": {
    repo_id: "acme/widget",
    total_records: 7,
    by_verdict: { ok: 4, review: 2, escalate: 1 },
    escalations: 1,
    unresolved: 3,
    last_detected_at: "2026-06-04T12:00:00Z",
    coverage_ratio: 0.82,
  },
  "octo/docs": {
    repo_id: "octo/docs",
    total_records: 0,
    by_verdict: { ok: 0, review: 0, escalate: 0 },
    escalations: 0,
    unresolved: 0,
    last_detected_at: null,
    coverage_ratio: null,
  },
};

// ── F-02/F-03 fixtures (mirror schema.py::ReviewRecord/ResolutionRecord) ─────

export const records: ReviewRecord[] = [
  {
    schema_version: "1.0.0",
    record_id: "rec-escalate-1",
    doc_id: "guide/install",
    doc_path: "docs/install.md",
    audience: "user-guide",
    drift_kind: "signature_changed",
    drift_detail: "install() gained a `force` parameter",
    cause: "the doc never mentions the new flag",
    verdict: "ESCALATE",
    fix: null,
    surface_hash: "aaaa1111",
    backend_kind: "anthropic",
    detected_at: "2026-06-04T09:00:00Z",
    resolved_at: "2026-06-04T09:00:00Z",
    config_snapshot: {},
    source_sha: "sha-aaa",
    ticket: {
      schema_version: "1.0.0",
      ticket_id: "tic-escalate-1",
      title: "[HIGH] signature_changed in guide/install",
      summary:
        "install() gained a `force` parameter. The remediation agent's read: the doc never mentions the new flag",
      severity: "high",
      drift_kind: "signature_changed",
      doc_id: "guide/install",
      doc_path: "docs/install.md",
      region_id: null,
      audience: "user-guide",
      affected_symbols: ["install", "uninstall"],
      root_cause: "the doc never mentions the new flag",
      proposed_change: "Needs a human author — the doc never mentions the new flag",
      change_kind: "none",
      diff: "- install(path)\n+ install(path, force=False)",
      acceptance_criteria: [
        { text: "A human has authored the missing/owned content", auto_satisfied: false },
        { text: "The new content is in sync with the code surface", auto_satisfied: false },
      ],
      verdict: "ESCALATE",
      recommended_action: "Escalate to a human author",
    },
  },
  {
    schema_version: "1.0.0",
    record_id: "rec-fix-2",
    doc_id: "eng/architecture",
    doc_path: "docs/arch.md",
    audience: "eng-guide",
    drift_kind: "moved_symbol",
    drift_detail: "Store moved to server/store.py",
    cause: "stale import path in the doc",
    verdict: "FIX",
    fix: { rationale: "update the import path", new_doc_text: "from .server.store import Store" },
    surface_hash: "bbbb2222",
    backend_kind: "anthropic",
    detected_at: "2026-06-04T10:30:00Z",
    resolved_at: "2026-06-04T10:30:00Z",
    config_snapshot: {},
    source_sha: "sha-bbb",
  },
];

export const resolutions: ResolutionRecord[] = [
  {
    schema_version: "1.0.0",
    record_id: "rec-fix-2",
    resolution: "accepted",
    resolved_text: null,
    resolved_by: "alice",
    resolved_at: "2026-06-04T11:00:00Z",
    note: "merged as-is",
  },
];

// ── F-05 fixture (mirrors app.RepoHealth) ───────────────────────────────────

export const health: RepoHealth = {
  repo_id: "acme/widget",
  total: 4,
  escalations: 1,
  escalation_rate: 0.25,
  unresolved: 2,
  overrides: 1,
  resolved: 2,
  mttr_seconds: 90,
};

export const coverage: CoverageSnapshot[] = [
  { ratio: 0.5, detected_at: "2026-06-01T00:00:00Z", documented: 5, undocumented: 5, waived: 0 },
  {
    ratio: 0.82,
    detected_at: "2026-06-04T00:00:00Z",
    documented: 9,
    undocumented: 1,
    waived: 1,
    files: [
      {
        path: "src/install.py",
        language: "python",
        owners: ["guide/install"],
        status: "documented",
        waived_reason: null,
      },
      {
        path: "src/legacy.py",
        language: "python",
        owners: [],
        status: "undocumented",
        waived_reason: null,
      },
      {
        path: "src/generated.py",
        language: "python",
        owners: [],
        status: "waived",
        waived_reason: "auto-generated; not authored by hand",
      },
    ],
  },
];

// A snapshot WITHOUT `files` (older shape) for the baskets-only fallback test.
export const coverageNoFiles: CoverageSnapshot[] = [
  {
    ratio: 0.6,
    detected_at: "2026-06-03T00:00:00Z",
    documented: 6,
    undocumented: 4,
    waived: 0,
  },
];

// ── W-02 fixture (the canonical config/cdmon/ template strings) ─────────────

export const configTemplates: {
  unit: string;
  index: string;
  ignore: string;
  doc_style: string;
} = {
  unit: "# config/cdmon/units/installer.yaml\nunit: installer\ncode:\n  - ../../src/install.py\n",
  index: "# config/cdmon/index.yaml\nrepo: acme/widget\ndocuments:\n  - doc_id: guide/install\n    path: ../../docs/install.md\n",
  ignore: "# config/cdmon/ignore.yaml\nignore:\n  - ../../**/generated/**\n",
  doc_style: "# config/cdmon/doc-style.yaml\nstyles:\n  user-guide: ../../templates/writing/user-guide.md\n",
};

// ── W-01 fixture (config documents + their code_refs; the relationship view) ─

export const configDocuments: ConfigDocumentTree[] = [
  {
    document: {
      repo_id: "acme/widget",
      doc_id: "guide/install",
      path: "docs/install.md",
      audience: "user-guide",
      unit: "installer",
      region_keys: ["intro", "flags"],
      context_refs: [
        { path: "docs/api/core-api.md", note: "link to the full engine reference" },
      ],
      sync_kind: "git",
      ref: "main",
      synced_at: "2026-06-04T09:00:00Z",
    },
    code_refs: [
      {
        repo_id: "acme/widget",
        doc_id: "guide/install",
        path: "src/install.py",
        symbols: ["install", "uninstall"],
        unit: "installer",
        sync_kind: "git",
      },
      {
        repo_id: "acme/widget",
        doc_id: "guide/install",
        path: "src/flags.py",
        symbols: [],
        unit: "installer",
        sync_kind: "git",
      },
    ],
  },
  {
    document: {
      repo_id: "acme/widget",
      doc_id: "eng/architecture",
      path: "docs/arch.md",
      audience: "eng-guide",
      unit: "core",
      region_keys: [],
      context_refs: [],
      sync_kind: "git",
      ref: "main",
      synced_at: "2026-06-04T10:30:00Z",
    },
    code_refs: [
      {
        repo_id: "acme/widget",
        doc_id: "eng/architecture",
        path: "src/server/store.py",
        symbols: ["Store"],
        unit: "core",
        sync_kind: "git",
      },
    ],
  },
];

// ── FEAT-CONFIGV2-016 fixtures: a monitored README (narrative) document ─────

/** A README document tree — a user-guide narrative with no managed region,
 * tracked against the CLI surface it documents. Surfaced in its OWN section. */
export const readmeDocTree: ConfigDocumentTree = {
  document: {
    repo_id: "acme/widget",
    doc_id: "readme",
    path: "README.md",
    audience: "user-guide",
    unit: "core",
    region_keys: [],
    context_refs: [],
    sync_kind: "git",
    ref: "main",
    synced_at: "2026-06-04T09:00:00Z",
  },
  code_refs: [
    {
      repo_id: "acme/widget",
      doc_id: "readme",
      path: "src/cli.py",
      symbols: [],
      unit: "core",
      sync_kind: "git",
    },
  ],
};

/** A drift record against the README (its public CLI surface moved). */
export const readmeRecord: ReviewRecord = {
  schema_version: "1.0.0",
  record_id: "rec-readme-1",
  doc_id: "readme",
  doc_path: "README.md",
  audience: "user-guide",
  drift_kind: "signature_changed",
  drift_detail: "the CLI gained a `cdmon trace` command",
  cause: "the README's command list is stale",
  verdict: "FIX",
  fix: { rationale: "regenerate the command list", new_doc_text: "…" },
  surface_hash: "cccc3333",
  backend_kind: "mock",
  detected_at: "2026-06-04T12:30:00Z",
  resolved_at: "2026-06-04T12:30:00Z",
  config_snapshot: {},
  source_sha: "sha-ccc",
};

/** A README entry for the editable (Mapping) tree. */
export const readmeEditableDoc: EditableDocument = {
  document: {
    repo_id: "acme/widget",
    doc_id: "readme",
    path: "README.md",
    audience: "user-guide",
    unit: "core",
    region_keys: [],
    context_refs: [],
    sync_kind: "local",
    ref: "local",
    synced_at: "2026-06-06T09:00:00Z",
  },
  code_refs: [
    {
      repo_id: "acme/widget",
      doc_id: "readme",
      path: "src/taskflow/cli.py",
      symbols: [],
      unit: "core",
      sync_kind: "local",
    },
  ],
};

// ── W-03 fixtures (the Y-02 SyncRun summary) ────────────────────────────────

/** A git sync that is behind main with two drifts (the "needs attention" case). */
export const syncRunGit: SyncRun = {
  sync_kind: "git",
  fully_synced: false,
  commits_ahead: 3,
  document_count: 12,
  code_ref_count: 24,
  drift: {
    ok: false,
    drift_count: 2,
    by_kind: { signature_changed: 1, moved_symbol: 1 },
    coverage_percent: 82,
  },
  branch: "main",
  head_commit: "abc1234",
  main_commit: "def5678",
  ref: "main",
  started_at: "2026-06-05T12:00:00Z",
  finished_at: "2026-06-05T12:00:09Z",
  repo_id: "acme/widget",
};

/** A clean local sync that is fully in sync with no drift (the "all good" case). */
export const syncRunLocal: SyncRun = {
  sync_kind: "local",
  fully_synced: true,
  commits_ahead: 0,
  document_count: 12,
  code_ref_count: 24,
  drift: {
    ok: true,
    drift_count: 0,
    by_kind: {},
    coverage_percent: 100,
  },
  branch: "main",
  head_commit: "abc1234",
  main_commit: "abc1234",
  ref: "local",
  started_at: "2026-06-05T12:05:00Z",
  finished_at: "2026-06-05T12:05:04Z",
  repo_id: "acme/widget",
};

// ── EDITOR (E-08) fixtures — the editable tree + staged edits + responses ────

/** The editable config tree the Mapping page renders (app.EditableConfigTree). */
export const editableTree: EditableConfigTree = {
  repo_id: "acme/widget",
  sync_kind: "local",
  documents: [
    {
      document: {
        repo_id: "acme/widget",
        doc_id: "guide/getting-started",
        path: "docs/guide/getting-started.md",
        audience: "user-guide",
        unit: "core",
        region_keys: ["intro"],
        context_refs: [
          { path: "docs/api/core-api.md", note: "full engine reference" },
          { path: "src/taskflow/core/engine.py", note: null },
        ],
        sync_kind: "local",
        ref: "local",
        synced_at: "2026-06-06T09:00:00Z",
      },
      code_refs: [
        {
          repo_id: "acme/widget",
          doc_id: "guide/getting-started",
          path: "src/taskflow/core/model.py",
          symbols: ["Task"],
          unit: "core",
          sync_kind: "local",
        },
      ],
    },
  ],
  undocumented_files: ["src/taskflow/core/scheduler.py"],
  ignored_files: ["tests/conftest.py"],
  unit_files: ["core", "installer"],
  doc_styles: {
    document_type: ["tutorial", "reference"],
    tone: ["neutral", "friendly"],
    writing_style: ["concise"],
    vocabulary: ["plain"],
  },
};

/** A list of staged edits in the three lifecycle states (edits.StoredConfigEdit). */
export const storedConfigEdits: StoredConfigEdit[] = [
  {
    edit_id: "edit-001",
    status: "pending",
    created_at: "2026-06-06T10:00:00Z",
    applied_at: null,
    edit: {
      action: "create_doc",
      unit: "core",
      doc_id: "guide/scheduling",
      path: "docs/guide/scheduling.md",
      audience: "user-guide",
      code_refs: [
        { path: "src/taskflow/core/scheduler.py", symbols: ["Scheduler"] },
      ],
      context_refs: [{ path: "docs/api/core-api.md", note: "engine ref" }],
      doc_style: { document_type: "tutorial", tone: "friendly" },
    },
  },
  {
    edit_id: "edit-002",
    status: "applied",
    created_at: "2026-06-06T10:01:00Z",
    applied_at: "2026-06-06T10:05:00Z",
    edit: {
      action: "add_code_ref",
      unit: "core",
      doc_id: "guide/getting-started",
      ref: { path: "src/taskflow/core/engine.py", lines: "10-42" },
    },
  },
];

/** The POST /config/generate response after making one edit live. */
export const generateResponse: GenerateResponse = {
  applied: ["edit-001"],
  sync_run: syncRunLocal,
  undocumented_files: [],
};

/** The POST /records/{id}/apply-fix response after applying an LLM fix. */
export const applyFixResponse: ApplyFixResponse = {
  applied: true,
  doc_path: "docs/guide/getting-started.md",
  diff: "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n",
  sync_run: syncRunLocal,
};
