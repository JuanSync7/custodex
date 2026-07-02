# COMPETITORS.md — competitive landscape, head-to-head bake-off, and what to copy

> **Status:** living strategy doc. The "Measured scorecard" section (§8) was
> produced by **actually installing and running** the OSS competitors against
> Custodex on 2026-06-29 (see §4 for the verified environment). Re-run the
> scenarios in §6 to refresh it; the eventual goal is the committed harness in §7
> so this becomes a `--check`-guarded generated artifact like `cdx wiki`.
>
> Prior context lives in two memory notes: `registry-landscape-and-docdoc-gap`
> (the four pillars + persistence answer) and this evaluation.

## 1. Purpose & the four pillars

Custodex's value is the **fusion** of four pillars. Every competitor contests at
most one or two; none fuses all four. This doc maps who contests what, proves it
by running the runnable ones head-to-head, and turns the gaps into a concrete
improvement backlog.

| Pillar | What it means | Custodex today |
|---|---|---|
| **A — code↔doc drift** | Detect when a doc no longer matches a fingerprinted code surface | ✅ **have** (the engine core) |
| **B — doc↔doc mapping** | One doc *depends on* another; flag the downstream when the upstream changes ("suspect link") | ❌ **lack** — the open pillar |
| **C — ownership + review-SLA + staleness** | An accountable owner/DRI/team per doc; time-based staleness; departed-owner orphans | ✅ **have** (EPIC OWN + EPIC SLA) |
| **D — central config-as-truth hub** | A many-repo hub; in-repo config is truth, a rebuildable DB is the mirror | ✅ **have** (SqlStore mirror) |

## 2. The competitive landscape — five bands

1. **OSS requirements/traceability** (pillar B): **Doorstop**, **StrictDoc**, **OpenFastTrace**, Sphinx-needs.
2. **OSS catalog / IDP** (pillars C+D, architecture lessons): **Backstage**, **OpenMetadata**, **DataHub**, Amundsen.
3. **OSS doc-quality / code-doc-adjacent** (narrow features): **Griffe**, **interrogate**, **pydocstyle**, Vale, lychee, Spectral, markdownlint.
4. **Commercial SaaS docs** (pillar A + LLM-fix): Swimm, Mintlify, DeepDocs, GitBook, Archbee, Guru, Confluence Verified, Notion.
5. **Commercial ALM** (pillar B done deeply — *and* the cautionary tale): **Jama Connect**, Siemens Polarion, IBM DOORS Next, codebeamer.

## 3. Pillar-by-pillar competitor map

- **Pillar A** is the **only** pillar with a true *mechanism-level* OSS rival: **Griffe** (`griffe check` extracts signatures and diffs two git refs). But Griffe is code-to-code with **no doc awareness and no audience model**.
- **Pillar B** has OSS *traceability* rivals (**Doorstop** suspect-links, **StrictDoc** typed relations, **OFT** revision tracing) and a deep *commercial* implementation (ALM "suspect links"). This is the pillar Custodex must build.
- **Pillar C** (owner + review-SLA + staleness) has **no runnable OSS peer**. Closest are timer-based human-attestation tools (Guru/Confluence) and catalog ownership (Backstage owner-per-entity), but none grades a doc against a source of truth.
- **Pillar D** (config-as-truth + rebuildable DB mirror) is validated by Backstage/OpenMetadata/DataHub — they independently converged on Custodex's disk=truth/SQL=mirror, **relational not graph**.

## 4. Runnable head-to-head shortlist (verified in *this* environment)

