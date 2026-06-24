# Vocabulary: engine-domain

Use the custodex engine's own vocabulary so documents read consistently
with the system they describe. These are terms of art; use them precisely and do
not coin synonyms for them.

Canonical terms:

- **drift** — a detected mismatch between a document and the code surface it
  describes. Kinds include HASH, REGION, MISSING_DOC, and UNHEALABLE.
- **surface / code surface** — the projected symbol/record/switch view of the
  referenced code; the single source of truth a document is graded against.
- **managed region** — a `CDM:BEGIN/END` block whose body the engine owns;
  carries an authority **mode** (`generated`, `llm`, `human`, `llm-seeded`).
- **heal** — applying a fix so a document matches its surface again.
- **verdict** — a backend's decision for a drift: FIX, INVALIDATE, or ESCALATE.
- **waiver** — an intentional, justified documentation gap.
- **coverage** — the share of the scoped code surface that is documented.
- **audience** — `user-guide` (public surface only) or `eng-guide` (internal too).

Guidance: prefer "the surface" over "the code"; "managed region" over "block";
"author" for prose an `llm` region produces, "render" for a mechanical region.
