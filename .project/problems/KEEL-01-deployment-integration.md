# Problem KEEL-01 — the project-keel ↔ Custodex integration is stale, and its hook skips green

**Status:** reported, not fixed. Every finding was reproduced first-hand on a
scratch copy of the project-keel repository's tracked files and git metadata
(the Keel checkout itself was only read; only read-only git ran on the copy) and
on this working tree. Keel paths below are relative to the Keel repository root.
A bare script name is short for its path: `cdmon_sync.py` and
`check_structure.py` are under `scripts/`; `build_corpus.py`, `check_corpus.py`
and `review_docs.py` are under `scripts/jobs/`; `cdmon.example.yaml` is under
`config/cdmon/`.
**Decision on record:** report only; the fixes belong in a dedicated pass, and
the Keel-side ones belong in the Keel repo with its own gate.

## What blocks deployment

**Custodex cannot be deployed with Keel until F1–F3 are fixed.** F1 and F3 need
Keel edits. F2 needs either a Keel edit to the adapter (fix-pass item 2) or a
Custodex `heal` command (item 13):

- **F1** — Keel's example config does not load: `version` must be a string, and
  `output` is an extra key the schema forbids.
- **F2** — the adapter's documented `heal` verb is not a `cdx` command. A direct
  `cdx monitor --apply` still sets the baseline fingerprints, so F2 blocks the
  adapter path Keel documents, not the gate.
- **F3** — the hook's `--check` runs `lint` (document structure), not `check`
  (drift), so it never detects drift.

**Registering Keel's documents is also blocked on F9.** The first adoption
step, `cdx lint --fix`, re-renders each registered document's frontmatter in a
form Keel's own line-based readers misread. 92 of the 119 distinct documents
whose frontmatter parses would be read differently, and every authored tag would
be lost. On `scripts/jobs/README.md`, which has a parity `.jinja` twin, the
re-render also turns Keel's `check_structure.py` gate red. The Custodex-side
`cdm:` splice fixes both, with no Keel change. A Keel-side fix needs two changes:
YAML-parsing readers, and that twin's frontmatter re-rendered to match. Neither
fix makes the adoption commit pass by itself, because of F10.

**Unattended heals are blocked on F10.** Every Custodex write to a Keel document
fails Keel's doc-freshness gate unless `updated:` is bumped by hand in the same
change. On the three documents with a parity `.jinja` twin (`README.md`,
`docs/guides/README.md` and `scripts/jobs/README.md`), that bump turns
`check_structure.py` red unless the twin's own `updated:` line is bumped too.

F7, the hook's skip while `config/cdmon/cdmon.yaml` is missing, is **not** a
blocker. It fires only in the undeployed state, where it hides F1–F3; it does not
stop a deployment. Verified on the scratch copy with F1 fixed, a baseline set by
`cdx monitor --apply`, and only `cdmon_sync.py:48` changed to map `--check` to
`check`, both skips (`:40-46`) left byte-unchanged: the hook printed "clean — no
drift detected" and exited 0, then exited 1 with "1 drift(s) detected … HASH" once
the README's `cdm.fingerprint` was tampered with.

| Finding | Side | Blocks | Status |
| --- | --- | --- | --- |
| F1 — example config does not load | Keel | deployment | reported |
| F2 — `heal` is not a `cdx` command | Keel, or Custodex (item 13) | deployment through the adapter; a direct `cdx monitor --apply` sets the baseline | reported |
| F3 — `--check` runs `lint`, not `check` | Keel | deployment | reported |
| F4 — frontmatter keys re-sorted | decision | nothing on its own — a one-time key-order diff | undecided |
| F5 — non-ASCII frontmatter escaped | Custodex | nothing on its own — one cause of F9 | reported |
| F6 — style guidance reaches one backend | Custodex | nothing | reported |
| F7 — hook skips green until `cdmon.yaml` exists | Keel | nothing — hides F1–F3 until then | reported |
| F8 — 7 documents' frontmatter is not valid YAML | Keel | registering those 7 | reported |
| F9 — the re-render corrupts what Keel reads | Custodex, or Keel (readers and twin) | registering 92 of the 119 parseable documents; turns `check_structure` red on a twinned one | reported |
| F10 — every write fails Keel's freshness gate | Keel | unattended heals | reported |

