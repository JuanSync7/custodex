# Breaking-change severity

*Pillar A — code↔doc drift.*

## What it is

Every code↔doc drift Custodex detects is **graded** by how it affects the public
surface:

| Severity | Meaning | Example |
| --- | --- | --- |
| **breaking** | a symbol was removed/renamed, **or** a surviving symbol's signature changed | `greet(name)` → `greet()` |
| **additive** | a new symbol was added; nothing existing changed | a new `farewell(name)` |
| **cosmetic** | only a docstring or implementation body moved | a reworded docstring |

The verdict rides on every `ReviewRecord` (the audit log) and is annotated inline
in `cdx check`, so a reviewer — and the central audit — can tell an API break from
a harmless prose update **at a glance**.

## Why it exists

"The docs drifted" isn't actionable on its own — a renamed public function and a
typo-fixed docstring both move the fingerprint, but they need very different
attention. Grading the drift turns a binary "stale" signal into a triage signal.

## How it works (and the subtle part)

Custodex already captured two structural signals per drift: which fingerprint
**tier** moved (signature / docstring / body) and the **anchor delta** (which
documented symbols were added or removed). Those classify most cases.

But they share a blind spot. **Adding a symbol also moves the signature tier** (the
set of signatures grew). So if one edit *both* adds a new symbol *and* changes an
existing symbol's signature, the aggregate signals can't tell that apart from a
plain addition — and the change was mislabeled **additive** when it was really
**breaking**.

The fix: Custodex now stores a **per-symbol signature digest** (`cdm.symbol_sigs`)
— a short hash of each documented symbol's `name/kind/signature/is_public`. On the
next drift it diffs the *surviving* symbols (present before and after); if any
survivor's signature digest moved, the change is **breaking**, even alongside an
addition. A pure addition leaves every survivor untouched, so it stays
**additive** — no false alarms.

Two properties worth knowing:

- **No re-baseline.** The digest is *not* part of the content hash, so your stored
  fingerprints stay valid — this was a fully additive change.
- **Graceful degrade.** A document last healed before this feature has no stored
  digests; it simply falls back to the older aggregate grading and never errors.
  Docs pick up the sharper grading lazily, the next time they're healed.

## How to use it

It's automatic — there's nothing to switch on.

```bash
cdx check
# … core-api: HASH [breaking] — surface drifted in signature tier(s) …
```

`cdx check` annotates each HASH drift with its severity; the same value is written
to `ReviewRecord.change_severity` and surfaced in the central audit. In CI, you can
read the severity off the record to decide whether a drift blocks a release.

## Advantages

- **Triage at a glance** — `[breaking]` vs `[additive]` vs `[cosmetic]` tells a
  reviewer how hard to look before they open the diff.
- **Catches the masked break** — the add-plus-in-place-signature-change case that
  the aggregate signals alone reported as a harmless addition.
- **Free and safe** — no schema change, no re-baseline, no new flags; old docs
  degrade gracefully.

## Limitations

- **Public surface only.** Severity grades the documented *signature* surface. A
  pure docstring or private-body change is `cosmetic` even if it's significant to a
  reader — that's a deliberate K3 choice for the externally-visible API.
- **Lazy rollout.** A doc gains the sharper grading only on its next heal; until
  then it uses the older aggregate grading (still correct, just less precise on the
  masked case).
- **It informs, it doesn't gate by itself.** Severity is a label on the record;
  wiring "breaking blocks the merge" is a policy you apply in CI.
