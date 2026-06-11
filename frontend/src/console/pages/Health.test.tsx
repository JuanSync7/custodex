import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Health, { type HealthApi } from "./Health";
import type { RepoHealth } from "../types";
import { health } from "../test/fixtures";

function fakeApi(overrides: Partial<HealthApi> = {}) {
  const api: HealthApi = {
    healthFor: async (): Promise<RepoHealth> => health,
    ...overrides,
  };
  return { api };
}

function renderHealth(api: HealthApi, repoId = "acme/widget") {
  return render(
    <MemoryRouter>
      <Health api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("Health page", () => {
  it("renders the repo health metrics", async () => {
    const { api } = fakeApi();
    renderHealth(api);

    expect(await screen.findByText(/health/i)).toBeInTheDocument();
    // total / escalations / resolved / unresolved / overrides stat values.
    expect(screen.getByTestId("stat-total")).toHaveTextContent("4");
    expect(screen.getByTestId("stat-escalations")).toHaveTextContent("1");
    expect(screen.getByTestId("stat-resolved")).toHaveTextContent("2");
    expect(screen.getByTestId("stat-unresolved")).toHaveTextContent("2");
    expect(screen.getByTestId("stat-overrides")).toHaveTextContent("1");
    // escalation rate rendered as a percentage.
    expect(screen.getByTestId("stat-escalation-rate")).toHaveTextContent("25%");
    // mttr humanised from seconds (90s → "1.5m").
    expect(screen.getByTestId("stat-mttr")).toHaveTextContent("1.5m");
  });

  it("renders an em dash for a null MTTR", async () => {
    const { api } = fakeApi({
      healthFor: async () => ({ ...health, resolved: 0, mttr_seconds: null }),
    });
    renderHealth(api);

    const mttr = await screen.findByTestId("stat-mttr");
    expect(mttr).toHaveTextContent("—");
  });

  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<RepoHealth>(() => {});
    const { api } = fakeApi({ healthFor: () => never });
    renderHealth(api);

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    const { api } = fakeApi({
      healthFor: async () => {
        throw new Error("health boom");
      },
    });
    renderHealth(api);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load health/i);
    expect(alert).toHaveTextContent(/health boom/);
  });
});
