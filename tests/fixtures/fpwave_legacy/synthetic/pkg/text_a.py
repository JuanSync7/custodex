"""Text helpers (A)."""


def clean(name: str) -> str:
    """Clean ``name``."""
    return _trim(name)


def _trim(name: str) -> str:
    return name.strip()
