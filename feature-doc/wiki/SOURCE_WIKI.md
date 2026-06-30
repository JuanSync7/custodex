# custodex — source wiki

Generated from the package inventory crossed against the golden catalog — **do not hand-edit**. Run `cdx wiki` (R-08) to regenerate.

**46 public modules**, 0 without a catalogued feature.

## `_v2base`

- Path: `_v2base.py`
- Public symbols: `CDMON_CONFIG_VERSION`, `__all__`
- Implemented by: `FEAT-CONFIGV2-010`

## `agent`

- Path: `agent/__init__.py`
- Public symbols: `AgentBackend`, `Artifact`, `Driver`, `PACKAGED_PROMPTS_DIR`, `PromptLibrary`, `RemediationState`, `__all__`, `build_graph`, `make_agent_backend`, `render_context`, `resolve_driver`, `select_artifacts`
- Implemented by: `FEAT-AGENT-001`, `FEAT-AGENT-002`, `FEAT-AGENT-003`, `FEAT-AGENT-004`, `FEAT-AGENT-005`, `FEAT-AGENT-006`, `FEAT-AGENT-007`, `FEAT-AGENT-008`

## `backends`

- Path: `backends.py`
- Public symbols: `ApiBackend`, `ApiClient`, `Backend`, `BackendResult`, `ClaudeCodeBackend`, `FixRequest`, `MockBackend`, `ProcessRunner`, `__all__`, `build_prompt`, `make_backend`, `parse_backend_json`
- Implemented by: `FEAT-BACKENDS-001`, `FEAT-BACKENDS-002`, `FEAT-BACKENDS-003`, `FEAT-BACKENDS-004`, `FEAT-BACKENDS-005`, `FEAT-BACKENDS-006`, `FEAT-BACKENDS-007`, `FEAT-BACKENDS-008`

## `blocks`

- Path: `blocks.py`
- Public symbols: `REGION_KEYS`, `__all__`, `expected_region`, `known_region_ids`, `render_template`, `symbol_table`
- Implemented by: `FEAT-HEAL-002`, `FEAT-HEAL-003`

## `build`

- Path: `build.py`
- Public symbols: `__all__`, `build`, `render_markdown`
- Implemented by: `FEAT-LAYOUT-008`, `FEAT-LAYOUT-009`

## `cli`

- Path: `cli.py`
- Public symbols: `app`, `build`, `check`, `coverage`, `deps`, `doctor`, `index`, `init`, `lint`, `main`, `monitor`, `new_doc`, `open_docs_pr_cmd`, `ownership`, `promotions`, `register`, `report`, `resolve`, `rpt`, `schema`, `serve`, `settings`, `should_sync_cmd`, `staleness`, `surface`, `surface_gaps`, `sync`, `sync_pr_cmd`, `trace`, `wiki`
- Implemented by: `FEAT-CLI-001`, `FEAT-CLI-002`, `FEAT-CLI-003`, `FEAT-CLI-004`, `FEAT-CLI-005`, `FEAT-CLI-006`, `FEAT-CLI-007`, `FEAT-CLI-008`, `FEAT-CLI-009`, `FEAT-CLI-010`, `FEAT-CLI-011`, `FEAT-CLI-012`, `FEAT-CLI-013`, `FEAT-CLI-014`, `FEAT-CLI-015`, `FEAT-CLI-016`, `FEAT-CLI-017`, `FEAT-CLI-018`, `FEAT-CLI-019`, `FEAT-CLI-020`, `FEAT-CLI-021`, `FEAT-CLI-022`, `FEAT-DOCDEPS-005`, `FEAT-OWNERSHIP-004`, `FEAT-SETTINGS-008`, `FEAT-STALENESS-004`

## `config`