Verified env (so a future runner doesn't re-discover it):
- **Use Python 3.11**, not the system `python3` (which is **3.6.8** — too old for strictdoc/pydantic-v2/fastapi). Venv built from `/usr/bin/python3.11` at `/tmp/cdx-competitor-eval/venv`.
- **PyPI is reachable**; `pip` HTTPS is *not* killed by Falcon/EDR (only `curl`/`wget` are at risk). No `curl`/`wget` were used.
- `java` is **OpenJDK 1.8** (OFT v4 needs **JRE 17+** → blocked); `node` is v24.15 (nvm); `docker` is podman 4.9.

| Tool | Version | Install | Status here | Maps to |
|---|---|---|---|---|
| **Doorstop** | 3.1 | `pip install doorstop` | ✅ **run** | Pillar B suspect-link |
| **StrictDoc** | 0.25.0 | `pip install strictdoc` | ✅ **run** (emits a real trace matrix) | Pillar B typed relations + A |
| **Griffe** | 2.1.0 | `pip install griffe` | ✅ **run** | Pillar A (`cdx check`) |
| **interrogate** | 1.7.0 | `pip install interrogate` | ✅ **run** | `cdx coverage` (docstring-presence analogue) |
| **pydocstyle** | 6.3.0 | `pip install pydocstyle` | ✅ **run** | `docstyle.py` / Layout Standard |
| OpenFastTrace | v4 | `java -jar oft.jar trace` | ⛔ blocked (Java 8 < JRE 17) | Pillar B defect taxonomy — design ref |
| Vale / lychee | — | Go/Rust binary | ⛔ blocked (binary download = EDR risk) | prose lint / broken-link — design ref |
| Backstage/OpenMetadata/DataHub | — | docker-compose / node | ⛔ heavy (not run) | Pillars C/D architecture — design ref |

## 5. The usability ("userability") rubric

Tedium-centered, because that is the Jama failure axis (§9). Quantitative
dimensions are measured mechanically; only soft ones need a judge.

| Dimension | Measures | Scored by |
|---|---|---|
| **Steps-to-first-signal** | Friction from empty repo → first useful result | count of manual steps + wall-seconds |
| **Manual-authoring index** *(THE Jama axis)* | Artifacts a human must hand-author/hand-link per unit of governance | count of authored links + docs + stamps (lower better) |
| **Upkeep per upstream change** | Manual steps to return to green after one edit (the "rot" tax) | steps to re-stamp/re-heal; re-run twice for idempotency |
| **Drift-detection depth** | Does it flag a target that *still resolves but changed*? | detected/missed + granularity (per-edge / per-doc / per-tier) |
| **LLM-assist delta** | Steps the LLM removes by turning *author* into *approve* | Δsteps & Δseconds, with vs without the LLM, same mutation |
| **Verdict auditability** | Does every handled change yield a record with drift **and** fix? | record exists + carries both (anti-rubber-stamp) |

## 6. Task scenarios (each runnable on a competitor *and* Custodex)

- **S1 — suspect link:** build a parent/child dependency, stamp it, edit the upstream, detect exactly the downstream edge, clear only that edge. *(Doorstop ↔ Custodex pillar B)*
- **S2 — code↔doc signature drift:** change a signature; confirm a comment-only/private change is *not* flagged for a user-guide. *(Griffe ↔ `cdx check`)*
- **S3 — coverage:** run a coverage gate; reconcile the two "covered" definitions. *(interrogate ↔ `cdx coverage`)*
- **S4 — rot/upkeep:** edit an upstream that still *resolves*; measure the upkeep tax. *(Doorstop ↔ `cdx monitor`)*
- **S5 — LLM delta:** same drift, but *author the fix* vs *approve an LLM diff*. *(Doorstop/StrictDoc ↔ `cdx monitor` mock)*
- **S6 — ownership/SLA:** detect a stale/orphaned doc and name the accountable human. *(no OSS peer ↔ `cdx ownership`/`cdx staleness`)*
- **S7 — config rules:** how much of Custodex's config validation is expressible as a generic ruleset? *(Spectral ↔ `cdx index --check`)*

## 7. The evaluation harness (proposed committed system)

Two layers, modelled on the existing `cdx wiki --check` generated-artifact pattern:

- **`scripts/competitor_eval/fixtures/`** — one canonical tiny target + a git-tracked `mutations/` set (`sig_change.patch`, `comment_only.patch`, `additive.patch`, `upstream_body.patch`). Every tool gets the **same** fixture + mutation so scores are comparable.
- **`scripts/competitor_eval/adapters/{doorstop,strictdoc,griffe,interrogate,custodex}.py`** — each exposes `setup() / apply_mutation(id) / run_scenario(id) -> Result`, where `Result` normalizes `{detected, manual_steps, authored_artifacts, exit_code, wall_seconds, audit_record, false_positives}`. Custodex's adapter shells the real `cdx` CLI against the project `.venv`; competitor adapters use the isolated py3.11 venv at `/tmp/cdx-competitor-eval/venv`.
- **`scripts/competitor_eval/run_eval.py`** — loops scenarios × tools, scores against §5, emits a committed `scorecard.json` (git-diffable across releases) and regenerates §8 of this doc. `run_eval.py --check` is a CI guard.
- **Workflow orchestrator** — provisions the venv, installs pinned tools, runs `run_eval.py`, and uses an LLM judge **only** for the soft dimensions (the quantitative ones are mechanical — same K1/K10 trust boundary as Custodex itself).
- **Cadence** — a non-blocking `.gitlab-ci.yml` job, monthly + pre-release.

*(This harness is designed but not yet committed — see §12 "Next steps".)*

## 8. Measured scorecard (real runs, 2026-06-29)

> Produced by running the tools, not by reading docs. `cdx` = project `.venv`;
> competitors = the py3.11 scratch venv (§4).

### S1 — doc↔doc suspect link · **Doorstop ✅ vs Custodex ❌ (not built)** *(STALE — see §13: EPIC B shipped the full Doorstop model + per-edge `cdx resolve --edge`, gating by default, PLUS transitive propagation (PROP-01) Doorstop lacks)*

Real Doorstop run: a parent `SRD001` and child `HLT001` (linked, reviewed → clean). The child stores **two separate fingerprints** — a per-edge hash of the parent inside `links:` *and* its own `reviewed:` stamp:

```
links:
- SRD001: YkocvNT7-kNZRhQeDHHKUGGH3v2btoTVcWt7O-FaFoE=   # hash of the PARENT at review time
reviewed: PKJ3gulAb9gKvjZG0kah8AmN1fBMvCob-NuztvZ05Us=   # hash of THIS item
```

Editing the upstream `SRD001` statement, then `doorstop` (validate):

```
WARNING: SRD: SRD001: unreviewed changes
WARNING: HLT: HLT001: suspect link: SRD001        <- exactly the downstream edge, nothing else
```

`doorstop clear HLT001 SRD001` re-stamps **only that edge** (link hash `YkocvNT7…` → `xtVzmB-h…`; the child's own `reviewed:` stamp is untouched). Idempotent on re-run.

- **Manual-authoring index:** ~9 hand steps to the first trace (2× create, 2× add, 2× author text, 1× link, 2× review).
- **Upkeep per change:** 2 steps (`review` parent + `clear` edge).
- **Usability gap found:** `doorstop` exits **0** on a suspect link — it's a non-gating `WARNING`. (`cdx check` exits **1** on drift.) → *copy-lesson: per-edge ack is great; make ours CI-gating.*
- **Custodex side:** ❌ no `depends_on`/`SUSPECT_LINK` exists. **This is the build target.** *(→ BUILT 2026-06: `docdeps.py` two-fingerprint model, `cdx deps`/`resolve --edge`, CI-gating by default — the §8 gap and the copy-lesson are both closed; §13 has the refreshed scorecard row.)*

### S2 — code↔doc drift · **Griffe vs `cdx check`**

`cdx check` on a mutated `widget.py` (kw-only param added to `widget_area` + new `widget_perimeter`):

```
2 drift(s) detected:
  api: HASH — fingerprint '636b0c04…' != current surface hash '43d7b398…'
  api [symbols]: REGION — managed region 'symbols' is out of date
check_rc=1            # gating
```

Griffe on the **same kinds of change** across git refs:

| Change | Griffe | `cdx check` |
|---|---|---|
| remove a required param | ✅ `widget_area(height): Parameter was removed` (rc 1) | ✅ HASH+REGION (rc 1) |
| **add** an optional param / new function | ⚠️ **silent (rc 0)** — additive is non-breaking | ✅ flagged — the doc must change |
| comment-only change | silent (rc 0) | suppressed for a *user-guide* (K3) |

**Verdict:** Griffe answers *"did my API break for code consumers?"* with a precise taxonomy but **no doc awareness, no audience model**, and is **silent on additive changes** — so a Griffe-guarded doc silently goes stale. `cdx check` answers *"is the doc still faithful to the surface, for this audience?"* — but its taxonomy is **coarse** (`HASH`/`REGION` vs "Parameter was removed"). → *copy-lesson: enrich `cdx check` with Griffe's breaking-change taxonomy.*

### S3 — coverage · **interrogate vs `cdx coverage`** (same fixture, both 100% — but measuring different things)

```
interrogate: widget.py 4/4 = 100%  RESULT: PASSED (min 80%)   # symbol HAS a docstring
cdx coverage: files 100% (1/1); public symbols 100% (4/4)     # symbol APPEARS in a managed doc
             documented 4 / undocumented 0 / waived 0
```

They diverge hard off this fixture: a module with perfect docstrings but **no managed doc** is interrogate-100% / `cdx`-0%. Custodex measures *external-doc faithfulness*, not *docstring presence*, and localizes gaps to an owner (pillar C). → *copy-lesson: reconcile the two "covered" numbers in positioning.*

### S5 — LLM-assist delta · **author vs approve**

`cdx monitor --apply` (mock backend, K4) on the S2 drift:

```
api: HASH -> FIX (applied)
api: REGION -> FIX
clean — no drift remaining
```

The `symbols` table **auto-regenerated** (including the additive `widget_perimeter`) and a **ReviewRecord** landed in `.cdmon/review-log.jsonl` carrying *both* the drift and the fix: `drift_kind=HASH`, old/new `surface_hash`, per-tier `fingerprint_tiers` (signature/docstring/composite), the full `new_doc_text`, a `rationale`, and a structured `DriftTicket` (severity, `affected_symbols`, `acceptance_criteria`). **K7 idempotency proven:** re-running `monitor` → "clean", doc md5 unchanged, log stayed at 2 records, empty git diff.

- **Authoring delta:** competitor path = human *hand-edits* the doc; Custodex path = human *approves one diff*. Custodex authors **0 links** (the surface is auto-extracted) vs Doorstop's hand-authored links.

### S6 — ownership + SLA · **`cdx ownership` / `cdx staleness`** (no OSS peer)

```
cdx ownership:  core-api [eng-guide] accountable=dana (owner=demo-team team=demo-team dri=dana)
cdx staleness:  core-api [stale] — reviewed 758 days ago; SLA is 90 days — re-review due
                io-api [never_reviewed] — never reviewed; SLA is 90 days
```

Doorstop offers only an unreviewed-changes stamp — **no owner, no SLA, no decay**. Pillar C has no runnable OSS competitor; this scenario documents the moat.

### Scorecard summary

| Pillar | Best OSS rival | Rival result (measured) | Custodex result (measured) |
|---|---|---|---|
| A code↔doc | Griffe 2.1 | precise breaking taxonomy; **silent on additive**; no doc/audience | HASH+REGION on *any* change; gating; audience-aware; coarse taxonomy |
| B doc↔doc | Doorstop 3.1 | ✅ exact suspect-link + per-edge clear; **non-gating (exit 0)** | ❌ **not implemented** |
| C ownership/SLA | *(none)* | Doorstop review-stamp only | ✅ `accountable=dana`; "758 days ago; SLA 90d" |
| D central hub | Backstage/OpenMetadata | git-as-truth + rebuildable Postgres index | ✅ SqlStore mirror (validated pattern) |
| LLM-delta | *(none)* | hand-author the fix | ✅ draft→approve + ReviewRecord; K7 idempotent |

## 9. Why Jama/ALM tools fail adoption — and where an LLM does (and does **not**) help

**Your "it's too tedious" thesis is right but incomplete — a B+.** It is the correct
*symptom*, not the whole disease.

**The tedium is real and #1 proximate** (high confidence): a Springer 2023 RE-survey
finds **77% of traceability is performed manually**; "traceability rot/decay" is a
named, studied phenomenon; practitioners hand-copy links; DOORS is called "the worst
software I've ever used" and is updated "only right before an audit." Remove the manual
labor and you remove the largest single barrier.

**But underneath it sit three organizational causes an LLM cannot touch** (high confidence):
1. **Cost/benefit asymmetry (the deepest):** "the people who experience the benefits are not the people who pay the costs." The maintainer ≠ the beneficiary.
2. **No enforced ownership:** "no single role" is responsible; "no manager who blames you" for skipping it. Where DOORS stuck, *compliance mandate* forced it.
3. **Intangible benefit under feature-velocity pressure:** engineers can't name the payoff; docs are "optional overhead."

Plus the well-worn secondary modes: steep learning curve + dedicated administrator;
value entirely dependent on initial setup; per-seat licensing that gates engineers out
and **forces a shadow Excel process**; heavyweight ALM vs agile cadence; and **compliance
theater** (links created after the fact only to pass an audit).

**Where the LLM bet genuinely wins (the tedium layer):** Custodex inverts authoring — the
surface is auto-extracted (the engineer authors *nothing*), drift is detected mechanically
on every commit, and the LLM drafts the fix-or-invalidate so the human's job shrinks from
**authoring** to **approving a diff**. That drives the maintainer's marginal cost toward
zero — which **collapses the cost side of the asymmetry**: if upkeep is ~free, it no longer
matters that maintainer ≠ beneficiary. Running in CI also **kills rot structurally** —
staleness surfaces per-commit, not at audit time.

**Where the LLM is irrelevant (and can backfire):**
- It lowers the cost of *producing* the artifact but cannot manufacture the *will* to value it. Cheap ≠ valued; where only velocity is rewarded, cheap docs stay unread.
- **Garbage-in:** code-as-truth certifies what the code *does*, never whether it's the *right* thing vs intent — and the highest-value requirements work is "human brain work."
- **Distrust of auto-content** is itself a failure mode: a wall of polished, under-reviewed diffs forks badly — engineers either **rubber-stamp** (destroying the audit value) or skim past (rot returns). Approval fatigue is real.

**What Custodex does that pure tooling/LLM can't** — it is architected at exactly these layers:
code is the single source of truth (K2, no parallel matrix to rot); detection is deterministic
& offline (K1/K10 — the LLM is *never* the source of truth, so it can't hallucinate a violation);
the LLM only *proposes*, and every verdict is an auditable **ReviewRecord** with drift **and** fix
(K5, the anti-rubber-stamp); **ownership + review-SLA are enforced and visible** (EPIC OWN/SLA —
the one thing that supplies the "no single role" accountability automation can't); it fails **loud
in CI** (K8, no silent rot to audit time); it's **free-at-point-of-use & CI-native** (no per-seat
shadow-Excel trap); and **audience-scoped verdicts (K3)** stop it crying wolf.

**Honest positioning limit:** Custodex removes the tedium and enforces upkeep, but it certifies
what the code *does*, not whether it's *right* vs intent. Don't oversell it as fixing requirements
quality — pair it with human approval + ownership so the will-to-document comes from accountability,
not the model.

## 10. What to copy to make Custodex more robust (prioritized)

| Pri | Lesson | From | Concrete Custodex change |
|---|---|---|---|
| **High** | Two-fingerprint doc↔doc model (item `reviewed:` stamp **separate** from a per-link hash of the upstream stored in the downstream) | Doorstop | new `custodex/docdeps.py`; `DocumentSpec.depends_on: list[DocEdge]`; `DriftKind.SUSPECT_LINK`; store upstream hash in the downstream's managed region (keeps detection pure, K1) |
| **High** | Per-edge human ack (`clear ITEM PARENT`) re-stamps one edge, not the whole doc | Doorstop | `cdx resolve --edge <down> <up>` form + ReviewRecord carries the upstream drift + verdict |
| **High** | One generic typed-edge table models the whole graph **without** a graph DB | OpenMetadata | add `doc_edges(from_id, type, to_id)` to SqlStore, both directions → O(1) reverse-lookup |
| **High** | Rebuildable index: replay disk→DB, `--clean` wipes stale rows | DataHub/Backstage | `cdx mirror rebuild [--clean]`; makes disk=truth/SQL=mirror an explicit, testable command |
| **High** | Verify → **decay** → re-verify *active* loop + one "Trust Score" + an **active nudge** | Guru/Confluence | `staleness.py` rolls up one Trust Score; add PR-comment/email nudge on SLA breach (the missing teeth is the *active reminder*, not the passive report) |
| Med | Suspect **propagates** along the graph → per-owner worklist + audited "cleared" verdict | DOORS/Jama/Polarion | `monitor.py` propagates `SUSPECT_LINK` transitively; `cdx review-center` worklist |
| Med | Named defect taxonomy (outdated/predated/orphaned/unwanted/ambiguous/uncovered) + `Needs:` required downstream types | OpenFastTrace | `DocEdgeStatus` enum in `cdx check`; let a doc declare required downstream coverage (reuse `cdx trace --fail-on-gap`) |
| Med | Typed/role-labelled edges (Refines/Implements/Verifies + auto reverse edge) | StrictDoc | `DocEdge.type`; auto-materialize the reverse edge; render a traceability matrix |
| Med | Grade change **severity** — silently auto-resync trivial deltas, escalate only structural breaks | Swimm | use `drifted_tiers`/anchors to auto-apply trivial surface deltas, reserve a ReviewRecord for structural breaks (cuts approval fatigue) |
| Med | Per-doc tunable re-verify cadence (volatile weekly, stable quarterly) | Archbee/OpsLevel | `DocumentSpec.review_interval` + a `criticality` field generalizing K3 |
| Med | Breaking-change taxonomy from signature diffs (param→kw-only, default removed, return changed) | **Griffe (measured §8)** | `drift.py`: add `breaking_change_kind` so `cdx check` says *what* broke, not just that the hash moved |
| Med | Anchor/fragment-level resolution + traversal cache | lychee | docdeps resolves edges at anchor/section granularity (reuse `blocks.py` region IDs); cache the doc-graph |
| Med | Portable rebuildable interchange export (federate without a central graph DB) | Sphinx-needs | `cdx export-graph` emits a per-repo doc/edge inventory the hub ingests |
| Med | Owner-as-Group fallback + orphan annotate-then-(optional)-sweep with `keep` override | Backstage | `ownership.py`: lint-warn on individual owners; mark-then-sweep with override |
| Low | Stable greppable rule IDs + JSON output + per-line suppression | markdownlint/Vale | `CDX-DRIFT-HASH`, `CDX-SUSPECT-LINK`; `--output json`; noqa-style suppression |
| Low | Markup-aware tokenizing (never lint prose inside code fences) | Vale | `docstyle.py` excludes fenced/inline code |

## 11. Low-confidence flags & maintenance notes

- **Pricing/trial terms are volatile** — Swimm/Cortex pages are now sales-gated; OpsLevel `/free-trial` 404s; Notion verification is Business/Enterprise-gated. Re-verify before quoting a tier.
- **Adoption-failure quotes** are anecdotal HN/PeerSpot/Medium (medium). The one high-confidence root-cause source is the **Springer 2023 RE-journal survey** (cost/benefit asymmetry I1, "no single role" I5, 77% manual).
- **Not executed here:** Spectral, markdownlint-cli2 ("likely", trivial npm; node present). OFT/Vale/lychee **blocked** (Java 8 / Go-Rust binary + EDR).
- **OFT license = GPL-3.0** (one search result wrongly said Apache-2.0; confirmed on GitHub + Maven).
- **Step-count / Δ numbers** in §8 are from single fixture runs — indicative, not benchmarks. The §7 harness will make them reproducible.
- **Pillar B "Custodex" columns are aspirational** until `docdeps` + `SUSPECT_LINK` + `doc_edges` ship.

## 12. Next steps

1. ~~**Build pillar B**~~ — ✅ **DONE** (EPIC B, branch `feat/pillar-b-docdeps`). Shipped the doc↔doc `depends_on` config field + typed `DocEdge`, `custodex/docdeps.py` (the pure suspect-link core mirroring `ownership.py`), the Doorstop two-fingerprint model (`cdm.upstream_hashes` per-edge baseline vs the doc's own `cdm.fingerprint`), `DriftKind.SUSPECT_LINK` through `cdx check`, `cdx deps` / `cdx deps --suggest` (link inference = the low-tedium authoring aid) / `cdx resolve --edge` (the per-edge `clear`), the configurable `docdeps.gate`, and Monitor handling (ESCALATE, never auto-edit; baseline new edges on `--apply`). Dogfooded on the demo (`getting-started depends_on io-api`), 6 catalogued FEAT-DOCDEPS-001..006 + DEMO-082..087, full gate green. **Deferred:** the central-server `doc_edges` mirror table + a frontend "Dependencies" view (a clean additive slice on the green base — B-07).
2. **Adopt the §10 mid-priority lessons** opportunistically (Griffe breaking-change taxonomy on a HASH drift, active staleness nudge + Trust Score, `cdx mirror rebuild --clean`).
3. **Commit the §7 harness** so this bake-off re-runs every release and §8 becomes a `--check`-guarded generated artifact.

## Appendix — per-tool teardown

- **Doorstop** (LGPL-3.0, Python, `pip`): git-native requirements tree; one YAML file per item; two-fingerprint suspect-links; per-edge `clear`. *Sharpest copy: the two-fingerprint model + per-edge ack.* Non-gating exit code.
- **StrictDoc** (Apache-2.0, Python+Rust, `pip`): `.sdoc` plaintext; typed role-labelled relations (Refines/Implements/Verifies + REVERSE_ROLE); tree-sitter source-marker parsing; MID-stable two-revision diff; self-contained `strictdoc server` web UI editing disk-truth. Verified to emit a real REQ-2→REQ-1 trace matrix. *Sharpest copy: typed edges + tree-sitter markers.*
- **OpenFastTrace** (GPL-3.0, Java, jar): `artifact~name~rev` tags, `Covers:`/`Needs:`/`Depends:`; named defect taxonomy; CI exit code. *Sharpest copy: the defect taxonomy.* Blocked here (JRE 17).
- **Griffe** (ISC, Python, `pip`): `griffe check` extracts signatures and diffs git refs; precise breaking-change taxonomy; silent on additive; no doc/audience. *Sharpest copy: breaking-change taxonomy.*
- **interrogate / pydocstyle** (Python, `pip`): docstring presence % gate / PEP-257 style. *Sharpest copy: `--fail-under` ergonomics; pydocstyle's absorption into Ruff = the lesson that standalone doc linters get consolidated → be invokable from a meta-runner.*
- **Backstage / OpenMetadata / DataHub** (Apache-2.0): catalog with git-as-truth + rebuildable relational index; owner-per-entity; typed-edge relationships **without** a graph DB. *Sharpest copy: the rebuildable-mirror pattern + the one typed-edge table; proof that relational beats graph.*
- **Commercial ALM (Jama/Polarion/DOORS/codebeamer)**: deep suspect-link + baselines + approval workflow — the **reference design** for pillar B *and* the cautionary tale (per-seat + heavyweight setup = shelfware). Sales-gated; not trialable for a quick bake-off.

## 13. 2026-07-02 re-verification — the landscape moved; so did Custodex

> Produced by a 4-agent web-research pass (traceability refresh + AI-doc-agent
> landscape + knowledge-graph design survey + onboarding-agent patterns) plus a
> fresh-eyes adoption simulation run against THIS working tree. §8's measured
> scorecard predates EPIC B/PROP/DIG/WL — this section supersedes its verdict
> rows.

### 13.1 What Custodex shipped since §8 (2026-06-29 → 2026-07-01)

| §8/§10 gap | Now |
|---|---|
| Pillar B "not built" | ✅ **BUILT + gating**: `docdeps.py` (Doorstop two-fingerprint, body-only upstream hash), `cdx deps`/`deps --suggest`/`deps --impact`/`resolve --edge`, `DriftKind.SUSPECT_LINK` gates `cdx check` (the exact non-gating exit-0 flaw we measured in Doorstop, fixed) |
| "Suspect propagates → per-owner worklist" (§10 Med) | ✅ PROP-01 (`SUSPECT_TRANSITIVE` advisory, never gates) + WL-01 (`cdx worklist`, per-owner join of orphan/stale/suspect, hub route omits suspect per K2) |
| "Griffe breaking-change taxonomy" (§10 Med) | ✅ DIG-01: per-symbol signature digests (`cdm.symbol_sigs`) → `Drift.sigs_changed` + BREAKING/ADDITIVE/COSMETIC severity — closes the masked add+in-place-signature case |
| Typed edges (§10 Med) | ✅ `DocEdgeType` {depends, refines, implements, verifies} (roles informational) |

**Four-pillar fusion claim: SURVIVES, restated precisely.** As of 2026-07-02 no
tool grades prose docs against an *extracted code surface* AND runs doc↔doc
suspect links, ownership/review-SLAs, and a multi-repo hub. Nearest: Jama
(3 pillars, requirements-world truth, heavyweight ALM); DataHub ("Continuous
Context" manifesto — *names our category* for data assets, blog-stage).

### 13.2 New threats (ranked)

1. **Dosu (dosu.dev)** — the one to watch. Auto-maintains in-repo docs (incl.
   AGENTS.md/CLAUDE.md), tracks doc↔doc relationships automatically, and
   **remembers reviewer rejections across runs** (their headline). 200k+
   engineers claimed. Missing: determinism, audit records, ownership/SLA. One
   ownership feature away from the governance quadrant.
2. **Fiberplane Drift (OSS)** — a deterministic doc-drift *linter* (tree-sitter
   AST fingerprints, frontmatter anchors, exit-1 CI, explicitly anti-LLM).
   Publicly validates our K1/K10 stance AND commoditizes the detection pillar
   alone. Detection-only, single-repo, no fix/audit/ownership/hub.
3. **Driver AI** — compiler-grade deterministic code DAG + scoped incremental
   re-derivation, sold as agent-context infrastructure. If it ever lets humans
   pin prose against the DAG and *grades* it, it leapfrogs with a stronger
   extraction engine. Enterprise-priced, closed.
4. **Jama 2606 / Polarion 2606 / IBM ELM AI Hub** — "AI suspect-link triage" is
   now a shipped ALM marketing category; Jama shipped the first ALM MCP server.
5. **Platform absorption** — Rovo Dev ($20/dev), Copilot agents, Amazon Q
   `/doc`: good-enough doc-updating bundled where teams already pay.
6. **Swimm VACATED the space** (pivoted to COBOL/mainframe modernization) — the
   historical pillar-1 leader leaving is a market gift; its lesson: pure
   doc-sync didn't sustain a company; the money moved to **governed context for
   AI agents**. Frame the four-pillar fusion as agent-context infrastructure.

### 13.3 Table-stakes gap

**MCP.** In H1-2026 Jama, Polarion (Copilot API), GitBook, ubCode, OpenMetadata,
Swimm and Dosu all shipped agent-context endpoints. Custodex's deterministic
reads (drift, ownership, staleness, doc-graph, ReviewRecords) are ideal MCP
material and none is exposed. → roadmap follow-on after EPIC AGT.

### 13.4 Usability, measured (fresh-eyes adoption sim, this tree, 2026-07-02)

Bare 2-module repo → first green `cdx check`: **5 commands + ONE hand-written
YAML edit**; drift→heal loop: 3 commands, K7-idempotent live; K1/K3/K5/K10 all
held empirically. **Verdict: alpha-ready for Python repos** with an engineer
willing to hand-author ~30 lines of YAML; NOT yet 10-minute adoption. The gap
is authoring/discovery, not correctness: (1) zero code↔doc mapping discovery
(the config is 100% hand-authored placeholders), (2) `init --v2` scaffold is
DOA in a bare repo (doc-style references writing templates only this repo
ships), (3) the adopt-an-existing-doc dance (config → `lint --fix` →
`monitor --apply`) is undocumented, (4) README quickstart buried/CI-oriented,
(5) `.cdmon/` commit-vs-ignore guidance absent.

### 13.5 The response — EPIC AGT (designed 2026-07-02)

Every winner in 13.2 is install-and-go; Custodex demands hand-authored config —
and every LLM-maintenance rival is auditless. EPIC AGT attacks the first
WITHOUT surrendering the second (new **K11: agents suggest; humans apply**):
deterministic entity/mention layer (`entities.py`, LazyGraphRAG split — LLM
never builds the index), entity-grounded edge suggestions + `cdx link`
(`docmap.py`), a unified knowledge-graph artifact + hub snapshot (`kgraph.py`),
the onboarding config-author (`cdx onboard`, Renovate-PR anatomy, Mintlify
arrive-green rule — kills gap 13.4-1/2), the doc-writer (`cdx write-doc`), and
two background suggesters (pure ticks, default-OFF loops, dedup + dismiss —
the Dosu-style continuous layer WITH the audit spine Dosu lacks). Positioning
line: *the only tool that can prove its docs are right, not just claim it
fixed them.*
