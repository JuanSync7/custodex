import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RepoDetail, { type RepoDetailApi } from "./RepoDetail";
import { ApiError, type RecordFilters } from "../api/client";
import type {
  ApplyFixResponse,
  ResolutionRecord,
  ReviewRecord,
  SyncRun,
} from "../types";
import {
  applyFixResponse,
  readmeRecord,
  records,
  resolutions,
  syncRunGit,
} from "../test/fixtures";

interface RecordCall {
  repoId: string;
  filters?: RecordFilters;
}

interface ResolveCall {
  repoId: string;
  rec: ResolutionRecord;
  token: string;
}

interface ApplyFixCall {
  repoId: string;
  recordId: string;
  token: string;
}

/** A fake client that captures recordsFor() + resolve() + applyRecordFix() calls. */
function fakeApi(overrides: Partial<RepoDetailApi> = {}) {
  const calls: RecordCall[] = [];
  const resolveCalls: ResolveCall[] = [];
  const applyFixCalls: ApplyFixCall[] = [];
  const api: RepoDetailApi = {
    recordsFor: async (
      repoId: string,
      filters?: RecordFilters,
    ): Promise<ReviewRecord[]> => {
      calls.push({ repoId, filters });
      return records;
    },
    resolutionsFor: async (): Promise<ResolutionRecord[]> => resolutions,
    resolve: async (
      repoId: string,
      rec: ResolutionRecord,
      token: string,
    ): Promise<{ record_id: string }> => {
      resolveCalls.push({ repoId, rec, token });
      return { record_id: rec.record_id };
    },
    applyRecordFix: async (
      repoId: string,
      recordId: string,
      token: string,
    ): Promise<ApplyFixResponse> => {
      applyFixCalls.push({ repoId, recordId, token });
      return applyFixResponse;
    },
    // Stubbed so the mounted <SyncControls> never hits the network.
    syncState: async (): Promise<SyncRun | null> => syncRunGit,
    syncRepo: async (): Promise<SyncRun> => syncRunGit,
    ...overrides,
  };
  return { api, calls, resolveCalls, applyFixCalls };
}

