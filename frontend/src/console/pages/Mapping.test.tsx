import { describe, it, expect } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Mapping, { type MappingApi } from "./Mapping";
import { ApiError } from "../api/client";
import type {
  ConfigEdit,
  EditableConfigTree,
  GenerateResponse,
  StoredConfigEdit,
  SyncRun,
} from "../types";
import {
  editableTree,
  generateResponse,
  storedConfigEdits,
  syncRunLocal,
} from "../test/fixtures";

function fakeApi(overrides: Partial<MappingApi> = {}): MappingApi {
  return {
    configEditable: async (): Promise<EditableConfigTree> => editableTree,
    stageConfigEdit: async (): Promise<{ edit_id: string }> => ({
      edit_id: "edit-new",
    }),
    listConfigEdits: async (): Promise<StoredConfigEdit[]> => [],
    generateConfig: async (): Promise<GenerateResponse> => generateResponse,
    // Stubbed so the mounted <SyncControls> never hits the network.
    syncState: async (): Promise<SyncRun | null> => syncRunLocal,
    syncRepo: async (): Promise<SyncRun> => syncRunLocal,
    ...overrides,
  };
}

function renderMapping(api: MappingApi, repoId = "acme/widget") {
  return render(
    <MemoryRouter>
      <Mapping api={api} repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("Mapping page", () => {
  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<EditableConfigTree>(() => {});
    renderMapping(
      fakeApi({
        configEditable: () => never,
        syncState: () => new Promise(() => {}),
      }),
    );

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    renderMapping(
      fakeApi({
        configEditable: async () => {
          throw new Error("mapping boom");
        },
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load mapping/i);
    expect(alert).toHaveTextContent(/mapping boom/);
  });

  it("renders a document row with its doc_id, audience, unit and regions", async () => {
    renderMapping(fakeApi());

    const row = await screen.findByRole("row", {
      name: /guide\/getting-started/,
    });
    expect(row).toHaveTextContent("docs/guide/getting-started.md");
    expect(row).toHaveTextContent("user-guide");
    expect(row).toHaveTextContent("core");
    expect(row).toHaveTextContent("intro");
  });

  it("reveals BOTH code_refs and context_refs (distinct) when a row is expanded", async () => {
    renderMapping(fakeApi());

    const row = await screen.findByRole("row", {
      name: /guide\/getting-started/,
    });
    // Collapsed by default — neither sub-list is visible yet.
    expect(screen.queryByText("src/taskflow/core/model.py")).not.toBeInTheDocument();
    expect(screen.queryByText(/glance-through/i)).not.toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: /view/i }));

    // Sub-list A: code_refs — path + symbol chip.
    expect(
      await screen.findByText("src/taskflow/core/model.py"),
    ).toBeInTheDocument();
    expect(screen.getByText("Task")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /^linked source files$/i }),
    ).toBeInTheDocument();

    // Sub-list B: context_refs — the distinct "Context (glance-through)" section,
    // each path + its note (and a no-note ref still shows its path).
    expect(screen.getByText(/glance-through/i)).toBeInTheDocument();
    expect(screen.getByText("docs/api/core-api.md")).toBeInTheDocument();
    expect(screen.getByText("full engine reference")).toBeInTheDocument();
    expect(screen.getByText("src/taskflow/core/engine.py")).toBeInTheDocument();
  });

  it("lists the undocumented files in the unlinked section", async () => {
    renderMapping(fakeApi());

    expect(
      await screen.findByText("src/taskflow/core/scheduler.py"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /unlinked source files \(1\)/i }),
    ).toBeInTheDocument();
  });

  it("renders ignored files in a CLOSED <details> showing the count", async () => {
    const { container } = renderMapping(fakeApi());

    await screen.findByRole("row", { name: /guide\/getting-started/ });

    const details = container.querySelector("details.mapping-ignored");
    expect(details).not.toBeNull();
    // Closed by default — no `open` attribute.
    expect(details).not.toHaveAttribute("open");
    // The summary shows the count.
    const summary = within(details as HTMLElement).getByText(
      /ignored files \(1\)/i,
    );
    expect(summary).toBeInTheDocument();
    // The ignored file is present in the DOM (details renders children even when closed).
    expect(screen.getByText("tests/conftest.py")).toBeInTheDocument();
  });

  it("defaults to local and re-fetches with git when the source toggles", async () => {
    const seen: string[] = [];
    renderMapping(
      fakeApi({
        configEditable: async (_repoId, syncKind) => {
          seen.push(syncKind ?? "local");
          return editableTree;
        },
      }),
    );

    await screen.findByRole("row", { name: /guide\/getting-started/ });
    expect(seen).toContain("local");

    fireEvent.change(screen.getByLabelText("Source"), {
      target: { value: "git" },
    });

    await waitFor(() => expect(seen).toContain("git"));
  });
});

