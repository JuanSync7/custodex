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
keys a project wants to add are allowed and left untouched. (The engine also
stamps additional *managed* `cdm.*` keys — `cdm.region_hashes` (§7) plus the
fingerprint-tier and region-anchor keys — which are engine-written, not
project-authored.)

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
| `INDEX_INCOMPLETE` | an `index: true` document does not link every document it indexes — honoring the index region's audience `kind` (§8) |

## 6. Workflow

```bash
cdmon new-doc <doc-id>     # scaffold a conformant .md from the config + code
cdmon lint                 # validate every doc against this standard (exit 1 on issues)
cdmon lint --fix           # stamp missing static front matter (schema_version/audience)
cdmon check                # content drift (orthogonal to lint — run both in CI)
cdmon build                # (re)render html:true docs to their .html twins (keeps the §4 pairing fresh)
```

`lint` (structure) and `check` (content) are orthogonal gates; CI should run
both.

## 7. Region authority modes

A region declares **who owns it** via the document's optional `region_modes`
map (region id → mode) in the config. An absent entry — and an absent map
entirely — means `generated`, so existing configs are unaffected (additive).

| mode | who authors it | what heal does |
|------|----------------|----------------|
| `generated` (default) | the engine | mechanically re-renders it from the code surface |
| `llm` | the backend (B-06) | renderer-backed: mechanically rendered + kept in sync; NO-renderer: backend-authored prose, re-authored when the code surface moves — see the rule below |
| `human` | a human | NEVER writes it; code drift only raises an advisory "review" signal |
| `llm-seeded` | the backend, then a human | behaves as `generated` until a human edits it (a stored per-region content hash diverges), then locks to `human` |

Every key in `region_modes` MUST be a region declared in that document's
`region_keys`; naming an undeclared region is a loud config error. The schema,
validation, and the `DocumentSpec.mode_for(region_id)` accessor land in B-01;
`human` (B-02), the `llm-seeded` lock (B-03), the mixed-authorship end-to-end
proof + renderer-backed `llm` rule (B-04), and pure-`llm` (no-renderer) prose
authoring (B-06) wire the behaviors above.

```yaml
documents:
  - id: eng-guide
    path: docs/eng-guide.md
    audience: eng-guide
    region_keys: [symbols, intro]
    region_modes:
      symbols: generated     # default; could be omitted
      intro: human           # a human owns this section; heal leaves it alone
```

### Per-region content hashes (`cdm.region_hashes`)

The `human`/`llm-seeded` behaviors are driven by a per-region content hash stored
in front matter under `cdm.region_hashes` (region id → `sha256[:16]` of the
region body, CRLF-normalized — the same algorithm as the HTML-twin source hash
§4). It rides alongside `cdm.fingerprint` and survives every heal (the heal copies
the whole `cdm:` mapping). The shared lock predicate is: a region is **locked**
when it carries a stored hash AND the current body's hash differs from it — i.e. a
human edited the body since the engine last stamped it. drift and heal both read
this one predicate, so they can never disagree.

```yaml
cdm:
  fingerprint: a1b2c3d4e5f6a7b8
  region_hashes:
    symbols: 0f1e2d3c4b5a6978   # stamped when the engine last authored this body
```

* `generated` / unlocked `llm-seeded`: the engine stamps the hash of the body it
  just wrote, so a later human edit diverges and locks the region.
* `human`: heal stamps the hash of the *human's current body* when it heals a code
  change, so the "code changed — review this section" advisory PERSISTS across the
  fingerprint heal until the human actually edits the body (then the hash diverges
  and the advisory clears). A human region with no stored hash is dormant (clean)
  until the first heal touches it.
* locked `llm-seeded`: keeps its existing stamp (re-stamping to the human body
  would falsely unlock it).

### `llm` rule (renderer-backed render vs pure-`llm` prose authoring — B-06)

A region declared `mode: llm` splits on whether the engine has a renderer for it:

* **with a renderer** (built-in `symbols` or a `region_templates` entry) the engine
  mechanically renders it and keeps it in sync on every code change — exactly like
  `generated` (the doc never silently goes stale);
