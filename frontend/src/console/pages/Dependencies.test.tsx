import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Dependencies, { type DependenciesApi } from "./Dependencies";
import type { DocGraph } from "../types";
import { docGraph } from "../test/fixtures";

function fakeApi(overrides: Partial<DependenciesApi> = {}): DependenciesApi {
  return {
    docGraphFor: async (): Promise<DocGraph> => docGraph,
    ...overrides,
  };
}

function renderDeps(api: DependenciesApi, repoId = "acme/widget") {
  return render(
    <MemoryRouter>
      <Dependencies api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("Dependencies page", () => {
  it("renders the declared doc↔doc edges with their relationship + audience", async () => {
    renderDeps(fakeApi());

    // The summary counts the edges and distinct documents.
    expect(
      await screen.findByText(/2 dependency edge\(s\) across 2 document\(s\)/i),
    ).toBeInTheDocument();

    // getting-started depends on io-api (a user-guide edge).
    const gsRow = screen.getByRole("row", { name: /getting-started/ });
    expect(gsRow).toHaveTextContent("io-api");
    expect(gsRow).toHaveTextContent(/depends/);
    expect(gsRow).toHaveTextContent(/user-guide/);

    // core-api refines io-api (an eng-guide edge).
    const coreRow = screen.getByRole("row", { name: /core-api/ });
    expect(coreRow).toHaveTextContent("io-api");
    expect(coreRow).toHaveTextContent(/refines/);

    // The document cell carries the full doc path as a hover title.
    expect(within(gsRow).getByText("getting-started")).toHaveAttribute(
      "title",
      "docs/getting-started.md",
    );
  });

  it("counts DISTINCT documents, not edges, when one doc has several upstreams", async () => {
    // core-api declares TWO upstream edges; getting-started one → 3 edges, 2 docs.
    const multi: DocGraph = {
      edges: [
        {
          doc_id: "core-api",
          doc_path: "docs/api/core-api.md",
          audience: "eng-guide",
          upstream_id: "io-api",
          type: "refines",
        },
        {
          doc_id: "core-api",
          doc_path: "docs/api/core-api.md",
          audience: "eng-guide",
          upstream_id: "overview",
          type: "depends",
        },
        {
          doc_id: "getting-started",
          doc_path: "docs/getting-started.md",
          audience: "user-guide",
          upstream_id: "io-api",
          type: "depends",
        },
      ],
      edge_count: 3,
    };
    renderDeps(fakeApi({ docGraphFor: async () => multi }));

    expect(
      await screen.findByText(/3 dependency edge\(s\) across 2 document\(s\)/i),
    ).toBeInTheDocument();
    // both of core-api's upstream rows render (io-api AND overview).
    const rows = screen.getAllByRole("row", { name: /core-api/ });
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.textContent).join(" ")).toMatch(/io-api/);
    expect(rows.map((r) => r.textContent).join(" ")).toMatch(/overview/);
  });

  it("renders a friendly empty state when there are no edges", async () => {
    renderDeps(fakeApi({ docGraphFor: async () => ({ edges: [], edge_count: 0 }) }));

    expect(
      await screen.findByText(/no declared doc↔doc dependencies/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<DocGraph>(() => {});
    renderDeps(fakeApi({ docGraphFor: () => never }));

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    renderDeps(
      fakeApi({
        docGraphFor: async () => {
          throw new Error("graph boom");
        },
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load dependencies/i);
    expect(alert).toHaveTextContent(/graph boom/);
  });
});
