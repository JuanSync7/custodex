import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Suggestions, { type SuggestionsApi } from "./Suggestions";
import { ApiError } from "../api/client";
import type { SuggestionsData } from "../types";

const DATA: SuggestionsData = {
  repo_id: "acme/widget",
  include_closed: true,
  suggestions: [
    {
      key: "k-fix-drift-0001",
      kind: "fix_drift",
      doc_id: "core-api",
      target: "docs/api/core-api.md",
      detail: "1 drift(s) [HASH] — review and heal with `cdx monitor --apply`",
      evidence: ["HASH:signature moved"],
      severity: "high",
      status: "pending",
      source: "worker",
      recorded_at: "2026-06-20T09:00:00Z",
      updated_at: "2026-06-20T09:00:00Z",
    },
    {
      key: "k-doc-gap-00002",
      kind: "document_gap",
      doc_id: null,
      target: "symbol src/queue.py#drain_queue",
      detail: "mentioned by 2 doc(s), covered by none — `cdx write-doc src/queue.py`",
      evidence: ["2 mentioning doc(s)"],
      severity: "low",
      status: "pending",
      source: "worker",
      recorded_at: "2026-06-20T09:00:00Z",
      updated_at: "2026-06-20T09:00:00Z",
    },
    {
      key: "k-resolved-0003",
      kind: "resolve_edge",
      doc_id: "guide",
      target: "core-api",
      detail: "edge guide → core-api was suspect; the tick no longer reports it",
      evidence: [],
      severity: "medium",
      status: "resolved",
      source: "worker",
      recorded_at: "2026-06-18T09:00:00Z",
      updated_at: "2026-06-20T09:00:00Z",
    },
    {
      key: "k-dismissed-004",
      kind: "add_edge",
      doc_id: "guide",
      target: "io-api",
      detail: "shared_symbol evidence links guide → io-api",
      evidence: ["symbol src/io.py#read_frame"],
      severity: "low",
      status: "dismissed",
      source: "worker",
      recorded_at: "2026-06-15T09:00:00Z",
      updated_at: "2026-06-16T09:00:00Z",
    },
  ],
};

function fakeApi(overrides: Partial<SuggestionsApi> = {}): SuggestionsApi {
  return {
    suggestionsFor: async (): Promise<SuggestionsData> => DATA,
    dismissSuggestion: async (repoId, key) => ({
      repo_id: repoId,
      key,
      status: "dismissed",
    }),
    ...overrides,
  };
}

function renderPage(api: SuggestionsApi, repoId = "acme/widget") {
  return render(
    <MemoryRouter>
      <Suggestions api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("Suggestions page", () => {
  it("separates pending from the closed audit trail (the pinned contract)", async () => {
    renderPage(fakeApi());
    expect(
      await screen.findByText(/2 pending suggestion\(s\)/i),
    ).toBeInTheDocument();

    const pending = screen
      .getByRole("heading", { name: "Pending" })
      .closest(".panel") as HTMLElement;
    expect(within(pending).getByRole("row", { name: /core-api/ })).toHaveTextContent(
      "high",
    );
    expect(
      within(pending).getByRole("row", { name: /drain_queue/ }),
    ).toHaveTextContent(/cdx write-doc/);

    const closed = screen
      .getByRole("heading", { name: /closed \(audit trail\)/i })
      .closest(".panel") as HTMLElement;
    expect(within(closed).getByRole("row", { name: /guide → core-api/ })).toHaveTextContent(
      "resolved",
    );
    expect(within(closed).getByRole("row", { name: /io-api/ })).toHaveTextContent(
      "dismissed",
    );
    // Closed items never show in the pending table.
    expect(
      within(pending).queryByRole("row", { name: /io-api/ }),
    ).not.toBeInTheDocument();
  });

  it("dismisses a pending item and moves it to the closed section", async () => {
    const calls: string[] = [];
    renderPage(
      fakeApi({
        dismissSuggestion: async (repoId, key) => {
          calls.push(key);
          return { repo_id: repoId, key, status: "dismissed" };
        },
      }),
    );
    const pending = (
      await screen.findByRole("heading", { name: "Pending" })
    ).closest(".panel") as HTMLElement;
    const row = within(pending).getByRole("row", { name: /core-api/ });
    await userEvent.click(within(row).getByRole("button", { name: /dismiss/i }));
    expect(calls).toEqual(["k-fix-drift-0001"]);
    // The item leaves pending and shows as dismissed in the audit trail.
    expect(await screen.findByText(/1 pending suggestion\(s\)/i)).toBeInTheDocument();
    const closed = screen
      .getByRole("heading", { name: /closed \(audit trail\)/i })
      .closest(".panel") as HTMLElement;
    expect(
      within(closed).getByRole("row", { name: /fix_drift/ }),
    ).toHaveTextContent("dismissed");
  });

  it("reveals the token input on a 401 and retries with it", async () => {
    let sentToken = "";
    let attempts = 0;
    renderPage(
      fakeApi({
        dismissSuggestion: async (repoId, key, token) => {
          attempts += 1;
          if (!token) throw new ApiError(401, "auth required");
          sentToken = token;
          return { repo_id: repoId, key, status: "dismissed" };
        },
      }),
    );
    const pending = (
      await screen.findByRole("heading", { name: "Pending" })
    ).closest(".panel") as HTMLElement;
    const row = within(pending).getByRole("row", { name: /core-api/ });
    await userEvent.click(within(row).getByRole("button", { name: /dismiss/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/auth required/i);

    await userEvent.type(screen.getByLabelText(/repo token/i), "s3cret");
    await userEvent.click(within(row).getByRole("button", { name: /dismiss/i }));
    expect(await screen.findByText(/1 pending suggestion\(s\)/i)).toBeInTheDocument();
    expect(attempts).toBe(2);
    expect(sentToken).toBe("s3cret");
  });

  it("shows the empty state when the inbox has never had items", async () => {
    renderPage(
      fakeApi({
        suggestionsFor: async () => ({
          repo_id: "octo/docs",
          include_closed: true,
          suggestions: [],
        }),
      }),
      "octo/docs",
    );
    expect(await screen.findByText(/inbox is empty/i)).toBeInTheDocument();
    expect(screen.getByText(/cdx suggest/)).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    renderPage(
      fakeApi({
        suggestionsFor: async () => {
          throw new Error("boom");
        },
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/);
  });
});
