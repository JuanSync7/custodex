import { describe, it, expect } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Documents, { type DocumentsApi } from "./Documents";
import type { ConfigDocumentTree, SyncRun } from "../types";
import { configDocuments, readmeDocTree, syncRunGit } from "../test/fixtures";

function fakeApi(overrides: Partial<DocumentsApi> = {}): DocumentsApi {
  return {
    documentsFor: async (): Promise<ConfigDocumentTree[]> => configDocuments,
    // Stubbed so the mounted <SyncControls> never hits the network.
    syncState: async (): Promise<SyncRun | null> => syncRunGit,
    syncRepo: async (): Promise<SyncRun> => syncRunGit,
    ...overrides,
  };
}

function renderDocuments(api: DocumentsApi, repoId = "acme/widget") {
  return render(
    <MemoryRouter>
      <Documents api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("Documents page", () => {
  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<ConfigDocumentTree[]>(() => {});
    // Hold the mounted <SyncControls> in loading too so no post-assert update fires.
    renderDocuments(
      fakeApi({
        documentsFor: () => never,
        syncState: () => new Promise(() => {}),
      }),
    );

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    renderDocuments(
      fakeApi({
        documentsFor: async () => {
          throw new Error("documents boom");
        },
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load documents/i);
    expect(alert).toHaveTextContent(/documents boom/);
  });

  it("renders a friendly empty state when there are no documents", async () => {
    renderDocuments(fakeApi({ documentsFor: async () => [] }));

    expect(
      await screen.findByText(/no documents configured/i),
    ).toBeInTheDocument();
  });

  it("renders each document's doc_id, audience, unit and region_keys", async () => {
    renderDocuments(fakeApi());

    const installRow = await screen.findByRole("row", {
      name: /guide\/install/,
    });
    expect(installRow).toHaveTextContent("docs/install.md");
    expect(installRow).toHaveTextContent("user-guide");
    expect(installRow).toHaveTextContent("installer");
    // region_keys render as chips.
    expect(installRow).toHaveTextContent("intro");
    expect(installRow).toHaveTextContent("flags");

    const archRow = screen.getByRole("row", { name: /eng\/architecture/ });
    expect(archRow).toHaveTextContent("eng-guide");
    expect(archRow).toHaveTextContent("core");
  });

  it("does not show code_refs until a row is expanded, then hides them again", async () => {
    renderDocuments(fakeApi());

    // Collapsed by default — no code ref paths visible.
    await screen.findByRole("row", { name: /guide\/install/ });
    expect(screen.queryByText("src/install.py")).not.toBeInTheDocument();

    // Expand the install document's code refs.
    const installRow = screen.getByRole("row", { name: /guide\/install/ });
    fireEvent.click(
      within(installRow).getByRole("button", { name: /view 2 refs/i }),
    );

    // Code refs (path + symbols) are now revealed.
    expect(await screen.findByText("src/install.py")).toBeInTheDocument();
    expect(screen.getByText("install")).toBeInTheDocument();
    expect(screen.getByText("uninstall")).toBeInTheDocument();
    // A ref with no symbols shows the whole-file marker.
    expect(screen.getByText("src/flags.py")).toBeInTheDocument();
    expect(screen.getByText(/whole file/i)).toBeInTheDocument();

    // Collapsing hides them again.
    fireEvent.click(
      within(installRow).getByRole("button", { name: /hide 2 refs/i }),
    );
    expect(screen.queryByText("src/install.py")).not.toBeInTheDocument();
  });

  it("requests git by default and re-requests local when the source toggles", async () => {
    const seen: string[] = [];
    renderDocuments(
      fakeApi({
        documentsFor: async (_repoId, syncKind) => {
          seen.push(syncKind ?? "git");
          return configDocuments;
        },
      }),
    );

    await screen.findByRole("row", { name: /guide\/install/ });
    expect(seen).toContain("git");

    fireEvent.change(screen.getByLabelText("Source"), {
      target: { value: "local" },
    });

    await waitFor(() => expect(seen).toContain("local"));
  });

  it("lists README files in a separate section, apart from the engineering docs", async () => {
    renderDocuments(
      fakeApi({ documentsFor: async () => [...configDocuments, readmeDocTree] }),
    );

    // The engineering documents render in the main table.
    await screen.findByRole("row", { name: /guide\/install/ });

    // The README appears under its OWN "README files" heading/section.
    const heading = screen.getByRole("heading", { name: /readme files/i });
    const section = heading.closest("div")!;
    const readmeRow = within(section).getByRole("row", { name: /readme/i });
    expect(readmeRow).toHaveTextContent("README.md");
    expect(readmeRow).toHaveTextContent("user-guide");
  });
});