- Path: `config.py`
- Public symbols: `AgentConfig`, `Audience`, `BackendConfig`, `CONFIG_TEMPLATE`, `CentralConfig`, `CodeRef`, `ConfigBundle`, `ContextRef`, `CoverageConfig`, `DEFAULT_CENTRAL_TOKEN_ENV`, `DocDepsConfig`, `DocEdge`, `DocEdgeType`, `DocumentSpec`, `IgnoreFile`, `IgnoreFrontmatter`, `IndexFile`, `IndexFrontmatter`, `IndexUnitRef`, `MonitorConfig`, `RESERVED_UNIT_STEMS`, `RegionColumn`, `RegionMode`, `RegionTemplate`, `StalenessConfig`, `UnitFile`, `UnitFrontmatter`, `WaiverEntry`, `__all__`, `add_code_ref`, `central_config_template`, `dump_unit_file`, `effective_coverage`, `gitignore_to_globs`, `load_bundle`, `load_config`, `load_config_dir`, `load_ignore_file`, `load_index_file`, `load_unit_file`, `regenerate_index`, `remove_code_ref`, `resolve_repo_root`, `set_context_refs`, `set_document_owner`, `unit_for_path`, `upsert_document`, `write_index`, `write_template`
- Implemented by: `FEAT-CONFIG-001`, `FEAT-CONFIG-002`, `FEAT-CONFIG-003`, `FEAT-CONFIG-004`, `FEAT-CONFIG-005`, `FEAT-CONFIG-006`, `FEAT-CONFIG-007`, `FEAT-CONFIG-008`, `FEAT-CONFIG-009`, `FEAT-CONFIG-010`, `FEAT-CONFIG-011`, `FEAT-CONFIGV2-001`, `FEAT-CONFIGV2-002`, `FEAT-CONFIGV2-003`, `FEAT-CONFIGV2-004`, `FEAT-CONFIGV2-005`, `FEAT-CONFIGV2-006`, `FEAT-CONFIGV2-007`, `FEAT-CONFIGV2-008`, `FEAT-CONFIGV2-009`, `FEAT-CONFIGV2-010`, `FEAT-CONFIGV2-014`, `FEAT-CONFIGV2-016`, `FEAT-CONFIGV2-017`, `FEAT-DOCDEPS-001`, `FEAT-OWNERSHIP-001`, `FEAT-OWNERSHIP-008`, `FEAT-STALENESS-003`

## `configsync`

- Path: `configsync.py`
- Public symbols: `GitInfo`, `SyncResult`, `__all__`, `read_config_at`, `run_sync`
- Implemented by: `FEAT-CONFIGV2-012`, `FEAT-DOCDEPS-007`, `FEAT-GITSYNC-005`, `FEAT-STALENESS-005`

## `coverage`

- Path: `coverage.py`
- Public symbols: `CoverageReport`, `OwnedFile`, `OwnedSymbol`, `OwnerSuggestion`, `__all__`, `coverage_snapshot`, `resolve_coverage`, `suggest_owners`
- Implemented by: `FEAT-COVERAGE-006`, `FEAT-COVERAGE-007`, `FEAT-COVERAGE-008`, `FEAT-COVERAGE-009`, `FEAT-COVERAGE-010`

## `docdeps`

- Path: `docdeps.py`
- Public symbols: `InferredEdge`, `SuspectLink`, `SuspectStatus`, `__all__`, `detect_suspect_links`, `infer_edges_from_links`, `render_deps_text`, `stamp_edges`, `upstream_fingerprint`
- Implemented by: `FEAT-DOCDEPS-002`, `FEAT-DOCDEPS-003`, `FEAT-DOCDEPS-004`, `FEAT-DOCDEPS-005`, `FEAT-DOCDEPS-006`

## `docstyle`

- Path: `docstyle.py`
- Public symbols: `DocStyleFrontmatter`, `DocStyleMap`, `DocStyleMapping`, `DocStyleSelection`, `STYLE_CATEGORIES`, `__all__`, `dump_doc_style`, `load_doc_style`, `read_style_guidance`, `resolve_style_files`
- Implemented by: `FEAT-QUALITY-001`, `FEAT-QUALITY-002`, `FEAT-QUALITY-003`, `FEAT-QUALITY-004`

## `doctor`

- Path: `doctor.py`
- Public symbols: `Check`, `CheckStatus`, `__all__`, `run_checks`
- Implemented by: `FEAT-QUALITY-008`, `FEAT-QUALITY-009`

