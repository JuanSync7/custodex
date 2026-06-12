# Changelog

All notable changes to `taskflow` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `core/scheduler.py` — `priority_order`, a name-sorted ready-set helper.

## [0.3.0] - 2026-06-07

### Added
- `io/report.py` — `render_report`, a plain-text per-status status table.
- `io/storage.py` — `save_graph` / `load_graph` JSON round-trip persistence.

### Changed
- `Engine.run` now cascades `FAILED` to every transitive dependent of a failed
  task instead of stopping at the first failure.

## [0.2.0] - 2026-05-20

### Added
- `core/engine.py` — `Engine.topological_order` (Kahn) and `Engine.run`.
- `CycleError`, carrying the unresolved task ids when a cycle is detected.

## [0.1.0] - 2026-05-02

### Added
- Initial domain model: `Status`, `Task`, `TaskGraph`.
