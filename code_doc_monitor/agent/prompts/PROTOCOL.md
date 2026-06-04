---
name: cdmon-verdict-contract
description: "The wire contract every remediation reply must satisfy: a single JSON object carrying a verdict, a one-line cause, and an optional fix. Injected into the agent prompt verbatim; mirrors the BackendResult / ProposedFix pydantic models so a reply round-trips into a ReviewRecord."
domain: docs
subdomain: drift
subject: verdict
kind: contract
version: 1
status: stable
tags: [contract, json, verdict, backend-result, schema]
---

# Verdict Contract

The remediation agent's reply is parsed by a machine, logged into a versioned
public `ReviewRecord` (K6), and — when the verdict is `FIX` and auto-apply is
on — used to rewrite the document. So the reply shape is a hard contract, not a
suggestion. This protocol is the single source of that shape; it mirrors the
`BackendResult` and `ProposedFix` models exactly.

## Contract Rules

1. **Reply with ONE JSON object and no other text.** No prose, no markdown
   fences, no leading or trailing commentary. The parser scans for the first
   balanced `{...}`; anything before it that looks like an object will be parsed
   instead.

2. **The object has exactly these top-level keys:**

   ```json
   {
     "verdict": "FIX | INVALIDATE | ESCALATE",
     "cause": "one-sentence explanation of why",
     "fix": { ... } | null
   }
   ```

   `verdict` MUST be one of the three literals. `cause` MUST be a non-empty
   string. `fix` MUST be `null` for `INVALIDATE` and `ESCALATE`, and an object
   for `FIX`.

3. **A `fix` object has exactly these keys (fill exactly one shape — see
   TOOL.md):**

   ```json
   {
     "region_id":       "<id> | null",
     "new_region_body": "<regenerated region body> | null",
     "new_doc_text":    "<full corrected document> | null",
     "rationale":       "what was regenerated and from what"
   }
   ```

   * **Region shape** (REGION drift): set `region_id` + `new_region_body`, leave
     `new_doc_text` null.
   * **Whole-doc shape** (HASH / MISSING_DOC drift): set `new_doc_text`, leave
     `region_id` + `new_region_body` null.

   Filling both shapes, or neither, is a contract violation.

4. **`new_region_body` carries no trailing newline.** The body is the lines
   strictly between the region markers; a trailing newline produces perpetual
   drift.

5. **Deterministic content.** Regenerate region/document content solely from the
   provided surface. No timestamps, no random ordering, no invented facts.

## Failure Reporting

A reply that violates this contract is re-asked once (the graph's bounded
re-ask), then raised as a typed `BackendError` (K8) — never silently coerced
into a partial verdict.