## `drift`

- Path: `drift.py`
- Public symbols: `Drift`, `DriftKind`, `DriftReport`, `__all__`, `detect`
- Implemented by: `FEAT-CONFIGV2-016`, `FEAT-DOCDEPS-004`, `FEAT-DRIFT-001`, `FEAT-DRIFT-002`, `FEAT-DRIFT-003`, `FEAT-DRIFT-004`, `FEAT-DRIFT-005`, `FEAT-DRIFT-006`, `FEAT-DRIFT-007`, `FEAT-DRIFT-008`, `FEAT-DRIFT-009`, `FEAT-DRIFT-010`

## `errors`

- Path: `errors.py`
- Public symbols: `BackendError`, `CatalogError`, `CodeDocMonitorError`, `ConfigError`, `DriftError`, `ExtractionError`, `InventoryError`, `SchemaError`, `SecretError`, `SyncError`, `TransportError`, `__all__`
- Implemented by: `FEAT-CONFIG-012`

## `extract`

- Path: `extract.py`
- Public symbols: `DocumentSurface`, `Extractor`, `PythonAstExtractor`, `Record`, `ShellExtractor`, `SurfaceFingerprint`, `Symbol`, `SymbolKind`, `__all__`, `anchor_id`, `build_document_surface`, `extract_argparse_records`, `extract_file`, `extract_json_records`, `extract_switches`, `get_extractor`, `register_extractor`
- Implemented by: `FEAT-CONFIGV2-017`, `FEAT-EXTRACT-001`, `FEAT-EXTRACT-002`, `FEAT-EXTRACT-003`, `FEAT-EXTRACT-004`, `FEAT-EXTRACT-005`, `FEAT-EXTRACT-006`, `FEAT-MANIFEST-005`

## `featurecatalog`

- Path: `featurecatalog.py`
- Public symbols: `FEATURE_ID_RE`, `Feature`, `FeatureCatalog`, `__all__`, `load_catalog`, `render_features_md`
- Implemented by: `FEAT-REFERENCE-001`, `FEAT-REFERENCE-002`

## `generate`

- Path: `generate.py`
- Public symbols: `ApplyFixResult`, `GenerateResult`, `__all__`, `apply_edits_to_disk`, `apply_record_fix`
- Implemented by: `FEAT-CONFIGV2-013`, `FEAT-OWNERSHIP-008`

## `gitauth`

- Path: `gitauth.py`
- Public symbols: `__all__`, `github_app_jwt`, `mint_github_installation_token`, `mint_gitlab_oauth_token`, `mint_provider_token`
- Implemented by: `FEAT-GITSYNC-003`

## `gitfetch`

- Path: `gitfetch.py`
- Public symbols: `RemoteSpec`, `__all__`, `cloned_repo`
- Implemented by: `FEAT-GITSYNC-001`, `FEAT-GITSYNC-005`, `FEAT-SETTINGS-005`

## `heal`

- Path: `heal.py`
- Public symbols: `ProposedFixLike`, `__all__`, `apply_fix`, `locked_region_ids`, `regenerate_regions`, `render_corrected`
- Implemented by: `FEAT-CONFIGV2-017`, `FEAT-HEAL-001`, `FEAT-HEAL-004`, `FEAT-HEAL-005`, `FEAT-HEAL-006`, `FEAT-HEAL-007`, `FEAT-HEAL-008`, `FEAT-HEAL-009`

## `index`

- Path: `index.py`
- Public symbols: `INDEX_SOURCE`, `__all__`, `render_index`
- Implemented by: `FEAT-CONFIGV2-015`

## `inventory`

- Path: `inventory.py`
- Public symbols: `CodeFile`, `DEFAULT_EXCLUDE`, `DEFAULT_INCLUDE`, `FileSymbols`, `Inventory`, `SymbolInventory`, `__all__`, `discover_files`, `discover_symbols`
- Implemented by: `FEAT-COVERAGE-001`, `FEAT-COVERAGE-002`, `FEAT-COVERAGE-003`, `FEAT-COVERAGE-004`, `FEAT-COVERAGE-005`

## `issues`

