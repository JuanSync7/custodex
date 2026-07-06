import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Graph, { type GraphApi } from "./Graph";
import type { GraphSnapshot } from "../types";

const SNAPSHOT: GraphSnapshot = {
  schema_version: "1.0.0",
  captured_at: "2026-06-20T09:00:00Z",
  nodes: [
    { id: "doc docs/guide.md", kind: "doc", name: "guide" },
    { id: "doc docs/api.md", kind: "doc", name: "api" },
    { id: "symbol src/engine.py#Engine", kind: "symbol", name: "Engine" },
    { id: "symbol src/queue.py#drain_queue", kind: "symbol", name: "drain_queue" },
  ],
  edges: [
    {
      source: "doc docs/api.md",
      target: "symbol src/engine.py#Engine",
      kind: "documents",
      tier: "declared",
    },
    {
      source: "doc docs/guide.md",
      target: "symbol src/queue.py#drain_queue",
      kind: "mentions",
      tier: "resolved",
    },
    {
      source: "doc docs/api.md",
      target: "symbol src/queue.py#drain_queue",
      kind: "mentions",
      tier: "resolved",
    },
    {
      source: "doc docs/guide.md",
      target: "doc docs/api.md",
      kind: "depends_on",
      tier: "declared",
    },
  ],
  unresolved: { guide: 2, api: 0 },
  warnings: [],
};

function fakeApi(overrides: Partial<GraphApi> = {}): GraphApi {
  return {
    graphFor: async (): Promise<GraphSnapshot> => SNAPSHOT,
    ...overrides,
  };
}

function renderGraph(api: GraphApi, repoId = "acme/widget") {
  return render(
    <MemoryRouter>
      <Graph api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("Graph page", () => {
  it("renders the node/edge summary with kind counts", async () => {
    renderGraph(fakeApi());
    expect(
      await screen.findByText(/4 node\(s\), 4 edge\(s\)/i),
    ).toBeInTheDocument();
    // kind counts: 2 doc nodes, 2 symbol nodes; 2 mentions edges.
    const kindTable = screen
      .getByRole("heading", { name: /nodes & edges by kind/i })
      .closest(".panel") as HTMLElement;
    expect(within(kindTable).getByRole("row", { name: /^doc / })).toHaveTextContent(
      "2",
    );
    expect(within(kindTable).getByText("mentions")).toBeInTheDocument();
  });

  it("renders the per-doc rot signal for nonzero unresolved counts", async () => {
    renderGraph(fakeApi());
    const rot = (
      await screen.findByRole("heading", { name: /rot signal/i })
    ).closest(".panel") as HTMLElement;
    const row = within(rot).getByRole("row", { name: /guide/ });
    expect(row).toHaveTextContent("2");
    // the zero-count doc is NOT listed as rot
    expect(within(rot).queryByRole("row", { name: /^api/ })).not.toBeInTheDocument();
  });

  it("ranks mentioned-but-undocumented symbols (the what-to-document feed)", async () => {
    renderGraph(fakeApi());
    const feed = (
      await screen.findByRole("heading", { name: /what to document next/i })
    ).closest(".panel") as HTMLElement;
    // drain_queue: 2 mentioning docs, no DOCUMENTS edge → ranked.
    const row = within(feed).getByRole("row", { name: /drain_queue/ });
    expect(row).toHaveTextContent("2");
    // Engine IS documented → excluded from the feed.
    expect(
      within(feed).queryByRole("row", { name: /#Engine/ }),
    ).not.toBeInTheDocument();
  });

  it("focusing a node lists its in/out edges", async () => {
    renderGraph(fakeApi());
    const select = await screen.findByRole("combobox");
    await userEvent.selectOptions(select, "doc docs/api.md");
    const focus = screen
      .getByRole("heading", { name: /focus a node/i })
      .closest(".panel") as HTMLElement;
    // out: documents Engine + mentions drain_queue; in: guide depends_on api.
    expect(within(focus).getByRole("row", { name: /#Engine/ })).toHaveTextContent(
      "out",
    );
    const dependsRow = within(focus).getByRole("row", { name: /guide\.md/ });
    expect(dependsRow).toHaveTextContent("in");
    expect(dependsRow).toHaveTextContent("depends_on");
  });

  it("shows the honest empty state before any snapshot is pushed", async () => {
    renderGraph(fakeApi({ graphFor: async () => ({}) }));
    expect(await screen.findByText(/no graph snapshot yet/i)).toBeInTheDocument();
    expect(screen.getByText(/cdx graph/)).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    renderGraph(
      fakeApi({
        graphFor: async () => {
          throw new Error("boom");
        },
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/);
  });
});
