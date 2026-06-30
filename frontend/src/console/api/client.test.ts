import { describe, it, expect } from "vitest";
import { ApiClient, ApiError } from "./client";
import type { ConfigEdit } from "../types";
import {
  applyFixResponse,
  configTemplates,
  editableTree,
  generateResponse,
  repos,
  statuses,
  storedConfigEdits,
  syncRunGit,
} from "../test/fixtures";

interface Captured {
  url: string;
  init?: RequestInit;
}

/** A fake `fetch` that records the request and returns a canned JSON body. */
function fakeFetch(
  body: unknown,
  { ok = true, status = 200 }: { ok?: boolean; status?: number } = {},
): { fetchImpl: typeof fetch; calls: Captured[] } {
  const calls: Captured[] = [];
  const fetchImpl = (async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    calls.push({ url: String(input), init });
    return {
      ok,
      status,
      json: async () => body,
    } as Response;
  }) as typeof fetch;
  return { fetchImpl, calls };
}

describe("ApiClient", () => {
  it("builds GET /repos against the default base url", async () => {
    const { fetchImpl, calls } = fakeFetch(repos);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.listRepos();

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/repos");
    expect(calls[0].init?.method).toBe("GET");
    expect(result).toEqual(repos);
  });

  it("builds GET /repos/{id}/status and preserves slashes in the repo id", async () => {
    const { fetchImpl, calls } = fakeFetch(statuses["acme/widget"]);
    const client = new ApiClient({
      baseUrl: "https://server.example/api",
      fetchImpl,
    });

    const result = await client.repoStatus("acme/widget");

    expect(calls[0].url).toBe(
      "https://server.example/api/repos/acme/widget/status",
    );
    expect(result.total_records).toBe(7);
  });

  it("url-encodes unsafe characters in a path segment but not the slash", async () => {
    const { fetchImpl, calls } = fakeFetch(statuses["acme/widget"]);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.repoStatus("org name/a b");

    expect(calls[0].url).toBe("/api/repos/org%20name/a%20b/status");
  });

  it("strips a trailing slash from the base url", async () => {
    const { fetchImpl, calls } = fakeFetch(repos);
    const client = new ApiClient({ baseUrl: "/api/", fetchImpl });

    await client.listRepos();

    expect(calls[0].url).toBe("/api/repos");
  });

  it("throws ApiError with status + url on a non-2xx response", async () => {
    const { fetchImpl } = fakeFetch(
      { detail: "boom" },
      { ok: false, status: 404 },
    );
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await expect(client.listRepos()).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      url: "/api/repos",
    });
    await expect(client.listRepos()).rejects.toBeInstanceOf(ApiError);
  });

  it("builds GET /records with no query string when no filters are given", async () => {
    const { fetchImpl, calls } = fakeFetch([]);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.recordsFor("acme/widget");

    expect(calls[0].url).toBe("/api/repos/acme/widget/records");
  });

  it("maps record filters to query params (dropping empties)", async () => {
    const { fetchImpl, calls } = fakeFetch([]);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.recordsFor("acme/widget", {
      verdict: "ESCALATE",
      drift_kind: "",
      audience: "eng-guide",
      doc_id: undefined,
      limit: 10,
      offset: 0,
    });

    const url = new URL(calls[0].url, "http://x");
    expect(url.pathname).toBe("/api/repos/acme/widget/records");
    expect(url.searchParams.get("verdict")).toBe("ESCALATE");
    expect(url.searchParams.get("audience")).toBe("eng-guide");
    expect(url.searchParams.get("limit")).toBe("10");
    // empty/undefined values are dropped, not sent as "":
    expect(url.searchParams.has("drift_kind")).toBe(false);
    expect(url.searchParams.has("doc_id")).toBe(false);
    // offset 0 is a real value and is sent:
    expect(url.searchParams.get("offset")).toBe("0");
  });

  it("builds GET /resolutions for a repo", async () => {
    const { fetchImpl, calls } = fakeFetch([]);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.resolutionsFor("acme/widget");

    expect(calls[0].url).toBe("/api/repos/acme/widget/resolutions");
  });

  it("builds GET /coverage for a repo", async () => {
    const { fetchImpl, calls } = fakeFetch([]);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.coverageFor("acme/widget");

    expect(calls[0].url).toBe("/api/repos/acme/widget/coverage");
  });

  it("builds GET /health for a repo", async () => {
    const { fetchImpl, calls } = fakeFetch({ repo_id: "acme/widget" });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.healthFor("acme/widget");

    expect(calls[0].url).toBe("/api/repos/acme/widget/health");
    expect(calls[0].init?.method).toBe("GET");
  });

  it("builds GET /worklist for a repo (WL-01; slash-preserving id)", async () => {
    const { fetchImpl, calls } = fakeFetch({
      owners: [],
      item_count: 0,
      doc_count: 0,
      includes_suspect: false,
    });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.worklistFor("acme/widget");

    expect(calls[0].url).toBe("/api/repos/acme/widget/worklist");
    expect(calls[0].init?.method).toBe("GET");
    // Reads are OPEN — no Authorization header is sent.
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(result.includes_suspect).toBe(false);
  });

  it("builds GET /documents with the sync_kind param (default git)", async () => {
    const { fetchImpl, calls } = fakeFetch([]);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.documentsFor("acme/widget");

    // W-03 fix: the repo_id is slash-preserving (matches the other methods).
    expect(calls[0].url).toBe(
      "/api/repos/acme/widget/documents?sync_kind=git",
    );
    expect(calls[0].init?.method).toBe("GET");
  });

  it("builds GET /documents encoding the repo id and the sync_kind=local param", async () => {
    const { fetchImpl, calls } = fakeFetch([]);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.documentsFor("a/b", "local");

    expect(calls[0].url).toBe("/api/repos/a/b/documents?sync_kind=local");
  });

  it("builds GET /config/templates (global, no repo, no auth)", async () => {
    const { fetchImpl, calls } = fakeFetch(configTemplates);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.configTemplates();

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/config/templates");
    expect(calls[0].init?.method).toBe("GET");
    // Reads are OPEN — no Authorization header is sent.
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(result).toEqual(configTemplates);
  });

  it("POSTs a resolution with the bearer token and JSON body (F-04 write)", async () => {
    const { fetchImpl, calls } = fakeFetch({ record_id: "rec-fix-2" });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const rec = {
      schema_version: "1.0.0",
      record_id: "rec-fix-2",
      resolution: "accepted" as const,
      resolved_text: null,
      resolved_by: "alice",
      resolved_at: "2026-06-05T01:00:00Z",
      note: null,
    };
    const result = await client.resolve("acme/widget", rec, "s3cret");

    expect(calls[0].url).toBe("/api/repos/acme/widget/resolutions");
    expect(calls[0].init?.method).toBe("POST");
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer s3cret");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual(rec);
    expect(result).toEqual({ record_id: "rec-fix-2" });
  });

  it("throws ApiError on a non-2xx resolve (e.g. 403 wrong token)", async () => {
    const { fetchImpl } = fakeFetch(
      { detail: "invalid bearer token" },
      { ok: false, status: 403 },
    );
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await expect(
      client.resolve(
        "acme/widget",
        {
          schema_version: "1.0.0",
          record_id: "rec-fix-2",
          resolution: "accepted",
          resolved_at: "2026-06-05T01:00:00Z",
        },
        "wrong",
      ),
    ).rejects.toMatchObject({ name: "ApiError", status: 403 });
  });

  it("POSTs a sync with the mode body + bearer token (W-03 write)", async () => {
    const { fetchImpl, calls } = fakeFetch(syncRunGit, { status: 201 });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.syncRepo("acme/widget", "git", "s3cret");

    expect(calls[0].url).toBe("/api/repos/acme/widget/sync");
    expect(calls[0].init?.method).toBe("POST");
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer s3cret");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ mode: "git" });
    expect(result).toEqual(syncRunGit);
  });

  it("POSTs a sync with mode=local", async () => {
    const { fetchImpl, calls } = fakeFetch(syncRunGit, { status: 201 });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.syncRepo("a/b", "local", "tok");

    expect(calls[0].url).toBe("/api/repos/a/b/sync");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ mode: "local" });
  });

  it("POSTs a sync with NO Authorization header when the token is empty (L-01 open repo)", async () => {
    const { fetchImpl, calls } = fakeFetch(syncRunGit, { status: 201 });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.syncRepo("acme/widget", "local", "");

    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ mode: "local" });
  });

  it("throws ApiError on a non-2xx sync (e.g. 403 wrong token)", async () => {
    const { fetchImpl } = fakeFetch(
      { detail: "invalid bearer token" },
      { ok: false, status: 403 },
    );
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await expect(
      client.syncRepo("acme/widget", "git", "wrong"),
    ).rejects.toMatchObject({ name: "ApiError", status: 403 });
  });

  it("builds GET /sync-state with no param when sync_kind is omitted", async () => {
    const { fetchImpl, calls } = fakeFetch(syncRunGit);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.syncState("acme/widget");

    expect(calls[0].url).toBe("/api/repos/acme/widget/sync-state");
    expect(calls[0].init?.method).toBe("GET");
    // Reads are OPEN — no Authorization header is sent.
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(result).toEqual(syncRunGit);
  });

  it("builds GET /sync-state with the sync_kind param when given", async () => {
    const { fetchImpl, calls } = fakeFetch(syncRunGit);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.syncState("acme/widget", "local");

    expect(calls[0].url).toBe(
      "/api/repos/acme/widget/sync-state?sync_kind=local",
    );
  });

  it("returns null from sync-state for a never-synced repo", async () => {
    const { fetchImpl } = fakeFetch(null);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.syncState("octo/docs");

    expect(result).toBeNull();
  });

  // ── EDITOR (E-08): editable tree + staged edits + generate/apply-fix ───────

  it("builds GET /config/editable with no param when sync_kind is omitted (OPEN read)", async () => {
    const { fetchImpl, calls } = fakeFetch(editableTree);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.configEditable("acme/widget");

    expect(calls[0].url).toBe("/api/repos/acme/widget/config/editable");
    expect(calls[0].init?.method).toBe("GET");
    // Reads are OPEN — no Authorization header is sent.
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(result).toEqual(editableTree);
    // The document's context_refs ride on the embedded ConfigDocument (E-03).
    expect(result.documents[0].document.context_refs[0].path).toBe(
      "docs/api/core-api.md",
    );
  });

  it("builds GET /config/editable with the sync_kind param + slash-preserving id", async () => {
    const { fetchImpl, calls } = fakeFetch(editableTree);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.configEditable("a/b", "local");

    expect(calls[0].url).toBe("/api/repos/a/b/config/editable?sync_kind=local");
  });

  it("POSTs a config edit with the bearer token + JSON body (E-05 write)", async () => {
    const { fetchImpl, calls } = fakeFetch({ edit_id: "edit-001" }, { status: 201 });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const edit: ConfigEdit = {
      action: "add_code_ref",
      unit: "core",
      doc_id: "guide/getting-started",
      ref: { path: "src/taskflow/core/engine.py", symbols: ["Engine"] },
    };
    const result = await client.stageConfigEdit("acme/widget", edit, "s3cret");

    expect(calls[0].url).toBe("/api/repos/acme/widget/config/edits");
    expect(calls[0].init?.method).toBe("POST");
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer s3cret");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual(edit);
    expect(result).toEqual({ edit_id: "edit-001" });
  });

  it("POSTs a config edit with NO Authorization header for an OPEN repo (empty token)", async () => {
    const { fetchImpl, calls } = fakeFetch({ edit_id: "edit-x" }, { status: 201 });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.stageConfigEdit(
      "octo/docs",
      { action: "remove_code_ref", unit: "core", doc_id: "d", path: "src/a.py" },
      "",
    );

    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("throws ApiError on a non-2xx stageConfigEdit (e.g. 422 bad action)", async () => {
    const { fetchImpl } = fakeFetch(
      { detail: "bad action" },
      { ok: false, status: 422 },
    );
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await expect(
      client.stageConfigEdit(
        "acme/widget",
        { action: "remove_code_ref", unit: "core", doc_id: "d", path: "src/a.py" },
        "tok",
      ),
    ).rejects.toMatchObject({ name: "ApiError", status: 422 });
  });

  it("builds GET /config/edits with no query when status is omitted (OPEN read)", async () => {
    const { fetchImpl, calls } = fakeFetch(storedConfigEdits);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.listConfigEdits("acme/widget");

    expect(calls[0].url).toBe("/api/repos/acme/widget/config/edits");
    expect(calls[0].init?.method).toBe("GET");
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(result).toEqual(storedConfigEdits);
  });

  it("builds GET /config/edits with the status filter param", async () => {
    const { fetchImpl, calls } = fakeFetch([]);
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.listConfigEdits("a/b", "pending");

    expect(calls[0].url).toBe("/api/repos/a/b/config/edits?status=pending");
  });

  it("POSTs config/generate with edit_ids + bearer token (E-06 write)", async () => {
    const { fetchImpl, calls } = fakeFetch(generateResponse, { status: 201 });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.generateConfig(
      "acme/widget",
      { edit_ids: ["edit-001"], mode: "local" },
      "s3cret",
    );

    expect(calls[0].url).toBe("/api/repos/acme/widget/config/generate");
    expect(calls[0].init?.method).toBe("POST");
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer s3cret");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      edit_ids: ["edit-001"],
      mode: "local",
    });
    expect(result).toEqual(generateResponse);
  });

  it("POSTs config/generate with an empty body (apply all pending edits)", async () => {
    const { fetchImpl, calls } = fakeFetch(generateResponse, { status: 201 });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await client.generateConfig("acme/widget", {}, "tok");

    expect(JSON.parse(String(calls[0].init?.body))).toEqual({});
  });

  it("POSTs apply-fix with an empty body + bearer token, encoding the record id (E-07)", async () => {
    const { fetchImpl, calls } = fakeFetch(applyFixResponse, { status: 201 });
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    const result = await client.applyRecordFix(
      "acme/widget",
      "rec fix/1",
      "s3cret",
    );

    // The record id is encoded with the slash-preserving helper (space → %20).
    expect(calls[0].url).toBe(
      "/api/repos/acme/widget/records/rec%20fix/1/apply-fix",
    );
    expect(calls[0].init?.method).toBe("POST");
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer s3cret");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({});
    expect(result).toEqual(applyFixResponse);
  });

  it("throws ApiError on a non-2xx apply-fix (e.g. 409 central-only repo)", async () => {
    const { fetchImpl } = fakeFetch(
      { detail: "repo has no local_path" },
      { ok: false, status: 409 },
    );
    const client = new ApiClient({ baseUrl: "/api", fetchImpl });

    await expect(
      client.applyRecordFix("acme/widget", "rec-1", "tok"),
    ).rejects.toMatchObject({ name: "ApiError", status: 409 });
  });
});
