# sharepoint-mirror — govern SharePoint documents with cdx

The EPIC SP recipe: mirror a SharePoint library into your repo as
**deterministic text**, declare the mirrored files as managed docs, and the
unchanged engine does the rest — fingerprints, `depends_on` suspect-links,
staleness SLAs, ownership. When someone edits the spec *in SharePoint*, the
next sync flips every dependent doc SUSPECT and `cdx check` tells you exactly
which of your docs went stale because of it.

## The pieces

```
SharePoint library
      │  (Microsoft Graph; cert-authenticated app)
      ▼
rag-sharepoint-api / pull_sharepoint.py     ← auth + raw-byte mirror (exists)
      │  raw .docx/.md bytes on disk, or the proxy's REST endpoints
      ▼
cdx sp-sync                                  ← THIS: convert + governed mirror
      │  docs/sharepoint/**.md  (cdm: front matter preserved across syncs)
      ▼
config/cdmon declarations                    ← owner, audience, depends_on
      ▼
cdx monitor --apply  /  cdx check            ← baselines, SUSPECT_LINK gating
```

## Setup (once)

1. Copy `spmirror.yaml` to `<repo>/config/spmirror.yaml` and point it at your
   library mirror dir (`source: dir`) or a running rag-sharepoint-api
   (`source: proxy`).
2. `cdx sp-sync --repo-root .` — the mirror lands under `dest`
   (e.g. `docs/sharepoint/specs/Design.docx.md`). Commit it.
3. Declare each mirrored doc you want governed in `config/cdmon/<unit>.yaml`
   (this is the governance decision — a human makes it, K11):

   ```yaml
   documents:
     - id: sp-design
       path: docs/sharepoint/specs/Design.docx.md
       audience: user-guide
       owner: jane.doe            # who answers for it
     - id: my-guide
       path: docs/guide.md
       audience: eng-guide
       depends_on:
         - doc: sp-design         # my-guide goes SUSPECT when the spec moves
   ```

4. `cdx monitor --apply` — stamps fingerprints + edge baselines. `cdx check`
   is green.

## The loop (scheduled)

Run on a schedule (SharePoint edits happen outside git pushes — nightly is
the usual cadence; hourly if the docs are hot):

```yaml
# .gitlab-ci.yml — fires on a GitLab pipeline schedule (set cadence in the UI)
sp-sync:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
  script:
    - pip install custodex
    - python pull_sharepoint.py --dest /tmp/library   # or hit your proxy
    - cdx sp-sync --config config/spmirror.yaml --repo-root .
    - cdx check --config config/cdmon || echo "dependents went SUSPECT"
    # commit the moved mirror + open a review MR with your usual tooling;
    # a human resolves each edge: cdx resolve --edge <downstream> <upstream>
```

Semantics you can rely on:

- **Idempotent** (K7): unchanged upstream → `pulled 0`, zero bytes written,
  manifest byte-identical. Safe on any cadence.
- **Baseline-preserving**: the engine's `cdm:` front matter survives every
  re-sync — no spurious drift from the connector itself.
- **Churn-immune**: `docx-text` reads only `word/document.xml`; a Word
  re-save with unchanged words never moves a fingerprint.
- **Human-gated deletion** (K5): a file removed from SharePoint is reported
  as a stale candidate; its mirror (and governance record) stays until a
  human deletes it.
- **Loud** (K8): malformed config, non-UTF-8 "text", a DTD smuggled into a
  docx, an unreachable proxy — every one a typed error, never a silent skip.
