import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import Wiki, { type WikiApi } from "./Wiki";
import { wikiPayload } from "../test/fixtures";
import type { WikiPayload } from "../types";

function fakeApi(overrides: Partial<WikiApi> = {}): WikiApi {
  return {
    wiki: async (): Promise<WikiPayload> => wikiPayload,
    ...overrides,
  };
}

describe("Wiki page", () => {
  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<WikiPayload>(() => {});
    render(<Wiki api={fakeApi({ wiki: () => never })} />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    render(
      <Wiki
        api={fakeApi({
          wiki: async () => {
            throw new Error("wiki boom");
          },
        })}
      />,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load/i);
    expect(alert).toHaveTextContent(/wiki boom/);
  });

  it("renders the section rail and the first section's HTML on load", async () => {
    render(<Wiki api={fakeApi()} />);

    // The rail lists every section title.
    const rail = await screen.findByRole("navigation", { name: /wiki sections/i });
    expect(within(rail).getByText("Feature Reference")).toBeInTheDocument();
    expect(within(rail).getByText("Traceability Matrix")).toBeInTheDocument();

    // The prose pane renders the FIRST section's HTML verbatim (the <strong> and
    // <li> survive — the fragment is injected, not escaped).
    expect(
      screen.getByRole("heading", { name: "Feature Reference", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText("FEAT-SERVER-019")).toBeInTheDocument();
    // The second section's distinctive content is NOT shown yet.
    expect(screen.queryByText("test_server.py")).not.toBeInTheDocument();
  });

  it("switches the rendered HTML when a second section is clicked", async () => {
    render(<Wiki api={fakeApi()} />);

    const rail = await screen.findByRole("navigation", { name: /wiki sections/i });
    fireEvent.click(within(rail).getByText("Traceability Matrix"));

    // The prose pane now shows the second section's HTML (a rendered table).
    expect(await screen.findByText("test_server.py")).toBeInTheDocument();
    // …and the first section's body is gone.
    expect(screen.queryByText("FEAT-SERVER-019")).not.toBeInTheDocument();
  });

  it("shows a friendly empty state when no wikis are available", async () => {
    render(<Wiki api={fakeApi({ wiki: async () => ({ sections: [] }) })} />);

    // The Wiki heading is still present (routing finds it), with an empty notice.
    expect(
      await screen.findByRole("heading", { name: /wiki/i }),
    ).toBeInTheDocument();
    const empty = await screen.findByText(/no wiki available/i);
    expect(empty).toBeInTheDocument();
    expect(empty).toHaveTextContent(/cdmon wiki/i);
  });
});
