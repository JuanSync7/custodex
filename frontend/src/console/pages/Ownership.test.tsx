import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Ownership, { type OwnershipApi } from "./Ownership";
import type { OwnershipData } from "../types";

const DATA: OwnershipData = {
  owners: [
    {
      doc_id: "core-api",
      doc_path: "docs/api/core-api.md",
      audience: "eng-guide",
      owner: "demo-team",
      team: "demo-team",
      dri: "dana",
      accountable: "dana",
      durable: "demo-team",
    },
    {
      doc_id: "io-api",
      doc_path: "docs/api/io-api.md",
      audience: "eng-guide",
      owner: null,
      team: null,
      dri: null,
      accountable: "demo-team",
      durable: "demo-team",
    },
  ],
  findings: [
    {
      doc_id: "core-api",
      doc_path: "docs/api/core-api.md",
      audience: "eng-guide",
      status: "orphan_dri_vacant",
      detail: "DRI 'dana' departed; durable owner 'demo-team' still active",
      accountable: "dana",
      owner: "demo-team",
      team: "demo-team",
      dri: "dana",
    },
  ],
  orphan_count: 1,
};

function fakeApi(overrides: Partial<OwnershipApi> = {}): OwnershipApi {
  return {
    ownershipFor: async (): Promise<OwnershipData> => DATA,
    ...overrides,
  };
}

function renderOwnership(api: OwnershipApi, repoId = "demo-taskflow") {
  return render(
    <MemoryRouter>
      <Ownership api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("Ownership page", () => {
  it("lists documents with their accountable owner", async () => {
    renderOwnership(fakeApi());
    expect(await screen.findByText("core-api")).toBeInTheDocument();
    expect(screen.getByText("io-api")).toBeInTheDocument();
    // core-api's accountable identity (its DRI) is shown.
    expect(screen.getAllByText("dana").length).toBeGreaterThan(0);
  });

  it("shows an orphan banner + status when an owner has departed", async () => {
    renderOwnership(fakeApi());
    expect(await screen.findByText(/need a new owner/i)).toBeInTheDocument();
    expect(screen.getByText(/orphan dri vacant/i)).toBeInTheDocument();
  });

  it("marks the departed accountable owner and surfaces the reason to AT", async () => {
    renderOwnership(fakeApi());
    // The orphan row's accountable (the departed DRI) gets a visible "departed"
    // badge instead of reading as a normal active owner...
    expect(await screen.findByText("departed")).toBeInTheDocument();
    // ...and the human-readable reason is in the DOM (sr-only) for screen readers,
    // not trapped solely in a non-interactive title tooltip.
    expect(screen.getByText(/DRI 'dana' departed/)).toBeInTheDocument();
  });

  it("shows a clean banner when there are no orphans", async () => {
    renderOwnership(
      fakeApi({
        ownershipFor: async () => ({ ...DATA, findings: [], orphan_count: 0 }),
      }),
    );
    expect(
      await screen.findByText(/active accountable owner/i),
    ).toBeInTheDocument();
  });

  it("renders an empty state when no ownership is recorded", async () => {
    renderOwnership(
      fakeApi({
        ownershipFor: async () => ({ owners: [], findings: [], orphan_count: 0 }),
      }),
    );
    expect(
      await screen.findByText(/no ownership recorded yet/i),
    ).toBeInTheDocument();
  });
});
