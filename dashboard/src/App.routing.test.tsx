import { afterEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import {
  configDocuments,
  configTemplates,
  editableTree,
  health,
  records,
  repos,
  resolutions,
  statuses,
} from "./test/fixtures";

// App uses the shared `apiClient`, which calls the global `fetch`. We stub fetch
// to serve the fixtures by URL so the real router + pages run end to end without
// a network (still no MSW — just a small URL router over the fixtures).
function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    let body: unknown = [];
    if (url.endsWith("/repos")) body = repos;
    else if (url.includes("/sync-state")) body = null;
    else if (url.includes("/status")) {
      const id = url.replace(/.*\/repos\//, "").replace(/\/status$/, "");
      body = statuses[id];
    } else if (url.includes("/records")) body = records;
    else if (url.includes("/resolutions")) body = resolutions;
    else if (url.includes("/config/editable")) body = editableTree;
    else if (url.includes("/coverage")) body = [];
    else if (url.includes("/documents")) body = configDocuments;
    else if (url.includes("/health")) body = health;
    else if (url.includes("/config/templates")) body = configTemplates;
    return { ok: true, status: 200, json: async () => body } as Response;
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App routing", () => {
  it("navigates from the Repos table to a repo's drift timeline on click", async () => {
    vi.stubGlobal("fetch", stubFetch());

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    // The repos table renders; the repo id is a link to its detail route.
    const repoLink = await screen.findByRole("link", { name: "acme/widget" });
    expect(repoLink).toHaveAttribute("href", "/repos/acme/widget");

    fireEvent.click(repoLink);

    // We're now on the detail route: the timeline heading + a record appear.
    expect(
      await screen.findByRole("heading", { name: /drift timeline/i }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("guide/install")).toBeInTheDocument(),
    );
  });

  it("navigates to a repo's coverage view via its coverage link", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        let body: unknown = [];
        if (url.endsWith("/repos")) body = repos;
        else if (url.includes("/status")) {
          const id = url.replace(/.*\/repos\//, "").replace(/\/status$/, "");
          body = statuses[id];
        } else if (url.includes("/coverage"))
          body = [{ ratio: 0.5, documented: 5, undocumented: 5, waived: 0 }];
        return { ok: true, status: 200, json: async () => body } as Response;
      }),
    );

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    const links = await screen.findAllByRole("link", { name: /coverage/i });
    fireEvent.click(links[0]);

    expect(
      await screen.findByRole("heading", { name: /coverage/i }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("50%")).toBeInTheDocument(),
    );
  });

  it("navigates to a repo's health view via its health link", async () => {
    vi.stubGlobal("fetch", stubFetch());

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    const links = await screen.findAllByRole("link", { name: /health/i });
    fireEvent.click(links[0]);

    expect(
      await screen.findByRole("heading", { name: /health/i }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("stat-escalation-rate")).toHaveTextContent("25%"),
    );
  });

  it("navigates to the global config format page via the Format nav link", async () => {
    vi.stubGlobal("fetch", stubFetch());

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    const formatLink = await screen.findByRole("link", { name: /format/i });
    expect(formatLink).toHaveAttribute("href", "/config");

    fireEvent.click(formatLink);

    expect(
      await screen.findByRole("heading", { name: /config format/i }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByText("index.yaml", { selector: "figcaption" }),
      ).toBeInTheDocument(),
    );
  });

  it("navigates to a repo's documents view via its documents link", async () => {
    vi.stubGlobal("fetch", stubFetch());

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    const links = await screen.findAllByRole("link", { name: /documents/i });
    fireEvent.click(links[0]);

    expect(
      await screen.findByRole("heading", { name: /documents/i }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("guide/install")).toBeInTheDocument(),
    );
  });

  it("navigates to a repo's mapping view via its mapping link", async () => {
    vi.stubGlobal("fetch", stubFetch());

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    const links = await screen.findAllByRole("link", { name: /mapping/i });
    fireEvent.click(links[0]);

    expect(
      await screen.findByRole("heading", { name: /mapping:/i }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("guide/getting-started")).toBeInTheDocument(),
    );
  });

  it("shows the in-repo nav inside a repo and its Mapping tab reaches the hierarchy", async () => {
    vi.stubGlobal("fetch", stubFetch());

    // Land directly on a repo's drift timeline.
    render(
      <MemoryRouter initialEntries={["/repos/acme/widget"]}>
        <App />
      </MemoryRouter>,
    );

    // The in-repo tab bar is present, with Drift active.
    const repoNav = await screen.findByRole("navigation", {
      name: /repo views/i,
    });
    expect(repoNav).toBeInTheDocument();

    // Click the Mapping tab on the in-repo bar (scoped to the nav landmark).
    const mappingTab = within(repoNav).getByRole("link", { name: "Mapping" });
    fireEvent.click(mappingTab);

    // The Mapping hierarchy renders.
    expect(
      await screen.findByRole("heading", { name: /mapping:/i }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("guide/getting-started")).toBeInTheDocument(),
    );

    // And the bar is still there, now with Mapping active.
    const navAfter = screen.getByRole("navigation", { name: /repo views/i });
    expect(within(navAfter).getByRole("link", { name: "Mapping" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
