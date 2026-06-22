import { useCallback } from "react";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { SettingsData } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface ServerSettingsApi {
  serverSettings(): Promise<SettingsData>;
}

export interface SettingsProps {
  api?: ServerSettingsApi;
}

/** Render a list value (or a placeholder when empty). */
function listOrNone(values: string[], empty: string): string {
  return values.length > 0 ? values.join(", ") : empty;
}

/** The human label for each environment secret (presence only — never the value). */
const SECRET_LABELS: ReadonlyArray<{ key: keyof SettingsData["secrets"]; label: string }> = [
  { key: "admin_token_configured", label: "Admin token ($CDMON_ADMIN_TOKEN)" },
  { key: "database_url_set", label: "Database URL ($CDMON_DATABASE_URL)" },
  { key: "secret_key_set", label: "Secret key ($CDMON_SECRET_KEY)" },
];

/** The GLOBAL server settings page (EPIC SVR) — not per-repo. Shows the effective
 *  runtime settings (config/settings.yaml + env) and whether each environment secret
 *  is configured. Secrets are NEVER shown — only their presence. */
export function Settings({ api = apiClient }: SettingsProps) {
  const loader = useCallback(() => api.serverSettings(), [api]);
  const state = useApi<SettingsData>(loader, [loader]);

  const head = <h1>Settings</h1>;

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        {head}
        <p role="status">Loading settings…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        {head}
        <p role="alert" className="error">
          Failed to load settings: {state.message}
        </p>
      </section>
    );
  }

  const { settings, secrets } = state.data;
  const s = settings.server;
  const rows: ReadonlyArray<[string, string]> = [
    ["server.host", s.host],
    ["server.port", String(s.port)],
    ["server.log_level", s.log_level],
    ["server.trusted_hosts", s.trusted_hosts.join(", ")],
    ["server.cors.allow_origins", listOrNone(s.cors.allow_origins, "(disabled)")],
    [
      "server.rate_limit.requests_per_minute",
      s.rate_limit.requests_per_minute === null
        ? "(none)"
        : String(s.rate_limit.requests_per_minute),
    ],
    ["server.git.allowed_hosts", s.git.allowed_hosts.join(", ")],
    ["server.git.extra_allowed_hosts", listOrNone(s.git.extra_allowed_hosts, "(none)")],
    ["server.git.allow_file_scheme", String(s.git.allow_file_scheme)],
    [
      "server.git.clone_timeout_seconds",
      s.git.clone_timeout_seconds === null
        ? "(none)"
        : String(s.git.clone_timeout_seconds),
    ],
  ];

  return (
    <section>
      {head}
      <p className="config-intro">
        The effective runtime settings for the central server — resolved from{" "}
        <code>config/settings.yaml</code>, overlaid by the <code>CDMON_*</code>{" "}
        environment variables (env wins), falling back to the built-in defaults.
        Edit the file (or set the env var) and restart the server to change them.
        Secrets live in the environment and are shown only as configured / not.
      </p>

      <h2>Runtime (v{settings.version})</h2>
      <table className="coverage-tree settings-table">
        <thead>
          <tr>
            <th scope="col">Setting</th>
            <th scope="col">Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, value]) => (
            <tr key={key}>
              <th scope="row">
                <span className="file-name">{key}</span>
              </th>
              <td>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Secrets</h2>
      <p className="coverage-summary">
        Resolved from the environment — presence only, the values are never sent.
      </p>
      <ul className="settings-secrets">
        {SECRET_LABELS.map(({ key, label }) => {
          const configured = secrets[key];
          return (
            <li key={key}>
              <span
                className={`file-status ${configured ? "status-documented" : "status-undocumented"}`}
              >
                <span
                  className={`dot ${configured ? "dot--sync" : "dot--review"}`}
                  aria-hidden="true"
                />
                {label}: {configured ? "configured" : "not set"}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default Settings;
