# code-doc-monitor — lessons learnt

Append one entry per slice: what was non-obvious, why, how to apply it later.

- [CDM-00] **Fixed module signatures up front (ARCHITECTURE.md) so slices
  compose.** The biggest risk in a sequential, dependency-heavy build is
  integration drift between slices. Pinning the public surface of every module
  before writing any of them lets each slice be validated in isolation against a
  stable contract. → Treat ARCHITECTURE.md as binding; change it deliberately,
  not incidentally.

- [CDM-01] **A Typer app with exactly one command collapses into a
  single-command CLI**, so `cdmon init ...` got parsed as `init` (the prog) plus
  an unexpected `init` argument and exited 2. Adding a group-level
  `@app.callback()` forces Typer to keep it a multi-command group even while only
  `init` exists — which is also what we want once later slices add
  surface/check/monitor/report/schema. Also: this pinned Typer build's
  `CliRunner` has no `isolated_filesystem`; use `monkeypatch.chdir(tmp_path)` for
  default-path CLI tests. → When a CLI is built incrementally, give it a callback
  from the first command so behaviour is stable across slices.

- [CDM-02] **The audience split is enforced entirely in the hash payload, not by
  re-extracting.** Both audiences share one extraction pass; the difference is
  (a) user-guide drops private symbols before building the surface and (b)
  `surface_hash` conditionally folds `docstring` into the payload only for
  eng-guide. This makes the key K3 behaviour falsifiable in a single test: edit
  only a docstring → eng hash moves, user hash is byte-identical. Two subtleties:
  the `audience` value must be *in* the payload or the two audiences could collide
  on identical public surfaces; and signature reconstruction has to be exhaustive
  (`ast.unparse` on annotations/defaults/returns, posonly `/`, bare `*` for
  keyword-only, `**kwargs`) because the signature string IS the user-guide
  fingerprint — a missing arg form would silently fail to detect real drift. Also
  mypy flags reusing a loop var name (`default`) across a positional loop (`expr`)
  and a `kw_defaults` loop (`expr | None`); rename to keep the narrowed types
  clean. → When a behaviour is "X is ignored for audience A but tracked for B",
  encode it as a payload toggle over one shared extraction, and pin it with a
  same-input-one-edit hash-equality test.

- [CDM-03] **`set_region`/`regions` split on `"\n"`, so a region body never
  carries a trailing newline.** A managed region's stored body is the lines
  *strictly between* the markers joined by `"\n"`; round-tripping `"foo\n"`
  through `set_region` yields the two lines `["foo", ""]` and `regions()` reads
  it back as `"foo\n"`. Renderers (`symbol_table`) and `expected_region` must
  therefore emit a body with NO trailing newline, or REGION drift would be
  perpetual (the freshly-rendered body would never equal the stored body). The
  heal idempotency test pins this: regenerate → detect() clean → regenerate
  returns False. **Forward-dependency tip:** `heal.apply_fix` needs
  `schema.ProposedFix`, built a slice later — typing the param as a local
  `@runtime_checkable Protocol` (`ProposedFixLike` with `region_id`/
  `new_region_body`/`new_doc_text`) keeps mypy honest (real attribute checks, not
  `Any`) without the circular/forward import. → When a slice consumes a type a
  later slice owns, depend on its *shape* via a Protocol, not its module.

- [CDM-04] **"No network in tests" (K4) is a coverage-shaped constraint, so
  design the network call to be the *only* uncovered line — never an untested
  branch.** `HttpSink` takes an injected `client` (`post(url, *, data, headers)`)
  so every behaviour that matters (url, exact JSON body, bearer header derived
  from `os.environ[auth_env]`, header *absence* when the env is unset) is asserted
  against a fake with zero network. The genuinely-unrunnable bit — the stdlib
  `urllib.request.urlopen` POST — is isolated inside a tiny `_UrllibClient.post`
  so it's the single uncovered region (66-70), self-documenting *why* it's
  uncovered. The lazy-build branch (`client is None → _UrllibClient()`) is still
  covered by monkeypatching `_UrllibClient.post` to a no-op, so "build a real
  client" runs without "use a real socket". Two more subtleties: read the bearer
  token at *emit* time, not construction, so a rotated token is picked up (and the
  env-unset path is testable); and reuse the JSONL line shape across `reviewlog`
  and `FileSink` so the file sink's output round-trips through `read_all` — one
  parser, two writers. → When a constraint forbids exercising a code path, push
  that path into the smallest possible leaf method and inject everything around
  it, so the forbidden line is the *only* gap and the gap is legible.