- Path: `issues.py`
- Public symbols: `GitHubIssueTransport`, `GitLabIssueTransport`, `IssuePlan`, `IssueTransport`, `__all__`, `open_coverage_issue`, `plan_coverage_issue`
- Implemented by: `FEAT-PR-007`, `FEAT-PR-008`

## `layout`

- Path: `layout.py`
- Public symbols: `LAYOUT_VERSION`, `LayoutCode`, `LayoutIssue`, `RegionState`, `__all__`, `config_region_states`, `embedded_md_hash`, `html_twin_path`, `lint_config`, `lint_doc`, `lint_html_twin`, `md_source_hash`, `region_states`, `scaffold_doc`, `stamp_doc_meta`
- Implemented by: `FEAT-CONFIGV2-016`, `FEAT-LAYOUT-001`, `FEAT-LAYOUT-002`, `FEAT-LAYOUT-003`, `FEAT-LAYOUT-004`, `FEAT-LAYOUT-005`, `FEAT-LAYOUT-006`, `FEAT-LAYOUT-007`, `FEAT-LAYOUT-009`

## `manifest`

- Path: `manifest.py`
- Public symbols: `Doc`, `__all__`, `drop_upstream_hash`, `parse_doc`, `parse_text`, `region_body_hash`, `region_is_locked`, `regions`, `render_doc`, `set_fingerprint`, `set_fingerprint_tiers`, `set_region`, `set_region_anchors`, `set_region_hash`, `set_upstream_hash`, `stamp_standard_meta`, `stored_fingerprint`, `stored_fingerprint_tiers`, `stored_region_anchors`, `stored_region_hash`, `stored_upstream_hashes`
- Implemented by: `FEAT-DOCDEPS-002`, `FEAT-MANIFEST-001`, `FEAT-MANIFEST-002`, `FEAT-MANIFEST-003`, `FEAT-MANIFEST-004`, `FEAT-MANIFEST-005`, `FEAT-MANIFEST-006`, `FEAT-MANIFEST-007`, `FEAT-MANIFEST-008`, `FEAT-MANIFEST-009`

## `monitor`

- Path: `monitor.py`
- Public symbols: `DEFAULT_EXEMPLAR_TOP_N`, `DEFAULT_LOG_PATH`, `HandledDrift`, `Monitor`, `MonitorResult`, `RULE_CAUSE_PREFIX`, `__all__`
- Implemented by: `FEAT-DOCDEPS-006`, `FEAT-MONITOR-001`, `FEAT-MONITOR-002`, `FEAT-MONITOR-003`, `FEAT-MONITOR-004`, `FEAT-MONITOR-005`, `FEAT-MONITOR-006`, `FEAT-MONITOR-007`, `FEAT-MONITOR-008`, `FEAT-MONITOR-009`

## `ownership`

- Path: `ownership.py`
- Public symbols: `EffectiveOwner`, `Identity`, `OwnershipFinding`, `OwnershipStatus`, `RosterSnapshot`, `__all__`, `detect_orphans`, `load_roster`, `render_ownership_text`, `resolve_accountable_durable`, `resolve_ownership`
- Implemented by: `FEAT-OWNERSHIP-002`, `FEAT-OWNERSHIP-003`, `FEAT-OWNERSHIP-004`, `FEAT-OWNERSHIP-005`, `FEAT-OWNERSHIP-007`, `FEAT-OWNERSHIP-009`

## `pr`

- Path: `pr.py`
- Public symbols: `GitHubTransport`, `GitLabTransport`, `MergeRequestPlan`, `PRTransport`, `__all__`, `open_docs_pr`, `plan_docs_pr`
- Implemented by: `FEAT-GITSYNC-004`, `FEAT-PR-004`, `FEAT-PR-005`, `FEAT-PR-006`

## `promotion`

- Path: `promotion.py`
- Public symbols: `PROMOTABLE_RESOLUTIONS`, `PromotionCandidate`, `PromotionRule`, `__all__`, `detect_promotions`, `rule_for`, `rule_from_candidate`
- Implemented by: `FEAT-LEARN-004`, `FEAT-LEARN-005`, `FEAT-LEARN-006`

