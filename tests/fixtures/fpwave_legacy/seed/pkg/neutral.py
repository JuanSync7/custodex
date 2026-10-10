"""A plain module with no wave features."""

GREETING = "hello"


def greet(name: str) -> str:
    """Greet ``name``."""
    return f"{GREETING}, {name}"
