"""A tiny stand-in for *some other team's* library — the cdx adopter example.

This module is NOT part of the custodex engine; it is a self-contained
"external repo" that ADOPTS cdx (its own ``cdmon.yaml`` maps these public
functions onto ``docs/api.md``'s managed ``symbols`` region). The e2e test
(``tests/test_example_external.py``) heals this doc and reports the records to an
in-process central server, proving the whole adopter loop offline (K4).
"""

from __future__ import annotations

DEFAULT_WIDTH = 80


def make_widget(label: str, *, width: int = DEFAULT_WIDTH) -> str:
    """Return a ``label`` centered inside a box ``width`` characters wide."""
    return label.center(width)


def widget_area(width: int, height: int) -> int:
    """Return the area of a ``width`` x ``height`` widget."""
    return width * height
