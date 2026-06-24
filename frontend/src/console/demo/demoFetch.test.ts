import { describe, expect, it } from "vitest";
import { ApiClient } from "../api/client";
import { makeDemoFetch } from "./demoFetch";

// The demo fetch is what makes the static juansync.dev showcase work: the REAL
// ApiClient, pointed at this mock, must resolve every route the console calls from
// the baked dataset (no backend). These tests run the actual client against it.
const client = new ApiClient({ fetchImpl: makeDemoFetch() });

describe("demoFetch", () => {
  it("answers the liveness probe so the shell shows Online", async () => {
    expect(await client.ping()).toEqual({ status: "ok" });
  });

  it("lists the demo fleet", async () => {
    const repos = await client.listRepos();
    expect(repos.length).toBeGreaterThan(0);
    expect(repos.map((r) => r.repo.repo_id)).toContain("acme/widget");
  });

  it("serves the busy repo's full story (drift, coverage)", async () => {
    const status = await client.repoStatus("acme/widget");
    expect(status.total_records).toBeGreaterThan(0);
    expect((await client.recordsFor("acme/widget")).length).toBeGreaterThan(0);
    expect((await client.coverageFor("acme/widget")).length).toBeGreaterThan(0);
  });

  it("surfaces the orphaned doc (a departed DRI)", async () => {
    const own = await client.ownershipFor("acme/widget");
    expect(own.orphan_count).toBe(1);
    expect(own.findings[0].doc_id).toBe("core-api");
    expect(own.findings[0].status).toBe("orphan_dri_vacant");
  });

  it("surfaces stale + never-reviewed docs", async () => {
    const sla = await client.stalenessFor("acme/widget");
    expect(sla.stale_count).toBeGreaterThan(0);
    const statuses = sla.findings.map((f) => f.status);
    expect(statuses).toContain("stale");
    expect(statuses).toContain("never_reviewed");
  });

  it("shows the quiet repo as empty, not errored", async () => {
    expect(await client.recordsFor("octo/docs")).toEqual([]);
    expect((await client.ownershipFor("octo/docs")).orphan_count).toBe(0);
    expect((await client.stalenessFor("octo/docs")).stale_count).toBe(0);
  });

  it("serves the global settings + config templates", async () => {
    expect((await client.serverSettings()).settings.server.port).toBeGreaterThan(0);
    expect(await client.configTemplates()).toHaveProperty("index");
  });

  it("returns a benign success for write actions (read-only demo)", async () => {
    const res = await client.resolve(
      "acme/widget",
      // a minimal ResolutionRecord shape — the demo echoes a record id
      { record_id: "r1", resolution: "accepted" } as never,
      "",
    );
    expect(res).toHaveProperty("record_id");
  });

  it("404s an unknown route (the client surfaces an error state)", async () => {
    await expect(client.repoStatus("nope/nope")).rejects.toThrow();
  });
});
