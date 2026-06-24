"""Tests for custodex.inventory (A-01).

File-level repo code-file discovery: deterministic, sorted, lossless output
(K10), pure with no FS mutation (K1), stdlib-only glob matching (K0), and a
typed loud error on a bad root (K8). Written before the implementation (K9, TDD).

Features: FEAT-COVERAGE-001, FEAT-COVERAGE-002, FEAT-COVERAGE-003
Features: FEAT-COVERAGE-004, FEAT-COVERAGE-005
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from custodex.errors import CodeDocMonitorError, ExtractionError, InventoryError
from custodex.inventory import (
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
    CodeFile,
    FileSymbols,
    Inventory,
    SymbolInventory,
    discover_files,
    discover_symbols,
)


def _touch(root: Path, rel: str, text: str = "x\n") -> Path:
    """Create ``root/rel`` (with parents) and return it."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# real-fixture / integration: a realistic mini-repo, exact included set
# --------------------------------------------------------------------------


def _build_mini_repo(root: Path) -> None:
    _touch(root, "pkg/a.py")
    _touch(root, "pkg/sub/b.py")
    _touch(root, "pkg/__pycache__/x.pyc")
    _touch(root, ".venv/lib/y.py")
    _touch(root, "tests/test_z.py")
    _touch(root, "README.md")


def test_real_fixture_exact_included_set(tmp_path: Path) -> None:
    _build_mini_repo(tmp_path)

    inv = discover_files(tmp_path)

    assert isinstance(inv, Inventory)
    assert tuple(f.path for f in inv.files) == (
        "pkg/a.py",
        "pkg/sub/b.py",
        "tests/test_z.py",
    )
    # all defaults → python; nothing dropped that should be kept
    assert {f.language for f in inv.files} == {"python"}


def test_root_is_posix_absolute(tmp_path: Path) -> None:
    _build_mini_repo(tmp_path)
    inv = discover_files(tmp_path)
    assert inv.root == tmp_path.resolve().as_posix()


# --------------------------------------------------------------------------
# unit: include / exclude glob matching
# --------------------------------------------------------------------------


def test_excludes_drop_pycache_dotdirs_and_venv(tmp_path: Path) -> None:
    _touch(tmp_path, "pkg/a.py")
    _touch(tmp_path, "pkg/__pycache__/a.cpython-311.pyc")
    _touch(tmp_path, ".venv/lib/site.py")
    _touch(tmp_path, ".git/hooks/pre-commit.py")
    _touch(tmp_path, ".hidden/secret.py")

    inv = discover_files(tmp_path)

    assert tuple(f.path for f in inv.files) == ("pkg/a.py",)


def test_include_only_matches_python_by_default(tmp_path: Path) -> None:
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "b.txt")
    _touch(tmp_path, "c.md")

    inv = discover_files(tmp_path)

    assert tuple(f.path for f in inv.files) == ("a.py",)


def test_custom_include_multiple_extensions(tmp_path: Path) -> None:
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "b.toml")
    _touch(tmp_path, "c.md")

    inv = discover_files(tmp_path, include=("**/*.py", "**/*.toml"))

    assert tuple(f.path for f in inv.files) == ("a.py", "b.toml")


def test_custom_exclude_overrides_default(tmp_path: Path) -> None:
    _touch(tmp_path, "pkg/a.py")
    _touch(tmp_path, "pkg/sub/b.py")

    inv = discover_files(tmp_path, exclude=("**/sub/**",))

    assert tuple(f.path for f in inv.files) == ("pkg/a.py",)


def test_empty_include_matches_nothing(tmp_path: Path) -> None:
    _touch(tmp_path, "a.py")
    inv = discover_files(tmp_path, include=())
    assert inv.files == ()


def test_a_file_kept_iff_matches_include_and_no_exclude(tmp_path: Path) -> None:
    # b.py matches include but also a custom exclude → dropped.
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "b.py")
    inv = discover_files(tmp_path, include=("**/*.py",), exclude=("b.py",))
    assert tuple(f.path for f in inv.files) == ("a.py",)


# --------------------------------------------------------------------------
# unit: extension → language, unknown kept (losslessness)
# --------------------------------------------------------------------------


def test_language_mapping_known_extensions(tmp_path: Path) -> None:
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "b.pyi")
    inv = discover_files(tmp_path, include=("**/*.py", "**/*.pyi"))
    langs = {f.path: f.language for f in inv.files}
    assert langs == {"a.py": "python", "b.pyi": "python"}


