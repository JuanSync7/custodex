# OKF-01 — the OKF v0.2 bundle projection (`okf.py` + `cdx okf`)

**Epic:** OKF (portable knowledge-bundle projections)
**Depends on:** — (consumes existing config/manifest/reviewlog surfaces only)
**Constraints:** K0, K1, K2, K5, K6, K7, K8, K9, K10

## Goal (validable)

Project the managed doc set into a Google OKF v0.2 bundle under `.cdmon/okf/`
— a PROJECTION of existing truths (config + doc bytes + the review and
resolutions logs + the pure drift report), never a storage format: deleting
the bundle changes nothing; regenerating it is byte-idempotent because the
bundle is deliberately clock-free (v0.2 makes `generated.at` optional — we
omit it, K10).

**Done when:**
- `custodex/okf.py` matches the pinned `ARCHITECTURE §EPIC CIX → OKF-01`
  signatures. Per managed doc: OKF front matter — `type` (doc-style
  document-type → display name; audience fallback), `title` (first H1 else
  doc id), `description` (first purpose-blockquote line, omitted when
  absent), `resource` (repo-relative doc path), `tags` `[audience]`,
  `generated: {by}` (NO `at`), `sources[]` one `{resource}` per code_ref,
  `verified[]` `{by: "human:<id>", at: <resolved_at>}` per BOUND
  verification (see "The `verified` binding" below; spec MUST: human:
  prefix) — plus the `custodex:` extension block (`doc_id`, `audience`,
  `fingerprint`) for round-trip traceability. ⟨R, revised⟩ The planned
  `unit` tag and `custodex.unit` key were dropped at build time (the
  deviation is recorded in the STATUS OKF-01 row); the code emits neither.
- Body = doc body with the `cdm:` front matter stripped, bytes otherwise
  verbatim; bundle mirrors `spec.path` so relative doc↔doc links survive.
