import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Worklist, { type WorklistApi } from "./Worklist";
import type { Worklist as WorklistData } from "../types";

const DATA: WorklistData = {
  owners: [
    {
      accountable: "alice",
      items: [
        {
          doc_id: "core-api",
          doc_path: "docs/api/core-api.md",
          audience: "eng-guide",
          reason: "orphan",
          severity: "high",
          detail: "owner `bob` departed; reassign a new DRI to clear",
          upstream_id: null,
        },
        {
          doc_id: "io-api",
          doc_path: "docs/api/io-api.md",
          audience: "eng-guide",
          reason: "stale",
          severity: "medium",
          detail: "reviewed 172 days ago; SLA is 90 days — re-review due",
          upstream_id: null,
        },
      ],
      item_count: 2,
      doc_count: 2,
    },
    {
      accountable: null,
      items: [
        {
          doc_id: "getting-started",
          doc_path: "docs/getting-started.md",
          audience: "user-guide",
          reason: "suspect",
          severity: "low",
          detail: "upstream io-api changed — re-check the dependency",
          upstream_id: "io-api",
        },
      ],
      item_count: 1,
      doc_count: 1,
    },
  ],
  item_count: 3,
  doc_count: 3,
  includes_suspect: false,
};

function fakeApi(overrides: Partial<WorklistApi> = {}): WorklistApi {
  return {
    worklistFor: async (): Promise<WorklistData> => DATA,
    ...overrides,
  };
}

function renderWorklist(api: WorklistApi, repoId = "acme/widget") {
  return render(
    <MemoryRouter>
      <Worklist api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("Worklist page", () => {
  it("renders the per-owner sections with their item + doc counts", async () => {
    renderWorklist(fakeApi());

    // The summary counts the items and distinct documents.
    expect(
      await screen.findByText(/3 item\(s\) across 3 document\(s\)/i),
    ).toBeInTheDocument();

    // The named owner heading is rendered with its counts.
    expect(screen.getByRole("heading", { name: "alice" })).toBeInTheDocument();
    expect(screen.getByText(/2 items · 2 docs/i)).toBeInTheDocument();

    // The unowned bucket renders as "Unowned" with a singular count.
    expect(screen.getByRole("heading", { name: /unowned/i })).toBeInTheDocument();
    expect(screen.getByText(/1 item · 1 doc/i)).toBeInTheDocument();
  });

  it("renders a severity chip and the reason for each item", async () => {
    renderWorklist(fakeApi());

    // The orphan row: a high-severity chip, the reason, the doc, the detail.
    const orphanRow = await screen.findByRole("row", { name: /core-api/ });
    expect(orphanRow).toHaveTextContent("high");
    expect(orphanRow).toHaveTextContent(/orphan/i);
    expect(orphanRow).toHaveTextContent(/owner `bob` departed/);

    // The stale row (io-api, "172 days ago"): medium severity, stale reason.
    // Matched by the distinctive detail text so it doesn't collide with the
    // suspect row (whose detail also names io-api).
    const staleRow = screen.getByRole("row", { name: /172 days ago/ });
    expect(staleRow).toHaveTextContent("io-api");
    expect(staleRow).toHaveTextContent("medium");
    expect(staleRow).toHaveTextContent(/stale/i);

    // The doc cell carries the full doc path as a hover title.
    expect(within(orphanRow).getByText("core-api")).toHaveAttribute(
      "title",
      "docs/api/core-api.md",
    );
  });

  it("renders the upstream id for a suspect item", async () => {
    renderWorklist(fakeApi());
    const suspectRow = await screen.findByRole("row", { name: /getting-started/ });
    expect(suspectRow).toHaveTextContent("low");
    expect(suspectRow).toHaveTextContent(/suspect/i);
    // The suspect item points at the changed upstream (→ io-api).
    expect(suspectRow).toHaveTextContent(/→\s*io-api/);
  });

  it("shows the hub banner explaining suspect items are repo-local when omitted", async () => {
    renderWorklist(fakeApi());
    const banner = await screen.findByText(/hub omits/i);
    expect(banner).toHaveTextContent(/repo-local/i);
    expect(banner).toHaveTextContent(/cdx worklist/);
  });

  it("does NOT show the omit-suspect banner when the view includes suspect items", async () => {
    renderWorklist(
      fakeApi({
        worklistFor: async () => ({ ...DATA, includes_suspect: true }),
      }),
    );
    // The owners still render...
    expect(await screen.findByRole("heading", { name: "alice" })).toBeInTheDocument();
    // ...but the repo-local omit banner is absent.
    expect(screen.queryByText(/hub omits/i)).not.toBeInTheDocument();
  });

  it("renders an all-clear empty state when nothing needs review", async () => {
    renderWorklist(
      fakeApi({
        worklistFor: async () => ({
          owners: [],
          item_count: 0,
          doc_count: 0,
          includes_suspect: false,
        }),
      }),
    );

    expect(await screen.findByText(/all clear/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<WorklistData>(() => {});
    renderWorklist(fakeApi({ worklistFor: () => never }));

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    renderWorklist(
      fakeApi({
        worklistFor: async () => {
          throw new Error("worklist boom");
        },
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load worklist/i);
    expect(alert).toHaveTextContent(/worklist boom/);
  });
});
