"""Repo code-file discovery (A-01) — pure, stdlib-only, deterministic.

The first layer of EPIC A (lossless coverage): walk a repo ``root`` and return
the **exact** set of code files it contains, as repo-relative POSIX paths, each
tagged with a coarse ``language`` derived from its extension.

Design constraints upheld here:

* **K0** — stdlib only. Glob matching is a small in-house translation to
  :mod:`re` so ``**`` means "any number of path segments, including none"
  (``fnmatch`` alone cannot express that, and ``PurePath.match`` only gained
  recursive ``**`` after our floor Python). No new dependency is added.
* **K1** — pure. The filesystem is read, never written; no backend is called.
* **K8** — loud. A ``root`` that is missing or is not a directory raises a typed
  :class:`InventoryError` with a clear message, never a silent empty result.
* **K10** — deterministic. Output is sorted by ``path`` and deduped, so the same
  tree always yields an identical :class:`Inventory` regardless of the order the
  filesystem happens to iterate. No wall-clock is read.

A file is included iff it matches at least one ``include`` glob AND zero
``exclude`` globs. A file that matches an include but whose extension is unknown
is kept with ``language="unknown"`` — losslessness means we never drop a matched
file just because we can't name its language.

Symbol-level inventory (A-02) extends this: :func:`discover_symbols` attaches the
symbol surface of each **python** file — reusing :func:`extract.extract_file`, it
never re-implements AST parsing (K0). Non-python files are kept with
``symbols=()`` (lossless — tracked, never dropped). Output preserves
:class:`Inventory` order and :func:`extract.extract_file` symbol order (K10). An
unparseable / unreadable python file lets :class:`ExtractionError` propagate
(loud — K8): a syntax-error file aborts the scan rather than silently skipping.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .errors import InventoryError
from .extract import Symbol, extract_file

__all__ = [
    "CodeFile",
    "Inventory",
    "FileSymbols",
    "SymbolInventory",
    "DEFAULT_INCLUDE",
    "DEFAULT_EXCLUDE",
    "discover_files",
    "discover_symbols",
]

# Frozen + extra="forbid": an inventory is an immutable, normalized snapshot of
# the repo (K10); an unknown field is a programming error, not a silent pass.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

DEFAULT_INCLUDE: tuple[str, ...] = ("**/*.py",)
DEFAULT_EXCLUDE: tuple[str, ...] = (
    "**/.*/**",
    "**/__pycache__/**",
    "**/.venv/**",
)

# Extension (lowercased, with dot) → coarse language label. Deliberately small;
# anything matched by an include but absent here is kept as "unknown" so no file
# is ever dropped for lack of a mapping (losslessness).
_LANGUAGE_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
}


class CodeFile(BaseModel):
    """One discovered code file: a repo-relative POSIX path and its language."""

    model_config = _MODEL_CONFIG

    path: str  # repo-relative, POSIX separators
    language: str  # derived from extension ("python", ... "unknown")


class Inventory(BaseModel):
    """The sorted, deduped set of code files discovered under ``root`` (K10)."""

    model_config = _MODEL_CONFIG

    root: str  # POSIX-normalized absolute root
    files: tuple[CodeFile, ...]  # sorted by path, deduped


class FileSymbols(BaseModel):
    """One inventoried file plus its extracted symbol surface (A-02).

    ``symbols`` is the tuple produced by :func:`extract.extract_file` for a
    python file, in that function's order; it is ``()`` for a non-python file
    (or a python file with no top-level symbols) — losslessness means such a
    file is tracked, never dropped.
    """

    model_config = _MODEL_CONFIG

    path: str  # repo-relative POSIX, matches the source CodeFile.path
    language: str
    symbols: tuple[Symbol, ...]


class SymbolInventory(BaseModel):
    """The symbol-level twin of :class:`Inventory` — same file order (K10)."""

    model_config = _MODEL_CONFIG

    root: str  # POSIX-normalized absolute root (mirrors Inventory.root)
    files: tuple[FileSymbols, ...]  # same order as the source Inventory.files


def _translate(pattern: str) -> re.Pattern[str]:
    """Compile a POSIX glob to a regex with proper ``**`` semantics.

    * ``**/`` — zero or more leading path segments (so a top-level ``.venv``
      still matches ``**/.venv/**``).
    * ``**`` — any characters, crossing ``/``.
    * ``*`` — any characters except ``/`` (one path segment).
    * ``?`` — one character except ``/``.

    Everything else is matched literally. The whole path must match (``\\Z``).
    """
    i = 0
    n = len(pattern)
    out: list[str] = ["(?s:"]
    while i < n:
        if pattern[i : i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append(r")\Z")
    return re.compile("".join(out))


def _matches_any(rel_path: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(p.match(rel_path) is not None for p in patterns)


def _language_for(rel_path: str) -> str:
    return _LANGUAGE_BY_EXT.get(Path(rel_path).suffix.lower(), "unknown")


def discover_files(
    root: Path,
    *,
    include: tuple[str, ...] = DEFAULT_INCLUDE,
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE,
) -> Inventory:
    """Discover code files under ``root`` (pure, deterministic — K1/K10).

    Returns an :class:`Inventory` of repo-relative POSIX paths, sorted by
    ``path`` and deduped, for every file that matches at least one ``include``
    glob and no ``exclude`` glob. Raises :class:`InventoryError` if ``root`` is
    missing or not a directory (K8).
    """
    if not root.exists():
        raise InventoryError(f"inventory root does not exist: {root}")
    if not root.is_dir():
        raise InventoryError(f"inventory root is not a directory: {root}")

    resolved = root.resolve()
    includes = tuple(_translate(p) for p in include)
    excludes = tuple(_translate(p) for p in exclude)

    # os.walk yields each file exactly once, so one CodeFile is appended per
    # file regardless of how many include globs it matches — overlapping
    # includes are inherently deduped (no per-glob fan-out).
    files: list[CodeFile] = []
    for dirpath, _dirnames, filenames in os.walk(resolved):
        base = Path(dirpath)
        for name in filenames:
            rel = (base / name).relative_to(resolved).as_posix()
            if not _matches_any(rel, includes):
                continue
            if _matches_any(rel, excludes):
                continue
            files.append(CodeFile(path=rel, language=_language_for(rel)))

    files.sort(key=lambda f: f.path)
    return Inventory(root=resolved.as_posix(), files=tuple(files))


def discover_symbols(inventory: Inventory, root: Path) -> SymbolInventory:
    """Attach each inventoried file's symbol surface (A-02 — pure, K1/K10).

    For every :class:`CodeFile` in ``inventory.files`` (in order), a python file
    is reduced to its symbols via :func:`extract.extract_file` (reused, never
    re-implemented — K0); any other file is kept with ``symbols=()`` so it is
    tracked rather than dropped (losslessness). ``root`` is the directory the
    repo-relative ``path``\\ s are resolved against (typically the same ``root``
    passed to :func:`discover_files`).

    The output preserves both ``Inventory.files`` order and each file's
    ``extract_file`` symbol order (K10), and never mutates the filesystem (K1).

    An unparseable or unreadable python file lets :class:`ExtractionError`
    propagate unchanged (loud — K8): a syntax-error file aborts the scan rather
    than being silently skipped. A resilient ``--skip-unparseable`` mode for
    scanning arbitrary external repos is deferred (see ``.project/problems``).
    """
    out: list[FileSymbols] = []
    for code_file in inventory.files:
        if code_file.language == "python":
            symbols = tuple(extract_file(root / code_file.path))
        else:
            symbols = ()
        out.append(
            FileSymbols(
                path=code_file.path,
                language=code_file.language,
                symbols=symbols,
            )
        )
    return SymbolInventory(root=inventory.root, files=tuple(out))
