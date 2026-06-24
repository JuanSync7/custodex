import { useCallback } from "react";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";

/** The four canonical template strings the server serves at /config/templates. */
export interface ConfigTemplates {
  unit: string;
  index: string;
  ignore: string;
  doc_style: string;
}

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface ConfigApi {
  configTemplates(): Promise<ConfigTemplates>;
}

export interface ConfigProps {
  api?: ConfigApi;
}

/** The labeled code blocks, in display order, mapped to their template key. */
const BLOCKS: ReadonlyArray<{ key: keyof ConfigTemplates; label: string }> = [
  { key: "unit", label: "Unit file" },
  { key: "index", label: "index.yaml" },
  { key: "ignore", label: "ignore.yaml" },
  { key: "doc_style", label: "doc-style.yaml" },
];

/** The GLOBAL config-format reference page (W-02) — not per-repo. Fetches the
 *  canonical config/cdmon/ templates and renders each in a labeled code block. */
export function Config({ api = apiClient }: ConfigProps) {
  const loader = useCallback(() => api.configTemplates(), [api]);
  const state = useApi<ConfigTemplates>(loader, [loader]);

  const head = (
    <h1>Config format</h1>
  );

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        {head}
        <p role="status">Loading templates…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        {head}
        <p role="alert" className="error">
          Failed to load templates: {state.message}
        </p>
      </section>
    );
  }

  const templates = state.data;

  return (
    <section>
      {head}
      <p className="config-intro">
        A repo describes itself to <code>cdx</code> under{" "}
        <code>config/cdmon/</code>: an <code>index.yaml</code> lists the documents
        and the code they own, one <code>*.yaml</code> per unit groups related
        code surfaces, <code>ignore.yaml</code> excludes paths from coverage, and{" "}
        <code>doc-style.yaml</code> points each audience at a writing template.
        Coverage is reported back into the generated{" "}
        <code>coverage.rpt</code>. The canonical templates below round-trip through
        their loaders — copy them to scaffold a new <code>config/cdmon/</code>.
      </p>

      <div className="config-templates">
        {BLOCKS.map(({ key, label }) => (
          <figure key={key} className="config-template panel">
            <figcaption className="config-template__label">{label}</figcaption>
            <pre className="config-code">
              <code>{templates[key]}</code>
            </pre>
          </figure>
        ))}
      </div>
    </section>
  );
}

export default Config;
