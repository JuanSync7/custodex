# HC-AUDIT: hard-coded values in custodex/ and templates/ci/

This is the frozen inventory (slice HC-INVENTORY) of every adopter-tunable
literal that the W0 sweep found in `custodex/**/*.py` and `templates/ci/*.yml`
at base commit ddc368d. A literal the sweep missed is added as a late row (see
the end of this file).
Each row names the slice that turns the literal into a config knob, or is a
`keep` row with the reason it is not a knob (a protocol constant, a kept
convention, a security bound, or a per-invocation flag).

The rule it serves (CONSTRAINTS.md K0): an install-time or tunable value comes
from config, never from a literal in code. A default declared as a field of a
config model (`MonitorConfig`, `IndexFile`, `Settings`, `SpMirrorConfig`) is the
sanctioned shipped default and is not a row; a code default that restates one
is a row.

How to read it:

- Line numbers in `sites` are as of the base commit of the row's freeze batch
  (`FROZEN_BATCHES` in `tests/smoke/test_hc_audit.py`; ddc368d for HC-001 to
  HC-076). That test reads each cited line at the base with `git show` and
  requires every cited site to hold one of the backticked spans of the row's
  `literal` cell, so code moving on never breaks a row. It also pins every
  frozen cell by a digest, so a frozen row cannot change unreviewed.
- Rows are frozen (critique M7). A frozen owner never gains a row: a newly
  found literal becomes a `keep` row or a fresh one-row `HC-<TOPIC>` slice.
- Knob names are the YAML path an adopter writes, in one of three homes:
  `server.*` keys in config/settings.yaml (the hub), `spmirror.*` keys in
  config/spmirror.yaml, and every other key in the repo config (config/cdmon
  or cdmon.yaml). Upper-case names are CI template variables. A value the hub
  needs to find a repo config (such as its path) cannot live in that config,
  so it is a kept convention or a `server.*` key, never a repo-config knob.
- Section names are this inventory's choice (the plan lets HC-INVENTORY name
  them): `learning.*` groups the exemplar, similarity and promotion knobs
  (HC-003, HC-004, HC-037), in place of the plan's illustrative
  `monitor.exemplar_top_n`. It awaits the user's ratification before
  HC-SWEEP-ENGINE builds on it.
- Classified against the not-a-knob lists of the step-1 specs: AF
  S1-APPLYFIX :664-678, CI S1-CITPL :883-889, FPW S1-FPWAVE :979-991, DS
  S1-DEADSEL :808-817, R11 S1-RULE11 :419-434.
