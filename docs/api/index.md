---
cdm:
  audience: eng-guide
  fingerprint: 3ff338fd4193d23f
  region_hashes:
    api-index: 9b888eef0222f709
  schema_version: 1.0.0
---
# code-doc-monitor — engineering docs

> Index of the engineering reference docs for this package — each is auto-maintained in sync with the code it documents.

<!-- CDM:BEGIN api-index -->
| Document | What it covers |
|---|---|
| [agent-workflow](agent-workflow.md) | The deterministic LangGraph remediation agent: the `Backend`-shaped entry (`backend`), the graph wiring + artifact selection/context (`graph`), the prompt library (`prompts`), the runtime/driver leaf (`runtime`), and the graph's shared state (`state`). |
| [code-doc-monitor — foundation (engineering reference)](foundation.md) | Auto-maintained by code-doc-monitor itself (dogfood). The prose is human; the symbol table below is generated from the code and kept in sync. |
| [code-doc-monitor — pipeline (engineering reference)](pipeline.md) | Auto-maintained by code-doc-monitor itself (dogfood). The prose is human; the symbol table below is generated from the code and kept in sync. |
| [code-doc-monitor — remediation (engineering reference)](remediation.md) | Auto-maintained by code-doc-monitor itself (dogfood). The prose is human; the symbol table below is generated from the code and kept in sync. |
| [coverage-system](coverage-system.md) | EPIC A coverage ownership: discover the repo's code files + symbols (`inventory`) and cross them against the documents' code refs to compute, losslessly, what is documented vs an undocumented (or waived) gap (`coverage`). |
| [layout-build](layout-build.md) | The doc-rendering surface: render `source='index'` collection regions (`index`), emit derived HTML twins (`build`), and lint a document's shape against the Layout Standard plus scaffold conformant new docs (`layout`). |
| [pr-loop](pr-loop.md) | EPIC C docs-PR loop: the structural `should-sync` loop-breaker decides whether a change warrants a heal (`syncpr`), and the host-agnostic PR client opens or updates the resulting docs pull/merge request (`pr`). |
| [central-client](central-client.md) | The central-system client side (EPIC E/G/GIT): the per-repo registry/identity that stamps which repo a review record came from before shipping it to the central ingest endpoint, plus the read-only config-sync engine and the server-side git surface — clone-on-demand, AES-GCM credential sealing, and short-lived GitHub App / GitLab OAuth token minting. |
| [learning](learning.md) | EPIC F learning loop: detect near-duplicate gaps/records (`similar`) and promote recurring, human-approved waivers and fixes into reusable config suggestions (`promotion`). |
| [ops](ops.md) | The operator surface: the `cdmon` CLI command functions that drive every subcommand (`cli`) and the `doctor` preflight that self-checks a config + environment before a run (`doctor`). |
| [server](server.md) | EPIC G central server (engineering reference): the FastAPI ingest/query app (`app`), the persistence service over review records (`store`), and the SQLAlchemy schema + session/engine layer it sits on (`db`). |
<!-- CDM:END api-index -->
