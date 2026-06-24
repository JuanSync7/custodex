# external-repo — a cdx adopter example

A small, self-contained stand-in for *some other team's repo* that ADOPTS
custodex. Unlike the dogfood (cdx monitoring its own source) or the
multilang golden example (extraction across five languages), this example proves
the **whole adopter loop**: client config -> heal -> report -> central server
stores -> query.

Layout:

```
external-repo/
  src/widget.py     a tiny public library (the "code")
  docs/api.md       an eng-guide doc with a managed `symbols` region (the "doc")
  cdmon.yaml        maps widget.py -> api.md, with a `central:` http block
```

The committed tree is in sync (`cdx check` exits 0, `cdx lint` exits 0).

The e2e test `tests/system/test_example_external.py` copies this tree under `tmp_path`,
adds a public function to `src/widget.py` (so `cdx check` now reports drift),
heals it with `cdx monitor --apply`, then registers the repo and reports the
healed records to an **in-process central server** (FastAPI `TestClient`) — wiring
`HttpSink`'s injected client to the TestClient — with a bearer token (E-06). It
asserts `GET /repos` and `GET /repos/{id}/records` show the repo + records, and
that a WRONG token is rejected. Everything runs offline (K4): no socket, no LLM.

To adopt cdx in your own repo, copy a workflow from `templates/ci/` and run
`cdx init --central <url> --repo-id <id>` to scaffold a config like this one.
