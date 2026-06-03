---
cdm:
  audience: user-guide
  fingerprint: 96ce44e72bdc8449
  schema_version: 1.0.0
---

# Flag aliases

> Legacy flags the greeter rewrites or rejects.

These rules come from `flags.json`. A `replace` flag is rewritten to its
replacement; an `error` flag is refused.

<!-- CDM:BEGIN flags -->
| Flag | Replaced by | Action | Comment |
|---|---|---|---|
| --loud | --shout | replace | legacy alias for --shout |
| --silent |  | error | not supported; use --repeat 0 |
<!-- CDM:END flags -->

Back to the [command-line options](cli.md).
