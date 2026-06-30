---
cdm:
  audience: eng-guide
  fingerprint: b99275e7121d34d4
  fingerprint_tiers:
    composite: b99275e7121d34d4
    docstring: 88a00d83aaa375f5
    signature: 408c0bf05b4d6d7a
  region_anchors:
    symbols:
    - 00652c5f721d5ef6
    - 031af45574e9fb3e
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 083c4cd04ae0a9e0
    - 08cabae98768bbac
    - 091a998373c22ca9
    - 09df7d93520d6632
    - 0a12e5898c92bfc6
    - 0b390c979393f83b
    - 0d9808ab184991ce
    - 0dad8198442ebc15
    - 147fda13f62e8d29
    - 16fa33fa4ac0dc4e
    - 17019d426b379415
    - 19599a22448b1545
    - 19f17915412b7ce2
    - 1c791cd5029fd0c8
    - 1fc476fb39fc321a
    - 203c45f1f1231235
    - 204ae77992ce6f89
    - 21366eab05e739b8
    - 2315c3ba973d34e0
    - 249c7e4c157119d2
    - 28b7f5de5919f6f2
    - 2a8f6ab973a376f0
    - 2fc7b290292b119c
    - 38227910a6a11440
    - 38527a9330f2dad5
    - 3920de84732eea78
    - 3920de84732eea78
    - 3ab8177372b53700
    - 3bdccdb6b130b338
    - 3e00b4ad560e5de7
    - 4054d8813d8e592f
    - 419b5f4b65b9c5f5
    - 4a2ca79bf708f89c
    - 4a36f89dafb0a101
    - 4f4f218b97d301a9
    - 5164fe30f50e30c5
    - 53878c6848eafd81
    - 545c02357695a6ff
    - 55c1a3c88cf92236
    - 572b9f66ffa43300
    - 582b027d421386db
    - 5c4c5ccabaf45fe2
    - 5f31511731a8d710
    - 5f3888a5d6d1f3a2
    - 6509a508c42b1144
    - 67280832bd5a56c8
    - 67768f80fff0ce41
    - 68abb78557da6b6c
    - 6bf33eee2fe93f9a
    - 6f1ffff66d35b774
    - 70df2bfd15daec86
    - 736a7fe906bf0129
    - 75694f3fe0d8b961
    - 7df536c744fd43fd
    - 81ffd1cd4b050ef8
    - 863a84e157e513f4
    - 87f90da1f29b87a9
    - 8ad81f9afab07be3
    - 8afc54eff24079b4
    - 8cf2490a5bab614d
    - 91cd02faf8342f49
    - 944fca707b7e57f5
    - 949e83f48e041117
    - 94aa6c378eb9283c
    - 980311c056ae3045
    - 98117ea616dd3e9f
    - 991d9c74dd497040
    - 9c1e4e21a8ba9712
    - a296a735a048dacd
    - a36f1a6c53893358
    - a47dddeeda46352d
    - a6517d7d72f73eb9
    - a796ab12a30a87b3
    - a8d0d1d4bb421622
    - ad1d037438d946ee
    - ad9f6cfd78f2c1ec
    - ae498729cee35511
    - ae5836c79fbf9808
    - b0e0fabb95a65a96
    - b40f2cf93387ebe8
    - b74297b27cc94564
    - bc66577b1733cdde
    - c103ef8a6b38f57b
    - c3101973fe2f73f3
    - c3bae03d014fe39d
    - c4d17477dd8645eb
    - c64ffddedd066da9
    - c6afc1df5b422222
    - c78a0ec77c5ec1a2
    - cb740b31a08869b1
    - cbbde2c420898532
    - cca68cf1f6eb5477
    - ccf57d95e8d57977
    - d28cf7729068ff29
    - d31f855d5547d0fb
    - d44082bccab4ddaa
    - d51a1c2ad604ab2c
    - d64571b73123f484
    - d66e738995cfa86a
    - d810ee574fcee4f5
    - d97ca633fb31ebf6
    - dbd044032a4e2c02
    - dc6b6698decf6ed2
    - debba00cbcfe4db9
    - df2e40dd04dfb417
    - e035339de5fa4542
    - e11241b69221ac34
    - e261f035d021125f
    - e4efb0831dc07263
    - e877dd6b99670aaa
    - e999daf597dbc1db
    - ea567e80184e4f05
    - eb717b7c18f96b59
    - ec27d28c8129e999
    - ed1daf324b0105f2
    - f1fa30154af56704
    - f265a8df55f3cbef
    - f73185493293c1ba
    - fd87e7b303770609
    - ff51b2032355ac8b
  region_hashes:
    symbols: d687b8f301376fb4
  schema_version: 1.0.0
