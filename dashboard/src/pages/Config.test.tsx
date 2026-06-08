import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import Config, { type ConfigApi, type ConfigTemplates } from "./Config";
import { configTemplates } from "../test/fixtures";

function fakeApi(overrides: Partial<ConfigApi> = {}): ConfigApi {
  return {
    configTemplates: async (): Promise<ConfigTemplates> => configTemplates,
    ...overrides,
  };
}

describe("Config page", () => {
  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<ConfigTemplates>(() => {});
    render(<Config api={fakeApi({ configTemplates: () => never })} />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    render(
      <Config
        api={fakeApi({
          configTemplates: async () => {
            throw new Error("templates boom");
          },
        })}
      />,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load templates/i);
    expect(alert).toHaveTextContent(/templates boom/);
  });

  it("renders the four labeled template blocks with their bodies", async () => {
    render(<Config api={fakeApi()} />);

    // Each labeled block (figure → figcaption + <pre><code>) renders the EXACT
    // template body in its <code>. textContent preserves the verbatim string
    // (unlike toHaveTextContent, which collapses whitespace/newlines).
    const codeFor = (label: string): string => {
      // Scope to the <figcaption> so a label that also appears INSIDE a code
      // block (e.g. an "index.yaml" comment) doesn't match multiple nodes.
      const cap = screen.getByText(label, { selector: "figcaption" });
      const fig = cap.closest("figure");
      expect(fig).not.toBeNull();
      const code = fig!.querySelector("pre code");
      expect(code).not.toBeNull();
      return code!.textContent ?? "";
    };

    await screen.findByText("Unit file", { selector: "figcaption" });
    expect(codeFor("Unit file")).toBe(configTemplates.unit);
    expect(codeFor("index.yaml")).toBe(configTemplates.index);
    expect(codeFor("ignore.yaml")).toBe(configTemplates.ignore);
    expect(codeFor("doc-style.yaml")).toBe(configTemplates.doc_style);
  });

  it("renders an intro describing the config/cdmon/ layout", async () => {
    render(<Config api={fakeApi()} />);

    await screen.findByText("Unit file");
    // The intro names the generated coverage report + the layout pieces.
    expect(screen.getByText(/coverage\.rpt/)).toBeInTheDocument();
  });
});
