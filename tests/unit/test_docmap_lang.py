"""COVLANG-DOCMAP — the doc→symbol coverage join reads each ref with its parser.

``docmap.symbol_owners`` is the join under the SHARED_SYMBOL suggestion rule,
the kgraph DOCUMENTS edges (so ``rank_centrality(undocumented_only=True)``,
the worker's DOCUMENT_GAP feed) and the ``cdx impact`` direct join. It used to
read EVERY code_ref with the Python-only ``extract_file`` and to ignore the
ref's selectors: a shell function a doc covered was never owned (the
``ExtractionError`` was swallowed), and a ``symbols: [X]`` ref claimed its
whole file.

The fixed contract, pinned here:

* a ``symbols`` ref is read by ``get_extractor(extract._symbol_language(ref))``
  — explicit ``lang`` > suffix map > python fallback — looked up at CALL time
  (a later ``register_extractor`` flows through, K0);
* a ``switches``/``records`` ref keeps its pre-routing Python read (its
  ``lang`` names a switch parser, never a symbol extractor), so a ``.sh``
  switch table owns no shell function whatever its ``lang``;
* every ref then owns only what ``extract._select`` picks with its
  ``symbols``/``lines``/``names`` selectors (the ``coverage.resolve_coverage``
  rule; ``arg_signature`` narrows a surface, not ownership); several refs to
  one file union;
* public symbols only (a private symbol skips itself, not the rest of the
  ref); a missing or non-file (directory), unparseable or
  unregistered-language ref is skipped, never fatal — but only
  ``ExtractionError`` is a skip: any other error an extractor raises
  propagates (K8);
* parity with ``cdx coverage`` holds for refs whose path is in normal form;
  a ``./``-prefixed ref is a known divergence (``resolve_coverage`` matches
  the raw path), pinned here so it turns red when that is fixed.

Features: FEAT-DOCMAP-004
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex import extract
from custodex.codeindex import (
    CodeIndex,
    IndexedFile,
    IndexedSymbol,
    build_code_index,
    impact_report,
)
from custodex.config import (
    Audience,
    CodeRef,
    CoverageConfig,
    DocumentSpec,
    MonitorConfig,
    load_config,
)
from custodex.coverage import resolve_coverage
from custodex.docmap import SuggestionTier, suggest_edges, symbol_owners
from custodex.errors import ExtractionError
from custodex.extract import Symbol, build_document_surface, register_extractor
from custodex.inventory import discover_files, discover_symbols
from custodex.kgraph import EdgeKind, build_graph, rank_centrality
from tests._repo import REPO_ROOT

# Line numbers are load-bearing for the `lines` selector cases.
RUN_SH = (
    "#!/bin/sh\n"  # 1
    "# Deploy the app.\n"  # 2
    "deploy_app() {\n"  # 3
    "  echo deploy\n"  # 4
    "}\n"  # 5
    "# Roll back.\n"  # 6
    "rollback() {\n"  # 7
    "  echo back\n"  # 8
    "}\n"  # 9
    "_internal() {\n"  # 10
    "  echo hidden\n"  # 11
    "}\n"  # 12
)
OTHER_SH = "#!/bin/sh\norphan_fn() {\n  echo orphan\n}\n"
TWO_PY = (
    "LIMIT = 3\n"  # 1
    "def solve_widget(x):\n"  # 2
    "    return x\n"  # 3
    "def tune_widget(y):\n"  # 4
    "    return y\n"  # 5
    "class Gadget:\n"  # 6
    "    def spin(self):\n"  # 7
    "        return 1\n"  # 8
    "def _hidden():\n"  # 9
    "    return 0\n"  # 10
)

SH_PUBLIC = {"symbol scripts/run.sh#deploy_app", "symbol scripts/run.sh#rollback"}
PY_PUBLIC = {
    "symbol pkg/two.py#LIMIT",
    "symbol pkg/two.py#solve_widget",
    "symbol pkg/two.py#tune_widget",
    "symbol pkg/two.py#Gadget",
    "symbol pkg/two.py#Gadget.spin",
}


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _repo(root: Path) -> Path:
    _write(root, "scripts/run.sh", RUN_SH)
    _write(root, "scripts/other.sh", OTHER_SH)
    _write(root, "pkg/two.py", TWO_PY)
    _write(root, "docs/a.md", "# A\n\nProse.\n")
    _write(root, "docs/b.md", "# B\n\nReference.\n")
    _write(root, "docs/c.md", "# C\n\nReference.\n")
    return root


def _spec(doc_id: str, *refs: CodeRef) -> DocumentSpec:
    return DocumentSpec(
        id=doc_id,
        path=f"docs/{doc_id}.md",
        audience=Audience.ENG_GUIDE,
        code_refs=refs,
    )


def _config(
    *specs: DocumentSpec, include: tuple[str, ...] = ("**/*.py",)
) -> MonitorConfig:
    return MonitorConfig(
        documents=specs, coverage=CoverageConfig(include=include, exclude=())
    )


def _owned(cfg: MonitorConfig, root: Path, doc_id: str = "b") -> set[str]:
    return {k for k, v in symbol_owners(cfg, root).items() if doc_id in v}


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap BOTH registries for copies so the REAL register_extractor writes them."""
    monkeypatch.setattr(extract, "_EXTRACTORS", dict(extract._EXTRACTORS))
    monkeypatch.setattr(
        extract, "_SYMBOL_LANG_BY_SUFFIX", dict(extract._SYMBOL_LANG_BY_SUFFIX)
    )