def test_unknown_extension_kept_as_unknown(tmp_path: Path) -> None:
    # Matched by include but no language mapping → kept, language="unknown".
    _touch(tmp_path, "weird.xyz")
    inv = discover_files(tmp_path, include=("**/*.xyz",))
    assert tuple((f.path, f.language) for f in inv.files) == (("weird.xyz", "unknown"),)


# --------------------------------------------------------------------------
# unit: determinism — sorted, order-independent of FS iteration, deduped
# --------------------------------------------------------------------------


def test_output_sorted_independent_of_creation_order(tmp_path: Path) -> None:
    # Create in an order whose natural os.walk/iter order differs from sorted.
    for rel in ("zeta/m.py", "alpha/a.py", "beta/b.py", "alpha/sub/z.py"):
        _touch(tmp_path, rel)

    inv = discover_files(tmp_path)

    paths = [f.path for f in inv.files]
    assert paths == sorted(paths)
    assert paths == [
        "alpha/a.py",
        "alpha/sub/z.py",
        "beta/b.py",
        "zeta/m.py",
    ]


def test_deterministic_same_tree_identical_output(tmp_path: Path) -> None:
    _build_mini_repo(tmp_path)
    first = discover_files(tmp_path)
    second = discover_files(tmp_path)
    assert first == second
    assert first.files == second.files


def test_no_fs_mutation(tmp_path: Path) -> None:
    _build_mini_repo(tmp_path)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    discover_files(tmp_path)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after


def test_question_mark_glob_matches_single_char(tmp_path: Path) -> None:
    # '?' must match exactly one non-separator char (and not a '/').
    _touch(tmp_path, "a1.py")
    _touch(tmp_path, "a12.py")
    _touch(tmp_path, "pkg/a1.py")  # leading dir segment must not be matched by '?'
    inv = discover_files(tmp_path, include=("a?.py",))
    assert tuple(f.path for f in inv.files) == ("a1.py",)


def test_overlapping_includes_dedupe(tmp_path: Path) -> None:
    _touch(tmp_path, "a.py")
    # a.py matches both include globs but must appear once.
    inv = discover_files(tmp_path, include=("**/*.py", "**/a.py"))
    assert tuple(f.path for f in inv.files) == ("a.py",)


def test_codefile_is_frozen_and_forbids_extra() -> None:
    cf = CodeFile(path="a.py", language="python")
    with pytest.raises(ValidationError):
        cf.path = "b.py"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        CodeFile(path="a.py", language="python", bogus=1)  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# loud errors (K8)
# --------------------------------------------------------------------------


