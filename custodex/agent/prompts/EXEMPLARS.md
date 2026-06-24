---
name: cdmon-few-shot-exemplars
description: "The few-shot framing for retrieved past-resolved drifts. Loaded ONLY when the remediation carries exemplars (the most-similar past drifts a human has already resolved). Tells the agent how to read them: as precedent, not as facts — the code surface is still the only source of truth."
domain: docs
type: reference
tags: [exemplars, few-shot, retrieval, precedent, reference]
---

# cdmon-few-shot-exemplars

This remediation comes with **exemplars** — the most-similar past drifts that a
human has already resolved, retrieved by feature match (same document, drift
kind, code surface, audience). They are *precedent*, not *facts*.

## How to use the exemplars

1. **Follow the precedent for the SHAPE of the answer**, not its content. If a
   similar past drift was `ACCEPTED`, the proposed fix style was right — mirror
   how it regenerated the region/document. If it was `OVERRIDDEN`, the
   human rewrote the fix: the `resolved_text` is the gold answer for that
   drift — prefer its wording/structure when the two drifts truly match.
2. **If a similar past drift was `INVALIDATED`**, that audience treated the
   change as irrelevant — a strong signal to INVALIDATE this one too, when the
   surface change is of the same (comment/docstring/private) nature.
3. **If it was `REJECTED`**, the past fix was wrong — do NOT repeat it.
4. **The code surface is still the only source of truth (K2).** An exemplar
   never licenses a fact the current surface does not contain. When the exemplar
   and the surface disagree, the surface wins; the exemplar only guides FORM.

Each exemplar below lists the past drift, its human outcome, and — for an
`overridden` outcome — the exact `resolved_text` the human committed.
