# Document Layout Standard (v1.0.0)

This standard defines **how a managed document is written** — the file
structure of the Markdown source and its derived HTML twin — so that every
project adopting `code-doc-monitor` lays its docs out the same way. The content
of the managed regions is governed by the code surface (see `ARCHITECTURE.md`);
this standard governs the *shape of the file around them*.

It is **machine-checked**, not just documented: `cdmon lint` validates a doc
against every rule below, and `cdmon new-doc` scaffolds a conformant file. A
non-conforming doc fails `cdmon lint` the same way stale content fails
`cdmon check`.

## 1. Canonical skeleton

A managed Markdown document has a fixed anchor order:

```markdown
---
cdm:
  audience: eng-guide          # matches the document's audience in the config
  fingerprint: 34b338becd0329f1 # managed: the code surface hash (heal refreshes)
  schema_version: "1.0.0"      # the Layout Standard version this doc follows
---
# <Title>

> <One-line purpose — a single blockquote describing what this doc covers.>

<Freely-authored human prose. Any Markdown is allowed here.>

<!-- CDM:BEGIN <region-key> -->
…generated content (owned by the engine, never hand-edited)…
<!-- CDM:END <region-key> -->
```

Required anchors, in order:

1. **Front matter** — a leading `---` … `---` YAML fence holding the managed
   `cdm:` mapping (§2).
2. **Title** — the first non-blank body line is a single `#` H1.
3. **Purpose** — a `>` blockquote immediately following the title.
4. **Prose** — zero or more human-authored blocks.
5. **Managed regions** — zero or more `CDM:BEGIN`/`CDM:END` blocks (§3), one per
   key declared in the document's `region_keys`.

Prose may appear between, before, or after regions; the linter does not police
prose content, only that the anchors above are present and well-formed.

## 2. Front-matter schema

The front matter MUST carry a `cdm:` mapping with three managed keys:

| key | meaning | who writes it |
|-----|---------|---------------|
| `schema_version` | the Layout Standard version this doc follows (`"1.0.0"`) | scaffolder / `lint --fix` |
| `audience` | `user-guide` or `eng-guide`; MUST equal the document's audience in the config | scaffolder / `lint --fix` |
| `fingerprint` | the code surface hash; refreshed on every heal | engine (`heal`) |

`schema_version` and `audience` are **static** — authored once and preserved
across heals (heal only ever rewrites `fingerprint`). Any other front-matter
keys a project wants to add are allowed and left untouched.

## 3. Marker grammar

Managed regions use **one** grammar everywhere:

```
<!-- CDM:BEGIN <region-key> -->
<!-- CDM:END <region-key> -->
```

- One key per line, matched on `<region-key>`; markers must balance and may not
  nest or duplicate.
- A region present in the doc but **not** declared in the config's
  `region_keys` is an error (`UNDECLARED_REGION`) — declare it or remove it.
- A declared region **absent** from the doc is an error (`MISSING_REGION`) —
  scaffolding adds it.

### Helium alias

The `helium` project predates this standard and uses an equivalent grammar:

```
<!-- HELIUM:AUTOGEN <key> START -->
<!-- HELIUM:AUTOGEN <key> END -->
```

This is a **documented alias** of the `CDM:BEGIN/END` grammar — same semantics
(balanced, non-nesting, keyed regions), different spelling. New projects use
`CDM:BEGIN/END`; helium keeps its spelling.

## 4. HTML pairing rule

When a document declares an HTML twin (`html: true` in its config spec), the
HTML is a **pure derivation** of the Markdown — never hand-edited:

- **1:1 path map** — `X.md` → `X.html` (same stem, `.html` suffix).
- **Embedded source hash** — the HTML carries the Markdown body hash in a
  `<meta name="code-doc-md-sha256" content="…">` tag (or, for helium,
  `helium-docs-md-sha256`). `cdmon lint` recomputes the hash of the current
  Markdown **body** and flags `HTML_STALE` on a mismatch and `HTML_MISSING` /
  `HTML_NOT_DERIVED` when the twin or its hash is absent.
- **Do-not-edit banner** — the HTML states it is generated.

The hash covers the Markdown **body** (everything after the front matter), so a
fingerprint-only refresh does not invalidate the HTML, but any change a reader
would see does. Audience split is preserved: humans read `*.html` /
`USER.html`; agents read the `.md` / `LLM.md`.

## 5. Issue codes

`cdmon lint` reports these codes (one per violation):

| code | rule |
|------|------|
| `MISSING_FRONT_MATTER` | no `---` front-matter fence |
| `MISSING_SCHEMA_VERSION` | `cdm.schema_version` absent |
| `SCHEMA_VERSION_MISMATCH` | `cdm.schema_version` ≠ the standard version |
| `MISSING_AUDIENCE` | `cdm.audience` absent |
| `AUDIENCE_MISMATCH` | `cdm.audience` ≠ the config's audience |
| `MISSING_FINGERPRINT` | `cdm.fingerprint` absent |
| `MISSING_TITLE` | no leading `#` H1 |
| `MISSING_PURPOSE` | no `>` blockquote after the title |
| `UNDECLARED_REGION` | a region not in `region_keys` |
| `MISSING_REGION` | a declared region not in the doc |
| `MALFORMED_STRUCTURE` | unbalanced / nested / duplicate markers |
| `HTML_MISSING` | declared HTML twin file is absent |
| `HTML_NOT_DERIVED` | HTML twin lacks the embedded source hash |
| `HTML_STALE` | embedded hash ≠ current Markdown body hash |

## 6. Workflow

```bash
cdmon new-doc <doc-id>     # scaffold a conformant .md from the config + code
cdmon lint                 # validate every doc against this standard (exit 1 on issues)
cdmon lint --fix           # stamp missing static front matter (schema_version/audience)
cdmon check                # content drift (orthogonal to lint — run both in CI)
```

`lint` (structure) and `check` (content) are orthogonal gates; CI should run
both.

## 7. Collection / index regions

A managed region can list **other documents** instead of code — a collection or
landing page. Declare a `region_templates` entry with `source: index`; the
region's body is then a generated table over every *other* document in the
config (the index document excludes itself), kept in sync like any code-backed
region (re-purpose, rename, add, or remove a sibling and the index drifts until
rebuilt). Set `kind: <audience>` to list only `user-guide` or `eng-guide` docs.

```yaml
region_templates:
  api-index:
    source: index
    # kind: eng-guide          # optional: restrict to one audience
    columns:
      - {header: "Document",       field: "title"}    # linked to the doc
      - {header: "What it covers", field: "summary"}

documents:
  - id: api-index
    path: docs/api/index.md
    audience: eng-guide
    region_keys: [api-index]    # an index doc needs no code_refs
```

Each row is one document; a column's `field` selects a synthetic per-doc value:

| field | value |
|-------|-------|
| `doc_id` | the document id |
| `title` | the doc's `#` H1, rendered as a Markdown link to its HTML twin (`html: true`) or `.md` |
| `summary` | the doc's leading `>` purpose blockquote |
| `link` | the bare relative link target |
| `audience` | `user-guide` / `eng-guide` |
| `path` | the doc's repo-relative path |

Because an index has no code surface, its fingerprint is stable and the
meaningful drift signal is the region body itself; `cdmon monitor --apply`
regenerates it (the engine renders the table with all-docs context and the
backend applies it).