## Why this matters now

Custodex is to be **deployed together with project-keel**. Keel already carries an
integration — `scripts/cdmon_sync.py`, `config/cdmon/cdmon.example.yaml`, a
pre-commit hook, `make check-cdmon`, and a coexistence contract in
`CONVENTIONS.md §9`. None of it works, and the hook reports a skip rather than a
failure, so Keel's gate stays green.

## F1 — the example config does not load (blocker)

`config/cdmon/cdmon.example.yaml` fails `load_config` on two counts:

```
version   Input should be a valid string   [input_value=1, input_type=int]
output    Extra inputs are not permitted   [input_value={'dir': '.cdmon', 'html': False}]
```

`MonitorConfig.version` is `str`; there is no `output` key, and the model is
`extra="forbid"`. The example also omits `root:` and gives its documents no
`code_refs` or `region_keys`, so even once it parses it monitors nothing. Copied
to `cdmon.yaml`, it makes the hook exit 1 with this `ConfigError`.

## F2 — the adapter's `heal` verb does not exist (blocker for the adapter)

`cdmon_sync.py` offers `lint | heal | build` (`:31`), `scripts/README.md:32`
documents the adapter with those three verbs, and `CONVENTIONS.md §9` says Keel's
keys "survive its `heal`/`lint --fix`" (`CONVENTIONS.md:312`). The CLI has
`lint`, `build`, `check` and `monitor`; **`heal` does not exist**. Once
`config/cdmon/cdmon.yaml` exists, `scripts/cdmon_sync.py heal` exits 2 with "No
such command 'heal'". Before that, the adapter's config skip (F7) prints "no
cdmon config at config/cdmon/cdmon.yaml; skipping." and exits 0. The heal verb
is `cdx monitor --apply`.

The adapter runs `cdmon <verb> --config …` (`cdmon_sync.py:48-49`), and `cdmon`
is Custodex's back-compat alias of `cdx`, so either side can fix F2: Keel maps
`heal` to `monitor --apply` in the adapter (item 2), or Custodex adds a `heal`
command that runs `monitor --apply` (item 13).

`§9` names the adapter as the doer that invokes the tool; it does not forbid
calling the tool directly. So F2 blocks deployment through the adapter Keel
documents, not the gate: a direct `cdx monitor --apply` sets the baseline, which
is what fix-pass item 6 does. Until a first `cdx monitor --apply` stamps
`cdm.fingerprint`, `cdx check` exits 1 on every registered document with
`HASH — fingerprint None != current surface hash …`.

## F3 — the hook's `--check` runs `lint`, not `check` (blocker)

The pre-commit hook is named "cdmon code-doc drift" (`.pre-commit-config.yaml:20`),
but `--check` maps to `cdmon lint` (`cdmon_sync.py:48-49`). `lint` validates
document structure against the Layout Standard; drift detection is `cdx check`.
So even with a config that loads, the hook never detects drift.

Measured on Keel's own `README.md`, with a minimally fixed config
(`version: "1.0.0"`, `root: "../.."`, that one document): the hook exits 1 on four
layout issues — `MISSING_SCHEMA_VERSION`, `MISSING_AUDIENCE`, `MISSING_FINGERPRINT`
and `MISSING_PURPOSE`. Keel's documents already carry front matter; what they lack
is a `cdm:` block and a `>` purpose line after the title. `cdx lint --fix` stamps
`cdm.schema_version` and `cdm.audience`, and `cdx monitor --apply` sets the
fingerprint. After both, `MISSING_PURPOSE` is the only issue left, and it needs a
hand-written purpose line. A second `cdx lint --fix` changes nothing. Both writes
are subject to F9 and F10.

