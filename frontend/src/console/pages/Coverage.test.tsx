import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Coverage, { type CoverageApi } from "./Coverage";
import type { CoverageSnapshot } from "../types";
import { coverage, coverageNoFiles } from "../test/fixtures";

function fakeApi(overrides: Partial<CoverageApi> = {}): CoverageApi {
  return {
    coverageFor: async (): Promise<CoverageSnapshot[]> => coverage,
    ...overrides,
  };
}

function renderCoverage(api: CoverageApi, repoId = "acme/widget") {
  return render(
    <MemoryRouter>
      <Coverage api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("Coverage page", () => {
  it("renders the latest snapshot's % and the three baskets", async () => {
    renderCoverage(fakeApi());

    // latest snapshot is ratio 0.82 → 82%, documented 9, undocumented 1, waived 1
    expect(await screen.findByText("82%")).toBeInTheDocument();

    const documented = screen.getByText("Documented").closest("div")!;
    expect(documented).toHaveTextContent("9");
    const undocumented = screen.getByText("Undocumented").closest("div")!;
    expect(undocumented).toHaveTextContent("1");
    const waived = screen.getByText("Waived").closest("div")!;
    expect(waived).toHaveTextContent("1");
  });

  it("renders a friendly empty state when no coverage is reported", async () => {
    renderCoverage(fakeApi({ coverageFor: async () => [] }));

    expect(
      await screen.findByText(/no coverage reported yet/i),
    ).toBeInTheDocument();
  });

  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<CoverageSnapshot[]>(() => {});
    renderCoverage(fakeApi({ coverageFor: () => never }));

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    renderCoverage(
      fakeApi({
        coverageFor: async () => {
          throw new Error("coverage boom");
        },
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load coverage/i);
    expect(alert).toHaveTextContent(/coverage boom/);
  });

  // ── T-03: the config-driven file list ─────────────────────────────────────

  it("renders a file row per file with status, owners and waived reason", async () => {
    renderCoverage(fakeApi());

    await screen.findByText("82%");

    // One row per file in the latest snapshot.
    const documentedRow = await screen.findByRole("row", {
      name: /src\/install\.py/,
    });
    expect(documentedRow).toHaveTextContent(/documented/i);
    expect(documentedRow).toHaveTextContent("guide/install");

    const gapRow = screen.getByRole("row", { name: /src\/legacy\.py/ });
    expect(gapRow).toHaveTextContent(/undocumented/i);

    const waivedRow = screen.getByRole("row", { name: /src\/generated\.py/ });
    expect(waivedRow).toHaveTextContent(/waived/i);
    expect(waivedRow).toHaveTextContent(/auto-generated/i);

    // Summary line.
    expect(
      screen.getByText(/9 documented · 1 gaps · 1 waived/),
    ).toBeInTheDocument();
  });

  it("falls back to baskets-only when the snapshot has no files", async () => {
    renderCoverage(fakeApi({ coverageFor: async () => coverageNoFiles }));

    expect(await screen.findByText("60%")).toBeInTheDocument();
    // Baskets still render.
    const documented = screen.getByText("Documented").closest("div")!;
    expect(documented).toHaveTextContent("6");
    // No file table.
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
