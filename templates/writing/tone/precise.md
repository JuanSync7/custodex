# Tone: precise

A precise tone prizes accuracy above warmth. The reader should be able to act on
a sentence without re-reading it, and every claim should be checkable against the
code surface.

Guidance:

- One idea per sentence. Split a sentence carrying two claims.
- Use the exact identifier names, types and values from the surface, in
  `code font`. Prefer concrete nouns and specific verbs ("returns the parsed
  config" beats "handles the configuration").
- State conditions explicitly: "when `timeout` is 0", not "in some cases".
- Name an edge rather than glossing it.
- Avoid hedges ("should usually", "probably") unless the uncertainty is real,
  and marketing adjectives ("powerful", "seamless", "robust"), which assert
  without informing.

## Claim discipline (shared by every tone)

These rules are not tone-dependent; they hold whatever voice the document uses.

### Grade every claim by what you can check

- State as fact only what the code surface establishes. Mark anything designed,
  planned or not yet exercised in the sentence itself — "is intended to", "is
  not yet implemented" — so the reader never has to guess whether a claim is
  observed behaviour or stated intent.
- Never assert that something was executed, verified, deployed, reviewed or
  accepted. None of that is visible in a code surface.
- Give a completeness claim its denominator: "6 of 6 backends accept a timeout",
  never a bare "all", "fully supported" or "healthy". If you cannot count both
  numbers, drop the claim rather than rounding it up. A number you cannot say
  the method for is an opinion with digits.

### State what is true, not since when

- Say whether a thing is there, not which release put it there: "the object form
  is not accepted", never "was removed in 2.4.0". A version number in prose is a
  fact with no owner — it goes stale silently at the next release, and the reader
  cannot tell whether it still holds. Write a version literal only where it is
  the thing itself: a command someone copies, or a value in a config file.
- Do not date the prose, and avoid words that decay: "currently", "recently",
  "new", "at the time of writing". Version control holds the timeline.

### Write the current truth, not the document's autobiography

You are given the document's existing text alongside the current surface, so the
difference between them is visible to you. It is an input, not subject matter.

- Never write "previously", "used to be", "the earlier version", "has been
  renamed/updated/fixed", or "this section now …".
- The test: would a reader who had never seen an earlier version lose anything
  they need **in order to act**? If not, the clause goes.
- "is now" and "no longer" are correct about the *system* — "the loader no longer
  accepts a bare string" states a current absence the reader must design around.
  They are wrong about the *text*.
- Deleting the autobiography is not deleting the warning inside it. If a
  historical clause named a trap, restate the trap in the present tense.
- Resolve a disagreement; never record one. Where the existing prose and the
  surface conflict, the surface wins — rewrite the sentence. Never leave a wrong
  value standing beside its correction: a skimming reader takes the first value
  they see.