def test_missing_root_raises_inventory_error(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    with pytest.raises(InventoryError) as exc:
        discover_files(missing)
    assert str(missing) in str(exc.value)


def test_file_as_root_raises_inventory_error(tmp_path: Path) -> None:
    f = _touch(tmp_path, "a.py")
    with pytest.raises(InventoryError):
        discover_files(f)


def test_inventory_error_is_custodex_error(tmp_path: Path) -> None:
    with pytest.raises(CodeDocMonitorError):
        discover_files(tmp_path / "nope")


# --------------------------------------------------------------------------
# defaults sanity
# --------------------------------------------------------------------------


def test_default_constants() -> None:
    assert DEFAULT_INCLUDE == ("**/*.py",)
    assert DEFAULT_EXCLUDE == ("**/.*/**", "**/__pycache__/**", "**/.venv/**")


# ==========================================================================
# A-02 — symbol-level inventory (discover_symbols)
# ==========================================================================
#
# Attaches the (public + private, for losslessness) symbol surface of each
# inventoried python file via extract.extract_file (reused, NOT re-implemented).
# Non-python matched files are tracked with symbols=() (lossless). Order is
# deterministic (K10): files follow Inventory.files; symbols follow extract_file.
# Unparseable python files let ExtractionError propagate (loud, K8).

_A_PY = '''\
"""Module a."""


def public_fn(x: int) -> int:
    """A documented public function."""
    return x


def _helper(y):
    return y


class Widget:
    """A widget."""

    def method(self, n: int) -> None:
        ...
'''

_B_PY = """\
def beta() -> None:
    ...
"""


def _build_symbol_repo(root: Path) -> None:
    """A mini-repo: public+private+method symbols, a nested file, a non-py file."""
    _touch(root, "pkg/a.py", _A_PY)
    _touch(root, "pkg/sub/b.py", _B_PY)
    _touch(root, "notes.txt", "just some prose, not python\n")


def _symbol_inv(root: Path) -> SymbolInventory:
    inv = discover_files(root, include=("**/*.py", "**/*.txt"))
    return discover_symbols(inv, root)


def test_discover_symbols_exact_symbol_names_per_file(tmp_path: Path) -> None:
    _build_symbol_repo(tmp_path)
    sinv = _symbol_inv(tmp_path)

    assert isinstance(sinv, SymbolInventory)
    by_path = {fs.path: fs for fs in sinv.files}

    # pkg/a.py: public fn, private helper, class + its method (qualified name).
    a = by_path["pkg/a.py"]
    assert a.language == "python"
    assert tuple(s.name for s in a.symbols) == (
        "public_fn",
        "_helper",
        "Widget",
        "Widget.method",
    )
    # is_public flags follow extract._is_public (underscore-prefixed = private).
    pubs = {s.name: s.is_public for s in a.symbols}
    assert pubs == {
        "public_fn": True,
        "_helper": False,
        "Widget": True,
        "Widget.method": True,
    }

    # pkg/sub/b.py: a single public function.
    b = by_path["pkg/sub/b.py"]
    assert tuple(s.name for s in b.symbols) == ("beta",)


def test_non_python_file_tracked_with_empty_symbols(tmp_path: Path) -> None:
    _build_symbol_repo(tmp_path)
    sinv = _symbol_inv(tmp_path)
    by_path = {fs.path: fs for fs in sinv.files}

    txt = by_path["notes.txt"]
    assert txt.language == "unknown"
    assert txt.symbols == ()  # tracked, never dropped (losslessness)


def test_symbol_inventory_order_matches_file_inventory(tmp_path: Path) -> None:
    _build_symbol_repo(tmp_path)
    inv = discover_files(tmp_path, include=("**/*.py", "**/*.txt"))
    sinv = discover_symbols(inv, tmp_path)

    assert tuple(fs.path for fs in sinv.files) == tuple(cf.path for cf in inv.files)
    # language carried through verbatim from the file inventory.
    assert tuple(fs.language for fs in sinv.files) == tuple(
        cf.language for cf in inv.files
    )
    assert sinv.root == inv.root


def test_discover_symbols_reuses_extract_file_symbols(tmp_path: Path) -> None:
    # The stored symbols are exactly what extract.extract_file produces, in order.
    from custodex.extract import extract_file

    _build_symbol_repo(tmp_path)
    sinv = _symbol_inv(tmp_path)
    by_path = {fs.path: fs for fs in sinv.files}

    expected = tuple(extract_file(tmp_path / "pkg/a.py"))
    assert by_path["pkg/a.py"].symbols == expected


def test_discover_symbols_deterministic(tmp_path: Path) -> None:
    _build_symbol_repo(tmp_path)
    inv = discover_files(tmp_path, include=("**/*.py", "**/*.txt"))
    first = discover_symbols(inv, tmp_path)
    second = discover_symbols(inv, tmp_path)
    assert first == second
    assert first.files == second.files


def test_discover_symbols_no_fs_mutation(tmp_path: Path) -> None:
    _build_symbol_repo(tmp_path)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    _symbol_inv(tmp_path)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after


def test_empty_inventory_yields_empty_symbol_inventory(tmp_path: Path) -> None:
    inv = discover_files(tmp_path, include=())  # matches nothing
    sinv = discover_symbols(inv, tmp_path)
    assert sinv.files == ()
    assert sinv.root == inv.root


def test_unparseable_python_file_raises_extraction_error(tmp_path: Path) -> None:
    # A syntax-error python file aborts the scan loudly (K8) — ExtractionError
    # propagates from extract.extract_file, no silent skip in this slice.
    _touch(tmp_path, "good.py", "def ok(): ...\n")
    _touch(tmp_path, "bad.py", "def broken(:\n")
    inv = discover_files(tmp_path)
    with pytest.raises(ExtractionError) as exc:
        discover_symbols(inv, tmp_path)
    assert "bad.py" in str(exc.value)


def test_extraction_error_is_custodex_error(tmp_path: Path) -> None:
    _touch(tmp_path, "bad.py", "class :\n")
    inv = discover_files(tmp_path)
    with pytest.raises(CodeDocMonitorError):
        discover_symbols(inv, tmp_path)


def test_filesymbols_is_frozen_and_forbids_extra() -> None:
    fs = FileSymbols(path="a.py", language="python", symbols=())
    with pytest.raises(ValidationError):
        fs.path = "b.py"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        FileSymbols(path="a.py", language="python", symbols=(), bogus=1)  # type: ignore[call-arg]


def test_symbol_inventory_is_frozen_and_forbids_extra() -> None:
    si = SymbolInventory(root="/r", files=())
    with pytest.raises(ValidationError):
        si.root = "/x"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        SymbolInventory(root="/r", files=(), bogus=1)  # type: ignore[call-arg]
