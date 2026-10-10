# S1-CITPL — the docs-MR CI job opens one docs MR per (target, config) and reports what it did

**Epic:** Step-1 correctness (1A), the CITPL family
**Written by:** CI-SPEC (W1, no code). This file makes S1-CITPL self-contained.
**Constraints:** K0, K1, K4, K5, K6, K7, K8, K9, K10, K11
**Status:** SPEC. Each owner slice pins its own signatures in ARCHITECTURE.md
before its TDD loop (PLAN §0, per-slice loop step 1). §3a lists them, with
their owners.
**Verified against:** main at `ddc368d` (step-0 PR3). Every `file:line` anchor in
§1–§8 is covered by a mechanical check there (§9).
**Revision:** round 4 of CI-SPEC. Round 1 added §8 F28–F38 and the items they
create (T10f, T92–T94, M36a/M36b, M59–M62), and corrected F12. Round 2 adds
§8 F39–F47 and the items they create (T55[page2, full_last_page], T95,
M63–M65); it restates the CI-HARNESS model as a requirement on that slice
(it has not landed), names the ARCHITECTURE heading, fixes T31's owner, and
trims five cited ranges that ended on a blank line. Round 3 adds §8
F48–F52: premise G7 reads `CiJob.predefined`, T31's birth signature uses no
CI-OPEN type and T31 gets its own module, the fake forge's default page size
is per provider, the CI-TEMPLATES fallback file set is complete, and the
CI-HARNESS model is stated as a condition rather than a dated observation.
Round 4 adds §8 F53–F56: the echo lift leaves the advisory computation in
`monitor`, HC-013 splits between CI-TEMPLATES and CI-GUARD, every template
knob is bound to its §10 default, and the checkers' location and command are
recorded where this file says they are.

## 0. Sources, and which one wins

- **Design narrative:** the S1-CITPL spec, revision 3 (1096 lines, D0–D11,
  T1–T91, M1–M58, sha256 prefix `1913ab9e9751f269` for its body). It lives in
  the step-1 scratchpad (`$SP/step1-design/specs/S1-CITPL.md`, where `$SP` is
  the step-1 scratchpad outside the repo), which is not part of the repo
  record. So this file carries, in step-1 form, every part of it an owner
  slice needs:
  - the design, D0–D11 (§3);
  - the signatures (§3a);
  - the exact template shape (§3b);
  - idempotency per write path (§3c);
  - the schema and version impact, and the upgrade bullets (§3d);
  - the knobs (§10).
- **Revision-2 text:** rev 3 cites about 70 items as "as rev 2", and no rev-2
  file survived in scratch or in `.project/slices/`. The text was recovered from
  the design-review workflow `wf_1ab41d67-24f`: agent `revise:S1-CITPL:1`, its
  StructuredOutput `spec_markdown` (82 706 chars, sha256 prefix
  `d180642f585e8df5`, re-hashed by this pass). It is inlined below.
- **Step-1 cut:** the consolidated plan, revision 2: §1 C2, C15, C16 and C17;
  §6 PD-30, PD-31 and PD-32; §8; the CITPL-family entries.
- **Precedence.** Where this file and the rev-3 spec differ, this file wins. It
  applies the step-1 cut, and it is the only in-repo copy. Where this file and
  a PLAN slice entry differ on an owner, a test or a mutant, this file wins
  (the reasons are in §8), and the owner slice's STATUS row cites the §8 finding.

**Ids.** T1–T91 and M1–M58 keep the spec's numbers.
- A split item gets a letter suffix, for example T3a and T3b.
- A step-1 interim replacement for a deferred item gets an `i` suffix, for
  example T60i.
- An item this file adds takes the next free number: T92–T95 and M59–M65. The
  harness self-test T10f joins the T10 family. A new row of an existing test
  takes a bracketed name, for example T55[page2].
- Nothing is renumbered.

## 1. Goal (rev 3, with the step-1 cut applied)

When the shipped CI templates run their docs-PR job after a real code change,
exactly one open bot docs MR per (target branch, config) carries the healed doc
text. That MR:
- uses paths relative to the git toplevel;
- is cut from the healed commit;
- opens even though `cdx-gate` is red on that commit.

The job log reports the run exactly as `cdx monitor --apply` would. The job fails
only AFTER the MR, and only on drift the MR does not fix.

The server docs-PR route never lets a cloned repo choose any of these:
- the backend;
- the sink;
- the forge;
- the MR cosmetics;
- a write location outside the clone.

All of this is proven by executing the templates, and the GitLab pipeline graph,
offline against a stateful fake forge.

**Step 1 narrows "exactly one" to what K7/K11 require (PD-30).**
- A retry of the same commit never opens a second MR, whatever the backend
  wrote, when HEAD is known. HEAD is known in a git checkout whose tracked
  modifications are only managed docs, which is the CI path (D6).
- With HEAD unknown (a non-git run, or other tracked edits), the stamp carries
  no commit, so a retry matches only on `content_key`. That holds for a
  deterministic writer only; a writer that emits different bytes opens another
  MR (§3c item 2, §8 F34).
- A retry after a partial submit (the branch was created, the MR was not) fails
  loudly and names the leftover branch (§3c item 10, §8 F33).
- A later push opens another stamped MR. Supersede, STALE, BLOCKED, converge and
  retire are RTE-05's.

## 2. The step-1 cut (binding)

**In step 1**
- The job becomes `should-sync` → `open-docs-pr` → `check` in all three jobs:
  the GitLab adopter template, the GitHub adopter template and `.gitlab-ci.yml`
  `docs:heal` (D1).
- The GitLab `cdx-docs-pr` job gets `needs: []` (D10, R1).
- The jobs get git: a bootstrap line (D10, R3).
- The jobs are serialised: `resource_group` (GitLab) and `concurrency` (GitHub).
- The config's state directory is cached per ref (C16). That directory is
  `<config dir>/.cdmon/`, not the checkout root's `.cdmon/`: the review log,
  resolutions and code index are config_dir-relative (monitor.py:188, :196;
  §8 F29).
- Template literals become variables with defaults (PD-30, critique M6):
  - `CDX_GIT_BOOTSTRAP`;
  - `CDX_DOCS_PR_RESOURCE_GROUP`, default `cdx-docs-pr`. Whether GitLab expands
    a variable in `resource_group` is INFERRED (OD19). T72 pins only the
    template shape; if the first live run shows no expansion, the template
    falls back to the literal with a comment (§8 F23);
  - `CDX_STATE_CACHE_KEY`;
  - `CDX_STATE_DIR`, the cached state directory. Its default is the state
    directory of that template's own `CDMON_CONFIG` (F29). OD19's live check
    also covers variable expansion in GitLab `cache:paths`.
- The harness models the §3b shape: `CI_COMMIT_REF_SLUG`, the
  `actions/cache/restore`/`save` steps (record-only) and a step-level `if:`.
  They are a requirement on CI-HARNESS's re-run (§3b, §5, §8 F28, F40).
- `open-docs-pr` gains `--provider`, `--tiered/--no-tiered` and a `--source-sha`
  alias for `--ref`.
  - `--ref` now also stamps `source_sha` on the run's records. Today it reaches
    only the MR title and description (cli.py:803-807).
  - `--target` exists today with the literal default `"main"` (cli.py:798-802).
    X-FORGE-SITES makes it None-then-resolve.
  - It uses the D3 fail-fast order and reports through `_echo_run` on stderr.
  - It owns the summary line (C15, PD-31).
  - The URL printed is `web_url`, else `html_url`.
- `syncpr.SyncRun` is renamed **`DocsSyncRun`**, so it does not collide with
  `server.store.SyncRun` (store.py:229; C15).
- The stamp `DocsPrStamp{v, config, commit, content_key}`, with `bot_head`
  declared but always None (§8 F14); the key
  `branch_digest(target, config_id, commit)`; and `find_open`, which returns
  `iid`/`number`, never the global `id`.
- `decide_docs_pr` applies D7 **rule 1** (UP_TO_DATE) and **rule 4** (OPEN, read as
  "otherwise OPEN"; see §3 D7).
- The rest of the D3–D9 and D11 machinery:
  - `HTTPError`/`URLError` become `TransportError` in the pr.py leaves (D8);
  - GitHub labels, GitLab `create`, and cutting the branch from `base_sha` (D8);
  - toplevel paths and the `should-sync` prefix strip (D6);
  - the HEAD-baselined delta (D9);
  - the honest dry-run plan;
  - the "Needs a human before merge:" section (D11).
- `should-sync` prints a positive token, and every error exits 2 (D10).
- The server route (D0) uses a mock-only backend plus NullSink (PD-32, C17), and
  every config field is classified (CI-TRUST).
- The knobs land in three steps. Until the later ones land, the transports'
  `from_env` signature defaults (pr.py:123/:305) are the single source of the env
  NAMES:
  - `forge.provider`, `forge.default_branch` and `docs_pr.branch_prefix`:
    X-FORGE-CFG (W12);
  - the rest of `forge:`/`docs_pr:` and `FORGE_ENV_DEFAULTS`: HC-FORGE (W27);
  - `forge.commit_sha_env`: HC-PROVENANCE (W28).

**Deferred to RTE-05 (PLAN §8)**
- D7 rule 2 (STALE), rule 3 (BLOCKED unstamped), rule 5 (HUMAN_COMMITS), rule 6
  (NOT_A_DESCENDANT) and rule 7 (set-SUPERSEDE).
- `bot_head`.
- `close_superseded` and its notes, and `converge_docs_prs`.
- The D7.5 retire pass (`retire_candidates`, `retire_obsolete`).
- `is_ancestor`.
- Central record dedupe, beyond the state-directory cache.
- Adopting an MR-less bot branch that a partial submit left at the same key
  (§3c item 10).

The tests and mutants that exist only for these are marked **RTE-05** in §6 and
§7. They are kept verbatim so RTE-05 inherits them, and are not scheduled in
step 1.

## 3. Design digest (step-1 form)

This is the part of D0–D11 that owner slices cite. Rev-3 prose that the cut does
not change is summarised, not repeated.

**D0 (CI-TRUST).** The cloned repo says WHAT to heal, never HOW or WHERE. The
docs-PR route is `POST /repos/{id}/docs-pr` (app.py:1807). Before its Monitor is
built:
- `confine_clone(tree, cfg, config_dir) -> str` checks these, following symlinks,
  and each must resolve inside `tree.resolve()`:
  - the resolved root;
  - every `documents[*].path`;
  - every `code_refs[*].path`;
  - every `context_refs[*].path`.
- An escaping path is a SyncError, which becomes a 400, with no heal and no
  transport call.
- `confine_clone` returns the root's POSIX prefix (`""` or `"sub/"`) as
  `repo_prefix`.
- `server_heal_config` copies only the classified heal inputs. It takes backend,
  agent, central, `apply_tiered`/`apply_default`, `forge` and `docs_pr` from the
  server.
- The Monitor gets `backend=make_backend(server.git.docs_pr_backend, …)` and
  `sink=NullSink()` explicitly. Today it is built from the clone (app.py:1869-1871).

**D1 (CI-TEMPLATES).**
- `open-docs-pr` is the only writer. It heals with
  `tiered=cfg.apply_tiered` (cli.py:831 today).
- `check` then grades the healed workspace and honours `docdeps.gate`
  (cli.py:564-568).

**D2 (CI-OPEN, with OPS-CLOSE for T31).**
- `sync_pr_run(monitor, *, dry_run, tiered) -> DocsSyncRun(sync, result,
  advisory)`.
  - The advisory is computed by `transitive_advisory(cfg, root)` BEFORE any
    dry-run restore (R10).
  - `sync_pr` becomes `sync_pr_run(...).sync`, with an unchanged signature.
- `_echo_run` is the monitor echo block lifted verbatim (§8 F49):
  - OPS-CLOSE (W17) births it as `_echo_run(result, links, error, *, tiered)`.
    `monitor` computes the advisory links, or the `advisory unavailable`
    error, as it does today and passes them in;
  - CI-OPEN (W18) replaces `(links, error)` with a precomputed
    `advisory: Advisory` and adds `to_stderr=False`.

  In both forms the lift is the
  echo lines only: cli.py:639-676 and cli.py:684-696, verbatim, plus the
  `advisory unavailable` echo (cli.py:683), which `_echo_run` prints from the
  passed `error` at the same point, so stderr keeps its order. The advisory
  computation, cli.py:677-682 (the `docdeps.transitive` guard,
  `resolve_repo_root`, `propagate_suspect` and the `except`), stays in
  `monitor` (§8 F53). The lift stops before two lines that stay in
  `monitor` after the call:
  - the `raise typer.Exit(code=1)` on remaining drift (cli.py:697);
  - `clean — no drift remaining` (cli.py:698).

  A lift of the whole block to cli.py:697 would make `open-docs-pr` exit 1 before
  steps 8-10, so the MR would never open when drift remains (§8 F32, M62).
- `monitor`'s per-stream bytes are unchanged (golden T31).
- `sync-pr` and `open-docs-pr` echo to stderr.
- The result lines, whose text CI-OPEN owns (C15):
  - `clean — nothing to open`, only when nothing drifted AND nothing differs
    from HEAD;
  - otherwise, when nothing is proposed but drift remains:
    `nothing to open — N drift(s) remain that this run did not heal (held,
    escalated or suspect); \`cdx check\` lists them`, exit 0.
  - SYNC-HONEST aligns E4 §8, MCP `clean` and the server summary to this text.

**D3 (CI-OPEN): the step-1 order.** `root` is `monitor.root`, not
`config_dir / cfg.root` (cli.py:822).
1. Load the config. A UnicodeDecodeError is a ConfigError (X-K8LOAD).
2. Validate the provider and the target. Both are pure and apply under
   `--dry-run`.
   - The provider is `--provider`, else `forge.provider`. It is parsed by the
     same case-insensitive parse X-FORGE-CFG gives `ForgeConfig.provider`. There
     is one copy, not a second one in cli.py.
   - The target is `--target`, else the X-FORGE-SITES resolver. It is checked by
     `config.validate_branch_name` (X-FORGE-CFG; rev 3 called this
     `forge.validate_branch`).
3. `git_facts(root, config_path=…, doc_paths=…)` (X-GITFACTS). It is loud when
   git is expected.
