# RTE-02a — decorator fidelity: stop documenting a property as a callable method

**Epic:** RTE (the apply-tier router)
**Depends on:** RTE-01 (the router — which will correctly escalate the resulting drift)
**Constraints:** K0, K1, K2, K6, K9, K10

## Goal (validable)

Make the extracted surface tell the truth about decorated symbols, so the docs
generated FROM it stop being confidently wrong. Today `custodex/extract.py` never
inspects `decorator_list` (`grep -c decorator` = **0**), so `@property` renders as a
callable method, `@staticmethod` as a method with no `self`, and `@classmethod` with
`cls` exposed as a caller-supplied argument.

This is not hypothetical. `docs/api/coverage-system.md` — this repo's OWN
dogfood-generated documentation — documents five consecutive `@property` attributes
as callable methods. **No model was involved**: the projection was lossy before any
LLM saw it. That makes this slice the prerequisite the epic named — there is no
point widening what auto-applies while the thing being applied is wrong.

**Done when:**
- `Symbol` gains `decorators: tuple[str, ...] = ()` (additive, appended LAST,
  SOURCE order — decorator order is semantic, so sorting would destroy meaning).
- `_decorator_names` resolves plain (`@property`), dotted (`@functools.cache`) and
  call (`@app.command(...)` -> `app.command`) decorators; unresolvable forms are
  skipped rather than crashing (K8: never a silent WRONG value, but an exotic
  decorator must not break extraction of the whole file).
- `_func_signature` prefixes the decorators, so the symbol table cell reads
  `@property def net(self) -> int` and a reader writes `obj.net`.
- `kind` is NOT changed (see the ⟨R⟩ in ARCHITECTURE: `_symbols_for_ref` selects
  `arg_signature` refs on `kind in ("function","method")`, so promoting `property`
  to its own kind would silently drop every property from that selection).
- A regression test pins the exact defect: extracting a fixture with
  `@property`/`@staticmethod`/`@classmethod` yields signatures a reader cannot
  misread, and `docs/api/coverage-system.md` no longer documents a property as a
  plain method.
- Determinism (K10): the same source always yields the same decorator tuple.
- Full gate + the repo-wide dogfood reheal committed with the slice.

## Design

One choke point: every function/method Symbol is built by `_func_symbol`
(`extract.py:396`, exactly two call sites), so both the new field and the new
signature are added there.

### Expected (and intended) blast radius

`kind` + `signature` feed both the per-symbol digest (`sig_by_anchor`) and the
`signature` fingerprint tier, so **every eng-guide doc covering decorated code
drifts**. Under RTE-01 those grade `BREAKING` (a surviving symbol's signature
moved) and therefore route `NEEDS_INTENT` — which is correct, not a nuisance:
existing prose may well say `.net()`, and that prose is now false. This is the
router and the fidelity fix working together, and it is exactly why this slice
is separated from RTE-02b (fields) — so the reheal has ONE attributable cause.

## Scope discipline (deliberately NOT in this slice)

- Class / pydantic FIELDS entering the surface + coverage denominator — RTE-02b.
- The module docstring as a `module`-kind symbol — RTE-02b.
- Promoting `property` into `SymbolKind` (needs the `_symbols_for_ref` selector
  updated in the same slice) — RTE-02b.
- Feeding decorators/docstrings into the backend prompt — RTE-02c.