---
# custodex — foundation (engineering reference)

> Auto-maintained by custodex itself (dogfood). The prose is human;
> the symbol table below is generated from the code and kept in sync.

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| AgentConfig | class | class AgentConfig(BaseModel) |
| Audience | class | class Audience(str, Enum) |
| BackendConfig | class | class BackendConfig(BaseModel) |
| BackendError | class | class BackendError(CodeDocMonitorError) |
| CDMON_CONFIG_VERSION | variable | CDMON_CONFIG_VERSION = '2.0.0' |
| CONFIG_TEMPLATE | variable | CONFIG_TEMPLATE = ... |
| CatalogError | class | class CatalogError(CodeDocMonitorError) |
| CentralConfig | class | class CentralConfig(BaseModel) |
| CodeDocMonitorError | class | class CodeDocMonitorError(Exception) |
| CodeRef | class | class CodeRef(BaseModel) |
| ConfigBundle | class | class ConfigBundle(BaseModel) |
| ConfigBundle.unit_for_document | method | def unit_for_document(self, doc_id: str) -> UnitFile \| None |
| ConfigBundle.unit_for_path | method | def unit_for_path(self, repo_relative_path: str) -> UnitFile \| None |
| ConfigError | class | class ConfigError(CodeDocMonitorError) |
| ContextRef | class | class ContextRef(BaseModel) |
| CoverageConfig | class | class CoverageConfig(BaseModel) |
| DEFAULT_CENTRAL_TOKEN_ENV | variable | DEFAULT_CENTRAL_TOKEN_ENV = 'CDMON_CENTRAL_TOKEN' |
| DOC_STYLE_TEMPLATE | variable | DOC_STYLE_TEMPLATE = ... |
| DocDepsConfig | class | class DocDepsConfig(BaseModel) |
| DocEdge | class | class DocEdge(BaseModel) |
| DocEdgeType | class | class DocEdgeType(str, Enum) |
| DocStyleFrontmatter | class | class DocStyleFrontmatter(BaseModel) |
| DocStyleFrontmatter._version_and_kind | method | def _version_and_kind(self) -> DocStyleFrontmatter |
| DocStyleMap | class | class DocStyleMap(BaseModel) |
| DocStyleMap.style_for | method | def style_for(self, doc_id: str) -> DocStyleSelection |
| DocStyleMapping | class | class DocStyleMapping(BaseModel) |
| DocStyleMapping.selection | method | def selection(self) -> DocStyleSelection |
| DocStyleSelection | class | class DocStyleSelection(BaseModel) |
| DocumentSpec | class | class DocumentSpec(BaseModel) |
| DocumentSpec._context_refs_paths_unique | method | def _context_refs_paths_unique(self) -> DocumentSpec |
| DocumentSpec._depends_on_well_formed | method | def _depends_on_well_formed(self) -> DocumentSpec |
| DocumentSpec._region_modes_reference_declared_regions | method | def _region_modes_reference_declared_regions(self) -> DocumentSpec |
| DocumentSpec.mode_for | method | def mode_for(self, region_id: str) -> RegionMode |
| DriftError | class | class DriftError(CodeDocMonitorError) |
| EXAMPLE_UNIT_STEM | variable | EXAMPLE_UNIT_STEM = 'example' |
| ExtractionError | class | class ExtractionError(CodeDocMonitorError) |
| IGNORE_TEMPLATE | variable | IGNORE_TEMPLATE = ... |
| INDEX_TEMPLATE | variable | INDEX_TEMPLATE = ... |
| IgnoreFile | class | class IgnoreFile(BaseModel) |
| IgnoreFrontmatter | class | class IgnoreFrontmatter(BaseModel) |
| IgnoreFrontmatter._version_must_match | method | def _version_must_match(self) -> IgnoreFrontmatter |
| IndexFile | class | class IndexFile(BaseModel) |
| IndexFrontmatter | class | class IndexFrontmatter(BaseModel) |
| IndexFrontmatter._version_must_match | method | def _version_must_match(self) -> IndexFrontmatter |
| IndexUnitRef | class | class IndexUnitRef(BaseModel) |
| InventoryError | class | class InventoryError(CodeDocMonitorError) |
| MonitorConfig | class | class MonitorConfig(BaseModel) |
| MonitorConfig._depends_on_targets_exist | method | def _depends_on_targets_exist(self) -> MonitorConfig |
| ProposedFix | class | class ProposedFix(BaseModel) |
| RESERVED_UNIT_STEMS | variable | RESERVED_UNIT_STEMS: frozenset[str] = frozenset({'index', 'ignore', 'doc-style'}) |
| RegionColumn | class | class RegionColumn(BaseModel) |
| RegionMode | class | class RegionMode(str, Enum) |
| RegionTemplate | class | class RegionTemplate(BaseModel) |
| STYLE_CATEGORIES | variable | STYLE_CATEGORIES: tuple[tuple[str, str], ...] = ... |
| SchemaError | class | class SchemaError(CodeDocMonitorError) |
| SecretError | class | class SecretError(CodeDocMonitorError) |
| StalenessConfig | class | class StalenessConfig(BaseModel) |
| StalenessConfig._positive_days | method | def _positive_days(self) -> StalenessConfig |
| SyncError | class | class SyncError(CodeDocMonitorError) |
| TransportError | class | class TransportError(CodeDocMonitorError) |
| UNIT_TEMPLATE | variable | UNIT_TEMPLATE = ... |
| UnitFile | class | class UnitFile(BaseModel) |
| UnitFile._validate_scope | method | def _validate_scope(self) -> UnitFile |
| UnitFrontmatter | class | class UnitFrontmatter(BaseModel) |
| UnitFrontmatter._version_must_match | method | def _version_must_match(self) -> UnitFrontmatter |
| V2_TEMPLATES | variable | V2_TEMPLATES: dict[str, str] = ... |
| Verdict | class | class Verdict(str, Enum) |
| WaiverEntry | class | class WaiverEntry(BaseModel) |
| _DEFAULT_EXCLUDE | variable | _DEFAULT_EXCLUDE: tuple[str, ...] = ('**/.*/**', '**/__pycache__/**', '**/.venv/**') |
| _DEFAULT_INCLUDE | variable | _DEFAULT_INCLUDE: tuple[str, ...] = ('**/*.py',) |
| _FM_RE | variable | _FM_RE = ... |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _OFFLINE_CENTRAL_BLOCK | variable | _OFFLINE_CENTRAL_BLOCK = ... |
| _UNITS_BLOCK_RE | variable | _UNITS_BLOCK_RE = ... |
| _UPDATED_LINE_RE | variable | _UPDATED_LINE_RE = re.compile('^updated:[^\\\\n]*$', re.MULTILINE) |
| _V2_MODEL_CONFIG | variable | _V2_MODEL_CONFIG = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| _coderef_to_yaml | function | def _coderef_to_yaml(ref: CodeRef) -> dict |
| _contextref_to_yaml | function | def _contextref_to_yaml(ref: ContextRef) -> dict |
| _deepest_unit_for_parts | function | def _deepest_unit_for_parts(units: tuple[UnitFile, ...], file_parts: tuple[str, ...]) -> UnitFile \| None |
| _dir_parts | function | def _dir_parts(p: str) -> tuple[str, ...] |
| _docedge_to_yaml | function | def _docedge_to_yaml(edge: DocEdge) -> dict |
| _document_to_yaml | function | def _document_to_yaml(doc: DocumentSpec) -> dict |
| _fill | function | def _fill(template: str, *, repo: str, now: str) -> str |
| _find_doc_index | function | def _find_doc_index(unit: UnitFile, doc_id: str) -> int |
| _is_ancestor | function | def _is_ancestor(ancestor: tuple[str, ...], descendant: tuple[str, ...]) -> bool |
| _load_v2_yaml | function | def _load_v2_yaml(path: Path) -> tuple[dict, str] |
| _missing_template_files | function | def _missing_template_files(selection: DocStyleSelection, templates_root: Path, *, where: str) -> list[str] |
| _now | function | def _now() -> str |
| _parse_v2_body | function | def _parse_v2_body(body: str, path: Path) -> dict |
| _render_units_block | function | def _render_units_block(filenames: list[str]) -> str |
| _replace_documents | function | def _replace_documents(unit: UnitFile, documents: tuple[DocumentSpec, ...]) -> UnitFile |
| _resolve_repo_root | function | def _resolve_repo_root(config_dir: Path, root: str) -> Path |
| _scan_unit_files | function | def _scan_unit_files(config_dir: Path) -> list[str] |
| _selection_to_yaml | function | def _selection_to_yaml(selection: DocStyleSelection) -> dict[str, str] |
| _split_frontmatter | function | def _split_frontmatter(text: str, where: Path) -> tuple[dict, str] |
| _yaml_scalar | function | def _yaml_scalar(value: str) -> str |
| _yaml_scalar | function | def _yaml_scalar(value: str) -> str |
| add_code_ref | function | def add_code_ref(unit: UnitFile, doc_id: str, ref: CodeRef) -> UnitFile |
| central_config_template | function | def central_config_template(*, url: str, repo_id: str, token_env: str = DEFAULT_CENTRAL_TOKEN_ENV, repo_url: str \| None = None) -> str |
| dump_doc_style | function | def dump_doc_style(doc_style: DocStyleMap, *, now: str) -> str |
| dump_unit_file | function | def dump_unit_file(unit: UnitFile, *, now: str) -> str |
| effective_coverage | function | def effective_coverage(bundle: ConfigBundle, repo_root: Path) -> CoverageConfig |
| gitignore_to_globs | function | def gitignore_to_globs(text: str) -> tuple[str, ...] |
| load_bundle | function | def load_bundle(config_dir: Path) -> ConfigBundle |
| load_config | function | def load_config(path: Path) -> MonitorConfig |
| load_config_dir | function | def load_config_dir(config_dir: Path) -> MonitorConfig |
| load_doc_style | function | def load_doc_style(path: Path, *, templates_root: Path) -> DocStyleMap |
| load_ignore_file | function | def load_ignore_file(path: Path) -> IgnoreFile |
| load_index_file | function | def load_index_file(path: Path) -> IndexFile |
| load_unit_file | function | def load_unit_file(path: Path) -> UnitFile |
| read_style_guidance | function | def read_style_guidance(selection: DocStyleSelection, templates_root: Path) -> str |
| regenerate_index | function | def regenerate_index(config_dir: Path) -> str |
| remove_code_ref | function | def remove_code_ref(unit: UnitFile, doc_id: str, path: str) -> UnitFile |
| resolve_repo_root | function | def resolve_repo_root(config_dir: Path, root: str) -> Path |
| resolve_style_files | function | def resolve_style_files(selection: DocStyleSelection, templates_root: Path) -> dict[str, Path] |
| scaffold_config_dir | function | def scaffold_config_dir(config_dir: Path, *, repo: str, now: str) -> None |
| set_context_refs | function | def set_context_refs(unit: UnitFile, doc_id: str, refs: tuple[ContextRef, ...]) -> UnitFile |
| set_document_owner | function | def set_document_owner(unit: UnitFile, doc_id: str, *, owner: str \| None = None, team: str \| None = None, dri: str \| None = None) -> UnitFile |
| unit_for_path | function | def unit_for_path(bundle: ConfigBundle, repo_relative_path: str) -> UnitFile \| None |
| upsert_document | function | def upsert_document(unit: UnitFile, doc: DocumentSpec) -> UnitFile |
| write_index | function | def write_index(config_dir: Path, text: str) -> None |
| write_template | function | def write_template(path: Path, content: str \| None = None) -> None |
<!-- CDM:END symbols -->