4. `Monitor(cfg, config_dir).check()`, detect-only.
5. **No drift:**
   - before CI-DELTA, print `clean — nothing to open`;
   - from CI-DELTA on, print it only when the HEAD delta is also empty;
   - exit 0, with **no forge contact** (the retire pass and its
     `open docs MRs not checked` note are RTE-05's).
6. **Non-dry only, before the heal:**
   - build the transport (`from_env` until HC-FORGE's `resolve_forge` replaces
     it);
   - `listing = find_open(target, docs_pr.branch_prefix)`, the first network call
     and an authenticated READ.
   - So a bad token, URL, project or scope exits 1 with 0 review-log lines,
     0 envelopes and byte-identical docs.
7. Heal: `run = sync_pr_run(Monitor(cfg, config_dir, source_sha=…,
   doc_style=_doc_style_for(config_dir), sink=NullSink() if dry_run else None),
   dry_run=…, tiered=tiered)`, then `_echo_run(..., to_stderr=True)`.
   - `tiered` is the `--tiered/--no-tiered` flag, else `cfg.apply_tiered`.
     That mirrors `monitor` (cli.py:596-602); the pin is
     `test_tiered_flag_overrides_config`.
8. If nothing is proposed, print the D2 line and exit 0.
9. `plan_docs_pr(run.sync, root, target_branch=…, ref=…,
   branch_prefix=cfg.docs_pr.branch_prefix, config_id=facts.config_id,
   commit=facts.head)`. Under `--dry-run`, print the JSON and stop, with no forge
   contact.
   - The plan sets `base_sha = commit` (GIT-TRANSPORT).
   - Later slices change this one call:
     - CI-PATHS adds `repo_prefix=facts.prefix`;
     - CI-DELTA adds `delta=`;
     - HC-FORGE replaces `branch_prefix=` with `docs_pr=cfg.docs_pr`.
   - `remaining` is NOT a kwarg in step 1. It rides on `run.sync.remaining`
     (SYNC-HONEST, §8 F19), so SYNC-HONEST needs no cli.py edit.
10. Decide and act: `open_or_supersede(plan, stamp=plan_stamp(plan,
    config_id=facts.config_id, commit=facts.head), listing=listing,
    transport=…)`, using the D7 step-1 rules.
    - OPEN: `submit(plan, stamp=…)`, printing `opened docs MR: <url>`.
    - UP_TO_DATE: `docs MR already open and up to date: <url>`, with 0 writes.
    - Exit 0.

⟨R-REFUTED⟩ (kept from rev 3): there is no heal short-circuit on a pre-heal
UP_TO_DATE. `check` grades the workspace, so a short-circuit would turn every
retry red. The reproduction was `$D3/sc`: rc=1 unhealed, rc=0 healed.

**D4 (X-FORGE-CFG, X-FORGE-SITES, HC-FORGE, HC-SCAFFOLD).**
- The `forge:` block holds `provider`, `default_branch`, `api_url`, `project`,
  `token_env` and `commit_sha_env`.
- The `docs_pr:` block holds `branch_prefix`, `title`, `labels` and
  `description_header`.
- Both are mirrored on IndexFile and lifted as the SAME instance, so
  `model_fields_set` is kept.
- `FORGE_ENV_DEFAULTS`:
  - gitlab: `CI_PROJECT_ID` / `CI_API_V4_URL` / `CDMON_GITLAB_TOKEN`;
  - github: `GITHUB_REPOSITORY` / `GITHUB_API_URL` / `CDMON_GITHUB_TOKEN`.
- The API URL comes from config, else the platform env, else a loud
  TransportError that names both. No CLI path reaches a public host (T27).
  Today `from_env` falls back to one silently (pr.py:141, :324). The
  `from_env`/`from_repo` public defaults stay for Python-API callers only
  (rev-3 open decision 6).
- There is one `config.Provider` alias (sinks.py:76, gitfetch.py:70).
- The scaffolds carry `forge:`, `docs_pr:` and `apply_tiered` only as comments
  (T26, T86).
- `register` sends `default_branch` iff it is in `forge.model_fields_set`.

**D5 (CI-OPEN for open-docs-pr, HC-PROVENANCE for the rest).**
- The resolver returns `--ref`, else the first NON-EMPTY name in
  `forge.commit_sha_env`, else None.
- Before HC-PROVENANCE, `open-docs-pr` mirrors `monitor` (cli.py:628):
  `ref`, else `$CI_COMMIT_SHA`.

**D6 (X-GITFACTS core; CI-PATHS for the prefix).**
- `default_git_probe` runs git with `LC_ALL=C`. An OSError becomes a SyncError
  ("git is required: …").
- A `.git` at root or any ancestor means a work tree is expected. A failing
  `rev-parse --show-toplevel`, including dubious ownership, is then a SyncError.
- No `.git` anywhere gives a non-git result:
  `GitFacts(prefix="", head=None, config_id=<config path rel. root>,
  in_work_tree=False)`.
- `head` is `rev-parse HEAD` iff the tracked modifications are only managed docs.
- A root and config in different work trees raise.
- The prefix is `rev-parse --show-prefix`.
- Toplevel-relative paths apply to plan files, `created` and the description
  bullets. `SyncResult.changed_paths` and the `sync-pr` patch stay root-relative.
- `should-sync` strips the prefix.

**D7 (CI-STAMP): the step-1 rules.**
- **Branch key:** when the commit is known,
  `f"{docs_pr.branch_prefix}-{branch_digest(target, config_id, commit)}"`, where
  `branch_digest(*parts) = sha256("\x00".join(parts))[:12]`. When it is unknown,
  the legacy key `sha256(patch)[:12]` applies (pr.py:421-424).
- **Stamp:** the LAST description line is
  `<!-- cdx-docs-pr {"commit":…,"config":…,"content_key":…,"v":1} -->`, compact
  sort_keys JSON.
  - `content_key` = sha256 of the canonical JSON of
    `{"config": config_id, "files": plan.files}`.
  - `stamp=None` (the server route and the Python API) adds no stamp line.
    Their description bytes equal today's while nothing remains. D11's section
    still applies to them when drift remains (§8 F31, T93).
- **`find_open(target_branch, branch_prefix)`:**
  - GitLab: `GET projects/:id/merge_requests?state=opened&target_branch=…`.
  - GitHub: `GET repos/:o/:r/pulls?state=open&base=…`, excluding forks and a null
    head repo.
  - The source branch must start with `prefix + "-"`.
  - Pages of `per_page=100` until a short page (fewer than 100 items), then
    sorted by number. 100 is both providers' documented maximum, so a short
    page is the last one on the real forges; it is a protocol constant (§10).
    T55[page2] and T55[full_last_page] pin the paging, and T95 pins that the
    fake forge honours `per_page` up to that maximum (§8 F42).
  - A non-list response is a TransportError.
  - `number` = GitLab `iid` / GitHub `number`.
- **`decide_docs_pr(ours, open_prs)`, step 1.** `mine` = the stamped MRs with
  `stamp.config == ours.config`.
  - **Rule 1, UP_TO_DATE:** some m in `mine` has `stamp.commit == ours.commit`
    (both non-None) or `stamp.content_key == ours.content_key`. The lowest
    number wins.
  - **Otherwise OPEN.** This is the PD-30 interim: a later push opens another
    stamped MR. Other-config MRs and unstamped prefix MRs are ignored, never
    acted on.
- **Consequences, all safe:**
  - no MR is ever closed or written except by its own creation;
  - a human-touched bot MR is never overwritten;
  - concurrent same-commit retries that both miss `find_open` collide on the
    commit-keyed branch, giving a TransportError and still one MR;
  - a partial submit (branch created, MR not) makes every retry of that commit
    collide on the same branch. That is loud, and names the branch
    (§3c item 10, T94);
  - an out-of-order older run opens its own MR (STALE is RTE-05, T70).

**D8 (GIT-TRANSPORT; the HTTP half is CI-STAMP's).**
- GitHub labels are a 7th call, `POST repos/…/issues/{number}/labels`.
- GitLab uses `create` for `plan.created`, and `update` otherwise.
- The branch is cut from `plan.base_sha` (else the target). On GitHub this skips
  `GET ref`.
- The pr.py urllib leaves wrap HTTPError/URLError as
  `TransportError(f"{method} {url} -> HTTP {code}: {body[:512]}")`.
- `open_or_supersede` (CI-STAMP) re-raises a TransportError from `submit` as a
  TransportError that names `plan.source_branch`. It adds the remedy: a previous
  run may have created that branch without an MR, so delete it or push again.
  Both providers' branch/ref-create requests carry the name only in their body
  (pr.py:181-186, :400-406), so the leaf's `{method} {url}` message cannot name
  it (T94).

**D9 (SYNC-HONEST for capture; CI-DELTA for the delta).**
- `DocsSyncRun.sync` carries these, all captured BEFORE a dry-run restore
  (syncpr.py:142-152):
  - `files`: the root-relative path plus the HEALED text, sorted;
  - `created_paths`;
  - `remaining`: the run's post-recheck drift (`run.result.remaining`). This is
    a step-1 addition (§8 F19).
- `docs_delta(sync, *, facts, root, doc_paths)`:
  - with `facts.head` known, it baselines each managed doc on
    `git show HEAD:<prefix+p>`;
  - otherwise it uses the legacy prefixed snapshot.
- `plan_docs_pr` returns None iff the delta is empty.

**D10 (CI-GUARD owns should-sync's contract and the guard block, in all three jobs; CI-TEMPLATES owns `needs`, serialisation and the git bootstrap; §3b).**
- `should-sync` prints exactly one stdout line: `SHOULD_SYNC_PROCEED`
  (`"proceed"`) or `SHOULD_SYNC_SKIP` (`"skip"`). Both are `Final` constants in
  syncpr.py, so the template compares against the VALUE `skip`.
- It exits 0 to proceed, 1 to skip, and **2 on ANY error**, with `error:` on
  stderr and no token. "Any error" means a CodeDocMonitorError, or any other
  Exception the command body catches.
- The template SKIPs only on `RC=1` AND `DECISION=skip`. An unset or all-zero
  before-sha, or a failing `git diff`, means PROCEED.
- The GitLab adopter rule adds `$CI_PIPELINE_SOURCE == "push"`.
- The GitHub job maps `CDMON_BEFORE_SHA: ${{ github.event.before }}`.
- The loaders wrap UnicodeDecodeError (X-K8LOAD).

**D11 (SYNC-HONEST).**
- When `sync.remaining` is non-empty, the description adds `Needs a human before
  merge:`. It has one bullet per remaining drift (`doc_id: KIND — detail`, in
  config order) and sits before the stamp line.
- With nothing remaining, the description bytes are unchanged.
- The section reaches every caller of `plan_docs_pr`, because it renders from
  `sync.remaining` (F19), not from a CLI kwarg. That includes the server
  docs-PR route (app.py:1872-1879: `sync_pr`, then `open_docs_pr(sync, …)`) and
  the Python API `open_docs_pr`. Rev 3 kept the route unaffected (`remaining`
  was a cli.py kwarg); this file's F19 changes that deliberately (§8 F31). T93
  pins the route's description with and without remaining drift.
- The bot MR's own gate stays red while held or SUSPECT drift remains
  (intended).

## 3a. Signatures to pin (step-1 subset of rev 3, with owners)

Each owner pins its lines in ARCHITECTURE.md before its TDD loop, under ONE
new top-level section `## S1-CITPL — the docs-MR CI job (step 1)`, in its own
`### <SLICE>` subsection (for example `### CI-STAMP`). This follows the file's
existing `## EPIC …` / `### <slice>` convention, and it is the heading
CI-HARNESS proposed (§8 F45). Lines marked RTE-05 are not pinned in step 1.

```python
# custodex/config.py
Provider = Literal["github", "gitlab"]                     # X-FORGE-CFG (ForgeConfig.provider); HC-FORGE makes it THE one alias (sinks.py:76, gitfetch.py:70)
def validate_branch_name(value: str) -> str                # X-FORGE-CFG (AF R17): strip + git ref rules, no leading "-"; ValueError on violation.
                                                           #   The one branch validator. A caller outside a pydantic validator wraps the ValueError
                                                           #   as a typed error (CI-OPEN --target: SchemaError -> `error:`, exit 1; K8)
class ForgeConfig(BaseModel):                              # the forge: block (additive K6), lifted IndexFile -> MonitorConfig as the SAME instance
    provider: Provider = "gitlab"                          # X-FORGE-CFG; case-insensitive input
    default_branch: str = "main"                           # X-FORGE-CFG; validate_branch_name
    api_url: str | None = None                             # HC-FORGE; http(s) only; None => platform env => loud
    project: str | None = None                             # HC-FORGE; None => platform env
    token_env: str | None = None                           # HC-FORGE; non-empty; None => FORGE_ENV_DEFAULTS[provider].token
    commit_sha_env: tuple[str, ...] = ("CI_COMMIT_SHA", "GITHUB_SHA")   # HC-PROVENANCE; each non-empty; () never reads env
class DocsPrConfig(BaseModel):                             # the docs_pr: block (additive K6)
    branch_prefix: str = "cdmon/docs-sync"                 # X-FORGE-CFG (kept cdmon-era name)
    title: str = "docs: sync"                              # HC-FORGE; single line
    labels: tuple[str, ...] = ()                           # HC-FORGE; each non-empty, comma-free
    description_header: str = "Automated docs sync opened by `cdx` (bot-generated)."   # HC-FORGE
FORGE_DEFAULTS: ForgeConfig = ForgeConfig()                # X-FORGE-CFG
class ForgeEnvNames(BaseModel): project: str; api_url: str; token: str        # HC-FORGE; frozen, extra="forbid"
FORGE_ENV_DEFAULTS: Mapping[Provider, ForgeEnvNames]      # HC-FORGE; MappingProxyType (values in §3 D4)
# load_config / load_config_dir / load_bundle / load_unit_file / load_index_file: UnicodeDecodeError -> ConfigError   # X-K8LOAD

# custodex/forge.py (NEW; core deps only; pr-loop code_refs)
class GitOutcome(NamedTuple): returncode: int; stdout: str; stderr: str        # X-GITFACTS
GitProbe = Callable[[Sequence[str], Path], GitOutcome]                          # X-GITFACTS
def default_git_probe(args: Sequence[str], cwd: Path) -> GitOutcome           # X-GITFACTS; LC_ALL=C; OSError -> SyncError
class GitFacts(BaseModel): in_work_tree: bool; prefix: str; config_id: str; head: str | None   # X-GITFACTS; frozen
def git_facts(root: Path, *, config_path: Path, doc_paths: tuple[str, ...] = (),
              probe: GitProbe = default_git_probe) -> GitFacts                 # X-GITFACTS (D6)
def branch_digest(*parts: str) -> str                      # CI-STAMP; sha256("\x00".join(parts).encode()).hexdigest()[:12]
class DocsDelta(BaseModel): files: tuple[tuple[str, str], ...]; created: tuple[str, ...]; baseline: Literal["head", "snapshot"]   # CI-DELTA
def docs_delta(sync: SyncResult, *, facts: GitFacts, root: Path, doc_paths: tuple[str, ...],
               probe: GitProbe = default_git_probe) -> DocsDelta               # CI-DELTA (D9)
class ForgeTarget(BaseModel): provider: Provider; project: str; api_url: str; token: str = Field(repr=False)   # HC-FORGE
def resolve_forge(forge: ForgeConfig, *, provider: str | None = None, environ: Mapping[str, str]) -> ForgeTarget   # HC-FORGE
def docs_pr_transport(target: ForgeTarget) -> GitLabTransport | GitHubTransport        # HC-FORGE
def issue_transport(target: ForgeTarget) -> GitLabIssueTransport | GitHubIssueTransport # HC-FORGE
def source_sha(ref: str | None, forge: ForgeConfig, *, environ: Mapping[str, str]) -> str | None   # HC-PROVENANCE
def is_ancestor(ancestor: str, descendant: str, root: Path, *, probe: GitProbe = ...) -> bool | None   # RTE-05

# custodex/syncpr.py
SHOULD_SYNC_PROCEED: Final = "proceed"; SHOULD_SYNC_SKIP: Final = "skip"      # CI-GUARD
class SyncResult(BaseModel):  # + additive fields, frozen, extra="forbid"
    files: tuple[tuple[str, str], ...] = ()                # SYNC-HONEST
    created_paths: tuple[str, ...] = ()                    # SYNC-HONEST
    remaining: tuple[Drift, ...] = ()                      # SYNC-HONEST (step-1 addition, §8 F19)
class Advisory(BaseModel): enabled: bool = False; links: tuple[SuspectLink, ...] = (); error: str | None = None   # CI-OPEN
def transitive_advisory(cfg: MonitorConfig, root: Path) -> Advisory            # CI-OPEN; never raises
class DocsSyncRun(NamedTuple): sync: SyncResult; result: MonitorResult; advisory: Advisory   # CI-OPEN (rev 3's SyncRun, renamed, C15)
def sync_pr_run(monitor: Monitor, *, dry_run: bool = False, tiered: bool = False) -> DocsSyncRun   # CI-OPEN
def sync_pr(monitor: Monitor, *, dry_run: bool = False, tiered: bool = False) -> SyncResult   # == sync_pr_run(...).sync; unchanged signature
def should_sync(changed_files: Iterable[str], config: MonitorConfig, *, repo_prefix: str = "") -> bool   # CI-PATHS

# custodex/pr.py
class MergeRequestPlan(BaseModel):  # + additive
    target_branch: str = FORGE_DEFAULTS.default_branch     # X-FORGE-SITES (pr.py:50)
    base_sha: str | None = None                            # GIT-TRANSPORT
    created: tuple[str, ...] = ()                          # GIT-TRANSPORT (populated by SYNC-HONEST, T45b)
class DocsPrStamp(BaseModel):  # CI-STAMP; frozen
    v: Literal[1] = 1; config: str; commit: str | None; content_key: str
    bot_head: str | None = None                            # declared, always None in step 1 (§8 F14); RTE-05 fills it
def render_stamp(stamp: DocsPrStamp) -> str                # CI-STAMP
def parse_stamp(description: str | None) -> DocsPrStamp | None   # CI-STAMP; last marker wins; malformed / v != 1 -> None
def plan_stamp(plan: MergeRequestPlan, *, config_id: str, commit: str | None) -> DocsPrStamp   # CI-STAMP
class OpenDocsPr(BaseModel):  # CI-STAMP; frozen
    number: int                # GitLab iid / GitHub number, never the global id
    url: str; source_branch: str; head_sha: str | None; stamp: DocsPrStamp | None
class DocsPrAction(str, Enum): OPEN; UP_TO_DATE              # CI-STAMP pins the values; RTE-05 appends STALE, SUPERSEDE, BLOCKED
class DocsPrDecision(BaseModel): action: DocsPrAction; existing: tuple[OpenDocsPr, ...] = ()   # CI-STAMP; RTE-05 adds reason
def decide_docs_pr(ours: DocsPrStamp, open_prs: tuple[OpenDocsPr, ...]) -> DocsPrDecision   # CI-STAMP (rules 1 and 4); RTE-05 adds `*, is_ancestor=None`
@runtime_checkable
class PRQuery(Protocol):
    def find_open(self, *, target_branch: str, branch_prefix: str) -> tuple[OpenDocsPr, ...]: ...   # CI-STAMP
    # close_superseded(...)                                # RTE-05
class DocsPrOutcome(BaseModel): action: DocsPrAction; url: str | None   # CI-STAMP; RTE-05 adds superseded, reason, leftover
def open_or_supersede(plan: MergeRequestPlan, *, stamp: DocsPrStamp, listing: tuple[OpenDocsPr, ...],
                      transport: GitLabTransport | GitHubTransport) -> DocsPrOutcome   # CI-STAMP (OPEN / UP_TO_DATE only in step 1);
                                                           #   a submit TransportError is re-raised naming plan.source_branch + the remedy (T94)
class GitLabTransport / GitHubTransport:                   # + PRQuery (CI-STAMP)
    def submit(self, plan: MergeRequestPlan, *, stamp: DocsPrStamp | None = None) -> dict   # CI-STAMP; stamp=None = today's bytes
_UrllibGitLabHttp.request / _UrllibGitHubHttp.request      # CI-STAMP: HTTPError/URLError -> TransportError
def plan_docs_pr(sync: SyncResult, root: Path, *,
                 target_branch: str | None = None,         # X-FORGE-SITES (None => FORGE_DEFAULTS)
                 ref: str | None = None,
                 branch_prefix: str | None = None, labels: tuple[str, ...] | None = None,   # legacy overrides; None since HC-FORGE
                 docs_pr: DocsPrConfig | None = None,      # HC-FORGE
                 repo_prefix: str = "",                    # CI-PATHS
                 delta: DocsDelta | None = None,           # CI-DELTA
                 config_id: str | None = None, commit: str | None = None,   # CI-STAMP (branch key); GIT-TRANSPORT copies commit into base_sha
                 ) -> MergeRequestPlan | None              # SYNC-HONEST: files from sync.files, created, Needs-a-human from sync.remaining
def open_docs_pr(sync, root, *, transport, dry_run=False, **plan_kw) -> dict | None   # signature UNCHANGED (server route + Python API);
                                                           #   its description gains D11's section when sync.remaining is non-empty (F31, T93)
# RTE-05: BlockReason, IsAncestor, converge_docs_prs, ConvergePlan, retire_candidates, retire_obsolete, close_superseded

# custodex/issues.py: from_env keyword defaults derived from FORGE_ENV_DEFAULTS        # HC-FORGE
# custodex/sinks.py
def make_sink(cfg: CentralConfig, *, commit_env: tuple[str, ...] = FORGE_DEFAULTS.commit_sha_env) -> Sink   # HC-PROVENANCE
# custodex/registry.py
def repo_identity_from_config(cfg: CentralConfig, *, commit_env: tuple[str, ...] = FORGE_DEFAULTS.commit_sha_env) -> RepoIdentity   # HC-PROVENANCE
# custodex/monitor.py: Monitor.__init__ -> sink or make_sink(config.central, commit_env=config.forge.commit_sha_env)   # HC-PROVENANCE
# custodex/configsync.py: run_sync(..., default_branch: str = FORGE_DEFAULTS.default_branch)                        # X-FORGE-SITES
# custodex/gitfetch.py
class RemoteSpec: provider: Provider; default_branch: str = FORGE_DEFAULTS.default_branch   # HC-FORGE / X-FORGE-SITES
def confine_clone(tree: Path, cfg: MonitorConfig, config_dir: Path) -> str                  # CI-TRUST; escape -> SyncError; returns the prefix
# custodex/settings.py
class GitSettings(BaseModel):  # + additive
    default_branch: str = "main"                           # X-FORGE-CFG (env CDMON_GIT_DEFAULT_BRANCH)
    docs_pr: DocsPrConfig = DocsPrConfig()                 # HC-FORGE
    docs_pr_backend: BackendConfig = BackendConfig()       # CI-TRUST; kind mock, and only mock in step 1 (PD-32)
    docs_pr_agent: AgentConfig = AgentConfig()             # CI-TRUST
# custodex/server/app.py
def server_heal_config(cfg: MonitorConfig, git: GitSettings) -> MonitorConfig             # CI-TRUST (D0)
# custodex/server/standalone.py
def build_standalone_store(repo_root, *, repo_id=None, now: str, default_branch: str | None = None) -> InMemoryStore   # X-FORGE-SITES

# custodex/cli.py
def _echo_run(result: MonitorResult, links: tuple[SuspectLink, ...], error: str | None, *, tiered: bool) -> None   # OPS-CLOSE (W17 birth; SuspectLink is custodex.docdeps's, F49)
def _echo_run(result: MonitorResult, advisory: Advisory, *, tiered: bool, to_stderr: bool = False) -> None   # CI-OPEN (W18 re-pin of OPS-CLOSE's, F49)
def _source_sha(ref: str | None, cfg: MonitorConfig) -> str | None                              # HC-PROVENANCE
@app.command(name="open-docs-pr")
def open_docs_pr_cmd(config=…, dry_run=…,
                     target: str | None = typer.Option(None, "--target"),                   # X-FORGE-SITES (the default); CI-OPEN (validation)
                     ref: str | None = typer.Option(None, "--ref", "--source-sha"),         # CI-OPEN
                     provider: str | None = typer.Option(None, "--provider"),              # CI-OPEN
                     tiered: bool | None = typer.Option(None, "--tiered/--no-tiered"))     # CI-OPEN; None => cfg.apply_tiered
@app.command(name="sync-pr") def sync_pr_cmd(..., ref: str | None = typer.Option(None, "--ref", "--source-sha"))   # HC-PROVENANCE
@app.command(name="should-sync") def should_sync_cmd(files=…, config=…)    # CI-PATHS (prefix); CI-GUARD (token, exit 2)
@app.command(name="surface-gaps") def surface_gaps(..., provider: str | None = typer.Option(None, "--provider"))   # HC-FORGE
# register: default_branch sent iff "default_branch" in cfg.forge.model_fields_set                  # X-FORGE-SITES
# config sync --default-branch: default None => forge.default_branch, else FORGE_DEFAULTS            # X-FORGE-SITES
```

## 3b. Template shape (step-1 form, exact; CI-TEMPLATES, with CI-GUARD's rows)

This is rev 3's "Final template shape" with the step-1 cut applied:
- literals become variables with defaults (PD-30, critique M6);
- the config's state directory `$CDX_STATE_DIR` is cached (C16, F29);
- there is no trailing converge.

**Who writes which lines.**
- CI-TEMPLATES (W22) reorders the job (D1) and adds everything outside the
  guard block:
  - `needs: []`;
  - the `resource_group`/`concurrency`;
  - `GIT_DEPTH`/`fetch-depth: 0`;
  - the state-directory cache;
  - the git bootstrap;
  - the provider token.

  It keeps TODAY's guard lines verbatim (gitlab adopter :69-74, github adopter
  :69-74, .gitlab-ci.yml :118-123).
- CI-GUARD (W23) replaces the guard, in ALL THREE jobs, with the D10 block below.
  It also adds `CDMON_BEFORE_SHA` (GitHub) and the push rule (GitLab adopter).
  - To do that it adds `.gitlab-ci.yml` and `templates/ci/README.md` (the
    skip-token contract) to its scheduler file set. Its co-wave slice
    FPW-CFG-1 touches neither.
  - The reason: T74 cannot pass under today's guard (§8 F26).

**templates/ci/gitlab-ci.adopter.yml** header (prose):
- `CDMON_GITLAB_TOKEN` is a project access token with `api` scope, protected and
  masked. It is invisible on unprotected branches.
  - The NAME is derived from the transport default until HC-FORGE, which then
    makes it renamable with `forge.token_env`.
- For local or custom CI, set `forge.api_url` and `forge.project` (HC-FORGE).
- `cdx-gate` is expected to be RED on the default branch until the docs MR
  merges. The docs job runs anyway (`needs: []`).
- The docs job installs git, because slim images lack it.

```yaml
variables:
  CDMON_CONFIG: "cdmon.yaml"
  CDX_GIT_BOOTSTRAP: "apt-get update -qq && apt-get install -y -qq --no-install-recommends git"
  CDX_DOCS_PR_RESOURCE_GROUP: "cdx-docs-pr"
  CDX_STATE_CACHE_KEY: "cdx-state-$CI_COMMIT_REF_SLUG"
  CDX_STATE_DIR: ".cdmon"                            # <config dir>/.cdmon: the dir of a file CDMON_CONFIG, or the CDMON_CONFIG dir itself (F29)

cdx-docs-pr:
  stage: docs
  needs: []                                          # run even when cdx-gate is red on this commit
  resource_group: "$CDX_DOCS_PR_RESOURCE_GROUP/$CI_COMMIT_BRANCH"   # OD19: variable support INFERRED; else the literal cdx-docs-pr with a comment
  variables:
    GIT_DEPTH: "0"                                   # whole push range for the guard
  cache:
    key: "$CDX_STATE_CACHE_KEY"
    paths: ["$CDX_STATE_DIR/"]                       # OD19 also covers cache:paths expansion; else the literal state dir with a comment
    when: always                                     # the job exits 1 whenever drift remains; a retry most often follows a red run (§8 F24)
  script:
    - command -v git >/dev/null 2>&1 || sh -c "$CDX_GIT_BOOTSTRAP"
    - *cdx-setup
    - .venv/bin/cdx register --config "$CDMON_CONFIG"
    - |
      BEFORE="${CI_COMMIT_BEFORE_SHA:-}"
      RC=0
      DECISION=""
      if [ -z "$BEFORE" ] || [ -z "$(printf '%s' "$BEFORE" | tr -d 0)" ]; then
        echo "no usable before-sha — proceeding; the heal is idempotent"
      elif CHANGED="$(git diff --name-only "$BEFORE" HEAD)"; then
        DECISION="$(printf '%s\n' "$CHANGED" | .venv/bin/cdx should-sync --config "$CDMON_CONFIG")" || RC=$?
        if [ "$RC" -eq 1 ] && [ "$DECISION" = "skip" ]; then
          echo "doc-only commit (bot heal) — skipping heal to avoid re-triggering the loop"
          exit 0
        elif [ "$RC" -ne 0 ]; then
          echo "should-sync did not decide (exit $RC) — proceeding; open-docs-pr reports the error"
        fi
      else
        echo "changed-file list unavailable for $BEFORE..HEAD — proceeding; the heal is idempotent"
      fi
    - .venv/bin/cdx open-docs-pr --config "$CDMON_CONFIG" --provider gitlab --target "$CI_COMMIT_BRANCH" --ref "$CI_COMMIT_SHA"
    - .venv/bin/cdx check --config "$CDMON_CONFIG"
  rules:
    - if: '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'   # CI-GUARD adds the push half (M57)
```

- `INSTALL_LINE` (§5) matches the `command -v git` line. The harness therefore
  never runs apt-get, and `strip_git=True` models the slim image.
- `$CDX_GIT_BOOTSTRAP` is an adopter knob: set it for an Alpine image, or to
  `true` for an image that ships git.
- `$CDX_STATE_DIR` is an adopter knob. The adopter default `.cdmon` is right
  for the shipped root `cdmon.yaml`, and it also holds the cwd-relative
  `central.outbox` default (sinks.py:303). For `CDMON_CONFIG: config/cdmon`, set
  it to `config/cdmon/.cdmon`.

**templates/ci/github-actions.adopter.yml, `cdx-docs-pr`:**
- `if:` is unchanged (:52).
- `concurrency: {group: cdx-docs-pr-${{ github.ref }}, cancel-in-progress:
  false}` is a literal with a comment (§8 F25). A job-level `concurrency` cannot
  read `env:`, and the harness does not model `vars`.
- The job `env:` adds `CDMON_GITHUB_TOKEN: ${{ secrets.CDMON_GITHUB_TOKEN }}`
  (CI-TEMPLATES), `CDX_STATE_DIR: .cdmon` (CI-TEMPLATES, F29) and
  `CDMON_BEFORE_SHA: ${{ github.event.before }}` (CI-GUARD).
- Checkout uses `fetch-depth: 0`, replacing :58.
- The state directory uses `actions/cache/restore` before the run step, and
  `actions/cache/save` with `if: always()` after it. Both use
  `path: ${{ env.CDX_STATE_DIR }}`. The key is
  `cdx-state-${{ github.ref_name }}-${{ github.sha }}`, with restore-key
  `cdx-state-${{ github.ref_name }}-`. The `env` and `github` contexts are
  available in a step's `with:`. Unlike the job-level `concurrency` (F25), these
  lines therefore need no literal.
- ONE `run:` step holds the same guard block, using `cdx` and
  `"${CDMON_BEFORE_SHA:-}"`. It has no `${{ }}` inside `run:`, for
  script-injection hygiene. It ends with:

```bash
          cdx open-docs-pr --config "$CDMON_CONFIG" --provider github --target "$GITHUB_REF_NAME" --ref "$GITHUB_SHA"
          cdx check --config "$CDMON_CONFIG"
```

- The comment documents Option B (`github.token`): with it, a bot PR never
  triggers `cdx-gate`.

**.gitlab-ci.yml `docs:heal`** (:107-132):
- It gets the same git line and the same block (`config/cdmon`), plus
  `GIT_DEPTH: "0"`, the `resource_group`, and the state-directory cache with
  the job variable `CDX_STATE_DIR: "config/cdmon/.cdmon"`. The dogfood review log
  lives there, not at the root (F29).
- The global `cache:` at :58-61 (`.cache/pip`) is replaced by a job-level
  `cache:`. So docs:heal lists BOTH caches (§8 F24).
- It keeps stage `test` and its rules (manual, `allow_failure: true`).
- The header at :30-38 is updated.

**What the harness must model for this shape (§8 F28, F40).** The CI-HARNESS
model as first written refused the shape above. Each refusal was reproduced
against that copy of `tests/_ci_exec.py`:
- GitLab: `$CI_COMMIT_REF_SLUG` is not a modelled predefined variable, so
  `CDX_STATE_CACHE_KEY` makes every job in the template raise `NotModelled`;
- GitHub: `${{ }}` in a step's `with:` is refused;
- GitHub: `actions/cache/restore` and `actions/cache/save` are not modelled
  actions;
- GitHub: a step-level `if:` is not a modelled step key.

The model below is a REQUIREMENT on
CI-HARNESS, not a description of landed code, until the premise check F28
passes with `--harness` on CI-HARNESS's landed tree (§8 F40, F52). Holding
the harness files is not enough: a copy that has them but refuses
`resource_group` still fails F28 (§8 F48). Its acceptance check is the
CI-SPEC premise check F28 (with G6 and G7), run with `--harness <CI-HARNESS
tree>`: it fails closed on a tree without the model, and is reported as
deferred, never as passed, while no tree exists. The model this file relies
on, and T10f pins:
- `CI_COMMIT_REF_SLUG` (GitLab's slug of the ref) and `CI_COMMIT_REF_NAME` are
  always set;
- as on GitLab, `CI_COMMIT_BEFORE_SHA` is always set, all zeros when there is
  no before-sha;
- the modelled predefined variables are on `CiJob.predefined`, for both
  platforms. `CiJob.env` holds only a GitHub workflow's and job's `env:`.
  Premise G7 reads `predefined` (§8 F48);
- `actions/cache`, `actions/cache/restore` and `actions/cache/save` are
  record-only no-ops. Their `with:` (`path`, `key`, `restore-keys`) is kept
  raw and never evaluated. Every run is a cache miss unless the test seeds the
  workspace: the harness never restores a cache by itself, on either platform
  (T10f[never_restores_github, never_restores_gitlab]);
- a step `if:` may be only `always()` or `success()`. An `if: always()` step
  runs after an earlier step fails;
- every other action, `with:` key and `${{ }}` outside `env:`/`run:` is still
  refused.

Consequences for this file:
- T6's cache-hit model copies the config's state directory, derived from the
  product as T92 derives it, from run 1's checkout into run 2's. T92 pins
  statically that each template caches exactly that directory. So the harness
  never needs to resolve a cache path.
- T64[gitlab_unset] runs the guard block directly with bash rather than
  through `gitlab_job`, because the harness (like GitLab) never leaves the
  before-sha unset (F35).

Owner: CI-HARNESS, in its re-run. If the model does not land there, the owner
is CI-TEMPLATES, whose file set then gains `tests/_ci_exec.py`,
`tests/_fake_forge.py` (T95, `max_per_page`), `tests/_cdx_ci_shim.py` (the G6
fault models) and `tests/system/test_ci_harness.py`. Its co-wave DS-INBOX
touches none of them (§8 F51).

## 3c. Idempotency (K7), per write path, in step 1

Each path names its pinning test.

1. **Same-workspace rerun after the MR:**
   - before CI-DELTA: `check` is clean, so the job prints `clean — nothing to
     open`, with 0 forge contact and 0 records;
   - from CI-DELTA on: the delta vs HEAD equals the MR, so the result is
     UP_TO_DATE, with only the list GET, 0 writes and 0 records (T5a).
2. **Fresh-checkout retry of the same commit, any backend, HEAD known:**
   - the stamp matches on commit, so the result is UP_TO_DATE with 0 forge writes
     (T6; the CI-OPEN CLI row in §6.3);
   - the heal and the record re-emission recur. This is the pre-existing residue,
     pinned as parity with a `monitor --apply` twin, not as zero (T6[cache_miss];
     rev-3 open decision 16). A cache hit on the config's state directory makes
     the retry see run 1's review log (T6[cache_hit], T6[cache_hit_dir], T92);
   - concurrent same-commit retries collide on the commit-keyed branch. That gives
     a typed TransportError (T46) and still 1 MR.
   - **HEAD unknown** (non-git, or tracked edits beyond managed docs): the
     commit is None, so rule 1 matches only on `content_key`. A deterministic
     writer still gets UP_TO_DATE. A writer that emits different bytes gets a
     different `content_key` and legacy branch key, so it opens a second MR.
     That residue is pinned by the CI-OPEN K7 test's [non_git_salted] row
     (§8 F34). CI never takes this path while its checkout is clean.
3. **Unhealable drift left:** 0 provider writes. The records equal a `monitor`
   twin's; R11-HELDONCE may make that zero (T5b).
4. **A later push while a bot MR is open:** another stamped MR is opened (PD-30,
   T60i). Re-running either job gives UP_TO_DATE on its own MR (T62i). No MR is
   ever written except by its own creation.
5. **The bot's MR is merged:** `should-sync` prints `skip` and exits 1, so the job
   SKIPs. This holds for subdirectory configs too (T7, T63).
6. **Unknown before-sha, any `should-sync` error, or missing git:** the job
   PROCEEDs, or fails loudly before any record. Both are safe by 1–4 (T64, T65,
   T74).
7. **`--dry-run`:**
   - docs are byte-identical (K1);
   - 0 envelopes;
   - no forge contact;
   - the plan equals the real plan (T36, T42).
8. **The server route:**
   - a fresh clone per call;
   - NullSink;
   - no file written outside the clone (D0);
   - repeated dry runs write 0 bytes outside it (CI-TRUST K7);
   - tests/integration/test_syncpr.py:145 stays green.
9. **Every input to `decide_docs_pr`** is provider state plus commits. There is
   no clock (K10), so re-running gives the same decision.
10. **A retry after a partial submit** (§8 F33): run 1 created the commit-keyed
    branch, then its commit or MR create failed. GitLab creates the branch first
    (pr.py:181-186), and GitHub creates the ref before the PR (pr.py:400-406).
    `find_open` lists only open MRs, so the retry decides OPEN, and its branch
    create collides ("Branch already exists" / "Reference already exists").
    - Step 1: the retry exits 1 with `error:` naming the source branch and the
      remedy: delete that branch, or push again, which gives a new key. It makes
      0 further writes and opens 0 MRs. It is loud and bounded to one commit,
      and it is never silent (T94).
    - Under the legacy patch key, a deterministic writer hit the same collision
      today. A non-deterministic writer drew a fresh branch name and recovered.
      So the commit key trades that recovery for "no duplicate MR". That trade
      is accepted for step 1.
    - Adopting the MR-less bot branch at the same key is RTE-05's (§2
      Deferred). CI-STAMP's design review may pull it forward.

## 3d. Schema, version and upgrade impact (step 1)

- **Config (K6, additive):**
  - `MonitorConfig`/`IndexFile` gain `forge`/`docs_pr` (X-FORGE-CFG, HC-FORGE,
    HC-PROVENANCE);
  - `cdmon-config-version` stays `"2.0.0"`;
  - an OLDER custodex, an older central server included, rejects a config that
    SETS these keys (extra="forbid"). The scaffolds therefore emit them only as
    comments (T26, T86; HC-SCAFFOLD).
- **Server settings:** `GitSettings` gains `default_branch`, `docs_pr`,
  `docs_pr_backend` and `docs_pr_agent` (additive).
- **Models:**
  - `SyncResult` gains `files`, `created_paths` and `remaining`;
  - `MergeRequestPlan` gains `base_sha` and `created`, which are visible in the
    dry-run JSON;
  - new: `DocsPrStamp`, `OpenDocsPr`, `DocsPrAction{OPEN, UP_TO_DATE}`,
    `DocsPrDecision`, `DocsPrOutcome`, `DocsDelta`, `GitFacts`, `Advisory` and
    `DocsSyncRun`.
- **ReviewRecord and `cdx schema` are unchanged.** These are data changes only:
  - `source_sha` on sync-pr/open-docs-pr records;
  - `repo.commit` on GitHub envelopes;
  - the `GITHUB_SHA` stamp without `--ref`.
- **Branch names:** the shape `<prefix>-<12 hex>` is unchanged. The key input
  changes only when a clean-HEAD commit is known, which is the CI path, and that
  path had never opened an MR. The server route and non-git runs are
  byte-identical.
- **Versioning:** no fingerprint or hash change, so no adopter reheal is needed.
  The dogfood reheal covers the tracked modules each owner touches.
  - forge.py joins pr-loop's `code_refs` (X-GITFACTS).
  - The version stays 0.1.0 until REL-DECLARE (PLAN §0 P0).
- **Upgrade bullets** (owner slices' STATUS `upgrade:` lines; REL-0.2.0 builds
  the note from them):
  - CI-TRUST: server operators; the docs-PR route heals with
    `server.git.docs_pr_backend` (mock only in step 1). It never reports to the
    clone's `central:`, and it rejects (400) a clone whose root, docs or
    code_refs leave the clone.
  - CI-TEMPLATES: re-copy the docs-PR job. Changes to make:
    - remove `cdx monitor --apply`;
    - keep the guard lines as they are (CI-GUARD replaces them);
    - use `open-docs-pr --provider … --target <pushed branch> --ref <sha>`, then
      `cdx check`;
    - GitLab: `needs: []`, the `resource_group`, `GIT_DEPTH: "0"`, the git
      bootstrap and the state-directory cache. Set `CDX_STATE_DIR` to your
      config's `<config dir>/.cdmon`; the default `.cdmon` fits a root
      `cdmon.yaml`;
    - GitHub: `concurrency`, `fetch-depth: 0`, `CDX_STATE_DIR` and the cache
      steps;
    - set the provider token secret (`CDMON_GITLAB_TOKEN`, api scope, protected
      and masked; or `CDMON_GITHUB_TOKEN`, contents and pull-requests write).

    An upgraded CLI under the OLD job order still opens the MR (T73, CI-DELTA).
    Re-copying is still needed for gate independence, serialisation and git.
  - CI-GUARD: `should-sync` prints `proceed`/`skip`, and its errors exit 2.
    Re-copy the guard block, which skips only on exit 1 AND the `skip` token and
    proceeds on an unknown before-sha or a failing `git diff`. Also add
    `CDMON_BEFORE_SHA` (GitHub) and the `$CI_PIPELINE_SOURCE == "push"` rule
    (GitLab).
  - CI-OPEN: `open-docs-pr` reports the run like `monitor` (on stderr), fails
    before the heal on a bad provider, token or target, and prints `html_url` on
    GitHub.
  - CI-STAMP: a retry of the same commit reports `docs MR already open and up to
    date`. A later push opens another stamped MR until RTE-05 supersedes. If a
    run fails between creating the bot branch and opening the MR, a retry of that
    commit fails and names the branch: delete it, or push again.
  - SYNC-HONEST: the docs MR description lists what still needs a human
    (`Needs a human before merge:`). This covers the server docs-PR route and
    the Python API `open_docs_pr` too; their bytes are unchanged when nothing
    remains.
  - X-FORGE-SITES: `cdx register` sends `forge.default_branch` only when you set
    it, and `cdx serve` honours it.
  - HC-FORGE: set `forge.api_url` and `forge.project` for local or custom CI. No
    CLI path falls back to a public API host.
  - HC-PROVENANCE: `GITHUB_SHA` joins the commit env
    (`forge.commit_sha_env`).

## 4. Owner map

Each slice's items, in wave order (PLAN §2; plan.json). "PLAN" marks an owner
the plan already named; **bold** marks an owner confirmed or reassigned here
(reasons in §8). Non-CI tests a PLAN entry names are listed so each owner sees
its whole Red list.

| Slice | W | Tests | Mutants |
|---|---|---|---|
| CI-HARNESS | 1 | T10 incl. `test_rules_evaluator_refuses_unmodelled_syntax`, T75 (PLAN); **T10e** seam liveness (required, F30); **T10f** the §3b cache-step model, in its re-run (F28, F40, F41); **T95** the fake forge's `per_page` (F42) | M50 (PLAN); **M16, M64, M65** |
| X-GITFACTS | 1 | T47 without its `is_ancestor` rows; `test_zero_commit_repo_facts`, `test_dubious_ownership_is_loud` (PLAN) | M49, unit half (PLAN) |
| CI-TRUST | 2 | T76, T77, T78, T83a, T91, T24[backend, central, apply_tiered]; `test_every_config_field_is_classified`, `test_non_mock_docs_pr_backend_is_refused` (PLAN) | M51, M52 (PLAN) |
| X-K8LOAD | 3 | T81 (PLAN) | — |
| X-FORGE-CFG | 12 | T83b[branch], T24[forge.default_branch, docs_pr.branch_prefix] (PLAN); **T14[branch rows, unknown provider]** (split from the PLAN's HC-FORGE T14; F36) | **M12, M39** |
| CI-STAMP | 13 | T52, T53, T54[step-1 rows], T55, T79[isolation] (PLAN); **T46** (= the PLAN's `test_http_error_is_transport_error`), **T55[page2, full_last_page]** (F42), **T57b, T58[step-1 rows], T94** | M28, M46 (PLAN); **M27, M31′, M56′, M61, M63** |
| GIT-TRANSPORT | 14 | **T44, T45a, T57a** (= the PLAN's 7-call, missing-number, `create` and base_sha cases) | **M33, M34, M35** |
| X-FORGE-SITES | 16 | T22, T23, T84, T85 (PLAN); **T38** | M58 (PLAN); **M7** |
| OPS-CLOSE, then CI-OPEN | 17, 18 | **T31**, in tests/system/test_monitor_echo_golden.py: OPS-CLOSE (W17) lifts `_echo_run` first and births it with no CI-OPEN type; CI-OPEN re-pins the signature and keeps the test byte-identical (F49) | — |
| CI-OPEN | 18 | T28, T30, T32, T33, T34 (incl. the 401 row), T82, `test_tiered_flag_overrides_config` (PLAN); **T18a, T35, T36, T37, T39a, T41, T43**, **`test_open_docs_pr_retry_of_an_open_mr_is_up_to_date`** [git, non_git, non_git_salted] (the PLAN's K7 line, named here; F34); amendment #2. T34's api_url_unset row moves to HC-FORGE | M55 (PLAN); **M6, M8a, M9, M13a, M17, M18, M19, M20, M21, M22, M23, M62** |
| SYNC-HONEST | 19 | T42 (PLAN); **T29, T45b, T51** (T51 absorbs the PLAN's `test_mr_lists_remaining_before_stamp`), **T93** (F31) | **M10, M11, M40, M60** |
| CI-PATHS | 20 | **T48, T49** (the PLAN's "mono_repo and demo-subdirectory cases") | **M25, M26** |
| CI-DELTA | 21 | T73, T88 (PLAN); T73 in its own module, deps + CI-HARNESS (F36) | M54 (PLAN) |
| CI-TEMPLATES | 22 | T1, T2, T4, T5a, T5b, T6, T7, T8, T9, T11, T12c, T63, T66, T67, T68[retry half], T72 (PLAN); **T3a, T6[cache_hit_dir], T12[provider-token names, depth], T12b[needs, serialisation], T59, T60i, T62i, T75[W22 half], T90, T92**; **T10f** and **T95** only if CI-HARNESS's re-run does not land them (F28, F51); amendment #1. T74 moves to CI-GUARD (F26) | M42 (PLAN); **M1, M2, M3, M4, M5, M41a, M43, M59** |
| CI-GUARD | 23 | T50, T64 (+ the [gitlab_unset] row, F35), T65, T80 (PLAN); **T12[should-sync token, CDMON_BEFORE_SHA], T12b[push rule], T74** (from CI-TEMPLATES, F26); amendment #5 | M47, M48, M57 (PLAN); **M36a, M36b, M37, M41b, M49 (executed half)** |
| HC-FORGE | 27 | T13, T14[non-branch rows], T15, T16, T21, T25, T27, T83b[docs_pr] (PLAN); **T34[api_url_unset], T39b, T40**, T24[title, labels, header, api_url, project, token_env]; amendment #3 | **M13b, M14, M15, M24** |
| HC-PROVENANCE | 28 | T17, T19, T20 (PLAN); **T3b, T18 (without T18a)**, T24[commit_sha_env]; amendment #4 | **M8b, M38** |
| HC-SCAFFOLD | 37 | T26, T86 (PLAN) | — |
| RTE-05 | step 2+ | T47[is_ancestor], T54[rules 2, 3, 5–7], T56, T57[bot_head], T58[SUPERSEDE/BLOCKED/STALE], T60, T61, T62, T68[successive-push half], T69, T70, T71, T79[supersede/blocked], T89 | M29, M30, M31, M32, M44, M45, M53, M56 |

M31′ and M56′ are the step-1 re-derivations of M31 and M56 (§7).

**Dependency and file-set notes** (for the orchestrator; §8 F19–F21, F26, F28,
F36, F49, F51):
- CI-TEMPLATES should list SYNC-HONEST as a dependency. The wave order already
  satisfies this (W19 < W22).
- CI-TEMPLATES adds `tests/_ci_exec.py`, `tests/_fake_forge.py`,
  `tests/_cdx_ci_shim.py` and `tests/system/test_ci_harness.py` to its file set
  only if CI-HARNESS's re-run does not land the §3b model (F28, F51). Its
  co-wave DS-INBOX touches none of them.
- OPS-CLOSE adds `tests/system/test_monitor_echo_golden.py` (T31's module) to
  its file set. CI-OPEN should list OPS-CLOSE as a dependency, because it
  re-pins `_echo_run`. The wave order already satisfies this (W17 < W18; F49).
- CI-DELTA should list CI-HARNESS as a dependency (T73 executes a job). The wave
  order already satisfies this (W1 < W21).
- HC-FORGE (W27) and HC-PROVENANCE (W28) amend tests/system/test_cli.py
  (amendments #3 and #4). Each adds that module to its scheduler file set. Their
  co-wave slices (FPW-D, FPW-B) do not touch it.
- SYNC-HONEST stays off cli.py (W19's DS-CORE owns it) by carrying `remaining`
  on `SyncResult`.
- CI-GUARD (W23) adds `.gitlab-ci.yml` and `templates/ci/README.md` to its set.
  It owns the guard block in all three jobs (F26), and its co-wave FPW-CFG-1
  touches neither file.

**Test modules (PD-2: new tests go in new modules).** A test that rev 2 or
rev 3 named in an existing module moves to its owner's NEW module, unless that
existing module is already in the owner's scheduler file set. Two of these
are: CI-TRUST has tests/integration/test_server_gitsync.py, and CI-TEMPLATES has
tests/system/test_ci_templates.py.
- CI-HARNESS: `tests/system/test_ci_harness.py`.
- X-GITFACTS: `tests/unit/test_forge_git.py` (T47, not rev 2's
  `tests/unit/test_forge.py`).
- CI-TRUST: `tests/regression/test_server_clone_trust.py` (T91), and
  `tests/unit/test_heal_config_allowlist.py`, which holds the field walk and
  T83a. T83a does not go into the existing test_settings.py, which is outside
  CI-TRUST's set.
  - T24 goes in a NEW integration module that CI-TRUST creates, for example
    `tests/integration/test_server_docs_pr_trust.py`, not in
    test_server_gitsync.py. The later rows (X-FORGE-CFG, HC-FORGE,
    HC-PROVENANCE) then edit a module that no co-wave slice holds.
- X-K8LOAD: `tests/unit/test_k8_loaders.py` (T81).
- X-FORGE-CFG: `tests/unit/test_forge_config.py` (T83b[branch], T14[branch
  rows, unknown provider], and M12's by-value row).
- CI-STAMP: `tests/unit/test_docs_pr_stamp.py` (including T94).
- GIT-TRANSPORT: `tests/unit/test_transport_complete.py`.
- X-FORGE-SITES: `tests/system/test_branch_from_config.py` (T22, T23, T38,
  T84, T85) and `tests/unit/test_no_hardcoded_branch.py`.
- CI-OPEN: `tests/system/test_open_docs_pr_cli.py` (including T18a), with
  amendment #2 in test_cli.py.
- SYNC-HONEST: `tests/integration/test_sync_honest.py` (including T93).
- CI-PATHS: `tests/unit/test_toplevel_paths.py`.
- CI-DELTA: `tests/unit/test_docs_delta.py` (T88; rev 3 named
  `test_forge.py`), with T73 in its own `tests/system/test_pre_slice_job_order.py`.
  CI-TEMPLATES (W22) creates `test_ci_templates_exec.py` a wave later, so T73
  cannot live there (F36).
- CI-TEMPLATES: `tests/system/test_ci_templates_exec.py` (including T75's W22
  half and T6[cache_hit_dir]), `tests/regression/test_ci_template_order.py`,
  and T11/T12/T12b/T12c/T92 in test_ci_templates.py.
- CI-GUARD: `tests/system/test_should_sync_guard.py`.
- HC-FORGE: rev 2's `tests/unit/test_forge.py` (T15, T16) and
  `tests/unit/test_docs_pr_config.py` (T14) stand, because neither exists at
  ddc368d. T13 goes into test_docs_pr_config.py, not the existing
  test_config_v2.py. T21, T25, T27, T39b and T40 go into a new
  `tests/system/test_forge_cli.py`, not test_cli.py or test_pr.py. T34's
  api_url_unset row goes there too, as
  `test_open_docs_pr_api_url_unset_fails_before_any_heal`. CI-OPEN's T34 never
  carries that row, so HC-FORGE flips nothing in CI-OPEN's module (F36).
- HC-PROVENANCE: a new `tests/unit/test_provenance.py` (T17, T19, T20). They
  do not go into HC-FORGE's test_forge.py, test_sinks.py, test_registry.py or
  the *_cli.py modules. T18 (without T18a) and T3b go into a new
  `tests/system/test_provenance_cli.py`.
  - CI-TEMPLATES' T3a asserts nothing about the GitHub envelope commit, neither
    None nor HEAD. CI-OPEN's T18a has no GITHUB_SHA row. So HC-PROVENANCE adds
    rows and flips none in another slice's module (F36).
- HC-SCAFFOLD: a new `tests/unit/test_scaffold_keys.py` (T26, T86), with
  `tests/fixtures/scaffold_baseline_keys.json`. It does not reuse HC-FORGE's
  module, which is outside HC-SCAFFOLD's file set.
- **Rule:** no slice pins a row as an interim value that a later slice must
  flip in a module outside that later slice's file set. The one exception is
  the deliberate amendments of §6.6, each with a file-set entry (F20).

Deliberate amendments of existing tests are listed in §6.6.

## 5. The executed harness and fixtures (rev-2 text inlined; CI-HARNESS)

### tests/_ci_exec.py

- **`INSTALL_LINE`**:
  `re.compile(r"^\s*(python -m venv \.venv|(\.venv/bin/)?pip install\b|command -v git\b)")`.
  These are the ONLY lines skipped, and each template must match at least one, as
  a self-check against rot. The `command -v git` alternative is rev 3's.
- **`gitlab_job(template, job, *, head, branch, before, variables) -> CiJob`**
  (rev 2):
  - flattens `script` (anchors are already expanded by `safe_load`);
  - merges the template's and the job's `variables:` with the modelled predefined
    vars: `CI_COMMIT_SHA=head`,
    `CI_COMMIT_BEFORE_SHA=before` (all zeros when `before` is None, §3b),
    `CI_COMMIT_BRANCH`, `CI_DEFAULT_BRANCH`, `CI_PROJECT_ID`, `CI_API_V4_URL`;
  - adds the project CI/CD variables the template header documents;
  - derives the token NAME, never typing it as a literal;
  - runs the job as ONE `bash -eo pipefail -c`, like the GitLab runner.

  **Step 1:** `FORGE_ENV_DEFAULTS` does not exist until HC-FORGE (W27). Until
  then, derive the token name from
  `inspect.signature(GitLabTransport.from_env).parameters["token_env"].default`
  (pr.py:123), and likewise GitHub's (pr.py:305). HC-FORGE switches to the table,
  and T16 pins the two equal.
- **`gitlab_pipeline(template, *, source, branch, default_branch, head, before,
  variables) -> tuple[CiJob, ...]`** (rev 3):
  - a minimal `rules:` evaluator: `$VAR` truthiness, `$A == $B`,
    `$A == "lit"`, `&&`;
  - the first matching `if` wins, and `when: manual` is excluded from the auto
    run;
  - ANY other syntax raises `NotModelled`;
  - predecessors are `needs:` when present (`[]` = none), else every job of an
    earlier `stages:` entry.
- **`run_ci_pipeline(jobs, repo, …)`** runs the jobs in stage/needs order. A job
  whose predecessor failed is SKIPPED (GitLab `on_success`), and the result is
  a per-job status.
- **`github_job(template, job, *, head, branch, repository, secrets, event) ->
  CiJob`** (rev 2):
  - merges workflow, job and step `env:`;
  - resolves `${{ secrets.X }}` from `secrets` and `${{ github.event.before }}`
    from `event`. Any other `${{ }}` raises;
  - runs each `run:` step as its own `bash -e -c`, stopping at the first failure.

  Rev 3 adds:
  - `${{ }}` is evaluated only in `env:` and `run:`;
  - `concurrency:` and `if:` are checked statically only.

  Step 1 (§3b, §8 F28, F40) adds only what the §3b shape needs. It is a
  REQUIREMENT on CI-HARNESS's re-run, not landed code:
  - GitLab `CI_COMMIT_REF_SLUG`/`CI_COMMIT_REF_NAME`, and an always-set
    `CI_COMMIT_BEFORE_SHA` (all zeros when unknown, as on GitLab);
  - the modelled predefined variables on `CiJob.predefined` for both
    platforms, never in `CiJob.env` (a GitHub workflow's and job's `env:`
    only); premise G7 reads that field (§8 F48);
  - the `actions/cache` restore/save steps as record-only no-ops, with their
    `with:` kept raw;
  - a step `if:` of `always()`/`success()` only;
  - the GitLab job keys the §3b shape carries: `resource_group` (checked
    statically, like GitHub's `concurrency:`) and a job-level `cache:`
    (record-only, never restored, T10f);
  - a GitHub workflow triggered by `on: push` (the only modelled event).

  The harness never restores a cache on its own (T10f). T6 seeds the product's
  state directory itself.

  Three limits of the model that step-1 tests must respect (§8 F43, F44):
  - **Pipeline source.** A merge-request pipeline is not a push pipeline with
    another `CI_PIPELINE_SOURCE`: GitLab leaves `CI_COMMIT_BRANCH` unset there.
    CI-HARNESS's re-run refuses (`NotModelled`) a provider variable it neither
    sets nor knows to be unset for the given source, in `rules: if:` and in
    `${VAR:-…}` defaults. Every executed step-1 pipeline (T72, T73) is a
    `push` pipeline; an executed push-rule row, if one is ever added, uses a
    source on which GitLab sets `CI_COMMIT_BRANCH` (`schedule`, `web`), never
    `merge_request_event`.
  - **Protected variables.** The harness does not model variable protection.
    No step-1 test relies on the harness hiding the token on a non-default
    branch; a row that needs that passes `secrets={}` itself.
  - **GitHub events.** Only `push` is modelled; another `event_name` is
    refused. No step-1 GitHub row uses another event.
- **`run_ci_job(job, repo, *, tmp, forge_state, strip_git=False) ->
  CiRun(exit_code, stdout, stderr, requests)`** writes the shim as `tmp/bin/cdx`
  AND `repo/.venv/bin/cdx`.
- **Environment (R8).** The job env is built from an ALLOWLIST, never from
  `os.environ`:
  - `PATH` (only to locate binaries), `HOME=tmp/home`, `LANG=C.UTF-8`, `TMPDIR`;
  - the `CDX_FAKE_*` vars;
  - the modelled CI vars;
  - the declared secrets.
- **`strip_git=True`** builds `tmp/nogit-bin`, a symlink farm of every PATH
  executable except `git*`, to model a slim image (R3).
- **`no_ci_env`** is a pytest fixture for in-process CLI tests. It clears the
  commit-env names and the provider env names, derived from code, never typed.
  - Before HC-PROVENANCE the only commit env read is `CI_COMMIT_SHA`
    (cli.py:628/:1507/:2542, sinks.py:296, registry.py:234).
  - Before HC-FORGE the provider names are the `from_env` signature defaults.

### tests/_fake_forge.py

A STATEFUL fake GitLab and GitHub.
- Its state is a JSON file (`$CDX_FAKE_FORGE_STATE`) shared across job runs, so
  `find_open` sees the MR that run 1 opened.
- It models exactly the endpoints the transports use:
  - branch create. A duplicate raises the same error type the wrapped leaf
    raises. At W1 that is `custodex.errors.TransportError` (errors.py:55), raised
    by the fake itself. CI-STAMP's T46 later makes the real leaves raise the same
    type;
  - commit, returning `id` (GitLab) or `sha` (GitHub);
  - MR/PR create, which records the description and head sha;
  - list open, paged. It honours the request's `per_page` up to the
    providers' maximum of 100. With no `per_page` it uses the provider's
    default page size, GitLab 20, GitHub 30, from one per-provider table in
    the fake that T95 reads (§8 F50). A
    separate `max_per_page` test knob can force smaller pages. A fake that
    capped `per_page` below the request would end a short-page loop early and
    hide MRs (T95, §8 F42);
  - note/comment and close (used only by RTE-05 tests);
  - the GitHub `ref`, `commits`, `trees`, `refs` and `issues/{n}/labels`.
- MRs carry `id = iid + 10000` (GitLab) and `id != number` (GitHub), and answer
  404 on the wrong identifier (R15).
- Test hooks: a "human commit" (moves the head sha) and close.
- Every request is appended to `$CDX_FAKE_HTTP_LOG`.

### tests/_cdx_ci_shim.py

The real `custodex.cli:app`, with these changes:
- `pr._UrllibGitLabHttp` and `pr._UrllibGitHubHttp` are bound to the fake forge.
- `registry._UrllibRegisterHttp` and `sinks._UrllibClient` are replaced by JSONL
  recorders.
- `urllib.request.urlopen` is an AssertionError tripwire (K4).
- `CDX_FAKE_NONDET_SALT` (rev 2) wraps `custodex.monitor.apply_fix`
  (monitor.py:33, called at :582 and :666). It appends a salt-dependent prose
  line after each successful write, modelling an LLM that writes different bytes
  each run.
- `CDX_FAKE_DECLINE_WRITE` (rev 3) makes the write seam return False. That
  models the declined-write ALARM, as test_cli.py:1407-1443 does in-process.

Only the designed `# pragma: no cover` seams are touched. `submit` and
`find_open` run for real.

**Step 1: the seams are a requirement on CI-HARNESS.** CI-HARNESS runs in this
same wave; until premise check G6 passes on its landed tree, the seams are
not landed (§8 F40). Its round-1 shim (`tests/_cdx_ci_shim.py`,
`_wrap_write_boundary`) kept rev 2's seams and added one model, and its re-run
must keep them; premise check G6 verifies it on the landed tree:
- `CDX_FAKE_NONDET_SALT` AND `CDX_FAKE_DECLINE_WRITE` both wrap the ONE write
  boundary, `custodex.monitor.apply_fix`. The salt is appended only after
  `original(doc_path, fix)` returns True (a write that changed the document).
  The decline is filtered by comma-separated repo-relative doc paths.
- It adds `CDX_FAKE_NOW`, which pins `monitor._default_now`, `cli._now` and
  `config._now`, so record ids and timestamps compare byte-for-byte.

An earlier in-progress copy salted `backends.MockBackend.propose`. The landed
shim does not, so both fault models share the exposure to AF-1a (W4,
`render_fix`) and the E4/HEAL write-path slices. T10e's two halves (§6.5) are
therefore REQUIRED, not recommended: a moved seam must fail loudly (§8 F12,
F30).

### Fixtures

Real git via tests/_gitrepo.py. Git and bash are already suite requirements, so
there is no skipif. Fixtures are module-scoped and copied per test.

| Fixture | Contents |
|---|---|
| `adopter_repo` | examples/external-repo verbatim, plus `.gitignore` entries for `.cdmon/` and `.venv/`. Commits: A (base); B (`widget_area(width, height)` gains `depth: int = 1`); C (a `make_widget` signature change). Rev 3's B′ (reverts B) serves only RTE-05's T71 |
| `tiered_adopter_repo` | Tiers are stamped through a real heal BEFORE the base commit (⟨R-LEARNED⟩, re-verified at ddc368d: examples/external-repo/docs/api.md still ships a composite-only `cdm.fingerprint`, so its first change would grade UNKNOWN). `apply_tiered: true`. A region-less user-guide `docs/guide.md` over `src/acct.py`. The change adds `widget_perimeter` (ADDITIVE) and drops `force` (BREAKING) |
| `demo_repo` | demo/ without `.cdmon`. The green change is a private `_trace_hook`; the red change is `load_graph(..., *, strict=True)` (demo/src/taskflow/io/storage.py:49). Its config is the dir layout `config/cdmon`, so its state directory is `config/cdmon/.cdmon/` (T6[cache_hit_dir]) |
| `mono_repo` | an outer repo with demo/ under `demo/`, plus an unrelated top-level `docs/api/core-api.md` |
| `mono2_repo` | two configs, `apps/a/cdmon.yaml` and `apps/b/cdmon.yaml`, sharing the default prefix |

## 6. Test register

Each entry gives what it pins, today's status at ddc368d, and the step-1
disposition with its owner. The module an entry names is rev 2's or rev 3's.
The step-1 module is the one §4 gives.

- "rev 2" marks text recovered verbatim in substance.
- "rev 3" marks the rev-3 delta.
- "step 1" marks the re-derivation against the cut and the wave order.

### 6.1 PR-0: the server clone trust boundary

- **T76** `test_server_docs_pr_route_never_uses_the_clones_central_or_backend[central_http_auth_env, central_file_path, backend_command]` · **CI-TRUST**. RED (`$D3/trust1` posts `Bearer SERVER-KEK-VALUE`).
  - These clone configs produce **0** recorded outbound posts, no victim file and
    no subprocess marker:
    - `central: {sink: http, url: evil, auth_env: CDMON_SECRET_KEY}`, with the
      server env set;
    - `central: {sink: file, path: <abs>}`;
    - `backend: {kind: claude-code, command: [sh, -c, touch MARKER]}`.
  - The route still returns its normal status.
- **T77** `test_server_docs_pr_route_confines_the_clone[root_absolute, root_dotdot, doc_path_dotdot, code_ref_dotdot, doc_symlink_out]` · **CI-TRUST**. RED (`$D3/trustroot`).
  - Pins: 400, the victim byte-identical and 0 transport calls, for `dry_run`
    true and false.
- **T78** `test_server_docs_pr_route_prefixes_plan_paths_with_the_clone_root` · **CI-TRUST**. RED.
  - Pins: a clone whose root is `sub/` gives the plan file `sub/docs/api.md`.
- **T83a** test_settings.py::`test_git_settings_docs_pr_heal_backend_declared_and_rendered` · **CI-TRUST**. RED.
  - Pins the defaults (kind mock), and that `cdx settings` renders
    `server.git.docs_pr_backend.kind` (`_settings_lines`, cli.py:3109).
  - Step 1: a non-mock kind is refused (PD-32, `test_non_mock_docs_pr_backend_is_refused`).
- **T91** regression `test_server_route_never_acts_on_the_clones_authority` · **CI-TRUST**. RED.
  - A thin re-assertion of T76 and T77. Break-it: drop `sink=`/`backend=` or
    `confine_clone`.
- **T24** `test_server_docs_pr_route_uses_settings_not_the_cloned_repos_docs_pr`, parametrized by row.
  - rev 2: a cloned `docs_pr.branch_prefix: evil/x` is IGNORED; the prefix comes
    from `server.git.docs_pr` (the trust boundary).
  - rev 3: the rows `{docs_pr.branch_prefix: evil/x, forge.commit_sha_env:
    [SERVER_SECRET], forge.default_branch: evil}` are all ignored, and
    SERVER_SECRET appears in no response or envelope.
  - step 1: each row lands with the slice that creates its key:
    - CI-TRUST: backend, central, apply_tiered;
    - X-FORGE-CFG: forge.default_branch, docs_pr.branch_prefix;
    - HC-FORGE: title, labels, header, api_url, project, token_env;
    - HC-PROVENANCE: commit_sha_env.
  - `test_every_config_field_is_classified` makes each later knob slice red until
    it adds its row.

### 6.2 PR-A: config, forge, provenance, scaffolds, register, serve

- **T13** tests/integration/test_config_v2.py::`test_forge_and_docs_pr_blocks_are_lifted_from_index` · **HC-FORGE**. RED.
  - rev 2: index.yaml `forge: {provider: github}` and `docs_pr: {title: x}` reach
    `cfg` by VALUE. The class guard in test_config_v2.py only checks that the
    name exists.
  - step 1: X-FORGE-CFG's lift is killed earlier by AF 18 restated for
    `forge.default_branch`, which must carry a `docs_pr.branch_prefix`-by-value
    row (M12).
- **T14** tests/unit/test_docs_pr_config.py::`test_forge_and_docs_pr_are_loud_on_bad_values` · **HC-FORGE**. The branch rows and the unknown-provider row are **X-FORGE-CFG**'s (bold: split from the PLAN's HC-FORGE T14, F36), because `validate_branch_name` and the `Provider` parse land there. RED.
  - rev 2: each of these is a ConfigError through BOTH `load_config` and
    `load_config_dir`:
    - an unknown provider;
    - an empty or whitespace `default_branch`/`branch_prefix`;
    - an empty or multi-line title;
    - a label that is empty or contains a comma;
    - an empty `token_env`;
    - an empty `commit_sha_env` element;
    - a non-http(s) `api_url`.
- **T15** tests/unit/test_forge.py::`test_resolve_forge_precedence_and_loudness` · **HC-FORGE**. RED.
  - rev 2, precedence: the provider flag beats config; `project` and `api_url`
    config beat env; `token_env` config beats the table.
  - Loudness: a missing api_url raises TransportError naming `forge.api_url` AND
    the env var. The check order is project → token → api_url. A GitHub project
    must be owner/repo.
- **T16** tests/unit/test_forge.py::`test_from_env_defaults_are_the_forge_env_defaults` · **HC-FORGE**. RED.
  - rev 2: the four `from_env` signatures' defaults (pr.py:119-124, :301-306;
    issues.py:138-143, :201-206) equal `FORGE_ENV_DEFAULTS`.
- **T17** tests/unit/test_forge.py::`test_source_sha_precedence` · **HC-PROVENANCE**. RED.
  - rev 2: `ref`, then the first NON-EMPTY env var in `commit_sha_env` order, then
    None. A custom tuple is honoured; `()` never reads the env.
- **T18** tests/system/test_cli.py::`test_heal_commands_stamp_source_sha_like_monitor` · **HC-PROVENANCE**, except T18a. RED for sync-pr, open-docs-pr and GITHUB_SHA.
  - rev 2: parametrized over {`monitor --apply` (control), `sync-pr`,
    `open-docs-pr --dry-run`} × {`--ref`, only CI_COMMIT_SHA, only GITHUB_SHA}.
    Pins every new review-log record's `source_sha`.
  - step 1, **T18a** (CI-OPEN): the `open-docs-pr --dry-run --ref X` and
    only-CI_COMMIT_SHA rows. They kill M8a when CI-OPEN wires `source_sha`.
  - The GITHUB_SHA rows and every `sync-pr` row (sync-pr gains `--ref` in
    HC-PROVENANCE) stay in T18.
  - Step-1 modules: T18 goes in HC-PROVENANCE's new
    `tests/system/test_provenance_cli.py`; T18a goes in CI-OPEN's
    `tests/system/test_open_docs_pr_cli.py`. T18a has no GITHUB_SHA row, so
    HC-PROVENANCE flips nothing there (F36).
- **T19** test_sinks.py + test_registry.py::`test_envelope_commit_honours_commit_sha_env` · **HC-PROVENANCE**. RED.
  - rev 2: with only GITHUB_SHA set, the envelope and identity commit equal it
    (sinks.py:296, registry.py:234); `repo_commit` still wins.
- **T20** test_codeindex_cli.py + test_scip_cli.py::`test_*_stamps_through_the_forge_resolver` · **HC-PROVENANCE**. RED.
  - rev 2: with only GITHUB_SHA set, the stored `source_sha` equals it
    (cli.py:1507, :2542).
- **T21** tests/system/test_cli.py::`test_surface_gaps_provider_token_and_api_come_from_forge` · **HC-FORGE**. RED.
  - rev 2: `forge.provider: github` plus `token_env: MY_TOK` reaches the GitHub
    issue leaf with MY_TOK; `--provider gitlab` wins; no API URL gives a loud
    error with 0 requests (cli.py:1647-1713).
  - rev 3: adds a case-insensitive `--provider GitHub`.
- **T22** tests/system/test_cli.py::`test_config_sync_default_branch_comes_from_forge` · **X-FORGE-SITES**. RED.
  - rev 2: a spy on `run_sync` sees `forge.default_branch`; `--default-branch`
    wins (cli.py:955-957, configsync.py:388).
- **T23** tests/integration/test_server_gitsync.py::`test_server_default_branch_fallback_comes_from_settings` · **X-FORGE-SITES**. RED.
  - rev 2: `server.git.default_branch: trunk`, plus a repo with no default
    branch, means the docs-PR route targets trunk. The other three sites pass
    trunk too (app.py:1725, :1841, :2067, :2183).
- **T25** tests/unit/test_pr.py::`test_plan_docs_pr_reads_docs_pr_config` · **HC-FORGE**. RED.
  - rev 2: the prefix, title, labels and header come from the passed
    `DocsPrConfig`, and the legacy kwargs override it.
  - `DocsPrConfig()` reproduces today's plan bytes, and the existing plan tests
    (test_pr.py:80-190) stay green unmodified.
- **T26** tests/unit/test_docs_pr_config.py::`test_scaffolds_ship_forge_and_docs_pr_as_comments_equal_to_defaults` · **HC-SCAFFOLD**. RED.
  - rev 2: the three scaffolds load with no `forge`/`docs_pr` key, and
    un-commenting the example yields `ForgeConfig()`/`DocsPrConfig()`.
  - rev 3: `apply_tiered` joins as a comment. R11-SCAFFOLD (W4) comments it with
    its own test (templates_v2.py:136, onboard.py:244).
- **T27** tests/system/test_cli.py::`test_cli_never_builds_a_transport_via_from_env` · **HC-FORGE**. RED.
  - rev 2: with all four `from_env` monkeypatched to raise, `open-docs-pr` and
    `surface-gaps` still submit.
- **T81** · **X-K8LOAD**. RED (traceback).
  - rev 3: single-file, index and unit files with invalid UTF-8 give a
    ConfigError; `check` gives `error:` and exit 1.
- **T83b** · **X-FORGE-CFG** (branch half), **HC-FORGE** (docs_pr half). RED.
  - rev 3: declared, validated (an empty/whitespace branch is loud) and rendered
    by `cdx settings`.
- **T84** · **X-FORGE-SITES**. RED.
  - rev 3: when unset, the payload `default_branch` is None (today's bytes);
    when set to `develop`, it is sent. `provider` is never sent. Both loaders.
- **T85** · **X-FORGE-SITES**. RED.
  - rev 3: when unset, the branch is `"main"` (today); `forge.default_branch:
    develop` reaches the registration and both `run_sync` calls
    (standalone.py:48, :107, :121, :137).
- **T86** · **HC-SCAFFOLD**. RED (`apply_tiered`).
  - rev 3: every ACTIVE top-level key of the three scaffolds is in the frozen
    pre-slice key set, via the baseline file (C7).

### 6.3 PR-B: report, fail-fast, git facts, delta, transports, should-sync

- **T28** `test_sync_pr_run_returns_the_monitor_result` · **CI-OPEN**. RED.
  - rev 2: `sync_pr(...) == sync_pr_run(...)[0]`; the result's `handled` and
    `closures` are populated.
  - step 1: `sync_pr(...) == sync_pr_run(...).sync`. The return type is
    `DocsSyncRun` (C15), and `.advisory` is present.
- **T29** `test_sync_pr_captures_healed_files_and_created_paths_before_a_dry_run_restore` · **SYNC-HONEST** (reassigned; §8 F4). RED.
  - rev 2: under `dry_run=True`, `files` hold the HEALED text sorted,
    `created_paths` lists a new doc, and the tree is restored.
  - step 1: use `_CreatingBackend` (tests/integration/test_syncpr.py:182) for the
    new doc. The restore it guards is syncpr.py:142-152.
- **T30** `test_open_docs_pr_reports_the_run_exactly_like_monitor` · **CI-OPEN**. RED.
  - rev 2, parametrized over three fixtures:
    - (a) the declined-write ALARM: the test_cli.py:1407 fixture, with
      `apply_fix` stubbed;
    - (b) held-only tiered;
    - (c) a mechanical closure (test_cli.py:1352).
  - It pins that the verdict, closure, ALARM, advisory and remaining lines
    `open-docs-pr --dry-run` prints to stderr are the same multiset that
    `monitor --apply` prints on a twin, over both of monitor's streams. "clean" is
    never printed when drift remains.
  - rev 3: adds (d) `docdeps.transitive: true`: the dry-run advisory line equals
    `monitor --apply`'s (R10).
  - step 1: the twin comparison makes it robust to OPS-CLOSE's `held:` line and
    R11-HELDONCE.
- **T31** `test_monitor_output_is_byte_identical_across_the_echo_lift` · **OPS-CLOSE** (W17 lifts `_echo_run` first and births it; **CI-OPEN**, W18, re-pins its signature and keeps it byte-identical; §8 F46, F49). GREEN at birth; it guards the lift.
  - Module: tests/system/test_monitor_echo_golden.py, new, in OPS-CLOSE's file
    set. It rebuilds the two fixtures itself and never imports the test_cli
    module, so neither owner edits that module for T31.
  - Order inside OPS-CLOSE: the golden is committed GREEN on OPS-CLOSE's base
    before the lift, and the lift keeps it green. The only lines OPS-CLOSE may
    re-pin are its own `held:` lines.
  - OPS-CLOSE's `_echo_run` takes the advisory as `(links, error)`, which
    `monitor` computes as today, so the birth needs no CI-OPEN type
    (`Advisory` is CI-OPEN's). CI-OPEN swaps the pair for
    `advisory: Advisory`, and T31's bytes do not move.
  - rev 2: the golden stdout/stderr of `monitor --apply --tiered` on the RTE-03d
    closure (test_cli.py:1352) and alarm (test_cli.py:1407) fixtures.
  - step 1: add a `docdeps.transitive: true` row, because the advisory moves to
    "computed right after `run()`" (D2).
  - The later slice keeps it green and may re-pin only the lines its own design
    changes. For CI-OPEN that is none.
- **T32** `test_open_docs_pr_nothing_to_open_names_the_remaining_drift` · **CI-OPEN**, which owns the text (C15). RED.
  - rev 2: held-only prints "nothing to open — 1 drift(s) remain", exit 0; clean
    prints "clean — nothing to open".
  - step 1: the exact rev-3 D2 string. SYNC-HONEST aligns MCP and the server
    summary to it.
- **T33** `test_heal_commands_keep_stdout_machine_readable` · **CI-OPEN**. GREEN at birth; it kills M19.
  - rev 2: `sync-pr` stdout == the patch exactly; `open-docs-pr --dry-run` stdout
    parses as JSON; echo lines appear only on stderr.
- **T34** `test_open_docs_pr_misconfig_fails_before_any_heal` · **CI-OPEN**, except the api_url_unset row. RED.
  - rev 2, parametrized cases:
    - `--provider bitbucket`, and the same under `--dry-run`;
    - token unset; API URL unset;
    - `--target ""`; `--target "a b"`.
  - Each gives exit 1, `error:`, no traceback, 0 review-log lines, 0 FileSink
    envelopes and byte-identical docs.
  - rev 3: adds the list GET answering HTTP 401, which needs T46.
  - step 1: the **api_url_unset** row belongs to **HC-FORGE**. Until W27,
    `GitLabTransport.from_env` silently falls back to `https://gitlab.com/api/v4`
    (pr.py:141), so the row cannot be green at CI-OPEN. It lives in HC-FORGE's
    `tests/system/test_forge_cli.py` as
    `test_open_docs_pr_api_url_unset_fails_before_any_heal`, never as an interim
    row in CI-OPEN's module (F36).
  - Keep-green: `test_open_docs_pr_missing_env_is_loud` (test_cli.py:700-709,
    "CI_PROJECT_ID" in the message) under the new order, and again after
    `resolve_forge` (project is checked first).
- **T35** `test_open_docs_pr_clean_repo_needs_no_provider_env` · **CI-OPEN**. GREEN at birth; it kills M22.
  - rev 2: a clean tree with ZERO provider env prints "clean — nothing to open",
    exit 0. It sits alongside the kept `test_open_docs_pr_clean_repo_is_noop`
    (test_cli.py:692-697).
  - step 1: also pins 0 forge requests on the clean path (no retire pass).
- **T36** `test_previews_never_report_to_central` · **CI-OPEN**. RED.
  - rev 2: `open-docs-pr --dry-run` and `sync-pr --dry-run` with a FileSink give
    0 envelopes.
  - The local review-log append on a preview is pre-existing, shared by both
    commands, and unchanged.
- **CI-OPEN K7** `test_open_docs_pr_retry_of_an_open_mr_is_up_to_date` · **CI-OPEN** (the PLAN's K7 line, named here; §8 F22). RED.
  - In-process, parametrized over three rows:
    - [git]: a git fixture with a known head, so rule 1 matches on the commit.
      This row holds for any writer;
    - [non_git]: a non-git tmp_path, so the commit is None and rule 1 matches on
      `content_key`. This is a DETERMINISTIC-writer pin: it passes only because
      the mock backend writes the same bytes twice (§8 F34);
    - [non_git_salted]: the same, with a writer whose fix text carries a per-run
      salt (monkeypatched at the write boundary, like T10e's NONDET model). This
      is a residue pin: run 2 decides OPEN and submits a second MR, and the stub
      holds 2 MRs. HEAD-known CI runs never take this path; [git] with the same
      salt stays UP_TO_DATE.
  - Run 1 opens the MR through a stub transport that records requests. Run 2
    is on a FRESH copy of the unhealed tree, with the stub's list GET answering
    run 1's stamped MR. In the [git] and [non_git] rows, run 2:
    - prints `docs MR already open and up to date: <url>`;
    - makes exactly 1 request, the list GET;
    - exits 0;
    - leaves review-log records that equal a `monitor --apply` twin's (the
      pre-existing re-emission, §3c item 2).
  - A same-workspace rerun in this slice prints `clean — nothing to open`, with
    0 requests and 0 new records. CI-DELTA turns that into UP_TO_DATE (T5a).
  - Kills M28 at the CLI level. Mutation: `decide` always returns OPEN, which
    gives a second submit.
- **T93** `test_server_docs_pr_route_description_lists_what_still_needs_a_human[none_remaining, remaining]` · **SYNC-HONEST** (new; §8 F31). RED.
  - SYNC-HONEST owns app.py in its file set. It pins the server route's plan
    (the route with `dry_run: true` returns `plan.model_dump()`), driven by
    `sync_pr`, then `open_docs_pr(sync, …)` (app.py:1872-1879).
    - [none_remaining]: the description is byte-identical to today's
      stamp-free, section-free bytes.
    - [remaining]: it ends with `Needs a human before merge:` and one
      `doc_id: KIND — detail` bullet per remaining drift. There is no stamp
      line, because the route passes `stamp=None`.
  - The same pair runs through the Python API `open_docs_pr(..., dry_run=True)`
    on a local tree.
  - Kills M60.
- **T37** `test_open_docs_pr_provider_comes_from_forge_and_flag_overrides` · **CI-OPEN** (confirmed). RED.
  - rev 2: `forge.provider: github` hits the GitHub leaf; `--provider gitlab`
    wins.
  - step 1: plus `--provider GitHub`, case-insensitive. `forge.provider` comes
    from X-FORGE-CFG (W12). The leaf is reached via `from_env` until HC-FORGE.
- **T38** `test_open_docs_pr_target_comes_from_forge_and_flag_overrides` · **X-FORGE-SITES** (reassigned; §8 F2). RED.
  - rev 2: `forge.default_branch: develop` gives the plan target develop;
    `--target rel` wins.
  - step 1: X-FORGE-SITES already turns the `--target` default (cli.py:798-802,
    literal `"main"` at :799) into None-then-resolve. It is asserted via the
    `open-docs-pr --dry-run` JSON `target_branch`. At W16 that JSON still comes
    from today's command body; CI-OPEN (W18) keeps the row green.
- **T39** `test_open_docs_pr_mr_cosmetics_reach_both_providers`, split in two.
  - rev 2: the prefix, title, labels and header are asserted at the
    PROVIDER-REQUEST level: the GitLab MR body has `labels: "a,b"`; GitHub gets
    `issues/{n}/labels` with `["a","b"]`.
  - **T39a** · **CI-OPEN**: `docs_pr.branch_prefix: team/docs` gives the source
    branch `team/docs-<12hex>`, and `find_open` filters on `team/docs-`, on both
    providers.
  - **T39b** · **HC-FORGE**: title, labels and `description_header` at the
    request level. The GitHub labels call is GIT-TRANSPORT's.
- **T40** `test_open_docs_pr_token_env_comes_from_forge` · **HC-FORGE** (reassigned; `forge.token_env` lands at W27). RED.
  - rev 2: `forge.token_env: MY_TOK`, with only MY_TOK set, submits.
- **T41** `test_open_docs_pr_and_sync_pr_pass_doc_style_like_monitor` · **CI-OPEN** (confirmed). RED.
  - rev 2: a spy on the `custodex.cli.Monitor` kwargs, on a dir-layout config
    with doc-style.yaml.
  - Today `monitor` passes `doc_style=_doc_style_for(config_dir)`
    (cli.py:238, :629-633). `sync-pr` (:726) and `open-docs-pr` (:824) build a
    bare `Monitor(cfg, config_dir)`.
- **T42** `test_open_docs_pr_dry_run_plan_equals_the_real_plan` · **SYNC-HONEST** (PLAN). RED.
  - rev 2: on twin git fixtures, the dry-run JSON == the submitted plan,
    including `base_sha` and `created`, with HEALED file text. Docs are
    byte-identical after the dry run (K1).
  - step 1: `base_sha` is wired by CI-OPEN, `created` by T45b. CI-DELTA must keep
    it green when `created` moves to `delta.created`.
- **T43** `test_open_docs_pr_prints_the_github_html_url` · **CI-OPEN** (confirmed). RED.
  - rev 2: the name only; its Pins cell is "—". D8 (rev 2 and rev 3) supplies
    the rule: the CLI prints `web_url`, falling back to `html_url`.
  - step 1: pins `opened docs MR: <html_url>` when the response has no
    `web_url` (cli.py:859-860 reads only `web_url`), and `web_url` when both are
    present.
- **T44** `test_github_submit_applies_labels_via_the_issues_api` · **GIT-TRANSPORT** (reassigned). RED.
  - rev 2: 7 calls with labels; 6 without, and the existing 6-call test
    (test_pr.py:369) stays green. A missing `number` is a TransportError.
- **T45**, split in two.
  - rev 2: `test_gitlab_submit_creates_new_docs_and_updates_existing` plus
    test_syncpr.py::`test_sync_pr_marks_a_healed_missing_doc_as_created`. Uses a
    stub backend that heals MISSING_DOC (the mock leaves it unhealed); `create`
    for created paths, `update` otherwise. RED.
  - **T45a** · **GIT-TRANSPORT**: the transport half, on a hand-built plan with
    `created`. pr.py:189-192 always sends `update` today; the 3-call test
    (test_pr.py:221) stays green.
  - **T45b** · **SYNC-HONEST**: a healed MISSING_DOC, via `_CreatingBackend`,
    appears in `DocsSyncRun.sync.created_paths`, dry and non-dry, and reaches
    `plan.created`.
- **T46** `test_urllib_leaves_raise_transport_error_on_http_and_url_errors` · **CI-STAMP** (reassigned; this is the PLAN's `test_http_error_is_transport_error`). RED.
  - rev 2: `urlopen` is monkeypatched to raise HTTPError(409) or URLError, with
    no network. The message carries the method, url, code and a body excerpt
    (≤512 bytes).
  - step 1: the leaves are `_UrllibGitLabHttp` (pr.py:72-92) and
    `_UrllibGitHubHttp` (pr.py:248-270). Their `# pragma: no cover` shrinks to
    the `urlopen` line.
- **T47** tests/unit/test_forge_git.py::`test_git_facts_prefix_head_anchor_and_ancestry` · **X-GITFACTS**; its `is_ancestor` rows are **RTE-05**. RED. (Rev 2 named `tests/unit/test_forge.py`; X-GITFACTS's module is test_forge_git.py.)
  - rev 2, with real git:
    - a toplevel root gives `""`; a subdir gives `"demo/"`;
    - a dirty tracked tree gives head None;
    - a non-git root and anchor give (`""`, None);
    - root and anchor in different repos raise SyncError;
    - `is_ancestor` returns True, False, and None on a shallow clone.
  - rev 3 extras:
    - `.git` present with the probe raising OSError gives a SyncError;
    - `.git` present with rev-parse rc=128 `dubious ownership` gives a SyncError;
    - no `.git` and no binary gives non-git;
    - a dirty non-doc file gives head None; a dirty managed doc alone keeps head;
    - `config_id` for 3 layouts.
  - PLAN adds `test_zero_commit_repo_facts` and `test_dubious_ownership_is_loud`.
- **T48** `test_plan_paths_are_rebased_onto_the_git_toplevel` · **CI-PATHS** (reassigned). RED.
  - rev 2: in `mono_repo`, plan files, `created` and the description bullets are
    `demo/docs/...`. The `sync-pr` patch stays root-relative, with unchanged
    bytes.
- **T49** `test_should_sync_strips_the_repo_prefix` · **CI-PATHS** (reassigned; the should_sync caller at cli.py:771). RED.
  - rev 2: the DEMOS.md command exits 1; `demo/src/...` exits 0; a path outside
    the prefix exits 0. The regression corpus test stays green.
  - step 1: the command is at demo/DEMOS.md:770-772. It is false today, exiting 0
    because the path is not prefix-stripped. The corpus test is
    tests/regression/test_corpus_pipeline.py:366-386.
  - A `git_facts` SyncError inside should-sync is pinned as
    `exit_code != 0` plus `error:` on stderr, not as an exact 1. CI-GUARD's
    T50 pins the exact 2, so CI-GUARD needs no amendment of CI-PATHS's module
    (§8 F13, F27).
- **T50** `test_should_sync_errors_exit_2_never_skip` · **CI-GUARD**. RED (exit 1 today, cli.py:766-768).
  - rev 2: a malformed config, and a root in another repo, exit 2.
  - rev 3: adds a non-typed error (a monkeypatched `_load` raising ValueError):
    exit 2, no token.
- **T51** `test_mr_description_lists_what_still_needs_a_human` · **SYNC-HONEST** (reassigned from CI-GUARD; §8 F3). RED.
  - rev 2: the bullets appear when drift remains; with none remaining, the
    description bytes are unchanged.
  - step 1: D11's format. The section comes BEFORE the stamp line, which absorbs
    SYNC-HONEST's `test_mr_lists_remaining_before_stamp`.
- **T80** · **CI-GUARD**. RED.
  - rev 3: stdout is exactly `SHOULD_SYNC_PROCEED`/`SHOULD_SYNC_SKIP` for exit
    0/1, and nothing on stdout on error.
- **T82** · **CI-OPEN**. RED. It is T30(d).
- **T88** tests/unit/test_docs_delta.py::`test_docs_delta_baselines_on_head` · **CI-DELTA**. RED.
  - rev 3, `docs_delta` baselines on HEAD:
    - (a) an earlier writer's healed doc is in the delta vs HEAD;
    - (b) a dry-run overlay comes from `sync.files`;
    - (c) head None gives the prefixed snapshot (legacy);
    - (d) `created` = absent at HEAD;
    - (e) identical to HEAD gives an empty delta.

### 6.4 PR-C: one open docs MR per (target, config)

- **T52** `test_branch_key_is_content_independent_when_the_commit_is_known` · **CI-STAMP**. RED.
  - rev 2: different healed text with the same (target, commit) gives the SAME
    `source_branch`; another target gives another key; commit None gives the
    legacy patch hash (test_pr.py:80-110 stay green).
  - rev 3: another `config_id` gives another key.
- **T53** `test_stamp_renders_deterministically_and_round_trips` · **CI-STAMP**. RED.
  - rev 2: compact sort_keys JSON; the last marker wins; a malformed marker or
    `v: 2` gives None.
  - rev 3: it round-trips with `config`.
  - step 1: the field set is {v, config, commit, content_key}. For `bot_head`,
    see §8 F14.
- **T54** `test_decide_docs_pr` · **CI-STAMP** (the step-1 rows).
  - rev 2: parametrized over rules 1-7, plus precedence cases: UP_TO_DATE beats
    MULTIPLE_OPEN; a matching `content_key` with a new commit is UP_TO_DATE;
    `bot_head` None gives HUMAN_COMMITS; `is_ancestor` None gives
    NOT_A_DESCENDANT.
  - rev 3 adds:
    - UP_TO_DATE beats STALE, which beats UNSTAMPED, which beats OPEN;
    - an other-config MR is ignored (OPEN);
    - set-SUPERSEDE over 2 untouched ancestors.
  - **Step-1 rows:**
    - a commit match gives UP_TO_DATE; both commits None never match on commit;
    - a `content_key` match with a new commit gives UP_TO_DATE;
    - the lowest number among matches wins;
    - `mine` holding 2 MRs, the second of which matches, gives UP_TO_DATE (M31′);
    - an other-config MR alone gives OPEN (R5);
    - an unstamped prefix MR alone gives OPEN (the interim);
    - `mine` non-empty with no match gives OPEN (the PD-30 interim; RTE-05
      replaces this row with rules 2 and 5-7).
  - Every other row is **RTE-05**.
- **T55** `test_find_open_lists_bot_mrs_by_prefix_and_pages` · **CI-STAMP**. RED.
  - rev 2, for both providers:
    - the query params;
    - `cdmon/docs-syncX` is NOT matched (the `-` is required);
    - GitHub forks and a null head repo are excluded;
    - paging until a short page; sorted by number;
    - a non-list response is a TransportError.
  - rev 3: it returns `iid`/`number`, never `id`; the stub sets `id ≠ iid`
    (M56′).
  - step 1 (§8 F42), for both providers:
    - [page2]: the stub answers `per_page=100` with 100 open prefix MRs on
      page 1 and 1 on page 2, and the matching bot MR is the one on page 2.
      `find_open` returns it, after exactly 2 list GETs (`page=1`, `page=2`),
      each carrying `per_page=100`. Kills M63 (no paging).
    - [full_last_page]: exactly 100 MRs; page 2 is empty. 2 list GETs, all
      100 returned, and no third GET.
    - The page size is read from the product's own request, never typed into
      the stub's answer.
- **T56** `test_close_superseded_comments_then_closes` · **RTE-05**.
  - rev 2: the exact request sequence for both providers.
  - rev 3: by iid/number; the fake 404s on `id`.
- **T57** `test_submit_branches_from_base_sha_and_embeds_the_stamp`, split in two.
  - rev 2:
    - the GitLab branch has `ref = base_sha`;
    - GitHub skips `GET ref` and parents on `base_sha`;
    - the description ends with the stamp, whose `bot_head` is the created
      commit;
    - `stamp=None` gives today's bytes, so the existing submit tests stay green.
  - RED.
  - **T57a** · **GIT-TRANSPORT**: the `base_sha` half. Today GitLab cuts the
    branch from `plan.target_branch` (pr.py:181-186), and GitHub makes the
    `GET ref` call at pr.py:363-369. `base_sha=None` keeps today's calls.
  - **T57b** · **CI-STAMP**: `submit(plan, stamp=s)` makes the stamp the LAST
    description line, and `stamp=None` reproduces today's bytes.
  - The `bot_head` half, and the TransportError when a commit response lacks
    `id`/`sha`, are **RTE-05**.
- **T58** `test_open_or_supersede_acts_on_each_decision` · **CI-STAMP** (the step-1 rows).
  - rev 2, with a fake PRQuery: OPEN submits; UP_TO_DATE writes nothing;
    SUPERSEDE submits THEN closes; BLOCKED writes nothing.
  - rev 3: STALE writes nothing.
  - **Step-1 rows:** OPEN submits exactly once, with the stamp. UP_TO_DATE makes
    0 transport calls and returns the existing MR's URL.
  - The SUPERSEDE, BLOCKED and STALE rows are **RTE-05**.
  - The act function is pinned by CI-STAMP. Keep the rev-3 name
    `open_or_supersede(plan, *, stamp, listing, transport)`; RTE-05 adds
    `is_ancestor`.
- **T94** `test_partial_submit_leaves_a_loud_retry_that_names_the_branch[gitlab_commit_fails, gitlab_mr_fails, github_pr_fails]` · **CI-STAMP** (new; §8 F33). RED.
  - A stub leaf lets run 1's branch (GitLab) or ref (GitHub) create succeed,
    then fails the named later call.
  - The retry uses the same plan and stamp, with an empty listing, so it
    decides OPEN. Its branch/ref create answers "Branch already exists" /
    "Reference already exists".
  - `open_or_supersede` raises a TransportError whose message contains
    `plan.source_branch` and the remedy (delete the branch, or push again).
  - After the failing create, no further call is made, and the stub holds 0 MRs.
  - Kills M61. CI-OPEN's `error:` wrapper carries the message through unchanged,
    as it does for every TransportError.
- **T69** · **RTE-05**.
  - rev 3: `test_open_or_supersede_converges_after_the_write`.
- **T79** `test_config_identity_isolates_decisions` · **CI-STAMP** (the isolation half).
  - rev 3: at the same commit, two configs get distinct branch keys and
    `content_key`s, and neither is UP_TO_DATE for the other.
  - The "neither SUPERSEDEd nor BLOCKED" half is **RTE-05**.
- **T89** · **RTE-05**.
  - rev 3: `test_retire_candidates`.

### 6.5 PR-D: executed jobs and pipelines

These live in tests/system/test_ci_templates_exec.py unless an entry names
another module (T11, T12, T12b, T12c and T92 are static, in
test_ci_templates.py; T73 is CI-DELTA's). The executed ones run as subprocesses
with the env allowlist and no network.

- **T1** `test_adopter_docs_pr_job_opens_a_docs_mr_for_a_code_change[gitlab]` · **CI-TEMPLATES**. RED (no request).
  - rev 2:
    - the requests are GET list → branch (`ref=HEAD`) → commit
      (`update docs/api.md`, containing `depth: int = 1`) → MR;
    - the MR targets the pushed branch, and the title carries HEAD;
    - the description ends with a stamp with `commit=HEAD`;
    - the log contains `api: HASH -> FIX (applied)`;
    - exit 0.
  - rev 3: a trailing list (converge); the stamp has `config=cdmon.yaml`.
  - step 1: no trailing list (converge is RTE-05).
- **T2** `...[github]` · **CI-TEMPLATES**. RED.
  - rev 2: the same via GitHub: list → commits/HEAD → trees → commits → refs →
    pulls. The token comes from the job `env:` secret mapping.
  - step 1: no `GET ref` (`base_sha` is known) and no trailing list.
- **T3** `test_adopter_docs_pr_job_stamps_provenance_on_records_and_envelopes[gitlab, github]`, split in two. RED.
  - rev 2: `record.source_sha == HEAD` AND the envelope `repo.commit == HEAD`.
  - step 1: the envelope comes from the fixture's own `central: {sink: http,
    outbox: .cdmon/outbox.jsonl}` (examples/external-repo/cdmon.yaml). The shim
    records it, so the outbox stays empty.
  - **T3a** · **CI-TEMPLATES**: the records on both providers (via `--ref`), and
    the GitLab envelope (sinks.py:296 reads `CI_COMMIT_SHA` today). It asserts
    nothing about the GitHub envelope's commit, neither None nor HEAD, so no
    later slice flips a row here (F36).
  - **T3b** · **HC-PROVENANCE**: the GitHub envelope `repo.commit == HEAD`, in
    HC-PROVENANCE's own `tests/system/test_provenance_cli.py`. It needs
    `forge.commit_sha_env` (W28); until then the commit is None.
- **T4** `test_adopter_docs_pr_job_under_apply_tiered_ships_mechanical_then_fails_on_held` · **CI-TEMPLATES**. RED.
  - rev 2:
    - the MR files == `["docs/api.md"]`, and `docs/guide.md` is untouched;
    - exit 1;
    - the log carries the `closure: api — … closed mechanically (no backend)`
      line (cli.py:658-660 today), the guide verdict line, and `check`'s
      `guide: HASH [breaking]` (drift.py:398 format);
    - the MR description lists guide under "Needs a human".
  - step 1: "the guide verdict line" is whatever `cdx monitor --apply` prints for
    the held doc on a twin at that commit (OPS-CLOSE's `held:` line with its
    close hint; R11-HELDONCE). Compare with the twin, not with a literal.
- **T5** `test_adopter_docs_pr_job_rerun_in_same_workspace[healable, remaining_suspect]` · **CI-TEMPLATES**.
  - rev 2:
    - (a) prints "clean — nothing to open", with 0 provider requests, 0 new
      central records, exit 0;
    - (b) on demo with the io change: 0 provider writes, exit 1 from check, and
      the new records are exactly the re-recorded ESCALATE (pre-existing
      `monitor` behaviour).
  - rev 3, **T5a**: a same-workspace rerun after the MR prints
    `docs MR already open and up to date`, makes only the list GET, 0 writes,
    0 new records, exit 0. It needs CI-DELTA's HEAD baseline.
  - **T5b** as rev 2, but step 1 pins PARITY: the new records equal what
    `cdx monitor --apply` appends on a twin. R11-HELDONCE (W8) may make that
    zero; a fixed "re-recorded" count would pin a wart the program removes.
- **T6** `test_adopter_docs_pr_job_retry_under_a_nondeterministic_backend_opens_one_mr` · **CI-TEMPLATES**. RED (2 MRs).
  - rev 2: two fresh checkouts of B, with different `CDX_FAKE_NONDET_SALT`s.
    Run 2 prints "already open and up to date" and makes ONLY the GET list
    request. The fake forge holds exactly 1 MR.
  - rev 3: it also counts that the retry re-emits the same records.
  - step 1 (C16), parametrized over the state-directory cache:
    - [cache_miss]: run 2's records equal run 1's (re-emission, the residue
      RTE-05's central dedupe removes);
    - [cache_hit]: run 2's records equal what `cdx monitor --apply` appends on a
      twin whose state directory holds run 1's log.
    - Both: 1 MR, and run 2 makes only the list GET.
    - The test models a hit by copying the config's state directory, derived
      from the product exactly as T92 derives it, from run 1's checkout into
      run 2's. It never copies a hard-coded `.cdmon/`. T92 pins that the
      template caches that same directory. The static half pins the cache
      declaration in §3b:
      - GitLab: `cache:when: always`;
      - GitHub: `actions/cache/save` with `if: always()`.
      Run 1 of a retry is usually RED (§8 F24).
    - [cache_hit_dir] (step 1, F29): the same on `demo_repo` through
      `.gitlab-ci.yml docs:heal`, whose config is the dir layout `config/cdmon`.
      It pins directly that the log persisted: run 2's
      `config/cdmon/.cdmon/review-log.jsonl` begins with run 1's lines. That
      holds whatever R11-HELDONCE does to the records appended. A cache of the
      root `.cdmon/` carries nothing here (M59).
- **T7** `test_adopter_docs_pr_job_skips_the_bots_merged_docs_commit` · **CI-TEMPLATES**. GREEN; keep-green.
  - rev 2: the MR's files committed onto main give "skipping", no provider
    request, exit 0.
  - It must stay green through the reorder (W22) and through CI-GUARD's new
    guard (W23, skip only on RC=1 AND `skip`).
- **T8** `test_dogfood_docs_heal_job_opens_a_docs_mr` · **CI-TEMPLATES**. RED.
  - rev 2: `.gitlab-ci.yml docs:heal` (:107-132) on `demo_repo` with the green
    change: the MR carries `docs/api/core-api.md`, exit 0.
  - The job runs directly; the harness ignores its `when: manual` rule.
- **T9** `test_dogfood_docs_heal_job_opens_the_mr_then_gates[gate_true, gate_false]` · **CI-TEMPLATES**. RED.
  - rev 2: the MR carries `docs/api/io-api.md`; exit 1 with the getting-started
    SUSPECT_LINK. Under `docdeps.gate: false`, exit 0 (the D1 gate change).
- **T10** harness self-tests · **CI-HARNESS**.
  - rev 2: `test_harness_refuses_an_unmodelled_github_expression`,
    `test_harness_install_filter_matches_every_template`,
    `test_shim_tripwire_fails_an_unpatched_network_call`,
    `test_fake_forge_rejects_a_duplicate_branch`.
  - rev 3: `test_rules_evaluator_refuses_unmodelled_syntax`.
  - step 1, **T10e** `test_shim_write_seam_is_live` (REQUIRED, F30), with two
    halves:
    - with `CDX_FAKE_DECLINE_WRITE` set, a healable fixture's run shows the
      declined write;
    - with `CDX_FAKE_NONDET_SALT` set, two runs write different bytes.
    Both seams wrap `custodex.monitor.apply_fix`. If that seam moves (AF-1a
    `render_fix` W4, E4 and HEAL slices), T6 and T59 must fail loudly, not pass
    vacuously (§8 F12).
  - step 1, **T10f** `test_harness_models_the_state_cache_steps` · **CI-HARNESS** (its re-run; else **CI-TEMPLATES**, F28, F40, F41). The pins may be
    split across several tests; CI-HARNESS's STATUS row then names the test
    that carries each pin (none may be left to "covered elsewhere"). It pins:
    - a GitLab job whose variables reference `$CI_COMMIT_REF_SLUG` resolves it
      to GitLab's slug of the branch;
    - `CI_COMMIT_BEFORE_SHA` is set, all zeros, for `before=None`;
    - `actions/cache/restore`/`save` (`with: {path, key, restore-keys}`) are
      accepted as record-only no-ops, with `with:` kept raw and never
      evaluated;
    - a step `if: always()` runs after a failed step, and any other step `if:`
      is refused;
    - every other action, `with:` key and `${{ }}` outside `env:`/`run:` still
      raises `NotModelled`;
    - the harness never restores a cache by itself, asserted by executing, not
      by reading the harness source (§8 F41; kills M65):
      - [never_restores_github]: a GitHub job whose `actions/cache/restore`
        step is followed by a `run:` step that fails if the state directory
        exists, with that directory present in an EARLIER run's checkout and
        absent from this one. The job passes;
      - [never_restores_gitlab]: the same with a GitLab job that declares a
        `cache:` (key, paths, `when: always`) and whose first script line fails
        if the state directory exists.
- **T95** `test_fake_forge_honours_per_page_up_to_the_provider_max` · **CI-HARNESS** (new; else **CI-TEMPLATES**, F51; §8 F42, F50). RED.
  - With 101 open MRs in the fake, for GitLab and GitHub:
    - a list GET with `per_page=100` returns 100 items on page 1 and 1 on
      page 2;
    - a list GET with no `per_page` returns the provider's default page
      size (GitLab 20, GitHub 30), read from the fake's one per-provider
      table and never retyped in the test;
    - a request above 100 is answered with 100 items, as the providers do;
    - with the `max_per_page` knob set below 100, pages shrink to it.
  - Kills M64. The maximum (100) is the providers' documented maximum, the
    same protocol constant as §10's `per_page=100`.
- **T11** tests/system/test_ci_templates.py::`test_docs_pr_job_opens_the_mr_before_gating_and_runs_no_prior_writer` · **CI-TEMPLATES**. RED.
  - rev 2: it replaces the `monitor` assertion at test_ci_templates.py:129-134.
    A new `_job_subcommands(path, job)` builds a per-job ORDERED subcommand list,
    and the test requires `should-sync` < `open-docs-pr` < `check`, with no
    `monitor` and no `sync-pr` in the docs-PR job.
  - ⟨R-CORRECTED⟩ This deliberately corrects G-03's pin. The module docstring
    "Nothing here executes CI" (:14) is updated to point at the exec module.
- **T12** `test_docs_pr_job_wires_token_before_sha_and_full_history`, split by concern. RED.
  - rev 2:
    - the GitLab header names the provider token;
    - the GitHub job `env:` maps it to `secrets.*`, and `CDMON_BEFORE_SHA` to
      `github.event.before`;
    - `fetch-depth: 0` and `GIT_DEPTH: "0"` are set.
  - rev 3: the skip condition literally compares against `SHOULD_SYNC_SKIP` and
    requires `RC -eq 1`.
  - **CI-TEMPLATES** rows: the provider-token names, derived per §5 until
    HC-FORGE; `fetch-depth: 0` replacing github adopter :58 today; and `GIT_DEPTH: "0"`.
  - **CI-GUARD** rows: `CDMON_BEFORE_SHA`, and the should-sync token and `RC`
    condition.
  - "Token parts" in the PLAN means the should-sync token (M48).
- **T12b** `test_docs_pr_job_runs_independently_of_the_gate_and_serialised`.
  - rev 3: GitLab `needs: []`, or no earlier-stage job that runs `check`;
    GitHub has no `needs` on `cdx-gate`; `resource_group`/`concurrency` are
    present; the GitLab adopter rule requires `$CI_PIPELINE_SOURCE == "push"`.
  - **CI-TEMPLATES** rows: `needs` and serialisation.
    - The GitHub `concurrency.group` is a literal with a comment (§3b, §8 F25).
    - The GitLab `resource_group` references `$CDX_DOCS_PR_RESOURCE_GROUP`.
  - **CI-GUARD** row: the push rule (M57). It is static. An executed row, if
    one is ever added, must use a source on which GitLab sets
    `CI_COMMIT_BRANCH` (`schedule`, `web`): on `merge_request_event` the
    branch half of the rule already excludes the job, so a kill there would be
    an artifact of a harness that set the branch (§5, §8 F43).
- **T12c** `test_gitlab_docs_jobs_install_git` · **CI-TEMPLATES**.
  - rev 3: every GitLab job that runs git, `should-sync` or `open-docs-pr` has the
    git bootstrap (the line or `$CDX_GIT_BOOTSTRAP`) before its first use, or a
    non-slim image. Today both use `python:3.11-slim` (adopter :33,
    .gitlab-ci.yml:56).
- **T92** tests/system/test_ci_templates.py::`test_docs_jobs_cache_the_configs_state_dir[gitlab, github, dogfood]` · **CI-TEMPLATES** (new; §8 F29). RED.
  - For each of the three docs jobs, the job's cached path is resolved: the
    GitLab `cache:paths` entry after `$CDX_STATE_DIR` expansion, and the GitHub
    cache steps' `with.path` after `${{ env.CDX_STATE_DIR }}`.
  - It must equal the state directory the product derives for that job's own
    `CDMON_CONFIG`: `cli._resolve_config(<CDMON_CONFIG>)[1] /
    monitor.DEFAULT_LOG_PATH.parent`, relative to the checkout (cli.py:211-230,
    monitor.py:50). The value is derived from code, never a typed literal.
    - adopter templates: `.cdmon` for the root `cdmon.yaml`;
    - dogfood: `config/cdmon/.cdmon`.
  - It also pins the save-on-failure half (GitLab `when: always`; GitHub
    `actions/cache/save` with `if: always()`).
  - Kills M59.
- **T59** `test_adopter_docs_pr_job_surfaces_the_closure_alarm` · **CI-TEMPLATES**. RED.
  - rev 2: with the declined-write shim, the job output contains
    `closure ALARM` and never `clean`; exit 1.
  - step 1: the exit 1 comes from the trailing `check`, because `open-docs-pr`
    exits 0 with the D2 line.
- **T60** `test_successive_push_supersedes_an_untouched_bot_mr` · **RTE-05**.
  - rev 2: jobs at B then C leave exactly ONE open MR (commit C). MR B is closed
    with a note naming MR C's URL, and MR C carries both changes.
  - **T60i** `test_successive_push_opens_another_stamped_mr[untouched, touched]` · **CI-TEMPLATES** (the PD-30 interim; a residue pin that RTE-05 flips into T60/T61).
    - Jobs at B then C leave 2 open MRs, each stamped with its own commit.
    - MR B is byte-identical: no note, no close, no push to its branch.
    - [touched]: the test first moves MR B's head. Exit 0 on both runs.
- **T61** `test_successive_push_is_blocked_by_human_commits_on_the_bot_mr` · **RTE-05**.
  - rev 2: with MR B's head moved, the job at C exits 1; stderr names MR B's URL
    and `human_commits`; no new branch; MR B still open.
  - Its step-1 interim is T60i[touched].
- **T62** `test_stale_rerun_never_supersedes_a_newer_mr` · **RTE-05**.
  - rev 2: BLOCKED(not_a_descendant). rev 3: STALE, exit 0, MR C untouched.
  - **T62i** · **CI-TEMPLATES**: after T60i's state, re-running the job at B gives
    UP_TO_DATE on MR B (rule 1, its own stamp). 0 writes, MR C untouched, exit 0.
- **T63** `test_monorepo_subdir_config_commits_toplevel_paths_and_skips_the_bot_merge` · **CI-TEMPLATES** (confirmed; deps CI-PATHS). RED.
  - rev 2: `mono_repo` with `CDMON_CONFIG=demo/config/cdmon`. The MR path is
    `demo/docs/api/core-api.md`, and the top-level `docs/api/core-api.md` is
    untouched. Committing the MR's files and then re-running gives SKIP.
- **T64** `test_before_sha_unknown_proceeds[gitlab_zero, github_zero, github_multi_commit]` · **CI-GUARD** (confirmed). RED.
  - rev 2: an all-zero before-sha proceeds and opens the MR. A GitHub two-commit
    push whose last commit is doc-only proceeds; today it is skipped
    (`HEAD~1` at github template :70).
  - step 1: `github_multi_commit` needs `CDMON_BEFORE_SHA` (CI-GUARD) and
    `fetch-depth: 0` (CI-TEMPLATES, W22).
  - step 1 adds **[gitlab_unset]** (F35). It is a DIRECT bash run
    (`bash -eo pipefail`) of the adopter template's guard item, taken from the
    parsed YAML, with `CI_COMMIT_BEFORE_SHA` absent from the env and a stub
    `.venv/bin/cdx` should-sync. It is not run through `gitlab_job`: the harness,
    like GitLab, always sets the variable.
    - HEAD is a doc-only commit on top of a code commit, and the block PROCEEDs.
    - This row alone kills M36b: re-introducing the `:-HEAD~1` default diffs the
      doc-only last commit and SKIPs.
  - Equivalent-watch for M36b: GitLab sets `CI_COMMIT_BEFORE_SHA` on every
    pipeline (all zeros when unknown). So M36b is equivalent on GitLab itself,
    and killable only by the direct block run, which models a custom runner that
    leaves the variable unset. The `:-` default is kept as the safe side of that
    case: an unknown range means PROCEED.
- **T65** `test_malformed_config_is_loud_never_skipped` · **CI-GUARD** (confirmed). RED (a green job today).
  - rev 2: should-sync exits 2, the job proceeds, and `open-docs-pr` prints
    `error:` and exits 1. "skipping" never appears.
- **T66** `test_missing_token_fails_before_the_heal` · **CI-TEMPLATES** (confirmed). RED.
  - rev 2: exit 1, 0 central records, 0 provider requests, docs byte-identical.
  - rev 3: the token is resolved before `find_open`. Step 1: via `from_env`
    before the heal (D3 step 6).
- **T67** tests/regression/test_ci_template_order.py::`test_ci_docs_pr_step_is_not_preempted_by_an_earlier_heal` · **CI-TEMPLATES**. RED.
  - rev 2: a thin executed re-assertion of T1. Break-it: put `monitor --apply`
    back before `open-docs-pr`.
- **T68** tests/regression/test_ci_template_order.py::`test_retry_and_successive_push_never_stack_docs_mrs` · **CI-TEMPLATES** (the retry half).
  - rev 2: a thin re-assertion of T6 and T60. Break-it: always OPEN.
  - step 1: the retry half only (T6). In step 1 successive pushes DO stack by
    design (T60i); that half is **RTE-05**. Break-it unchanged.
- **T70** · **RTE-05**. rev 3: `test_out_of_order_older_run_is_stale_not_red`.
- **T71** · **RTE-05**. rev 3: `test_revert_retires_the_obsolete_bot_mr[untouched, touched]`.
- **T72** `test_gitlab_adopter_pipeline_runs_the_docs_job_although_the_gate_fails` · **CI-TEMPLATES**. RED (the stages skip the docs job; adopter :28-30, :45-57).
  - rev 3: at B, `cdx-gate` FAILED (check rc=1) and `cdx-docs-pr` RAN and
    opened the MR.
  - step 1: it pins the template SHAPE only: `CDX_DOCS_PR_RESOURCE_GROUP` is
    declared with its default, and `resource_group` references it. Whether
    GitLab expands variables in `resource_group` cannot be verified offline
    (K4). It stays INFERRED (OD19, CI Risk 1) until the first live manual
    `docs:heal` (§8 F23).
- **T73** `test_pre_slice_job_order_now_opens_the_mr` · **CI-DELTA**. RED (a silent "clean").
  - rev 3: the pre-slice docs job script, kept verbatim as a test constant
    (adopter :59-82 at ddc368d), runs with the new CLI. The MR carries the healed
    doc (HEAD baseline); `open-docs-pr` adds 0 records; exit 0.
  - step 1: it lives in CI-DELTA's own `tests/system/test_pre_slice_job_order.py`,
    because CI-TEMPLATES creates the exec module a wave later. CI-DELTA gains
    the dependency CI-HARNESS (F36). The pre-slice template is written to
    `tmp_path` from the test constant, and needs only the W1 harness model.
- **T74** `test_job_without_git_is_loud_never_skipped[gitlab, dogfood]` · **CI-GUARD** (reassigned from CI-TEMPLATES; §8 F26). RED (today: "skipping", exit 0; reproduced by this pass).
  - rev 3: with `strip_git=True`: exit 1, `error:` names git, 0 records, 0
    provider requests. "skipping" never appears.
  - step 1: under today's guard a missing git gives an empty changed-file list:
    - `git diff … || true` yields nothing;
    - `should-sync` therefore exits 1;
    - the job prints "skipping" and exits 0.
    Only D10's block (a failing `git diff` means PROCEED) lets open-docs-pr
    reach `git_facts` and fail loudly. CI-TEMPLATES' T12c pins the bootstrap
    line statically, and T74 pins the executed behaviour.
- **T75** `test_harness_env_is_an_allowlist` · **CI-HARNESS** (a self-test).
  - rev 3: `os.environ` poisoned with CI_COMMIT_SHA, GITHUB_SHA, CI_API_V4_URL and
    CDMON_GITLAB_TOKEN.
  - Step 1 at W1 (CI-HARNESS): the harness job env carries none of them.
  - **T75[W22 half]** · **CI-TEMPLATES** (F36): with `os.environ` poisoned the
    same way, in CI-TEMPLATES' exec module, T3a[github]'s records still stamp
    the fixture HEAD, and T66 still fails before the heal.
- **T90** `test_monorepo_two_configs_open_one_mr_each` · **CI-TEMPLATES** (reassigned from CI-STAMP; §8 F5). RED.
  - rev 3: `mono2_repo`. One push touching both configs gives 2 MRs, one per
    config. A-only then B-only pushes leave both open, with no supersede of the
    other config.
  - step 1: CI-STAMP carries the unit form (T79).

### 6.6 Deliberate amendments to existing tests

These are ⟨R-CORRECTED⟩. Any other pre-existing failure is a K9 regression.

1. **CI-TEMPLATES:** test_ci_templates.py:129-134 (`monitor` pinned in the docs
   job) is replaced by T11, and the docstring at :14 is updated.
2. **CI-OPEN:** `test_open_docs_pr_submits_via_stubbed_gitlab_leaf` at
   test_cli.py:712-740 changes as follows:
   - set `CI_API_V4_URL` (it is deleted today at :722);
   - answer the list GET with `[]`;
   - assert **4** calls (list, branch, commit, MR), where :738 asserts 3 today.

   Rev 3's 5th call (the trailing converge list) and its commit
   `{"id": "c0ffee"}` requirement (bot_head) are **RTE-05**.
3. **HC-FORGE:** `test_surface_gaps_opens_issue_github` at test_cli.py:1183-1196
   sets `GITHUB_API_URL`. It relies on the `api.github.com` fallback today
   (issues.py:223).
4. **HC-PROVENANCE:** `test_monitor_no_ref_no_env_leaves_source_sha_none` at
   test_cli.py:900-912 clears every name in `ForgeConfig().commit_sha_env`
   (derived), not only `CI_COMMIT_SHA` (:907).
5. **CI-GUARD:** `test_should_sync_bad_config_clean_error` at
   test_cli.py:850-857 changes `exit_code == 1` (:855) to `== 2`. It still
   asserts `error:` and no traceback. Re-grep the suite for other `should-sync`
   exit pins first.

## 7. Mutation register

M1–M41 are the rev-2 mutants; M42–M58 are rev 3's; M59–M65 are this file's
(their killers cell reads "— (step 1, F…)"). M36 is split into M36a and M36b
(F35). The "Rev-2 / rev-3 killers" column keeps the spec's text verbatim, and a
letter split carries its parent's cell whole. Rev 3 carried M1–M41 over "with
the same killers" except M28, M30 and M35, which are noted in the column.

"Step-1 owner" and "Step-1 killers" apply the cut and the wave order. Each owner
kills its mutant first-hand, with a byte-level restore. "later" killers re-kill
it in later slices. Owners the PLAN already named are plain; the rest are
**bold** (§4).

| # | Mutation | Rev-2 / rev-3 killers | Step-1 owner | Step-1 killers |
|---|---|---|---|---|
| M1 | `monitor --apply` back before `open-docs-pr` (GitLab adopter, :78-79 today) | T1, T11, T67 | **CI-TEMPLATES** | T1, T11, T67 |
| M2 | the same in the GitHub template (:78-79) | T2, T11 | **CI-TEMPLATES** | T2, T11 |
| M3 | the same in `.gitlab-ci.yml` (:126-127) | T8, T11 | **CI-TEMPLATES** | T8, T11 |
| M4 | drop the trailing `cdx check` | T4, T9, T11 | **CI-TEMPLATES** | T4, T9, T11 |
| M5 | `cdx check` placed BEFORE `open-docs-pr` | T4, T9, T11 | **CI-TEMPLATES** | T4, T9, T11 (equivalent-watch: needs a pre-MR `check` that fails) |
| M6 | `open-docs-pr` always uses GitLab | T2, T37 | **CI-OPEN** | T37; later T2 |
| M7 | ignore the `--target`/`forge.default_branch` resolution | T38 | **X-FORGE-SITES** | T38 |
| M8a | drop `source_sha=` from `open-docs-pr`'s Monitor | T3, T18 | **CI-OPEN** | T18a; later T3a |
| M8b | drop `source_sha=` from `sync-pr`'s Monitor | T3, T18 | **HC-PROVENANCE** | T18 |
| M9 | drop `doc_style=` | T41 | **CI-OPEN** | T41 |
| M10 | `plan_docs_pr` ignores `sync.files` | T42 | **SYNC-HONEST** | T42 |
| M11 | capture `files` after the restore | T29, T42 | **SYNC-HONEST** | T29, T42 |
| M12 | the merge lift drops `forge`/`docs_pr` | T13 | **X-FORGE-CFG** | AF 18 restated, plus a `docs_pr.branch_prefix`-by-value row; later T13 |
| M13a | `docs_pr.branch_prefix` not threaded to the plan or `find_open` | T25, T39 | **CI-OPEN** | T39a |
| M13b | `title`/`labels`/`description_header` not threaded | T25, T39 | **HC-FORGE** | T25, T39b |
| M14 | `token_env` not threaded | T15, T40 | **HC-FORGE** | T15, T40 |
| M15 | a `from_env` default re-typed as a literal that differs | T16 | **HC-FORGE** | T16 |
| M16 | the shim tripwire removed, or the harness silently skips an unknown `${{ }}` | T10 | **CI-HARNESS** | T10 |
| M17 | drop the `html_url` fallback | T43 | **CI-OPEN** | T43 |
| M18 | drop `_echo_run` from `open-docs-pr` | T30, T59, T4 | **CI-OPEN** | T30; later T59, T4 |
| M19 | echo to stdout in `sync-pr` | T33 | **CI-OPEN** | T33 |
| M20 | "clean" printed regardless of remaining drift | T32, T59 | **CI-OPEN** | T32; later T59 |
| M21 | resolve the transport AFTER the heal | T34, T66 | **CI-OPEN** | T34; later T66 |
| M22 | resolve the transport before the detect-only check | T35 | **CI-OPEN** | T35 (equivalent-watch: a clean tree with no provider env) |
| M23 | drop NullSink under `--dry-run` | T36 | **CI-OPEN** | T36 |
| M24 | `api_url` falls back to a public host | T15, T21, T34 | **HC-FORGE** | T15, T21, T34[api_url_unset] |
| M25 | drop the repo prefix from plan paths | T48, T63 | **CI-PATHS** | T48; later T63 |
| M26 | `should_sync` ignores `repo_prefix` | T49, T63 | **CI-PATHS** | T49; later T63 |
| M27 | branch key over the patch even when the commit is known | T52, T6 | **CI-STAMP** | T52; later T6 (equivalent-watch: needs a non-deterministic writer or two plans with different text) |
| M28 | skip `find_open` / always OPEN | T6, T58, T60, T68 (rev 3 adds T5a, T73) | CI-STAMP | T58 (UP_TO_DATE row), T54 rule 1; later `test_open_docs_pr_retry_of_an_open_mr_is_up_to_date` (CI-OPEN), then T5a, T6, T62i, T68, T73 |
| M29 | `decide`: drop the HUMAN_COMMITS rule | T54, T61 | RTE-05 | (T54, T61; equivalent-watch: needs `head != bot_head`) |
| M30 | `decide`: drop the ancestry rule | T54, T62 (rev 3: T54, T61) | RTE-05 | (T54, T61, per rev 3) |
| M31 | `decide`: MULTIPLE_OPEN checked before UP_TO_DATE | T54 | RTE-05 | (T54; equivalent-watch: needs two open MRs, one matching) |
| M31′ | `decide` returns OPEN when `mine` is non-empty before trying rule 1, or takes only the FIRST of `mine` | T54 | **CI-STAMP** | T54 (2-MR row; equivalent-watch: needs two same-config MRs, one matching) |
| M32 | supersede closes BEFORE submitting | T58 | RTE-05 | (T58) |
| M33 | drop the GitHub labels call | T44, T39 | **GIT-TRANSPORT** | T44; later T39b |
| M34 | GitLab action always `update` | T45 | **GIT-TRANSPORT** | T45a |
| M35 | branch off the target instead of `base_sha` | T57, T1 (rev 3: T57, T1) | **GIT-TRANSPORT** | T57a; later T1 |
| M36a | revert the guard to today's lines (gitlab adopter :69-74): the `${CI_COMMIT_BEFORE_SHA:-HEAD~1}` default with the diff's failure swallowed, skipping on an empty list | T64 | **CI-GUARD** | T64[gitlab_zero], T74 (reproduced: today's line SKIPs on a zero before-sha and on a missing git; F35) |
| M36b | only re-introduce the `:-HEAD~1` default into the D10 block's `BEFORE=` | T64 | **CI-GUARD** | T64[gitlab_unset], a direct run of the guard block (equivalent-watch: EQUIVALENT on GitLab, which always sets the before-sha; it needs an UNSET before-sha plus a doc-only last commit, because the zero-sha and diff-failed branches intercept every other case, F35) |
| M37 | a `should-sync` error exits 1 | T50, T65 | **CI-GUARD** | T50, T65 |
| M38 | `make_sink` ignores `commit_env` | T19, T3 | **HC-PROVENANCE** | T19, T3b |
| M39 | the server route reads the cloned repo's `docs_pr` | T24 | **X-FORGE-CFG** | T24[docs_pr.branch_prefix], `test_every_config_field_is_classified` |
| M40 | drop the held list from the description | T51, T4 | **SYNC-HONEST** | T51; later T4 |
| M41a | GitHub template back to `fetch-depth: 2` | T64, T12 | **CI-TEMPLATES** | T12[depth] |
| M41b | GitHub guard back to `HEAD~1` | T64, T12 | **CI-GUARD** | T64 |
| M42 | drop `needs: []` from `cdx-docs-pr` | T72, T12b (rev 3) | CI-TEMPLATES | T72, T12b |
| M43 | drop `resource_group`/`concurrency` | T12b (rev 3) | **CI-TEMPLATES** | T12b |
| M44 | STALE → BLOCKED (drop rule 2) | T54, T62, T70 (rev 3) | RTE-05 | (T54, T62, T70; equivalent-watch: needs a clone that SEES the newer commit, T70's fetch order) |
| M45 | skip the post-write converge | T69 (rev 3) | RTE-05 | (T69) |
| M46 | `decide` ignores `stamp.config`, or the key omits the config | T54, T79, T90 (rev 3) | CI-STAMP | T54, T79; later T90 |
| M47 | `should-sync` catch narrowed to CodeDocMonitorError | T50, T80 (rev 3) | CI-GUARD | T50, T80 |
| M48 | the template SKIPs on RC=1 without the token | T12, T65 (rev 3) | CI-GUARD | T12[should-sync token], T65 |
| M49 | `git_facts` degrades to non-git when `.git` exists but git fails | T47, T74 (rev 3) | X-GITFACTS | T47; later T74 at CI-GUARD (equivalent-watch: `.git` present with git unusable) |
| M50 | the harness inherits `os.environ` | T75 (rev 3) | CI-HARNESS | T75 |
| M51 | the server route builds its Monitor from the clone's backend/central | T76, T91 (rev 3) | CI-TRUST | T76, T91 |
| M52 | drop `confine_clone` | T77, T91 (rev 3) | CI-TRUST | T77, T91 |
| M53 | drop the retire pass | T71, T89 (rev 3) | RTE-05 | (T71, T89; equivalent-watch: needs an untouched stamped strict ancestor of a clean HEAD) |
| M54 | `docs_delta` uses the snapshot although head is known | T73, T88, T5a (rev 3) | CI-DELTA | T73, T88; later T5a (equivalent-watch: docs modified by an EARLIER writer) |
| M55 | the advisory computed after the dry-run restore | T82 (rev 3) | CI-OPEN | T82 (equivalent-watch: `transitive: true` with a heal that changes the advisory) |
| M56 | close/note by global `id` instead of iid/number | T56 (rev 3) | RTE-05 | (T56) |
| M56′ | `find_open` maps `OpenDocsPr.number` from `id` | T56 (rev 3) | **CI-STAMP** | T55 (the stub sets `id ≠ iid`) |
| M57 | drop `$CI_PIPELINE_SOURCE == "push"` | T12b (rev 3) | CI-GUARD | T12b[push rule] |
| M58 | `register` always sends `default_branch` | T84 (rev 3) | X-FORGE-SITES | T84 |
| M59 | cache the checkout-root `.cdmon/` instead of `$CDX_STATE_DIR` (or a default that ignores the job's `CDMON_CONFIG`) | — (step 1, F29) | **CI-TEMPLATES** | T92[dogfood], T6[cache_hit_dir] |
| M60 | `plan_docs_pr` renders D11's section only when a stamp is given, or the server route builds `SyncResult` without `remaining` | — (step 1, F31) | **SYNC-HONEST** | T93[remaining] |
| M61 | `open_or_supersede` lets the leaf's TransportError through unchanged (no branch name, no remedy), or swallows it | — (step 1, F33) | **CI-STAMP** | T94 |
| M62 | `_echo_run` lifts cli.py:639-697 including `raise typer.Exit(code=1)` on remaining drift | — (step 1, F32) | **CI-OPEN** | T32 (held-only exits 0 with the D2 line); later T4, T59 |
| M63 | `find_open` requests page 1 only (no paging), or stops at a page shorter than the stub's but not shorter than `per_page` | — (step 1, F42) | **CI-STAMP** | T55[page2] |
| M64 | the fake forge caps `per_page` at the provider's default page size (GitLab 20, GitHub 30) instead of the providers' maximum (100) | — (step 1, F42) | **CI-HARNESS** | T95 |
| M65 | the harness restores the state directory from an earlier run when it meets `actions/cache/restore` or a GitLab `cache:` | — (step 1, F41) | **CI-HARNESS** | T10f[never_restores_github, never_restores_gitlab] |

## 8. Findings from the re-derivation

These are recorded for the owner slices' design reviews. None needs a user
decision.

- **F1. Recovery.** The rev-2 text existed only in the design-review transcript
  (§0). Rev 3's "as rev 2" references are now resolved here, together with the
  "as rev 2" fixtures (`tiered_adopter_repo`, `demo_repo`) and the harness text
  (`gitlab_job`), which the plan's list did not name.
- **F2. T38 and M7 belong to X-FORGE-SITES, not CI-OPEN.** X-FORGE-SITES (W16)
  already changes the `open-docs-pr --target` default (cli.py:798-802) to
  None-then-resolve. CI-OPEN (W18) only consumes it.
- **F3. T51 and M40 belong to SYNC-HONEST, not CI-GUARD.** T51 is D11, the MR
  description, and is the same test as SYNC-HONEST's
  `test_mr_lists_remaining_before_stamp`. The plan lists T51 under CI-GUARD's Red.
- **F4. T29 and M11 were claimed twice.** They sit inside CI-OPEN's "T28–T34"
  range and in SYNC-HONEST's design ("files and created paths are captured
  before the restore"; its header cites "CI hidden defect 3"). They go to
  SYNC-HONEST, and CI-OPEN's range becomes T28, T30–T34.
- **F5. T90 cannot pass at CI-STAMP (W13).** It executes jobs, and needs the CLI
  wiring (CI-OPEN, W18) and the reordered templates (CI-TEMPLATES, W22). It moves
  to CI-TEMPLATES; CI-STAMP keeps the unit form, T79.
- **F6. T3's GitHub-envelope half needs `forge.commit_sha_env`** (HC-PROVENANCE,
  W28). `make_sink` reads only `CI_COMMIT_SHA` (sinks.py:296). Split into T3a and
  T3b.
- **F7. T34's api_url_unset row needs HC-FORGE (W27).** Until then,
  `from_env` falls back to gitlab.com (pr.py:141).
- **F8. T39 and T40 need HC-FORGE's knobs.** T39 is split so the prefix row
  (T39a) kills M13a at CI-OPEN.
- **F9. The PLAN's "T12 (token parts)" means the should-sync token.** CI-GUARD
  owns M48 and T80. The provider-token rows stay with CI-TEMPLATES, and the
  T12b push-rule row goes to CI-GUARD, which owns M57.
- **F10. `FORGE_ENV_DEFAULTS` arrives only at W27.** CI-HARNESS (W1, which runs
  in this same wave) and CI-TEMPLATES (W22) derive the token NAMES from the
  `from_env` signature defaults (pr.py:123, :305). The `no_ci_env` fixture clears
  `CI_COMMIT_SHA` plus those names until HC-PROVENANCE/HC-FORGE re-derive them.
- **F11. R11-HELDONCE (W8) changes rerun records.** T5b and T6 pin parity with a
  `monitor` twin, not a fixed "re-recorded" count.
- **F12. The shim's write seams can move under later slices.**
  - Rev 2 put NONDET and DECLINE on `custodex.monitor.apply_fix` (monitor.py:33,
    :582, :666).
  - AF-1a (W4) extracts `render_fix` from `heal.apply_fix`, and the E4/HEAL
    slices change the write path.
  - Corrected in this revision (F30): the landed CI-HARNESS shim keeps BOTH
    NONDET and DECLINE on `monitor.apply_fix`. An earlier draft of this finding
    said NONDET had moved to `backends.MockBackend.propose`, narrowing the
    exposure to DECLINE. That was true of an in-progress copy only.
  - T10e makes a moved seam fail loudly, so T6 and T59 cannot pass vacuously.
    Both of its halves are required.
- **F13. A transient fail-open, W20–W22.** CI-PATHS adds a `git_facts` call to
  should-sync. A SyncError there exits 1, which the old template reads as SKIP,
  until CI-GUARD (W23). This is no regression: today `git diff … || true`
  already skips on a missing git, as reproduced for F26. It sits inside the
  do-not-deploy window. T49 pins the interim as `!= 0` plus `error:` (F27).
- **F14. Stamp forward-compatibility.**
  - Rev 3's `DocsPrStamp` already declares `bot_head: str | None = None`; the
    PLAN's step-1 field set dropped it.
  - With `extra="forbid"`, a step-1 reader would reject an RTE-05 stamp that
    carries `bot_head`. It would then treat that MR as unstamped, and a retry
    would open a duplicate.
  - So CI-STAMP keeps the field declared, always None in step 1 (§3a), and `v`
    stays 1.
  - `render_stamp` omits `bot_head` while it is None, so the step-1 marker
    carries exactly the four keys of §3 D7 (T53). `commit: null` is still
    rendered. `parse_stamp` accepts `bot_head` present or absent.
- **F15. Out of scope for T46:** the urllib leaves in issues.py (:71-112) and
  registry.py (:98-113) stay unwrapped. This is a follow-up; HC-FORGE is the
  natural home.
- **F16. The retire pass is deferred.** The step-1 clean path makes NO forge
  contact. T35 pins 0 requests, and rev-3 D3 step 5's
  `open docs MRs not checked` note is RTE-05's.
- **F17. `git_facts`' rule "a `.git` in any ancestor means a work tree" is
  sensitive to where tests run.** A pytest basetemp inside a work tree would flip
  the tmp_path CLI tests into git mode (prefix ≠ ""). X-GITFACTS or CI-PATHS
  should pin that tmp_path fixtures are outside a work tree, or scope the probe.
- **F18. demo/DEMOS.md:770-772 is false today.** Reproduced by this pass at
  ddc368d:
  - `echo "demo/docs/api/core-api.md" | cdx should-sync --config
    demo/config/cdmon` exits 0, where the doc says 1;
  - the root-relative `docs/api/core-api.md` exits 1.

  T49 (CI-PATHS) makes the documented command true.
- **F19. `remaining` rides on `SyncResult`, not on a `plan_docs_pr` kwarg.**
  - Rev 3 D3 step 9 passes `remaining=run.result.remaining` from cli.py.
  - SYNC-HONEST (W19) owns D11, but W19's DS-CORE owns cli.py, and CI-OPEN (W18)
    cannot pass a kwarg that does not exist yet.
  - So SYNC-HONEST adds `SyncResult.remaining: tuple[Drift, ...] = ()`, which
    `sync_pr_run` fills before any restore. `plan_docs_pr` renders "Needs a
    human" from `sync.remaining`.
  - The same field serves MCP `clean` (tools.py:1113) and the server summary
    (app.py:1884). Neither needs a second call.
  - The change is additive (K6), and the CLI path needs no edit.
- **F20. File sets the scheduler must widen:**
  - HC-FORGE and HC-PROVENANCE: `tests/system/test_cli.py`, for amendments #3
    and #4. The co-wave FPW-D and FPW-B do not touch it.
  - CI-GUARD: `.gitlab-ci.yml` and `templates/ci/README.md` (F26). The co-wave
    FPW-CFG-1 touches neither.
  - CI-TEMPLATES: `tests/_ci_exec.py`, `tests/_fake_forge.py`,
    `tests/_cdx_ci_shim.py` and `tests/system/test_ci_harness.py`, unless
    CI-HARNESS lands the §3b model first (F28, F51).
  - OPS-CLOSE: `tests/system/test_monitor_echo_golden.py`, T31's module (F49).
  - The alternative, a new module, cannot amend an existing test. Every other
    later-slice row goes in the later slice's own new module (F36).
- **F21. CI-TEMPLATES depends on SYNC-HONEST** (T4's "Needs a human" bullet,
  and M40's later killer), and that is missing from the plan. The wave order
  already satisfies it (W19 < W22). The scheduler should record it.
- **F22. CI-OPEN's K7 line ("UP_TO_DATE: 0 writes, 0 new records") only holds
  for 0 FORGE writes.**
  - A fresh-checkout retry re-heals before it decides (the ⟨R-REFUTED⟩
    short-circuit, §3 D3), so records are re-emitted. That is the pre-existing
    residue, pinned as twin parity.
  - "0 new records" holds only for the same-workspace rerun. Before CI-DELTA,
    that path prints `clean — nothing to open`.
  - The named test `test_open_docs_pr_retry_of_an_open_mr_is_up_to_date` (§6.3)
    pins both.
- **F23. T72 cannot verify OD19 offline.** Whether GitLab expands variables in
  `resource_group` is provider behaviour (K4 forbids the network). T72 pins the
  template shape, and the first live manual `docs:heal` settles OD19. If
  expansion is not supported, the fallback is the fixed name `cdx-docs-pr`,
  which serialises all branches.
- **F24. The state-directory cache must save on failure.**
  - The docs job exits 1 whenever drift remains, and a retry usually follows a
    red run. Both default cache policies save only on success: GitLab
    `cache:when: on_success`, and the post step of GitHub's `actions/cache`.
  - So the templates use `when: always`, and `actions/cache/save` with
    `if: always()` (§3b). Otherwise T6[cache_hit] models a state CI never
    produces.
  - A job-level `cache:` also replaces the global one in .gitlab-ci.yml
    (:58-61), so docs:heal lists both caches.
- **F25. The GitHub `concurrency.group` stays a literal with a comment.**
  - A job-level `concurrency` can read `github`, `inputs` and `vars`, but not
    `env:`.
  - The harness models `${{ }}` only in `env:`/`run:`, and checks
    `concurrency:` statically.
  - The group is adopter-edited, which matches the knob table's "adopter edits
    the template" row. The GitLab `resource_group` does take
    `$CDX_DOCS_PR_RESOURCE_GROUP`.
- **F26. T74 moves from CI-TEMPLATES to CI-GUARD, which then owns the whole D10
  guard.**
  - Reproduced by this pass, on examples/external-repo with a code commit and
    `git` removed from PATH: today's guard prints `git: command not found`, then
    "doc-only commit (bot heal) — skipping heal…", and exits 0.
  - With the rev-3 block, the same run prints "changed-file list unavailable …
    — proceeding" and reaches `open-docs-pr`.
  - So T74 can only pass once the guard changes. The guard is D10, the design
    CI-GUARD cites.
  - CI-TEMPLATES keeps today's guard lines while it reorders the job. CI-GUARD
    replaces them in all three jobs, and takes M36a/M36b (F35) and M49's
    executed half.
- **F27. T49 pins the interim should-sync exit loosely.** It pins `!= 0` plus
  `error:`, not an exact 1, so CI-GUARD (W23) needs no edit of CI-PATHS's
  module to flip it to 2. T50 pins the exact 2.

Findings F28–F38 come from round 1 of this file's review. Each was reproduced
first-hand, or checked mechanically, by the CI-SPEC premise check (see the
Dogfood section).

- **F28. The CI-HARNESS model refused the §3b shape.** Reproduced by writing the
  §3b GitLab and GitHub jobs to scratch and building them with CI-HARNESS's
  `tests/_ci_exec.py`:
  - GitLab: `NotModelled: … $CI_COMMIT_REF_SLUG is not defined for this job`.
    `CDX_STATE_CACHE_KEY` is a top-level variable, so every job in the
    template fails, the T72 pipeline included;
  - GitHub: `step 4: with: ${{ }} is only evaluated in env: and run:`;
  - with those expressions removed: `action 'actions/cache/restore@v4' is not
    modelled`;
  - a step-level `if:` is not a modelled step key either.

  F25 had cited the same limit to keep `concurrency.group` a literal, but §3b
  put `${{ }}` in `with:` anyway.
  - CI-HARNESS's round-1 fix modelled all of these but is not landed (F40).
    The model is therefore a requirement on CI-HARNESS's re-run: the cache
    actions record-only, with `with:` raw, and `CI_COMMIT_BEFORE_SHA` always
    set.
  - The premise check F28 asserts acceptance. It was red against the first
    model, and it is red against the in-flight round-1 copy, which still
    refuses the GitLab job key `resource_group` (§8 F48). Without a CI-HARNESS
    tree it is reported as deferred, and on a tree without the model it fails.
  - §3b and §5 describe the model this file relies on, and T10f pins it.
  - T6 seeds the product-derived state directory itself, and T92 ties the
    template to it. So nothing depends on the harness resolving cache paths.
  - If the round does not land, CI-TEMPLATES takes the model, with
    `tests/_ci_exec.py` and `tests/system/test_ci_harness.py` added to its file
    set (F20).
- **F29. The state directory is config_dir-relative, not the checkout root.**
  - The review log is `config_dir / DEFAULT_LOG_PATH` (monitor.py:50, :188), the
    resolutions log is `config_dir / DEFAULT_RESOLUTIONS_PATH` (monitor.py:196),
    and the code index is `config_dir / ".cdmon"` (cli.py:1509-1530).
  - `config_dir` is the directory itself for a dir config, else the file's
    parent (cli.py:211-230).
  - Reproduced: on a copy of demo/ with the `load_graph(..., *, strict=True)`
    change, `cdx monitor --apply --config demo/config/cdmon` run from the
    checkout root wrote `demo/config/cdmon/.cdmon/review-log.jsonl` and created
    no root `.cdmon/`.
  - So a cache of `.cdmon/` captured nothing for `.gitlab-ci.yml docs:heal`
    (`config/cdmon`), T63 (`demo/config/cdmon`) or T90 (`apps/a/.cdmon/`).
    GitLab only warns when a cache path matches nothing, so this would have been
    silent. T6[cache_hit] ran only on the root single-file fixture and could not
    catch it.
  - Fix: the knob `CDX_STATE_DIR`, whose default per template is that template's
    own state directory (§3b, §10). The pins are T92, derived from code, and
    T6[cache_hit_dir], a direct check that the log persisted.
  - The cwd-relative `central.outbox` default (sinks.py:303) stays under the
    root `.cdmon/`. It is inside the adopter default. For a subdirectory config
    it stays uncached, which is the existing outbox backlog item (§9).
- **F30. The CI-HARNESS shim wraps one write boundary for both fault models.**
  CI-HARNESS's round-1 `tests/_cdx_ci_shim.py` said so in its docstring: "Both
  fault models wrap the ONE write boundary, custodex.monitor.apply_fix". Its
  re-run must keep that (premise check G6).
  `_wrap_write_boundary` appends the salt after `original(doc_path, fix)`.
  F12's "narrows the exposure to DECLINE" was stale (it was written against an
  earlier copy) and is corrected. T10e's halves are required.
- **F31. F19 changes the server route's MR bytes when drift remains.**
  - app.py:1872-1879 calls `sync = sync_pr(monitor, …)`, then
    `open_docs_pr(sync, …)`. With `remaining` on `SyncResult` and D11 rendered
    from `sync.remaining`, the route's description (and the Python API's) gains
    the section.
  - In rev 3, `remaining` was a cli.py-only kwarg, so the route was unaffected.
  - The change is kept: an honest bot MR from the server is the point of D11.
    It is stated in D7, D11, §3a and §3d, and pinned by T93 (SYNC-HONEST, which
    owns app.py). Bytes are unchanged when nothing remains.
- **F32. The `_echo_run` lift range is cli.py:639-696, not :639-697.** Line 697
  is `raise typer.Exit(code=1)` inside `if result.remaining:` (:691-697), and
  :698 is `clean — no drift remaining`. A verbatim lift to :697 would stop
  `open-docs-pr` before steps 8-10. The MR would then never open under held
  drift, contradicting D2's exit-0 line, T32 and T59. Pinned by M62. F53
  narrows the lift inside that range.
- **F33. A partial submit left a permanently red retry that no K7 path
  covered.**
  - GitLab `submit` creates the branch first (pr.py:181-186), and GitHub creates
    the ref before the PR (pr.py:400-406).
  - With the commit key, every retry of that commit collides on the leftover
    branch until the next push or a manual delete. `find_open` sees only open
    MRs.
  - Under the legacy key, a deterministic writer already collided. A
    non-deterministic one escaped through a fresh key.
  - Step 1 accepts the residue as loud and bounded. The message names the
    branch and the remedy (§3c item 10, D8, T94, M61). Adoption of the branch
    is RTE-05's.
- **F34. The CI-OPEN K7 [non_git] row is a deterministic-writer pin.** With
  commit None, rule 1 can match only on `content_key`, which a non-deterministic
  writer changes. §1 and §3c item 2 are scoped to HEAD known. The residue is
  pinned by [non_git_salted], per the "pin a rationale only in ship shape"
  lesson.
- **F35. M36 as written was not killed by its step-1 killers.** Reproduced with
  a real git repo, a stub should-sync and `bash -eo pipefail` on the D10 block:
  - `BEFORE="${CI_COMMIT_BEFORE_SHA:-}"` and the mutated `:-HEAD~1` behave the
    same on a zero before-sha (both PROCEED via the zero check) and on a
    missing git (both PROCEED via the diff-failed branch).
  - Only an UNSET before-sha with a doc-only last commit tells them apart:
    PROCEED vs SKIP.
  - Today's whole line (`:-HEAD~1` with the diff failure swallowed) SKIPs on a
    zero sha and on a missing git.
  - So M36 is split. M36a is the whole-line revert, killed by T64[gitlab_zero]
    and T74. M36b is the default alone.
  - M36b is EQUIVALENT on GitLab itself: the variable is always set, and so is
    the harness's since CI-HARNESS's fix round. It is killable only by the new
    T64[gitlab_unset], a DIRECT bash run of the guard block with the variable
    absent, which models a custom runner.
  - The `:-` default is kept deliberately, because an unknown range must mean
    PROCEED. `premise_check.py` F35 re-runs this table on this file's own §3b
    block.
- **F36. Module ownership gaps are closed.**
  - T73 moves to CI-DELTA's own module, and CI-DELTA → CI-HARNESS is added.
  - T75's W22 half gets an owner (CI-TEMPLATES).
  - T3b and T18 go to HC-PROVENANCE's new `tests/system/test_provenance_cli.py`.
    T3a pins nothing about the GitHub envelope commit, and T18a has no
    GITHUB_SHA row.
  - T34[api_url_unset] lives only in HC-FORGE's `test_forge_cli.py`.
  - T14's branch and unknown-provider rows are marked as a split from the
    PLAN's HC-FORGE T14, not "(PLAN)".
  - The §4 rule is that no slice pins an interim row another slice must flip.
- **F37. The ARCHITECTURE RTE-05 line needs a reconciled amendment.**
  ARCHITECTURE.md:4209-4210 pins "`target_key`/`stamped_key` (heal- AND
  backend-invariant), `PRQuery.find_open`, the `SyncDecision` tri-state, `cdx
  inflight`". CI-STAMP's amendment must say which step-1 names supersede those
  (planning text §4), or two names for one concept stay pinned.
- **F38. The anchor claim is now mechanical and exact.**
  - Round 0 said every other anchor in §3–§7 was checked, but `cli.py:596-602`
    (D3 step 7) had no anchor_check row. It was correct (:596 opens
    `tiered: bool | None = typer.Option(`, :602 closes it), but unchecked.
  - `gap_check.py` K8 now requires every `file:N[-M]` citation in §1–§8 to be
    covered by an anchor_check row, including continuation refs such as
    `(cli.py:238, :629-633)`.
  - K9 does the same for every other bare `:N` ref. It resolves each one to the
    nearest file or template alias (`gitlab adopter :69-74`,
    `GitHub template (:78-79)`) earlier in its block. An unresolvable bare ref
    fails, so none is silently unchecked.
  - One residual: "covered" means some anchor row lies inside the cited range.
    A range misquoted onto a span that still contains another row passes. A
    single-line misquote does not. Round 2 narrows that residual: the gap
    check K11 also requires a backticked identifier near each citation to
    appear inside the cited range, against a reviewed list of the citations
    whose claim is a role rather than a literal (F47).

Findings F39–F47 come from round 2 of CI-SPEC. They fold in the CI-HARNESS
round-2 review where it touches this file, and the round-2 mutation gaps of
this file's own checkers.

- **F39. Provenance wording must outlive the session.** Round 1 dated two
  observations by wall-clock time of day and cited checker paths in session
  scratch that a host cleanup has since removed. Round 2 states what was
  observed, not when, and cites the checkers by role; the STATUS row records
  where they live and the command that re-runs them. The gap check K12 fails
  on a clock time or a session-scratch path in §1–§10.
- **F40. The CI-HARNESS model is a requirement until it lands.** It counts as
  landed only when the premise check F28 (with G6 and G7) passes with
  `--harness` on CI-HARNESS's landed tree. Holding `tests/_ci_exec.py`,
  `tests/_fake_forge.py`, `tests/_cdx_ci_shim.py` and
  `tests/system/test_ci_harness.py` is not enough (F48, F52). Every place this file described CI-HARNESS's model as landed
  (§3b, §5, F28, F30) now states it as a REQUIREMENT on that re-run, verified by
  the premise check (F28, G6, G7) with `--harness <tree>`. Without a tree the
  check reports those three as deferred and exits non-zero unless the deferral
  is explicit (`--harness-deferred`), so a missing harness is never reported as
  a pass.
- **F41. T10f's "never restores a cache" pin had no test.** The CI-HARNESS
  round-2 review found no test named `test_harness_models_the_state_cache_steps`,
  and no test for its last pin. T10f now spells that pin as two executed rows
  (a step or script line that fails if the state directory exists), kills the
  new M65 with them, and lets CI-HARNESS split the pins across tests as long
  as its STATUS row names the test for each.
- **F42. Short-page paging needs a fake that honours `per_page`.** D7's
  `find_open` stops at a page shorter than `per_page=100`, which is right on the
  real forges (100 is their maximum). The round-1 fake capped `per_page` at its
  default page size (20), so a correct product would stop after page 1 and miss
  MRs. T95 (CI-HARNESS) pins the fake; T55[page2, full_last_page] (CI-STAMP)
  pin the product; M63 and M64 are their mutants.
- **F43. Merge-request pipelines are half-modelled in the harness.** The
  CI-HARNESS round-2 review found that a provider variable the model does not
  set is treated as unset in `rules: if:` and in `${VAR:-…}` defaults, and that
  `CI_COMMIT_BRANCH` can be set on an MR pipeline (GitLab never does that).
  Impact here: the executed step-1 pipelines (T72, T73) are push pipelines and
  are unaffected; M57's killer is static (T12b[push rule]); an executed
  push-rule row must not use `merge_request_event` (§5, T12b). CI-TEMPLATES and
  CI-GUARD run pipelines only after CI-HARNESS's re-run refuses unmodelled
  provider names.
- **F44. Variable protection and non-push GitHub events are not modelled.** The
  §3b header's "invisible on unprotected branches" is GitLab behaviour that no
  step-1 test pins through the harness; a row that needs it passes
  `secrets={}`. GitHub events other than `push` are refused. No step-1 row
  depends on either (§5).
- **F45. One ARCHITECTURE heading for S1-CITPL.** Round 1 said "a new `###
  S1-CITPL` section"; CI-HARNESS proposed a top-level `## S1-CITPL — …` with a
  `### CI-HARNESS` subsection. ARCHITECTURE.md's existing convention is
  `## EPIC …` with `### <slice>` subsections, so §3a now names
  `## S1-CITPL — the docs-MR CI job (step 1)` with one `### <SLICE>` per owner.
  The orchestrator creates the `##` heading once, with the first owner that
  pins.
- **F46. T31 had no single owner.** Its §6 heading read "born by whichever of
  OPS-CLOSE (W17) and CI-OPEN (W18) lifts `_echo_run` first", while §4 says
  OPS-CLOSE (W17) lifts it first. The wave order decides it, so the owner is
  OPS-CLOSE, and CI-OPEN keeps the test byte-identical.
- **F47. Cited ranges must end on a cited line.** Five ranges ended on a
  blank line after a function: three in test_cli.py (the tests that start at
  its lines 712, 1183 and 1407) and the urllib leaves of issues.py and
  registry.py. Each is trimmed to the function's last non-blank line, and the
  anchor check now rejects a blank endpoint, so the trim is checked rather
  than counted by hand (two of the five end in two blank lines, not one).
- **F48. Premise G7 read the wrong field; F28's last refusal is real.** The
  harness premises were re-run against the in-flight CI-HARNESS copy:
  - G7 read `job.env`, but the harness keeps the modelled predefined variables
    on `CiJob.predefined`, for both platforms; `CiJob.env` holds only a
    GitHub workflow's and job's `env:`. The probe saw no value although the
    copy sets the zero sha. §3b and §5 now pin the field, and G7 reads it. On
    a copy that otherwise meets the model G7 passes, and it fails when the
    harness stops defaulting the before-sha to zeros, so the probe is not
    vacuous.
  - F28 still refuses the GitLab job key `resource_group`. That is a real gap
    in the in-flight copy, already on §5's requirement list, and F28 stays red
    until CI-HARNESS's re-run models the key.
  - With `resource_group` accepted on a copy, F28's probe next refused its own
    input: §3b's GitLab block is an excerpt without the template's `stages:`
    list, and the harness, like GitLab, refuses an undeclared stage. The probe
    now prepends the adopter template's own `stages:`, read from the template.
    On that copy F28, G6 and G7 all pass.
  - §5's `gitlab_job` bullet said `CI_COMMIT_BEFORE_SHA=before`. It now says
    all zeros when `before` is None, as §3b does.
- **F49. T31's birth signature used a later wave's type.** §3a pinned
  `_echo_run(result, advisory: Advisory, …)` for OPS-CLOSE (W17), but
  `Advisory` is CI-OPEN's type (W18, in syncpr), outside OPS-CLOSE's file set,
  so the birth could not compile. OPS-CLOSE now births
  `_echo_run(result, links, error, *, tiered)` from what `monitor` computes
  today, and CI-OPEN re-pins it to `(result, advisory, *, tiered,
  to_stderr=False)`, as the plan's rule that whichever of the two lands second
  re-pins T31 says. T31 gets its own module,
  `tests/system/test_monitor_echo_golden.py`, in OPS-CLOSE's file set. CI-OPEN
  should list OPS-CLOSE as a dependency (W17 < W18 already holds).
- **F50. The fake's default page size is per provider.** §5 and T95 said 20
  for both forges, but GitHub's default is 30. Both now name GitLab 20 and
  GitHub 30, read from one per-provider table in the fake that T95 reads,
  and M64 names both.
- **F51. The CI-TEMPLATES fallback file set was incomplete.** If CI-HARNESS's
  re-run does not land the model, CI-TEMPLATES also inherits T95
  (`tests/_fake_forge.py`, `max_per_page`) and the G6 fault models
  (`tests/_cdx_ci_shim.py`). §3b, §4, the dependency notes and F20 now list
  all four files.
- **F52. Another slice's progress is stated as a condition, not an
  observation.** §3b and F40 said what the CI-HARNESS worktree held at one
  moment, which went false when the in-flight copy appeared. Both now state
  the condition under which the model counts as landed: F28 passes on the
  landed tree. The gap check rejects the dated phrasing (K16) and ISO dates
  (K12).
- **F53. The echo lift leaves the advisory computation in `monitor`.** D2
  called the lift verbatim, the echo lines only, cli.py:639-696. That range
  holds the advisory computation (cli.py:677-682), that is the
  `docdeps.transitive` guard, `resolve_repo_root`, `propagate_suspect` and
  the `except`. Both
  `_echo_run` pins take the advisory as input, so lifting the range literally
  contradicts the signature. The lift is now cli.py:639-676 and
  cli.py:684-696, plus the `advisory unavailable` echo (cli.py:683), printed
  from the passed `error` at its old point. If `monitor` printed that error
  itself before the call, it would come before the closure ALARM lines on
  stderr and T31's per-stream bytes would change. The end of the range is
  F32's and is unchanged (M62).
- **F54. HC-013 splits between CI-TEMPLATES and CI-GUARD.** The HC-INVENTORY
  audit row HC-013 (`HEAD~1` diff base and `fetch-depth: 2`) gives both
  halves to CI-TEMPLATES, with the replacement "`CDMON_BEFORE_SHA` with full
  history". This file splits it:
  - the depth half (`GIT_DEPTH`/`fetch-depth: 0`) is CI-TEMPLATES's (§3b,
    §10);
  - the diff base, `HEAD~1` replaced by the before-sha with
    `CDMON_BEFORE_SHA` on GitHub, is CI-GUARD's, because it sits in the guard
    block CI-GUARD replaces (§3b, T12[should-sync token, CDMON_BEFORE_SHA],
    F26).

  HC-INVENTORY's next pass, or the scheduler, should amend the audit row to
  match, so HC-SWEEP and CI-TEMPLATES do not also add the mapping.
- **F55. Every template knob is bound to its §10 default.** §10 gave
  `CDX_GIT_BOOTSTRAP`'s default as "the guarded apt-get line", which nothing
  could compare with the value §3b declares. It now quotes the line. The gap
  check binds the two both ways:
  - K18b: every `CDX_*` variable §3b declares (GitLab `variables:`, the
    GitHub job `env:`, dogfood docs:heal) has a `template` row in §10 whose
    shipped default equals the declared value;
  - K10: the parsed GitLab job reads each knob through its variable
    (`resource_group`, the cache `key` and `paths`, the git line), and no
    knob's default appears as a literal anywhere else in the job.
- **F56. The checkers' location and command are recorded.** The Dogfood
  section said the STATUS row records where the CI-SPEC checkers live and
  how to re-run them, and the row did neither. The row now names the
  checkers' directory, as a labelled path outside the repo, and the exact
  chained command. The status check fails when the row lacks either, when
  its command omits a checker the Dogfood section names, or when it carries
  an absolute path. Also:
  - §0 gave the revision-3 spec as 1179 lines; it has 1096, and K7 now
    checks the count;
  - K12 also rejects day-month-year, month-day-year and slash dates;
  - K16 matches F40's and §3b's landing condition as one whole sentence, so
    a condition widened with a deferral fails;
  - G4b: a row that the finding a mutant's §7 row cites says could not
    catch it is never listed among that mutant's killers;
  - the deferred premise run is checked from outside: F28, G6 and G7 are
    reported on the DEFERRED line and never among the premises that hold.

## 9. Anchors re-grepped at ddc368d (CI Risk 10)

Rev-3 anchor → at ddc368d. The CI-SPEC checkers make this mechanical (they
live outside the repo; the STATUS row records where, and the command):
- the anchor check matches each of its frozen rows (file, line, expected
  text) against the worktree at ddc368d, and rejects a blank endpoint;
- the gap check's K8 and K9 require every `file:N[-M]` citation in
  §1–§8 to be covered by one of those rows, a continuation ref (`, :629-633`)
  and a bare template ref (`gitlab adopter :69-74`) included, and its K11
  requires a backticked identifier near each citation to sit inside the cited
  range, or the citation to be on its reviewed list.

Together they make the claim "every anchor in §1–§8 is checked" exact (F38).
This §9 table keeps the historical rev-3 numbers and is not itself scanned. The
PLAN's own line numbers predate step 0. For example:
- X-FORGE-SITES' "cli.py:796" is now :798-802;
- X-FORGE-CFG's `_settings_lines` "cli.py:3110" is :3109;
- HC-PROVENANCE's "cli.py:625/:1504/:2525" is :628/:1507/:2542;
- HC-FORGE's surface-gaps "cli.py:1650-1707" is :1647-1713.

| Rev 3 | Now | What |
|---|---|---|
| cli.py:819-821 | cli.py:822 (root), :824 (bare Monitor) | open-docs-pr root and Monitor |
| cli.py:828 | cli.py:831 | `tiered=cfg.apply_tiered` in open-docs-pr |
| cli.py:830-832 | cli.py:833-835 | "clean — nothing to open" |
| cli.py:844 | cli.py:847 | `GitLabTransport.from_env()` (GitLab-only) |
| cli.py:794-798 | cli.py:798-802 (literal at :799) | `--target` default "main" |
| — | cli.py:803-807 | open-docs-pr `--ref` (MR title/description only today) |
| — | cli.py:764-768 | should-sync: a load error exits 1 |
| — | cli.py:658-660 | the verified-closure echo (T4) |
| cli.py:720 | cli.py:726 | sync-pr's bare Monitor |
| cli.py:636-694 | cli.py:639-697 | the monitor echo block (handled, closures, advisory :677-690, remaining); the lift is :639-676 and :684-696 plus :683's echo, the computation :677-682 stays (F32, F53) |
| — | cli.py:697, :698 | monitor's remaining-drift exit and `clean — no drift remaining` (stay in `monitor`, F32) |
| — | cli.py:596-602 | monitor's `--tiered/--no-tiered` option (D3 step 7) |
| — | cli.py:211-230 | `_resolve_config`: config_dir = the dir, else the file's parent (F29) |
| — | monitor.py:50, :188, :196 | `DEFAULT_LOG_PATH`; review log and resolutions under `config_dir` (F29) |
| — | cli.py:1509-1530 | the code index under `config_dir / ".cdmon"` (F29) |
| — | server/app.py:1872-1879 | the route: `sync_pr`, then `open_docs_pr(sync, …)` (F31) |
| — | pr.py:181-186, :400-406 | branch/ref created before the MR/PR (F33) |
| cli.py:672-685 | cli.py:677-690 | the PROP-01 advisory |
| cli.py:688 | cli.py:697 | monitor exits 1 on remaining |
| cli.py:560-565 | cli.py:564-568 | `docdeps.gate` in check |
| cli.py:625, 1504, 2525 | cli.py:628, 1507, 2542 | `CI_COMMIT_SHA` reads |
| cli.py:771 | cli.py:771 | the should_sync caller (unchanged) |
| cli.py:1650-1707 | cli.py:1647-1713 | surface-gaps and `_issue_transport` |
| cli.py:952-956 | cli.py:955-957 | config sync `--default-branch` |
| cli.py:3096-3116 | cli.py:3109 | `_settings_lines` |
| cli.py:864 | cli.py:863-864 | register |
| pr.py:455-456 | pr.py:457-458 | `if not sync.patch: return None` |
| pr.py:459-461 | pr.py:459-461 | plan files read from disk (unchanged) |
| pr.py:181-186, :190 | pr.py:181-186, :189-192 | GitLab branch `ref=target`; the `update` action |
| pr.py:72-92, :248-270 | unchanged | urllib leaves |
| pr.py:123, :305 / :141, :324 | unchanged | token-env defaults / public-host fallbacks |
| pr.py:430, 445, 447, 448, 462 | unchanged | header, target, prefix, labels, title |
| syncpr.py:114-127 / :129-140 / :142-152 | :114-127 / :129-140 / :142-152 | snapshot / after / dry-run restore (unchanged) |
| syncpr.py:88-97 | unchanged | `_diff_one` `lineterm=""` (SYNCPR-PATCH-HDR, a non-goal) |
| sinks.py:296, registry.py:234 | unchanged | commit env |
| sinks.py:303/305 (outbox) | sinks.py:303 | the cwd-relative `.cdmon/outbox.jsonl` default (off-path backlog; examples/external-repo/cdmon.yaml sets `outbox:` explicitly) |
| issues.py:141, 204 | issues.py:142, 205 (public hosts :160, :223) | token-env defaults |
| gitfetch.py:70-71, configsync.py:388 | unchanged | Provider Literal; default branches |
| standalone.py:48/:107/:121/:137 | unchanged | `_DEFAULT_BRANCH` |
| server/app.py:1866-1870 | server/app.py:1869-1871 (route :1807) | the route's Monitor built from the clone |
| server/app.py:1884 | unchanged | the route summary |
| app.py:1725/1841/2067/2183 | unchanged | the `"main"` fallbacks |
| config.py:667; templates_v2.py:128-137; onboard.py:231-253 | config.py:667; templates_v2.py:136; onboard.py:244 | scaffolds (the `apply_tiered: false` lines) |
| mcp/tools.py:1074, :1108 | tools.py:1113 (`clean=`), :1089 (`sync_docs`) | :1074 is now the docstring |
| templates/ci/gitlab-ci.adopter.yml :28-30, :33, :45-57, :59-82, :70, :78-79 | unchanged | stages, image, gate, docs job, before-sha, writer order |
| templates/ci/github-actions.adopter.yml :52, :58, :70, :78-79 | unchanged | if, fetch-depth 2, HEAD~1, writer order |
| .gitlab-ci.yml :30-38, :56, :126-127 | unchanged (docs:heal :107-132) | header, image, writer order |
| test_cli.py:692, :712-742, :850-857, :900-912, :1183-1199, :1406 | :692-697, :700-709, :712-742 (:722 deletes CI_API_V4_URL, :738 asserts 3 calls), :850-857 (:855 exit 1), :900-912 (:907), :1183-1197, :1352, :1407-1445 | kept and amended tests; the closure and ALARM fixtures |
| test_ci_templates.py:14, :129-134 | unchanged | docstring; `monitor` pin |
| test_pr.py:80-86, :112-186, :369 | :80-110, :114-190, :369 | branch determinism; plan kwargs; GitHub 6-call |
| test_syncpr.py:145 | tests/integration/test_syncpr.py:145 | the K7 test (the module lives in integration/) |
| test_corpus_pipeline.py:367-386 | :366-386 | loop-safety corpus |
| demo/DEMOS.md:769-771 | :770-772 | the should-sync claim |
| SPEC.md:105-110, :126 | SPEC.md:105-107, :109, :126 | CLI table and flow |
| ARCHITECTURE.md:1749 | :1749-1750 | should-sync exits |
| ARCHITECTURE.md:4056-4057 | :4209-4210 | the RTE-05 line CI-STAMP amends: `find_open` and stamp rules 1/4 move into step 1, and the pinned names are superseded (F37; the text is in the CI-SPEC planning note) |
| README.md:140-143, :173-174, :396-397 | :140-141, :172-173, :396-397 | prose |
| examples/external-repo/README.md:22 | unchanged | prose |
| templates/ci/README.md:20-21 | :19-21 | prose |
| Dockerfile:21-25 | :21 (`FROM python:3.11-slim`), :23-25 (git install) | git on the same base image |

## 10. Knobs, and what is not a knob (the list HC-INVENTORY freezes)

**Adopter-tunable, with shipped defaults.** Every default reproduces today's
behaviour, except four deliberate changes (rev 3):
- (a) no public API host on any CLI path;
- (b) `GITHUB_SHA` joins the commit env;
- (c) the server route heals with server settings, never the clone's;
- (d) `register` sends a declared branch.

Engine knobs are declared on IndexFile and lifted onto MonitorConfig as the SAME
instance (the existing pattern). Server tunables live in config/settings.yaml.

| Knob | Shipped default | Override | Owner |
|---|---|---|---|
| `forge.provider` | `"gitlab"` (case-insensitive input) | `--provider` | X-FORGE-CFG; read by CI-OPEN, HC-FORGE |
| `forge.default_branch` | `"main"` | `--target`, `--default-branch` | X-FORGE-CFG; sites X-FORGE-SITES |
| `forge.api_url` | `None` ⇒ platform env ⇒ **loud** | — | HC-FORGE |
| `forge.project` | `None` ⇒ `$CI_PROJECT_ID` / `$GITHUB_REPOSITORY` | — | HC-FORGE |
| `forge.token_env` | `None` ⇒ `CDMON_GITLAB_TOKEN` / `CDMON_GITHUB_TOKEN` | — | HC-FORGE |
| `forge.commit_sha_env` | `("CI_COMMIT_SHA", "GITHUB_SHA")` | `--ref` / `--source-sha` | HC-PROVENANCE |
| `docs_pr.branch_prefix` | `"cdmon/docs-sync"` | Python-API kwarg | X-FORGE-CFG; threaded by CI-OPEN |
| `docs_pr.title` | `"docs: sync"` | — | HC-FORGE |
| `docs_pr.labels` | `()` | Python-API kwarg | HC-FORGE (the GitHub call is GIT-TRANSPORT's) |
| `docs_pr.description_header` | ``"Automated docs sync opened by `cdx` (bot-generated)."`` | — | HC-FORGE |
| `server.git.default_branch` | `"main"` (env `CDMON_GIT_DEFAULT_BRANCH`) | — | X-FORGE-CFG; sites X-FORGE-SITES |
| `server.git.docs_pr` | `DocsPrConfig()` | — | HC-FORGE |
| `server.git.docs_pr_backend` | `BackendConfig()`, mock only in step 1 | — | CI-TRUST |
| `server.git.docs_pr_agent` | `AgentConfig()` | — | CI-TRUST |
| `FORGE_ENV_DEFAULTS` | the §3 D4 table | via `forge.*` | HC-FORGE |
| template `CDX_GIT_BOOTSTRAP` | `apt-get update -qq && apt-get install -y -qq --no-install-recommends git`; the job runs it only when git is missing | CI/CD variable | CI-TEMPLATES |
| template `CDX_DOCS_PR_RESOURCE_GROUP` | `cdx-docs-pr` | CI/CD variable | CI-TEMPLATES |
| template `CDX_STATE_CACHE_KEY` | `cdx-state-$CI_COMMIT_REF_SLUG` | CI/CD variable | CI-TEMPLATES |
| template `CDX_STATE_DIR` | the template's own `<config dir>/.cdmon`: `.cdmon` (adopter templates, root `cdmon.yaml`), `config/cdmon/.cdmon` (dogfood `docs:heal`) | CI/CD variable / job `env:` | CI-TEMPLATES (F29) |
| template `GIT_DEPTH` / `fetch-depth` | `"0"` / `0` | adopter edits the template | CI-TEMPLATES |
| GitHub `concurrency.group`, `rules`/`if:` | as in §3b | adopter edits the template (F25) | CI-TEMPLATES, CI-GUARD |

**Not tunable** (protocol constants):
- the provider REST paths and `per_page=100` (both providers' documented
  maximum; T55 and T95 pin it, §8 F42);
- the 12-hex digest and the `\x00` separator;
- the stamp marker `cdx-docs-pr` and its `v: 1`;
- the `should-sync` tokens `proceed`/`skip`;
- the MR body section labels (`Changed documents:`,
  `Needs a human before merge:`);
- the 512-byte HTTP error excerpt;
- the should-sync exit codes 0, 1 and 2.

`cdmon/` (the branch-prefix default) and the `CDMON_*` env names are kept
cdmon-era convention names (CLAUDE.md).

## Dogfood

This file carries no code and no tracked module, so no reheal is needed. `cdx
check` over the 4 configs is unaffected. The file is `.project/` planning.

**Keeping this file true.** The CI-SPEC checkers live outside the repo. The
S1-CITPL STATUS row names their directory, as a labelled path, and the exact
chained command; an owner slice re-runs that command after a rebase, with
`--harness <CI-HARNESS tree>` once CI-HARNESS lands (F40, F56). The status
check fails if the row loses either. The checkers:
- `coverage_check.py` checks that every required T and M carries rev-2 text and
  an owner, and every added item (T92–T95, M59–M65) an owner and a killer.
- `anchor_check.py` checks each anchor row against the tree.
- `gap_check.py` K1–K21 checks:
  - the killers column is verbatim, per row;
  - each base M id has its own row;
  - §4, §6 and §7 owners agree, both ways;
  - each rev-2 test name and number is present;
  - the recovery hash and char count, and the rev-3 hash and line count
    (K7, F56);
  - every cited anchor is covered (K8, K9);
  - §3b's parsed GitLab shape and the D2/§10 text hold, and the job reads
    every knob through its variable with no default as a literal (K10, F53,
    F55); every `CDX_*` variable §3b declares equals its §10 default
    (K18b, F55);
  - a backticked identifier near each citation is inside the cited range,
    or the citation is on the reviewed list (K11);
  - no clock time, date in any of four forms or session-scratch path (K12,
    F39, F52, F56);
  - T10f's never-restores rows, T95 and the fake's per-provider `per_page`
    requirement, and every construct of the §3b shape on §5's requirement
    list (K13, F41, F42, F50), and T55's paging rows (K14, F42);
  - the ARCHITECTURE heading (K15, F45); the CI-HARNESS model stated as a
    requirement and a condition, never as landed or dated, the condition as
    one whole sentence with no deferral, and the three model limits and
    their direction (K16, F40, F43, F44, F52, F56);
  - every "Kills M<n>" in §6 mirrored in M<n>'s §7 killers (K17); every
    cited `forge.*`, `docs_pr.*` and `server.git.*` field on §10 (K18);
  - T31's owner (K4) and its two `_echo_run` pins, the OPS-CLOSE one free of
    CI-OPEN types, with T31's module named (K19, F49); the complete
    CI-TEMPLATES fallback file set (K20, F51); the HC-013 split (K21, F54);
  - the round-2 text gaps: the [non_git_salted] residue (G3) and every §7
    step-1 killer resolving to a §6 item, and a named row to a whole row
    token of that item (G4), and never one that §8 says cannot catch it
    (G4b, F56).
- `premise_check.py` re-runs the first-hand premises:
  - F18: the DEMOS.md should-sync exits;
  - F26: today's guards skip silently without git;
  - F29: the state directory is under the config dir;
  - F35: the M36a/M36b split, on this file's own D10 block;
  - F28: the harness accepts the §3b shape, given CI-HARNESS's `_ci_exec.py`
    (the first model refused it), with G6 (both fault models wrap
    `monitor.apply_fix`) and G7 (`before=None` gives the zero sha on `CiJob.predefined`, F48). Without a
    CI-HARNESS tree these three are reported as deferred (F40);
  - G1: the §3b D10 block proceeds when should-sync exits 1 without the `skip`
    token; G2: every `CDX_STATE_DIR` default equals the state dir the product
    derives for that job's `CDMON_CONFIG`; G5: M36b's named T64 rows tell the
    §3b block from M36b when executed;
  - the three exclusivity claims (T43, T45a, F6).
- `deferred_contract.py` runs the premise check with `--harness-deferred` and
  fails unless F28, G6 and G7 are on the DEFERRED line and absent from the
  premises that hold (F40, F56).
- `status_check.py` checks the STATUS row text: the labelled checker
  directory, a command naming every checker above, and no absolute path
  (F56).