- Bundle-root `index.md`: front matter `okf_version: "0.2"` ONLY; body =
  sorted `* [Title](path) - description` bullets. No concept file is ever
  named `index.md`/`log.md` (reserved-name rule). ⟨R, revised by dogfood⟩ A
  managed doc NAMED `index.md` (custodex's own `api-index` landing page) is
  NOT an error: it maps body-verbatim onto the per-directory INDEX FILE the
  spec reserves that name for (frontmatter-less, excluded from the root
  index's concept list). Only `log.md` — and a bundle-ROOT `index.md`,
  which would overwrite the generated root index — stays a loud
  ConfigError; the original all-loud guard made `cdx okf` unusable on
  custodex itself. ⟨R, review r5⟩ Two doc ids on ONE bundle path (compared
  once normalised) are a loud ConfigError naming both ids and the path:
  the bundle has one file per path, so the later concept silently replaced
  the earlier one — and with it a current REJECT on the earlier id.
- `cdx okf` follows the `cdx wiki` precedent: default WRITES (per-file
  compare-skip, K7, `wrote/unchanged` accounting), `--check` exits 1 listing
  stale/missing bundle files, `--out` overrides the default dir. Missing
  source doc → listed in `skipped`, never a crash (K8 loudness reserved for
  malformed config/doc parse errors).
- Governance: waiver for `custodex/okf.py`; `feature-doc/catalog/okf.yaml`
  (FEAT-OKF-001, modules `[okf, cli]`); DEMO-116; tagged tests; wiki regen;
  cli-doc reheal.
- Full gate green (as CIX-01).

## Design

YAML front matter is emitted with `yaml.safe_dump` (core dep, K0) with a
FIXED field order (type, title, description, resource, tags, generated,
verified, sources, custodex) — deterministic bytes (K10). No pruning of
foreign files in `--out` targets (documented limit; the default dir is ours
but `--out` may not be).

### The `verified` binding (pre-merge review fixes: idea 11 / critic 2.5, then review rounds 1-5)

The first cut turned EVERY resolution — a REJECTED one included — into a
`human:<by>` event, ignored the resolutions log's last-write-wins rule, never
compared hashes (a stale accept survived a code change + machine reheal), and
invented `human:unrecorded` for a resolution with no `resolved_by`. Review
round 1 then showed that a matching surface hash alone still over-claims: a
REGION or SUSPECT_LINK record's surface hash equals the stored fingerprint
BEFORE its fix lands (accepting an unapplied proposal published `verified`
over content `cdx check` rejects); an accept of an unapplied HASH proposal
bound to a LATER machine heal the human never saw; an old accept revived
after S1 → S2 → S1; and an OVERRIDDEN resolution attested the machine text
the human overrode (custodex never writes `resolved_text` to the doc).
Review round 2 showed the gates still ran PER RECORD: alice's ACCEPT of a
`cdx monitor` run's HASH record kept `verified: human:alice` while bob
REJECTED the same run's REGION record (the content on disk), in either
order, with `okf --check` "in sync"; and `cdx okf` ran whole-config drift
detection whenever the resolutions log had ANY entry, so a log holding only
a REJECT made one unreadable code ref fail the export. Review rounds 3 and 4
found no logic defect: they pinned mutation gaps (the tiebreak, a
contiguous and byte-for-byte override, supersession by any drift kind AND
any verdict, per-doc supersession, sorted ids) and widened the honest scope
— any record-less content change keeps the claim (not only a prose edit),
and an MCP run's simultaneous drifts on a doc share ONE record id, so they
are one review (the record grain). Review round 5 found one silent
overwrite — two doc ids on one path published the later id's verdict over
the earlier id's REJECT (now a loud ConfigError) — pinned the newest record
by instant, an INVALIDATED later record that still supersedes and the
override's exact bytes (interior whitespace, mid-line text, body only),
made the recorded-instants pin independent of the presumption, and added
the local-logs-only limit.

The join lives in `okf.py` beside the fingerprint and body it binds to
(`render_bundle(..., records=, resolutions=, drift_report=)`), and a doc has
ONE verdict.

**Current reviews.** A doc's current reviews are the LAST-WRITE resolutions
(`reviewlog.resolved_index`, APPEND order — a later line corrects an earlier
one whatever its stamp) of its review records that were graded against the
doc's CURRENT stored fingerprint and recorded at or after the doc's NEWEST
review record (parsed instants; a naive stamp is UTC). A review recorded
before a newer record of ANY drift kind or verdict — the record of a
machine heal, of a dry-run preview, of a code move and its revert, of an
upstream edit's escalation — is superseded until a record bound to the
current surface is (re)resolved at or after the newest one; a newer record
at a surface that no longer exists can never lift that. Supersession is per
doc: another doc's records never touch it. Only a RECORD supersedes: a
write that leaves none is not seen (see "Code surface, not content" below).

**Verdict.** The doc carries `verified` only when
1. the drift report shows NO outstanding drift on it (positive evidence;
   `drift_report=None` verifies nothing), and
2. no current review DISPUTES it — an outcome in `DISPUTING_RESOLUTIONS`
   = {REJECTED}, named or anonymous, or an OVERRIDDEN whose `resolved_text`
   (surrounding whitespace stripped) is not in the body byte-for-byte as ONE
   contiguous block (a change request still pending; a match only after
   case-folding or collapsing whitespace does not count).

A sibling REJECT withholds an ACCEPT in either order when the two are
distinct records, as `cdx monitor` writes them; records that share one id
are one review (see "Record grain" below).

It then carries one `{by: "human:<id>", at: <resolved_at>}` per current
review that ATTESTS it — an outcome in `VERIFYING_RESOLUTIONS` = {ACCEPTED,
OVERRIDDEN}, an override only once its text landed — with a recorded
`resolved_by` (whitespace collapsed; none → no event, never
`human:unrecorded`). INVALIDATED ("a non-event") judges the drift, not the
content: it neither attests nor disputes (and still counts as a REVIEW for an
SLA bump — a split by design). Identical `(by, at)` events collapse; events
are ordered by parsed instant, then resolver, then the verbatim stamp (K10).

**Detect only when at stake.** `pending_verifications(config, root,
records=, resolutions=)` (pure) returns the doc ids that WOULD carry
`verified` if drift-free — every gate but the drift gate; it agrees with
`render_bundle` under a clean report. `cdx okf` runs the pure `drift.detect`
(K1, from the CONFIG dir, as `cdx check` does) only when it is non-empty, so
a rejected-only, orphan, unnamed, vetoed or superseded log never extracts
code, while a real claim with an unreadable code ref is loud (K8).

**K8 scope.** The review log's instants are read only when a resolution
joins one of its records; then every record's `detected_at` is parsed (any
may supersede) and a corrupt one is a loud `SchemaError` naming the field.
`drift_report=None`, or no joining resolution, reads none.

⟨R⟩ Honest scope (each limit but the structural "Local logs only" is pinned
by a named test in ship shape, so no docstring over-claims; each pin flips
deliberately when its follow-up lands, and a standing limit's pin flips only
if its decision is revisited):
- **Presumption.** A record carries no run id and no applied flag, so the
  engine cannot tell WHICH same-surface record a human looked at: a review
  recorded at or after the doc's newest record is presumed to be of the doc
  as it stands. Accepting an OLD dry-run proposal after the machine heal
  verifies the heal's write — byte-identical with the mock backend, not
  necessarily with an LLM
  (`test_a_resolution_after_the_newest_record_is_presumed_to_review_the_doc`).
  Closing it needs a run id and an applied marker on the record (additive
  K6 — the OKF-02 follow-up; a doc digest alone would not close it: it
  proves the doc is unchanged since the resolve, not which write the human
  reviewed).
- **Code surface, not content.** The stored fingerprint is a code-surface
  hash (K2) and only a review record supersedes, so ANY content change that
  moves no code surface and writes no ReviewRecord keeps the claim — a human
  prose edit (`test_verified_binds_the_code_surface_not_the_prose`), and
  equally a record-less MACHINE rewrite: custodex's own `cdx new-doc
  --force` replaces the whole reviewed body with a TODO scaffold at the same
  surface while `cdx check` stays clean
  (`test_a_record_less_whole_doc_rewrite_keeps_the_claim`), and the server
  editor's `generate.apply_record_fix` / `generate.apply_edits_to_disk`
  write docs without a record too. Binding to the content needs a doc
  digest captured at resolve time — the additive K6 follow-up (OKF-03).
- **Recorded instants, not wall time.** Supersession compares the instants
  the writers stamped. `cdx monitor` stamps each record just BEFORE it
  applies that record's fix; MCP `remediate_drift` and `sync_docs` stamp
  EVERY record with the call-start instant, so the window is the WHOLE call
  (possibly minutes with an LLM backend): a resolution recorded while a run
  is in flight — even of that call's OWN record, with no older proposal
  involved — still predates the writes it then vouches for
  (`test_a_resolution_made_during_an_mcp_heal_vouches_for_its_write`: alice
  accepts the call's record while the backend authors the `llm` region,
  then the call writes it). A run id alone does not close it; OKF-02's
  applied receipt, or OKF-03's resolve-time digest, does.
- **Record grain.** A resolution names a record id, and the id hashes the
  doc, its surface and the record's stamp. `cdx monitor` stamps each record,
  so a run's HASH and REGION records on a doc are two reviews. MCP
  `remediate_drift`/`sync_docs` stamp every record with the call-start
  instant, so a doc's simultaneous drifts share ONE id — the grain MCP
  documents ("resolving it covers all of that doc's simultaneous drifts") —
  and are ONE review under last-write-wins: bob's REJECT of the REGION facet
  then alice's ACCEPT of the HASH facet is a correction and verifies, while
  the reverse order does not
  (`test_an_mcp_runs_simultaneous_drifts_on_a_doc_are_one_review`). A
  STANDING limit, per the program decision "MCP grain (A): fix the docs":
  MCP keeps its documented doc grain (the known limitation in
  `.project/problems/MCP-02-record-id-grain.md`), and a `ResolutionRecord`
  names no facet, so okf cannot split one id's facets on its own.
- **Containment, not replacement.** An override's text must be in the doc,
  not the machine text gone
  (`test_an_override_verifies_only_once_the_humans_text_is_in_the_doc`
  appends it beside the machine text).
- **Writer channel.** Who WROTE a resolution (a person at `cdx resolve`, or
  an MCP agent passing `resolved_by` to `resolve_drift`) is not recorded, so
  a `resolved_by` supplied by a non-human writer still reads as `human:`
  (`test_an_agent_supplied_resolver_still_reads_as_human`); the `channel`
  field on `ResolutionRecord` is follow-up OKF-CHANNEL (schema + MCP +
  server).
- **Local logs only.** The join reads the logs it is given — for `cdx okf`,
  the local `.cdmon/review-log.jsonl` and `.cdmon/resolutions.jsonl`. A
  resolution recorded through the central hub (the console's `POST
  /repos/{id}/resolutions`, or `POST /repos/{id}/records/{record_id}/apply-fix`)
  lives only in the server's store and never reaches the local log, so it
  neither attests nor vetoes: a REJECT made in the console does not
  withhold a CLI accept. Structural (the local-log paths are the only
  inputs `cdx okf` reads), so it has no ship-shape pin.

## Non-goals

- OKF v0.1 back-compat output; `log.md` emission; `stale_after` (needs a
  date policy — a later staleness-SLA join); Attested Computation types;
  importing/consuming foreign OKF bundles.

## Test plan (TDD)

- **unit** `tests/unit/test_okf.py`: front-matter golden bytes for a
  representative doc (type mapping incl. doc-style present/absent, blockquote
  present/absent); cdm strip + body-verbatim; index.md golden; reserved-name
  guards (a doc NAMED index.md → frontmatter-less directory index; a
  bundle-ROOT index.md, a log.md, a `../` path or two doc ids on one bundle
  path — also once normalised, also with the file missing, in the render,
  export, check and `pending_verifications` alike, writing nothing → loud
  ConfigError naming both ids and the path); export
  idempotency (second run all-`unchanged`); skipped accounting. The
  `verified` join: the outcome sets (verifying {accepted, overridden},
  disputing {rejected}, INVALIDATED in neither); last-write-wins in APPEND
  order (retracted accept → none, corrected reject → one, a later ANONYMOUS
  line still retracts, an earlier-stamped REJECT appended later still wins);
  unknown resolver (None/""/blank) → no event, never `unrecorded`; resolver
  whitespace collapsed; an override verifies only when ALL its text is on
  disk (absent/None/""/blank/partial multi-line → none; ACCEPT ignores any
  text; the text must be on disk as ONE contiguous block — its lines
  scattered through the doc do not count — and byte-for-byte: a match only
  after case-folding, a doubled space or a dropped blank line does not
  count, nor do trailing spaces on an interior line, while surrounding
  whitespace at either end is not content; a contiguous substring counts
  even mid-line; the text must be in the BODY, not the stripped `cdm:`
  front matter);
  surface_hash must equal the stored
  fingerprint (no fingerprint →
  none); no drift report, or a REGION/SUSPECT_LINK/HASH/UNHEALABLE drift on
  the doc → none, while drift on ANOTHER doc does not block; ONE verdict per
  doc — a current REJECT (named or anonymous) or unlanded override on a
  sibling record withholds every claim, in either order, while a REJECT of
  an older surface, a superseded REJECT, an INVALIDATED sibling, a corrected
  REJECT, a landed override and an unnamed accept do not; a later record
  for the SAME doc supersedes (any surface; instants, not strings; the
  newest by instant wherever it sits in the log, and chosen by instant when
  the stamps' string order differs; equal instant keeps;
  a later SUSPECT_LINK or REGION record supersedes a HASH accept exactly as
  a HASH record does, and a later ESCALATE or INVALIDATE record exactly as a
  FIX record does, in the render and in `pending_verifications`; a later
  record resolved INVALIDATED still supersedes — its review is neutral and
  the older accept never revives; another
  doc's record never supersedes, in either); a review at or after the
  newest record,
  of ANY record at the current surface, lifts supersession (re-accepting the
  old record after a revert verifies) while accepting a newer record at a
  vanished surface never does; malformed stamps → SchemaError naming the
  field, anywhere in the log, only when a resolution joins a record (none
  read with `drift_report=None`); naive vs aware compare as UTC under a
  non-UTC local zone; orphan/foreign-doc resolutions ignored; events ordered
  by parsed instant (offset forms), then resolver, then verbatim stamp (eight
  forms of one instant; two resolvers at one instant in `Z`/`+00:00` forms
  order by resolver), input-order-free; identical events collapse
  (accept + override too); prose-only edit keeps the claim while a
  fingerprint move drops it; export with verifications is idempotent and a
  retraction stales exactly that concept; `pending_verifications` agrees
  with a clean-report render in every case (bound, none, rejected, orphan,
  unnamed, older surface, superseded, vetoed, no fingerprint, index-named
  landing doc, a reviewed doc whose file is missing), ignores drift and log
  order, and returns SORTED ids (eight verifiable docs; ids sorted by id,
  not by bundle path; codepoint order, so `Beta` before `alpha`).
- **system** `tests/system/test_okf_cli.py` (CliRunner): default write into
  tmp config's `.cdmon/okf`; re-run unchanged; `--check` clean then stale
  after a doc edit; `--out` honored; `--json` shape. Real `monitor` →
  `resolve` → `okf` flows: a rejection never verifies; accept verifies and a
  later reject retracts it (`--check` STALE); no `--by` → no event; a code
  change + reheal drops the stale claim and a re-export is a no-op (K7);
  accepting an unapplied REGION proposal → none while `cdx check` fails; an
  accepted SUSPECT_LINK escalation → none until `resolve --edge` clears it,
  then verified; an accept before a later machine heal → none until the
  heal's own record is accepted; S1 → S2 → S1 revert → none; an override →
  none until its text is in the doc; `okf --check` in sync right after
  exporting a verification (and a re-export writes 0); a sibling REGION
  record REJECTED → none in either order (`--check` STALE); an OLD dry-run
  proposal accepted after the heal verifies (the presumption, pinned); a
  dry-run preview supersedes after a revert, resolving the preview cannot
  restore, re-accepting a current record does; drift is detected only when a
  verification is at stake (no review log, a review log without
  resolutions, rejected-only, an unnamed accept, a vetoed accept → an
  unreadable code ref breaks nothing; a real claim → loud); detection runs
  from the config dir (`root: ".."`); a MISSING_DOC on the id (unnormalized
  path, duplicate id) blocks the claim; a corrupt review-log stamp is loud
  only once a resolution joins it; a record-less `cdx new-doc --force`
  rewrite at the same surface keeps the claim (the code-surface limit,
  pinned); an upstream edit's SUSPECT_LINK escalation supersedes an earlier
  accept even once `resolve --edge` clears the link (no record, `cdx check`
  clean) until the escalation itself is resolved; a heal of ANOTHER doc
  never withdraws this doc's claim; two doc ids on one path make `cdx okf`
  and `cdx okf --check` fail loudly naming both ids and the path, with no
  bundle written. MCP-shaped (the tools called
  in-process with an injected `now`, offline — K4): one call's HASH and
  REGION records share ONE id, so reject-then-accept verifies and
  accept-then-reject does not (the record grain, pinned); a resolution of
  an MCP heal call's OWN record, made while the backend authors the `llm`
  region, vouches for the write made after it (the recorded-instants limit,
  pinned independently of the presumption); an agent-supplied `resolved_by` is
  emitted as `human:` (the writer-channel limit, pinned).

## Reheal order (DoD)

`(waiver) → cdx monitor --apply → cdx check → cdx wiki → cdx trace →
ruff/mypy/pytest`.
