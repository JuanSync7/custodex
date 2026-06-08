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

## CDM-11 — LangGraph remediation agent + separated .md artifacts

- **A new orchestration style is additive when it honors the existing seam.**
  The agent did not replace `build_prompt`/the single-shot backends; it became a
  fourth `backend.kind` whose `AgentBackend.propose` satisfies the *same*
  `Backend` Protocol. So `Monitor`, the review-log, the sinks, and every system
  test were untouched (K9) — the LangGraph graph slots in exactly where a
  one-shot call did. → When adding a richer engine, conform to the narrowest
  existing interface (here, one `propose` method) before reaching for a wider one.
- **A heavy optional dep stays optional via a lazy import + an extra.** K0 pins
  the core to `pydantic`/`typer`/`pyyaml`; `langgraph` would break that as a hard
  dependency. Putting it behind a `[agent]` extra AND importing the subpackage
  lazily inside `make_backend`'s `kind == "agent"` branch (with a typed
  BackendError if the extra is absent) means the default `mock` path imports
  nothing new, while the agent path gets a real langgraph graph. The constraint
  text (K0) was updated deliberately, not silently. → Reconcile an explicit
  feature request against a dependency constraint by making the feature opt-in at
  *both* the packaging and the import boundary, and amend the constraint on the record.
- **"Load the .md only when needed" is a graph decision, not a loader trick.**
  The `select` node returns the artifact list per drift (TOOL only when the drift
  is healable, PERSONA only when enabled+present); `compose` then asks the
  `PromptLibrary` for exactly those, which reads+caches each file on first use.
  Separating *which artifacts* (graph policy) from *how to load one* (library
  mechanics) made both trivially testable: `select_artifacts` is a pure function,
  and the lazy/cached/loud-missing behaviour is three small library tests. → Push
  conditional-resource decisions up into the workflow and keep the loader dumb.
- **The inject-the-leaf discipline (CDM-04/05) extends straight to a graph.** The
  graph is deterministic; only the `invoke` node calls the `Driver`, and the
  driver is the single injected boundary. Reusing `backends._default_process_runner`
  / `_anthropic_messages_call` as the claude-code/api leaves (and one new
  `_openai_chat_call` for `local`) kept the only `# pragma: no cover` lines the
  real syscalls, so the whole workflow — retry loop, re-ask nudge, fail-raise —
  hit 100% offline. The mypy gotcha: a value narrowed by `if not x: raise` is
  re-widened to `str | None` when captured by a nested closure, so bind it to a
  freshly-annotated local (`api_key: str = raw_key`) before the closure, and use
  distinct names across driver branches or the first `: str` annotation leaks. →
  A deterministic graph over an injected leaf is testable to 100% with no network;
  watch closure-capture re-widening when a node closes over a narrowed local.

## A-01 — inventory.py (glob `**` semantics, determinism)

- **`fnmatch` and 3.11 `PurePath.match` cannot do real recursive `**`.** The spec's
  `DEFAULT_EXCLUDE = ("**/.*/**", "**/__pycache__/**", "**/.venv/**")` only works if
  `**/` matches *zero or more* leading path segments — so a TOP-LEVEL `.venv/lib/y.py`
  or `.git/.../x.py` is excluded. Plain `fnmatch("**/.venv/**")` translates `*`→`.*`
  and the literal `/` after `**` forces at least one leading segment, so a root-level
  `.venv` is NOT matched and leaks through. `PurePosixPath.match` on Python 3.11 also
  treats `**` as a single non-recursive wildcard (recursive `**` only landed in 3.13).
  FIX (stdlib-only, K0): a small in-house `_translate(glob) -> re.Pattern` where
  `**/`→`(?:.*/)?` (zero-or-more segments, the key trick), `**`→`.*`, `*`→`[^/]*`,
  `?`→`[^/]`, everything else `re.escape`d, anchored with `\Z`. Probe matches with a
  throwaway `python -c` BEFORE writing the impl — it instantly revealed the leak.
- **Dedup falls out of the loop shape, don't add a `seen` set.** `os.walk` yields each
  file exactly once; append ONE `CodeFile` per file (checking `any(include)` /
  `any(exclude)`), never per-matching-glob. Overlapping includes (`("**/*.py","**/a.py")`)
  are then inherently deduped with no `seen` set — and an unreachable `seen.add/continue`
  is just dead lines that block 100% coverage. I removed mine to hit 100%.
- **Losslessness = keep unknown extensions.** A file that matches an include but whose
  extension isn't in the language table is kept with `language="unknown"`, never dropped.
  EPIC A is "lossless coverage", so dropping a matched file would silently under-count.
- **B017 in tests:** `pytest.raises(Exception)` for frozen/extra-forbid pydantic checks
  trips ruff B017 — assert the specific `pydantic.ValidationError` instead.
- **Dogfood drift is from errors.py, not the new module.** Per the dogfood-reheal memory:
  inventory.py itself is unwired so it doesn't drift any doc, but adding `InventoryError`
  to the TRACKED errors.py drifts docs/api/foundation.md (HASH + symbols REGION).
  `cdmon monitor --apply` heals it; `check`+`lint` then exit 0.

## A-02 — symbol-level inventory (discover_symbols)

- **Reuse `extract.extract_file`, do NOT re-implement AST.** A-02's whole job is to
  cross `Inventory.files` with `extract.extract_file` — the symbol order and the
  `is_public` / qualified-method-name (`Widget.method`, kind `method`) semantics come
  free from extract.py and stay consistent with `build_document_surface`. The slice is
  ~30 lines of glue, no `ast` import. Order is doubly-deterministic (K10): outer =
  `Inventory.files` order (already sorted by A-01), inner = `extract_file`'s body order.
- **Drive `language`, not the suffix, for the python branch.** A-01 already classified
  every file (`.py`/`.pyi` → "python", else "unknown"); `discover_symbols` keys off
  `code_file.language == "python"` so the python-vs-non-python decision lives in ONE
  place (the A-01 ext table). A `.txt` matched via a custom include arrives as
  `language="unknown"` and gets `symbols=()` — lossless, never dropped.
- **Unparseable-file policy = LOUD by design (K8), and it's a real future blocker.**
  A single syntax-error `.py` in the tree makes the whole `discover_symbols` scan raise
  `ExtractionError` (it propagates straight from `extract_file`). That's correct for the
  dogfood/known-good repo this slice targets, but for scanning ARBITRARY external repos
  (EPIC G) one bad file shouldn't abort the whole inventory. Captured as a real adoption
  blocker in `.project/problems/A-02.md` with a proposed `--skip-unparseable` resilient
  mode (collect per-file errors instead of raising). Deferred deliberately, not forgotten.
- **No dogfood reheal this time.** Unlike A-01 (which touched the TRACKED `errors.py`),
  A-02 only edits `inventory.py` — which is NOT referenced by any `docs/api/*` symbol
  table in `cdmon.yaml` — and adds nothing to `errors.py`. So `cdmon check`/`lint` stay
  green with zero reheal. The dogfood-reheal memory only bites when you edit a module
  that appears in a tracked doc's code_refs; verify before assuming you must reheal.
- **`extract.Symbol` is already frozen + `extra="forbid"`** and re-exported from
  `extract.__all__`, so importing it into `inventory.py` and nesting it inside the
  frozen `FileSymbols` model just works (pydantic composes the immutables). `FileSymbols`
  equality is structural, so `discover_symbols(inv) == discover_symbols(inv)` proves
  determinism directly.

## A-03 — coverage.py ownership resolver

- **Ownership ignores audience — a DELIBERATE divergence from `build_document_surface`.**
  `build_document_surface` drops private symbols for a `user-guide` (K3: they are
  non-events for that audience's hash/surface). The coverage resolver does the OPPOSITE:
  a `code_ref` "covers" the symbol it points at regardless of audience, because the
  question here is "is this code REFERENCED by a doc", not "is it in the audience-filtered
  surface". So a user-guide ref over a file owns that file's `_private` symbols too. The
  audience-vs-gap separation is enforced downstream instead: private symbols are tracked
  losslessly in `CoverageReport.symbols` but are excluded from the gap basket
  (`undocumented_symbols`) and the `percent_public_symbols` universe — they are not
  documentation targets. Keeping these two notions separate (ownership = referenced;
  gap-% = public) is the crux of the slice; a test (`test_ownership_ignores_audience`)
  pins it so a future refactor can't quietly start audience-filtering ownership.

- **Reusing `extract._select` is the whole trick — do NOT re-implement selection.** Its
  current signature is `_select(symbols: list[Symbol], ref_symbols, ref_lines, ref_names)
  -> list[Symbol]` (positional, private but same-package import is fine). Feed it the
  file's FULL symbol list (from the inventory's `FileSymbols.symbols`) plus the ref's
  three selector tuples, then test membership of the returned symbols by `(name, lineno)`.
  This gives whole-file (empty selectors → all), `symbols` (a CLASS name pulls in its
  `Class.method` children — proven by `test_symbols_selector_pulls_in_methods`),
  `lines`-overlap, and `names` semantics for free and *consistent with extraction*. Note
  `_select` does NOT apply `arg_signature` (that lives in `_symbols_for_ref`, narrowing a
  surface); coverage deliberately ignores `arg_signature` too — a ref still "covers" the
  file's symbols it names regardless of arg filtering. `(name, lineno)` is the right key:
  unique per symbol within a file, and it's what `build_document_surface` dedupes on.

- **`percent_*` must not divide by zero — and the two metrics have DIFFERENT empty cases.**
  `percent_files` → 100.0 when there are no files (empty repo). `percent_public_symbols` →
  100.0 when there are no PUBLIC symbols, which is a real non-empty case: a repo whose only
  symbols are private (`_x`) has an undocumented FILE (so `percent_files` can be 0.0) yet a
  vacuously-100% public-symbol metric. Both branches are tested
  (`test_empty_repo_is_100_percent`, `test_repo_with_only_private_symbols_is_100_percent`)
  so the zero-division guard is real coverage, not dead code.

- **No dogfood reheal (again).** `coverage.py` is unwired (not imported by cli/monitor) and
  not referenced by any `docs/api/*` code_ref in `cdmon.yaml`, so `cdmon check` stays green
  with zero reheal — consistent with the A-02 lesson: reheal only bites when you edit a
  module that appears in a tracked doc's code_refs. Confirmed `cdmon check` exits 0.

## A-04 — config `coverage:` section + waivers

- **The waiver percent-universe decision (numerator AND denominator).** A waiver is NOT a
  free 100% — it must remove the item from the *denominator* too, else waiving a gap would
  *lower* the percentage (gap drops from the numerator but stays in the total). So
  `percent_* = documented / (total − waived)`. A repo where every public symbol is either
  documented or waived reports exactly 100%. Both `percent_files` and `percent_public_symbols`
  subtract waived from their universe; the empty-universe→100.0 guard now fires when
  total==waived too (a fully-waived repo), so it's still live coverage, not dead code.

