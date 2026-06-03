---
cdm:
  audience: eng-guide
  fingerprint: 5fc3f74151bb0d5c
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
| DocumentSurface.surface_hash | method | def surface_hash(self) -> str |
| Drift | class | class Drift(BaseModel) |
| DriftKind | class | class DriftKind(str, Enum) |
| DriftReport | class | class DriftReport(BaseModel) |
| DriftReport.ok | method | def ok(self) -> bool |
| DriftReport.summary | method | def summary(self) -> str |
| REGION_KEYS | variable | REGION_KEYS: frozenset[str] = frozenset({'symbols'}) |
| Record | class | class Record(BaseModel) |
| Symbol | class | class Symbol(BaseModel) |
| SymbolKind | variable | SymbolKind = ... |
| _BEGIN | variable | _BEGIN = re.compile('^<!-- CDM:BEGIN (\\\\S+) -->\\\\s*$') |
| _END | variable | _END = re.compile('^<!-- CDM:END (\\\\S+) -->\\\\s*$') |
| _FM_RE | variable | _FM_RE = ... |
| _MAX_VALUE_LEN | variable | _MAX_VALUE_LEN = 48 |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _SH_CASE_SWITCH | variable | _SH_CASE_SWITCH = re.compile('(--?[A-Za-z][\\\\w-]*)(?=[)\|])') |
| _SH_GETOPTS | variable | _SH_GETOPTS = ... |
| _SUFFIX_LANG | variable | _SUFFIX_LANG = ... |
| _SWITCHLIKE | variable | _SWITCHLIKE = re.compile('^--?[A-Za-z][\\\\w-]*$') |
| _TCL_ARGV_BLOCK | variable | _TCL_ARGV_BLOCK = ... |
| _TCL_REGEXP_CLASS | variable | _TCL_REGEXP_CLASS = ... |
| _TCL_SWITCH | variable | _TCL_SWITCH = re.compile('\\\\n\\\\s*\\\\^(-\\\\w[\\\\w-]*)') |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ... |
| __all__ | variable | __all__ = ['DriftKind', 'Drift', 'DriftReport', 'detect'] |
| _cell | function | def _cell(text: str) -> str |
| _class_signature | function | def _class_signature(node: ast.ClassDef) -> str |
| _const_str | function | def _const_str(node: ast.expr \| None, max_len: int \| None = 80) -> str |
| _format_args | function | def _format_args(args: ast.arguments) -> str |
| _func_signature | function | def _func_signature(node: ast.FunctionDef \| ast.AsyncFunctionDef, display_name: str) -> str |
| _func_symbol | function | def _func_symbol(node: ast.FunctionDef \| ast.AsyncFunctionDef, *, name: str, display_name: str, kind: SymbolKind) -> Symbol |
| _is_argvish | function | def _is_argvish(node: ast.AST) -> bool |
| _is_public | function | def _is_public(name: str) -> bool |
| _positional_names | function | def _positional_names(args: ast.arguments) -> tuple[str, ...] |
| _py_switches | function | def _py_switches(text: str, path: Path) -> set[str] |
| _record_cell | function | def _record_cell(col: RegionColumn, rec: Record) -> str |
| _records_for_ref | function | def _records_for_ref(ref: CodeRef, root: Path) -> list[Record] |
| _row | function | def _row(sym: Symbol) -> str |
| _select | function | def _select(symbols: list[Symbol], ref_symbols: tuple[str, ...], ref_lines: tuple[tuple[int, int], ...], ref_names: tuple[str, ...]) -> list[Symbol] |
| _sh_switches | function | def _sh_switches(text: str) -> set[str] |
| _short_diff | function | def _short_diff(expected: str, actual: str, region_id: str) -> str |
| _switch_strings | function | def _switch_strings(node: ast.AST) -> list[str] |
| _symbol_cell | function | def _symbol_cell(col: RegionColumn, sym: Symbol) -> str |
| _symbols_for_ref | function | def _symbols_for_ref(ref: CodeRef, root: Path) -> list[Symbol] |
| _tcl_switches | function | def _tcl_switches(text: str) -> set[str] |
| _value_repr | function | def _value_repr(node: ast.expr) -> str |
| _variable_symbols | function | def _variable_symbols(node: ast.Assign \| ast.AnnAssign) -> list[Symbol] |
| build_document_surface | function | def build_document_surface(doc: DocumentSpec, root: Path) -> DocumentSurface |
| detect | function | def detect(config: MonitorConfig, config_dir: Path) -> DriftReport |
| expected_region | function | def expected_region(region_id: str, surface: DocumentSurface, template: RegionTemplate \| None = None) -> str \| None |
| extract_argparse_records | function | def extract_argparse_records(path: Path) -> list[Record] |
| extract_file | function | def extract_file(path: Path) -> list[Symbol] |
| extract_json_records | function | def extract_json_records(path: Path, *, records_key: str, name_field: str) -> list[Record] |
| extract_switches | function | def extract_switches(path: Path, *, lang: str = 'auto') -> list[Record] |
| known_region_ids | function | def known_region_ids(templates: Mapping[str, RegionTemplate] \| None = None) -> frozenset[str] |
| parse_doc | function | def parse_doc(path: Path) -> Doc |
| parse_text | function | def parse_text(raw: str, path: Path \| None = None) -> Doc |
| regions | function | def regions(doc: Doc) -> dict[str, str] |
| render_doc | function | def render_doc(meta: dict[str, Any], body: str) -> str |
| render_template | function | def render_template(template: RegionTemplate, surface: DocumentSurface) -> str |
| set_fingerprint | function | def set_fingerprint(meta: dict[str, Any], value: str) -> dict[str, Any] |
| set_region | function | def set_region(body: str, id: str, new: str) -> tuple[str, bool] |
| stamp_standard_meta | function | def stamp_standard_meta(meta: dict[str, Any], *, schema_version: str, audience: str) -> dict[str, Any] |
| stored_fingerprint | function | def stored_fingerprint(doc: Doc) -> str \| None |
| symbol_table | function | def symbol_table(surface: DocumentSurface) -> str |
<!-- CDM:END symbols -->