class _FakeExtractor:
    """A registered non-Python language that emits one fixed public symbol."""

    def __init__(self, language: str) -> None:
        self.language = language

    def extract(self, path: Path) -> list[Symbol]:
        if not path.is_file():
            raise ExtractionError(f"missing {path}")
        return [
            Symbol(
                name="from_fake",
                kind="function",
                signature="from_fake()",
                lineno=1,
                end_lineno=1,
                is_public=True,
                docstring=None,
            )
        ]


class _BlindExtractor:
    """Returns one fixed public symbol WITHOUT reading the path.

    Every in-tree extractor raises ``ExtractionError`` on a missing path or a
    directory, which masks the ``is_file`` pre-check; this one does not, so
    only the pre-check keeps such a ref from owning ``ghost``.
    """

    language = "blind"

    def extract(self, path: Path) -> list[Symbol]:
        return [
            Symbol(
                name="ghost",
                kind="function",
                signature="ghost()",
                lineno=1,
                end_lineno=1,
                is_public=True,
                docstring=None,
            )
        ]


class _BuggyExtractor:
    """A registered extractor with a bug: raises a non-``ExtractionError``."""

    language = "buggy"

    def extract(self, path: Path) -> list[Symbol]:
        raise RuntimeError("extractor bug")


class TestSymbolOwnersRouting:
    def test_shell_ref_public_functions_are_owned(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        owners = symbol_owners(
            _config(_spec("b", CodeRef(path="scripts/run.sh"))), root
        )
        assert owners == {k: {"b"} for k in SH_PUBLIC}  # `_internal` stays private

    def test_bash_suffix_is_owned(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/run.bash", RUN_SH)
        cfg = _config(_spec("b", CodeRef(path="scripts/run.bash")))
        assert _owned(cfg, tmp_path) == {
            "symbol scripts/run.bash#deploy_app",
            "symbol scripts/run.bash#rollback",
        }

    def test_explicit_lang_wins_over_the_python_fallback(self, tmp_path: Path) -> None:
        _write(tmp_path, "bin/deploy", RUN_SH)  # suffix-less: auto → python
        auto = _config(_spec("b", CodeRef(path="bin/deploy")))
        shell = _config(_spec("b", CodeRef(path="bin/deploy", lang="shell")))
        assert _owned(auto, tmp_path) == set()  # python parse fails → skipped
        assert _owned(shell, tmp_path) == {
            "symbol bin/deploy#deploy_app",
            "symbol bin/deploy#rollback",
        }

    def test_explicit_unknown_lang_on_a_mapped_suffix_is_skipped(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path)
        cfg = _config(
            _spec(
                "b",
                CodeRef(path="pkg/two.py", lang="rust"),  # unregistered beats .py
                CodeRef(path="scripts/run.sh", lang="python"),  # python beats .sh
            )
        )
        assert symbol_owners(cfg, root) == {}

    def test_explicit_registered_lang_on_a_mapped_suffix_matches_the_surface(
        self, tmp_path: Path, isolated_registry: None
    ) -> None:
        root = _repo(tmp_path)
        register_extractor(_FakeExtractor("fakelang"))
        spec = _spec("b", CodeRef(path="scripts/run.sh", lang="fakelang"))
        graded = {
            f"symbol scripts/run.sh#{s.name}"
            for s in build_document_surface(spec, root).symbols
            if s.is_public
        }
        assert (
            _owned(_config(spec), root) == graded == {"symbol scripts/run.sh#from_fake"}
        )

    def test_python_refs_are_unchanged_including_the_pyi_fallback(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path)
        _write(root, "pkg/stub.pyi", "def typed(x: int) -> int: ...\n")
        cfg = _config(
            _spec("b", CodeRef(path="pkg/two.py"), CodeRef(path="pkg/stub.pyi"))
        )
        assert _owned(cfg, root) == PY_PUBLIC | {"symbol pkg/stub.pyi#typed"}

    def test_unregistered_language_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        _write(root, "gui/app.tcl", "proc go {} { puts hi }\n")
        cfg = _config(
            _spec(
                "b",
                CodeRef(path="gui/app.tcl", lang="tcl"),  # listed FIRST
                CodeRef(path="scripts/missing.sh"),
                CodeRef(path="scripts/run.sh"),
            )
        )
        assert _owned(cfg, root) == SH_PUBLIC

    def test_a_later_registration_flows_through_at_call_time(
        self, tmp_path: Path, isolated_registry: None
    ) -> None:
        _write(tmp_path, "lib/thing.fake", "not python (\n")
        cfg = _config(_spec("b", CodeRef(path="lib/thing.fake")))
        assert _owned(cfg, tmp_path) == set()  # unmapped suffix → python → skipped
        register_extractor(_FakeExtractor("fake"), suffixes=(".fake",))
        assert _owned(cfg, tmp_path) == {"symbol lib/thing.fake#from_fake"}

    def test_a_missing_file_is_skipped_even_by_an_extractor_that_never_reads(
        self, tmp_path: Path, isolated_registry: None
    ) -> None:
        """The ``is_file`` pre-check owns the missing-file skip.

        Every in-tree extractor raises ``ExtractionError`` on a missing path,
        which would mask a dropped pre-check; this blind extractor returns a
        fixed symbol WITHOUT touching the path, so only the pre-check keeps a
        missing ref from owning it.
        """
        register_extractor(_BlindExtractor(), suffixes=(".blind",))
        _write(tmp_path, "lib/real.blind", "anything\n")
        cfg = _config(
            _spec("b", CodeRef(path="lib/gone.blind"), CodeRef(path="lib/real.blind"))
        )
        assert symbol_owners(cfg, tmp_path) == {"symbol lib/real.blind#ghost": {"b"}}

    def test_a_directory_ref_path_owns_nothing_even_for_a_blind_extractor(
        self, tmp_path: Path, isolated_registry: None
    ) -> None:
        """The pre-check is ``is_file``, not ``exists``: a ref naming a
        directory is skipped, even by an extractor that never reads."""
        register_extractor(_BlindExtractor(), suffixes=(".blind",))
        (tmp_path / "lib" / "pkg.blind").mkdir(parents=True)
        cfg = _config(_spec("b", CodeRef(path="lib/pkg.blind")))
        assert symbol_owners(cfg, tmp_path) == {}

    def test_a_directory_python_ref_path_is_skipped_not_fatal(
        self, tmp_path: Path
    ) -> None:
        """Ship shape: an in-tree python ref naming a directory is skipped and
        the doc's other refs still own their symbols."""
        (tmp_path / "pkg" / "sub.py").mkdir(parents=True)
        _write(tmp_path, "pkg/m.py", "def solve():\n    pass\n")
        cfg = _config(_spec("b", CodeRef(path="pkg/sub.py"), CodeRef(path="pkg/m.py")))
        assert symbol_owners(cfg, tmp_path) == {"symbol pkg/m.py#solve": {"b"}}

    def test_an_extractor_bug_is_loud_not_skipped(
        self, tmp_path: Path, isolated_registry: None
    ) -> None:
        """Only ``ExtractionError`` is an advisory skip; any other error a
        registered extractor raises propagates (K8 — never swallow a bug)."""
        register_extractor(_BuggyExtractor(), suffixes=(".buggy",))
        _write(tmp_path, "lib/x.buggy", "x\n")
        cfg = _config(_spec("b", CodeRef(path="lib/x.buggy")))
        with pytest.raises(RuntimeError, match="extractor bug"):
            symbol_owners(cfg, tmp_path)

    def test_a_private_symbol_before_public_ones_does_not_end_the_ref(
        self, tmp_path: Path
    ) -> None:
        """The private filter skips ONE symbol; it does not stop the ref.

        Every other fixture puts its private symbol LAST, which would mask a
        ``continue`` turned into ``break``.
        """
        _write(
            tmp_path, "scripts/run.sh", "_helper() {\n  :\n}\ndeploy_app() {\n  :\n}\n"
        )
        _write(
            tmp_path, "pkg/m.py", "def _helper():\n    pass\ndef solve():\n    pass\n"
        )
        cfg = _config(
            _spec("b", CodeRef(path="scripts/run.sh"), CodeRef(path="pkg/m.py"))
        )
        assert symbol_owners(cfg, tmp_path) == {
            "symbol scripts/run.sh#deploy_app": {"b"},
            "symbol pkg/m.py#solve": {"b"},
        }

    def test_ownership_is_audience_agnostic(self, tmp_path: Path) -> None:
        """A user-guide owns the same symbols an eng-guide does (K3 is a drift
        verdict rule, not a coverage rule)."""
        _write(tmp_path, "pkg/two.py", "def solve(x):\n    return x\n")
        user = DocumentSpec(
            id="u",
            path="docs/u.md",
            audience=Audience.USER_GUIDE,
            code_refs=(CodeRef(path="pkg/two.py"),),
        )
        eng = DocumentSpec(
            id="e",
            path="docs/e.md",
            audience=Audience.ENG_GUIDE,
            code_refs=(CodeRef(path="pkg/two.py"),),
        )
        assert symbol_owners(_config(user, eng), tmp_path) == {
            "symbol pkg/two.py#solve": {"u", "e"}
        }


class TestOwnershipFollowsTheRefSelection:
    @pytest.mark.parametrize(
        ("ref", "expected"),
        [
            pytest.param(
                CodeRef(path="scripts/run.sh", symbols=("deploy_app",)),
                {"symbol scripts/run.sh#deploy_app"},
                id="sh-symbols",
            ),
            pytest.param(
                CodeRef(path="scripts/run.sh", lines=((7, 9),)),
                {"symbol scripts/run.sh#rollback"},
                id="sh-lines",
            ),
            pytest.param(
                CodeRef(path="scripts/run.sh", lines=((8, 8),)),
                {"symbol scripts/run.sh#rollback"},
                id="sh-lines-inside-a-body",
            ),
            pytest.param(
                CodeRef(path="pkg/two.py", lines=((2, 3),)),
                {"symbol pkg/two.py#solve_widget"},
                id="py-lines",
            ),
            pytest.param(
                CodeRef(path="pkg/two.py", names=("LIMIT",)),
                {"symbol pkg/two.py#LIMIT"},
                id="py-names",
            ),
            pytest.param(
                CodeRef(path="pkg/two.py", symbols=("Gadget",)),
                {"symbol pkg/two.py#Gadget", "symbol pkg/two.py#Gadget.spin"},
                id="py-class-pulls-methods",
            ),
            pytest.param(
                CodeRef(path="scripts/run.sh", symbols=("_internal",)),
                set(),
                id="private-selection",
            ),
            pytest.param(
                CodeRef(path="pkg/two.py", names=("solve_widget",)),
                set(),
                id="py-names-on-a-function",
            ),
        ],
    )
    def test_selectors_narrow_ownership_to_the_selection(
        self, tmp_path: Path, ref: CodeRef, expected: set[str]
    ) -> None:
        root = _repo(tmp_path)
        assert _owned(_config(_spec("b", ref)), root) == expected

    def test_arg_signature_does_not_narrow_ownership(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        cfg = _config(_spec("b", CodeRef(path="pkg/two.py", arg_signature=("x",))))
        assert _owned(cfg, root) == PY_PUBLIC

    def test_two_narrowed_refs_to_one_file_own_the_union(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        cfg = _config(
            _spec(
                "b",
                CodeRef(path="pkg/two.py", symbols=("solve_widget",)),
                CodeRef(path="pkg/two.py", symbols=("tune_widget",)),
            )
        )
        assert _owned(cfg, root) == {
            "symbol pkg/two.py#solve_widget",
            "symbol pkg/two.py#tune_widget",
        }

    def test_a_ref_path_is_read_and_keyed_at_its_lexical_normpath(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path)
        cfg = _config(
            _spec("b", CodeRef(path="missing/../scripts/run.sh")),
            _spec("c", CodeRef(path="./pkg//two.py", symbols=("tune_widget",))),
        )
        assert symbol_owners(cfg, root) == {
            **{k: {"b"} for k in SH_PUBLIC},
            "symbol pkg/two.py#tune_widget": {"c"},
        }

    def test_a_non_normal_ref_path_is_a_known_divergence_from_coverage(
        self, tmp_path: Path
    ) -> None:
        """Known limit, pinned so it is visible: the join (and the graded
        surface) read a ref at its lexical ``normpath``, but
        ``coverage.resolve_coverage`` matches the RAW ``ref.path`` against
        inventory paths, and ``CodeRef`` does not normalize. Parity with
        ``cdx coverage`` therefore holds only for refs already in normal form.
        This turns red when ``resolve_coverage`` normalizes the ref path; then
        assert equality instead.
        """
        root = _repo(tmp_path)
        cfg = _config(
            _spec("d", CodeRef(path="./pkg/two.py", symbols=("solve_widget",)))
        )
        assert symbol_owners(cfg, root) == {"symbol pkg/two.py#solve_widget": {"d"}}
        surface = build_document_surface(cfg.documents[0], root)
        assert [s.name for s in surface.symbols if s.is_public] == ["solve_widget"]
        inv = discover_symbols(discover_files(root, include=("pkg/two.py",)), root)
        report = resolve_coverage(cfg, inv)
        assert [f.path for f in inv.files] == ["pkg/two.py"]  # the cause is real
        assert report.documented_symbols == ()

    def test_same_file_under_two_languages_is_read_per_ref(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path)
        cfg = _config(
            _spec("b", CodeRef(path="pkg/two.py")),
            # The shell regex parses a .py file without error and finds nothing:
            # doc c must not inherit doc b's Python read of the same path.
            _spec("c", CodeRef(path="pkg/two.py", lang="shell")),
        )
        assert symbol_owners(cfg, root) == {k: {"b"} for k in PY_PUBLIC}

    @pytest.mark.parametrize("kind", ["switches", "records"])
    def test_non_symbols_refs_keep_the_pre_routing_ownership(
        self, tmp_path: Path, kind: str
    ) -> None:
        root = _repo(tmp_path)
        cfg = _config(_spec("b", CodeRef(path="pkg/two.py", extract=kind)))
        assert _owned(cfg, root) == PY_PUBLIC

    @pytest.mark.parametrize("lang", ["auto", "shell"])
    @pytest.mark.parametrize("kind", ["switches", "records"])
    def test_non_symbols_sh_ref_owns_nothing_whatever_its_lang(
        self, tmp_path: Path, kind: str, lang: str
    ) -> None:
        root = _repo(tmp_path)
        cfg = _config(
            _spec("b", CodeRef(path="scripts/run.sh", extract=kind, lang=lang))
        )
        assert symbol_owners(cfg, root) == {}

    def test_non_symbols_python_ref_without_py_suffix_keeps_whole_file(
        self, tmp_path: Path
    ) -> None:
        _write(tmp_path, "bin/cli", "def main():\n    return 0\n")
        cfg = _config(
            _spec("b", CodeRef(path="bin/cli", extract="records", lang="python"))
        )
        assert _owned(cfg, tmp_path) == {"symbol bin/cli#main"}

    @pytest.mark.parametrize(
        ("ref", "expected"),
        [
            pytest.param(
                CodeRef(
                    path="pkg/two.py", extract="switches", symbols=("solve_widget",)
                ),
                {"symbol pkg/two.py#solve_widget"},
                id="switches-with-symbols",
            ),
            pytest.param(
                CodeRef(path="pkg/two.py", extract="records", lines=((4, 5),)),
                {"symbol pkg/two.py#tune_widget"},
                id="records-with-lines",
            ),
        ],
    )
    def test_selectors_narrow_a_non_symbols_ref_too(
        self, tmp_path: Path, ref: CodeRef, expected: set[str]
    ) -> None:
        root = _repo(tmp_path)
        assert _owned(_config(_spec("b", ref)), root) == expected


class TestInRepoConfigs:
    def test_the_multilang_switch_table_claims_no_shell_function(self) -> None:
        example = REPO_ROOT / "examples" / "multilang"
        owners = symbol_owners(load_config(example / "cdmon.yaml"), example)
        # Non-vacuous: the Python library doc still owns its module.
        assert owners.get("symbol code/greeter.py#greet") == {"library"}
        # `tools` reads code/batch.sh as a switch table (extract: switches,
        # lang: shell): it documents switches, not the script's functions.
        assert not [k for k in owners if k.startswith("symbol code/batch.sh#")]
        assert "usage" in {
            s.name
            for s in extract.get_extractor("shell").extract(example / "code/batch.sh")
        }


class TestConsumersSeeShellCoverage:
    def _cfg(self, include: tuple[str, ...]) -> MonitorConfig:
        return _config(
            _spec("a"),
            _spec("b", CodeRef(path="scripts/run.sh")),
            include=include,
        )

    def _mentions(self, root: Path) -> None:
        _write(root, "docs/a.md", "# A\n\nRun `deploy_app`, never `orphan_fn`.\n")

    def test_shared_symbol_suggestion_for_a_covered_shell_function(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path)
        self._mentions(root)
        edges = suggest_edges(self._cfg(("**/*.sh", "**/*.py")), root)
        assert [(e.doc_id, e.upstream_id, e.tier, e.evidence) for e in edges] == [
            (
                "a",
                "b",
                SuggestionTier.SHARED_SYMBOL,
                ("symbol scripts/run.sh#deploy_app",),
            )
        ]

    def test_kgraph_documents_edge_and_the_undocumented_ranking(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path)
        self._mentions(root)
        g = build_graph(self._cfg(("**/*.sh", "**/*.py")), root)
        documents = {
            (e.source, e.target) for e in g.edges if e.kind is EdgeKind.DOCUMENTS
        }
        assert documents == {("doc docs/b.md", k) for k in SH_PUBLIC}
        # The covered function leaves the gap feed; the uncovered foil stays.
        assert rank_centrality(g, undocumented_only=True) == (
            ("symbol scripts/other.sh#orphan_fn", 1),
        )
        assert ("symbol scripts/run.sh#deploy_app", 1) in rank_centrality(g)

    def test_default_coverage_scope_changes_only_the_documents_edges(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path)
        self._mentions(root)
        cfg = self._cfg(("**/*.py",))
        g = build_graph(cfg, root)
        documents = {
            (e.source, e.target) for e in g.edges if e.kind is EdgeKind.DOCUMENTS
        }
        assert documents == {("doc docs/b.md", k) for k in SH_PUBLIC}
        # Mentions resolve only against the coverage inventory (.py here).
        assert suggest_edges(cfg, root) == ()
        assert rank_centrality(g, undocumented_only=True) == ()

    def test_impact_join_is_ready_for_a_shell_carrying_index(
        self, tmp_path: Path
    ) -> None:
        """Pins the JOIN only: an index that carries shell symbols attributes a
        shell signature change to the covering doc.

        NOT reachable in ship shape today: ``build_code_index`` reads through
        ``inventory.discover_symbols`` (Python only), so a ``.sh`` file is
        indexed with no symbols; see the next test, which pins that limitation.
        """
        root = _repo(tmp_path)

        def _index(sig: str) -> CodeIndex:
            sym = IndexedSymbol(
                name="deploy_app",
                kind="function",
                signature="deploy_app()",
                lineno=3,
                end_lineno=5,
                is_public=True,
                anchor="deploy_app",
                sig_digest=sig,
            )
            return CodeIndex(
                generated_by="custodex/test",
                files=(
                    IndexedFile(
                        path="scripts/run.sh",
                        language="shell",
                        content_digest=sig,
                        symbols=(sym,),
                    ),
                ),
            )

        report = impact_report(
            self._cfg(("**/*.py",)), root, _index("0" * 16), _index("1" * 16), None
        )
        assert [(d.doc_id, d.direct) for d in report.docs] == [
            ("b", ("symbol scripts/run.sh#deploy_app",))
        ]

    def test_ship_shape_impact_still_reports_no_doc_for_a_shell_change(
        self, tmp_path: Path
    ) -> None:
        """Known limitation, pinned so it cannot be silently claimed fixed.

        The code index ``cdx impact`` diffs is built by ``build_code_index``,
        whose inventory (``discover_symbols``) reads Python only: a ``.sh``
        file lands with no symbols, so a shell signature change and an added
        shell function both affect 0 docs although ``symbol_owners`` now owns
        the shell functions. This turns red when the inventory half of
        NEW-COV-LANG (COV-DENOM) lands; update it then.
        """
        root = _repo(tmp_path)
        cfg = _config(_spec("b", CodeRef(path="scripts/run.sh")), include=("**/*.sh",))
        before = build_code_index(cfg, root)
        (stored_file,) = [f for f in before.files if f.path == "scripts/run.sh"]
        assert stored_file.symbols == ()  # the inventory sees no shell symbol
        _write(
            root,
            "scripts/run.sh",
            "#!/bin/sh\ndeploy_app() {\n  echo deploy --fast\n}\n"
            "fresh_fn() {\n  echo new\n}\n",
        )
        after = build_code_index(cfg, root)
        assert before != after  # the file DID change
        assert "symbol scripts/run.sh#deploy_app" in symbol_owners(cfg, root)
        report = impact_report(cfg, root, before, after, None)
        assert report.docs == ()


class TestConsumersSeeThePythonSelection:
    def test_an_unselected_python_symbol_is_an_undocumented_gap(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path)
        _write(root, "docs/a.md", "# A\n\nCall `solve_widget` then `tune_widget`.\n")
        cfg = _config(
            _spec("a"),
            _spec("b", CodeRef(path="pkg/two.py", symbols=("solve_widget",))),
        )
        g = build_graph(cfg, root)
        assert rank_centrality(g, undocumented_only=True) == (
            ("symbol pkg/two.py#tune_widget", 1),
        )
        assert [
            (e.doc_id, e.upstream_id, e.evidence) for e in suggest_edges(cfg, root)
        ] == [("a", "b", ("symbol pkg/two.py#solve_widget",))]