## `registry`

- Path: `registry.py`
- Public symbols: `HttpRegisterTransport`, `HttpSyncTransport`, `RegisterTransport`, `RegistrationPayload`, `__all__`, `register_repo`, `repo_identity_from_config`, `sync_repo_remote`
- Implemented by: `FEAT-SERVER-017`, `FEAT-SERVER-018`

## `report`

- Path: `report.py`
- Public symbols: `CDMON_REPORT_VERSION`, `CoverageRpt`, `RptSummary`, `RptUndocumented`, `RptUnit`, `__all__`, `build_coverage_rpt`, `parse_rpt`, `render_rpt`, `report_repo_root`, `write_rpt`
- Implemented by: `FEAT-QUALITY-005`, `FEAT-QUALITY-006`, `FEAT-QUALITY-007`

## `reviewlog`

- Path: `reviewlog.py`
- Public symbols: `DEFAULT_RESOLUTIONS_PATH`, `__all__`, `append`, `append_resolution`, `read_all`, `read_resolutions`, `resolved_index`, `select_by_verdict`, `summarize`, `summarize_with_resolutions`
- Implemented by: `FEAT-RECORD-007`, `FEAT-RECORD-008`, `FEAT-RECORD-009`

## `schema`

- Path: `schema.py`
- Public symbols: `ProposedFix`, `Resolution`, `ResolutionRecord`, `ReviewRecord`, `Verdict`, `__all__`, `new_record_id`, `resolution_record_schema`, `review_record_schema`
- Implemented by: `FEAT-RECORD-001`, `FEAT-RECORD-002`, `FEAT-RECORD-003`, `FEAT-RECORD-004`, `FEAT-RECORD-005`, `FEAT-RECORD-006`

## `secrets`

- Path: `secrets.py`
- Public symbols: `SecretBox`, `__all__`, `secret_box_from_env`
- Implemented by: `FEAT-GITSYNC-002`

## `server`

- Path: `server/__init__.py`
- Public symbols: `AddCodeRefEdit`, `ApplyFixResponse`, `Base`, `ConfigCodeRef`, `ConfigCodeRefRow`, `ConfigContextRef`, `ConfigDocEdge`, `ConfigDocument`, `ConfigDocumentRow`, `ConfigEdit`, `ConfigEditRow`, `CoverageIngest`, `CoverageSnapshotRow`, `CreateDocEdit`, `DocStyleOptions`, `DocsPrRequest`, `DocumentTree`, `EditCodeRef`, `EditContextRef`, `EditDocStyle`, `EditableConfigTree`, `EditableDocument`, `GenerateRequest`, `GenerateResponse`, `InMemoryStore`, `ReassignOwnerEdit`, `RecordRow`, `RegisteredRepo`, `RemoveCodeRefEdit`, `RepoHealth`, `RepoRow`, `RepoStatus`, `RepoTelemetry`, `ResolutionRow`, `RosterRow`, `SetContextRefsEdit`, `SetDocStyleEdit`, `ShapeStat`, `SqlStore`, `Store`, `StoredConfigEdit`, `SyncRequest`, `SyncRun`, `SyncRunRow`, `WIKI_SECTIONS`, `__all__`, `build_standalone_app`, `build_standalone_store`, `create_all`, `create_app`, `effective_identity`, `engine_from_url`, `hash_token`, `main`, `resolve_repo_id`, `store_from_env`
- Implemented by: `FEAT-DOCDEPS-007`, `FEAT-OWNERSHIP-005`, `FEAT-OWNERSHIP-006`, `FEAT-OWNERSHIP-007`, `FEAT-OWNERSHIP-008`, `FEAT-OWNERSHIP-009`, `FEAT-SERVER-001`, `FEAT-SERVER-002`, `FEAT-SERVER-003`, `FEAT-SERVER-004`, `FEAT-SERVER-005`, `FEAT-SERVER-006`, `FEAT-SERVER-007`, `FEAT-SERVER-008`, `FEAT-SERVER-009`, `FEAT-SERVER-010`, `FEAT-SERVER-011`, `FEAT-SERVER-012`, `FEAT-SERVER-013`, `FEAT-SERVER-014`, `FEAT-SERVER-015`, `FEAT-SERVER-016`, `FEAT-SERVER-019`, `FEAT-SETTINGS-004`, `FEAT-SETTINGS-005`, `FEAT-SETTINGS-006`, `FEAT-SETTINGS-007`, `FEAT-STALENESS-005`, `FEAT-STALENESS-006`