function renderDetail(api: RepoDetailApi, repoId = "acme/widget") {
  return render(
    <MemoryRouter>
      <RepoDetail api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("RepoDetail page", () => {
  it("renders records as a timeline with doc, drift kind, verdict and source", async () => {
    const { api } = fakeApi();
    renderDetail(api);

    expect(await screen.findByText("guide/install")).toBeInTheDocument();
    expect(screen.getByText("eng/architecture")).toBeInTheDocument();

    const escalateRow = screen.getByRole("row", { name: /guide\/install/ });
    expect(escalateRow).toHaveTextContent("signature_changed");
    expect(escalateRow).toHaveTextContent("ESCALATE");
    expect(escalateRow).toHaveTextContent("sha-aaa");
  });

  it("shows a resolution badge for a resolved record and unresolved otherwise", async () => {
    const { api } = fakeApi();
    renderDetail(api);

    // rec-fix-2 has an `accepted` resolution; rec-escalate-1 has none.
    const resolvedRow = await screen.findByRole("row", {
      name: /eng\/architecture/,
    });
    expect(resolvedRow).toHaveTextContent("accepted");

    const unresolvedRow = screen.getByRole("row", { name: /guide\/install/ });
    expect(unresolvedRow).toHaveTextContent("unresolved");
  });

  it("re-queries with the right params when a filter changes", async () => {
    const { api, calls } = fakeApi();
    renderDetail(api);

    await screen.findByText("guide/install");
    expect(calls).toHaveLength(1);
    expect(calls[0].repoId).toBe("acme/widget");
    expect(calls[0].filters?.verdict).toBeUndefined();

    fireEvent.change(screen.getByLabelText("Verdict"), {
      target: { value: "ESCALATE" },
    });

    await waitFor(() => expect(calls.length).toBeGreaterThan(1));
    const last = calls[calls.length - 1];
    expect(last.filters?.verdict).toBe("ESCALATE");
    expect(last.repoId).toBe("acme/widget");
  });

  it("re-queries with the audience filter param", async () => {
    const { api, calls } = fakeApi();
    renderDetail(api);

    await screen.findByText("guide/install");
    fireEvent.change(screen.getByLabelText("Audience"), {
      target: { value: "eng-guide" },
    });

    await waitFor(() =>
      expect(calls[calls.length - 1].filters?.audience).toBe("eng-guide"),
    );
  });

  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<ReviewRecord[]>(() => {});
    // Hold the mounted <SyncControls> in loading too so no post-assert update fires.
    const { api } = fakeApi({
      recordsFor: () => never,
      syncState: () => new Promise(() => {}),
    });
    renderDetail(api);

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    const { api } = fakeApi({
      recordsFor: async () => {
        throw new Error("records boom");
      },
    });
    renderDetail(api);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load records/i);
    expect(alert).toHaveTextContent(/records boom/);
  });

  it("shows an empty state when no records match", async () => {
    const { api } = fakeApi({ recordsFor: async () => [] });
    renderDetail(api);

    expect(
      await screen.findByText(/no records match these filters/i),
    ).toBeInTheDocument();
  });

  // ── F-04: the resolve write control ───────────────────────────────────────

  it("POSTs a resolution with the chosen resolution, note and token", async () => {
    const { api, resolveCalls } = fakeApi();
    renderDetail(api);

    // rec-escalate-1 is unresolved, so it gets a resolve form.
    const unresolvedRow = await screen.findByRole("row", {
      name: /guide\/install/,
    });

    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "s3cret" },
    });
    fireEvent.change(within(unresolvedRow).getByLabelText("Resolution"), {
      target: { value: "invalidated" },
    });
    fireEvent.change(within(unresolvedRow).getByLabelText("Note"), {
      target: { value: "not a real drift" },
    });
    fireEvent.click(within(unresolvedRow).getByRole("button", { name: /validate/i }));

    await waitFor(() => expect(resolveCalls).toHaveLength(1));
    const call = resolveCalls[0];
    expect(call.repoId).toBe("acme/widget");
    expect(call.token).toBe("s3cret");
    expect(call.rec.record_id).toBe("rec-escalate-1");
    expect(call.rec.resolution).toBe("invalidated");
    expect(call.rec.note).toBe("not a real drift");
    expect(typeof call.rec.resolved_at).toBe("string");
  });

  it("reflects the new resolution badge on success", async () => {
    const { api } = fakeApi();
    renderDetail(api);

    const unresolvedRow = await screen.findByRole("row", {
      name: /guide\/install/,
    });
    expect(unresolvedRow).toHaveTextContent("unresolved");

    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "s3cret" },
    });
    fireEvent.change(within(unresolvedRow).getByLabelText("Resolution"), {
      target: { value: "accepted" },
    });
    fireEvent.click(within(unresolvedRow).getByRole("button", { name: /validate/i }));

    const updatedRow = await screen.findByRole("row", { name: /guide\/install/ });
    await waitFor(() => expect(updatedRow).toHaveTextContent("accepted"));
  });

  it("blocks the POST with a friendly validation when the token is missing", async () => {
    const { api, resolveCalls } = fakeApi();
    renderDetail(api);

    const unresolvedRow = await screen.findByRole("row", {
      name: /guide\/install/,
    });
    fireEvent.click(within(unresolvedRow).getByRole("button", { name: /validate/i }));

    // A friendly inline message, NOT a crash, and the client is never called.
    expect(await screen.findByText(/token is required/i)).toBeInTheDocument();
    expect(resolveCalls).toHaveLength(0);
  });

  it("surfaces an error when the resolve POST rejects", async () => {
    const { api } = fakeApi({
      resolve: async () => {
        throw new Error("invalid bearer token");
      },
    });
    renderDetail(api);

    const unresolvedRow = await screen.findByRole("row", {
      name: /guide\/install/,
    });
    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "wrong" },
    });
    fireEvent.click(within(unresolvedRow).getByRole("button", { name: /validate/i }));

    expect(await screen.findByText(/invalid bearer token/i)).toBeInTheDocument();
  });

  // ── T-03: the expandable DriftTicket card ─────────────────────────────────

  it("relabels the resolve submit to Validate", async () => {
    const { api } = fakeApi();
    renderDetail(api);

    const unresolvedRow = await screen.findByRole("row", {
      name: /guide\/install/,
    });
    expect(
      within(unresolvedRow).getByRole("button", { name: /validate/i }),
    ).toBeInTheDocument();
  });

  it("expands a record with a ticket to reveal the ticket card", async () => {
    const { api } = fakeApi();
    renderDetail(api);

    await screen.findByText("guide/install");
    const toggle = screen.getByRole("button", { name: /view ticket/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    // Title, severity chip, status badge.
    expect(
      screen.getByText("[HIGH] signature_changed in guide/install"),
    ).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText(/awaiting review/i)).toBeInTheDocument();
    // Sections (cause appears in summary + root cause → use getAllByText).
    expect(
      screen.getAllByText(/the doc never mentions the new flag/i).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/needs a human author/i)).toBeInTheDocument();
    expect(screen.getByText(/escalate to a human author/i)).toBeInTheDocument();
    // Affected symbols (mono chips).
    expect(screen.getByText("install")).toBeInTheDocument();
    expect(screen.getByText("uninstall")).toBeInTheDocument();
    // diff pre.
    expect(screen.getByText(/install\(path, force=False\)/)).toBeInTheDocument();
    // Acceptance checklist items.
    expect(
      screen.getByText(/a human has authored the missing\/owned content/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/the new content is in sync with the code surface/i),
    ).toBeInTheDocument();

    // Collapsing hides it again.
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByText("[HIGH] signature_changed in guide/install"),
    ).not.toBeInTheDocument();
  });

  it("can resolve from inside the expanded ticket panel", async () => {
    const { api, resolveCalls } = fakeApi();
    renderDetail(api);

    await screen.findByText("guide/install");
    fireEvent.click(screen.getByRole("button", { name: /view ticket/i }));

    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "s3cret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));

    await waitFor(() => expect(resolveCalls).toHaveLength(1));
    expect(resolveCalls[0].rec.record_id).toBe("rec-escalate-1");
  });

  // ── E-11: the apply-fix (LLM) button ─────────────────────────────────────

  it("shows the Apply fix (LLM) button only for a FIX record with a fix", async () => {
    const { api } = fakeApi();
    renderDetail(api);

    // rec-fix-2 is a FIX record WITH a fix → expand its details to reveal the button.
    await screen.findByText("eng/architecture");
    fireEvent.click(screen.getByRole("button", { name: /view details/i }));
    expect(
      screen.getByRole("button", { name: /apply fix \(llm\)/i }),
    ).toBeInTheDocument();

    // rec-escalate-1 is an ESCALATE record (fix:null) → expanding its ticket
    // shows no apply-fix button.
    fireEvent.click(screen.getByRole("button", { name: /view ticket/i }));
    const ticketRow = screen
      .getByText("[HIGH] signature_changed in guide/install")
      .closest("tr") as HTMLElement;
    expect(
      within(ticketRow).queryByRole("button", { name: /apply fix \(llm\)/i }),
    ).not.toBeInTheDocument();
  });

  it("does NOT show the button for a FIX record that carries no fix", async () => {
    const fixless: ReviewRecord[] = [
      { ...records[1], record_id: "rec-fixless", fix: null },
    ];
    const { api } = fakeApi({
      recordsFor: async () => fixless,
      resolutionsFor: async () => [],
    });
    renderDetail(api);

    await screen.findByText("eng/architecture");
    fireEvent.click(screen.getByRole("button", { name: /view details/i }));
    expect(
      screen.queryByRole("button", { name: /apply fix \(llm\)/i }),
    ).not.toBeInTheDocument();
  });

  it("applies the fix with the repo id, record id and token, shows the diff and re-fetches", async () => {
    const { api, calls, applyFixCalls } = fakeApi();
    renderDetail(api);

    await screen.findByText("eng/architecture");
    expect(calls).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "s3cret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /view details/i }));
    fireEvent.click(screen.getByRole("button", { name: /apply fix \(llm\)/i }));

    await waitFor(() => expect(applyFixCalls).toHaveLength(1));
    expect(applyFixCalls[0].repoId).toBe("acme/widget");
    expect(applyFixCalls[0].recordId).toBe("rec-fix-2");
    expect(applyFixCalls[0].token).toBe("s3cret");

    // The returned diff is shown (in the collapsible <details>).
    expect(await screen.findByText(/applied to/i)).toBeInTheDocument();
    expect(screen.getByText(/\+new/)).toBeInTheDocument();

    // Records are re-fetched so the timeline reflects the healed state.
    await waitFor(() => expect(calls.length).toBeGreaterThan(1));
  });

  it("shows a no-change affordance when applied is false", async () => {
    const { api } = fakeApi({
      applyRecordFix: async (): Promise<ApplyFixResponse> => ({
        ...applyFixResponse,
        applied: false,
        diff: "",
      }),
    });
    renderDetail(api);

    await screen.findByText("eng/architecture");
    fireEvent.click(screen.getByRole("button", { name: /view details/i }));
    fireEvent.click(screen.getByRole("button", { name: /apply fix \(llm\)/i }));

    expect(await screen.findByText(/no change/i)).toBeInTheDocument();
  });

  it("reveals an auth message when apply-fix returns 401", async () => {
    const { api } = fakeApi({
      applyRecordFix: async () => {
        throw new ApiError(401, "/repos/acme/widget/records/rec-fix-2/apply-fix");
      },
    });
    renderDetail(api);

    await screen.findByText("eng/architecture");
    fireEvent.click(screen.getByRole("button", { name: /view details/i }));
    fireEvent.click(screen.getByRole("button", { name: /apply fix \(llm\)/i }));

    expect(await screen.findByText(/auth required/i)).toBeInTheDocument();
    // The page's existing token input is present (reused, not a second field).
    expect(screen.getByLabelText("Token")).toBeInTheDocument();
  });

  it("shows the legacy cause/rationale fallback when a record has no ticket", async () => {
    const { api } = fakeApi();
    renderDetail(api);

    // rec-fix-2 has no ticket; its row is resolved (accepted) so no toggle row.
    await screen.findByText("eng/architecture");
    const toggle = screen.getByRole("button", { name: /view details/i });
    fireEvent.click(toggle);

    // Legacy fallback shows the record's cause + the fix rationale.
    expect(screen.getByText(/stale import path in the doc/i)).toBeInTheDocument();
    expect(screen.getByText(/update the import path/i)).toBeInTheDocument();
    // No ticket title is rendered.
    expect(screen.queryByText(/HIGH\] signature_changed/)).not.toBeInTheDocument();
  });

  it("lists README drift in a separate 'README files' section", async () => {
    const { api } = fakeApi({
      recordsFor: async () => [...records, readmeRecord],
    });
    renderDetail(api);

    // Engineering records render in the main timeline…
    await screen.findByRole("row", { name: /guide\/install/ });
    // …and the README record under its OWN "README files" section.
    const heading = screen.getByRole("heading", { name: /readme files/i });
    const section = heading.closest("div")!;
    const readmeRow = within(section).getByRole("row", { name: /readme/i });
    expect(readmeRow).toHaveTextContent("README.md");
    expect(readmeRow).toHaveTextContent("signature_changed");
  });
});
