---
title: "The agent layer"
description: "Entities, doc mapping, the knowledge graph, onboarding, the doc writer, and the two background suggesters — what EPIC AGT adds and how to drive it."
---

# The agent layer

Custodex's agent layer (EPIC AGT) turns the monitor into a set of **specific,
robust task agents**. The design rule behind every one of them is **K11:
agents suggest; humans apply** — each agent produces advisory, auditable data
with a deterministic identity, and nothing changes your config or docs except
an explicit human verb.

## Entities — the deterministic mention layer (`cdx entities`)

Every backticked span and markdown link in a managed doc's prose is linked
against a **closed registry** built from the code surface, the managed-doc
set, and the repo file tree — no LLM anywhere in the index (the LazyGraphRAG
split). Precision beats recall: an ambiguous mention is unresolved-or-ignored,
**never guessed**. Unresolved mentions are the **graph-rot signal** — prose
pointing at code that no longer exists — and both the dogfood and the demo
corpora pin it at **zero**, so any regression fails loudly. The resolution
universe honors your ignore config, so a gitignored build artifact can never
flip a mention between checkouts.

## Doc mapping — suggested edges you accept or reject (`cdx deps --suggest`, `cdx link`)

The mapping agent proposes `depends_on` edges with a provenance **tier** and
evidence: `resolved_link` (one doc's prose links another) or `shared_symbol`
(doc A mentions a symbol exactly one doc B covers). `cdx link DOWN UP` accepts
— a comment-preserving splice into your unit YAML plus an immediate baseline
stamp, so the edge arrives reviewed. `cdx link --reject` records a **durable
no** in `.cdmon/edge-rejections.jsonl`: the pair never comes back, and the
background workers honor it too.

## The knowledge graph (`cdx graph`, the Graph tab)

One deterministic fold of everything Custodex knows: DOCUMENTS, DEPENDS_ON,
MENTIONS, LINKS_TO, PART_OF, OWNED_BY — typed nodes and provenance-tiered
edges, with per-doc unresolved counts riding along. Section names are slugs,
so the artifact carries no doc prose and mirrors safely to the hub (K2). The
console's **Graph** tab renders the pushed snapshot: kind counts, the rot
signal, the *what-to-document-next* feed (mentioned-but-undocumented symbols),
and a focus-node edge browser.

## Onboarding — the config author (`cdx onboard`)

Point it at any repo: it analyzes packages, guesses doc candidates **with
evidence**, and proposes a complete `config/cdmon/`. The default run is a
dry-run plan; `--apply` writes, scaffolds, heals and self-validates so the
very first `cdx check` an adopter runs is **green**.

## The doc writer (`cdx write-doc`)

One verb from an undocumented source file to a registered, conformant,
check-green document — mechanical where the machine is right (scaffold,
fingerprints), backend-authored where prose is needed (the `overview` region
is `mode: llm`, so the standing heal loop **re-authors it when the code
moves**).

## The two background suggesters (`cdx suggest`, the Suggestions tab)

Two workers run in parallel: a **fixes** suggester (drifted docs, suspect
edges, promotable review shapes) and a **docs** suggester (coverage gaps from
the graph, mapping suggestions). Each suggestion has a deterministic key over
structured fields — a reworded detail keeps its key, a drift that recurs
after a heal is new work — and every detail embeds the exact next human
command. On the server they are **off by default**; when enabled they
reconcile a per-repo inbox: items that stop being true auto-resolve,
reappearing ones reopen, and a human **dismiss is durable**. The console's
**Suggestions** tab shows pending items with severity chips and keeps the
resolved/dismissed audit trail visibly separate.