## `settings`

- Path: `settings.py`
- Public symbols: `CorsSettings`, `DEFAULT_SETTINGS_PATH`, `GitSettings`, `RateLimitSettings`, `ServerSettings`, `Settings`, `__all__`, `load_settings`, `resolve_settings`, `secret_presence`, `settings_from_env`
- Implemented by: `FEAT-SETTINGS-001`, `FEAT-SETTINGS-002`, `FEAT-SETTINGS-003`

## `similar`

- Path: `similar.py`
- Public symbols: `Exemplar`, `FEATURE_WEIGHTS`, `__all__`, `rank_similar`
- Implemented by: `FEAT-LEARN-001`, `FEAT-LEARN-002`, `FEAT-LEARN-003`

## `sinks`

- Path: `sinks.py`
- Public symbols: `FileSink`, `HttpSink`, `IngestEnvelope`, `NullSink`, `RepoIdentity`, `Sink`, `__all__`, `make_sink`
- Implemented by: `FEAT-RECORD-010`, `FEAT-RECORD-011`, `FEAT-RECORD-012`, `FEAT-RECORD-013`

## `srcindex`

- Path: `srcindex.py`
- Public symbols: `ModuleIndex`, `SourceIndex`, `__all__`, `build_source_index`, `render_source_wiki_md`
- Implemented by: `FEAT-REFERENCE-005`, `FEAT-REFERENCE-006`

## `staleness`

- Path: `staleness.py`
- Public symbols: `ReviewedDoc`, `StalenessFinding`, `StalenessStatus`, `__all__`, `detect_stale`, `grade_doc`, `render_staleness_text`, `resolve_sla_days`, `reviewed_docs_from_config`
- Implemented by: `FEAT-STALENESS-001`, `FEAT-STALENESS-002`, `FEAT-STALENESS-003`

## `syncpr`

- Path: `syncpr.py`
- Public symbols: `SyncResult`, `__all__`, `should_sync`, `sync_pr`
- Implemented by: `FEAT-PR-001`, `FEAT-PR-002`, `FEAT-PR-003`

## `templates_v2`

- Path: `templates_v2.py`
- Public symbols: `DOC_STYLE_TEMPLATE`, `EXAMPLE_UNIT_STEM`, `IGNORE_TEMPLATE`, `INDEX_TEMPLATE`, `UNIT_TEMPLATE`, `V2_TEMPLATES`, `__all__`, `scaffold_config_dir`
- Implemented by: `FEAT-CONFIGV2-011`

## `testwiki`

- Path: `testwiki.py`
- Public symbols: `TestBoundary`, `TestCase`, `TestModule`, `__all__`, `collect_tests`, `render_test_wiki_md`
- Implemented by: `FEAT-REFERENCE-004`

## `ticket`

- Path: `ticket.py`
- Public symbols: `AcceptanceCheck`, `DriftTicket`, `TicketSeverity`, `TicketStatus`, `__all__`, `build_ticket`, `ticket_status`
- Implemented by: `FEAT-PR-009`, `FEAT-PR-010`, `FEAT-PR-011`

## `traceability`

- Path: `traceability.py`
- Public symbols: `EvidenceKind`, `FEATURE_REF_RE`, `FeatureRef`, `TraceMatrix`, `__all__`, `build_matrix`, `render_matrix_md`, `scan_refs`
- Implemented by: `FEAT-REFERENCE-003`

## `wiki`

- Path: `wiki.py`
- Public symbols: `WIKI_TARGETS`, `__all__`, `regenerate`
- Implemented by: `FEAT-REFERENCE-007`

## Coverage

None — every public module maps to at least one catalog feature.
