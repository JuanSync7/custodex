# Writing templates — the guidance handed to a prose-authoring backend

These files are the **generic, repo-agnostic** half of Custodex's authoring
guidance. `config/cdmon/doc-style.yaml` selects one stem per category; the four
selected bodies are concatenated by `custodex.docstyle.read_style_guidance` in a
fixed order and reach the backend as `FixRequest.style_guidance`, for one case
only: authoring a no-renderer `mode: llm` region. Only the `agent` backend puts
that field into its prompt. The `claude-code` and `api` backends build theirs
with `backends.build_prompt`, which leaves it out, and `cdx write-doc` does not
pass it.

| Category | Selects | Answers |
| --- | --- | --- |
| `document-type` | one of the stems below | what this document is *for*, and what it is **not** for |
| `tone` | `precise` · `formal` · `friendly` | how claims are made |
| `writing-style` | `reference-dense` · `concise` · `narrative` | how the page is shaped for its reader |
| `vocabulary` | `general` · `engine-domain` | which terms of art to use, and not to coin synonyms for |

`document-type` stems: `api-reference`, `how-to`, `tutorial`, `explanation`
(the Diátaxis four) plus `runbook`, `decision-record`, `register`, `record`.

A stem is a free-form name resolved to `<category>/<stem>.md`, so an adopter adds
their own by dropping a file in and naming it. Only the four selected stems are
composed, so adding stems costs nothing at prompt time.

## What belongs here, and what does not

Generic rules only — true of documentation in any repository, and actionable by a
model that can see the code surface, the current document text, and the region it
is authoring. Anything tied to one repository's taxonomy, citation grammar, check
names, or directory layout belongs in **that repository**, as its own templates
selected by its own `doc-style.yaml`. A copy here would be a second live home for
a fact that can change without Custodex knowing — the failure these very
templates tell an author to avoid.

Two rules a template must not state, because the mechanism forbids them:

- **Front matter.** The `cdm:` block is machine-managed: when an engine write (`cdx lint --fix`, an engine heal, docdeps edge stamps, a mirror re-sync) rewrites it, it is re-dumped key-sorted and any comment inside it is lost. Every other top-level key keeps its exact bytes (quoting, list style, folding, comments) when the block is a column-0 block mapping without duplicate, `<<` or aliased top-level keys. Any other layout is re-dumped data-exact (see `manifest.render_doc`). A backend's whole-document fix is written as the backend returned it. A template that tells an author to write or edit the `cdm:` block is telling it to fight the healer.
- **History of the document.** Regions are re-authored from scratch, so anything
  that depends on remembering an earlier version cannot survive. Rules that
  *forbid* narrating history do belong here — the authoring prompt includes the
  document's current text, so an author can see the change and must be told not
  to write about it.

## A known limitation

The category vocabulary is fixed at four. Rules that hold regardless of tone —
claim discipline, denominators, no version literals, no autobiography — therefore
have to be repeated in every `tone/` stem, because only one stem is ever
selected.

They live in one section, `## Claim discipline (shared by every tone)`, which is
the **last** section of every tone stem and is **byte-identical** in each. Edit
all copies together: change one, then paste the whole section, heading to end of
file, over the others. `tests/unit/test_writing_templates.py` fails when the
copies disagree, when a stem lacks the heading, or when a shared rule is missing
from any copy. A new tone stem copies the section verbatim.

A fifth axis — one always-composed shared template — would remove the duplication
and is the right fix if these rules keep growing.
