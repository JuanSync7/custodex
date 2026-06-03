---
cdm:
  audience: eng-guide
  fingerprint: 0feef5496fd123b1
  schema_version: 1.0.0
---

# Greeter library

> The Python greeter library — its public functions and classes.

This is an **engineering guide**: because the audience is `eng-guide`, the
managed symbol table below tracks the full implementation surface (docstrings
included), so an internal change is flagged as drift.

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| DEFAULT_GREETING | variable | DEFAULT_GREETING = 'Hello' |
| Greeter | class | class Greeter |
| Greeter.__init__ | method | def __init__(self, greeting: str = DEFAULT_GREETING) -> None |
| Greeter.greet | method | def greet(self, name: str) -> str |
| greet | function | def greet(name: str, *, shout: bool = False) -> str |
<!-- CDM:END symbols -->
