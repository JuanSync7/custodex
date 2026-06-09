---
cdm:
  audience: eng-guide
  fingerprint: c517174e060739b2
  region_hashes:
    symbols: fd9462ac5f4b71ff
  schema_version: 1.0.0
---
# coverage-system

> EPIC A coverage ownership: discover the repo's code files + symbols
> (`inventory`) and cross them against the documents' code refs to compute,
> losslessly, what is documented vs an undocumented (or waived) gap (`coverage`).

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| CDMON_REPORT_VERSION | variable | CDMON_REPORT_VERSION = '1.0.0' |
| CodeFile | class | class CodeFile(BaseModel) |
| CoverageReport | class | class CoverageReport(BaseModel) |
| CoverageReport.documented_files | method | def documented_files(self) -> tuple[OwnedFile, ...] |
| CoverageReport.documented_symbols | method | def documented_symbols(self) -> tuple[OwnedSymbol, ...] |
| CoverageReport.percent_files | method | def percent_files(self) -> float |
| CoverageReport.percent_public_symbols | method | def percent_public_symbols(self) -> float |
| CoverageReport.undocumented_files | method | def undocumented_files(self) -> tuple[OwnedFile, ...] |
| CoverageReport.undocumented_symbols | method | def undocumented_symbols(self) -> tuple[OwnedSymbol, ...] |
| CoverageReport.waived_files | method | def waived_files(self) -> tuple[OwnedFile, ...] |
| CoverageReport.waived_symbols | method | def waived_symbols(self) -> tuple[OwnedSymbol, ...] |
| CoverageRpt | class | class CoverageRpt(BaseModel) |
| DEFAULT_EXCLUDE | variable | DEFAULT_EXCLUDE: tuple[str, ...] = ('**/.*/**', '**/__pycache__/**', '**/.venv/**') |
| DEFAULT_INCLUDE | variable | DEFAULT_INCLUDE: tuple[str, ...] = ('**/*.py',) |
| FileSymbols | class | class FileSymbols(BaseModel) |
| Inventory | class | class Inventory(BaseModel) |
| OwnedFile | class | class OwnedFile(BaseModel) |
| OwnedSymbol | class | class OwnedSymbol(BaseModel) |
| OwnerSuggestion | class | class OwnerSuggestion(BaseModel) |
| RptSummary | class | class RptSummary(BaseModel) |
| RptUndocumented | class | class RptUndocumented(BaseModel) |
| RptUnit | class | class RptUnit(BaseModel) |
| SymbolInventory | class | class SymbolInventory(BaseModel) |
| _GENERATED_BY | variable | _GENERATED_BY = 'cdmon rpt' |
| _LANGUAGE_BY_EXT | variable | _LANGUAGE_BY_EXT: dict[str, str] = {'.py': 'python', '.pyi': 'python'} |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| _build_units | function | def _build_units(bundle: ConfigBundle, report: coverage_mod.CoverageReport) -> tuple[RptUnit, ...] |
| _count_ignored | function | def _count_ignored(bundle: ConfigBundle, repo_root: Path, include: tuple[str, ...], universe_size: int) -> int |
| _ext | function | def _ext(path: str) -> str |
| _file_for_unit | function | def _file_for_unit(bundle: ConfigBundle, unit: UnitFile) -> str |
| _fmt_percent | function | def _fmt_percent(value: float \| None) -> str |
| _language_for | function | def _language_for(rel_path: str) -> str |
| _matches_any | function | def _matches_any(rel_path: str, patterns: tuple[re.Pattern[str], ...]) -> bool |
| _parse_percent | function | def _parse_percent(value: object) -> float \| None |
| _path_under | function | def _path_under(path: str, directory: str) -> bool |
| _percent | function | def _percent(documented: int, universe: int) -> float \| None |
| _proposed_doc_id | function | def _proposed_doc_id(path: str) -> str |
| _sorted_owners | function | def _sorted_owners(owners: set[str]) -> tuple[str, ...] |
| _split_rpt | function | def _split_rpt(text: str) -> tuple[dict, str] |
| _suggest_unit | function | def _suggest_unit(bundle: ConfigBundle, path: str) -> tuple[str \| None, str] |
| _translate | function | def _translate(pattern: str) -> re.Pattern[str] |
| _waiver_reason | function | def _waiver_reason(waivers: tuple[tuple[re.Pattern[str], WaiverEntry], ...], path: str, symbol: str \| None) -> str \| None |
| _yaml_scalar | function | def _yaml_scalar(value: str) -> str |
| build_coverage_rpt | function | def build_coverage_rpt(bundle: ConfigBundle, repo_root: Path, *, ref: str \| None) -> CoverageRpt |
| coverage_snapshot | function | def coverage_snapshot(report: CoverageReport) -> dict |
| discover_files | function | def discover_files(root: Path, *, include: tuple[str, ...] = DEFAULT_INCLUDE, exclude: tuple[str, ...] = DEFAULT_EXCLUDE) -> Inventory |
| discover_symbols | function | def discover_symbols(inventory: Inventory, root: Path) -> SymbolInventory |
| parse_rpt | function | def parse_rpt(text: str) -> CoverageRpt |
| render_rpt | function | def render_rpt(rpt: CoverageRpt) -> str |
| report_repo_root | function | def report_repo_root(config_dir: Path, bundle: ConfigBundle) -> Path |
| resolve_coverage | function | def resolve_coverage(config: MonitorConfig, inv: SymbolInventory) -> CoverageReport |
| suggest_owners | function | def suggest_owners(report: CoverageReport, config: MonitorConfig) -> tuple[OwnerSuggestion, ...] |
| write_rpt | function | def write_rpt(config_dir: Path, text: str) -> None |
<!-- CDM:END symbols -->