## F4 — foreign frontmatter survives as YAML, but is re-sorted (adopter-visible)

`CONVENTIONS.md §9` claims "cdmon preserves foreign top-level frontmatter keys
and writes only under `cdm:`". **The claim holds at the YAML level** — verified
by healing a Keel-shaped document carrying all twelve of its top-level keys;
parsed as YAML, every key and value survived and only `cdm:` was added. The
`lint --fix` half of the claim is pinned by
`tests/integration/test_foreign_frontmatter.py`. It does not hold for the text
Keel's own tools read; F9 covers that.

`manifest.render_doc` calls `yaml.safe_dump(..., sort_keys=True)`, so the keys
come back **alphabetised**: `canonical` leads and `title` lands eleventh. Keel's
house shape is `title:` first (117 of the 119 documents below). Key order alone
changes nothing Keel reads, since its parsers build a mapping, but every
registered Keel document takes a one-time whole-frontmatter reshuffle diff — on
the first `cdx lint --fix` as well as the first heal, since both re-render
through `render_doc`.

**Key order alone does not make heals diff-free.** Measured on the 119 distinct
Keel documents whose frontmatter parses (F8 says how they are counted; 7 more
carry frontmatter that is not valid YAML), counting documents whose frontmatter
round-trips through the render byte-identical:

| Render | Byte-identical round trips |
| --- | --- |
| `render_doc` as shipped (`sort_keys=True`) | 0 of 119 |
| key order preserved | 27 of 119 |
| key order preserved + `allow_unicode=True` (F5) | 70 of 119 |
| key order preserved + F5 + unlimited line width | 74 of 119 |

The remaining 45 differ because flow lists (`tags: [a, b]`) come back as block
lists and some quoted scalars are re-quoted. Diff-free heals need `render_doc` to
splice only the `cdm:` block into the original frontmatter text instead of
re-dumping all of it — the same change F9 needs.

Two options, and they are a genuine conflict rather than a bug:

- **Custodex side** — preserve the incoming frontmatter. The `cdm:`-block splice
  removes the reshuffle and F9's corruption together; an order-preserving
  re-dump alone removes only the reshuffle. Either way the `cdm:` subtree stays sorted
  (the fingerprint-tier helpers insert its keys unsorted and rely on the dump to
  sort them). Makes Custodex a better citizen in any repo with a frontmatter
  convention; needs no Keel edit.
- **Keel side** — accept alphabetical order and note it in §9. This is enough
  only together with F9's Keel-side fix: frontmatter read as YAML, and each
  parity twin's frontmatter brought into the re-rendered form. On its own it
  leaves F9's corruption in place.

> **Correction (2026-09-27 review).** The Custodex-side option was first costed
> as "K10's 'sorted keys' habit and a re-heal of every dogfood doc". Neither
> holds. All 21 frontmatter-bearing documents under `docs/`, `demo/docs/` and
> `examples/*/docs/` re-render byte-identical with key order preserved, so none
> needs a re-heal. K10 is already read as "a fixed, deterministic order" rather
> than "alphabetical" elsewhere (`okf.py`, `docstyle.py` and `config.py` dump with
> `sort_keys=False`), so the option needs a K10 wording change — sorted keys for
> engine-owned data, foreign frontmatter order preserved — not a break.

## F5 — non-ASCII frontmatter is escaped

`render_doc`'s `safe_dump` passes no `allow_unicode`, so an em-dash in a Keel
`title:`/`summary:` — which its house style uses — comes back escaped, and a long
`summary:` refolds as a multi-line double-quoted scalar. It churns every heal,
and Keel's line parsers read the escaped form literally (F9). `allow_unicode=True`
removes the escaping; a long scalar still folds at PyYAML's default 80-column
width, as a plain scalar, until a wider `width=` is passed as well (`report.py`
already dumps with `width=10**9`).

## F6 — style guidance reaches only ONE of the four backends

Not Keel-specific, but it decides how much of the writing-template work is live.
`FixRequest.style_guidance` is rendered by `agent/graph.py:render_context`
**only**. `backends.build_prompt` never renders it — verified by byte-equality:
`build_prompt(req_with_style) == build_prompt(req_without_style)`. So:

