"""Utilities."""


def normalise(text: str, *, keep_case: bool = False) -> str:
    """Strip ``text``, optionally keeping its case."""
    stripped = text.strip()
    return stripped if keep_case else stripped.lower()
