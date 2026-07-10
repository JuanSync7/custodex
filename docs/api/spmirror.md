---
cdm:
  audience: eng-guide
  fingerprint: d0a6a0fb88d53287
  fingerprint_tiers:
    composite: d0a6a0fb88d53287
    docstring: 74ace2e6f4d57fea
    signature: 370cb4ed3cc8db6c
  region_anchors:
    symbols:
    - 014219481103975f
    - 051af376199dec21
    - 07ca9aca44076975
    - 0d8ab225a327981f
    - 0e570ca6fabe24f9
    - 177f1f267012d839
    - 184fa15048ea1736
    - 1993e081ec707836
    - 249470f8d968ed2c
    - 2e1ab985aa7d0bdb
    - 2fa929ff9023b141
    - 313a910dd2688512
    - 3174cff531ec41ba
    - 35b6313d22612a48
    - 3846dd887d7e0678
    - 3fbc1943cd94a01c
    - 4a892bd5029ae280
    - 55351556ae9399a2
    - 62c57e79cf7253e5
    - 688242835feffd6f
    - 6c5a289087c6b765
    - 75f7eff1aaffca07
    - 78099ba05b34053f
    - 7ce08ff8a94cd389
    - 7ce397d3281dcc41
    - 7db6d8f5a04787c6
    - 7e5cf2918c4ecf65
    - 80bb624a15d2ab52
    - 81a34c1cd25c327d
    - 82235d92b2d0c09a
    - 82bf6359db7ace9c
    - 8867eb966b281109
    - 8b74e05df9c7ac3b
    - 8eed4c50f1a6d860
    - 8f030459f12924b0
    - 9c0dc0cbb585b90c
    - 9dcacac4b571fa09
    - b0c45e2664601ef3
    - b55c78646b9a1428
    - b8b240b11b893fde
    - bfa8ce695d2fcc6e
    - c417a51fb0a1020e
    - c721ee64e5f1e9ad
    - cbf8cac63dcb8397
    - d57bce0ca9a3387d
    - e18a39d085eaa0e5
    - e3ad257a408fbdd0
    - e6f1825e16924bff
    - f1a4235dbda80934
    - ff89906d9fa65087
  region_hashes:
    overview: d9f5bd1b0227656f
    symbols: adf1e3c08f807f01
  schema_version: 1.0.0
  symbol_sigs:
    014219481103975f: c7ab2bead314c420
    051af376199dec21: e7ddc1e5f8554f01
    07ca9aca44076975: 46b0db2189f9e6ff
    0d8ab225a327981f: 217627b08dabd1f3
    0e570ca6fabe24f9: 46bfeeafe35e7bd1
    177f1f267012d839: 58abe95ca9ede2f9
    184fa15048ea1736: aeb7d1b5afa85a56
    1993e081ec707836: 4fe47169930995fa
    249470f8d968ed2c: 9ea77d079d8311ba
    2e1ab985aa7d0bdb: d4c2f369551e5f3f
    2fa929ff9023b141: c751cb1e48f8e2f4
    313a910dd2688512: b457a471275fccbe
    3174cff531ec41ba: 76de7c773c6f0214
    35b6313d22612a48: b43860ff0d330deb
    3846dd887d7e0678: 9edfe8d1f2bfee02
    3fbc1943cd94a01c: 93d2a08902256346
    4a892bd5029ae280: eef3dc349d1affb9
    55351556ae9399a2: e365d9e98848c292
    62c57e79cf7253e5: 97e23f1ce1cb0c0e
    688242835feffd6f: 7e9e9d40d6758c38
    6c5a289087c6b765: ecef71d4f1e3943c
    75f7eff1aaffca07: d489ae7a5bb86ffa
    78099ba05b34053f: 2e0afb29e5e35646
    7ce08ff8a94cd389: d47ae37676fcdd2f
    7ce397d3281dcc41: c6afa9619993d62c
    7db6d8f5a04787c6: c7c61d525560779f
    7e5cf2918c4ecf65: e7d442e904a59c94
    80bb624a15d2ab52: 1f1ed6c8c69811ad
    81a34c1cd25c327d: f34f2d3ca01989ee
    82235d92b2d0c09a: 8afc9d44924daada
    82bf6359db7ace9c: 48d9ab06376b383e
    8867eb966b281109: 0ab7c2da236311a0
    8b74e05df9c7ac3b: dcb2d33605b5cb89
    8eed4c50f1a6d860: 88a3d0a785fcd16b
    8f030459f12924b0: c6831d0b1906f7a5
    9c0dc0cbb585b90c: 116eac776616f56a
    9dcacac4b571fa09: 93882ad37fda4f12
    b0c45e2664601ef3: cde66ac02a4d416e
    b55c78646b9a1428: 7575022367e16e29
    b8b240b11b893fde: fef15a0579f2656d
    bfa8ce695d2fcc6e: 8081578398050a54
    c417a51fb0a1020e: 9ff669043eae7d6e
    c721ee64e5f1e9ad: d17222f906b6ed38
    cbf8cac63dcb8397: 122e892f8ad7efb7
    d57bce0ca9a3387d: d56049cde23a3e34
    e18a39d085eaa0e5: 064ea58618d252df
    e3ad257a408fbdd0: ccbee215a437ecc4
    e6f1825e16924bff: 8aa8f59d17ce633b
    f1a4235dbda80934: e8ad77e9f5d9268c
    ff89906d9fa65087: 4d863f1f3c0fafc5
