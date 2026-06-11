import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import SyncControls, { type SyncControlsApi } from "./SyncControls";
import { ApiError } from "../api/client";
import type { SyncMode, SyncRun } from "../types";
import { syncRunGit, syncRunLocal } from "../test/fixtures";

interface SyncCall {
  repoId: string;
  mode: SyncMode;
  token: string;
}

/** A fake client capturing syncRepo() calls; syncState defaults to git fixture. */
function fakeApi(overrides: Partial<SyncControlsApi> = {}) {
  const syncCalls: SyncCall[] = [];
  const api: SyncControlsApi = {
    syncState: async (): Promise<SyncRun | null> => syncRunGit,
    syncRepo: async (
      repoId: string,
      mode: SyncMode,
      token: string,
    ): Promise<SyncRun> => {
      syncCalls.push({ repoId, mode, token });
      return mode === "git" ? syncRunGit : syncRunLocal;
    },
    ...overrides,
  };
  return { api, syncCalls };
}

describe("SyncControls", () => {
  it("renders a never-synced state when sync-state is null", async () => {
    const { api } = fakeApi({ syncState: async () => null });
    render(<SyncControls repoId="octo/docs" api={api} token="tok" />);

    expect(await screen.findByText(/never synced/i)).toBeInTheDocument();
  });

  it("renders the loaded badge, commits-ahead, drift count and coverage", async () => {
    const { api } = fakeApi();
    render(<SyncControls repoId="acme/widget" api={api} token="tok" />);

    // syncRunGit has 2 drifts → the drift headline wins over commits-ahead.
    expect(await screen.findByText(/2 drift/i)).toBeInTheDocument();
    expect(screen.getByText(/82% coverage/i)).toBeInTheDocument();
    expect(screen.getByText(/2026-06-05T12:00:09Z/)).toBeInTheDocument();
  });

  it("shows 'In sync' with no drift and zero commits ahead", async () => {
    const { api } = fakeApi({ syncState: async () => syncRunLocal });
    render(<SyncControls repoId="acme/widget" api={api} token="tok" />);

    expect(await screen.findByText(/in sync/i)).toBeInTheDocument();
    expect(screen.getByText(/100% coverage/i)).toBeInTheDocument();
  });

  it("shows 'N commits ahead' when ahead but no drift", async () => {
    const ahead: SyncRun = {
      ...syncRunGit,
      commits_ahead: 5,
      drift: { ok: true, drift_count: 0, by_kind: {}, coverage_percent: 90 },
    };
    const { api } = fakeApi({ syncState: async () => ahead });
    render(<SyncControls repoId="acme/widget" api={api} token="tok" />);

    expect(await screen.findByText(/5 commits ahead/i)).toBeInTheDocument();
  });

  it("clicking Sync (main) posts git + token, updates state and fires onSynced", async () => {
    // Start from a never-synced state so the update is observable.
    const { api, syncCalls } = fakeApi({ syncState: async () => null });
    let synced: SyncRun | null = null;
    render(
      <SyncControls
        repoId="acme/widget"
        api={api}
        token="s3cret"
        onSynced={(r) => {
          synced = r;
        }}
      />,
    );

    await screen.findByText(/never synced/i);
    fireEvent.click(screen.getByRole("button", { name: /sync \(main\)/i }));

    await waitFor(() => expect(syncCalls).toHaveLength(1));
    expect(syncCalls[0]).toEqual({
      repoId: "acme/widget",
      mode: "git",
      token: "s3cret",
    });
    // State adopts the returned run (git → 2 drift).
    expect(await screen.findByText(/2 drift/i)).toBeInTheDocument();
    expect(synced).toEqual(syncRunGit);
  });

  it("clicking Sync (local) posts the local mode", async () => {
    const { api, syncCalls } = fakeApi({ syncState: async () => null });
    render(<SyncControls repoId="acme/widget" api={api} token="tok" />);

    await screen.findByText(/never synced/i);
    fireEvent.click(screen.getByRole("button", { name: /sync \(local\)/i }));

    await waitFor(() => expect(syncCalls).toHaveLength(1));
    expect(syncCalls[0].mode).toBe("local");
  });

  it("syncs with an empty token against an OPEN repo (no input shown)", async () => {
    // L-01: a standalone/open repo accepts a token-less sync. The button is NOT
    // hard-guarded on an empty token, and no token input is shown upfront.
    const { api, syncCalls } = fakeApi({ syncState: async () => null });
    render(<SyncControls repoId="acme/widget" api={api} />);

    await screen.findByText(/never synced/i);
    // No token input upfront (it only appears after an auth error).
    expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /sync \(main\)/i }));
    // The sync IS attempted, with an empty token (open repo).
    await waitFor(() => expect(syncCalls).toHaveLength(1));
    expect(syncCalls[0].token).toBe("");
    // Still no token input, and no error.
    expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reveals the token input + auth message on a 403, then a typed token works", async () => {
    // L-01: a token-protected repo returns 403 to the token-less attempt; THEN the
    // input is revealed and a typed token retries successfully.
    const syncCalls: SyncCall[] = [];
    let reject = true;
    const api: SyncControlsApi = {
      syncState: async () => null,
      syncRepo: async (repoId, mode, token) => {
        if (reject) {
          throw new ApiError(403, "/api/repos/acme/widget/sync");
        }
        syncCalls.push({ repoId, mode, token });
        return syncRunGit;
      },
    };
    render(<SyncControls repoId="acme/widget" api={api} />);

    await screen.findByText(/never synced/i);
    // No input before the auth error.
    expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /sync \(main\)/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/auth invalid/i);
    // The token input is now revealed.
    expect(await screen.findByLabelText("Token")).toBeInTheDocument();

    // Typing a token and retrying succeeds.
    reject = false;
    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "typed-tok" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sync \(main\)/i }));
    await waitFor(() => expect(syncCalls).toHaveLength(1));
    expect(syncCalls[0].token).toBe("typed-tok");
  });

  it("passes syncKind to syncState so the header is scoped to the active source", async () => {
    const stateCalls: Array<string | undefined> = [];
    const { api } = fakeApi({
      syncState: async (_repoId: string, syncKind?: SyncMode) => {
        stateCalls.push(syncKind);
        return syncKind === "local" ? syncRunLocal : syncRunGit;
      },
    });
    const { rerender } = render(
      <SyncControls repoId="acme/widget" api={api} token="tok" syncKind="git" />,
    );

    // git source → the git fixture's drift headline.
    expect(await screen.findByText(/2 drift/i)).toBeInTheDocument();
    expect(stateCalls).toContain("git");

    // Switching the host's kind re-loads scoped to local (in sync, 100%), and the
    // stale git run does NOT linger.
    rerender(
      <SyncControls repoId="acme/widget" api={api} token="tok" syncKind="local" />,
    );
    expect(await screen.findByText(/in sync/i)).toBeInTheDocument();
    expect(screen.getByText(/100% coverage/i)).toBeInTheDocument();
    expect(stateCalls).toContain("local");
  });

  it("surfaces an auth message on an ApiError 403 (host-supplied token)", async () => {
    const { api } = fakeApi({
      syncState: async () => null,
      syncRepo: async () => {
        throw new ApiError(403, "/api/repos/acme/widget/sync");
      },
    });
    render(<SyncControls repoId="acme/widget" api={api} token="wrong" />);

    await screen.findByText(/never synced/i);
    fireEvent.click(screen.getByRole("button", { name: /sync \(main\)/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/auth invalid/i);
    // The host supplies the token, so no local input is ever shown.
    expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();
  });
});
