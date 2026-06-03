"""A tiny greeter library (the eng-guide subject: Python symbols)."""

from __future__ import annotations

DEFAULT_GREETING = "Hello"


def greet(name: str, *, shout: bool = False) -> str:
    """Return a greeting for ``name``; upper-case it when ``shout`` is set."""
    message = f"{DEFAULT_GREETING}, {name}!"
    return message.upper() if shout else message


class Greeter:
    """A stateful greeter that remembers its greeting word."""

    def __init__(self, greeting: str = DEFAULT_GREETING) -> None:
        self.greeting = greeting

    def greet(self, name: str) -> str:
        """Greet ``name`` using this greeter's configured greeting."""
        return f"{self.greeting}, {name}!"