| backend | uses the writing templates |
| --- | --- |
| `agent` | yes |
| `claude-code` | **no** — calls `build_prompt` |
| `api` | **no** — calls `build_prompt` |
| `mock` | no, by design (authors deterministically in code) |

An adopter on `backend.kind: api` gets none of the guidance. The fix is small and
additive: render the block in `build_prompt` exactly as `render_context` does,
guarded on `is not None` so a request without guidance stays byte-identical.

A second path misses the guidance on every backend: `cdx write-doc` calls
`draft_document` / `write_and_register` without `style_guidance`, although both
accept it. Only `Monitor._style_guidance_for` threads it into a `FixRequest`.

## F7 — the hook skips green until `cdmon.yaml` exists (visibility, not a blocker)

> **Correction (2026-09-27 review).** This finding, then numbered F3, first said
> that installing Custodex alongside Keel "is the event that turns a green
> pre-commit red", because `cdmon` is a console-script alias of Custodex and the
> `shutil.which("cdmon")` skip would stop firing. That is wrong: a second skip
> still fires. The claim is quoted here as the mistake, so it is not repeated.

`cdmon_sync.py` has two skips, and both exit 0:

1. `:40-43` — `cdmon` is not on `PATH`: prints "cdmon not installed; skipping".
2. `:44-46` — `config/cdmon/cdmon.yaml` (the `DEFAULT_CONFIG` at `:22`) does not
   exist: prints "no cdmon config at config/cdmon/cdmon.yaml; skipping."

Keel ships only `cdmon.example.yaml`. With Custodex installed, `cdmon` is on
`PATH`, the second skip fires, and the hook stays green. Keel documents this as
"a stated skip" (`Makefile:78`, `.github/workflows/ci.yml:28`). The hook goes red
only when someone creates `cdmon.yaml` — for example by copying the example, as
its header comment instructs (`cdmon.example.yaml:1`) — and then it exits 1 with
the F1 `ConfigError`.

The skip is announced, not silent, but it is green, which is why F1–F3 have gone
unnoticed. The manual path fails too: `cdx check` run at Keel's root with no
`--config` exits 1 with "Cannot read config file cdmon.yaml".

This is the same failure shape as RTE-02c's empty coverage universe: a green
result that checked nothing.

## F8 — seven Keel documents carry frontmatter that is not valid YAML

Keel tracks 168 Markdown paths, but 37 of them are `CLAUDE.md` symlinks to a
sibling `AGENT.md`, and Keel's readers read each file once:
`build_corpus.py:596-608` and `check_structure.py:357-374` (`check_A`) skip a path
whose realpath they have already seen, and Keel's corpus has no `CLAUDE.md` node.
Every count in this document is therefore over the 131 distinct files. 126 of
them open with a frontmatter block; 119 of those parse and 7 do not. Each of the
7 has a plain scalar containing `: `, which YAML does not allow unquoted, for
example `title: ADR-0001: Record architecture decisions` and
`summary: System-level shape: components, boundaries, data flow, tech choices.`
Keel's own gate accepts them: `check_structure.py:295` (`parse_frontmatter`)
splits each line on its first colon, and `check_structure.py` exits 0 on the tree.

- `api/edge_nginx/README.md`
- `docs/adr/0001-record-architecture-decisions.md`
- `docs/architecture/README.md`
- `docs/architecture/transports.md`
- `docs/design/documentation-quality.md`
- `docs/design/keel-hardening-plan.md`
- `test-docs/coverage/register.md`

Registering any one of them fails the whole run, not just that document (K8).
With `docs/architecture/README.md` registered beside `README.md`, `cdx check` and
`cdx monitor --apply` both exit 1 with "Malformed YAML front matter in
docs/architecture/README.md: mapping values are not allowed here" and check
nothing else. ADR-0001 and the architecture README are two of the first
documents an adopter would register.

