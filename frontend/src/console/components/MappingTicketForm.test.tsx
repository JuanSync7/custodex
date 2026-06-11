import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import MappingTicketForm, {
  type MappingTicketFormApi,
} from "./MappingTicketForm";
import { ApiError } from "../api/client";
import type { ConfigEdit } from "../types";
import { editableTree } from "../test/fixtures";

interface StageCall {
  repoId: string;
  edit: ConfigEdit;
  token: string;
}

function fakeApi(overrides: Partial<MappingTicketFormApi> = {}) {
  const stageCalls: StageCall[] = [];
  let counter = 0;
  const api: MappingTicketFormApi = {
    stageConfigEdit: async (repoId, edit, token) => {
      stageCalls.push({ repoId, edit, token });
      counter += 1;
      return { edit_id: `edit-${counter}` };
    },
    ...overrides,
  };
  return { api, stageCalls };
}

function renderForm(
  api: MappingTicketFormApi,
  props: Partial<React.ComponentProps<typeof MappingTicketForm>> = {},
) {
  return render(
    <MappingTicketForm
      repoId="acme/widget"
      documents={editableTree.documents}
      unitFiles={editableTree.unit_files}
      docStyles={editableTree.doc_styles}
      api={api}
      {...props}
    />,
  );
}

describe("MappingTicketForm", () => {
  it("existing doc + source file (scope=all) stages an add_code_ref", async () => {
    const { api, stageCalls } = fakeApi();
    renderForm(api, { initialDocId: "guide/getting-started" });

    fireEvent.change(screen.getByLabelText("Path", { selector: "input" }), {
      target: { value: "src/taskflow/core/scheduler.py" },
    });
    fireEvent.click(screen.getByRole("button", { name: /stage ticket/i }));

    await waitFor(() => expect(stageCalls).toHaveLength(1));
    expect(stageCalls[0].edit).toEqual({
      action: "add_code_ref",
      unit: "core",
      doc_id: "guide/getting-started",
      ref: { path: "src/taskflow/core/scheduler.py" },
    });
  });

  it("scope=symbols emits symbols on the ref", async () => {
    const { api, stageCalls } = fakeApi();
    renderForm(api, { initialDocId: "guide/getting-started" });

    fireEvent.change(screen.getByLabelText("Path", { selector: "input" }), {
      target: { value: "src/taskflow/core/scheduler.py" },
    });
    fireEvent.change(screen.getByLabelText("Scope"), {
      target: { value: "symbols" },
    });
    fireEvent.change(
      screen.getByLabelText(/symbols \(comma-separated\)/i),
      { target: { value: "Scheduler, run" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /stage ticket/i }));

    await waitFor(() => expect(stageCalls).toHaveLength(1));
    expect(stageCalls[0].edit).toEqual({
      action: "add_code_ref",
      unit: "core",
      doc_id: "guide/getting-started",
      ref: { path: "src/taskflow/core/scheduler.py", symbols: ["Scheduler", "run"] },
    });
  });

  it("scope=lines emits lines as a start-end string", async () => {
    const { api, stageCalls } = fakeApi();
    renderForm(api, { initialDocId: "guide/getting-started" });

    fireEvent.change(screen.getByLabelText("Path", { selector: "input" }), {
      target: { value: "src/taskflow/core/scheduler.py" },
    });
    fireEvent.change(screen.getByLabelText("Scope"), {
      target: { value: "lines" },
    });
    fireEvent.change(screen.getByLabelText(/lines \(start-end\)/i), {
      target: { value: "10-42" },
    });
    fireEvent.click(screen.getByRole("button", { name: /stage ticket/i }));

    await waitFor(() => expect(stageCalls).toHaveLength(1));
    const edit = stageCalls[0].edit;
    expect(edit.action).toBe("add_code_ref");
    if (edit.action === "add_code_ref") {
      expect(edit.ref).toEqual({
        path: "src/taskflow/core/scheduler.py",
        lines: "10-42",
      });
    }
  });

  it("creating a NEW document stages a create_doc with code_refs + doc_style", async () => {
    const { api, stageCalls } = fakeApi();
    renderForm(api, { initialSourcePath: "src/taskflow/core/scheduler.py" });

    // Target dropdown defaults to "+ New document…" since no initialDocId.
    fireEvent.change(screen.getByLabelText("Target document"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Doc id"), {
      target: { value: "guide/scheduling" },
    });
    // The new-doc Path input (the fieldset's Path); the source Path is pre-filled.
    const pathInputs = screen.getAllByLabelText("Path", { selector: "input" });
    fireEvent.change(pathInputs[0], {
      target: { value: "docs/guide/scheduling.md" },
    });
    fireEvent.change(screen.getByLabelText("Audience"), {
      target: { value: "user-guide" },
    });
    fireEvent.change(screen.getByLabelText("Document type"), {
      target: { value: "tutorial" },
    });
    fireEvent.click(screen.getByRole("button", { name: /stage ticket/i }));

    await waitFor(() => expect(stageCalls).toHaveLength(1));
    expect(stageCalls[0].edit).toEqual({
      action: "create_doc",
      unit: "core",
      doc_id: "guide/scheduling",
      path: "docs/guide/scheduling.md",
      audience: "user-guide",
      code_refs: [{ path: "src/taskflow/core/scheduler.py" }],
      doc_style: { document_type: "tutorial" },
    });
  });

  it("context-refs-only on an existing doc stages a set_context_refs", async () => {
    const { api, stageCalls } = fakeApi();
    renderForm(api, { initialDocId: "guide/getting-started" });

    fireEvent.change(screen.getByLabelText("Context path"), {
      target: { value: "docs/api/core-api.md" },
    });
    fireEvent.change(screen.getByLabelText("Note"), {
      target: { value: "engine ref" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add context ref/i }));
    fireEvent.click(screen.getByRole("button", { name: /stage ticket/i }));

    await waitFor(() => expect(stageCalls).toHaveLength(1));
    expect(stageCalls[0].edit).toEqual({
      action: "set_context_refs",
      unit: "core",
      doc_id: "guide/getting-started",
      context_refs: [{ path: "docs/api/core-api.md", note: "engine ref" }],
    });
  });

  it("doc-style-only on an existing doc stages a set_doc_style", async () => {
    const { api, stageCalls } = fakeApi();
    renderForm(api, { initialDocId: "guide/getting-started" });

    fireEvent.change(screen.getByLabelText("Tone"), {
      target: { value: "friendly" },
    });
    fireEvent.click(screen.getByRole("button", { name: /stage ticket/i }));

    await waitFor(() => expect(stageCalls).toHaveLength(1));
    expect(stageCalls[0].edit).toEqual({
      action: "set_doc_style",
      doc_id: "guide/getting-started",
      doc_style: { tone: "friendly" },
    });
  });

  it("stages MULTIPLE sequential tickets when several aspects change at once", async () => {
    const { api, stageCalls } = fakeApi();
    renderForm(api, { initialDocId: "guide/getting-started" });

    fireEvent.change(screen.getByLabelText("Path", { selector: "input" }), {
      target: { value: "src/taskflow/core/scheduler.py" },
    });
    fireEvent.change(screen.getByLabelText("Tone"), {
      target: { value: "friendly" },
    });
    fireEvent.click(screen.getByRole("button", { name: /stage ticket/i }));

    await waitFor(() => expect(stageCalls).toHaveLength(2));
    expect(stageCalls[0].edit.action).toBe("add_code_ref");
    expect(stageCalls[1].edit.action).toBe("set_doc_style");
  });

  it("reveals the token input + auth message on a 401, then a typed token works", async () => {
    const stageCalls: StageCall[] = [];
    let reject = true;
    const api: MappingTicketFormApi = {
      stageConfigEdit: async (repoId, edit, token) => {
        if (reject) throw new ApiError(401, "/api/repos/acme/widget/config/edits");
        stageCalls.push({ repoId, edit, token });
        return { edit_id: "edit-1" };
      },
    };
    renderForm(api, { initialDocId: "guide/getting-started" });

    fireEvent.change(screen.getByLabelText("Path", { selector: "input" }), {
      target: { value: "src/taskflow/core/scheduler.py" },
    });
    expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /stage ticket/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/auth required/i);
    expect(await screen.findByLabelText("Token")).toBeInTheDocument();

    reject = false;
    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "typed-tok" },
    });
    fireEvent.click(screen.getByRole("button", { name: /stage ticket/i }));
    await waitFor(() => expect(stageCalls).toHaveLength(1));
    expect(stageCalls[0].token).toBe("typed-tok");
  });

  it("pre-fills the source path when launched from an unlinked file", () => {
    const { api } = fakeApi();
    renderForm(api, { initialSourcePath: "src/taskflow/core/scheduler.py" });

    const pathInputs = screen.getAllByLabelText("Path", {
      selector: "input",
    }) as HTMLInputElement[];
    // With no initialDocId the target defaults to NEW doc; the source Path is the
    // last Path input and carries the pre-filled value.
    expect(
      pathInputs.some((i) => i.value === "src/taskflow/core/scheduler.py"),
    ).toBe(true);
  });
});