- Plan overrides applied: PD-33 (FIX_SELECTOR severity moves to server
  settings, overriding the DS list), O13 (X-TPLROOT owns templates/writing,
  overriding DS), PD-7 (branch literals), PD-40 (new timeouts default to None,
  today's behaviour), PD-41 (the rules path is a CLI option).
- Kept convention names are never rows to rename: `config/cdmon/`,
  `cdmon.yaml`, `.cdmon/`, `cdmon-config-version` and the `CDMON_*` env prefix.
- Owners with no literal to replace own no row: HC-SCAFFOLD (W37) re-renders
  the scaffolds, DOCTOR-PING adds a new timeout knob, D06-STORE adds new keys.

## Owners

| owner | status | note |
| --- | --- | --- |
| HC-SWEEP-SERVER | scheduled W36 | server.workers severities and the central HTTP timeout (PD-33, PD-40) |
| HC-SWEEP-ENGINE | scheduled W35 | exemplar top-N, similarity weights, coverage-issue labels |
| REC-RECIPE | scheduled W6 | single-sources the default model id (critique M6) |
| X-FORGE-CFG | scheduled W12 | forge.provider, forge.default_branch, docs_pr.branch_prefix |
| X-TPLROOT | scheduled W13 | writing_templates_root at all 5 sites (O13) |
| X-FORGE-SITES | scheduled W16 | every branch literal reads the resolved default branch (PD-7) |
| CI-OPEN | scheduled W18 | open-docs-pr --provider dispatch |
| CI-TEMPLATES | scheduled W22 | template job order, history and git bootstrap variables |
| FPW-CFG-1 | scheduled W23 | extraction length limits |
| HC-FORGE | scheduled W27 | forge env names, API URL, docs_pr text and labels, surface-gaps provider |
| HC-PROVENANCE | scheduled W28 | forge.commit_sha_env |
| REL-0.2.0 | scheduled W39 | CUSTODEX_SPEC install pin in both templates |
| DEFER-COVLANG | deferred | language maps follow register_extractor (BL NEW-COV-LANG items 1-2) |
| HC-FORGE-TIMEOUT | new XS | timeouts for every forge HTTP call, CLI and hub |
| HC-BACKEND | new XS | API backend URL, token budget, key env and local model name |
| HC-SINGLE-SOURCE | new XS | code defaults that restate a config-model default |
| HC-PROMO-MIN | new XS | the rule-promotion threshold |
| HC-ENTITIES | new XS | the PATH-universe walk and path-suffix set |
| HC-WORKLIST-SEVERITY | new XS | the worklist status-to-severity maps |
| HC-ISSUE-TEXT | new XS | the coverage-gap issue title and body header |
| HC-DOCS-ROOT | new XS | the docs directory that write-doc creates a new doc in |

## Rows

| id | literal | sites | owner | knob or keep reason |
| --- | --- | --- | --- | --- |
| HC-001 | `_SEVERITY` map from suggestion kind to work severity | `custodex/workers.py:85-91` | HC-SWEEP-SERVER | `server.workers.severities` (PD-33: FIX_SELECTOR is HIGH here, overriding DS :808-817) |
| HC-002 | `urlopen(req)` with no timeout on the central registry and sink calls | `custodex/registry.py:111`, `custodex/sinks.py:148` | HC-SWEEP-SERVER | `central.http_timeout_seconds` (default None, today's behaviour, PD-40) |
| HC-003 | `DEFAULT_EXEMPLAR_TOP_N = 3` and `top_n: int = 3` | `custodex/monitor.py:53`, `custodex/similar.py:72` | HC-SWEEP-ENGINE | `learning.exemplar_top_n` |
| HC-004 | `FEATURE_WEIGHTS` similarity weights | `custodex/similar.py:36-41` | HC-SWEEP-ENGINE | `learning.similarity_weights` (default: today's values) |
| HC-005 | `_DEFAULT_LABELS: tuple[str, ...] = ("documentation",)` on coverage-gap issues | `custodex/issues.py:43` | HC-SWEEP-ENGINE | `coverage.issue_labels` |
| HC-006 | `claude-sonnet-4-20250514` default model id, duplicated | `custodex/backends.py:68`, `custodex/agent/runtime.py:36` | REC-RECIPE | `backend.model` and `agent.model` fall back to one declared default |
| HC-007 | `branch_prefix: str = "cdmon/docs-sync"` | `custodex/pr.py:447` | X-FORGE-CFG | `docs_pr.branch_prefix` |
| HC-008 | `"templates" / "writing"` writing-templates root | `custodex/config.py:1278`, `custodex/generate.py:323`, `custodex/monitor.py:252`, `custodex/templates_v2.py:287`, `custodex/server/app.py:748` | X-TPLROOT | `writing_templates_root` (O13 overrides DS's templates/writing entry) |
| HC-009 | `"main"` default branch in the engine and the CLI | `custodex/pr.py:50`, `custodex/pr.py:445`, `custodex/configsync.py:388`, `custodex/cli.py:799`, `custodex/cli.py:956` | X-FORGE-SITES | `forge.default_branch` via resolve_default_branch (PD-7) |
| HC-010 | `"main"` default branch on the hub | `custodex/server/app.py:1725`, `custodex/server/app.py:1841`, `custodex/server/app.py:2067`, `custodex/server/app.py:2183`, `custodex/server/standalone.py:48`, `custodex/gitfetch.py:71` | X-FORGE-SITES | `server.git.default_branch` (PD-7) |
| HC-011 | `GitLabTransport.from_env()` in open-docs-pr, GitLab only | `custodex/cli.py:847` | CI-OPEN | `forge.provider`, overridable by `--provider` |
| HC-012 | `cdx monitor --apply` in the docs job | `templates/ci/gitlab-ci.adopter.yml:78`, `templates/ci/github-actions.adopter.yml:78` | CI-TEMPLATES | removed; open-docs-pr is the sole writer and applies per `apply_tiered` |
| HC-013 | `HEAD~1` diff base and `fetch-depth: 2` | `templates/ci/gitlab-ci.adopter.yml:70`, `templates/ci/github-actions.adopter.yml:58`, `templates/ci/github-actions.adopter.yml:70` | CI-TEMPLATES | `CDMON_BEFORE_SHA` with full history (`GIT_DEPTH` / `fetch-depth` 0) |
| HC-014 | `python:3.11-slim` docs image without git | `templates/ci/gitlab-ci.adopter.yml:33` | CI-TEMPLATES | `CDX_GIT_BOOTSTRAP` (OD18) |
| HC-015 | `_MAX_VALUE_LEN = 48` | `custodex/extract.py:466` | FPW-CFG-1 | `extraction.max_value_len` |
| HC-016 | `max_len` of 80 in `_const_str` | `custodex/extract.py:982` | FPW-CFG-1 | `extraction.max_record_value_len` |
| HC-017 | `CI_PROJECT_ID`, `CDMON_GITLAB_TOKEN`, `CI_API_V4_URL`, `GITHUB_REPOSITORY`, `CDMON_GITHUB_TOKEN`, `GITHUB_API_URL` env names | `custodex/pr.py:122-124`, `custodex/pr.py:304-306`, `custodex/issues.py:141-143`, `custodex/issues.py:204-206` | HC-FORGE | `forge.project`, `forge.token_env`, `forge.api_url` (FORGE_ENV_DEFAULTS) |
| HC-018 | `https://gitlab.com/api/v4` and `https://api.github.com` public-API fallbacks | `custodex/pr.py:110`, `custodex/pr.py:141`, `custodex/pr.py:291`, `custodex/pr.py:324`, `custodex/issues.py:129`, `custodex/issues.py:160`, `custodex/issues.py:192`, `custodex/issues.py:223` | HC-FORGE | `forge.api_url` (None means the platform env var, else loud; no public host) |
| HC-019 | `Automated docs sync opened by` MR body header | `custodex/pr.py:427-437` | HC-FORGE | `docs_pr.description_header` |
| HC-020 | `"docs: sync"` MR title | `custodex/pr.py:462` | HC-FORGE | `docs_pr.title` |
| HC-021 | `labels: tuple[str, ...] = ()` on the docs MR | `custodex/pr.py:448` | HC-FORGE | `docs_pr.labels` |
| HC-022 | `"gitlab"` surface-gaps `--provider` default | `custodex/cli.py:1657` | HC-FORGE | `forge.provider` |
| HC-023 | `Literal["github", "gitlab"]` provider vocabulary, duplicated | `custodex/sinks.py:76`, `custodex/gitfetch.py:70` | HC-FORGE | one `Provider` alias, the vocabulary of `forge.provider` |
| HC-024 | `CI_COMMIT_SHA` commit env name | `custodex/sinks.py:296`, `custodex/registry.py:234`, `custodex/cli.py:628`, `custodex/cli.py:1507`, `custodex/cli.py:2542` | HC-PROVENANCE | `forge.commit_sha_env` (default CI_COMMIT_SHA, GITHUB_SHA) |
| HC-025 | `pip install custodex` unpinned install | `templates/ci/gitlab-ci.adopter.yml:43`, `templates/ci/github-actions.adopter.yml:43`, `templates/ci/github-actions.adopter.yml:62` | REL-0.2.0 | `CUSTODEX_SPEC` (custodex~=0.2.0) |
| HC-026 | `_LANGUAGE_BY_EXT`, `_SUFFIX_LANG`, `_SYMBOL_LANG_BY_SUFFIX` language maps | `custodex/inventory.py:70`, `custodex/extract.py:761`, `custodex/extract.py:955` | DEFER-COVLANG | derived from `register_extractor` registrations, not a config key |
| HC-027 | `urlopen(req)` with no timeout on forge calls, and hub transports built without one (`from_repo(remote_url, token or "")`) | `custodex/pr.py:90`, `custodex/pr.py:268`, `custodex/issues.py:86`, `custodex/issues.py:110`, `custodex/gitauth.py:73`, `custodex/server/app.py:1048-1056` | HC-FORGE-TIMEOUT | `forge.http_timeout_seconds` (CLI) and `server.git.http_timeout_seconds` (hub), default None |
| HC-028 | `https://api.anthropic.com/v1/messages` API URL; the agent api driver ignores `base_url` (`_anthropic_messages_call(model, prompt, cfg.timeout_s, api_key)`) | `custodex/backends.py:646`, `custodex/agent/runtime.py:116-119` | HC-BACKEND | `backend.base_url`, and honour `agent.base_url` |
| HC-029 | `"max_tokens": 1024` | `custodex/backends.py:641` | HC-BACKEND | `backend.max_tokens` |
| HC-030 | `ANTHROPIC_API_KEY` key env on the API backend and in doctor | `custodex/backends.py:678`, `custodex/doctor.py:102` | HC-BACKEND | `backend.api_key_env` (the agent already has `agent.api_key_env`) |
| HC-031 | `"local-model"` model name for the agent local driver | `custodex/agent/runtime.py:129` | HC-BACKEND | `agent.model` must be set for the local driver, else loud |
| HC-032 | `timeout_s: int = 120` restating the backend timeout | `custodex/backends.py:589`, `custodex/backends.py:679` | HC-SINGLE-SOURCE | `backend.timeout_s` (read the model default, do not restate it) |
| HC-033 | `timeout: int = 120` restating the spmirror timeout | `custodex/spmirror.py:203` | HC-SINGLE-SOURCE | `spmirror.timeout_seconds` |
| HC-034 | `{"github.com", "gitlab.com"}` restating the hub host allowlist | `custodex/server/app.py:766` | HC-SINGLE-SOURCE | `server.git.allowed_hosts` |
| HC-035 | `max_retries: int = 2` restating the central retry count | `custodex/sinks.py:178` | HC-SINGLE-SOURCE | `central.max_retries` |
| HC-036 | `baseline: str = "body"` restating the docdeps baseline | `custodex/docdeps.py:129` | HC-SINGLE-SOURCE | `docdeps.baseline` (stays body) |
| HC-037 | `min_count: int = 3` rule-promotion threshold, restated by the CLI (`min_count: int = typer.Option(`) | `custodex/promotion.py:95`, `custodex/cli.py:1233-1234` | HC-PROMO-MIN | `learning.promotion_min_count` (the hub and the worker use the code default today) |
| HC-038 | `_SKIP_DIRS` walk exclusions and `_KNOWN_SUFFIXES` path suffixes | `custodex/entities.py:82`, `custodex/entities.py:85` | HC-ENTITIES | `entities.skip_dirs` and `entities.path_suffixes` |
| HC-039 | `_ORPHAN_SEVERITY`, `_STALE_SEVERITY`, `_SUSPECT_SEVERITY` status-to-severity maps | `custodex/worklist.py:87-98` | HC-WORKLIST-SEVERITY | `worklist.severities` |
| HC-040 | `"config" / "cdmon"` and `"config", "cdmon"` hub per-repo config path | `custodex/server/app.py:667`, `custodex/server/app.py:863`, `custodex/server/app.py:1868`, `custodex/server/app.py:1870` | keep | kept convention: the hub finds each repo's config at config/cdmon, as the CLI does (HC-054), so it cannot read that path from the config it is looking for; single-file cdmon.yaml repos are skipped today, a feature gap for its own ticket, not a knob |
| HC-041 | `_JWT_TTL_SECONDS = 540`, `_JWT_BACKDATE_SECONDS = 60` | `custodex/gitauth.py:42-43` | keep | GitHub App protocol: the JWT lifetime must stay under GitHub's 10-minute cap, with skew backdating |
| HC-042 | `_PROVIDER_USERS` token usernames | `custodex/gitfetch.py:55` | keep | provider protocol: the HTTPS username each forge requires for a token clone |
| HC-043 | API base derived from the remote host in `from_repo` (`else f"https://{host}/api/v4"`, `else f"https://{host}/api/v3"`) | `custodex/pr.py:163-167`, `custodex/pr.py:347-351` | keep | provider protocol: the API path convention for the remote's own host, not a public fallback |
| HC-044 | `"anthropic-version": "2023-06-01"` header | `custodex/backends.py:651` | keep | API protocol version the request body is written against; changing it changes the code |
| HC-045 | `["claude", "-p"]` default CLI argv | `custodex/backends.py:599`, `custodex/agent/runtime.py:42` | keep | the claude CLI grammar; `backend.command` and `agent.command` already override it |
| HC-046 | `_PROMPT_TOKEN = "{prompt}"` | `custodex/backends.py:71` | keep | placeholder grammar of `backend.command`; a vocabulary, not a tunable value |
| HC-047 | `api_url` default `https://api.github.com` for an App installation | `custodex/gitauth.py:124`, `custodex/gitauth.py:201` | keep | the sealed credential carries its own api_url; this is the protocol default for github.com Apps |
| HC-048 | `_SEVERITY_RANK`, `_REASON_RANK`, `_SUGGESTION_SEVERITY_RANK` rank maps | `custodex/worklist.py:81-82`, `custodex/workers.py:292`, `custodex/server/store.py:283` | keep | deterministic sort order of a closed vocabulary (K10), not a policy value |
| HC-049 | MCP result caps 50, 20, 2000, 20000 (`_DEFAULT_LIST_CAP = 50`, `limit: int = 50`, `limit: int = 20`) | `custodex/mcp/tools.py:103-111`, `custodex/mcp/server.py:97`, `custodex/mcp/server.py:113`, `custodex/mcp/server.py:154`, `custodex/mcp/server.py:188`, `custodex/mcp/server.py:208` | keep | tool-contract bounds; the per-call `limit` argument is the lever (server.py restating tools.py is a follow-up) |
| HC-050 | `_IGNORED_FILES_CAP = 200` | `custodex/server/app.py:88` | keep | response-size bound on a diagnostic list; the full count is still reported |
| HC-051 | `WIKI_SECTIONS` and the `feature-doc` root of the hub's own wiki | `custodex/server/app.py:140-145`, `custodex/server/app.py:158` | keep | the EPIC R layout of custodex's own shipped wiki, not an adopter value |
| HC-052 | `thread.join(timeout=5)` on shutdown | `custodex/server/app.py:1006` | keep | a bounded shutdown wait for an in-process worker thread; no adopter behaviour depends on it |
| HC-053 | `CDMON_ALLOWED_GIT_HOSTS`, `CDMON_ADMIN_TOKEN`, `CDMON_DATABASE_URL`, `CDMON_SP_API` env names | `custodex/server/app.py:767`, `custodex/server/app.py:944`, `custodex/server/app.py:2284`, `custodex/spmirror.py:636` | keep | kept convention: the CDMON_* environment prefix (CLAUDE.md naming) |
| HC-054 | `config/cdmon` and `cdmon.yaml` config auto-detection (`Path("config") / "cdmon"`, `"config" / "cdmon"`) | `custodex/cli.py:178`, `custodex/cli.py:227`, `custodex/cli.py:278`, `custodex/cli.py:320`, `custodex/cli.py:399`, `custodex/cli.py:464`, `custodex/cli.py:1005`, `custodex/cli.py:1063`, `custodex/cli.py:2135` | keep | kept convention: the config/cdmon directory and cdmon.yaml file names; `--config` overrides them |
| HC-055 | `.cdmon/` runtime state paths (`Path(".cdmon")`) | `custodex/monitor.py:50`, `custodex/reviewlog.py:35`, `custodex/cli.py:1288`, `custodex/spmirror.py:81` | keep | kept convention: the .cdmon/ runtime state directory (PD-41: the rules path is a CLI option) |
| HC-056 | CLI option defaults `local`, `127.0.0.1`, `depends`, `eng-guide`, `all` | `custodex/cli.py:930`, `custodex/cli.py:1032`, `custodex/cli.py:1968`, `custodex/cli.py:2211`, `custodex/cli.py:2683` | keep | per-invocation flag defaults: the flag is the knob, and a loopback bind is the safe default |
| HC-057 | CLI path defaults `Path("feature-doc") / "catalog"`, `Path("tests")`, `Path("demo")`, `Path("config/settings.yaml")` | `custodex/cli.py:2958`, `custodex/cli.py:2963`, `custodex/cli.py:2968`, `custodex/cli.py:3141` | keep | per-invocation path flags; the flag is the knob and the default names the documented layout |
| HC-058 | `timeout=10` on the `git config user.name` probe | `custodex/cli.py:2069` | keep | a guard on a local subprocess probe; it never touches the network |
| HC-059 | `_MAX_RESPONSE_BYTES` 128 MiB and `_MAX_PART_BYTES` 64 MiB | `custodex/spmirror.py:87`, `custodex/spmirror.py:313` | keep | security bounds against a hostile service; `spmirror` max_bytes is the adopter filter |
| HC-060 | `DEFAULT_SPMIRROR_PATH = Path("config") / "spmirror.yaml"` | `custodex/spmirror.py:80` | keep | the documented config location, the same kept convention as config/cdmon; a flag overrides it |
| HC-061 | `_SKIP_DIRS` and `"docs"` in onboarding | `custodex/onboard.py:60`, `custodex/onboard.py:215` | keep | a pre-config probe: onboarding runs before any config exists, so it cannot read one |
| HC-062 | `indent: int = 2` and `depth: int = 1` | `custodex/docwriter.py:161`, `custodex/kgraph.py:301` | keep | a YAML rendering detail and a Python-API argument default; neither changes adopter behaviour |
| HC-063 | `DEFAULT_INCLUDE` and `DEFAULT_EXCLUDE` scan scope | `custodex/inventory.py:60-64` | keep | already the `coverage.include` / `coverage.exclude` model defaults, kept in lock-step by a test |
| HC-064 | `_DEFAULT_SUFFIXES`, `_CATALOG_DIR`, `_PKG_DIR` trace and wiki layout | `custodex/traceability.py:53`, `custodex/wiki.py:44-47` | keep | the EPIC R layout of custodex's own feature catalog, not an adopter value |
| HC-065 | `CDMON_CONFIG_VERSION = "2.0.0"` | `custodex/_v2base.py:36` | keep | a config-format fact (the cdmon-config-version key), not a tunable |
| HC-066 | `CONFIG_TEMPLATE`, `UNIT_TEMPLATE`, `INDEX_TEMPLATE`, `_INDEX_BODY` scaffolds | `custodex/config.py:667`, `custodex/templates_v2.py:60`, `custodex/templates_v2.py:112`, `custodex/onboard.py:233` | keep | scaffold text an adopter edits after generation; HC-SCAFFOLD (W37) renders it from the models |
| HC-067 | `CDMON_CONFIG` template variable defaulting to `cdmon.yaml` | `templates/ci/gitlab-ci.adopter.yml:37`, `templates/ci/github-actions.adopter.yml:31` | keep | already a template variable the adopter overrides per repo (CI :879, adopter edits the template) |
| HC-068 | Python `3.11` image and `python-version` | `templates/ci/github-actions.adopter.yml:40`, `templates/ci/github-actions.adopter.yml:61` | keep | adopter edits the template (CI :879); the runtime version is the adopter's choice |
| HC-069 | `--ref "$CI_COMMIT_SHA"` and `--ref "$GITHUB_SHA"` | `templates/ci/gitlab-ci.adopter.yml:78-79`, `templates/ci/github-actions.adopter.yml:78-79` | keep | the platform's own commit variable, passed explicitly so provenance never reads a hidden env |
| HC-070 | `CDMON_CENTRAL_TOKEN` secret name | `templates/ci/github-actions.adopter.yml:54` | keep | kept convention: the CDMON_* environment prefix (CLAUDE.md naming) |
| HC-071 | `title = f"docs: {n} undocumented public symbol` coverage-gap issue title | `custodex/issues.py:283` | HC-ISSUE-TEXT | `coverage.issue_title` |
| HC-072 | `Automated coverage report opened by` coverage-gap issue body header | `custodex/issues.py:252-256` | HC-ISSUE-TEXT | `coverage.issue_header` |
| HC-073 | `path=f"docs/{final_id}.md"` new-doc path in write-doc | `custodex/cli.py:2251` | HC-DOCS-ROOT | `docs_root` (the directory new docs are created in) |
| HC-074 | `path=f"docs/{doc_id}.md"` doc paths in onboarding | `custodex/onboard.py:299` | keep | a pre-config probe: onboarding writes the first config, so it cannot read one |
| HC-075 | `"--depth=1"` shallow hub clone | `custodex/gitfetch.py:107` | keep | the hub reads one snapshot of the default branch and never walks history |
| HC-076 | inline `<style>` sheet of the built HTML preview | `custodex/build.py:210-235` | keep | presentation of a generated preview page, not adopter behaviour |

## Changing this file

- A frozen row changes only with a reviewed update of its batch digest in
  `FROZEN_BATCHES`, and a frozen owner's roster entry only with a reviewed
  update of `FROZEN_ROSTER` or `FROZEN_ROSTER_NOTES_SHA256`, all in
  `tests/smoke/test_hc_audit.py` and visible in that file's diff.
- A newly found literal is appended after the last row with the next id
  (HC-NNN, no gap). It is either a `keep` row with a reason, or the only row of
  a new `HC-<TOPIC>` owner that is added to the roster as `new XS`. It never
  joins an existing owner.
- A late row quotes its literal in backticks and cites lines that each hold one
  of those spans in the working tree; the lint checks it.
- Freeze a late row in the same change: `test_every_row_is_frozen` fails and
  prints the `Batch(...)` to append to `FROZEN_BATCHES` (its base is the
  current HEAD, whose lines the row cites) and the `FROZEN_ROSTER` entry for a
  new owner. From then on the row is checked at its base commit, so its owner
  landing and removing the literal never breaks it.
- Rows sit at column 0 inside the one `## Rows` table. Never indent a row,
  split the table with a blank line, or hide text in an HTML comment.
- When an owner slice lands, change its roster status to `done`; its rows stay.
  The lint accepts only a frozen owner's pinned status or `done`.
