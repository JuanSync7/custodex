# Contributing to taskflow

Thanks for your interest in `taskflow`! This is a small, well-tested library;
contributions that keep it small and well-tested are very welcome.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Before you open a pull request

Run the full local gate — the same checks CI runs (`.github/workflows/ci.yml`):

```bash
ruff format --check .
ruff check .
pytest
```

## Keep the docs in sync

This repo is monitored by [custodex](https://example.com/cdmon): the
API docs under `docs/` carry managed `CDM:BEGIN/END` regions that mirror the
public code surface. If you change a public signature, regenerate the regions
before committing:

```bash
python -m custodex.cli check          # is anything out of sync?
python -m custodex.cli monitor --apply # heal the managed regions
```

A pull request that drifts a documented symbol without healing its region will
fail the `docs` job in CI.

## Commit style

- One logical change per commit.
- Present-tense, imperative subject lines (`add scheduler helper`, not
  `added ...`).
- Reference the affected module in the body when it helps a reviewer.
