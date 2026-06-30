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
  OwnershipData,
  RepoHealth,
  StalenessData,
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

// WL-01 — the per-owner review triage for the busy repo. This is the REPO-LOCAL
// view (`includes_suspect: true`), so it shows all three reasons: `dana` owns the
// orphaned + stale core-api and a suspect doc whose upstream moved; the Unowned
// bucket holds io-api (never reviewed). The HUB strips suspect items (K2), but the
// demo runs the repo-local picture so the console shows the full feature.
const WIDGET_WORKLIST: Worklist = {
  owners: [
    {
      accountable: "dana",
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
      item_count: 3,
      doc_count: 2,
    },
    {
      accountable: null,
      items: [
        {
          doc_id: "io-api",
          doc_path: "docs/api/io-api.md",
          audience: "eng-guide",
          reason: "stale",
          severity: "medium",
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
    staleness: repoId === BUSY ? staleness : EMPTY_STALENESS,
    health: repoId === BUSY ? health : EMPTY_HEALTH(repoId),
    documents: repoId === BUSY ? configDocuments : [],
    docGraph: repoId === BUSY ? docGraph : { edges: [], edge_count: 0 },
    editable: editableTree,
    configEdits: storedConfigEdits,
    generate: generateResponse,
  }),
};