- [CDM-05] **An f-string with a backslash in the `{...}` expression is a syntax
  error before Python 3.12, and ruff lints to `py310` — so a `f"{('- diff:\n' +
  ...)}"` broke `ruff format`/parse even though the interpreter was 3.11.** Hoist
  the value to a plain statement (`diff_line = f"...\n..."`) and interpolate the
  *name*. → On a 3.10-targeted project, keep backslash escapes out of f-string
  expression parts; build the string first, interpolate the variable. Second
  lesson: **the LLM-reply parser's robustness is itself a correctness surface, so
  pin its adversarial inputs.** `parse_backend_json` scans for the first balanced
  `{...}` (tracking string state + escapes) rather than regex/`json.loads` on the
  whole reply, so it survives prose wrappers, ```json fences, and `}`/`"` *inside*
  string values — but it also means a stray `{...}` decoy *before* the real JSON
  wins, which is the correct, documented trade-off (LLMs are told to reply
  JSON-only). Tests must cover bare/fenced/prose-wrapped/garbage/invalid-verdict/
  unbalanced/malformed-fix, and the "brace inside a string" case, or the brace
  matcher's escape handling is silently untested. Third: **mirror CDM-04's
  inject-the-leaf discipline for *both* the subprocess and the HTTP call.** The
  process `runner` and the API `client` are constructor-injected callables; the
  only `# pragma: no cover` lines are the real `subprocess.run` and real
  `urllib.urlopen` leaves, plus a defensive `not isinstance(data, dict)` guard
  that the balanced-brace extractor makes unreachable. Cover the lazy-default-
  build branch by monkeypatching the leaf (`subprocess.run` / `_anthropic_
  messages_call`) to a stub, and cover the error wrapping by having the injected
  fake raise — so "build the real client/runner" and "an error is wrapped loudly"
  both run with zero process/network. → Inject every side-effecting boundary as a
  callable, push the unrunnable syscall into a one-line leaf, and test the
  build-the-default branch via a stubbed leaf so 100% coverage holds without K4
  violations.

