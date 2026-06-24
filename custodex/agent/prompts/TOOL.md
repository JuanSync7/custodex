---
name: cdmon-fix-shapes
description: "The two mechanical fix shapes a remediation FIX may take — a region-shaped patch or a whole-document rewrite — and the deterministic rule that maps a drift kind to its shape. No judgment; the shape follows from the drift kind."
domain: docs
action: fix-shape
type: reference
tags: [fix-shape, region, whole-doc, mechanical, reference]
---

# cdmon-fix-shapes

A FIX is delivered in one of two shapes. Which one is **not a judgement call** —
it is fixed by the drift kind. This artifact is loaded only when a fix may be
produced (i.e. the drift is healable); a pure ESCALATE needs no fix shape.

## When to use

| Drift kind | Fix shape | Why |
|------------|-----------|-----|
| `REGION` | Region shape | Exactly one managed `CDM:BEGIN/END` region is stale; patch just that region so untouched prose and the fingerprint are left alone (K7). |
| `HASH` | Whole-doc shape | The surface fingerprint moved; regenerate every managed region **and** refresh the front-matter fingerprint in one rewrite, or the loop never converges. |
| `MISSING_DOC` | Whole-doc shape | The document does not exist yet; produce the full conformant document. |
| `UNHEALABLE` | (no fix) | Cannot be regenerated mechanically — ESCALATE, `fix: null`. |

## Region shape

Set on the `fix` object:

```json
{ "region_id": "<the drift's region_id>", "new_region_body": "<regenerated body>",
  "new_doc_text": null, "rationale": "regenerated region <id> from the surface" }
```

`new_region_body` is the content **between** the markers, with no trailing
newline, rendered from the surface.

## Whole-doc shape

Set on the `fix` object:

```json
{ "region_id": null, "new_region_body": null,
  "new_doc_text": "<the FULL corrected document>",
  "rationale": "rewrote the document from the surface; regions + fingerprint refreshed" }
```

`new_doc_text` keeps the human prose verbatim, regenerates every managed region
from the surface, and refreshes the `cdm.fingerprint` front-matter value. It is
the only shape that refreshes the fingerprint, so a HASH drift must use it.
