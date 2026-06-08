"""Tests for code_doc_monitor.extract (CDM-02).

Covers AST-only extraction (K0), the audience filter (K3), sub-file selection,
and deterministic, audience-normalized hashing (K10). Written before the
implementation (K9, TDD).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.config import Audience, CodeRef, DocumentSpec
from code_doc_monitor.errors import ExtractionError
from code_doc_monitor.extract import (
    DocumentSurface,
    Extractor,
    PythonAstExtractor,
    Record,
    SurfaceFingerprint,
    Symbol,
    build_document_surface,
    extract_file,
    get_extractor,
    register_extractor,
)

# A sample module exercising every symbol kind we extract. The docstring on
# `foo` is the testable proxy for "comment-like prose" (K3).
SAMPLE = '''\
"""Module docstring."""

VAR = 1
_PRIVATE = 2


def foo(a, b=1, *args) -> int:
    """Foo does a thing."""
    return a + b


def _helper(x):
    return x


class Widget(Base):
    """A widget."""

    def __init__(self, name):
        self.name = name

    def render(self) -> str:
        return self.name

    def _internal(self):
        return None
'''


def _write(tmp_path: Path, text: str = SAMPLE) -> Path:
    p = tmp_path / "sample.py"
    p.write_text(text, encoding="utf-8")
    return p


def _by_name(symbols: list[Symbol]) -> dict[str, Symbol]:
    return {s.name: s for s in symbols}


def _doc(audience: Audience, *refs: CodeRef) -> DocumentSpec:
    return DocumentSpec(
        id="d", path="docs/d.md", audience=audience, code_refs=tuple(refs)
    )


# --------------------------------------------------------------------------- #
# extract_file                                                                  #
# --------------------------------------------------------------------------- #
def test_extract_file_finds_all_kinds(tmp_path: Path) -> None:
    syms = _by_name(extract_file(_write(tmp_path)))

    assert set(syms) == {
        "VAR",
        "_PRIVATE",
        "foo",
        "_helper",
        "Widget",
        "Widget.__init__",
        "Widget.render",
        "Widget._internal",
    }

    assert syms["VAR"].kind == "variable"
    assert syms["foo"].kind == "function"
    assert syms["Widget"].kind == "class"
    assert syms["Widget.render"].kind == "method"


def test_extract_file_public_flags(tmp_path: Path) -> None:
    syms = _by_name(extract_file(_write(tmp_path)))

    assert syms["VAR"].is_public is True
    assert syms["_PRIVATE"].is_public is False
    assert syms["foo"].is_public is True
    assert syms["_helper"].is_public is False
    assert syms["Widget"].is_public is True
    assert syms["Widget.render"].is_public is True
    assert syms["Widget._internal"].is_public is False
    # Dunder __init__ counts as part of the class surface (treated public).
    assert syms["Widget.__init__"].is_public is True


def test_extract_file_signatures(tmp_path: Path) -> None:
    syms = _by_name(extract_file(_write(tmp_path)))

    assert syms["foo"].signature == "def foo(a, b=1, *args) -> int"
    assert syms["Widget"].signature == "class Widget(Base)"
    assert syms["Widget.render"].signature == "def render(self) -> str"
    assert syms["VAR"].signature == "VAR = 1"


def test_extract_file_docstrings(tmp_path: Path) -> None:
    syms = _by_name(extract_file(_write(tmp_path)))

    assert syms["foo"].docstring == "Foo does a thing."
    assert syms["Widget"].docstring == "A widget."
    assert syms["Widget.render"].docstring is None
    assert syms["VAR"].docstring is None


def test_extract_file_async_def(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text("async def go(x):\n    return x\n", encoding="utf-8")
    syms = _by_name(extract_file(p))
    assert syms["go"].kind == "function"
    assert syms["go"].signature == "async def go(x)"


def test_extract_file_annotated_assignment(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text("TIMEOUT: int = 30\nNAME: str\n", encoding="utf-8")
    syms = _by_name(extract_file(p))
    assert syms["TIMEOUT"].kind == "variable"
    assert syms["TIMEOUT"].signature == "TIMEOUT: int = 30"
    assert syms["NAME"].signature == "NAME: str"


def test_extract_file_complex_signature(tmp_path: Path) -> None:
    """Annotated, positional-only, *args, keyword-only, and **kwargs params."""
    p = tmp_path / "c.py"
    p.write_text(
        "def f(a, b: int, /, c=3, *args: str, d, e: int = 5, **kw: bool) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    syms = _by_name(extract_file(p))
    assert syms["f"].signature == (
        "def f(a, b: int, /, c=3, *args: str, d, e: int = 5, **kw: bool) -> None"
    )


def test_extract_file_keyword_only_bare_star(tmp_path: Path) -> None:
    p = tmp_path / "k.py"
    p.write_text("def g(a, *, b):\n    pass\n", encoding="utf-8")
    syms = _by_name(extract_file(p))
    assert syms["g"].signature == "def g(a, *, b)"


def test_extract_file_class_keyword_base(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("class Meta(Base, metaclass=ABCMeta):\n    pass\n", encoding="utf-8")
    syms = _by_name(extract_file(p))
    assert syms["Meta"].signature == "class Meta(Base, metaclass=ABCMeta)"


def test_extract_file_tuple_assignment_ignored(tmp_path: Path) -> None:
    """A tuple-unpacking target has no plain Name, so yields no variable."""
    p = tmp_path / "t.py"
    p.write_text("(a, b) = (1, 2)\nC = 3\n", encoding="utf-8")
    syms = _by_name(extract_file(p))
    assert "C" in syms
    assert "a" not in syms and "b" not in syms


def test_extract_file_annotated_attribute_target_ignored(tmp_path: Path) -> None:
    """An annotated assignment to a non-Name target yields no variable."""
    p = tmp_path / "ann.py"
    p.write_text("obj.attr: int = 1\nD = 2\n", encoding="utf-8")
    syms = _by_name(extract_file(p))
    assert "D" in syms
    assert "attr" not in syms


def test_extract_file_unreadable_raises(tmp_path: Path) -> None:
    """A directory masquerading as a path triggers the OSError branch."""
    d = tmp_path / "adir.py"
    d.mkdir()
    with pytest.raises(ExtractionError):
        extract_file(d)


def test_extract_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="(?i)not found|cannot read|missing"):
        extract_file(tmp_path / "nope.py")


def test_extract_file_syntax_error_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(ExtractionError, match="(?i)syntax"):
        extract_file(p)


# --------------------------------------------------------------------------- #
# Sub-file selection                                                            #
# --------------------------------------------------------------------------- #
def test_select_whole_file(tmp_path: Path) -> None:
    _write(tmp_path)
    doc = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    surface = build_document_surface(doc, tmp_path)
    assert {s.name for s in surface.symbols} == {
        "VAR",
        "_PRIVATE",
        "foo",
        "_helper",
        "Widget",
        "Widget.__init__",
        "Widget.render",
        "Widget._internal",
    }


def test_select_by_symbol_name(tmp_path: Path) -> None:
    _write(tmp_path)
    doc = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py", symbols=("foo",)))
    surface = build_document_surface(doc, tmp_path)
    assert {s.name for s in surface.symbols} == {"foo"}


def test_select_class_includes_methods(tmp_path: Path) -> None:
    _write(tmp_path)
    doc = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py", symbols=("Widget",)))
    surface = build_document_surface(doc, tmp_path)
    assert {s.name for s in surface.symbols} == {
        "Widget",
        "Widget.__init__",
        "Widget.render",
        "Widget._internal",
    }


def test_select_by_lines(tmp_path: Path) -> None:
    _write(tmp_path)
    # foo spans lines 7-9 in SAMPLE.
    doc = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py", lines=((7, 9),)))
    surface = build_document_surface(doc, tmp_path)
    assert {s.name for s in surface.symbols} == {"foo"}


def test_select_by_names_only_variables(tmp_path: Path) -> None:
    _write(tmp_path)
    # `names` selects module-level variables; `foo` is a function so excluded.
    doc = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py", names=("VAR", "foo")))
    surface = build_document_surface(doc, tmp_path)
    assert {s.name for s in surface.symbols} == {"VAR"}


def test_combine_refs_dedupes_and_orders(tmp_path: Path) -> None:
    _write(tmp_path)
    doc = _doc(
        Audience.ENG_GUIDE,
        CodeRef(path="sample.py", symbols=("foo",)),
        CodeRef(path="sample.py", symbols=("foo",)),
        CodeRef(path="sample.py", names=("VAR",)),
    )
    surface = build_document_surface(doc, tmp_path)
    names = [s.name for s in surface.symbols]
    assert names == sorted(names)  # deterministic order
    assert names.count("foo") == 1  # deduped


# --------------------------------------------------------------------------- #
# Audience filter (K3)                                                          #
# --------------------------------------------------------------------------- #
def test_user_guide_excludes_private(tmp_path: Path) -> None:
    _write(tmp_path)
    doc = _doc(Audience.USER_GUIDE, CodeRef(path="sample.py"))
    surface = build_document_surface(doc, tmp_path)
    names = {s.name for s in surface.symbols}
    assert "_helper" not in names
    assert "_PRIVATE" not in names
    assert "Widget._internal" not in names
    assert "foo" in names
    assert "Widget.render" in names


def test_eng_guide_includes_private(tmp_path: Path) -> None:
    _write(tmp_path)
    doc = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    surface = build_document_surface(doc, tmp_path)
    names = {s.name for s in surface.symbols}
    assert "_helper" in names
    assert "_PRIVATE" in names
    assert "Widget._internal" in names


# --------------------------------------------------------------------------- #
# surface_hash (K10)                                                            #
# --------------------------------------------------------------------------- #
def test_surface_hash_stable_across_builds(tmp_path: Path) -> None:
    _write(tmp_path)
    doc = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    h1 = build_document_surface(doc, tmp_path).surface_hash()
    h2 = build_document_surface(doc, tmp_path).surface_hash()
    assert h1 == h2
    assert len(h1) == 16


def test_docstring_edit_moves_eng_not_user(tmp_path: Path) -> None:
    """The key audience behaviour (K3): a docstring-only edit moves the
    eng-guide hash but NOT the user-guide hash."""
    _write(tmp_path, SAMPLE)
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    usr = _doc(Audience.USER_GUIDE, CodeRef(path="sample.py"))
    eng_before = build_document_surface(eng, tmp_path).surface_hash()
    usr_before = build_document_surface(usr, tmp_path).surface_hash()

    edited = SAMPLE.replace('"""Foo does a thing."""', '"""Foo does SOMETHING ELSE."""')
    assert edited != SAMPLE
    _write(tmp_path, edited)

    eng_after = build_document_surface(eng, tmp_path).surface_hash()
    usr_after = build_document_surface(usr, tmp_path).surface_hash()

    assert eng_after != eng_before  # eng-guide tracks docstrings
    assert usr_after == usr_before  # user-guide ignores docstrings


def test_signature_change_moves_both(tmp_path: Path) -> None:
    _write(tmp_path, SAMPLE)
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    usr = _doc(Audience.USER_GUIDE, CodeRef(path="sample.py"))
    eng_before = build_document_surface(eng, tmp_path).surface_hash()
    usr_before = build_document_surface(usr, tmp_path).surface_hash()

    edited = SAMPLE.replace("def foo(a, b=1, *args) -> int:", "def foo(a, b=2) -> str:")
    assert edited != SAMPLE
    _write(tmp_path, edited)

    eng_after = build_document_surface(eng, tmp_path).surface_hash()
    usr_after = build_document_surface(usr, tmp_path).surface_hash()

    assert eng_after != eng_before
    assert usr_after != usr_before


def test_private_change_does_not_move_user_guide(tmp_path: Path) -> None:
    _write(tmp_path, SAMPLE)
    usr = _doc(Audience.USER_GUIDE, CodeRef(path="sample.py"))
    before = build_document_surface(usr, tmp_path).surface_hash()

    edited = SAMPLE.replace("def _helper(x):", "def _helper(x, y, z):")
    assert edited != SAMPLE
    _write(tmp_path, edited)

    after = build_document_surface(usr, tmp_path).surface_hash()
    assert after == before


def test_surface_hash_differs_by_audience(tmp_path: Path) -> None:
    _write(tmp_path)
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    usr = _doc(Audience.USER_GUIDE, CodeRef(path="sample.py"))
    assert (
        build_document_surface(eng, tmp_path).surface_hash()
        != build_document_surface(usr, tmp_path).surface_hash()
    )


def test_build_missing_file_raises(tmp_path: Path) -> None:
    doc = _doc(Audience.ENG_GUIDE, CodeRef(path="ghost.py"))
    with pytest.raises(ExtractionError):
        build_document_surface(doc, tmp_path)


def test_document_surface_is_frozen(tmp_path: Path) -> None:
    _write(tmp_path)
    doc = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    surface = build_document_surface(doc, tmp_path)
    assert isinstance(surface, DocumentSurface)
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        surface.doc_id = "x"  # type: ignore[misc]


def test_long_variable_value_is_elided(tmp_path: Path) -> None:
    """A long constant value collapses to ``...``; short values render verbatim.

    ``ast.unparse`` normalizes whitespace, so a short multi-line literal collapses
    to a short single-line form (kept); only a genuinely long value is elided.
    """
    p = tmp_path / "m.py"
    long_list = "BIG = [" + ", ".join(str(i) for i in range(40)) + "]\n"
    p.write_text(
        'SHORT = 1\nLONG = "'
        + ("x" * 200)
        + '"\nSMALL = (\n    1,\n    2,\n)\n'
        + long_list,
        encoding="utf-8",
    )
    syms = {s.name: s for s in extract_file(p)}
    assert syms["SHORT"].signature == "SHORT = 1"
    assert syms["LONG"].signature == "LONG = ..."
    assert syms["SMALL"].signature == "SMALL = (1, 2)"  # short -> kept
    assert syms["BIG"].signature == "BIG = ..."  # long -> elided


# --------------------------------------------------------------------------- #
# P-01: Extractor protocol + registry                                          #
# --------------------------------------------------------------------------- #
def test_get_extractor_python_is_default(tmp_path: Path) -> None:
    ext = get_extractor("python")
    assert isinstance(ext, PythonAstExtractor)
    assert isinstance(ext, Extractor)  # runtime_checkable Protocol
    assert ext.language == "python"


def test_extract_file_routes_through_registry(tmp_path: Path) -> None:
    """extract_file is a thin wrapper over the registered python extractor."""
    p = _write(tmp_path)
    assert _by_name(extract_file(p)) == _by_name(get_extractor("python").extract(p))


def test_get_extractor_unknown_language_raises() -> None:
    with pytest.raises(ExtractionError):
        get_extractor("rust")


def test_register_extractor_roundtrip(tmp_path: Path) -> None:
    """A registered extractor is resolvable; restore the registry afterwards."""

    class _Toy:
        language = "toy"

        def extract(self, path: Path) -> list[Symbol]:
            return []

    try:
        register_extractor(_Toy())
        assert isinstance(get_extractor("toy"), _Toy)
    finally:
        from code_doc_monitor.extract import _EXTRACTORS

        _EXTRACTORS.pop("toy", None)


# --------------------------------------------------------------------------- #
# P-01: golden byte-invariance (the OFF==today oracle)                         #
# --------------------------------------------------------------------------- #
# Captured from the pre-P1 implementation over SAMPLE; the body tier MUST be
# byte-invisible when OFF, so these literals must never move.
_GOLDEN_USER_GUIDE = "9e9171f520832497"
_GOLDEN_ENG_GUIDE = "f688a396c2e8be27"


def test_surface_hash_golden_user_guide(tmp_path: Path) -> None:
    _write(tmp_path)
    usr = _doc(Audience.USER_GUIDE, CodeRef(path="sample.py"))
    assert build_document_surface(usr, tmp_path).surface_hash() == _GOLDEN_USER_GUIDE


def test_surface_hash_golden_eng_guide(tmp_path: Path) -> None:
    _write(tmp_path)
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    assert build_document_surface(eng, tmp_path).surface_hash() == _GOLDEN_ENG_GUIDE


def test_surface_hash_off_equals_explicit_false(tmp_path: Path) -> None:
    _write(tmp_path)
    for aud in (Audience.USER_GUIDE, Audience.ENG_GUIDE):
        surf = build_document_surface(_doc(aud, CodeRef(path="sample.py")), tmp_path)
        assert surf.surface_hash() == surf.surface_hash(include_body=False)


# --------------------------------------------------------------------------- #
# P-01: body-AST hash normalization                                            #
# --------------------------------------------------------------------------- #
_BODY_SRC = '''\
def f(a, b):
    """Doc."""
    total = a + b
    return total


class C:
    def m(self, x):
        return x * 2


VAR = 1
'''


def test_body_hash_present_for_func_and_method_only(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text(_BODY_SRC, encoding="utf-8")
    syms = _by_name(extract_file(p))
    assert syms["f"].body_hash is not None
    assert syms["C.m"].body_hash is not None
    assert syms["C"].body_hash is None  # class
    assert syms["VAR"].body_hash is None  # variable


def test_body_hash_insensitive_to_comments_and_formatting(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text(
        "def f(a, b):\n    total = a + b\n    return total\n", encoding="utf-8"
    )
    b = tmp_path / "b.py"
    b.write_text(
        "def f(a, b):\n"
        "    # an explanatory comment\n"
        "    total  =  a + b\n"
        "\n"
        "    return total\n",
        encoding="utf-8",
    )
    assert (
        _by_name(extract_file(a))["f"].body_hash
        == _by_name(extract_file(b))["f"].body_hash
    )


def test_body_hash_changes_on_logic_change(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("def f(a, b):\n    return a + b\n", encoding="utf-8")
    b = tmp_path / "b.py"
    b.write_text("def f(a, b):\n    return a - b\n", encoding="utf-8")
    assert (
        _by_name(extract_file(a))["f"].body_hash
        != _by_name(extract_file(b))["f"].body_hash
    )


def test_body_hash_ignores_docstring(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text('def f(a):\n    """One."""\n    return a\n', encoding="utf-8")
    b = tmp_path / "b.py"
    b.write_text(
        'def f(a):\n    """Two, different."""\n    return a\n', encoding="utf-8"
    )
    assert (
        _by_name(extract_file(a))["f"].body_hash
        == _by_name(extract_file(b))["f"].body_hash
    )


def test_body_hash_ignores_decorator(tmp_path: Path) -> None:
    """Decorators live on decorator_list, not .body — a deliberate P1 boundary."""
    a = tmp_path / "a.py"
    a.write_text("def f(a):\n    return a\n", encoding="utf-8")
    b = tmp_path / "b.py"
    b.write_text("@staticmethod\ndef f(a):\n    return a\n", encoding="utf-8")
    assert (
        _by_name(extract_file(a))["f"].body_hash
        == _by_name(extract_file(b))["f"].body_hash
    )


def test_body_hash_deterministic(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text(_BODY_SRC, encoding="utf-8")
    assert (
        _by_name(extract_file(p))["f"].body_hash
        == _by_name(extract_file(p))["f"].body_hash
    )


def test_body_hash_async_change_moves(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("async def f(a):\n    return await g(a)\n", encoding="utf-8")
    b = tmp_path / "b.py"
    b.write_text("async def f(a):\n    return await h(a)\n", encoding="utf-8")
    assert (
        _by_name(extract_file(a))["f"].body_hash
        != _by_name(extract_file(b))["f"].body_hash
    )


# --------------------------------------------------------------------------- #
# P-01: flag gating in surface_hash                                            #
# --------------------------------------------------------------------------- #
def _body_edit(src: str) -> str:
    edited = src.replace("return a + b", "return a * b")
    assert edited != src
    return edited


def test_body_tier_on_user_guide_is_invariant(tmp_path: Path) -> None:
    """The hard constraint: user-guide bytes never change under the flag (K3)."""
    _write(tmp_path)
    usr = _doc(Audience.USER_GUIDE, CodeRef(path="sample.py"))
    surf = build_document_surface(usr, tmp_path)
    assert surf.surface_hash(include_body=True) == surf.surface_hash(include_body=False)


def test_body_tier_on_eng_guide_moves_on_body_only_change(tmp_path: Path) -> None:
    _write(tmp_path, SAMPLE)
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    before = build_document_surface(eng, tmp_path).surface_hash(include_body=True)
    off_before = build_document_surface(eng, tmp_path).surface_hash(include_body=False)

    _write(tmp_path, _body_edit(SAMPLE))
    after = build_document_surface(eng, tmp_path).surface_hash(include_body=True)
    off_after = build_document_surface(eng, tmp_path).surface_hash(include_body=False)

    assert after != before  # ON: a body-only change moves the eng-guide hash
    assert (
        off_after == off_before
    )  # OFF: same change is invisible (signature unchanged)


def test_body_tier_on_user_guide_body_change_does_not_move(tmp_path: Path) -> None:
    _write(tmp_path, SAMPLE)
    usr = _doc(Audience.USER_GUIDE, CodeRef(path="sample.py"))
    before = build_document_surface(usr, tmp_path).surface_hash(include_body=True)

    _write(tmp_path, _body_edit(SAMPLE))
    after = build_document_surface(usr, tmp_path).surface_hash(include_body=True)
    assert after == before  # K3: a body change is a non-event for user-guide


def test_body_tier_on_class_var_only_surface_is_invariant(tmp_path: Path) -> None:
    """An eng-guide surface with no function/method body adds no body_hash key."""
    src = "class C(Base):\n    pass\n\n\nVAR = 1\n"
    p = tmp_path / "sample.py"
    p.write_text(src, encoding="utf-8")
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    surf = build_document_surface(eng, tmp_path)
    assert surf.surface_hash(include_body=True) == surf.surface_hash(include_body=False)


# --------------------------------------------------------------------------- #
# P-02: tiered SurfaceFingerprint                                              #
# --------------------------------------------------------------------------- #
def test_fingerprint_composite_equals_surface_hash(tmp_path: Path) -> None:
    """The composite IS surface_hash() — the unchanged identity (no re-baseline)."""
    _write(tmp_path)
    for aud in (Audience.USER_GUIDE, Audience.ENG_GUIDE):
        surf = build_document_surface(_doc(aud, CodeRef(path="sample.py")), tmp_path)
        for include_body in (False, True):
            fp = surf.fingerprint(include_body=include_body)
            assert fp.composite == surf.surface_hash(include_body=include_body)


def test_fingerprint_composite_matches_golden(tmp_path: Path) -> None:
    """Composite is byte-identical to the frozen P-01 golden (back-compat anchor)."""
    _write(tmp_path)
    usr = _doc(Audience.USER_GUIDE, CodeRef(path="sample.py"))
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    assert build_document_surface(usr, tmp_path).fingerprint().composite == (
        _GOLDEN_USER_GUIDE
    )
    assert build_document_surface(eng, tmp_path).fingerprint().composite == (
        _GOLDEN_ENG_GUIDE
    )


def test_fingerprint_signature_tier_always_present(tmp_path: Path) -> None:
    _write(tmp_path)
    for aud in (Audience.USER_GUIDE, Audience.ENG_GUIDE):
        surf = build_document_surface(_doc(aud, CodeRef(path="sample.py")), tmp_path)
        fp = surf.fingerprint()
        assert isinstance(fp.signature, str) and len(fp.signature) == 16


def test_fingerprint_docstring_tier_eng_only(tmp_path: Path) -> None:
    """The docstring tier exists for eng-guide, is None for user-guide (K3)."""
    _write(tmp_path)
    usr = build_document_surface(
        _doc(Audience.USER_GUIDE, CodeRef(path="sample.py")), tmp_path
    )
    eng = build_document_surface(
        _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py")), tmp_path
    )
    assert usr.fingerprint().docstring is None
    assert isinstance(eng.fingerprint().docstring, str)


def test_fingerprint_body_tier_gated(tmp_path: Path) -> None:
    """Body tier: None when off; present for eng-guide when on; None for user-guide."""
    _write(tmp_path)
    eng = build_document_surface(
        _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py")), tmp_path
    )
    usr = build_document_surface(
        _doc(Audience.USER_GUIDE, CodeRef(path="sample.py")), tmp_path
    )
    assert eng.fingerprint(include_body=False).body is None
    assert isinstance(eng.fingerprint(include_body=True).body, str)
    assert usr.fingerprint(include_body=True).body is None  # K3


def test_fingerprint_drifted_against_signature(tmp_path: Path) -> None:
    _write(tmp_path, SAMPLE)
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    before = build_document_surface(eng, tmp_path).fingerprint()
    _write(
        tmp_path, SAMPLE.replace("def foo(a, b=1, *args) -> int:", "def foo(a) -> int:")
    )
    after = build_document_surface(eng, tmp_path).fingerprint()
    assert after.drifted_against(before) == ("signature",)


def test_fingerprint_drifted_against_docstring(tmp_path: Path) -> None:
    _write(tmp_path, SAMPLE)
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    before = build_document_surface(eng, tmp_path).fingerprint()
    _write(
        tmp_path,
        SAMPLE.replace('"""Foo does a thing."""', '"""Foo does SOMETHING ELSE."""'),
    )
    after = build_document_surface(eng, tmp_path).fingerprint()
    assert after.drifted_against(before) == ("docstring",)


def test_fingerprint_drifted_against_body(tmp_path: Path) -> None:
    _write(tmp_path, SAMPLE)
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    before = build_document_surface(eng, tmp_path).fingerprint(include_body=True)
    _write(tmp_path, _body_edit(SAMPLE))
    after = build_document_surface(eng, tmp_path).fingerprint(include_body=True)
    assert after.drifted_against(before) == ("body",)


def test_fingerprint_drifted_against_identical_is_empty(tmp_path: Path) -> None:
    _write(tmp_path)
    eng = _doc(Audience.ENG_GUIDE, CodeRef(path="sample.py"))
    fp = build_document_surface(eng, tmp_path).fingerprint(include_body=True)
    assert fp.drifted_against(fp) == ()


def test_fingerprint_signature_tier_folds_records() -> None:
    """A records-only change moves the signature tier (records are structural)."""
    base = DocumentSurface(
        doc_id="d",
        audience=Audience.ENG_GUIDE,
        symbols=(),
        records=(Record(name="--x", kind="switch"),),
    )
    changed = DocumentSurface(
        doc_id="d",
        audience=Audience.ENG_GUIDE,
        symbols=(),
        records=(Record(name="--y", kind="switch"),),
    )
    assert changed.fingerprint().drifted_against(base.fingerprint()) == ("signature",)


def test_fingerprint_is_frozen() -> None:
    from pydantic import ValidationError

    fp = SurfaceFingerprint(signature="a", docstring=None, body=None, composite="a")
    with pytest.raises(ValidationError):
        fp.signature = "b"  # type: ignore[misc]
