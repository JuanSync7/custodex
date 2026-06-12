# Adopter CI templates

Drop-in CI for repos ADOPTING code-doc-monitor (`cdmon`). Pick the one for your
platform, copy it into your repo, and adjust the install line + config path.

| File | Platform | Copy to |
|------|----------|---------|
| `gitlab-ci.adopter.yml` | GitLab CI/CD | `.gitlab-ci.yml` (or `include:` it) |
| `github-actions.adopter.yml` | GitHub Actions | `.github/workflows/cdmon.yml` |

Both ship the same two jobs:

- **`cdmon-gate`** — runs on every MR/PR and branch/push. Offline (no network, no
  LLM). It runs `cdmon doctor` (preflight wiring), then `cdmon check` (content
  drift, detect-only) and `cdmon lint` (the Document Layout Standard). Any of the
  three failing fails the pipeline, so doc drift never lands silently.

- **`cdmon-docs-pr`** — runs on a push to the **default branch**. It heals the
  docs and opens a docs MR/PR (`cdmon open-docs-pr`), GUARDED by
  `cdmon should-sync`: the push's changed-file list (`git diff --name-only`) is
  piped to `should-sync`, which exits non-zero (SKIP) when every changed file is a
  managed doc path — the bot's own doc-only commit — so the heal does NOT
  re-trigger and open another MR/PR. Provenance is stamped with `--ref` so each
  review record's `source_sha` matches the MR/PR.

## Adopting in three steps

1. **Scaffold a config.** `cdmon init --central <central-url> --repo-id <your/id>`
   writes a `cdmon.yaml` with a `central:` HTTP-reporting block. Map your code →
   docs in it (see `examples/external-repo/cdmon.yaml` for a worked example).
2. **Wire CI.** Copy the template for your platform.
3. **Set the central token as a CI SECRET.** The central server checks a per-repo
   bearer token (E-06). Store it as `CDMON_CENTRAL_TOKEN`:
   - GitLab: a **protected + masked** CI/CD variable.
   - GitHub: a repository **secret** (referenced via `${{ secrets.CDMON_CENTRAL_TOKEN }}`).

   NEVER commit the token. The central URL and `repo_id` live in the committed
   `cdmon.yaml`; only the token is a secret. Run `cdmon register` once (the docs-PR
   job does this) to announce the repo, after which `cdmon monitor` reports its
   review records to the central server.

> The templates reference only real `cdmon` subcommands — a test in this repo
> (`tests/system/test_ci_templates.py`) parses every script line and fails if a
> template ever names a command the CLI does not expose, so they cannot drift out
> of date.
