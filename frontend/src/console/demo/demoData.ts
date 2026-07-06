// The showcase demo dataset (juansync.dev). The static Pages build has NO backend,
// so the demo console runs the REAL components against this baked-in dataset via a
// mock `fetch` (see ./demoFetch). The shapes are the same ones the tests exercise,
// so the demo can never drift from the live API contract — it reuses the test
// fixtures verbatim and only ADDS the ownership view (the one shape the unit tests
// build inline rather than export).
//
// Two repos tell the story: `acme/widget` is busy (drift records, partial coverage,
// an orphaned doc, a stale doc), and `octo/docs` is a clean/empty repo — so the
// Fleet shows both a working and a quiet repo, and drilling into the busy one walks
// through every headline feature (drift → ownership → staleness → coverage).
import {
  configDocuments,
  configTemplates,
  coverage,
  docGraph,
  editableTree,
  generateResponse,
  health,
  records,
  repos,
  resolutions,
  serverSettings,
  staleness,
  statuses,
  storedConfigEdits,
} from "../test/fixtures";
import type {
  GraphSnapshot,
  OwnershipData,
  RepoHealth,
  StalenessData,
  SuggestionsData,
  Worklist,
} from "../types";

const EMPTY_HEALTH = (repoId: string): RepoHealth => ({
  repo_id: repoId,
  total: 0,
  escalations: 0,
  escalation_rate: 0,
  unresolved: 0,
  overrides: 0,
  resolved: 0,
  mttr_seconds: null,
});

const EMPTY_STALENESS: StalenessData = {
  findings: [],
  stale_count: 0,
  now: staleness.now,
};

// Accountability view — the one shape the unit tests build inline. `core-api`'s DRI
// (dana) has departed while the durable `platform-team` still owns it, so it is a
// SOFT orphan a reassignment clears — exactly the EPIC OWN demo story.
const WIDGET_OWNERSHIP: OwnershipData = {
  owners: [
    {
      doc_id: "core-api",
      doc_path: "docs/api/core-api.md",
      audience: "eng-guide",
      owner: "platform-team",
      team: "platform-team",
      dri: "dana",
      accountable: "dana",
      durable: "platform-team",
    },
    {
      doc_id: "io-api",
      doc_path: "docs/api/io-api.md",
      audience: "eng-guide",
      owner: "platform-team",
      team: "platform-team",
      dri: "ravi",
      accountable: "ravi",
      durable: "platform-team",
    },
    {
      doc_id: "getting-started",
      doc_path: "docs/getting-started.md",
      audience: "user-guide",
      owner: "docs-guild",
      team: "docs-guild",
      dri: "mei",
      accountable: "mei",
      durable: "docs-guild",
    },
  ],
  findings: [
    {
      doc_id: "core-api",
      doc_path: "docs/api/core-api.md",
      audience: "eng-guide",
      status: "orphan_dri_vacant",
      detail: "DRI `dana` has departed; the durable owner `platform-team` is active — reassign a new DRI to clear.",
      accountable: "dana",
      owner: "platform-team",
      team: "platform-team",
      dri: "dana",
    },
  ],
  orphan_count: 1,
};

const EMPTY_OWNERSHIP: OwnershipData = {
  owners: [],
  findings: [],
  orphan_count: 0,
};

