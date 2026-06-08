import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import Repos, { type ReposApi } from "./Repos";
import type { RegisteredRepo, RepoStatus } from "../types";
import { repos, statuses } from "../test/fixtures";

/** Render under a MemoryRouter (Repos rows render <Link>s). */
function renderRouted(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

/** A fake client implementing the ReposApi surface — no network. */
function fakeApi(overrides: Partial<ReposApi> = {}): ReposApi {
  return {
    listRepos: async (): Promise<RegisteredRepo[]> => repos,
    repoStatus: async (id: string): Promise<RepoStatus> => statuses[id],
    ...overrides,
  };
}

describe("Repos page", () => {
  it("renders the repos returned by the client with their status numbers", async () => {
    renderRouted(<Repos api={fakeApi()} />);

    expect(
      await screen.findByRole("row", { name: /acme\/widget/ }),
    ).toBeInTheDocument();

    // both repo ids visible
    expect(screen.getByText("acme/widget")).toBeInTheDocument();
    expect(screen.getByText("octo/docs")).toBeInTheDocument();

    // status numbers from the fixture for acme/widget
    const widgetRow = screen.getByRole("row", { name: /acme\/widget/ });
    expect(widgetRow).toHaveTextContent("7"); // total records
    expect(widgetRow).toHaveTextContent("82%"); // coverage ratio 0.82
  });

  it("shows a loading state before the promise resolves", async () => {
    // a never-resolving listRepos keeps the page in the loading phase
    let resolve!: (v: RegisteredRepo[]) => void;
    const pending = new Promise<RegisteredRepo[]>((r) => {
      resolve = r;
    });
    renderRouted(<Repos api={fakeApi({ listRepos: () => pending })} />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);

    // resolve so the effect cleanup doesn't warn
    resolve(repos);
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
  });

  it("shows an error state when the client rejects", async () => {
    const api = fakeApi({
      listRepos: async () => {
        throw new Error("network down");
      },
    });
    renderRouted(<Repos api={api} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load repositories/i);
    expect(alert).toHaveTextContent(/network down/);
  });

  it("renders an empty state when there are no repos", async () => {
    const api = fakeApi({ listRepos: async () => [] });
    renderRouted(<Repos api={api} />);

    expect(
      await screen.findByText(/no repositories registered/i),
    ).toBeInTheDocument();
  });
});
