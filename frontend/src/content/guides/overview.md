# Capabilities guide

A plain-language tour of what Custodex does — and a deep dive on the three
capabilities most recently added. Each capability page answers the same six
questions: **what it is, why it exists, how it works, how to use it, what it's
good at, and where its limits are.**

> This guide is hand-written for humans. The [Wiki](/wiki/features) is the
> machine-generated feature/traceability reference; this is the "why & how".

## The one-sentence version

**Custodex keeps your code and its documentation honest** — it detects when docs
drift out of sync with the code (and with each other), proposes or invalidates a
fix through an LLM, pegs an accountable owner to every document, tracks review
SLAs, and records every verdict as an auditable review record.

## The four pillars

Custodex is built on four orthogonal pillars. Everything else hangs off these.

| Pillar | Question it answers | Core idea |
| --- | --- | --- |
| **A — code↔doc drift** | "Does this doc still match the code it describes?" | Extract the code surface, fingerprint it, flag the doc when the fingerprint moves. |
| **B — doc↔doc dependencies** | "If I change this doc, what else must I re-check?" | A doc declares it `depends_on` another; a per-edge baseline hash flags a *suspect link* when the upstream changes (the Doorstop model). |
| **C — accountability** | "Who owns this doc, and is it overdue for review?" | Config pegs an owner/team/DRI to each doc; a central roster flags departed owners; a review SLA flags stale docs. |
| **D — the central hub** | "What's the state across *all* my repos?" | A FastAPI server mirrors every repo's config + records into a rebuildable database, served read-only. |

**Audience changes every verdict (K3).** A `user-guide` is never flagged for a
comment-only, private, or internal change; an `eng-guide` is. The same code edit
can drift one doc and leave another clean — by design.

**Detection never mutates (K1).** `cdx check` and `cdx drift` are pure: no file
writes, no LLM calls, no network. Fixing is a separate, opt-in step that always
produces a human-reviewable record.

## What's new

These three capabilities sharpen the pillars above. Each has its own page:

- **[Transitive suspect advisory](/guide/transitive-suspect)** *(Pillar B)* —
  when an upstream doc changes, see the *whole* downstream blast radius, not just
  its direct dependents.
- **[Breaking-change severity](/guide/breaking-change-severity)** *(Pillar A)* —
  every code↔doc drift is now graded *breaking / additive / cosmetic*, so a
  reviewer can tell an API break from a prose tweak at a glance.
- **[Per-owner review worklist](/guide/review-worklist)** *(Pillars B + C)* —
  one prioritised queue per accountable owner, joining orphaned, stale, and
  suspect documents into a single triage view.

## How you interact with Custodex

Three surfaces, one engine:

- **The `cdx` CLI** — `cdx check` (detect), `cdx monitor` (detect → fix →
  record), and read-only views (`cdx deps`, `cdx ownership`, `cdx staleness`,
  `cdx worklist`). This is what runs in CI.
- **The console** *(this site)* — a per-repo dashboard: documents, coverage,
  dependencies, ownership, and the review worklist.
- **The central API** — `GET /repos/{id}/…` read routes that serve the same data
  across every registered repo from the rebuildable mirror.