* **with no renderer** the body is **backend-authored prose** (B-06). It is graded
  by whether the **code surface it documents moved** (the whole-doc fingerprint
  diverges), NOT against any mechanical render — its prose legitimately differs:
  * code moved → a healable `REGION` drift; the backend re-authors the prose from
    the current surface, and `monitor --apply` applies it (idempotent — same
    surface ⇒ identical authored body ⇒ a second `--apply` is a clean no-op);
  * code unchanged → no drift (the prose stands).

The default offline `MockBackend` authors a deterministic, audience-aware prose
stand-in (a stable sentence enumerating the public symbols the section covers), so
the suite stays offline (K4) and the heal is idempotent (K7/K10). A NON-`llm`
no-renderer region still surfaces as `UNHEALABLE` (genuinely no authoring path —
loud, K8). The critical idempotence point: a code change raises BOTH a whole-doc
HASH and the REGION drift; the HASH heal regenerates the rendered regions +
fingerprint but PRESERVES a no-renderer region's body byte-identical (it never
blanks the prose), and the REGION fix authors the new body.

### Inspecting region authority state (`cdmon lint --modes`)

`cdmon lint --modes` prints each managed region's declared `mode` plus its
renderer / lock / advisory state — one line per region:

```
region authority modes:
  eng-guide::symbols — generated [renderer]
  eng-guide::intro — human [no-renderer advisory]
```

This is a **state surface, not a gate**: the modes map is already validated at
config-load, so `--modes` only *reports* state and never changes `lint`'s
structural pass/fail exit code (run it alongside the structural lint).

## 8. Collection / index regions

A managed region can list **other documents** instead of code — a collection or
landing page. Declare a `region_templates` entry with `source: index`; the
region's body is then a generated table over every *other* document in the
config (the index document excludes itself), kept in sync like any code-backed
region (re-purpose, rename, add, or remove a sibling and the index drifts until
rebuilt). Set `kind: <audience>` to list only `user-guide` or `eng-guide` docs.

Separately, set `index: true` on the document spec to enable the structural
**completeness** lint: `cdmon lint` then emits `INDEX_INCOMPLETE` (§5) if the
landing page fails to link a document it indexes. The two flags are orthogonal —
`source: index` drives the *generated table*, `index: true` drives the
*link-completeness lint* — and a landing page typically sets both.

The completeness lint honors the index region's audience **`kind`**, so it stays
aligned with the table the index actually renders: an `eng-guide`-scoped index is
*not* flagged for omitting a `user-guide` document (e.g. a monitored `README.md`),
because that document is never listed there. With no `kind` (an all-audiences
index), every other document must be linked.

```yaml
region_templates:
  api-index:
    source: index
    kind: eng-guide            # restrict to one audience (and scope the lint to it)
    columns:
      - {header: "Document",       field: "title"}    # linked to the doc
      - {header: "What it covers", field: "summary"}

documents:
  - id: api-index
    path: docs/api/index.md
    audience: eng-guide
    index: true                 # landing page: INDEX_INCOMPLETE requires it to link every eng-guide sibling
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

## 9. Generation context — `context_refs`

A document entry MAY carry a `context_refs:` list alongside its `code_refs:`.
These are **sub-documents or sub-source-files the author should glance through or
refer to** when generating the document — generation context, not documented
surface. Each entry is a repo-relative `path` plus an optional `note`:

```yaml
documents:
  - id: getting-started
    path: docs/guide/getting-started.md
    audience: user-guide
    code_refs:
      - {path: src/core/model.py, symbols: [Task]}
    context_refs:                       # generation context — NOT coverage
      - {path: docs/api/core-api.md, note: "link to the full engine reference"}
      - {path: src/core/engine.py,  note: "scheduling semantics referenced here"}
```

`context_refs` are surfaced to the authoring prompt as reference material but are
**never counted in coverage, the `.rpt`, or drift** — they are not part of the
documented surface (that is `code_refs`). They can be added from the console's
interactive Mapping view (the single Astro frontend served at `/`; see the
project README). Paths are not resolved for existence at load, so a
`context_refs` entry may point at a not-yet-created doc.
