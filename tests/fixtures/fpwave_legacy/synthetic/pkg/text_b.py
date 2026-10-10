"""Text helpers (B)."""


def clean(name: str, *, upper: bool = False) -> str:
    """Clean ``name``, optionally upper-casing it."""
    return name.upper() if upper else name.lower()