// WL-01 — the per-owner review triage for the busy repo. This is the REPO-LOCAL view
// (`includes_suspect: true`), so it shows all three reasons, bucketed under each doc's
// LIVE assignee — consistent with the Ownership tab (same dataset): core-api is a
// DRI-vacant orphan (`dana` departed), so its orphan + stale work re-routes to the
// still-active durable owner `platform-team` (never `dana`'s dead queue); `getting-started`
// (accountable `mei`) has a suspect upstream; `io-api` (accountable `ravi`) was never
// reviewed. The HUB strips suspect items (K2), but the demo runs the repo-local picture
// so the console shows the full feature.
const WIDGET_WORKLIST: Worklist = {
  owners: [
    {
      accountable: "mei",
      items: [
        {
          doc_id: "getting-started",
          doc_path: "docs/getting-started.md",
          audience: "user-guide",
          reason: "suspect",
          severity: "low",
          detail:
            "upstream `io-api` changed since this doc last referenced it — re-check the dependency",
          upstream_id: "io-api",
        },
      ],
      item_count: 1,
      doc_count: 1,
    },
    {
      // core-api's DRI `dana` departed (DRI-vacant) → its work re-routes to the
      // still-active durable owner, NOT the departed `dana`.
      accountable: "platform-team",
      items: [
        {
          doc_id: "core-api",
          doc_path: "docs/api/core-api.md",
          audience: "eng-guide",
          reason: "orphan",
          severity: "high",
          detail:
            "DRI `dana` has departed; the durable owner `platform-team` is active — reassign a new DRI to clear.",
          upstream_id: null,
        },
        {
          doc_id: "core-api",
          doc_path: "docs/api/core-api.md",
          audience: "eng-guide",
          reason: "stale",
          severity: "medium",
          detail: "reviewed 172 days ago; SLA is 90 days — re-review due",
          upstream_id: null,
        },
      ],
      item_count: 2,
      doc_count: 1,
    },
    {
      accountable: "ravi",
      items: [
        {
          doc_id: "io-api",
          doc_path: "docs/api/io-api.md",
          audience: "eng-guide",
          reason: "stale",
          severity: "high",
          detail: "never reviewed; SLA is 90 days",
          upstream_id: null,
        },
      ],
      item_count: 1,
      doc_count: 1,
    },
  ],
  item_count: 4,
  doc_count: 3,
  includes_suspect: true,
};

const EMPTY_WORKLIST: Worklist = {
  owners: [],
  item_count: 0,
  doc_count: 0,
  includes_suspect: true,
};

// AGT-03/AGT-07: the busy repo's mirrored knowledge-graph snapshot — small but
// exercising every table on the Graph page: kind counts, a rot signal, one
// mentioned-but-undocumented symbol, and focusable in/out edges.
const WIDGET_GRAPH: GraphSnapshot = {
  schema_version: "1.0.0",
  captured_at: "2026-06-20T09:00:00Z",
  nodes: [
    { id: "doc docs/api/core-api.md", kind: "doc", name: "core-api" },
    { id: "doc docs/guide.md", kind: "doc", name: "guide" },
    { id: "symbol src/widget/engine.py#Engine", kind: "symbol", name: "Engine" },
    { id: "symbol src/widget/queue.py#drain_queue", kind: "symbol", name: "drain_queue" },
    { id: "section docs/guide.md#usage", kind: "section", name: "usage" },
    { id: "owner mei", kind: "owner", name: "mei" },
  ],
  edges: [
    {
      source: "doc docs/api/core-api.md",
      target: "symbol src/widget/engine.py#Engine",
      kind: "documents",
      tier: "declared",
    },
    {
      source: "doc docs/guide.md",
      target: "doc docs/api/core-api.md",
      kind: "depends_on",
      tier: "declared",
    },
    {
      source: "doc docs/guide.md",
      target: "symbol src/widget/engine.py#Engine",
      kind: "mentions",
      tier: "resolved",
    },
    {
      source: "doc docs/guide.md",
      target: "symbol src/widget/queue.py#drain_queue",
      kind: "mentions",
      tier: "resolved",
    },
    {
      source: "doc docs/api/core-api.md",
      target: "symbol src/widget/queue.py#drain_queue",
      kind: "mentions",
      tier: "resolved",
    },
    {
      source: "section docs/guide.md#usage",
      target: "doc docs/guide.md",
      kind: "part_of",
      tier: "resolved",
    },
    {
      source: "doc docs/guide.md",
      target: "owner mei",
      kind: "owned_by",
      tier: "declared",
    },
  ],
  unresolved: { guide: 1, "core-api": 0 },
  warnings: [],
};

const EMPTY_GRAPH: GraphSnapshot = {};