describe("Mapping page — E-10 form + staged edits + generate", () => {
  it("'Link to a document…' opens the form pre-filled with the source path", async () => {
    renderMapping(fakeApi());

    const linkBtn = await screen.findByRole("button", {
      name: /link to a document/i,
    });
    fireEvent.click(linkBtn);

    const form = await screen.findByRole("form", { name: /mapping ticket form/i });
    const inputs = within(form).getAllByLabelText("Path", {
      selector: "input",
    }) as HTMLInputElement[];
    expect(
      inputs.some((i) => i.value === "src/taskflow/core/scheduler.py"),
    ).toBe(true);
  });

  it("opens the form as a popout dialog and closes it on ×", async () => {
    renderMapping(fakeApi());

    fireEvent.click(
      await screen.findByRole("button", { name: /link to a document/i }),
    );
    // The form is now inside a modal dialog (popout), not inline.
    const dialog = await screen.findByRole("dialog", {
      name: /file a mapping ticket/i,
    });
    expect(within(dialog).getByRole("form", { name: /mapping ticket form/i }))
      .toBeInTheDocument();
    // Closing the popout removes the dialog.
    fireEvent.click(within(dialog).getByRole("button", { name: /close/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("'Edit mapping…' opens the form pre-targeted at that document", async () => {
    renderMapping(fakeApi());

    const editBtn = await screen.findByRole("button", { name: /edit mapping/i });
    fireEvent.click(editBtn);

    const form = await screen.findByRole("form", { name: /mapping ticket form/i });
    const target = within(form).getByLabelText(
      "Target document",
    ) as HTMLSelectElement;
    expect(target.value).toBe("guide/getting-started");
  });

  it("submitting the form calls stageConfigEdit with an add_code_ref edit", async () => {
    const stageCalls: ConfigEdit[] = [];
    renderMapping(
      fakeApi({
        stageConfigEdit: async (_repoId, edit) => {
          stageCalls.push(edit);
          return { edit_id: "edit-staged" };
        },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /edit mapping/i }));
    const form = await screen.findByRole("form", { name: /mapping ticket form/i });
    fireEvent.change(within(form).getByLabelText("Path", { selector: "input" }), {
      target: { value: "src/taskflow/core/scheduler.py" },
    });
    fireEvent.click(
      within(form).getByRole("button", { name: /stage ticket/i }),
    );

    await waitFor(() => expect(stageCalls).toHaveLength(1));
    expect(stageCalls[0]).toEqual({
      action: "add_code_ref",
      unit: "core",
      doc_id: "guide/getting-started",
      ref: { path: "src/taskflow/core/scheduler.py" },
    });
  });

  it("shows a pending edit returned by listConfigEdits", async () => {
    renderMapping(
      fakeApi({ listConfigEdits: async () => storedConfigEdits }),
    );

    expect(await screen.findByText("edit-001")).toBeInTheDocument();
    // The pending count is in the heading.
    expect(
      screen.getByRole("heading", { name: /staged edits \(1 pending\)/i }),
    ).toBeInTheDocument();
  });

  it("re-fetches the staged list after a successful stage", async () => {
    let calls = 0;
    renderMapping(
      fakeApi({
        listConfigEdits: async () => {
          calls += 1;
          // First load: empty. After a stage bumps the reload, return the edit.
          return calls > 1 ? storedConfigEdits : [];
        },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /edit mapping/i }));
    const form = await screen.findByRole("form", { name: /mapping ticket form/i });
    fireEvent.change(within(form).getByLabelText("Path", { selector: "input" }), {
      target: { value: "src/taskflow/core/scheduler.py" },
    });
    fireEvent.click(within(form).getByRole("button", { name: /stage ticket/i }));

    expect(await screen.findByText("edit-001")).toBeInTheDocument();
  });

  it("Generate calls generateConfig and re-fetches the editable tree", async () => {
    let editableCalls = 0;
    const genCalls: unknown[] = [];
    renderMapping(
      fakeApi({
        configEditable: async () => {
          editableCalls += 1;
          return editableTree;
        },
        listConfigEdits: async () => storedConfigEdits,
        generateConfig: async (_repoId, body) => {
          genCalls.push(body);
          return generateResponse;
        },
      }),
    );

    const genBtn = await screen.findByRole("button", {
      name: /generate \/ make live/i,
    });
    await waitFor(() => expect(genBtn).not.toBeDisabled());
    const before = editableCalls;
    fireEvent.click(genBtn);

    await waitFor(() => expect(genCalls).toHaveLength(1));
    // The tree is re-fetched (now live).
    await waitFor(() => expect(editableCalls).toBeGreaterThan(before));
    // The result line shows the applied count.
    expect(await screen.findByText(/applied 1 edit/i)).toBeInTheDocument();
  });

  it("Generate is disabled when there are no pending edits", async () => {
    renderMapping(fakeApi({ listConfigEdits: async () => [] }));

    const genBtn = await screen.findByRole("button", {
      name: /generate \/ make live/i,
    });
    expect(genBtn).toBeDisabled();
  });

  it("a 401 from generateConfig reveals the token input + auth message", async () => {
    let reject = true;
    const genCalls: string[] = [];
    renderMapping(
      fakeApi({
        listConfigEdits: async () => storedConfigEdits,
        generateConfig: async (_repoId, _body, token) => {
          if (reject) {
            throw new ApiError(401, "/api/repos/acme/widget/config/generate");
          }
          genCalls.push(token);
          return generateResponse;
        },
      }),
    );

    const genBtn = await screen.findByRole("button", {
      name: /generate \/ make live/i,
    });
    await waitFor(() => expect(genBtn).not.toBeDisabled());
    fireEvent.click(genBtn);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/auth required/i);
    expect(await screen.findByLabelText("Token")).toBeInTheDocument();

    reject = false;
    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "gen-tok" },
    });
    fireEvent.click(screen.getByRole("button", { name: /generate \/ make live/i }));
    await waitFor(() => expect(genCalls).toEqual(["gen-tok"]));
  });
});