Only read-only `cdx lint` goes on past such a document: it reports it as
`MALFORMED_STRUCTURE` and lints the rest. `cdx lint --fix` stops at it. With
`README.md` registered before `docs/architecture/README.md`, it printed "fixed
front matter: README.md", then exited 1 with the same "Malformed YAML front
matter" error: `README.md` was rewritten (12 lines added, 6 removed) and no
layout issue was reported. With the malformed document registered first, it
exits 1 before writing anything, so what is left half-written depends on
registration order.

## F9 — the re-render corrupts what Keel's own tools read (blocker for registering documents)

Keel reads frontmatter with a line parser, not YAML.
`scripts/jobs/build_corpus.py:154-171` (`_parse_frontmatter`, which feeds
`wiki/corpus.json`, the one-brain index) and `check_structure.py:295`
(`parse_frontmatter`) skip a line that starts with a space or tab, split every
other line on its first colon, and ignore a line with no colon.
`CONVENTIONS.md §1` makes frontmatter what "lets tools, agents, and humans sort
and route files". `render_doc` re-dumps the whole block (F4, F5), and that
parser misreads four of its changes:

- A flow list comes back as a block list: `tags: [template, scaffold, project_keel]`
  becomes `tags:` followed by unindented `- template` lines. A line like
  `- template` has no colon, so Keel ignores it, and `tags` reads as empty.
- Non-ASCII text is escaped inside a double-quoted scalar (F5), which Keel reads
  literally: the quotes and the six-character `\u2014` escape stay in the
  value where the author wrote `—`.
- A long scalar folds at 80 columns, and Keel keeps only the first line.
- A quoted scalar is re-quoted. A double-quoted value can come back
  single-quoted, with any apostrophe doubled (`Docker''s`), or unquoted, and
  Keel keeps whichever quotes it finds.

Reproduced on the scratch copy: `README.md`, `agents/README.md` and
`agents/practice_refactor/README.md` were registered, only `cdx lint --fix` (the
first adoption step) was run, and the corpus was rebuilt with Keel's
`build_corpus.py`. In its output, 3 of the 660 nodes changed, the three
documents:

- `readme` loses the authored tags `template`, `scaffold` and `project_keel`.
- `agents-practice-refactor-readme` has its summary cut to "Walks the corpus KG
  and refactors each chunk toward a named practice, gating", and loses the tags
  `agent`, `practices` and `gate`.
- `agents-readme` has its summary replaced by
  `"Autonomous / LLM agents (the 'brains') \u2014 reasoning, policy, prompts."`,
  with the quotes and the literal `\u2014` escape where the original read an
  em dash, and gains a bogus tag `u2014`.

The corpus agents query, `wiki/corpus.json`, is the linked form:
`make site-data` runs `link_corpus.py` after `build_corpus.py`, and
`check_corpus.py` validates that form. There the changed tags and summaries also
move keyword edges: 13 of the 660 nodes change, and the link graph drops from
4,164 edges to 4,154.

No Keel gate notices the damage to these three. `check_structure.py` exits 0.
`check_corpus.py` exits 0 with "fresh build valid + deterministic" only on a
tree with no local `wiki/corpus.json`, such as a fresh clone or CI. With one
present, as on any checkout where `make site-data` has run, it exits 1 with
"wiki/corpus.json is stale vs the tree". It does that after any edit that
changes the corpus, so it does not point at the damage. (The freshness hook fails
on any write, damaged or not; see F10.) `README.md` has a parity twin, but the
twin templates its `tags:` line (`tags: [template, scaffold, {{ project_slug }}]`).
That is the only twin line the re-render removes, and the twin check skips
templated lines, so the stamp alone leaves the twin check green. The `updated:`
bump the same commit needs does not (F10). `cdx monitor --apply` re-renders
through the same `render_doc`; run alone on `README.md`, it leaves the same
block-list `tags:`.

