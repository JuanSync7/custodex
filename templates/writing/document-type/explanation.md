# Document type: explanation

An explanation is understanding-oriented prose that illuminates *why* a system
is the way it is. The reader is not trying to do a task right now; they want
the bigger picture, the rationale, the trade-offs, and how the pieces fit.

Guidance:

- Frame around concepts and decisions, not steps or symbols. Answer "why",
  "what if", and "how does this relate to that".
- Give the history of the SYSTEM where it clarifies a design: the constraint
  that forced a choice, the alternative that was rejected and why. That is
  context the reader needs in order to decide.
- Never give the history of the DOCUMENT. "The earlier version of this guide
  said X" is not context, it is autobiography — cut it. If the old text named a
  trap, restate the trap in the present tense.
- Make trade-offs explicit. Name the tension and which side the design chose.
- Connect ideas: show how a component relates to its neighbours and to the
  system's goals.
- It is fine to express a considered opinion, clearly marked as such.
- Do not turn into instructions or a reference dump; if you find yourself
  listing every parameter, that belongs elsewhere.
- Use diagrams or analogies when they make a relationship clearer than prose.

## Not its job

Steps to follow (that is a how-to) or an exhaustive catalogue (that is a
reference). An explanation earns its place by making the next decision easier: it
names the alternative that was rejected and why, and the conditions under which
the answer would change.
