---
cdm:
  audience: eng-guide
  fingerprint: 8242a090b65a4375
  fingerprint_tiers:
    composite: 8242a090b65a4375
    docstring: 1a4a1e5a6af645d6
    signature: 5fb88207d63bea31
  region_anchors:
    symbols:
    - 004e9ebd1915d8c9
    - 02d43e3b1f07ef35
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 0712dcd00be0a81f
    - 0a12e5898c92bfc6
    - 0c27f67f2c31b80d
    - 0e521d4fec62ad6d
    - 10025d4ecda1075d
    - 113d887bd2c19dd6
    - 136d9c181ab496c9
    - 159e0d8feb35472d
    - 1a23f568636ee3df
    - 1e07ea56a9427118
    - 1ec4f05521a7e7b1
    - 288dfcba0083016a
    - 2b6d39ab2be6b34d
    - 2d99c0e7975fe9ad
    - 302733cd18785ad9
    - 3263bf02338e3642
    - 35e3a6277907b11f
    - 364bbe729c337185
    - 3808bf2494e6a6d5
    - 3b0ad2a2d6bcde10
    - 3e36acf3f35aaf6d
    - 40092567da6296d3
    - 43b3558a3373be6b
    - 44cec81ef175f533
    - 47171524a9611928
    - 49f4e57c2625d4ae
    - 4ba36c7d585f5ba6
    - 4c0e77012c5bd916
    - 4d0f131e6154f657
    - 4ddbfadee5502368
    - 4f16ebaf7eaa6ec6
    - 55fc83051d88bf5d
    - 57c90323dcf86a86
    - 5943cd04645293aa
    - 59f467abbc21ec6e
    - 5bd2d418572469ea
    - 5c782ed8831611b8
    - 6035b3d7a6bf2f06
    - 69cde016e060557f
    - 6a0a75b77a742aa8
    - 6f3a5aa1e95b414e
    - 74ae6b0e62e83c24
    - 76678d385d32f282
    - 76f15f4722cb0940
    - 775d4b61d2a56f3b
    - 79b617cc6f1be0fd
    - 7fd0737abe5f54c6
    - 80525ce65b460521
    - 8321704f2df523e7
    - 899dae061ed4d088
    - 8b4c82401c9c9ece
    - 8cf2f5b57de3a251
    - 959abcca1c243b68
    - 96f0fd1a02672602
    - 9b90157bb848360d
    - a0437059f483f15e
    - a856e8f87099101c
    - a86351dd510278f3
    - a9ce5af3358d811d
    - aa6dd30c353e6f30
    - ae65d5e6c2bbc28e
    - b6266548bc12c221
    - ba0e4afa93400b80
    - ba3e33f1d5e43c48
    - bfdd510698ef3ccb
    - c103ef8a6b38f57b
    - c13511dd9759c3e9
    - c1faae7f8b52fd67
    - c251c41353f1ee0c
    - c4d866abae595c15
    - c59d75f794f2c316
    - cc36abe96137112e
    - cd5653449960afec
    - cfa1c5fc66e83838
    - cfacfd3ec33b9608
    - d196cdaed851bfc1
    - d2426a2018658d8f
    - d2b3e82b6f007167
    - d32e474046e5b6ed
    - d34fc1bf1a20ee7f
    - d5f141037bc764e7
    - d84177d85803ae60
    - d9d7946672ac11e4
    - da2b2b25df3784d9
    - dc6dfac078d0a936
    - e7a4f972c13bfd21
    - e8300f9f77ae5e83
    - e89c414d9074bd9a
    - f2377e72f2b44883
    - f5b46fe8829dbc03
    - f6efd327d3c62610
    - fa4842e3b1aaf938
    - fb7f1b86375d74b7
  region_hashes:
    symbols: e7105c6309853667
  schema_version: 1.0.0
---
# code-doc-monitor — pipeline (engineering reference)

