import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import Settings, { type ServerSettingsApi } from "./Settings";
import { serverSettings } from "../test/fixtures";
import type { SettingsData } from "../types";

function fakeApi(overrides: Partial<ServerSettingsApi> = {}): ServerSettingsApi {
  return {
    serverSettings: async (): Promise<SettingsData> => serverSettings,
    ...overrides,
  };
}

describe("Settings page", () => {
  it("shows a loading state before the promise resolves", () => {
    const never = new Promise<SettingsData>(() => {});
    render(<Settings api={fakeApi({ serverSettings: () => never })} />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows an error state when the client rejects", async () => {
    render(
      <Settings
        api={fakeApi({
          serverSettings: async () => {
            throw new Error("settings boom");
          },
        })}
      />,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/failed to load settings/i);
    expect(alert).toHaveTextContent(/settings boom/);
  });

  it("renders the resolved runtime settings", async () => {
    render(<Settings api={fakeApi()} />);
    expect(await screen.findByText("server.host")).toBeInTheDocument();
    // the host/port values are shown
    expect(screen.getByText("0.0.0.0")).toBeInTheDocument();
    expect(screen.getByText("33333")).toBeInTheDocument();
    // an empty/none knob renders a placeholder, not an empty cell
    expect(screen.getByText("(disabled)")).toBeInTheDocument(); // cors off
  });

  it("reports secret presence without ever showing a value", async () => {
    render(
      <Settings
        api={fakeApi({
          serverSettings: async () => ({
            ...serverSettings,
            secrets: {
              admin_token_configured: true,
              database_url_set: false,
              secret_key_set: false,
            },
          }),
        })}
      />,
    );
    // the admin token is reported configured...
    expect(await screen.findByText(/Admin token.*: configured/)).toBeInTheDocument();
    // ...and an unset secret reads "not set"
    expect(screen.getByText(/Secret key.*: not set/)).toBeInTheDocument();
  });
});
