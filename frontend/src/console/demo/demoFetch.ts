// A mock `fetch` that answers the console's API calls from the baked demo dataset
// (see ./demoData). The console's shared `ApiClient` does a LAZY `globalThis.fetch`
// lookup, so installing this (DemoConsole.tsx) makes the REAL console run with no
// backend — the static juansync.dev showcase. Reads return canned data; writes
// return a benign success so the UI never errors mid-flow.
import { applyFixResponse, syncRunGit } from "../test/fixtures";
import { DEMO } from "./demoData";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Known per-repo sub-paths, peeled off the tail so the leading repo_id (which may
// itself contain slashes — the server route is `{repo_id:path}`) is whatever remains.
const REPO_SUBS = [
  "status",
  "records",
  "resolutions",
  "coverage",
  "ownership",
  "staleness",
  "health",
  "documents",
  "doc-graph",
  "sync",
  "sync-state",
  "config/editable",
  "config/edits",
  "config/generate",
];

/** Build a `fetch` that serves the demo dataset and never touches the network. */
export function makeDemoFetch(): typeof fetch {
  const demoFetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const href =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const method = (
      init?.method ?? (input instanceof Request ? input.method : "GET")
    ).toUpperCase();
    const path = new URL(href, "http://demo.local").pathname;

    // ── global routes ───────────────────────────────────────────────────────
    if (path === "/health") return json(DEMO.health);
    if (path === "/repos") return json(DEMO.repos);
    if (path === "/config/templates") return json(DEMO.configTemplates);
    if (path === "/settings") return json(DEMO.serverSettings);
    if (path === "/openapi.json") {
      return json({
        openapi: "3.1.0",
        info: { title: "Custodex central server", version: "0.1.0" },
        paths: {},
      });
    }

    // ── per-repo routes: /repos/{repo_id}/{sub} ─────────────────────────────
    if (path.startsWith("/repos/")) {
      const rest = path.slice("/repos/".length);
      // apply-fix is the one deeper route (.../records/{id}/apply-fix).
      if (rest.endsWith("/apply-fix")) return json(applyFixResponse);
      // Longest sub first so `config/editable` wins over a bare `editable` tail.
      const sub = [...REPO_SUBS]
        .sort((a, b) => b.length - a.length)
        .find((s) => rest === s || rest.endsWith(`/${s}`));
      if (sub) {
        const repoId = decodeURIComponent(
          rest.slice(0, rest.length - sub.length).replace(/\/$/, ""),
        );
        const data = DEMO.byRepo(repoId);
        switch (sub) {
          case "status":
            return data.status ? json(data.status) : json({ detail: "unknown repo" }, 404);
          case "records":
            return json(data.records);
          case "resolutions":
            return method === "POST"
              ? json({ record_id: "demo-resolution" })
              : json(data.resolutions);
          case "coverage":
            return json(data.coverage);
          case "ownership":
            return json(data.ownership);
          case "staleness":
            return json(data.staleness);
          case "health":
            return json(data.health);
          case "documents":
            return json(data.documents);
          case "doc-graph":
            return json(data.docGraph);
          case "sync":
            return json(syncRunGit);
          case "sync-state":
            return json(null);
          case "config/editable":
            return json(data.editable);
          case "config/edits":
            return method === "POST"
              ? json({ edit_id: "demo-edit" })
              : json(data.configEdits);
          case "config/generate":
            return json(data.generate);
        }
      }
    }
    return json({ detail: `demo: no route for ${path}` }, 404);
  };
  return demoFetch as typeof fetch;
}