- [CDM-06] **The MockBackend FIXes only `REGION` drift, so a "fully closes after
  --apply" test must avoid co-occurring `HASH` drift.** A stale fingerprint *and*
  a stale region body produce two drifts; the mock FIXes the REGION (via
  `expected_region`) but ESCALATEs the HASH (it has no region to regenerate), and
  `apply_fix` on a region body deliberately does NOT refresh the front-matter
  fingerprint (K7: it touches only the named region). So a fixture that wants
  `remaining == ()` after `run(apply=True)` must write a *correct* fingerprint and
  only a stale region body — one REGION drift the mock can close. (If you want the
  hash refreshed too, that's `heal.regenerate_regions`, not `apply_fix` — a
  different, whole-surface path the mock doesn't drive.) → When asserting a
  remediation loop goes clean, match the fixture's drift kinds to what the chosen
  backend can actually resolve, and remember region-fix ≠ fingerprint-refresh.
  Second: **Typer (this pinned build) handles `bool | None` with an
  `--apply/--no-apply` flag and `Path | None` with `--out` natively**, so the
  CLI's tri-state apply (None→config default) and optional output file need no
  custom parsing — the `None` default flows straight into `Monitor.run(apply=...)`.
  Third: **typer doesn't catch our exceptions, so each command wraps its load +
  work in one `try/except CodeDocMonitorError` that echoes `error: <msg>` to
  stderr and raises `typer.Exit(1)` (K8)** — the clean-error contract is per-command
  boilerplate, but it keeps the "no traceback" guarantee local and testable
  (assert `"Traceback" not in output`). → Centralize nothing clever for CLI error
  handling; a small per-command try/except is the most legible way to honor K8.

- [CDM-07] **Detection and remediation must agree on what "fully healed" means.**
  A realistic code change raises TWO drifts on a doc — a REGION drift (stale
  table) and a HASH drift (stale fingerprint). A backend that only fixes regions
  leaves the fingerprint HASH behind, so `monitor --apply` never converges. Fix:
  the backend's whole-doc FIX (`heal.render_corrected`) regenerates regions AND
  refreshes the fingerprint in one shot, reusing the exact logic `regenerate_regions`
  uses — so a backend FIX and an engine heal can never disagree. → When a fixer and
  a checker are separate, route both through one shared "what the doc should be"
  function; otherwise they drift apart and the loop won't close.
- [CDM-07] **The strongest "invalidate a comment change" is to never flag it.**
  The spec wanted comment/private/local changes to be non-events for a user guide.
  Implementing that at the *extraction* level (the user-guide surface hash excludes
  docstrings/private symbols) means such a change produces ZERO user-guide drift —
  stronger and cheaper than detecting drift and asking the LLM to INVALIDATE it.
  The INVALIDATE *verdict* remains as a secondary net (for changes that DO move the
  surface but a human/LLM judges irrelevant). → Push audience policy as far down
  the pipeline (into extraction) as it will go; reserve the LLM for genuine judgment.
- [CDM-07] **A symbol's "signature" is doc content — keep it doc-sized.** Rendering
  a module-level constant's full value put a 2 KB template string into one table
  cell. Eliding long/multi-line values to `...` (short scalars kept) makes the
  generated table readable without losing the public surface. `ast.unparse`
  normalizes whitespace, so a short multi-line literal collapses to a short line and
  is kept — only genuinely long values elide.
- [CDM-07] **Dogfood on a copy for the self-heal proof, in place for the in-sync
  assertion.** Asserting the checked-in docs match the checked-in code catches real
  rot; proving the heal LOOP works by mutating source must happen on a temp copy so
  the test never dirties the repo.

## CDM-08 — document layout standard + lint

- **A standard that isn't machine-checked drifts like any other doc.** We had
  two implicit doc dialects (cdmon's `CDM:BEGIN` + front-matter fingerprint vs
  helium's `HELIUM:AUTOGEN … START/END` + html-embedded hash). Writing the
  Layout Standard as prose alone would have just added a third thing to keep in
  sync. Encoding it as `cdmon lint` (a checkable gate) is what makes it real.
- **Put static metadata where heal already preserves it.** `schema_version` and
  `audience` are static, so authoring them once and relying on `set_fingerprint`
  (which copies the whole `cdm:` mapping and only overwrites `fingerprint`) to
  carry them forward meant **zero changes to heal/drift** and zero blast radius
  on their tests. The alternative — stamping them in `_corrected` — would have
  broken every heal idempotence test. Let the existing invariant do the work.
- **Lint (structure) and check (content) are orthogonal gates.** Keeping them
  separate commands (rather than folding lint into check) avoided perturbing the
  existing check/monitor semantics and tests, and matches how CI wants them:
  two independent red/green signals.
- **The scaffolder is the standard's executable spec.** `scaffold_doc` must emit
  a doc that passes its own `lint_doc` — a single round-trip test
  (`test_scaffold_doc_passes_lint_and_is_in_sync`) pins skeleton, markers, and
  front-matter schema all at once, so the standard and the generator can't drift
  apart.

## CDM-09 — source:index layer (built on the records/templates architecture)

- **Adopt the in-flight design instead of forking it.** An earlier pass added a
  parallel `DocumentSpec.index_of` + `collection.py`; once the other session
  finished `region_templates` with a `source: "index"` enum value and a
  `render_template` comment explicitly deferring index to "the index-aware
  layer", the right move was to delete the parallel mechanism and implement
  exactly that hook. One index concept, not two.
- **An index can't be rendered from a single surface, so render it where the
  whole config is in hand and pass the body in.** `expected_region`/the backend
  only see one doc's surface; index needs all docs. Rather than thread all-docs
  context through `heal`/`render_corrected`, `drift.detect` and `monitor.run`
  (which both already hold `config`+`root`) render the index and the backend
  receives it via a new `FixRequest.index_body`. Minimal, and the self-heal
  property holds.
- **An index doc has no code surface — keep its fingerprint stable.** With
  `code_refs=()` the surface hash never moves, so HASH never fires and the
  meaningful drift signal is the region body. That sidesteps the whole-doc
  `render_corrected` path (which would mis-handle an index region) entirely.
- **A shared workspace under concurrent edit needs re-validation, not memory.**
  Files (config.py, drift.py) changed under me repeatedly; re-reading each seam
  immediately before editing — and re-healing the dogfood after every code
  change — was the only safe way to land changes on top of a moving codebase.
