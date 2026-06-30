# Transitive suspect advisory

*Pillar B — document↔document dependencies.*

## What it is

When you change a document that other documents depend on, Custodex flags the
**direct** dependents as *suspect* (their baseline of your doc no longer matches).
The **transitive suspect advisory** extends that view: it shows the *entire*
downstream chain that will eventually need re-confirming — the full blast radius —
as a read-only, non-gating advisory.

If `tutorial → guide → api-reference` (each depends on the next) and you edit
`api-reference`, then `guide` is **directly** suspect, and `tutorial` is
**transitively** suspect: it isn't broken *yet*, but it will need a look once
`guide` is updated.

## Why it exists

The pure [Doorstop](https://doorstop.readthedocs.io/) model is a *lazy wavefront*:
only the direct edge goes suspect, and the next hop only lights up after the
intermediate doc is itself re-confirmed. That's correct, but it hides the scope of
a change — you fix `guide`, and only *then* discover `tutorial` also needs work.
The advisory surfaces the whole closure **now**, so a reviewer can plan the full
sweep up front.

## How it works

- A pure function (`propagate_suspect`) walks the **reverse** of the `depends_on`
  graph from every directly-suspect document, cycle-safe and deterministic, and
  reports each reachable downstream as a `SUSPECT_TRANSITIVE` link.
- It is **HYBRID**: detection itself stays the strict direct wavefront. The
  transitive closure is *advisory only* — it never mints a drift record and never
  changes `cdx check`'s exit code.
- This is deliberate. A transitive edge has **no changed upstream body to stamp**,
  so an eager transitive *drift* would be impossible to clear deterministically —
  it would nag forever. Keeping it advisory sidesteps that entirely.

## How to use it

**CLI** — add `--transitive` to the dependency view:

```bash
cdx deps --transitive
```

It prints the directly-suspect edges, then a clearly-labelled
*"transitively suspect (pending wavefront; does NOT gate)"* section. `cdx check`
still exits non-zero **only** on the direct suspects.

**Opt-in monitor line** — set `docdeps.transitive: true` in config and
`cdx monitor` prints a one-line advisory summary (off by default).

**Central hub** — `GET /repos/{id}/doc-graph/reverse?doc=X&transitive=true`
returns the full reverse-reachable closure. This is **pure graph reachability**,
never a suspect verdict: the hub has the dependency graph, but the document bodies
needed to hash an upstream live in the repo, so suspect *status* stays repo-local.

## Advantages

- **See the whole blast radius up front** — plan a documentation sweep instead of
  discovering downstream work one hop at a time.
- **Zero risk to your gate** — advisory-only and off by default; it can never make
  CI red or mint an un-clearable record.
- **Deterministic & cycle-safe** — the same graph always yields the same closure,
  even with circular dependencies.

## Limitations

- **It does not gate.** By design, the transitive advisory will never fail
  `cdx check`. If you want a hard stop, the *direct* suspect link is the gate.
- **It's a forecast, not a verdict.** A transitively-suspect doc may turn out to
  need no change once its upstream is updated — it flags *potential* work.
- **Off by default.** The `cdx monitor` summary requires the `docdeps.transitive`
  knob; `cdx deps --transitive` is always available on demand.