A document whose parity twin does not template the changed lines turns Keel's
gate red. `config/project.json:6-15` declares three Markdown parity twins:
`README.md`, `docs/guides/README.md` and `scripts/jobs/README.md`.
`check_structure.py`'s `check_N` (`:2143`) fails when a non-templated line of the
`.jinja` twin is missing from the plain file (`_twin_parity_findings`,
`:2122-2131`). It compares text lines and parses no YAML, so a YAML-parsing
reader does not change its result. Registering only `scripts/jobs/README.md` and
running `cdx lint --fix` makes `check_structure.py` exit 1 with two errors: the
twin's `tags: [jobs, scheduled, automation, triggers]` line and its em-dash
`summary:` line are "in the twin but not in scripts/jobs/README.md". The
structure hook is `always_run` in pre-commit (`.pre-commit-config.yaml:7-12`), so
the adoption commit is refused. Stamping all 119 parseable documents gives the
same two errors and no others: `README.md`'s changed line is templated, and
`docs/guides/README.md`'s lines survive the re-render. On a tree with no local
`wiki/corpus.json`, `check_corpus.py` still exits 0, although the corpus changes.
In `build_corpus.py`'s output, the title, summary or tags of 89 documents change.
In the linked corpus that `check_corpus.py` validates, 307 of the 660 nodes
change, and the link graph drops from 4,164 edges to 4,111. With a local
`wiki/corpus.json`, `check_corpus.py` reports that file stale, as it would for
any edit, and does not point at the damage.

The twin check also refuses the F10 fix, whatever the render. Each of the three
parity twins carries its own `updated:` line, untemplated
(`README.md.jinja:11`, `docs/guides/README.md.jinja:10` and
`scripts/jobs/README.md.jinja:12`). Bumping `updated:` on the plain document, as
F10 requires in the same change, leaves the twin's old line missing from it.
`check_structure.py` then exits 1, with one error for each twinned document
whose twin is not bumped too. F10 has the measurements.

Measured over the 119 distinct Keel documents whose frontmatter parses as YAML
(F8). Each was stamped as `lint --fix` does, then read with Keel's
`_parse_frontmatter`; the table counts documents where any top-level key other
than `cdm` reads differently. Running the real `cdx lint --fix` over all 119 gives
the same 92.

| Render | Documents Keel reads differently |
| --- | --- |
| `render_doc` as shipped | 92 of 119 |
| key order preserved | 92 of 119 |
| key order preserved + `allow_unicode=True` (F5) | 49 of 119 |
| key order preserved + F5 + unlimited line width | 45 of 119 |
| only the `cdm:` block spliced into the original text | 0 of 119 |

As shipped, all 45 documents with authored tags lose every tag, 50 titles and 20
summaries become double-quoted `\u` escapes, 10 summaries are cut at the fold,
and 15 more values are re-quoted or refolded.

`allow_unicode` and an unlimited width remove the escapes and the folds, but not
the tag loss or the re-quoting. 45 documents are still read differently: all 45
lose their tags, and 8 of them, ADR-0002 to ADR-0009, also have a title or
summary re-quoted. All 8 titles and one summary come back single-quoted, with
any apostrophe doubled. Keel reads ADR-0005's title as
`'ADR-0005: … Docker''s contract, …'` where it read
`"ADR-0005: … Docker's contract, …"`.
Three summaries come back unquoted. So neither setting is a fix on its own; only
the `cdm:` splice or YAML-parsing readers fix both misreads.

Custodex alone can fix the misreads and the twin errors the re-render causes;
Keel would need two changes. Neither side's fix covers the twin error that the
F10 bump causes: a twinned document's adoption commit also needs its `.jinja`
twin's `updated:` bumped, or that line templated (F10).

- **Custodex side** — `render_doc` splices only the `cdm:` block into the
  original frontmatter text and leaves every other line byte-identical. This also
  settles F4 and F5 for any document with foreign frontmatter. With only a sorted
  `cdm:` block spliced into all 119, `check_structure.py` exits 0 and the rebuilt
  corpus, linked and unlinked, is identical to the pristine one. That tree still
  fails the freshness hook with 117 `STALE` lines, one per spliced document that
  carries `updated:`.