- **Only UNOWNED, PUBLIC items are waivable — order matters in the resolver.** `waived_reason`
  is computed only when `(not owners)` for a file and `(is_public and not owners)` for a
  symbol. This makes a waiver on an already-documented item a pure no-op (documented wins,
  basket unchanged) and a waiver on a private symbol inert (private symbols are never doc
  targets, so they can't enter the public waived basket). Computing the waiver unconditionally
  and *then* filtering would have leaked `waived_reason` onto documented/private rows and
  broken the additive equality with A-03.

- **Inert-waiver choice: SILENT, not loud.** A waiver matching no file/symbol does NOT raise.
  Rationale: in A-05 the scan scope (`coverage.include/exclude`) is applied to `discover_files`
  *before* the resolver sees the inventory, so a waiver whose path was legitimately excluded
  from the scan will match nothing — that's normal config, not malformed input. The single
  loud failure (K8) is a waiver missing its `reason`, caught at config-load by the required
  pydantic field. Documented in ARCHITECTURE.md and tested
  (`test_non_matching_waiver_is_silently_inert`).

- **config ↔ inventory import cycle is real — inline the defaults, lock-step with a test.**
  The slice spec suggested `from . import inventory` into config, but `inventory` → `extract`
  → `config` is an existing import chain, so importing inventory from config deadlocks at
  module import (confirmed: an early `from . import inventory` was reverted). The
  `CoverageConfig.include/exclude` defaults are therefore inlined literals
  (`_DEFAULT_INCLUDE/_EXCLUDE`) matching `inventory.DEFAULT_INCLUDE/EXCLUDE`, guarded by
  `test_coverage_defaults_match_inventory` so the two copies never silently diverge. `coverage.py`
  CAN and DOES import `inventory._translate` (coverage is downstream of both).

- **Dogfood reheal DID bite this slice (unlike A-02/A-03).** `config.py` is a tracked module
  in `cdmon.yaml`'s `foundation` doc, so adding the two models drifted its symbol table +
  fingerprint → `cdmon monitor --apply` healed foundation (HASH then REGION), after which
  `cdmon check` and `cdmon lint` both exit 0. Rule of thumb confirmed: reheal bites iff the
  edited module appears in a tracked doc's `code_refs`.

- **Pydantic `@property` baskets are NOT in `model_dump()` — inject them for `--json`.**
  `CoverageReport`'s percentages and the documented/undocumented/waived baskets are
  computed `@property`s, so `report.model_dump(mode="json")` carries only the stored
  `files`/`symbols` tuples — `percent_public_symbols`, `undocumented_symbols`, etc. are
  ABSENT. `cdmon coverage --json` therefore starts from `model_dump(mode="json")`
  (lossless, JSON-safe: tuples → lists) and then adds each derived basket/percentage
  explicitly (`_coverage_payload` in cli.py). A consumer (and the gate-metric test) can
  then read `percent_public_symbols` straight from the JSON without recomputing it. If
  A-08 dumps `CoverageReport` anywhere, remember the same: dump the model, then attach the
  properties you need.

- **Typer `float | None` option for an optional numeric gate works out of the box.**
  `fail_under: float | None = typer.Option(None, "--fail-under", ...)` needs no custom
  parsing — Typer accepts `--fail-under 90` (→ `90.0`) and treats omission as `None`, which
  is exactly the "absent ⇒ always exit 0, present ⇒ gate" semantics. The command ends with
  an explicit `raise typer.Exit(code=0)` on the success path so the gate branch and the
  pass branch are symmetric (and both testable).

- **`cdmon coverage` self-scan is honestly low (files 22%, public symbols 18%) — that's the point.**
  Running the new command on this repo's own `cdmon.yaml` reports ~18% public-symbol
  coverage because the engine's own inventory/coverage/cli/agent modules aren't in any
  tracked doc yet. So the A-06 CI step is INFORMATIONAL only (no `--fail-under`): a hard
  gate would fail every pipeline today. EPIC H (esp. H-02) is what raises self-coverage so
  the gate can be switched on later — the comment in `.gitlab-ci.yml` marks the exact spot.

- **A-07 new-doc-id naming scheme: full-path-token `pkg/sub/mod.py → pkg-sub-mod`.**
  Of the two scheme options the spec floated (`mod` vs `pkg-sub-mod`), the bare-stem
  `mod` collides whenever two packages both have a `mod.py` (e.g. `a/util.py` and
  `b/util.py` would both propose `util`), which would silently group unrelated gaps
  under one fabricated doc. The full-path token (drop `.py`/`.pyi`, `/`→`-`) is
  collision-free by construction and id/filesystem-safe. Implemented as the pure
  `_proposed_doc_id`; documented in ARCHITECTURE's coverage.py section. The `is_new`
  vs `is_sibling` split is itself deterministic: "sibling" wins whenever ANY doc owns
  ANY symbol in the file (lowest doc id breaks ties), so a partly-documented file
  never spawns a competing new-doc proposal.

- **Decision 1 (heuristic, not Backend) consequence: zero blast radius, but no
  cross-file intelligence.** Keeping `suggest_owners` a pure function off
  `CoverageReport` meant NO change to the four backends, NO `langgraph`/network, and
  trivially-deterministic tests (no mock). The trade-off it bakes in: suggestions see
  only ownership facts, so they can't propose grouping by *topic* (e.g. "these three
  unowned files are all about parsing → one doc") — that's the explicit later
  "LLM-enhanced suggester" extension. On the dogfood repo this shows up as 524
  suggestions that are ALL `is_new_doc=True` (the tracked docs reference whole modules
  but own no individual symbols in the *undocumented* files), which is correct but
  verbose — a topic-clustering pass is what would compress it.

- **Decision 2 (dedicated manifest, not in `cdmon.yaml`) consequence: lossless +
  idempotent, but a second source of truth.** Writing `.cdmon/coverage.json` (already
  gitignored alongside `review-log.jsonl`) avoided the ruamel dependency (K0) and the
  `extra="forbid"` round-trip problem an injected yaml key would hit. The manifest is a
  pure DERIVED artifact — like the html twins — so it must never be hand-edited; the K7
  read-before-write guard makes a re-run a no-op. Consumers reading the manifest must
  treat `cdmon.yaml` as authoritative for config and the manifest as a regenerable cache.

- **typer 0.26 has no clean optional-value option; use bool-flag + optional positional.**
  `--write [PATH]` (bare → default, with-value → custom) cannot be a single typer
  Option: `flag_value` alone makes `--write` *require* an argument, and the click
  `is_flag=False, flag_value=...` idiom isn't surfaced by typer's wrapper (and `click`
  isn't importable as a top-level module under the K0 dep set). The working pattern is a
  bool `--write` flag plus an optional positional `[PATH]` Argument on the same command
  (the `coverage` command had no other positional, so it's unambiguous): `--write` →
  default, `--write out.json` → custom, a bare positional without `--write` is a
  read-only no-op. Verified the parse with a throwaway probe before wiring it.

- **EPIC A is complete (A-01…A-08).** The coverage stack now goes file/symbol discovery
  → ownership cross → waivers → CLI report/gate → gap→owner suggestions → idempotent
  manifest, all pure/offline/deterministic. The self-scan numbers stay honestly low
  (~18% public symbols) until EPIC H documents the engine's own modules; the A-06 CI
  step remains informational (no `--fail-under`) until then.

- **B-01: cross-field validation on a frozen pydantic model uses `@model_validator(mode="after")`.**
  To enforce "every `region_modes` key must be in `region_keys`" (a relationship
  between two fields), a `@field_validator` is insufficient (it sees one field). The
  `mode="after"` model validator runs once all fields are parsed, returns `self`, and
  raises `ValueError` on violation — pydantic re-wraps that as a `ValidationError`,
  which `load_config` already catches and re-raises as `ConfigError` (K8). No new error
  plumbing needed; the existing wrap carries it. Works fine on a frozen model.

- **B-01: a `str`-valued Enum in a `dict[str, RegionMode]` round-trips through YAML/JSON
  for free.** Because `RegionMode(str, Enum)` members ARE strings, pydantic accepts the
  raw `"human"` from YAML/JSON and coerces to the enum, and `model_dump(mode="json")`
  emits the bare value — so `region_modes: {intro: human}` survives a load→dump→load
  cycle with no custom serializer. Mirror `Audience` exactly (same base, same hyphenated
  values like `llm-seeded`). An unknown string (`"telepathy"`) fails enum coercion →
  ConfigError, giving the loud-on-bad-mode behavior for free.

## B-02 — human regions: reported, never auto-edited

- **A human-owned region's staleness signal is the fingerprint (code moved), NOT
  body-vs-render.** A human writes prose that *by definition* never equals the
  generated render, so "body != expected" would flag a human region forever. The
  correct rule: flag a human region (`REGION, healable=False`) only when the doc's
  stored fingerprint ≠ current surface hash — i.e. the code it describes changed.
  When in sync, the human body is accepted as-is. Two of the (interrupted)
  subagent's red tests encoded *contradictory* models on exactly this point;
  reconciling them forced the rule into the open.
- **Enforce "never author a human region" at the WRITE boundary, not the backend.**
  `apply_fix(..., *, preserve=frozenset())` re-injects the document's current body
  for every preserved region before writing a whole-doc fix — so a backend (even a
  real LLM) returning whole-doc text that overwrites a human region cannot clobber
  it. The guarantee holds regardless of backend, and `FixRequest`/the backends stay
  untouched. (Same spirit as CDM-07: put the invariant where the bytes are written.)
- **KNOWN LIMITATION → B-03:** healing the HASH (refreshing the fingerprint) clears
  the human-region review signal even if the prose was never updated. The proper
  fix is a *per-region* content-hash in front matter (the llm-seeded lock, B-03),
  so the advisory persists until the human actually edits. **(FIXED in B-03.)**

## B-03 — llm-seeded lock (per-region content hash) + B-02 advisory persistence

- **One shared lock predicate, two opposite readings — keep the predicate, not the
  reading, shared.** `manifest.region_is_locked(doc, id, body)` (stored hash present
  AND `region_body_hash(body) != stored`) is the SINGLE truth drift + heal both call
  (CDM-07). But the two MODES read its hash comparison in opposite directions:
  `llm-seeded` treats *diverged* as "human took it over → lock", while the `human`
  advisory treats *still-matches-the-stamp* as "human hasn't re-reviewed → keep
  firing". So the SHARED thing is the hash + the comparison helper, not a single
  boolean meaning. Trying to force one `is_locked` boolean to serve both would have
  inverted one of them. → Share the mechanism (hash + compare), let each mode
  interpret; don't over-unify the semantics.

- **The B-02 advisory persists by stamping the human BODY, not by withholding the
  fingerprint.** The naïve fix for "advisory clears after a fingerprint heal" is to
  leave the HASH drift pending — but the B-02 system test explicitly asserts the
  fingerprint IS refreshed on `--apply`. So persistence had to come from the per-region
  hash: heal stamps `region_hashes[id] = hash(human body)` when it preserves a human
  region; drift then fires the advisory while the current body still equals that stamp
  (human hasn't acknowledged) and clears it the moment the body changes — entirely
  independent of the fingerprint. Crucially this is **additive**: with NO stored region
  hash (every pre-B-03 doc) the human branch falls back to the old fingerprint signal,
  so all B-02 tests pass byte-for-byte unchanged.

- **Stamp the AUTHORED body, never re-stamp a locked one.** When heal authors a region
  (generated or unlocked llm-seeded) it stamps the hash of the body it just WROTE — so
  the next human edit diverges and locks it. But a region already locked (human-edited
  llm-seeded) must KEEP its old stamp: re-stamping it to the current (human) body would
  make `region_body_hash(body) == stored` again and silently UNLOCK it. The `locked llm-
  seeded → skip stamping` guard in both `_corrected` and `_stamp_region_hashes` is the
  crux; a test asserts the stamp is unchanged after a locked re-heal.

- **`region_hashes` rides for free on the existing `set_fingerprint` copy.** Like CDM-08's
  static front-matter keys, putting the per-region hashes under `cdm.region_hashes` means
  `set_fingerprint` (which copies the whole `cdm` map and only overwrites `fingerprint`)
  carries them forward across every heal with zero changes to the fingerprint path. The
  mirror of `layout.md_source_hash` (CRLF-normalize → sha256[:16]) makes the stamp portable
  and is pinned by a `region_body_hash == md_source_hash` equality test.

- **Two write boundaries to thread, both reached from `monitor`.** The lock+stamp had to
  work in (a) `regenerate_regions`/`render_corrected` (baseline + the MockBackend whole-doc
  HASH fix, via shared `_corrected`) AND (b) `apply_fix` (the real `monitor --apply` write).
  `apply_fix` lacks the surface, so it can't author — but it CAN derive `locked_region_ids`
  from the doc's current bodies (fold into `preserve`) and re-stamp authored bodies via
  `_stamp_region_hashes` after the splice. `monitor.run` passes the full `region_modes` map
  so both the lock and the stamp happen at the genuine write boundary, mirroring B-02's
  "guarantee lives where the bytes are written" discipline.

- **Dogfood reheal bit (manifest/heal/drift are all tracked).** Editing the three modules
  drifted `docs/api/{pipeline,remediation}` (HASH+REGION); `cdmon monitor --apply` healed
  them, `check`+`lint` exit 0, and the full suite is green POST-reheal (the dogfood in-sync
  tests must pass after, not just before, the heal).
- **Process note:** finished by the orchestrator after the slice subagent hit the
  session token limit mid-TDD. The red tests + `.project/problems/B-02-HANDOFF.md`
  made the resume point unambiguous. → Having a subagent write failing tests first
  is itself a resumability mechanism.

## B-04/05 — mixed-authorship e2e + interim `llm` rule + lint-as-state-surface

- **The SAFE interim `llm` rule needed ZERO engine code — `llm` already falls
  through to the `generated` path.** The slice asked to decide pure-`llm`'s interim
  behavior. drift/heal branch only on `HUMAN` and `LLM_SEEDED`; a region whose mode
  is `LLM` is neither, so it is already treated exactly like `generated` (rendered if
  a renderer exists, UNHEALABLE/ESCALATE if not). That is the safe choice — a pure-
  `llm` region has no human prose to clobber yet, and a renderer-backed one never goes
  silently stale — so the work was to DECIDE it, ASSERT it
  (`test_mixed_authorship_four_regions_e2e` checks the `llm` region regenerates like
  `gen`), and DOCUMENT it additively (`config.RegionMode` docstring + LAYOUT_STANDARD
  §7), with a clear note that B-06 replaces it with real backend prose authoring. →
  When a mode's interim behavior is "act like an existing mode," prefer the
  no-new-branch encoding and pin it with a test + a doc note, not a special case.

- **A `human` region is dormant (clean) UNTIL the engine stamps its body — so build
  the mixed baseline by preserving human WITHOUT stamping it.** B-03 made the human
  advisory PERSIST by stamping `cdm.region_hashes[human]` and firing while the body
  still matches the stamp. The corollary (found the hard way: my first baseline
  `check().ok` failed) is that a *freshly stamped* human region reports its advisory
  forever — it is never "clean". The realistic lifecycle is: baseline = human
  UNSTAMPED → clean; a code change + `monitor --apply` heals the fingerprint AND
  stamps the human body → the advisory then persists until the human edits. To get a
  clean four-mode baseline I healed with `preserve={"human"}` + a `modes` map that
  EXCLUDES `human` (so `seeded`/`llm`/`gen` get their lock/stamp but the human stays
  unstamped). → A stamped human region is a perpetual advisory by design; only stamp
  it when a real heal touches the doc, never at baseline setup.

- **A `name`-only `symbols` template does NOT drift on a signature change — add the
  `signature` column.** The mixed-authorship doc rendered each region via a
  `region_templates` `symbols`-source table. With only a `name` column, changing
  `compute(a,b)` → `compute(a,b,c=0)` left every row identical (the symbol name is
  unchanged), so only HASH drift fired and the per-region REGION assertions got a
  `KeyError`. Adding a `signature` column made the rendered body move with the code,
  so the `gen`/`llm` REGION drifts appear. → When a fixture must produce REGION drift,
  render a column that actually changes with the edit you make.

- **Lint-as-state-surface: report, never re-validate, never gate.** B-05 surfaces each
  region's mode + lock/advisory via pure `region_states`/`config_region_states` reading
  `spec.mode_for` + the public manifest hash helpers — NOT a new `LayoutCode`/issue. The
  modes map is already validated at config-load (B-01), so re-validating in lint would
  duplicate the gate; instead `cdmon lint --modes` prints an informational view and the
  structural pass/fail exit code is untouched (pinned by
  `test_lint_modes_does_not_suppress_structural_failures`). → When a slice asks to
  "teach lint about X," distinguish a *gate* (drives exit code, needs an issue code)
  from a *surface* (reports state, additive, exit-code-neutral); a STATE read is the
  smaller, safer change.

- **Dogfood reheal bit via a DOCSTRING edit on a tracked module.** I only changed
  `config.RegionMode`'s docstring (no signature change), but `config.py` is in the
  `foundation` doc and the eng-guide surface hash folds docstrings (K3), so it drifted
  HASH. `cdmon monitor --apply` healed it; the same run also flushed accumulated
  pipeline/remediation symbol-table lag from the earlier B-02/B-03 module edits (those
  docs reference `heal.py`/`drift.py`/`config.py` and had not been re-healed). `check`
  + `lint` exit 0 and the full suite is green POST-reheal. → A docstring-only edit on a
  tracked module still drifts an eng-guide doc; reheal regardless of whether the public
  signature moved.

- **EPIC B is COMPLETE.** generated/human/llm-seeded are fully working end to end and
  proven by a single mixed-authorship system test; pure-`llm` prose authoring is the
  one deferred piece (B-06), with a documented + asserted interim rule (`llm` ==
  `generated`) holding the line until then.

## EPIC-C — docs-PR flow

- **The dry-run "restore-INCLUDING-delete-new-files" trick (C-01).** A dry-run that
  must leave the tree byte-identical can't just snapshot+restore *existing* files: a
  heal can CREATE a file (a MISSING_DOC stub). The complete inverse of `monitor.run`'s
  mutation is therefore: snapshot each doc's text as `str | None` (None = absent)
  BEFORE; if a doc was None before but exists after, the run created it → DELETE it on
  restore; otherwise rewrite it to its before-text. Snapshot the byte content before
  AND after to *verify* the restore — that assertion is the actual K1 contract, not the
  code. The mock backend ESCALATEs MISSING_DOC so it never creates a file; to cover the
  delete branch I injected a tiny `_CreatingBackend` returning a whole-doc FIX (the
  cheap way to drive a real file-creation through `monitor.run(apply=True)`).

- **Reuse `monitor.run` to get authority-correctness for FREE.** `sync_pr` builds the
  patch by diffing the docs around a real `monitor.run(apply=True)` — NOT by
  re-implementing heal. Because the heal write-boundary already enforces B-02/B-03
  (human/locked-llm-seeded regions are never authored by the engine), those bodies
  simply never change, so they never appear in the diff. Zero new authority logic, and
  a one-line regression guard (`human_body not in result.patch`) proves it. The lesson:
  when you need "what would healing change?", drive the *same* pipeline and diff, don't
  fork it.

- **`difflib.unified_diff` is deterministic if you pin its inputs (K10).** Use
  `splitlines(keepends=True)` + `lineterm=""` + fixed `a/<path>`/`b/<path>` labels and
  sort the docs by path. No timestamps in the header (the 2-arg fromfile/tofile form
  omits the mtime field), so the patch is byte-stable across runs — `dry.patch ==
  applied.patch` holds, which is the test that the dry-run and real-apply paths agree.

- **`docs:gate` is an ORTHOGONAL CI signal, kept separate from `tests:offline`.** Drift
  is a different failure mode than a failing unit test, so it gets its own fast offline
  job (`cdmon check` + `cdmon lint`) rather than being folded into the test job — a red
  pipeline then tells you *which* kind of thing broke. Both gates are pure/offline (K1/
  K4), so neither spends a token. C-04 still needs to add the loop-safety path rule so
  the bot's own doc-only commits don't re-trigger the heal (noted in a CI comment).

- [C-03] **The GitLab 3-call MR flow (branch → commit → MR) collapses to ONE injected
  leaf, so the whole transport is 100%-testable with zero network (K4).** GitLab needs
  three REST calls — POST `/repository/branches` (create the source branch off the
  target), POST `/repository/commits` (one commit carrying an `update` action per healed
  file), POST `/merge_requests` (open the MR) — but they all go through a single
  `_GitLabHttp.request(method, url, *, body, token) -> dict` Protocol. The ONE real
  `urllib.request.urlopen` lives in the `_UrllibGitLabHttp.request` leaf (the only
  `# pragma: no cover`); a fake `_GitLabHttp` asserts the exact 3 ordered calls + bodies
  + token, and the lazy build-default branch is covered by monkeypatching that concrete
  leaf's `.request` (NOT the Protocol — patching the `Protocol` class does nothing, so
  the build-default test silently hit the real network and 401'd; patch the *concrete*
  `_UrllibGitLabHttp`). This is CDM-04/05 inject-the-leaf applied to a multi-call API:
  one leaf, many provider calls behind it.

- [C-03] **Deterministic-branch-from-patch-hash makes the bot PR idempotent at the
  branch level (K10).** `source_branch = f"{prefix}-{sha256(sync.patch)[:12]}"`: the
  same healed patch always yields the same branch, so re-running `open-docs-pr` for an
  unchanged docs sync targets the same branch (no proliferation), while any real doc
  change moves the hash → a fresh branch. The patch (not the file contents or a
  timestamp) is the right hash input because it already canonicalizes WHAT changed.

- [C-03] **Two-layer plan/transport split = assert the plan, never the network.**
  `plan_docs_pr` builds a pure, frozen `MergeRequestPlan` (branch/title/description/
  files/labels) and `open_docs_pr` just routes it (empty→None no-op; `dry_run`→
  `plan.model_dump()` with NO transport call; else `transport.submit`). Tests assert
  the EXACT plan against a fake `PRTransport` and assert the no-call paths by checking
  the fake recorded zero calls — the provider is never reached. The CLI's `--dry-run`
  path needs no transport at all: a module-level `_NullTransport` (a never-submitted
  guard) satisfies the type so dry-run prints the plan JSON without env/network, and
  the real `GitLabTransport.from_env()` (loud K8 on a missing var) is built only on the
  live path.

- [C-03] **`--dry-run` must thread through to the *sync*, not just the transport.**
  `cdmon open-docs-pr --dry-run` calls `sync_pr(dry_run=True)` so the working tree is
  left byte-identical (the plan is computed from the would-be-healed content via the
  C-02 restore-including-delete), AND skips building/calling the transport — two
  independent "no side effect" guarantees from one flag. For C-04/05: the plan already
  carries the changed doc **paths** (`files` + the bulleted `description`) so the
  loop-safety exclude can be built from `plan.files`/`sync.changed_paths`, and the
  provenance `ref` already lands in the title + description (C-05 threads a
  `source_sha`/`ref` into the `ReviewRecord` + reuses this MR description).

- [D-03] **Feature-match scoring with DESCENDING-DISTINCT weights + a documented
  total order beats "domination" intuition.** The spec wanted "higher feature
  dominates" but a naive read (surface_hash=5 must beat doc+kind+audience) is wrong:
  3+2+1=6 > 5, so a same-doc/kind/audience record outranks a same-surface-only one —
  and that is CORRECT (three shape matches is stronger evidence than one surface
  match). Don't over-engineer weight-domination; just pick distinct descending weights
  and lean on the explicit total order. The ranking is `sort(key=(-score,
  recency_desc, record_id_asc))`: recency-DESC inside an otherwise-ascending sort is
  the only trick — ISO timestamps sort lexicographically=chronologically, so invert
  each code point (`_neg_iso`) to flip just that field without a reverse pass. → A
  single total-order sort key (K10) is more robust than multi-pass sorting; encode
  every tie-break in the key and negate the descending ones.

- [D-03] **ReviewRecord carries no `region_id`, so a spec feature can be physically
  unavailable.** The D-03 spec listed `region_id` as a similarity feature, but the
  retrieval target is a `ReviewRecord` (which only has `doc_id`/`drift_kind`/
  `audience`/`surface_hash`). Rather than widen the public schema (a deliberate K6
  decision, not an incidental one), I dropped region from the feature set and
  documented it. → When a spec names a feature, verify the data model actually carries
  it before implementing; prefer documenting the gap over silently widening a versioned
  public model.

- [D-04] **DEFAULT-OFF + DEFAULT-EMPTY is what makes a cross-cutting change provably
  additive.** Three independent default guards keep every prior test byte-identical:
  `FixRequest.exemplars=()` (backends/build_prompt/MockBackend never look at it),
  `Monitor(use_exemplars=False)` (reads NO log/resolutions, attaches `()`), and
  `render_context`'s `_render_exemplars` returning `""` for an empty tuple (so the agent
  prompt is byte-for-byte the pre-D-04 string). The cheapest proof is a test that
  asserts equality with/without the feature engaged (`build_prompt(base)==build_prompt(
  with_ex)`, `render_context(req)==render_context(empty)`) rather than re-deriving the
  expected output. → For any additive feature on a hot path, add an explicit
  "engaged-vs-not is identical when default" assertion; it catches accidental coupling
  the existing suite would miss.

- [D-04] **Artifact selection is the natural seam for "only when relevant" prompt
  content.** The agent already loaded TOOL.md only for healable drifts and PERSONA.md
  only when enabled; EXEMPLARS.md slots in identically — `select_artifacts` appends it
  iff `req.exemplars` is non-empty, and `render_context` renders the bodies. The
  static FRAMING (how to read precedent: ACCEPTED→mirror, OVERRIDDEN→use resolved_text,
  REJECTED→avoid, surface still wins per K2) lives in the `.md`; the per-drift DATA
  lives in `render_context`. → Keep new prompt capabilities as a selectable artifact +
  a context renderer; never inline framing into code, and gate it on the data actually
  being present so the no-data path stays unchanged.

- **`should_sync` is the STRUCTURAL loop-breaker, not a heuristic (C-04).** The
  PR-driven loop (a code push heals docs → opens a docs MR → that MR's merge is itself
  a commit) could re-trigger the heal forever. The fix is a *pure set-membership*
  predicate, not a label/branch-name convention: a heal runs iff at least one changed
  file is OUTSIDE the managed-doc set (`{d.path for d in config.documents}`). A bot
  commit that touches ONLY managed docs is, by construction, doc-only → `should_sync`
  is False → no heal → the loop terminates. Keeping it a pure function over a
  changed-file LIST (not git, not a provider API) makes it trivially testable
  (truth-table) and provider-agnostic — CI supplies the list however it likes
  (`git diff --name-only`). POSIX-normalize BOTH sides (`PurePosixPath`, back-slash→`/`)
  so `./docs/x.md` / `docs\x.md` / `docs/x.md` collapse to one comparison; otherwise a
  cosmetic path variant silently flips the verdict.
- **Additive-schema back-compat is a ONE-LINE change with a LOAD-BEARING test (C-05,
  K6).** Adding `source_sha: str | None = None` to `ReviewRecord` is safe ONLY if you
  (a) APPEND it last (never reorder/rename — pydantic validates by name so order is
  cosmetic for round-trip, but field order leaks into `model_json_schema()` and any
  positional consumer, so appending keeps the diff minimal and the intent obvious),
  and (b) give it a default so an OLD JSONL line that predates the field still
  `model_validate_json`s. The proof is a literal hand-written legacy-record dict (NO
  `source_sha` key) that must validate to `source_sha is None` — that single test is
  the K6 contract; without it a "harmless" default could be silently made required by
  a later refactor. The default-None ALSO means every prior record test passes
  UNCHANGED (the field is invisible until something sets it), which is why a wide
  additive change perturbs zero existing assertions.
- **Provenance has ONE source of truth with explicit precedence (C-05).** The `ref`
  that stamps `ReviewRecord.source_sha` (via `monitor --ref`), the MR title, and the
  MR description (C-03 `open-docs-pr --ref`) must all be the SAME value, or an audit
  can't link a record to its MR. The rule, documented in ARCHITECTURE + the `--ref`
  help: explicit `--ref`/`--source-sha` wins, else `$CI_COMMIT_SHA`, else None. Reading
  the env fallback in the CLI (not deep in `Monitor`) keeps the pure pipeline injectable
  and clock/env-free (K10) — the env read is at the IO boundary, the same place the now-clock
  is injected.
- **The human OUTCOME is a SEPARATE append-only event, never a record mutation (D-01/D-02, K5).**
  Capturing "this drift was accepted/overridden/rejected/invalidated" by editing the
  `ReviewRecord` in place would violate K5 (the review log is an immutable audit trail)
  and force a rewrite of a JSONL line. Instead a `ResolutionRecord` is its OWN
  append-only event linked to the review record by `record_id` (FK) — the review log is
  never touched, and a resolution lands in a parallel `.cdmon/resolutions.jsonl`. This
  also keeps the outcome schema independently versioned/additive: `note` is appended
  LAST with a default so an older resolution line still parses (same K6 pattern as
  `ReviewRecord.source_sha`). The read side JOINS the two logs.
- **Last-write-wins is the RIGHT join for an append-only outcome log (D-01/D-02).** A
  human may resolve the same record twice (a correction). Because the log is append-only,
  a correction is a NEW line, not an edit — so `resolved_index` iterates in append
  (chronological) order and keeps the LAST entry per `record_id`. This gives the most
  recent decision deterministically (K10) while preserving the full history on disk for
  audit/replay. The summary then counts a record as "resolved" iff its id is in that
  index; ORPHAN resolutions (an id not in the review log) are dropped so they can't
  inflate counts — the review log is the authoritative population.
- **Extend the cohesive module, don't reflex-split (D-01/D-02).** The spec offered a new
  `resolutionlog.py` OR extending `reviewlog.py`. Extending won: the join needs BOTH logs,
  and `append_resolution`/`read_resolutions` are byte-for-byte mirrors of `append`/`read_all`
  (same append-mode/parent-dirs/blank-skip/`SchemaError`-with-line-no machinery). A separate
  module would have duplicated that machinery or created a circular read dependency for the
  join. Cohesion > file count.
- **The CLI now has its OWN injectable `_now` seam (D-02).** `Monitor` injects `now` via its
  ctor, but `cdmon resolve` builds a `ResolutionRecord` directly in the command. Rather than
  thread a clock through, a module-level `cli._now()` (mirroring `monitor._default_now`) is the
  seam tests monkeypatch (`monkeypatch.setattr(cli, "_now", ...)`) for a deterministic
  `resolved_at` (K10). Pattern for any future CLI command that timestamps without a Monitor.
- **Generalizable shape vs exact `surface_hash` — the key D-05 design call.** similar.py's
  retrieval RANKS on `surface_hash` (weight 5.0, its dominant feature) because it wants the
  most-similar PAST drift to show the agent. The PROMOTION detector wants the OPPOSITE: a shape
  that RECURS. `surface_hash` is the exact code state and changes on every edit, so it NEVER
  recurs across distinct drifts — grouping by it would yield singleton buckets and promote
  nothing. The shape that recurs is the audience-scoped doc+kind `(doc_id, drift_kind, audience)`.
  So D-05 deliberately DROPS `surface_hash` from the key (the test `test_three_unanimous_invalidations_one_candidate`
  uses THREE different `surface_hash`es in one shape to prove generalization). Reuse the substrate
  (`read_all` + `resolved_index`), NOT the scoring feature set.
- **Promote DECISIONS, not content (D-05).** Only `invalidated`/`rejected` auto-promote: they are
  pure human judgements with NO `resolved_text`, so a rule reproduces them deterministically.
  `overridden` carries human prose that rarely generalizes (a rule can't author the right body),
  and `accepted` of a mechanical fix is already LLM-free — both are excluded. The promotable set is
  a named constant (`PROMOTABLE_RESOLUTIONS`) so a future content-rule slice can extend it explicitly.
- **The zero-backend-call cost-curve win, proven by a SPY (D-06).** The validable goal is not "the
  rule produces the right verdict" but "the backend is NEVER consulted for a matched drift". A
  counting `_SpyBackend` (wraps MockBackend, increments `calls`) makes that assertion concrete:
  matched shape → `spy.calls == 0`, non-matching → `== 1`, default `rules=()` → `== 1` for everything
  (the additivity proof). The rule path `continue`s BEFORE building the FixRequest or calling
  `propose`, so it is strictly cheaper than the backend path — the system's cost curve bends DOWN as
  it learns. Default-empty `rules` keeps `run()` byte-identical to today (the same default-OFF pattern
  as D-04's `use_exemplars`).
- **Mark the rule-sourced record, but additively (D-06, K5/K6).** A rule-resolved drift is STILL
  recorded for human audit (K5) — it must be distinguishable from a backend verdict without a schema
  change (K6). Rather than add a `ReviewRecord` field, the marker lands in the existing free-form
  `config_snapshot` (`resolved_by="rule"`) plus a `RULE_CAUSE_PREFIX` on the human-readable `cause`.
  The central server (EPIC E) can filter on it; no migration needed.

- [E-01] **Reporting is best-effort and must NEVER raise into the heal loop (K4).** `HttpSink.emit`
  swallows EVERY transport exception (`except Exception` on each `client.post`, documented as "network
  down") and falls back to queueing — a flaky/down central system can never crash a `monitor --apply`
  run. The corollary: tests drive every behaviour through the injected client (a `FlakyClient` with a
  `down` flag + a `fail_for` set of call-ordinals), and the REAL `_UrllibClient.post` urlopen stays the
  ONLY `# pragma: no cover` leaf. K4 here is coverage-shaped — if a behaviour isn't exercised by the
  fake, it isn't covered; structure the code so the only un-coverable line is the actual socket call.

- [E-01] **Drain-then-send ordering is the whole correctness story for the outbox.** `emit` must
  (1) drain the backlog oldest-first, (2) send the new envelope ONLY if the backlog drained cleanly,
  and (3) on any failure queue the new envelope BEHIND the backlog. The non-obvious bug to avoid:
  sending the new record while a backlog exists (or queueing it ahead of the backlog) breaks the
  oldest-first invariant. A partial flush re-writes `failed+remainder` back in order (`queued[i:]`), so
  the next `emit` resumes exactly where it stopped. The outbox is a JSONL of `IngestEnvelope` lines
  drained by read-all-then-rewrite-the-undrained-tail — simple and deterministic because the sink is
  single-process (no concurrent writers to reconcile).

- [E-01] **The envelope is the SHARED, versioned wire format — define it ONCE, in the layer that owns
  the transport (K6).** `RepoIdentity`/`IngestEnvelope` live in `sinks.py`, NOT `schema.py`: `schema.py`
  stays the pure review-record source and importing it back into `schema.py` would cycle. The E-03
  server imports `IngestEnvelope` from `sinks` and validates `/ingest` bodies against it directly —
  there are NO client/server DTOs to keep in sync, and `schema_version` is the single additive-compat
  hinge. Wrapping (envelope) rather than mutating `ReviewRecord` keeps the record schema untouched
  while adding repo identity, exactly the additive discipline K6 wants.

- [E-01] **Additive config + a required-on-condition field caught loudly in the factory (K8).** The new
  `CentralConfig` repo fields all default `None`/`2`, so every pre-E-01 config still loads — but `repo_id`
  is REQUIRED when `sink=="http"`. Pydantic can't express "required only for one sink kind" cleanly on a
  frozen model, so the check lives in `make_sink` (a loud `SchemaError`, K8) — the same place the
  existing `url`-required check already lived. Commit precedence is `cfg.repo_commit` else
  `$CI_COMMIT_SHA` (CI injects the SHA), resolved in `make_sink` so the env read happens once at sink
  construction, not per-emit.

- [E-02] **A "factor a shared helper" instruction can collide with the module dependency graph — the
  cycle wins.** The spec invited factoring `make_sink`'s `RepoIdentity` build into a shared
  `repo_identity_from_config(cfg)` and having `make_sink` call it. But that helper naturally lives in the
  NEW module (`registry.py`), and `registry` already imports `RepoIdentity` from `sinks` — so `sinks`
  calling back into `registry` would be a hard import cycle. Resolution: keep the helper in `registry.py`
  for `registry`'s own (and E-03's / future) callers, and leave `make_sink`'s ~6-line identity build as a
  deliberate small dup rather than invert the dependency or hoist the helper into a third module just to
  satisfy DRY. → "Factor if it cleanly de-dups" means *check the import direction first*; a one-way
  `new→old` dependency is clean, the reverse is a cycle — don't over-refactor to chase it. The
  RepoIdentity wire model lives in `sinks.py` (E-01's call) and is the shared root both `IngestEnvelope`
  and `RegistrationPayload` build on, so any helper that produces it belongs DOWNSTREAM of `sinks`.

- [E-02] **The inject-the-leaf pattern leaves exactly one partial branch, and that's correct.** Every
  test starts the transport with `http=None` and stubs `_UrllibRegisterHttp.request`, so the lazy-build
  `if http is None:` line is always taken in one direction (the `else` — reusing an already-built leaf —
  is never hit because nothing re-registers on the same instance). Coverage reports it as a partial
  branch (`118->120`) with 0 statements missed. This is the SAME shape as `sinks.py`/`pr.py` and is
  intended: the real network leaf is the only `# pragma: no cover`, and the lazy-build short-circuit's
  unused arm is an artifact of single-use transports in tests, not a coverage gap. → Don't chase 100%
  branch coverage by contriving a re-register call; the inject pattern's one partial branch is the cost
  of keeping the real urlopen the sole uncovered line.

- [E-03] **A `[server]` extra is genuinely lazy ONLY if core never imports the subpackage — verify it,
  don't assume.** The lazy boundary isn't a property of `server/__init__.py` (which DOES import fastapi
  via `.app`); it's the property that `code_doc_monitor/__init__.py` and the engine modules never
  `import .server`. `server/__init__.py` can eagerly import fastapi and the boundary still holds, because
  nothing pulls the subpackage in until you explicitly `import code_doc_monitor.server`. I proved it with
  a `sys.modules` assertion (`'fastapi' not in sys.modules` after a bare core import) rather than trusting
  the structure. → When adding an optional-extra subpackage, the test that matters is "does a core import
  drag in the heavy dep", not "is the subpackage's own `__init__` lazy". Keep the PURE half (here
  `store.py`: the `Store` Protocol + `InMemoryStore`, no fastapi) separate so a non-HTTP consumer/test can
  use it without the extra.

- [E-03] **Shared schema AS the request model = zero-DTO validation for free, including extra-key
  rejection.** Typing a FastAPI route param as `registry.RegistrationPayload` / `sinks.IngestEnvelope`
  (the very models the client sends) means a malformed body is a 422 with no hand-written DTO (K6), AND
  because those models are `extra="forbid"`, an unexpected key is also a 422 (K8) — no extra code. The
  record round-trips byte-for-byte (asserted `response_record == sent_record`) because both ends use the
  same pydantic model. → For any new ingest endpoint, reuse the shared wire model directly; don't mirror
  it into a DTO (mirrors drift the contract and lose the extra="forbid" guard).

- [E-03] **`{repo_id:path}` is required when a path param can contain `/`.** Repo ids are org/name
  (`acme/widget`); a plain `/repos/{repo_id}/records` route does NOT match a URL-encoded `%2F` because
  Starlette decodes it and the slash then splits path segments (→ 404). The `:path` converter captures
  the remainder whole. Cost me one red cycle. → Any path param keyed on a `repo_id`/path-like id needs
  `:path`. E-05's per-repo query endpoints inherit this.

- [E-03] **Two clean non-blanket escapes keep mypy/ruff green for an optional extra: a per-file B008
  ignore and a per-module `ignore_missing_imports`.** FastAPI's `Depends(...)` in route defaults trips
  ruff B008 exactly like typer's option defaults — reuse the existing per-file-ignore idiom
  (`server/app.py = ["B008"]`), don't `# noqa` each line. `uvicorn` (in the `[server]` extra, and not
  even installed in this `.venv`) has no stubs and is referenced ONLY in the `# pragma: no cover`
  `main()` launch leaf — a per-module `[[tool.mypy.overrides]] ignore_missing_imports = true` is the
  surgical fix, NOT a blanket `# type: ignore` on the import. The Starlette TestClient `httpx`/`httpx2`
  deprecation got a TARGETED `filterwarnings` ignore (matched on the message text), so a future `-W
  error` server run stays green without globally silencing warnings. → Prefer config-level, scoped
  escapes (per-file ruff ignore, per-module mypy override, message-matched filterwarnings) over inline
  blanket suppressions; they document intent and don't leak to unrelated code.

## E-04 — SQLAlchemy DB layer (Postgres-first) + Alembic

- **"Indexed columns + full JSON" hybrid is the K6-additive store design.** Each
  record/resolution row stores the FULL shared pydantic model in a JSON column
  (`JSON().with_variant(JSONB(), "postgresql")` → JSONB on PG, JSON on SQLite) AND a
  set of indexed scalar columns (`repo_id/doc_id/verdict/drift_kind/audience/
  detected_at/source_sha`). The JSON is the SOURCE OF TRUTH on read (`ReviewRecord.
  model_validate(row.record)`); the scalars are a derived projection written on insert,
  there only for E-05's SQL filters. Net effect: an ADDED schema field round-trips with
  NO migration (old rows still `model_validate`), proven by re-using the C-05 `source_sha`
  additive field as the round-trip witness. The portable JSON type lives in ONE helper
  (`_json_type()`) imported by BOTH the models and the Alembic migration so SQLite-dev
  and PG-prod never drift.
- **SQLite-default / `pg`-marker is the offline-first DB strategy (mirror of `live_llm`).**
  The default suite runs the WHOLE contract on stdlib SQLite (no driver, K4/K9); a
  `@pytest.mark.pg` copy runs the same contract against `$CDMON_DATABASE_URL` Postgres.
  Register the marker + extend `addopts` to `-m "not live_llm and not pg"` so it's
  collected-but-DESELECTED by default (verified: 16 collected / 1 deselected); `-m pg`
  in the `tests:pg` CI job (a `postgres:16` service) opts in. The real-PG test body is
  the only K4-acceptable uncovered leaf — but because tests aren't in `--cov` scope it
  needs no `# pragma`, and `@pytest.mark.skipif(not pg_url)` makes it skip cleanly even
  if someone runs `-m pg` locally without a DB.
- **In-memory SQLite needs `StaticPool` + `check_same_thread=False` or you get a fresh
  empty DB per connection.** `sqlite:///:memory:` with the default pool gives each new
  connection its OWN database, so `create_all` (one connection) is invisible to the
  store's sessions AND to FastAPI's TestClient thread ("no such table: repos"). Gate
  in-memory SQLite specifically onto `StaticPool` (one shared connection) inside
  `engine_from_url`; file-backed SQLite and Postgres use the normal pool. This is the
  thing that bit the `create_app(SqlStore(memory_engine))` Protocol-swap re-run.
- **SQLAlchemy 2.0 `Mapped[...]`/`mapped_column` typing is mypy-clean with ZERO ignores.**
  Use `Mapped[str]` / `Mapped[str | None]` / `Mapped[dict]` + `mapped_column(...)` (not
  the legacy `Column`), declare the JSON column type as `TypeEngine[dict]` from the
  helper, and `select(...).order_by(Row.id)` via `session.scalars(...).all()`. No
  sqlalchemy-plugin gap forced a `# type: ignore` — 34 files clean. (The one subtlety:
  the surrogate-`id` PK + autoincrement is required for an insertion-order column; a
  non-PK `autoincrement` column on SQLite raises a NOT-NULL IntegrityError, so make the
  ordering key the integer PK and the business key (`repo_id`) a unique index.)
- **Alembic URL precedence: `$CDMON_DATABASE_URL` must WIN over the `alembic.ini`
  placeholder.** A hardcoded `sqlalchemy.url` in `alembic.ini` means `if not
  get_main_option("sqlalchemy.url")` is ALWAYS False, so the env var was silently
  ignored and the CLI migrated the placeholder `cdmon.db` instead of the configured DB.
  Fix: env.py sets the url from `$CDMON_DATABASE_URL` when present (else leaves whatever
  the Config has — the up/down pytest sets it programmatically via `set_main_option`, the
  ini default is the dev fallback). Also set `path_separator = os` in `alembic.ini` to
  silence the 1.18 legacy-splitting DeprecationWarning, and `render_as_batch=True` in
  env.py so future ALTERs run on SQLite too. The up/down round-trip is gate-tested via
  the `alembic` Python API (`command.upgrade(cfg,"head")` / `command.downgrade(cfg,"base")`)
  on a temp SQLite file, asserting the four tables appear then disappear.
- **`RepoStatus` as a COMPUTED VIEW is the one legit response DTO — and it doesn't
  violate K6.** K6 forbids parallel hand-written copies of the SHARED *stored* schema
  (`ReviewRecord`/`ResolutionRecord`) — those endpoints still return the shared models
  directly. `RepoStatus` is an AGGREGATE (counts/by_verdict/unresolved/last_detected_at/
  coverage_ratio) computed FROM store reads; it has no stored counterpart, so it's a
  view, not a duplicate. Make the distinction explicit in the model docstring +
  ARCHITECTURE/SPEC so a future slice doesn't "tidy it away" or, worse, mint DTOs for
  the real records. Zero-fill `by_verdict` with all enum keys so the dashboard renders a
  stable shape (K10) regardless of which verdicts are present.
- **Filter-via-indexed-columns then RE-VALIDATE the JSON — the hybrid pays off in E-05.**
  The E-04 "indexed scalar columns + full JSON" design means E-05's filters are pure SQL
  `WHERE` on the indexed columns (`verdict`/`drift_kind`/`audience`/`doc_id`), but the
  returned rows are STILL re-validated from the JSON column (`ReviewRecord.model_validate
  (r.record)`) — the scalar columns are only a query index, never the read source of
  truth (K6). Keep the `InMemoryStore` filter semantics byte-identical (same AND-combine,
  same insertion order, same `offset:offset+limit` slice) so the Protocol stays the one
  seam and the unit tests stay offline/fast. Enforce `limit>0`/`offset>=0` at the FastAPI
  layer (`Query(gt=0)`/`Query(ge=0)`) so bad pagination is a 422, not a silent empty page.
- **Hashed-token auth as a tiny inline dependency: hash ONCE, compare hashes, never store
  plaintext.** One shared `hash_token` (sha256 hex) used at BOTH register-time (write the
  hash) and verify-time (hash the presented bearer, compare) keeps them in lock-step
  (K10). Store the hash on its OWN column, NOT in the payload JSON — `model_dump(mode=
  "json", exclude={"auth_token"})` strips the write-only plaintext field before it ever
  touches the DB, and `RegisteredRepo` simply omits it, so no read path can leak it
  (assert `auth_token ∉` every read in a test). Status-code discipline (K8): check
  unknown-repo FIRST (404), then missing/not-Bearer header (401), then mismatch (403) —
  order matters so an unknown repo never leaks "needs a token". A nullable `token_hash`
  (None = registered without a token) keeps the column ADDITIVE and back-compatible:
  token-less repos stay open, which is also what lets the existing register→ingest→read
  tests keep passing by simply NOT supplying a token (the one intentional test change).
- **First-register is open, RE-register is gated — so a repo can mint its own token.**
  If `POST /repos` required a token, a brand-new repo could never establish one. So the
  auth dep fires on register ONLY when the repo already exists AND has a token_hash
  (rotation must be authorized by the current token); the first registration is open. On
  `SqlStore.add_repo` UPSERT, rotate the hash ONLY when a new token is supplied (`if
  token_hash is not None`) so a re-register that omits the token doesn't blank it.
- **EPIC F (React+Vite SPA) posture, decided + documented here: GET reads are OPEN, only
  writes are bearer-gated.** The dashboard consumes `GET /repos/{id}/records|resolutions|
  coverage|status` with NO `Authorization` header; only `POST /ingest` + re-register need
  `Bearer`. Rationale: the SPA is a read-only view and per-repo tokens are an ingest
  credential, not a user session — gating reads would need a separate auth model (org/
  user accounts, out of scope). Tightening reads (and token rotation/revocation UI) is
  noted as future work. `RepoStatus` is the summary shape; `by_verdict` always carries
  all three verdict keys.

## F-01 — dashboard scaffold (Vite + React + TS) + Vitest

- **`erasableSyntaxOnly` is a TS 5.8+ compiler option — pin TS or drop it.** The current
  Vite `react-ts` template's `tsconfig.app.json`/`tsconfig.node.json` ship
  `"erasableSyntaxOnly": true`, which TypeScript **5.7.3** rejects with `TS5023: Unknown
  compiler option`. The lesson: the scaffold template tracks the latest TS; if you pin TS
  one minor behind, strip template options newer than your pinned compiler (or bump TS).
  Removed it from both tsconfigs — the build went green. (`tsc -b` surfaces this; `vitest`
  does NOT, because Vitest transpiles with esbuild and never type-checks.)
- **Vitest 2.x bundles its OWN nested `vite`, which breaks `tsc -b` on a shared
  `vite.config.ts`.** With `vitest@2.1.8` + top-level `vite@6`, typing `vite.config.ts`'s
  `test:` key (needed for jsdom/setupFiles) pulls Vitest's `vitest/config`, whose plugin
  types come from `node_modules/vitest/node_modules/vite` — a DIFFERENT type identity than
  the top-level `vite` that `@vitejs/plugin-react` returns. `tsc -b` then fails:
  `Type 'PluginOption[]' is not assignable to type 'PluginOption[]'` (same name, two copies)
  and `'stringify': "auto" not assignable to boolean`. Fix that worked: **bump to
  `vitest@3.2.6`**, which uses the top-level `vite@6` (no nested copy — confirmed
  `node_modules/vitest/node_modules/` has only `picomatch`), and import `defineConfig` from
  `vitest/config`. Build clean, 9 tests green. Alternative (not taken): keep `defineConfig`
  from `vite` + a separate `vitest.config.ts`, or a `/// <reference types="vitest/config" />`
  triple-slash — but the reference is NOT picked up by `tsc -b` when the config is in a
  referenced project (`tsconfig.node.json`), so the `test:` key errored. One vite is simplest.
- **Inject `fetch`/the client instead of MSW — zero network, less dep weight.** The slice
  said "MSW or a typed fake". A typed fake is lighter: `ApiClient({fetchImpl})` takes an
  injectable `fetch` (client unit tests pass a fake capturing `{url, init}` to assert the
  path + base-URL building), and `Repos` takes an injectable `api?: ReposApi` prop (component
  tests pass a plain object resolving/rejecting fixtures). No MSW server, no
  `setupServer`/`beforeAll` lifecycle, no opened sockets — and the same pattern extends to
  F-02/03/04 pages verbatim.
- **`react-refresh/only-export-components` is a WARN, not error — but keep page modules
  component-only anyway.** `Repos.tsx` exports the `ReposApi`/`ReposProps` *types* + the
  component; ESLint's react-refresh rule is configured `allowConstantExport` and types are
  erased, so no warning fired. If you add a non-component value export to a page, expect the
  warning (move it to a sibling module).
- **`dist/` was already gitignored at the repo root (Python `build/`+`dist/`) — but add an
  explicit `dashboard/dist/` + `dashboard/node_modules/` anyway for clarity**, plus a
  `dashboard/.gitignore`. `package-lock.json` IS committed (reproducible installs).
- **The Python `cdmon` gate is undisturbed by the TS dir.** `cdmon check`/coverage scan
  `**/*.py` only; `dashboard/` has no `.py`, so it's invisible to dogfooding — confirmed
  `cdmon check` exit 0 and pytest still 648 after the scaffold. Do NOT add the dashboard to
  `cdmon.yaml`.

## F-02/03 — drift-timeline + coverage views (routing + 2 read views)

- **A react-router `:param` cannot capture a slash — a slash-bearing repo id needs a splat
  route + a dispatcher, NOT `:repoId`/`:repoId/coverage`.** repo ids are the `org/name` form
  (the server route is `{repo_id:path}`), and `<Route path="/repos/:repoId">` would put `org`
  in `repoId` and `name` in the unmatched tail. The fix: ONE splat route `/repos/*` →
  `RepoRoute.tsx`, which reads `useParams()["*"]`, reconstructs the full id, and dispatches to
  `Coverage` (when the tail ends `/coverage`) or `RepoDetail`. Inverse link builders live in
  `src/routing.ts` (`linkToRepo`/`linkToCoverage`, each segment `encodeURIComponent`d, slashes
  preserved) so the hrefs round-trip through the splat. Two `*` routes can't disambiguate
  `…/x` from `…/x/coverage` (both match `/repos/*`), hence the in-component dispatch.
- **The shared `apiClient` singleton captured `fetch` at construction, so `vi.stubGlobal('fetch',…)`
  didn't reach it.** F-01's client did `this.fetchImpl = opts.fetchImpl ?? fetch` — binding the
  *current* global at import time. An integration test that drives the REAL router (and thus the
  singleton) and stubs the global fetch was ignored: it hit jsdom's real fetch and threw
  "Failed to parse URL from /api/repos" (relative base). Fix: default to a LAZY indirection
  `opts.fetchImpl ?? ((...a) => globalThis.fetch(...a))` — an explicit injected fake is still used
  verbatim, but the default now honors a later `vi.stubGlobal`. Lesson for any future singleton
  over a global: don't snapshot the global in the constructor.
- **schema→TS is HALF the contract: `cdmon schema` emits ONLY the review record.** Running
  `.venv/bin/cdmon schema --out dashboard/src/schema.review.json` gives the K6-true
  `ReviewRecord` JSON Schema (with `$defs` for `Audience`/`Verdict`/`ProposedFix`), which I
  mirrored 1:1 into TS interfaces — generated, honest, matches the rendered fields.
  But `ResolutionRecord` is NOT in that schema (the CLI only serializes the review record), and
  the coverage snapshot is an OPAQUE `list[dict]` server-side (`store.coverage_for`; app.py reads
  only `ratio`). So `Resolution`/`ResolutionRecord` were hand-written from `schema.py` and
  `CoverageSnapshot` declared with `ratio` contractual + optional/defensive basket counts +
  an index signature — and I said so in a comment in `types.ts`. Don't claim "generated from
  schema" for shapes the schema command never emits.
- **Verdict name collision: F-01's `Verdict` is the RepoStatus *bucket* (`ok|review|escalate`),
  NOT the per-record decision (`FIX|INVALIDATE|ESCALATE`).** I named the record's enum
  `RecordVerdict` to avoid shadowing the existing export. They are genuinely different value
  sets (aggregate status buckets vs. the backend's per-drift verdict in `schema.py::Verdict`).
- **Testing a filter re-query: a fake client that CAPTURES call args + a `useApi` whose `deps`
  include the filter state.** `RepoDetail`'s `loader` is a `useCallback` over the filter
  primitives, passed as the only `useApi` dep; a `fireEvent.change` on a `<select>` updates
  state → new `loader` identity → re-run → the fake records a new `recordsFor(repoId, filters)`
  call whose `filters.verdict` the test asserts. No MSW, no sockets. (`@testing-library/user-event`
  is NOT installed in this repo — `fireEvent.change` is enough for selects/inputs.)

## F-04/F-05 — resolve write path (full-stack) + health overview (EPIC F COMPLETE)
- **A full-stack slice puts the SHARED schema on the wire, not a DTO.** F-04's
  `POST /repos/{id}/resolutions` validates the request body DIRECTLY against the shared
  `schema.py::ResolutionRecord` (FastAPI/pydantic, `extra="forbid"` → 422 on a stray key),
  and the TS `ApiClient.resolve` sends the same `ResolutionRecord` shape from `types.ts`.
  ONE schema, both ends — the K6 discipline that kept ingest DTO-free applies to the write
  path too. The only computed VIEW model added (`RepoHealth`) is clearly labelled like
  `RepoStatus`: an AGGREGATE over store reads, so K6's "no DTOs for the SHARED schema" does
  not govern it.
- **MTTR from ISO deltas is pure + deterministic if you don't read the clock in the math.**
  `_compute_health` parses each record's injected `detected_at` and its resolution's injected
  `resolved_at` (both ISO strings already on the stored models) and means the deltas —
  `_parse_iso(s) = datetime.fromisoformat(s.replace("Z","+00:00"))` to accept the trailing `Z`.
  Seeding two records with KNOWN 60s and 120s deltas asserts `mttr_seconds == 90.0` EXACTLY
  (K10). `escalation_rate` is `escalations/total` with an explicit `0.0` when `total==0` (no
  ZeroDivision on an empty repo). The wall-clock only appears at the UI edge
  (`new Date().toISOString()` when the user submits), never inside the aggregate.
- **The write-auth token flow from the UI reuses the EXACT server auth dep.** The resolve
  route calls the SAME `_verify_token` as `/ingest` (404 unknown repo → 401 missing Bearer →
  403 wrong Bearer), so the auth matrix test is identical in shape to E-06's ingest matrix.
  On the client, a small `postJson(path, body, token)` helper adds `Content-Type` +
  `Authorization: Bearer <token>`; the fake `fetch` captures `init.headers`/`init.body` so the
  test asserts the bearer + the JSON body. A MISSING token is caught in the COMPONENT (a
  friendly `role=alert`, no POST) — validate before you fetch so the client is never called
  with an empty token (asserted: `resolveCalls` stays empty).
- **`add_resolution` was already on both stores as an E-04 "seed helper" — F-04 just promoted
  it onto the `Store` Protocol.** No new persistence code; the route persists through the
  existing seam. When a future write needs a store method, check whether an earlier slice
  already shipped it as a helper before adding a parallel one.
- **Humanising MTTR seconds bit the test fixture.** `Health.tsx` renders 90s as "1.5m"
  (s<60→`Ns`, <3600→`N.Nm`, …). The first test asserted "90" against the fixture's
  `mttr_seconds: 90` and failed (got "1.5m"). Either assert the HUMANISED form or pick a
  sub-60 fixture — the rendered string is what the test sees, not the raw number.
- **A `…/health` route is another splat suffix, same as `…/coverage`.** `RepoRoute` already
  dispatched a slash-bearing repo id from the `/repos/*` tail; adding health was one more
  `tail.endsWith("/health")` branch + a `linkToHealth` inverse builder — the splat pattern
  scales to N per-repo sub-views without per-view `:param` routes.

- **G-02 — WARN vs FAIL: an absent runtime prereq is NOT a broken config.** The
  hard call in `cdmon doctor` is grading. A config can be perfectly VALID and
  still not be RUNNABLE on this particular machine: no `claude` CLI on `$PATH`,
  `$ANTHROPIC_API_KEY`/the central token unset, the optional `[agent]` extra not
  installed, a missing doc FILE (which `cdmon new-doc`/the heal will scaffold).
  Grading any of those as FAIL would make `doctor` a useless gate in CI (a job
  without the prod secrets would always red). So the rule we landed (and pinned in
  ARCHITECTURE.md + the `doctor.py` module docstring): **a merely-ABSENT prereq is
  WARN; only a STRUCTURALLY-broken config is FAIL.** The FAILs are exactly the
  cases `make_sink` would already raise on (K8): an `http` sink with no `url` /
  no `repo_id`, a `file` sink with no `path`. A missing doc file is PASS (it is
  creatable, not a gap), a missing CODE REF file is WARN (extraction degrades but
  the config is still valid in another checkout). `doctor` exits 0 unless a FAIL,
  so WARNs are advisory and CI stays green where it should.
- **G-02 — keep `doctor` OFFLINE; a `--ping` is a separate, injected-transport
  concern.** The temptation is for "doctor" to actually hit the central URL and
  report reachability. That breaks K4 (no network in the default path) and makes
  the check non-deterministic. We kept `run_checks` side-effect-free except env /
  `$PATH` / installed-distribution reads, and noted `--ping` (with an INJECTED
  transport, like every other network leaf in this repo) as an explicit future
  add. Token PRESENCE (is `$auth_env` set?) is a fine offline proxy for "are you
  wired to authenticate?" without sending anything.
- **G-01 — make `init --central` ADDITIVE by SWAPPING a substring, not rebuilding
  the template.** The existing `test_init_writes_file` + a new byte-identical
  assertion lock the offline template to its exact bytes. Rather than re-author a
  parallel template (drift risk), `central_config_template` does a single
  `CONFIG_TEMPLATE.replace(_OFFLINE_CENTRAL_BLOCK, http_block, 1)` — only the
  `central:` block changes, everything else (documents/backend/coverage scaffold)
  stays byte-for-byte, and the offline path still writes `CONFIG_TEMPLATE`
  verbatim. The resulting config is asserted to BOTH round-trip through
  `load_config` AND build a real `HttpSink` via `make_sink` (repo_id present) — the
  two contracts an adopter actually needs.
- **G — CliRunner separates stdout/stderr; assert K8 errors on `.stderr`.** The
  `doctor` malformed-config test first checked `result.stdout` for `error:` and
  failed (empty) — the per-command K8 handler prints to `err=True`. typer's
  `CliRunner` keeps the streams separate, so error-path assertions must read
  `result.stderr`, not `result.stdout` (the PASS/WARN/FAIL check lines go to
  stdout).
- **G-04 — wiring `HttpSink`→FastAPI `TestClient` for an OFFLINE full-loop e2e:
  keep the adapter in the TEST, mind the exception contract.** The capstone proves
  client config → heal → report → server → query with NO socket. `HttpSink`'s
  client is injected (`post(url, *, data, headers)`), so the test (not the package,
  K0) supplies a `_TestClientPostClient` that forwards to `TestClient.post(url,
  content=data, headers=headers)`. CRITICAL: `HttpSink.emit` treats ANY raised
  exception as "transport down" and never raises (K4) — so the adapter MUST RAISE
  on a ≥400 response, otherwise a 403/401 looks like a SUCCESS and the K4
  outbox-queue path never fires. With that, the wrong-token test is clean: every
  ingest 403s → the sink queues the envelopes to its outbox → nothing lands
  server-side, exactly the observable behaviour an adopter would get. The register
  transport has a DIFFERENT injected shape (`_RegisterHttp.request(method, url, *,
  body, token)` wrapped by `HttpRegisterTransport`, whose PUBLIC seam is
  `register(payload)`), so pass `HttpRegisterTransport(url, http=<adapter>)` — NOT
  a bare adapter — as `register_repo(transport=…)`.
- **G-04 — a raw `TestClient.post(content=bytes)` needs an explicit
  `Content-Type: application/json` or FastAPI 422s the body (masking auth).** When
  asserting the bearer rejection directly (replaying a queued outbox envelope), a
  raw `post(content=line.encode())` returned 422 ("not a valid dictionary"), NOT
  the 403 we wanted — FastAPI only parses the body as JSON when the content type
  says so. `HttpSink._headers()` always sets it, so the sink path was fine; the
  hand-rolled raw post had to add `{"Content-Type": "application/json"}`. Then 403
  (wrong token) and 202 (right token) on the SAME bytes prove the E-06 write path.
- **G-03 — a template-honesty test must parse the COMMAND lines, not the file
  text.** A first cut regex-scanned the whole YAML for `cdmon <word>` and tripped
  on PROSE in comments ("the cdmon repo", "your committed cdmon config" →
  `repo`/`config`). The honest check parses the YAML and collects only the actual
  script lines (GitLab top-level `script` lists + the shared `&cdmon-setup` anchor;
  GitHub `jobs.<id>.steps[].run` blocks — GitHub jobs are NESTED under `jobs:`,
  GitLab jobs are TOP-LEVEL), strips trailing `# …` comments, THEN regexes for
  `cdmon <token>` and checks it against `typer.main.get_command(app).commands.keys()`
  (the canonical click names — handles `name=`-overridden + function-derived like
  `new-doc`). Verified it bites: `check`→`verify` reds the test. Note GitHub's `on:`
  key parses to YAML boolean `True`, so iterate `doc.values()` defensively.
- **G — an example fixture under `examples/` is insulated from the dogfood + the
  pytest run for free.** `examples/external-repo/src/widget.py` is NOT scanned by
  the dogfood `cdmon.yaml` (which roots at `code_doc_monitor/`) and NOT collected by
  pytest (`testpaths = ["tests"]`), so adding it cannot perturb `cdmon coverage`,
  `cdmon check`, or test collection. Scaffold the fixture doc IN-SYNC with
  `cdmon new-doc <id> --config <fixture cfg>` (then drop a real purpose line —
  prose outside the managed region doesn't change the fingerprint), so the committed
  tree passes `check`+`lint` and the e2e test creates drift on a copy.

## H-02 — self-dogfood: documenting the engine's own modules + a hard coverage gate

**Scope the coverage scan BEFORE measuring — the denominator is the whole story.**
`cdmon coverage` defaults to `inventory.DEFAULT_INCLUDE = ("**/*.py",)` with only
dotfile/`__pycache__`/`.venv` excludes. On the repo itself that swept in `tests/`,
`examples/`, `alembic/`, and `dashboard/node_modules/`, ballooning the universe to
1106 public symbols and pinning the headline at 12.2%. None of those are the
*engine's* documentable surface. Adding a `coverage.include:
["code_doc_monitor/**/*.py"]` block scopes the metric to what the slice is actually
about (engine self-coverage), which baselined honestly at 42.2% (135/320). This is
a *scope* decision, not a waiver: out-of-scope trees leave the metric entirely;
waivers are for in-scope engine code that intentionally needs no doc and must
justify themselves.

**The documentation loop is genuinely mechanical (K2 pays off).** Per group of
modules: `cdmon new-doc <id>` writes a conformant scaffold (front matter + a
`> TODO` purpose line + a generated `CDM:BEGIN symbols` table) → add the
`DocumentSpec` + `code_refs` to `cdmon.yaml` → edit ONLY the one-line `>` purpose
→ `cdmon monitor --apply`. The apply does two things at once: heals each doc's
fingerprint after the prose edit, AND regenerates the `api-index` landing page —
because its region is `source: index`, the new docs appear in the index table
automatically (never hand-edit the index). 8 docs covered all 23 engine modules;
do NOT make one doc per module (group by EPIC/concern).

**What was waived and why (4 symbols, 3 files):** the package `__init__.py`
re-export aggregators — their only public symbols are `__all__` and `__version__`.
Every name they re-export is documented in its HOME module's doc, so the aggregator
itself is not a documentable surface. Waived with a reason each (not scoped out,
because they ARE engine files); a new test asserts every waiver carries a reason so
losslessness stays explicit. Result: 100.0% of scanned engine public symbols.

**Make the win durable or it rots.** Two locks: (1) the CI step flips from the
informational `cdmon coverage` to the hard `cdmon coverage --fail-under 95` (a
couple points below the achieved 100% for heal headroom); (2)
`tests/test_dogfood.py` resolves the real report the same way the CLI does
(`discover_files(include=cfg.coverage.include) → discover_symbols → resolve_coverage`)
and asserts `percent_public_symbols >= 95`. So a future slice that adds an engine
module without documenting it fails BOTH the local suite and CI — the
self-improvement can't silently regress. Note for H-01/H-03/H-04: the dogfood
config now owns the *entire* engine public surface, so ANY edit to a tracked module
drifts its `docs/api/*` doc — reheal (`cdmon monitor --apply --config cdmon.yaml`)
is now mandatory after touching essentially any `code_doc_monitor/**` file, not just
the handful previously documented.

## H-01/H-04 — telemetry view math + injected issue transport (+ document the new module)

**Telemetry is a COMPUTED view, not a stored schema.** Like `RepoStatus`/`RepoHealth`,
`RepoTelemetry`/`ShapeStat` are aggregates computed in `server/app.py` from the two
Store reads (`records_for` + `resolutions_for_repo`) — NOT parallel copies of a stored
shared model, so K6's "no DTOs for the SHARED schema" does not apply (the record/
resolution endpoints still return the shared schema). NO new Store method was needed;
SqlStore works unchanged because the view only calls the existing Protocol reads. The
shape key is `(drift_kind, audience)` — deliberately COARSER than promotion's
`(doc_id, drift_kind, audience)` so it surfaces which KIND of drift the backend handles
poorly across docs. `override_rate` counts FIRST-resolution-per-record OVERRIDDEN
(insertion order, mirroring `_compute_health`'s MTTR join) over the shape's record
count; a record with no resolution contributes 0. Worst-first ordering (K10) is a
single sort key `(-escalation_rate, -override_rate, drift_kind, audience)` — the
trailing `(drift_kind, audience)` is the deterministic tie-break. `promotion_candidates`
just REUSES the pure `detect_promotions` server-side (no re-implementation).

**Issue transport = `pr.py` mirrored, inject-the-leaf.** `issues.py` copies the
`pr.py`/`registry.py` pattern exactly: a frozen `IssuePlan`, an INJECTED
`IssueTransport` Protocol, GitLab + GitHub default transports each with a `from_env`
(loud `TransportError`/K8 on a missing var) and a stdlib-urllib `_Urllib*IssueHttp`
leaf whose real `urlopen` is the ONLY `# pragma: no cover` line. Tests drive a fake
transport for the payload/dry-run/no-op paths; the lazy-build + missing-env branches
are covered with the real POST stubbed (monkeypatch the leaf's `.request`). GitLab and
GitHub differ in three places worth noting: auth header (`PRIVATE-TOKEN` vs
`Authorization: Bearer`), URL (`/projects/<id>/issues` vs `/repos/<owner/repo>/issues`),
and label encoding (comma-joined string vs JSON list) — the plan stays
provider-agnostic; each `submit` adapts. `plan_coverage_issue` returns `None` on no
gaps so `open_coverage_issue` + the CLI are a clean no-op, and the body is deterministic
(gaps grouped under their A-07 suggested owner, owners sorted).

**A NEW engine module is itself a doc gap — document it in the SAME slice.** After H-02
the dogfood owns the entire engine public surface, so adding `issues.py` without adding
it to `cdmon.yaml` would have dropped doc self-coverage below the `--fail-under 95`
self-gate and failed `test_dogfood`. The fix is one `code_refs:` line in a FITTING
existing doc (here `pr-loop`, the natural home for the PR/issue transports) + a reheal
(`cdmon monitor --apply`). Order of operations that worked: code green → add module to
cdmon.yaml → reheal → `cdmon check`/`lint`/`coverage --fail-under 95` all exit 0 →
re-run the full suite (the reheal mutates `docs/api/*`, which `test_dogfood` checks).
For H-03: the regression corpus should include a "new undocumented engine module" case
— it's the most likely future self-gate regression.

## H-03 — regression corpus from lessons & known limitations (EPIC-2 capstone)

**A corpus is a curated INDEX of invariants, not a copy of the suite — reference
the existing seam, add only the genuine gap.** The temptation is to re-prove every
unit; the value is in one durable guard per *learned failure mode*. 21 of the 22
cases are thin re-assertions against the SAME engine seams the system/heal/drift/
schema/sinks/monitor tests already use (audience invalidation, heal idempotence,
human/llm-seeded lock, should_sync, schema back-compat, reporting-never-raises,
zero-backend-call rule, dogfood-in-sync). The ONE genuinely new guard is the H-01/
H-04 finding turned standing: an UNLISTED `code_doc_monitor/**` module's public
symbol must be detected as a gap AND drop self-coverage — no prior test pinned it,
and it is the single most likely future self-gate regression. → When asked for a
"corpus", curate the highest-value still-true invariants and ADD only where a lesson
had no guard; tag each case with its lesson id so a red points at the writeup.

**Auto-mark via `conftest.pytest_collection_modifyitems`, not 22 decorators.** A
package-local `conftest.py` that adds the `regression` marker to every item whose
nodeid is under `tests/regression/` keeps the corpus a pure drop-in (adding a file
enlists it) and makes `pytest -m regression` select EXACTLY the corpus while the
default suite still includes it (the cases live under `tests/`). Register the marker
in `pyproject` so `--strict`-style runs don't warn. Note: a command-line `-m
regression` OVERRIDES the addopts `-m "not live_llm and not pg"`, but the corpus
carries neither of those marks, so nothing leaks in.

**The "break-it" check found a redundancy, and that's a real finding.** Documenting
that a guard BITES (temporarily break the fix → corpus reds → revert) revealed that
the B-02 human-region guarantee is enforced by TWO layers: a `preserve` set computed
in `monitor.run` AND the modes-derived lock in `heal.locked_region_ids`. Clearing
ONLY `monitor`'s `preserve` did NOT red the human/llm-seeded guards — the
load-bearing guard is the heal-layer lock (`apply_fix` re-derives locked ids from
`modes`). So the break-it note in each docstring targets `heal.locked_region_ids`,
not the redundant monitor set. → A break-it check is not just confidence; it tells
you WHICH layer actually holds the invariant, so the guard's documentation points at
the right code.

**Match the corpus fixture's drift kind to the path under test (CDM-06 redux).** The
zero-backend-call [D-06] case needs EXACTLY ONE REGION drift so the spy count is
unambiguous; a docstring edit on the shared fixture raises HASH+REGION (the HASH
still hits the backend → `spy.calls == 1`). Reusing test_monitor's recipe — a
CORRECT fingerprint + a STALE region body — yields a single REGION drift the rule
can resolve cleanly. The llm-seeded FILL phase similarly needs an UNFILLED stub
(the shared `make_repo` pre-heals as `generated`), so reset the doc to `DOC_STUB`
before the fill. → When porting a system scenario into a focused corpus case,
re-derive the precise drift shape; don't assume the shared fixture produces it.

**No stale lessons.** Every invariant in `.project/LESSON_LEARNT.md` and
`.project/problems/*` that was a candidate guard is still TRUE; none were superseded.
The corpus is now the program's durable memory — `tests/regression/README.md` maps
each case to its lesson id, so the LESSON file and the executable guards stay linked.

**EPIC H + the whole EPIC-2 program are COMPLETE.** See the STATUS "EPIC H + EPIC-2
PROGRAM COMPLETE" section for the closing summary.

**[B-06] The whole-doc HASH heal already preserves no-renderer regions — verify
before "fixing".** The spec flagged the critical idempotence risk: a code change
raises BOTH a whole-doc HASH drift and the no-renderer `llm` REGION drift; if the
HASH fix (`heal._corrected`/`render_corrected`) blanked the prose region, the REGION
fix and the HASH fix would fight and `monitor --apply` would never converge. But
`_corrected` already SKIPS any region id `not in known` (`if region_id not in known:
continue`), so a no-renderer region's body is preserved byte-identical for free —
NO heal code change was needed. The right move was to PIN that with guard tests
(`test_render_corrected_preserves_no_renderer_llm_region`,
`..._whole_doc_never_blanks_llm_region`) rather than refactor. → When a spec says
"verify X; if broken, fix it", actually verify first; a guard test on
already-correct behavior is the deliverable, not a speculative rewrite.

**[B-06] A per-doc (fingerprint) staleness signal can't prove "loud after a
mechanical heal" — surface-without-apply does.** The B-06 design keys a no-renderer
`llm` region's staleness to the WHOLE-DOC fingerprint (`stored != current`), exactly
like the HASH drift. That means a purely mechanical `regenerate_regions` heal — which
refreshes the fingerprint — legitimately CLEARS the signal (the doc is "in sync" by
the only signal the engine has). So the "no authoring path still surfaces it" goal
can't be shown by running a fingerprint-refreshing heal and expecting the region to
still fire (it won't, by design). The honest, design-consistent proof is
`monitor.run(apply=False)`: with no auto-apply nothing authors the prose, the REGION
drift stays in `remaining` AND is recorded for a human (K5/K8) — loud, never silently
dropped. → When a freshness signal is shared with a coarser one (here the whole-doc
fingerprint), don't assert loudness through a path that closes the coarser signal;
assert it through detect/record, not through a heal that moves the very hash you key on.

**[P-01] An additive payload KEY (not a new hash) is how you add a fingerprint
tier without re-baselining stored fingerprints — and the body tier must skip
user-guide at the source, not the call site.** `surface_hash` already had the
discipline: the `records` key only enters the JSON payload when non-empty, so a
records-free surface hashes exactly as it did before records existed. The body
tier reuses that exactly — `body_hash` enters a symbol's entry ONLY when
`include_body` is on AND the symbol has one — so `include_body=False` (the
default) is byte-identical to the pre-P1 contract for EVERY audience, and every
previously-stored `cdm.fingerprint` stays valid. The user-guide invariant is
enforced inside `surface_hash` (`include_body_tier = include_body and audience is
not USER_GUIDE`), NOT by asking each caller to pass the right flag: a body change
is a non-event for the externally-visible API (K3), so even with the global flag
ON the user-guide bytes can never move. → When adding a sensitivity tier to a
hash, make it an additive payload key gated on "on AND present", and bake the
audience exclusion into the hashing function so no caller can violate it.

**[P-01] A fingerprint flag is a "one-shared-truth" value: every site that STAMPS
must use the same flag as the site that DETECTS, or `monitor --apply` never
converges.** `drift.detect` compares `stored` vs `surface_hash(include_body=cfg
flag)`. If heal/scaffold stamped the fingerprint with a DIFFERENT `include_body`,
the engine would re-detect its own freshly-healed doc as drifted — a permanent,
self-inflicted HASH drift (the same trap B-03 flagged for its lock predicate). So
the flag had to thread through ALL of: `drift.detect`, `heal._corrected`/
`render_corrected`/`regenerate_regions`, `layout.scaffold_doc`, `monitor` (record
hash + exemplar hash), and `backends.FixRequest.fingerprint_body_tier` (the
backend stamps the whole-doc fix). The e2e idempotence assertion (`run(apply=True)`
twice → second `handled == ()`) is the guard that proves stamp and detect agree. →
Thread a fingerprint-derivation flag to EVERY stamping site in one slice and pin
agreement with an idempotent-reheal test, never just the detect site.

**[P-01] Capture the golden hash BEFORE you touch the code.** The whole
byte-invariance claim ("OFF == today") rests on literal hash values. Computing
them from the pre-change tree and baking them into a regression test
(`test_surface_hash_golden_user_guide`/`_eng_guide`) turns "I think it's
identical" into an executable oracle that fails loudly if any future edit
accidentally moves the default payload. → For any "this change is byte-identical"
guarantee, snapshot the bytes from the OLD code first and assert the literal.

**[P-02] Make the new identity a SUPERSET that contains the old one, not a
replacement.** "Tiered fingerprint" sounds like it replaces the opaque hash — but
replacing the stored `cdm.fingerprint` bytes would invalidate every doc in every
adopter repo. Instead the `composite` digest IS the unchanged `surface_hash()`
(the P-01 golden literals still pass), and the per-tier digests are *additional*
diagnostics stored under a *separate* additive key (`cdm.fingerprint_tiers`). The
identity never moved; only new metadata appeared beside it. → When "restructuring"
a stored contract, keep the OLD value as one field of the NEW structure and assert
the golden still holds — a restructure that changes the identity bytes is a
migration, not an additive slice.

**[P-02] "Which tier moved" needs the OLD per-tier digests — there is no
shortcut.** The composite can't be decomposed back into tiers after the fact, and
you don't have the old code to re-extract. So the per-tier digests must be STAMPED
at heal time and read back at detect time — the same one-shared-truth threading as
P-01's flag, but now for a second key. An old doc predating the stamp legitimately
can't say which tier moved, so `drifted_tiers` falls back to `()` with the
composite-only message rather than guessing. → If a diagnostic compares "before vs
after", the "before" half has to be persisted when you author, not reconstructed
when you detect; design the absent-history fallback explicitly.

**[P-02] A `schema_version` minor bump is just an additive field PLUS the version
string — and the back-compat test is the version string left ALONE.** Bumping
`ReviewRecord` to `1.1.0` meant updating the two tests that assert the *default*
version, but the legacy-parse tests (which pin `"1.0.0"` in a hand-written JSONL
line) must NOT change — their whole point is that an OLD record keeps its own old
version and still validates with the new field defaulting. → When you bump a
version default, grep every `schema_version` assertion and split them: freshly-built
records assert the new version; legacy-fixture records keep the old one.
