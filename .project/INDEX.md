# custodex — project index

A standardized, reusable code→documentation drift monitor with LLM
auto-remediation and human-reviewable audit logging.

## Specs
- [SPEC.md](spec/SPEC.md) — purpose, concepts, functional requirements, CLI, acceptance.
- [CONSTRAINTS.md](spec/CONSTRAINTS.md) — binding rules K0–K10.
- [ARCHITECTURE.md](spec/ARCHITECTURE.md) — module boundaries + exact signatures.

## Slices (vertical, each TDD with a validable goal)

| slice | module(s) | validable goal |
|-------|-----------|----------------|
| CDM-00 | bootstrap | skeleton + venv + tooling green; smoke test passes |
| CDM-01 | errors, config, cli(init) | load yaml/json config into models; `cdx init` writes a template; bad config raises ConfigError |
| CDM-02 | extract | per-document audience-aware surface from AST + sub-file selection; stable hash; user-guide ignores comments/privates |
| CDM-03 | manifest, blocks, drift, heal | detect MISSING/HASH/REGION/UNHEALABLE drift audience-correctly; regenerate regions idempotently |
| CDM-04 | schema, reviewlog, sinks | ReviewRecord + JSON schema; append/read JSONL; file/null sink offline |
| CDM-05 | backends | mock/claude-code/api behind one factory + shared prompt; FIX/INVALIDATE/ESCALATE; subprocess+HTTP injected/mocked |
| CDM-06 | monitor, cli | end-to-end orchestration detect→verdict→record→apply→recheck; full CLI |
| CDM-07 | tests, docs, dogfood | system tests on a fixture repo; dogfood own config; ≥90% cov; README + schema doc |

## Dependency order
CDM-00 → CDM-01 → CDM-02 → CDM-03 → CDM-04 → CDM-05 → CDM-06 → CDM-07
(CDM-04 may proceed in parallel with CDM-02/03 — it only depends on CDM-01.)

See [STATUS.md](STATUS.md) for the live board and [LESSON_LEARNT.md](LESSON_LEARNT.md).