- **Keel side** — every frontmatter reader (`build_corpus.py`,
  `check_structure.py` and the rest) parses YAML. `check_structure.py` is
  stdlib-only and 3.6-safe by design, so this needs a YAML dependency there or a
  parser that handles block lists, quoting and folding. That fixes the reads but
  not the twin check. Each parity twin whose frontmatter lines the re-render
  changes (today `scripts/jobs/README.md.jinja`) must also be brought into the
  re-rendered form or have those lines templated. Copying the stamped frontmatter,
  without `cdm:`, into that twin made `check_structure.py` exit 0 again. The twin
  then carries Custodex's dump format, with a block list and an escaped em dash,
  and so does every project generated from it.

Until a fix lands, registering a Keel document risks this damage: only 27 of the
119 read identically after a stamp.

## F10 — every Custodex write fails Keel's doc-freshness gate

Keel gates freshness. `updated:` must never be earlier than the file's last
commit, and a file modified in the working tree must carry today's date
(`CONVENTIONS.md:61`). The rule is `review_docs.py:81-121` (`stale_findings`). It
runs in pre-commit as the always-run `doc-review` hook (`review_docs.py --strict`,
`.pre-commit-config.yaml:37-42`), in `make check-docs`, and as
`tests/integration/test_doc_freshness.py`.

Custodex never restamps `updated:`, and §9 grants it only the `cdm:` block. On the
scratch copy, `review_docs.py --strict` exits 0 when pristine and exits 1 after
either write:

