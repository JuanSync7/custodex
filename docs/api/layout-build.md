---
cdm:
  audience: eng-guide
  fingerprint: 09074a22c5ac2086
  fingerprint_tiers:
    composite: 09074a22c5ac2086
    docstring: a4cbc7432a38d3b4
    signature: 148704f70f48ac5c
  region_anchors:
    symbols:
    - 051af376199dec21
    - 051af376199dec21
    - 051af376199dec21
    - 0a117288e3ad5fd9
    - 121fac4abbd395e7
    - 1aa85dcdb820ad6f
    - 1c09754ba01a0bd4
    - 25a91541a80c2db7
    - 28f3b5bece254269
    - 32466863d59a837d
    - 3263bf02338e3642
    - 32b4643f68a7fb0c
    - 39f44ada4b1c867f
    - 428e940464772b56
    - 44575cf5b28512d7
    - 455bc0c616969849
    - 4bd9dfdca395b1c2
    - 50faa59c28359a81
    - 57e95573338b8c2c
    - 595c2ade54f041a6
    - 7090147ceb0f13e4
    - 76c672648868806c
    - 80e1f0d22cb730d7
    - 813af547c4b32143
    - 860a6a26aa433f4d
    - 8ab7c9f466a0a9ad
    - 900cc34005e4e6c4
    - 91bc38b860278093
    - 939970728c990620
    - 97ecb5831b1569a9
    - a31e15ecaa50a231
    - a5f2ce7571108068
    - a65e8494c7b4ebcb
    - ac85cf40a716ad95
    - b2f96f3352bc541f
    - b7b052ea09395beb
    - b896315011001453
    - bd8d37ebab94dcc2
    - c14470b3f3fd6751
    - c26192c331298b0c
    - c898a6e5d78245c2
    - c9d11b2748b2f916
    - d3b8fd43b3f1bdf7
    - d4850c3b92cc3267
    - d94a531b0edeebe3
    - e48bb07ca2299726
    - e8cba50f7965bea9
    - f13cd8f9638ef83f
    - fb63866c577db827
    - fe988deeef5014be
  region_hashes:
    symbols: 7c71fc9ce96c9720
  schema_version: 1.0.0
---
# layout-build

> The doc-rendering surface: render `source='index'` collection regions
> (`index`), emit derived HTML twins (`build`), and lint a document's shape
> against the Layout Standard plus scaffold conformant new docs (`layout`).

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| INDEX_SOURCE | variable | INDEX_SOURCE = 'index' |
| LAYOUT_VERSION | variable | LAYOUT_VERSION = '1.0.0' |
| LayoutCode | class | class LayoutCode(str, Enum) |
| LayoutIssue | class | class LayoutIssue(BaseModel) |
| RegionState | class | class RegionState(BaseModel) |
| _BOLD | variable | _BOLD = re.compile('\\\\*\\\\*([^*]+)\\\\*\\\\*') |
| _CDM_MARKER | variable | _CDM_MARKER = ... |
| _CELL_SPLIT | variable | _CELL_SPLIT = re.compile('(?<!\\\\\\\\)\\\\\|') |
| _CODE | variable | _CODE = re.compile('`([^`]+)`') |
| _HEADING | variable | _HEADING = re.compile('^(#{1,6})\\\\s+(.*)$') |
| _HR | variable | _HR = re.compile('^(-{3,}\|\\\\*{3,}\|_{3,})$') |
| _LINK | variable | _LINK = re.compile('\\\\[([^\\\\]]+)\\\\]\\\\(([^)]+)\\\\)') |
| _MD_HASH_RE | variable | _MD_HASH_RE = ... |
| _OLI | variable | _OLI = re.compile('^\\\\d+\\\\.\\\\s+') |
| _PAGE | variable | _PAGE = ... |
| _SLUG_STRIP | variable | _SLUG_STRIP = re.compile('[^a-z0-9]+') |
| _TABLE_SEP | variable | _TABLE_SEP = re.compile('^\\\\s*\\\\\|?[\\\\s:\|-]+\\\\\|?\\\\s*$') |
| _ULI | variable | _ULI = re.compile('^[-*+]\\\\s+') |
| __all__ | variable | __all__ = ['render_markdown', 'build'] |
| __all__ | variable | __all__ = ['INDEX_SOURCE', 'render_index'] |
| __all__ | variable | __all__ = ... |
| _cdm_meta | function | def _cdm_meta(doc: Doc) -> dict[str, object] |
| _cell | function | def _cell(text: str) -> str |
| _doc_title | function | def _doc_title(body: str, fallback: str) -> str |
| _fields | function | def _fields(index_spec: DocumentSpec, target: DocumentSpec, root: Path) -> dict[str, str] |
| _index_coverage_issues | function | def _index_coverage_issues(config: MonitorConfig, root: Path) -> list[LayoutIssue] |
| _index_link_targets | function | def _index_link_targets(index_spec: DocumentSpec, target: DocumentSpec) -> set[str] |
| _indexed_audiences | function | def _indexed_audiences(spec: DocumentSpec, config: MonitorConfig) -> set[str] \| None |
| _inline | function | def _inline(text: str) -> str |
| _link | function | def _link(index_spec: DocumentSpec, target: DocumentSpec) -> str |
| _md_href_to_html | function | def _md_href_to_html(target: str) -> str |
| _nav | function | def _nav(html_docs: list[tuple[DocumentSpec, str]], current: DocumentSpec) -> str |
| _render_table | function | def _render_table(header: list[str], rows: list[list[str]]) -> str |
| _slug | function | def _slug(text: str) -> str |
| _split_row | function | def _split_row(line: str) -> list[str] |
| _structure_issues | function | def _structure_issues(spec: DocumentSpec, body: str) -> list[LayoutIssue] |
| _title_and_summary | function | def _title_and_summary(body: str) -> tuple[str, str] |
| build | function | def build(config: MonitorConfig, config_dir: Path) -> list[Path] |
| config_region_states | function | def config_region_states(config: MonitorConfig, config_dir: Path) -> list[RegionState] |
| embedded_md_hash | function | def embedded_md_hash(html: str) -> str \| None |
| html_twin_path | function | def html_twin_path(md_path: str) -> str |
| lint_config | function | def lint_config(config: MonitorConfig, config_dir: Path) -> list[LayoutIssue] |
| lint_doc | function | def lint_doc(doc: Doc, spec: DocumentSpec) -> list[LayoutIssue] |
| lint_html_twin | function | def lint_html_twin(md_body: str, html_text: str \| None, *, doc_id: str, html_path: str) -> list[LayoutIssue] |
| md_source_hash | function | def md_source_hash(md_text: str) -> str |
| region_states | function | def region_states(doc: Doc, spec: DocumentSpec, *, known: frozenset[str]) -> list[RegionState] |
| render_index | function | def render_index(template: RegionTemplate, index_spec: DocumentSpec, config: MonitorConfig, root: Path) -> str |
| render_markdown | function | def render_markdown(md: str) -> str |
| scaffold_doc | function | def scaffold_doc(spec: DocumentSpec, surface: DocumentSurface, *, include_body: bool = False) -> str |
| stamp_doc_meta | function | def stamp_doc_meta(doc: Doc, spec: DocumentSpec) -> str |
<!-- CDM:END symbols -->
