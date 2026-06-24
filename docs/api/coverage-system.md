---
cdm:
  audience: eng-guide
  fingerprint: 0fcc2a58c16a72d9
  fingerprint_tiers:
    composite: 0fcc2a58c16a72d9
    docstring: dbb21710739ecb71
    signature: 9c42d71c49d57a48
  region_anchors:
    symbols:
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 0a00684f58d55fb2
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 0b1efd3918e93d36
    - 0d2ea7328ecf80d3
    - 14360f8e77a83e3b
    - 1806ec6f4332752f
    - 19d970d62be117c8
    - 1b781ce08f7f383e
    - 1f478039981ec67a
    - 28e334513f048254
    - 2b1c7b749aa1db9e
    - 2c3a315a764aa111
    - 2dae765203afe6c5
    - 34334567f8fc4ede
    - 3920de84732eea78
    - 3a9f60b22e1d58ff
    - 427afbd939cfaab7
    - '4378315705150641'
    - 487c77375bf56e8e
    - 4bb7544f582c78bb
    - 4ec889db5ffabb51
    - 586156833bfe91d6
    - 587bbbca22cfe971
    - 591e52541f62a54b
    - 67a05c12dcf6fc16
    - 6ae91c1e3dfb0110
    - 6df6dbb794e027fc
    - 74fc029dfd6da994
    - 758f487fe8e9fcc5
    - 76350496c0742633
    - 78e6f4adcfaeb0b7
    - 7a544cef931f264e
    - 7ad564ee6eb9440b
    - 7d557c38ede78f03
    - 7dfb1e0cf30ef6a6
    - 80355d08016cb600
    - 86f1cfd890083f71
    - 96d81dfc954ed1d1
    - 98abd7deb3704062
    - 9b2cb3e08a55927c
    - 9b65a806fdded268
    - 9cf2dab4f3165cc4
    - a0349ffb70fca838
    - b13b21cc700ecdf8
    - b1accca467354d09
    - b82edecb7b28df76
    - becdfe67c10eaffd
    - ceb64a017275373b
    - d3f8b859a1d6f6e6
    - ebc5463059b9e69c
    - f3ed7c6531101567
    - f5360eea84dad3bf
    - f5cdddaecbe5e409
  region_hashes:
    symbols: 88c39ba5596976d6
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
| _GENERATED_BY | variable | _GENERATED_BY = 'cdx rpt' |
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