> Auto-maintained by code-doc-monitor itself (dogfood). The prose is human;
> the symbol table below is generated from the code and kept in sync.

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| Doc | class | class Doc(BaseModel) |
| DocumentSurface | class | class DocumentSurface(BaseModel) |
| DocumentSurface.fingerprint | method | def fingerprint(self, *, include_body: bool = False) -> SurfaceFingerprint |
| DocumentSurface.surface_hash | method | def surface_hash(self, *, include_body: bool = False) -> str |
| Drift | class | class Drift(BaseModel) |
| DriftKind | class | class DriftKind(str, Enum) |
| DriftReport | class | class DriftReport(BaseModel) |
| DriftReport.ok | method | def ok(self) -> bool |
| DriftReport.summary | method | def summary(self) -> str |
| Extractor | class | class Extractor(Protocol) |
| Extractor.extract | method | def extract(self, path: Path) -> list[Symbol] |
| PythonAstExtractor | class | class PythonAstExtractor |
| PythonAstExtractor.extract | method | def extract(self, path: Path) -> list[Symbol] |
| REGION_KEYS | variable | REGION_KEYS: frozenset[str] = frozenset({'symbols'}) |
| Record | class | class Record(BaseModel) |
| ShellExtractor | class | class ShellExtractor |
| ShellExtractor.extract | method | def extract(self, path: Path) -> list[Symbol] |
| SurfaceFingerprint | class | class SurfaceFingerprint(BaseModel) |
| SurfaceFingerprint.drifted_against | method | def drifted_against(self, other: SurfaceFingerprint) -> tuple[str, ...] |
| Symbol | class | class Symbol(BaseModel) |
| Symbol.anchor_id | method | def anchor_id(self) -> str |
| SymbolKind | variable | SymbolKind = ... |
| _BEGIN | variable | _BEGIN = re.compile('^<!-- CDM:BEGIN (\\\\S+) -->\\\\s*$') |
| _END | variable | _END = re.compile('^<!-- CDM:END (\\\\S+) -->\\\\s*$') |
| _EXTRACTORS | variable | _EXTRACTORS: dict[str, Extractor] = {'python': PythonAstExtractor()} |
| _FM_RE | variable | _FM_RE = ... |
| _MAX_VALUE_LEN | variable | _MAX_VALUE_LEN = 48 |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _SHELL_DEF_RE | variable | _SHELL_DEF_RE = ... |
| _SH_CASE_SWITCH | variable | _SH_CASE_SWITCH = re.compile('(--?[A-Za-z][\\\\w-]*)(?=[)\|])') |
| _SH_GETOPTS | variable | _SH_GETOPTS = ... |
| _SUFFIX_LANG | variable | _SUFFIX_LANG = ... |
| _SWITCHLIKE | variable | _SWITCHLIKE = re.compile('^--?[A-Za-z][\\\\w-]*$') |
| _SYMBOL_LANG_BY_SUFFIX | variable | _SYMBOL_LANG_BY_SUFFIX: dict[str, str] = {'.py': 'python'} |
| _TCL_ARGV_BLOCK | variable | _TCL_ARGV_BLOCK = ... |
| _TCL_REGEXP_CLASS | variable | _TCL_REGEXP_CLASS = ... |
| _TCL_SWITCH | variable | _TCL_SWITCH = re.compile('\\\\n\\\\s*\\\\^(-\\\\w[\\\\w-]*)') |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ['DriftKind', 'Drift', 'DriftReport', 'detect'] |
| _body_ast_hash | function | def _body_ast_hash(node: ast.FunctionDef \| ast.AsyncFunctionDef) -> str |
| _cell | function | def _cell(text: str) -> str |
| _class_signature | function | def _class_signature(node: ast.ClassDef) -> str |
| _const_str | function | def _const_str(node: ast.expr \| None, max_len: int \| None = 80) -> str |
| _extract_python_symbols | function | def _extract_python_symbols(path: Path) -> list[Symbol] |
| _extract_shell_symbols | function | def _extract_shell_symbols(path: Path) -> list[Symbol] |
| _format_args | function | def _format_args(args: ast.arguments) -> str |
| _func_signature | function | def _func_signature(node: ast.FunctionDef \| ast.AsyncFunctionDef, display_name: str) -> str |
| _func_symbol | function | def _func_symbol(node: ast.FunctionDef \| ast.AsyncFunctionDef, *, name: str, display_name: str, kind: SymbolKind) -> Symbol |
| _hash_payload | function | def _hash_payload(payload: dict[str, object]) -> str |
| _is_argvish | function | def _is_argvish(node: ast.AST) -> bool |
| _is_public | function | def _is_public(name: str) -> bool |
| _positional_names | function | def _positional_names(args: ast.arguments) -> tuple[str, ...] |
| _py_switches | function | def _py_switches(text: str, path: Path) -> set[str] |
| _record_cell | function | def _record_cell(col: RegionColumn, rec: Record) -> str |
| _records_for_ref | function | def _records_for_ref(ref: CodeRef, root: Path) -> list[Record] |
| _row | function | def _row(sym: Symbol) -> str |
| _select | function | def _select(symbols: list[Symbol], ref_symbols: tuple[str, ...], ref_lines: tuple[tuple[int, int], ...], ref_names: tuple[str, ...]) -> list[Symbol] |
| _sh_switches | function | def _sh_switches(text: str) -> set[str] |
| _shell_block_end | function | def _shell_block_end(lines: list[str], start_idx: int, start_col: int) -> int |
| _shell_docstring | function | def _shell_docstring(lines: list[str], header_idx: int) -> str \| None |
| _short_diff | function | def _short_diff(expected: str, actual: str, region_id: str) -> str |
| _switch_strings | function | def _switch_strings(node: ast.AST) -> list[str] |
| _symbol_cell | function | def _symbol_cell(col: RegionColumn, sym: Symbol) -> str |
| _symbol_language | function | def _symbol_language(ref: CodeRef) -> str |
| _symbols_for_ref | function | def _symbols_for_ref(ref: CodeRef, root: Path) -> list[Symbol] |
| _tcl_switches | function | def _tcl_switches(text: str) -> set[str] |
| _value_repr | function | def _value_repr(node: ast.expr) -> str |
| _variable_symbols | function | def _variable_symbols(node: ast.Assign \| ast.AnnAssign) -> list[Symbol] |
| anchor_id | function | def anchor_id(qualified_name: str) -> str |
| build_document_surface | function | def build_document_surface(doc: DocumentSpec, root: Path) -> DocumentSurface |
| detect | function | def detect(config: MonitorConfig, config_dir: Path) -> DriftReport |
| expected_region | function | def expected_region(region_id: str, surface: DocumentSurface, template: RegionTemplate \| None = None) -> str \| None |
| extract_argparse_records | function | def extract_argparse_records(path: Path) -> list[Record] |
| extract_file | function | def extract_file(path: Path) -> list[Symbol] |
| extract_json_records | function | def extract_json_records(path: Path, *, records_key: str, name_field: str) -> list[Record] |
| extract_switches | function | def extract_switches(path: Path, *, lang: str = 'auto') -> list[Record] |
| get_extractor | function | def get_extractor(language: str) -> Extractor |
| known_region_ids | function | def known_region_ids(templates: Mapping[str, RegionTemplate] \| None = None) -> frozenset[str] |
| parse_doc | function | def parse_doc(path: Path) -> Doc |
| parse_text | function | def parse_text(raw: str, path: Path \| None = None) -> Doc |
| region_body_hash | function | def region_body_hash(body: str) -> str |
| region_is_locked | function | def region_is_locked(doc: Doc, region_id: str, current_body: str) -> bool |
| regions | function | def regions(doc: Doc) -> dict[str, str] |
| register_extractor | function | def register_extractor(extractor: Extractor, *, suffixes: tuple[str, ...] = ()) -> None |
| render_doc | function | def render_doc(meta: dict[str, Any], body: str) -> str |
| render_template | function | def render_template(template: RegionTemplate, surface: DocumentSurface) -> str |
| set_fingerprint | function | def set_fingerprint(meta: dict[str, Any], value: str) -> dict[str, Any] |
| set_fingerprint_tiers | function | def set_fingerprint_tiers(meta: dict[str, Any], fp: SurfaceFingerprint) -> dict[str, Any] |
| set_region | function | def set_region(body: str, id: str, new: str) -> tuple[str, bool] |
| set_region_anchors | function | def set_region_anchors(meta: dict[str, Any], region_id: str, anchors: tuple[str, ...]) -> dict[str, Any] |
| set_region_hash | function | def set_region_hash(meta: dict[str, Any], region_id: str, value: str) -> dict[str, Any] |
| stamp_standard_meta | function | def stamp_standard_meta(meta: dict[str, Any], *, schema_version: str, audience: str) -> dict[str, Any] |
| stored_fingerprint | function | def stored_fingerprint(doc: Doc) -> str \| None |
| stored_fingerprint_tiers | function | def stored_fingerprint_tiers(doc: Doc) -> SurfaceFingerprint \| None |
| stored_region_anchors | function | def stored_region_anchors(doc: Doc, region_id: str) -> tuple[str, ...] \| None |
| stored_region_hash | function | def stored_region_hash(doc: Doc, region_id: str) -> str \| None |
| symbol_table | function | def symbol_table(surface: DocumentSurface) -> str |
<!-- CDM:END symbols -->