- after `cdx lint --fix` on the three F9 documents, with one `STALE` line per
  document ("modified in the working tree but stamped … -- set `updated:` … in
  the same change");
- after `cdx monitor --apply` alone on `README.md`, with the same line for
  `README.md`.

The committed half of the rule was checked by calling `stale_findings` directly,
not end to end, because it needs a commit. A document committed after its
`updated:` date is flagged "a change landed without restamping `updated:`".

So the adoption commit, and every later heal, needs `updated:` bumped by hand in
the same change.

On the three documents with a parity `.jinja` twin (F9), that bump collides with
`check_structure.py`'s twin check. Each twin carries its own `updated:` line,
untemplated: `README.md.jinja:11`, `docs/guides/README.md.jinja:10` and
`scripts/jobs/README.md.jinja:12`. `review_docs.py` governs only tracked `*.md`
files, so it never asks for a twin to be bumped, but `check_N` fails once the
twin's old `updated:` line is missing from the plain file. Both hooks were run on
the scratch copy under the host's `python3`, as pre-commit runs them:

| Tree | `check_structure.py` | `review_docs.py --strict` |
| --- | --- | --- |
| `cdx lint --fix` on `README.md` alone | exit 0 | exit 1, 1 `STALE` |
| + `updated:` bumped on `README.md` | exit 1, 1 error: `README.md.jinja`'s `updated:` | exit 0 |
| + `updated:` bumped on `README.md.jinja` | exit 0 | exit 0 |
| `cdm:` block spliced into all 119 (FM-SPLICE's shape) | exit 0 | exit 1, 117 `STALE` |
| + `updated:` bumped on the 117 that carry it | exit 1, 3 errors: each twin's `updated:` | exit 0 |
| + `updated:` bumped on the three twins | exit 0 | exit 0 |

So a twinned document's adoption commit passes both always-run hooks only if it
also bumps that document's `.jinja` twin, whichever render wrote it. Keel's own
pytest does not catch the collision: all 727 of its tests pass on the tree with
the three twin errors. `check_structure.py` is the gate that refuses the commit,
in pre-commit and in CI's `make check-all`.

Unattended heals — `cdx monitor --apply` in CI, the docs-PR loop — cannot pass
Keel's gates until Keel exempts `cdm:`-only changes from the freshness rule.
That option keeps `check_structure.py` green as well: once item 4 has landed, a
heal changes only `cdm:` lines, which leaves every twin line in place (the
splice row above). Granting the tool `updated:`, which §9 does not, is not
enough on its own. A tool restamp of `updated:` breaks the twin check exactly as
a hand bump does, so it also needs the twins' `updated:` lines templated, or the
tool editing the twins.

## What a fix pass would do

Keel side — items 1 and 3 unblock the gate; item 2 unblocks the adapter path
(item 13 is the Custodex-side alternative):

1. Rewrite `cdmon.example.yaml` against the current schema (F1) —
   `version: "1.0.0"`, `root: "../.."` (resolved relative to the config file),
   real `code_refs` and `region_keys`, no `output:`.
2. Point `cdmon_sync.py` at `cdx` (falling back to `cdmon`) and map `heal` →
   `monitor --apply` (F2), unless Custodex ships item 13. The script must still
   parse under Python 3.6, because pre-commit runs it with the bare `python3`.
3. Map `--check` to `check`, or run `check` and then `lint` (F3).

Either side — item 4 must land before any Keel document is registered:

4. Fix F9: the `cdm:`-block splice in `render_doc`, keeping the `cdm:` subtree
   sorted (Custodex); or YAML-parsing frontmatter readers plus each changed
   parity twin's frontmatter re-rendered or templated (Keel, today
   `scripts/jobs/README.md.jinja`). `allow_unicode` and a wider `width` are not
   enough on their own.

Keel side — before heals run unattended:

5. Exempt `cdm:`-only changes from the freshness rule (F10). This keeps both
   always-run hooks green for unattended heals. The alternative, granting the
   tool `updated:`, also needs the three parity twins' `updated:` lines
   templated, or the tool editing the twins; otherwise every heal of a twinned
   document fails the twin check. Until then, bump `updated:` by hand in every
   change Custodex writes, and on the `.jinja` twin of `README.md`,
   `docs/guides/README.md` or `scripts/jobs/README.md` whenever that document
   changes.

Adoption — after items 1, 3 and 4 (item 6 calls `cdx` directly, so it does not
wait for item 2 or 13):

6. Adopt once. `cdx lint --fix` stamps `cdm.schema_version` and `cdm.audience`,
   and `cdx monitor --apply` sets the baseline fingerprints. Then bump `updated:`
   on every document either command wrote, and on the `.jinja` twin of
   `README.md`, `docs/guides/README.md` or `scripts/jobs/README.md` if that
   document is registered (F10). On that exact tree, run
   `python3 scripts/check_structure.py` and
   `python3 scripts/jobs/review_docs.py --strict` before committing; both must
   exit 0. If `lint` stays in the hook, each registered document also needs a
   hand-written `>` purpose line after its title.
7. Before registering any of the seven F8 documents, quote its frontmatter values
   that contain `: `. Until then, a registered one stops `cdx lint --fix` partway.
8. Once `cdmon.yaml` is committed, consider making its absence a failure rather
   than a skip (F7), so deleting the config cannot silently turn the gate off.
9. Decide F4 deliberately and write the decision into `CONVENTIONS.md §9`. The
   Custodex-side fix in item 4 settles it.

Custodex side — items 10–12 block nothing; item 13 is the Custodex-side fix
for F2:

10. Add `allow_unicode=True` and a wider `width=` to `render_doc` (F5), for
    documents still rendered in full.
11. Render `style_guidance` in `build_prompt`, and pass it on the `write-doc` path
    (F6).
12. Make `cdx lint --fix` handle malformed front matter the way `cdx lint` does:
    report `MALFORMED_STRUCTURE` for that document and carry on, instead of
    aborting after writing the documents registered before it (F8; K7, K8).
13. Add a `heal` command that runs `monitor --apply` (F2). The adapter calls
    `cdmon heal --config …` (`cdmon_sync.py:49`), and `scripts/README.md:32` and
    `CONVENTIONS.md:312` document the verb, so the command makes Keel's
    documented path work with no Keel edit. It is the alternative to item 2's
    `heal` mapping; one of the two is needed to deploy through the adapter.
