# custodex — feature traceability

Generated from the golden catalog crossed against inline `Feature:` tags in `tests/` + `demo/` — **do not hand-edit**. Run `cdx trace` (R-07 `cdx wiki`) to regenerate.

**235 features** — COMPLETE (every feature needs >=1 test AND >=1 demo).

| Feature | Tests | Demos |
|---------|-------|-------|
| `FEAT-AGENT-001` | unit/test_agent.py | DEMOS.md |
| `FEAT-AGENT-002` | unit/test_agent.py | DEMOS.md |
| `FEAT-AGENT-003` | unit/test_agent.py | DEMOS.md |
| `FEAT-AGENT-004` | integration/test_agent_style.py, unit/test_agent.py | DEMOS.md |
| `FEAT-AGENT-005` | integration/test_agent_style.py, unit/test_agent.py | DEMOS.md |
| `FEAT-AGENT-006` | integration/test_agent_style.py, unit/test_agent.py | DEMOS.md |
| `FEAT-AGENT-007` | unit/test_agent.py | DEMOS.md |
| `FEAT-AGENT-008` | integration/test_agent_style.py, system/test_live_llm.py, unit/test_agent.py | DEMOS.md |
| `FEAT-BACKENDS-001` | system/test_live_llm.py, unit/test_backends.py | DEMOS.md |
| `FEAT-BACKENDS-002` | system/test_live_llm.py, system/test_system.py, unit/test_backends.py | DEMOS.md |
| `FEAT-BACKENDS-003` | system/test_demo_walkthrough.py, system/test_system.py, unit/test_backends.py | DEMOS.md |
| `FEAT-BACKENDS-004` | system/test_live_llm.py, system/test_system.py, unit/test_backends.py | DEMOS.md |
| `FEAT-BACKENDS-005` | system/test_live_llm.py, unit/test_backends.py | DEMOS.md |
| `FEAT-BACKENDS-006` | unit/test_backends.py | DEMOS.md |
| `FEAT-BACKENDS-007` | unit/test_backends.py | DEMOS.md |
| `FEAT-BACKENDS-008` | integration/test_agent_style.py, unit/test_backends.py | DEMOS.md |
| `FEAT-CLI-001` | integration/test_templates_v2.py, system/test_cli_init.py | DEMOS.md |
| `FEAT-CLI-002` | integration/test_config_index.py, system/test_dogfood.py | DEMOS.md |
| `FEAT-CLI-003` | integration/test_report.py, system/test_demo_e2e.py | DEMOS.md |
| `FEAT-CLI-004` | system/test_cli.py | DEMOS.md |
| `FEAT-CLI-005` | system/test_ci_templates.py, system/test_cli.py, system/test_demo_e2e.py, system/test_demo_walkthrough.py, system/test_dirlayout_e2e.py, system/test_system.py | DEMOS.md |
| `FEAT-CLI-006` | system/test_cli.py | DEMOS.md |
| `FEAT-CLI-007` | system/test_cli.py, system/test_demo_walkthrough.py, system/test_dirlayout_e2e.py, system/test_system.py | DEMOS.md |
| `FEAT-CLI-008` | system/test_ci_templates.py, system/test_cli.py | DEMOS.md |
| `FEAT-CLI-009` | integration/test_syncpr.py, system/test_ci_templates.py, system/test_cli.py | DEMOS.md |
| `FEAT-CLI-010` | system/test_ci_templates.py, system/test_cli.py | DEMOS.md |
| `FEAT-CLI-011` | system/test_cli.py | DEMOS.md |
| `FEAT-CLI-012` | system/test_cli_sync.py | DEMOS.md |
| `FEAT-CLI-013` | system/test_cli.py | DEMOS.md |
| `FEAT-CLI-014` | integration/test_doctor.py, system/test_ci_templates.py, system/test_demo_walkthrough.py | DEMOS.md |
| `FEAT-CLI-015` | system/test_cli.py, system/test_demo_walkthrough.py, system/test_system.py | DEMOS.md |
| `FEAT-CLI-016` | system/test_cli.py | DEMOS.md |
| `FEAT-CLI-017` | system/test_cli.py, system/test_demo_walkthrough.py, system/test_dirlayout_e2e.py | DEMOS.md |
| `FEAT-CLI-018` | system/test_cli.py | DEMOS.md |
| `FEAT-CLI-019` | system/test_cli.py | DEMOS.md |
| `FEAT-CLI-020` | system/test_ci_templates.py, system/test_cli.py, system/test_system.py | DEMOS.md |
| `FEAT-CLI-021` | system/test_cli.py | DEMOS.md |
| `FEAT-CLI-022` | system/test_cli.py, system/test_system.py | DEMOS.md |
| `FEAT-CONFIG-001` | integration/test_config.py | DEMOS.md |
| `FEAT-CONFIG-002` | integration/test_config.py, system/test_example_multilang.py, system/test_system.py | DEMOS.md |
| `FEAT-CONFIG-003` | integration/test_generate.py, system/test_demo_e2e.py, system/test_dogfood.py, unit/test_context_refs.py | DEMOS.md |
| `FEAT-CONFIG-004` | integration/test_config.py, system/test_system.py | DEMOS.md |
| `FEAT-CONFIG-005` | integration/test_config.py, system/test_system.py | DEMOS.md |
| `FEAT-CONFIG-006` | unit/test_templates.py | DEMOS.md |
| `FEAT-CONFIG-007` | integration/test_config.py | DEMOS.md |
| `FEAT-CONFIG-008` | integration/test_config.py, system/test_cli_init.py, system/test_dogfood.py, system/test_example_external.py, system/test_live_llm.py | DEMOS.md |
| `FEAT-CONFIG-009` | integration/test_config.py, system/test_cli_init.py, system/test_dirlayout_e2e.py, system/test_dogfood.py, system/test_example_external.py, system/test_example_multilang.py | DEMOS.md |
| `FEAT-CONFIG-010` | integration/test_config.py, system/test_cli_init.py | DEMOS.md |
| `FEAT-CONFIG-011` | system/test_system.py, unit/test_drift.py | DEMOS.md |
| `FEAT-CONFIG-012` | integration/test_config.py | DEMOS.md |
| `FEAT-CONFIGV2-001` | integration/test_config_ignore.py, integration/test_config_v2.py, regression/test_corpus_selfcoverage.py, system/test_demo_e2e.py, system/test_dirlayout_e2e.py, system/test_dogfood.py, system/test_standalone.py, unit/test_testwiki.py | DEMOS.md |
| `FEAT-CONFIGV2-002` | integration/test_config_ignore.py, integration/test_config_v2.py, system/test_dirlayout_e2e.py, unit/test_context_refs.py, unit/test_testwiki.py | DEMOS.md |
| `FEAT-CONFIGV2-003` | integration/test_config_index.py, integration/test_config_v2.py, system/test_demo_e2e.py, system/test_dogfood.py, system/test_standalone.py | DEMOS.md |
| `FEAT-CONFIGV2-004` | integration/test_config_index.py, integration/test_config_v2.py, integration/test_templates_v2.py | DEMOS.md |
| `FEAT-CONFIGV2-005` | integration/test_config_v2.py | DEMOS.md |
| `FEAT-CONFIGV2-006` | integration/test_config_ignore.py, integration/test_report.py, system/test_demo_e2e.py, system/test_dirlayout_e2e.py, unit/test_context_refs.py | DEMOS.md |
| `FEAT-CONFIGV2-007` | integration/test_config_ignore.py, integration/test_templates_v2.py | DEMOS.md |
| `FEAT-CONFIGV2-008` | integration/test_config_v2.py, integration/test_configsync.py, integration/test_gitfetch.py, system/test_demo_e2e.py, system/test_dirlayout_e2e.py, system/test_dogfood.py, system/test_standalone.py | DEMOS.md |
| `FEAT-CONFIGV2-009` | integration/test_config_index.py, system/test_dogfood.py | DEMOS.md |
| `FEAT-CONFIGV2-010` | integration/test_config_v2.py | DEMOS.md |
| `FEAT-CONFIGV2-011` | integration/test_templates_v2.py | DEMOS.md |
| `FEAT-CONFIGV2-012` | integration/test_apply_fix.py, integration/test_configsync.py, integration/test_gitfetch.py, integration/test_server_gitsync.py, integration/test_server_sync.py, system/test_cli_sync.py, system/test_demo_e2e.py, system/test_demo_gitsync_e2e.py, system/test_gitrepo_sync_e2e.py, system/test_standalone.py, unit/test_gitfetch.py | DEMOS.md |
| `FEAT-CONFIGV2-013` | integration/test_apply_fix.py, integration/test_generate.py, system/test_demo_walkthrough.py | DEMOS.md |
| `FEAT-CONFIGV2-014` | unit/test_unit_serializer.py | DEMOS.md |
| `FEAT-CONFIGV2-015` | unit/test_index.py | DEMOS.md |
| `FEAT-CONFIGV2-016` | system/test_dogfood.py | DEMOS.md |
| `FEAT-CONFIGV2-017` | system/test_testdoc_mirror.py | DEMOS.md |
| `FEAT-COVERAGE-001` | integration/test_config_ignore.py, integration/test_editable_tree.py, integration/test_generate.py, integration/test_report.py, regression/test_corpus_selfcoverage.py, unit/test_inventory.py | DEMOS.md |
| `FEAT-COVERAGE-002` | integration/test_config_ignore.py, unit/test_inventory.py | DEMOS.md |
| `FEAT-COVERAGE-003` | unit/test_inventory.py | DEMOS.md |
| `FEAT-COVERAGE-004` | unit/test_inventory.py | DEMOS.md |
| `FEAT-COVERAGE-005` | regression/test_corpus_selfcoverage.py, unit/test_inventory.py | DEMOS.md |
| `FEAT-COVERAGE-006` | regression/test_corpus_selfcoverage.py, system/test_dirlayout_e2e.py, unit/test_coverage.py | DEMOS.md |
| `FEAT-COVERAGE-007` | integration/test_config_ignore.py, regression/test_corpus_selfcoverage.py, system/test_cli.py, system/test_demo_walkthrough.py, system/test_dirlayout_e2e.py, system/test_dogfood.py, system/test_e2e_ticket_coverage.py, unit/test_coverage.py | DEMOS.md |
| `FEAT-COVERAGE-008` | regression/test_corpus_selfcoverage.py, system/test_dirlayout_e2e.py, system/test_dogfood.py, unit/test_coverage.py | DEMOS.md |
| `FEAT-COVERAGE-009` | regression/test_corpus_selfcoverage.py, system/test_dirlayout_e2e.py, unit/test_coverage.py | DEMOS.md |
| `FEAT-COVERAGE-010` | integration/test_server_store_parity.py, system/test_cli.py, system/test_e2e_ticket_coverage.py, unit/test_coverage.py | DEMOS.md |
| `FEAT-DOCDEPS-001` | unit/test_docdeps_config.py | DEMOS.md |
| `FEAT-DOCDEPS-002` | unit/test_docdeps.py | DEMOS.md |
| `FEAT-DOCDEPS-003` | unit/test_docdeps.py | DEMOS.md |
| `FEAT-DOCDEPS-004` | unit/test_drift_suspect_link.py | DEMOS.md |
| `FEAT-DOCDEPS-005` | system/test_docdeps_cli.py | DEMOS.md |
| `FEAT-DOCDEPS-006` | integration/test_monitor_docdeps.py | DEMOS.md |
| `FEAT-DOCDEPS-007` | integration/test_docdeps_server.py | DEMOS.md |
| `FEAT-DOCDEPS-008` | integration/test_db.py, integration/test_docdeps_server.py | DEMOS.md |
| `FEAT-DOCDEPS-009` | system/test_docdeps_cli.py, unit/test_docdeps.py | DEMOS.md |
| `FEAT-DOCDEPS-010` | integration/test_docdeps_server.py, system/test_docdeps_cli.py, unit/test_docdeps.py | DEMOS.md |
| `FEAT-DRIFT-001` | regression/test_corpus_pipeline.py, regression/test_corpus_selfcoverage.py, system/test_cli.py, system/test_demo_walkthrough.py, system/test_dirlayout_e2e.py, system/test_dogfood.py, system/test_example_external.py, system/test_example_multilang.py, system/test_live_llm.py, system/test_system.py, unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-002` | system/test_system.py, unit/test_drift.py, unit/test_traceability.py | DEMOS.md |
| `FEAT-DRIFT-003` | system/test_system.py, unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-004` | regression/test_corpus_pipeline.py, system/test_system.py, unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-005` | integration/test_monitor.py, system/test_system.py, unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-006` | system/test_system.py, unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-007` | system/test_system.py, unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-008` | regression/test_corpus_pipeline.py, system/test_system.py, unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-009` | unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-010` | unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-011` | integration/test_monitor.py, unit/test_drift.py | DEMOS.md |
| `FEAT-DRIFT-012` | integration/test_monitor.py, unit/test_drift.py, unit/test_extract.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-EXTRACT-001` | regression/test_corpus_pipeline.py, system/test_dogfood.py, system/test_example_multilang.py, system/test_system.py, unit/test_extract.py, unit/test_records.py, unit/test_testwiki.py, unit/test_traceability.py | DEMOS.md |
| `FEAT-EXTRACT-002` | regression/test_corpus_pipeline.py, system/test_system.py, unit/test_extract.py, unit/test_records.py, unit/test_testwiki.py | DEMOS.md |
| `FEAT-EXTRACT-003` | system/test_example_multilang.py, unit/test_extract.py, unit/test_records.py, unit/test_testwiki.py | DEMOS.md |
| `FEAT-EXTRACT-004` | regression/test_corpus_pipeline.py, system/test_system.py, unit/test_extract.py | DEMOS.md |
| `FEAT-EXTRACT-005` | system/test_system.py, unit/test_extract.py | DEMOS.md |
| `FEAT-EXTRACT-006` | system/test_example_multilang.py, system/test_system.py, unit/test_extract.py | DEMOS.md |
| `FEAT-GITSYNC-001` | system/test_gitrepo_sync_e2e.py, unit/test_gitfetch.py | DEMOS.md |
| `FEAT-GITSYNC-002` | unit/test_secrets.py | DEMOS.md |
| `FEAT-GITSYNC-003` | unit/test_gitauth.py | DEMOS.md |
| `FEAT-GITSYNC-004` | unit/test_pr.py | DEMOS.md |
| `FEAT-GITSYNC-005` | system/test_gitrepo_sync_e2e.py | DEMOS.md |
| `FEAT-HEAL-001` | integration/test_heal.py, regression/test_corpus_pipeline.py, regression/test_corpus_selfcoverage.py, system/test_demo_walkthrough.py, system/test_dirlayout_e2e.py, system/test_dogfood.py, system/test_example_external.py, system/test_system.py | DEMOS.md |
| `FEAT-HEAL-002` | integration/test_heal.py, system/test_system.py | DEMOS.md |
| `FEAT-HEAL-003` | unit/test_templates.py | DEMOS.md |
| `FEAT-HEAL-004` | integration/test_heal.py, integration/test_syncpr.py, regression/test_corpus_pipeline.py, system/test_system.py | DEMOS.md |
| `FEAT-HEAL-005` | integration/test_heal.py, regression/test_corpus_pipeline.py, system/test_system.py | DEMOS.md |
| `FEAT-HEAL-006` | integration/test_heal.py, system/test_system.py | DEMOS.md |
| `FEAT-HEAL-007` | integration/test_heal.py, regression/test_corpus_pipeline.py, system/test_system.py | DEMOS.md |
| `FEAT-HEAL-008` | integration/test_apply_fix.py, integration/test_heal.py, regression/test_corpus_pipeline.py, system/test_demo_walkthrough.py, system/test_live_llm.py, system/test_system.py | DEMOS.md |
| `FEAT-HEAL-009` | integration/test_heal.py, regression/test_corpus_pipeline.py, system/test_live_llm.py, system/test_system.py | DEMOS.md |
| `FEAT-LAYOUT-001` | integration/test_layout.py, regression/test_corpus_selfcoverage.py, system/test_cli.py, system/test_dogfood.py, system/test_example_multilang.py, system/test_system.py | DEMOS.md |
| `FEAT-LAYOUT-002` | integration/test_layout.py, regression/test_corpus_selfcoverage.py, system/test_cli.py, system/test_dogfood.py, system/test_example_multilang.py | DEMOS.md |
| `FEAT-LAYOUT-003` | integration/test_layout.py, system/test_cli.py, system/test_system.py | DEMOS.md |
| `FEAT-LAYOUT-004` | integration/test_layout.py, system/test_cli.py | DEMOS.md |
| `FEAT-LAYOUT-005` | integration/test_build.py, integration/test_layout.py, system/test_example_multilang.py, system/test_system.py | DEMOS.md |
| `FEAT-LAYOUT-006` | integration/test_layout.py, system/test_dogfood.py | DEMOS.md |
| `FEAT-LAYOUT-007` | integration/test_layout.py, system/test_cli.py, system/test_system.py | DEMOS.md |
| `FEAT-LAYOUT-008` | integration/test_build.py | DEMOS.md |
| `FEAT-LAYOUT-009` | integration/test_build.py | DEMOS.md |
| `FEAT-LEARN-001` | integration/test_monitor.py, unit/test_similar.py | DEMOS.md |
| `FEAT-LEARN-002` | unit/test_similar.py | DEMOS.md |
| `FEAT-LEARN-003` | integration/test_monitor.py, unit/test_agent.py, unit/test_similar.py | DEMOS.md |
| `FEAT-LEARN-004` | system/test_cli.py, unit/test_promotion.py | DEMOS.md |
| `FEAT-LEARN-005` | unit/test_promotion.py | DEMOS.md |
| `FEAT-LEARN-006` | integration/test_monitor.py, regression/test_corpus_contracts.py, unit/test_promotion.py | DEMOS.md |
| `FEAT-MANIFEST-001` | system/test_system.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-MANIFEST-002` | system/test_system.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-MANIFEST-003` | regression/test_corpus_pipeline.py, system/test_system.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-MANIFEST-004` | system/test_system.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-MANIFEST-005` | system/test_system.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-MANIFEST-006` | regression/test_corpus_pipeline.py, system/test_system.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-MANIFEST-007` | regression/test_corpus_pipeline.py, system/test_system.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-MANIFEST-008` | system/test_system.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-MANIFEST-009` | system/test_system.py, unit/test_manifest.py | DEMOS.md |
| `FEAT-MONITOR-001` | integration/test_monitor.py, regression/test_corpus_pipeline.py, system/test_cli.py, system/test_e2e_ticket_coverage.py, system/test_example_external.py, system/test_live_llm.py, system/test_system.py, unit/test_index.py, unit/test_templates.py | DEMOS.md |
| `FEAT-MONITOR-002` | integration/test_monitor.py, regression/test_corpus_selfcoverage.py, system/test_dogfood.py, system/test_example_multilang.py, unit/test_index.py, unit/test_templates.py | DEMOS.md |
| `FEAT-MONITOR-003` | integration/test_apply_fix.py, integration/test_monitor.py, regression/test_corpus_pipeline.py, regression/test_corpus_selfcoverage.py, system/test_cli.py, system/test_demo_walkthrough.py, system/test_dirlayout_e2e.py, system/test_dogfood.py, system/test_example_external.py, system/test_live_llm.py, system/test_system.py, unit/test_index.py, unit/test_templates.py | DEMOS.md |
| `FEAT-MONITOR-004` | integration/test_apply_fix.py, integration/test_monitor.py, system/test_e2e_ticket_coverage.py, system/test_example_external.py, system/test_system.py, unit/test_index.py | DEMOS.md |
| `FEAT-MONITOR-005` | integration/test_monitor.py, system/test_cli.py | DEMOS.md |
| `FEAT-MONITOR-006` | integration/test_monitor.py, regression/test_corpus_pipeline.py, system/test_live_llm.py, system/test_system.py | DEMOS.md |
| `FEAT-MONITOR-007` | integration/test_monitor.py, regression/test_corpus_contracts.py | DEMOS.md |
| `FEAT-MONITOR-008` | integration/test_monitor.py | DEMOS.md |
| `FEAT-MONITOR-009` | integration/test_agent_style.py | DEMOS.md |
| `FEAT-OWNERSHIP-001` | unit/test_ownership.py | DEMOS.md |
| `FEAT-OWNERSHIP-002` | unit/test_ownership.py | DEMOS.md |
| `FEAT-OWNERSHIP-003` | unit/test_ownership.py | DEMOS.md |
| `FEAT-OWNERSHIP-004` | system/test_ownership_cli.py, unit/test_ownership.py | DEMOS.md |
| `FEAT-OWNERSHIP-005` | integration/test_db.py, integration/test_ownership_server.py | DEMOS.md |
| `FEAT-OWNERSHIP-006` | integration/test_ownership_server.py | DEMOS.md |
| `FEAT-OWNERSHIP-007` | integration/test_ownership_server.py | DEMOS.md |
| `FEAT-OWNERSHIP-008` | integration/test_generate.py, unit/test_unit_serializer.py | DEMOS.md |
| `FEAT-OWNERSHIP-009` | system/test_demo_e2e.py | DEMOS.md |
| `FEAT-PR-001` | integration/test_syncpr.py, system/test_cli.py | DEMOS.md |
| `FEAT-PR-002` | integration/test_syncpr.py, system/test_cli.py | DEMOS.md |
| `FEAT-PR-003` | integration/test_syncpr.py, regression/test_corpus_pipeline.py, system/test_cli.py | DEMOS.md |
| `FEAT-PR-004` | system/test_cli.py, unit/test_pr.py | DEMOS.md |
| `FEAT-PR-005` | system/test_gitrepo_sync_e2e.py, unit/test_pr.py | DEMOS.md |
| `FEAT-PR-006` | system/test_cli.py, unit/test_pr.py | DEMOS.md |
| `FEAT-PR-007` | system/test_cli.py, unit/test_issues.py | DEMOS.md |
| `FEAT-PR-008` | system/test_cli.py, unit/test_issues.py | DEMOS.md |
| `FEAT-PR-009` | integration/test_monitor.py, integration/test_server_store_parity.py, system/test_e2e_ticket_coverage.py, unit/test_ticket.py | DEMOS.md |
| `FEAT-PR-010` | system/test_e2e_ticket_coverage.py, unit/test_ticket.py | DEMOS.md |
| `FEAT-PR-011` | unit/test_ticket.py | DEMOS.md |
| `FEAT-QUALITY-001` | system/test_demo_e2e.py, unit/test_docstyle.py | DEMOS.md |
| `FEAT-QUALITY-002` | unit/test_docstyle.py | DEMOS.md |
| `FEAT-QUALITY-003` | integration/test_agent_style.py, unit/test_docstyle.py | DEMOS.md |
| `FEAT-QUALITY-004` | integration/test_generate.py, integration/test_templates_v2.py | DEMOS.md |
| `FEAT-QUALITY-005` | integration/test_report.py, system/test_demo_e2e.py | DEMOS.md |
| `FEAT-QUALITY-006` | integration/test_report.py | DEMOS.md |
| `FEAT-QUALITY-007` | integration/test_report.py, system/test_demo_e2e.py | DEMOS.md |
| `FEAT-QUALITY-008` | integration/test_doctor.py, system/test_demo_walkthrough.py | DEMOS.md |
| `FEAT-QUALITY-009` | integration/test_doctor.py | DEMOS.md |
| `FEAT-RECORD-001` | regression/test_corpus_contracts.py, system/test_cli.py, system/test_e2e_ticket_coverage.py, system/test_example_external.py, system/test_system.py, unit/test_schema.py | DEMOS.md |
| `FEAT-RECORD-002` | integration/test_db.py, regression/test_corpus_contracts.py, unit/test_schema.py | DEMOS.md |
| `FEAT-RECORD-003` | regression/test_corpus_contracts.py, system/test_cli.py, system/test_system.py, unit/test_schema.py | DEMOS.md |
| `FEAT-RECORD-004` | system/test_e2e_ticket_coverage.py, system/test_system.py, unit/test_schema.py | DEMOS.md |
| `FEAT-RECORD-005` | integration/test_monitor.py, unit/test_schema.py | DEMOS.md |
| `FEAT-RECORD-006` | integration/test_apply_fix.py, integration/test_server.py, integration/test_server_store_parity.py, regression/test_corpus_contracts.py, system/test_cli.py, unit/test_schema.py | DEMOS.md |
| `FEAT-RECORD-007` | integration/test_monitor.py, system/test_cli.py, system/test_demo_walkthrough.py, system/test_system.py, unit/test_reviewlog.py | DEMOS.md |
| `FEAT-RECORD-008` | unit/test_reviewlog.py | DEMOS.md |
| `FEAT-RECORD-009` | system/test_cli.py, unit/test_reviewlog.py | DEMOS.md |
| `FEAT-RECORD-010` | integration/test_server.py, integration/test_server_store_parity.py, system/test_e2e_ticket_coverage.py, system/test_example_external.py, unit/test_sinks.py | DEMOS.md |
| `FEAT-RECORD-011` | system/test_system.py, unit/test_sinks.py | DEMOS.md |
| `FEAT-RECORD-012` | regression/test_corpus_contracts.py, system/test_cli_init.py, system/test_example_external.py, unit/test_sinks.py | DEMOS.md |
| `FEAT-RECORD-013` | system/test_cli_init.py, unit/test_sinks.py | DEMOS.md |
| `FEAT-REFERENCE-001` | integration/test_demo_traceability.py, unit/test_featurecatalog.py | DEMOS.md |
| `FEAT-REFERENCE-002` | unit/test_featurecatalog.py | DEMOS.md |
| `FEAT-REFERENCE-003` | unit/test_traceability.py | DEMOS.md |
| `FEAT-REFERENCE-004` | unit/test_testwiki.py | DEMOS.md |
| `FEAT-REFERENCE-005` | unit/test_srcindex.py | DEMOS.md |
| `FEAT-REFERENCE-006` | unit/test_srcindex.py | DEMOS.md |
| `FEAT-REFERENCE-007` | system/test_wiki_cli.py, unit/test_wiki.py | DEMOS.md |
| `FEAT-SERVER-001` | integration/test_server.py, system/test_demo_e2e.py, system/test_example_external.py, system/test_server_launch.py, system/test_standalone.py | DEMOS.md |
| `FEAT-SERVER-002` | integration/test_server.py, integration/test_server_store_parity.py, system/test_e2e_ticket_coverage.py, system/test_example_external.py, system/test_server_launch.py | DEMOS.md |
| `FEAT-SERVER-003` | integration/test_provider_secret.py, integration/test_server.py, integration/test_server_gitsync.py, integration/test_server_store_parity.py, system/test_demo_gitsync_e2e.py, system/test_e2e_ticket_coverage.py, system/test_example_external.py, system/test_server_launch.py | DEMOS.md |
| `FEAT-SERVER-004` | integration/test_apply_fix.py, integration/test_config_edits_routes.py, integration/test_db.py, integration/test_generate.py, integration/test_server.py, integration/test_server_store_parity.py, integration/test_server_sync.py, system/test_e2e_ticket_coverage.py, system/test_example_external.py, system/test_standalone.py | DEMOS.md |
| `FEAT-SERVER-005` | integration/test_apply_fix.py, integration/test_config_edits_routes.py, integration/test_db.py, integration/test_server.py, integration/test_server_store_parity.py, integration/test_server_sync.py, integration/test_store_config.py, system/test_e2e_ticket_coverage.py, system/test_server_launch.py | DEMOS.md |
| `FEAT-SERVER-006` | integration/test_db.py, integration/test_provider_secret.py, integration/test_server_gitsync.py, integration/test_server_store_parity.py, integration/test_server_sync.py, integration/test_store_config.py, system/test_gitrepo_sync_e2e.py, system/test_server_launch.py, unit/test_gitauth.py, unit/test_secrets.py | DEMOS.md |
| `FEAT-SERVER-007` | integration/test_db.py, system/test_server_launch.py | DEMOS.md |
| `FEAT-SERVER-008` | integration/test_server.py, integration/test_server_store_parity.py, system/test_demo_e2e.py, system/test_e2e_ticket_coverage.py, system/test_server_launch.py | DEMOS.md |
| `FEAT-SERVER-009` | integration/test_server_sync.py, integration/test_store_config.py, system/test_demo_e2e.py, system/test_standalone.py | DEMOS.md |
| `FEAT-SERVER-010` | integration/test_editable_tree.py, integration/test_server_sync.py, integration/test_store_config.py, system/test_demo_e2e.py, system/test_standalone.py | DEMOS.md |
| `FEAT-SERVER-011` | integration/test_config_edits_routes.py, integration/test_generate.py, integration/test_store_config.py, unit/test_config_edits.py | DEMOS.md |
| `FEAT-SERVER-012` | integration/test_generate.py, system/test_demo_walkthrough.py | DEMOS.md |
| `FEAT-SERVER-013` | integration/test_apply_fix.py, system/test_demo_walkthrough.py | DEMOS.md |
| `FEAT-SERVER-014` | integration/test_editable_tree.py, system/test_demo_e2e.py, system/test_standalone.py | DEMOS.md |
| `FEAT-SERVER-015` | integration/test_server.py, system/test_demo_e2e.py, system/test_standalone.py | DEMOS.md |
| `FEAT-SERVER-016` | integration/test_templates_v2.py | DEMOS.md |
| `FEAT-SERVER-017` | system/test_cli.py, system/test_example_external.py, unit/test_registry.py | DEMOS.md |
| `FEAT-SERVER-018` | system/test_cli_sync.py | DEMOS.md |
| `FEAT-SERVER-019` | integration/test_server.py | DEMOS.md |
| `FEAT-SETTINGS-001` | unit/test_settings.py | DEMOS.md |
| `FEAT-SETTINGS-002` | unit/test_settings.py | DEMOS.md |
| `FEAT-SETTINGS-003` | unit/test_settings.py | DEMOS.md |
| `FEAT-SETTINGS-004` | integration/test_server_settings.py | DEMOS.md |
| `FEAT-SETTINGS-005` | integration/test_server_settings.py | DEMOS.md |
| `FEAT-SETTINGS-006` | integration/test_server_settings.py | DEMOS.md |
| `FEAT-SETTINGS-007` | integration/test_server_settings.py | DEMOS.md |
| `FEAT-SETTINGS-008` | system/test_settings_cli.py | DEMOS.md |
| `FEAT-STALENESS-001` | unit/test_staleness.py | DEMOS.md |
| `FEAT-STALENESS-002` | unit/test_staleness.py | DEMOS.md |
| `FEAT-STALENESS-003` | unit/test_staleness.py | DEMOS.md |
| `FEAT-STALENESS-004` | system/test_staleness_cli.py | DEMOS.md |
| `FEAT-STALENESS-005` | integration/test_staleness_server.py | DEMOS.md |
| `FEAT-STALENESS-006` | integration/test_staleness_server.py, system/test_demo_e2e.py | DEMOS.md |
| `FEAT-WORKLIST-001` | integration/test_worklist_server.py, system/test_worklist_cli.py, unit/test_worklist.py | DEMOS.md |

## Gaps

None — every feature has at least one test and one demo.
