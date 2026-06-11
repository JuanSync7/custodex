import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import ConnectionStatus from "./ConnectionStatus";

describe("ConnectionStatus", () => {
  it("reports Online when the server answers /health", async () => {
    const api = { ping: async () => ({ status: "ok" }) };
    render(<ConnectionStatus api={api} baseUrl="http://srv:33333" intervalMs={0} />);

    // Starts optimistic ("Linking…") then settles online once the probe resolves.
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/online/i),
    );
    expect(screen.getByRole("status")).toHaveTextContent("http://srv:33333");
  });

  it("reports Offline when the probe rejects", async () => {
    const api = {
      ping: async () => {
        throw new Error("connection refused");
      },
    };
    render(<ConnectionStatus api={api} baseUrl="/api" intervalMs={0} />);

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/offline/i),
    );
  });
});
