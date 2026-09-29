# Document type: runbook

A runbook is executed top to bottom by someone who may be under pressure and may
not have written any of it. The reader's contract is: *I will run this, in order,
and it will work.* Success is measured by whether they can, without asking anyone.

Guidance:

- Give an order proven to work, and say what the procedure assumes on entry and
  leaves behind on exit.
- One action per step, with one outcome.
- Every step carries a **pass condition** stated as something observable — an
  exact string, an exit code, a value with its range. "Verify it worked" is not
  a pass condition.
- Every step carries a **failure branch**: what the failure means and where to go
  next, named as a section rather than "investigate".
- Say who runs it, on which host, as which user, and from where.
- Commands are copy-paste clean: no shell prompts, no output interleaved.
  Placeholders in `<angle-brackets>`, named before the block.
- A consideration travels *with* its step. A step without its consideration is
  how an operator ends up with a green check over a broken system.
- Prefer the wrapper that carries the guards over the raw command it wraps.

## Not its job

Explaining why the system is built this way (that is an explanation), or
cataloguing every option (that is a reference). Where a step needs background,
state the one sentence the operator needs to act and point at the document that
owns the rest.
