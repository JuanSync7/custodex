# Per-owner review worklist

*Pillars B + C — dependencies and accountability, joined.*

## What it is

One prioritised **queue per accountable owner**. Custodex already finds three kinds
of documents that need a human's attention:

- **orphaned** — the accountable owner has departed (Pillar C / ownership);
- **stale** — past its review SLA, or never reviewed (Pillar C / staleness);
- **suspect** — a doc↔doc upstream changed (Pillar B / dependencies).

The worklist **joins** all three into a single triage view, bucketed under the
person (or team) who can actually act on each one — so instead of running three
separate reports and cross-referencing owners by hand, each owner sees one list.

## Why it exists

The three signals were already there, but scattered across `cdx ownership`,
`cdx staleness`, and `cdx deps`. Answering "what should *I* review today?" meant
running all three and manually filtering to your name. The worklist does that join
for you, sorts it by urgency, and routes each item to a live owner.

## How it works

- It is a **pure join** — it never re-detects. It consumes the already-computed
  ownership, staleness, and suspect findings and buckets each under its document's
  **accountable** owner (`dri → owner → team → inherited`).
- A document with several problems becomes several **items** but is counted once as
  a **document** — so the UI shows "4 items across 3 docs" without double-counting.
- Items are sorted by **severity, then reason, then document** — high-severity work
  floats to the top of every queue.

### The orphan exception

There's one careful twist. An *orphaned* document's accountable owner has, by
definition, **departed** — so routing its "please reassign me" item to that
person's queue would be a dead letter nobody reads. The worklist re-routes orphan
work to the **live** assignee:

- a **DRI-vacant** doc (the DRI left, but the durable team is still active) → that
  active **team**, the natural place to assign a new DRI;
- an **owner-departed** doc (no active fallback at all) → the **unowned** bucket,
  for an admin to triage.

So a reassignment task always lands where someone can act on it.

## How to use it

**CLI:**

```bash
cdx worklist --roster roster.yaml         # every owner's queue
cdx worklist --owner platform-team        # just one queue
cdx worklist --no-include-suspect         # ownership + staleness only
cdx worklist --fail-on-work               # opt-in CI gate (exit 1 if any work)
```

It's read-only and deterministic (you can pass `--now` to pin the clock). Orphan
items need `--roster` (the list of who's still active); without it, orphans are
skipped.

**Console** — the **Worklist** tab on each repo shows the same queues, with a
severity chip and reason on every row.

**Central hub** — `GET /repos/{id}/worklist` serves the join across every repo. The
hub returns ownership + staleness work, but **omits suspect items** and sets
`includes_suspect: false` — an honest partial view, because per-edge suspect
freshness needs the document bodies, which live in the repo (K2). Run
`cdx worklist` in the repo for the complete picture.

## Advantages

- **One queue per person** — answers "what should I review?" directly, no manual
  cross-referencing.
- **Prioritised** — highest-severity work first, so triage starts where it matters.
- **Routes to someone who can act** — orphaned work goes to the live team or the
  admin triage bucket, never a departed person's dead queue.
- **Opt-in gate** — `--fail-on-work` turns it into a CI check when you want one.

## Limitations

- **The hub view is partial.** Suspect items are repo-local (K2); the central
  `/worklist` route serves ownership + staleness only and says so via
  `includes_suspect: false`.
- **Orphans need a roster.** Without `--roster`, there's no "who departed" data, so
  orphan items are skipped (staleness and suspect still appear).
- **The unowned bucket can't be `--owner`-filtered.** `--owner` targets a *named*
  owner; the unowned/orphan-triage bucket is always shown in the full view.
- **It triages, it doesn't fix.** The worklist tells you *what* needs review and
  *who* owns it; resolving each item is still a human (or `cdx monitor`) action.