---
# spmirror

> EPIC SP SharePoint mirror connector: list/fetch a library (a local
> `pull_sharepoint.py` mirror dir or the `rag-sharepoint-api` proxy),
> convert each file to deterministic text (`docx-text` container-churn-
> invariant, `passthrough`; a lossless doc2md plugs into the same
> registry), and write the governed mirror under `dest` — preserving
> every engine-stamped `cdm:` baseline across re-syncs (`spmirror`).

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| Converter | class | class Converter(Protocol) |
| Converter.convert | method | def convert(self, raw: bytes, *, source_name: str) -> str |
| DEFAULT_SPMIRROR_PATH | variable | DEFAULT_SPMIRROR_PATH = Path('config') / 'spmirror.yaml' |
| DirSource | class | class DirSource |
| DirSource.__init__ | method | def __init__(self, root: Path) -> None |
| DirSource.fetch | method | def fetch(self, path: str) -> bytes |
| DirSource.list_documents | method | def list_documents(self) -> tuple[SpDocument, ...] |
| ProxySource | class | class ProxySource |
| ProxySource.__init__ | method | def __init__(self, api_url: str, site_url: str, folder: str \| None = None, *, timeout: int = 120) -> None |
| ProxySource._post | method | def _post(self, route: str, payload: dict[str, Any]) -> dict[str, Any] |
| ProxySource.fetch | method | def fetch(self, path: str) -> bytes |
| ProxySource.list_documents | method | def list_documents(self) -> tuple[SpDocument, ...] |
| Source | class | class Source(Protocol) |
| Source.fetch | method | def fetch(self, path: str) -> bytes |
| Source.list_documents | method | def list_documents(self) -> tuple[SpDocument, ...] |
| SpDocument | class | class SpDocument(BaseModel) |
| SpMirrorConfig | class | class SpMirrorConfig(BaseModel) |
| SpMirrorConfig._wellformed | method | def _wellformed(self) -> SpMirrorConfig |
| SpMirrorError | class | class SpMirrorError(CodeDocMonitorError) |
| SpSyncReport | class | class SpSyncReport(BaseModel) |
| _AUX_TEXT_PART_RE | variable | _AUX_TEXT_PART_RE = ... |
| _CONVERTERS | variable | _CONVERTERS: dict[str, Converter] = ... |
| _Doc2mdOffice | class | class _Doc2mdOffice |
| _Doc2mdOffice.convert | method | def convert(self, raw: bytes, *, source_name: str) -> str |
| _DocxText | class | class _DocxText |
| _DocxText._has_paragraph_ancestor | method | def _has_paragraph_ancestor(para: ElementTree.Element, parents: dict[ElementTree.Element, ElementTree.Element]) -> bool |
| _DocxText._paragraph_text | method | def _paragraph_text(para: ElementTree.Element) -> str |
| _DocxText._prefix | method | def _prefix(para: ElementTree.Element) -> str |
| _DocxText.convert | method | def convert(self, raw: bytes, *, source_name: str) -> str |
| _HEADING_RE | variable | _HEADING_RE = re.compile('[Hh]eading(\\\\d+)$') |
| _MANIFEST_REL | variable | _MANIFEST_REL = Path('.cdmon') / 'sp-manifest.json' |
| _MANIFEST_SCHEMA_VERSION | variable | _MANIFEST_SCHEMA_VERSION = '1.0.0' |
| _MAX_PART_BYTES | variable | _MAX_PART_BYTES = 64 * 1024 * 1024 |
| _MAX_RESPONSE_BYTES | variable | _MAX_RESPONSE_BYTES = 128 * 1024 * 1024 |
| _OFFICE_EXTS | variable | _OFFICE_EXTS = {'docx', 'pptx', 'xlsx'} |
| _Passthrough | class | class _Passthrough |
| _Passthrough.convert | method | def convert(self, raw: bytes, *, source_name: str) -> str |
| _W_NS | variable | _W_NS = ... |
| __all__ | variable | __all__ = ... |
| _load_sp_manifest | function | def _load_sp_manifest(path: Path) -> dict[str, Any] |
| _mirror_rel | function | def _mirror_rel(cfg: SpMirrorConfig, doc_path: str, converter_id: str) -> str |
| _reject_dtd | function | def _reject_dtd(payload: bytes, source_name: str) -> None |
| _skip_unchanged | function | def _skip_unchanged(prior: object, doc: SpDocument) -> bool |
| _urlopen | variable | _urlopen = urllib.request.urlopen |
| _write_body_preserving_meta | function | def _write_body_preserving_meta(target: Path, body: str) -> bool |
| convert_bytes | function | def convert_bytes(converter_id: str, raw: bytes, *, source_name: str) -> str |
| docx_lossy_parts | function | def docx_lossy_parts(raw: bytes) -> tuple[str, ...] |
| load_spmirror_config | function | def load_spmirror_config(path: Path, *, env: Mapping[str, str] \| None = None) -> SpMirrorConfig |
| source_from_config | function | def source_from_config(cfg: SpMirrorConfig) -> Source |
| sync_mirror | function | def sync_mirror(cfg: SpMirrorConfig, repo_root: Path, source: Source, *, force: bool = False, dry_run: bool = False) -> SpSyncReport |
<!-- CDM:END symbols -->

<!-- CDM:BEGIN overview -->
This eng-guide section is authored from the code surface (the single source of truth) and is re-authored whenever that surface changes. It covers the public API: `Converter`, `Converter.convert`, `DEFAULT_SPMIRROR_PATH`, `DirSource`, `DirSource.__init__`, `DirSource.fetch`, `DirSource.list_documents`, `ProxySource`, `ProxySource.__init__`, `ProxySource.fetch`, `ProxySource.list_documents`, `Source`, `Source.fetch`, `Source.list_documents`, `SpDocument`, `SpMirrorConfig`, `SpMirrorError`, `SpSyncReport`, `_Doc2mdOffice.convert`, `_DocxText.convert`, `_Passthrough.convert`, `__all__`, `convert_bytes`, `docx_lossy_parts`, `load_spmirror_config`, `source_from_config`, `sync_mirror`.
<!-- CDM:END overview -->