// AGT-06/AGT-07: the busy repo's suggestion inbox — one of each lifecycle
// state so the pending/closed separation renders.
const WIDGET_SUGGESTIONS: SuggestionsData = {
  repo_id: "acme/widget",
  include_closed: true,
  suggestions: [
    {
      key: "a1b2c3d4e5f60718",
      kind: "fix_drift",
      doc_id: "core-api",
      target: "docs/api/core-api.md",
      detail:
        "1 drift(s) [HASH] on docs/api/core-api.md — review and heal with `cdx monitor --apply`",
      evidence: ["HASH:signature moved"],
      severity: "high",
      status: "pending",
      source: "worker",
      recorded_at: "2026-06-20T09:00:00Z",
      updated_at: "2026-06-20T09:00:00Z",
    },
    {
      key: "b2c3d4e5f6071829",
      kind: "document_gap",
      doc_id: null,
      target: "symbol src/widget/queue.py#drain_queue",
      detail:
        "symbol src/widget/queue.py#drain_queue is mentioned by 2 doc(s) but covered by none — draft a doc with `cdx write-doc src/widget/queue.py`",
      evidence: ["2 mentioning doc(s)"],
      severity: "low",
      status: "pending",
      source: "worker",
      recorded_at: "2026-06-20T09:00:00Z",
      updated_at: "2026-06-20T09:00:00Z",
    },
    {
      key: "c3d4e5f607182930",
      kind: "resolve_edge",
      doc_id: "guide",
      target: "core-api",
      detail:
        "edge guide → core-api is suspect — review the upstream change, then `cdx resolve --edge guide core-api`",
      evidence: ["suspect: upstream changed since last review"],
      severity: "medium",
      status: "resolved",
      source: "worker",
      recorded_at: "2026-06-18T09:00:00Z",
      updated_at: "2026-06-20T09:00:00Z",
    },
    {
      key: "d4e5f60718293041",
      kind: "add_edge",
      doc_id: "guide",
      target: "io-api",
      detail:
        "shared_symbol evidence links guide → io-api — accept with `cdx link guide io-api` or silence with `cdx link --reject guide io-api`",
      evidence: ["symbol src/widget/io.py#read_frame"],
      severity: "low",
      status: "dismissed",
      source: "worker",
      recorded_at: "2026-06-15T09:00:00Z",
      updated_at: "2026-06-16T09:00:00Z",
    },
  ],
};

const EMPTY_SUGGESTIONS = (repoId: string): SuggestionsData => ({
  repo_id: repoId,
  include_closed: true,
  suggestions: [],
});

const BUSY = "acme/widget";

/** Per-repo demo data. The busy repo carries the full story; the quiet repo is
 *  intentionally empty so the Fleet shows both states. */
export const DEMO = {
  health: { status: "ok" as const },
  repos,
  configTemplates,
  serverSettings,
  byRepo: (repoId: string) => ({
    status: statuses[repoId] ?? null,
    records: repoId === BUSY ? records : [],
    resolutions: repoId === BUSY ? resolutions : [],
    coverage: repoId === BUSY ? coverage : [],
    ownership: repoId === BUSY ? WIDGET_OWNERSHIP : EMPTY_OWNERSHIP,
    worklist: repoId === BUSY ? WIDGET_WORKLIST : EMPTY_WORKLIST,
    graph: repoId === BUSY ? WIDGET_GRAPH : EMPTY_GRAPH,
    suggestions:
      repoId === BUSY ? WIDGET_SUGGESTIONS : EMPTY_SUGGESTIONS(repoId),
    staleness: repoId === BUSY ? staleness : EMPTY_STALENESS,
    health: repoId === BUSY ? health : EMPTY_HEALTH(repoId),
    documents: repoId === BUSY ? configDocuments : [],
    docGraph: repoId === BUSY ? docGraph : { edges: [], edge_count: 0 },
    editable: editableTree,
    configEdits: storedConfigEdits,
    generate: generateResponse,
  }),
};
