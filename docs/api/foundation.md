---
cdm:
  audience: eng-guide
  fingerprint: 0e78535dfd49a547
  schema_version: 1.0.0
---
# code-doc-monitor — foundation (engineering reference)

> Auto-maintained by code-doc-monitor itself (dogfood). The prose is human;
> the symbol table below is generated from the code and kept in sync.

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| Audience | class | class Audience(str, Enum) |
| BackendConfig | class | class BackendConfig(BaseModel) |
| BackendError | class | class BackendError(CodeDocMonitorError) |
| CONFIG_TEMPLATE | variable | CONFIG_TEMPLATE = ... |
| CentralConfig | class | class CentralConfig(BaseModel) |
| CodeDocMonitorError | class | class CodeDocMonitorError(Exception) |
| CodeRef | class | class CodeRef(BaseModel) |
| ConfigError | class | class ConfigError(CodeDocMonitorError) |
| DocumentSpec | class | class DocumentSpec(BaseModel) |
| DriftError | class | class DriftError(CodeDocMonitorError) |
| ExtractionError | class | class ExtractionError(CodeDocMonitorError) |
| MonitorConfig | class | class MonitorConfig(BaseModel) |
| ProposedFix | class | class ProposedFix(BaseModel) |
| RegionColumn | class | class RegionColumn(BaseModel) |
| RegionTemplate | class | class RegionTemplate(BaseModel) |
| SchemaError | class | class SchemaError(CodeDocMonitorError) |
| Verdict | class | class Verdict(str, Enum) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| load_config | function | def load_config(path: Path) -> MonitorConfig |
| write_template | function | def write_template(path: Path) -> None |
<!-- CDM:END symbols -->
