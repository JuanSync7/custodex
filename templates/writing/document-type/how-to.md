# Document type: how-to guide

A how-to guide is a recipe for a competent reader who has a specific goal and
needs the steps to achieve it. Unlike a tutorial, it assumes background
knowledge and does not teach; unlike reference, it is task-shaped, not
surface-shaped.

Guidance:

- Title the guide as the task it accomplishes, phrased as a goal
  ("Rotate the central token", "Add a coverage waiver").
- State preconditions first: what must already be true or installed.
- Give a numbered sequence of actions. Each step is an imperative
  ("Run...", "Set...", "Verify...").
- Address the real-world problem, including the branching a practitioner hits;
  it is fine to cover a couple of variations within one task.
- Omit conceptual background — link to an explanation instead of inlining it.
- Show commands and config exactly, and show how to confirm the task succeeded.
- Keep it focused on one goal; a second goal is a second how-to.

## Not its job

Teaching the domain (that is a tutorial), cataloguing the surface (that is a
reference), or justifying the design (that is an explanation). When the reader
needs one of those, state the conclusion they need here and point at the document
that owns it.

## Every command block a reader is meant to run

- **Copy-paste clean.** No shell prompts, no output interleaved with the command.
  Show output in a separate block, labelled as output.
- **Context stated.** Which host, which user, which directory — in a leading
  comment or the sentence before.
- **A pass condition**, stated as something observable: an exact string, an exit
  code, a value with its expected range. "Verify it worked" is not a pass
  condition.
- **A failure branch:** what a failure means and where to go next. "Investigate"
  is not a destination.
- **Placeholders in `<angle-brackets>`**, named before the block.

The test: someone who has read only this section can run the block and know, from
its output alone, whether it worked.

A consideration travels *with* its command, in a sentence or two. A command
without its consideration is how a check ends up reporting success while
measuring nothing.

## One action per step

A step is one action with one outcome. State the entry state the procedure
assumes and the exit state it produces, so a reader can tell whether they are in
a position to start and whether they finished.
