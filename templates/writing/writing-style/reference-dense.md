# Writing style: reference-dense

A reference-dense style packs the maximum verifiable information into the
minimum prose. It is built for the reader who scans and extracts, not the one
who reads linearly.

Guidance:

- Front-load the load-bearing fact in each sentence and paragraph; the reader may
  stop after the first line.
- Prefer tables, definition lists and tight bullets over flowing paragraphs when
  content is enumerable. Keep sentences short and declarative.
- Cut connective filler ("it is important to note that", "as you can see").
- Use parallel structure across entries so the eye can pattern-match down a page.
- Keep one canonical phrasing per fact; do not restate the same point three ways.

## Every sentence stands alone

A reader arrives here from a search result, not from the top of the page.

- Do not open a sentence with "this", "it" or "the above" pointing across a
  heading boundary — name the thing you mean. Never write "as noted above".
- Make each entry legible without the surrounding narrative.

## One fact, one home

- When a fact belongs to another document, state the conclusion the reader must
  act on and point at that document. Do not carry its reasons, counts, values or
  flags across.
- Two live copies of a fact are a contradiction on a delay timer: they drift
  apart, and the reader cannot tell which one went stale.

## Match the shape you were given

- Read the sections already present and reproduce their skeleton: the same
  heading depth and order, the same fields in the same sequence, the same
  phrasing for the same kind of statement.
- Identifiers other text can cite — section numbers, entry ids, heading anchors —
  are a fixed interface, not presentation. Carry each one through unchanged,
  attached to the same content. Give a new entry the next number past the highest
  present; never renumber the set.
- Open each section by naming what the reader gets — a result, an object, a
  capability — in one sentence. "Returns the parsed configuration for one run"
  beats "About configuration parsing". A topic label is not an opening.

## Write for the next change

Where two phrasings are equally true and equally clear today, choose the one that
will still be true after the code changes: state what the surface *is*, rather
than when it changed, what it used to be, or how many of a thing there happen to
be right now.
