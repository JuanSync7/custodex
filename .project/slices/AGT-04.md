# Slice AGT-04 — `onboard.py`: the config-authoring onboarding agent

> Provenance note: the contract was pinned in `ARCHITECTURE.md` §EPIC AGT
> BEFORE implementation (the process rule); this slice file was committed as a
> 1-line probe by the session-limit-killed subagent and replaced with the real
> spec during the PR #20 review fixes. The goals below are the ones the
> implementation was built and tested against.

The adoption-friction killer: point `cdx onboard` at ANY repo and get a
complete, arrive-green `config/cdmon/` — a deterministic plan (K10) the human
reviews before anything is written (K11), then an apply step that scaffolds,
heals (mock backend, offline) and SELF-VALIDATES.

## Goal (validable)

On a synthetic adopter repo (two top-level packages, a README, one unparseable
source file, loose scripts):
1. `analyze_repo` yields a RepoMap: per-package file/symbol counts (the broken
   file WARNS, never aborts), doc candidates with audience guesses THAT CARRY
   EVIDENCE, repo signals (README/AGENTS.md/CLAUDE.md/docs/existing config —
   AGENTS.md/CLAUDE.md are signals, never doc candidates), loose-file warnings;
2. `propose_config` is deterministic: one unit per top-level package (REAL
   `UnitFile` models via `dump_unit_file` — fresh files may model-dump; the
   AGT-02 splice rule is for hand-maintained files), one eng-guide doc per
   package, README as a user-guide narrative doc, owner precedence
   `--owner` → git `user.name` (injected seam) → `"unassigned"` + note,
   reserved stems (`index`/`ignore`/`doc-style`) skipped with a note;
3. default run is a DRY-RUN: prints the Renovate-style plan, writes NOTHING;
4. `--apply` writes the bundle + ignore/doc-style + writing templates,
   scaffolds each proposed doc in-sync, heals, and self-validates (load →
   doctor no-FAIL → 0 drift) or exits loudly — **the very next `cdx check`
   AND `cdx index --check` exit 0 on the onboarded repo (arrive-green e2e)**;
5. `--apply` refuses a non-empty config dir without `--force` (K8);
6. the `init --v2` DOA fix: `ensure_writing_templates(repo_root)` materializes
   the four doc-style-referenced writing templates when absent (never
   overwrites, idempotent K7; ONE `WRITING_TEMPLATE_STEMS` constant so the map
   and the files cannot drift), called by BOTH `scaffold_config_dir` and
   `apply_plan` — regression-guarded by scaffold-then-`load_bundle` in an
   EMPTY tmp tree.

## In scope

**New `custodex/onboard.py`** (pure core): `DocCandidate` / `PackageCandidate`
/ `RepoMap` / `OnboardPlan`; `analyze_repo(root)`; `propose_config(repo_map, *,
repo, owner)`; `apply_plan(plan, config_dir)`; `render_plan_text(plan)`.

**`custodex/templates_v2.py`** — `WRITING_TEMPLATE_STEMS` +
`ensure_writing_templates(repo_root)` (write-if-absent).

**`custodex/cli.py`** — `cdx onboard [--path][--repo][--owner][--apply]
[--force]`; `_git_user_name(root)` module seam (monkeypatched in tests so the
pure core never reads git).

## DoD bundle

- `feature-doc/catalog/onboard.yaml` (FEAT-ONBOARD-001/002) + DEMO-104/105.
- coverage.waive for `custodex/onboard.py`; wiki regen; trace green.
- cli.py is tracked → dogfood reheal + README quickstart LEADS with onboard.
- Full gate (ruff/mypy/pytest ≥90 branch) + all cdx gates exit 0.

## Test plan

- unit (`test_onboard.py`): analyze resilience (broken file → warning),
  audience evidence, owner precedence chain, reserved-stem skip, plan
  determinism (double-run equality), refuse-non-empty, template ensure
  idempotency + never-overwrite.
- system (`test_onboard_cli.py`): dry-run writes nothing; apply → arrive-green
  e2e (`cdx check` + `cdx index --check` exit 0); `init --v2` DOA regression
  (scaffold → `load_bundle` in an empty tree).

## Out of scope

Language detection beyond the extractor registry, multi-root monorepo layouts,
LLM-assisted audience classification (the plan is deterministic; a model may
CONSUME it later), frontend (AGT-07).
