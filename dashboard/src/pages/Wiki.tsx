import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
import { useApi } from "../hooks/useApi";
import { DocIcon } from "../components/icons";
import type { WikiPayload, WikiSection } from "../types";

/** The slice of the API this page needs — fakeable in tests (no network). */
export interface WikiApi {
  wiki(): Promise<WikiPayload>;
}

export interface WikiProps {
  api?: WikiApi;
}

/**
 * A cheap "topics" count for a section's rail badge: the number of headings in
 * the pre-rendered HTML fragment (`<h1>..<h6>`). Falls back to 0 when a section
 * carries no headings (e.g. a bare table). Pure string scan — no DOM parse (K10).
 */
function topicCount(html: string): number {
  const matches = html.match(/<h[1-6][\s>]/gi);
  return matches ? matches.length : 0;
}

/**
 * The GLOBAL Feature Wiki page (R-09) — not per-repo. Fetches the four committed
 * EPIC-R wikis as pre-rendered HTML (`api.wiki()`), then renders a docs layout:
 * a LEFT section rail (the wikis, the selected one highlighted, with a per-section
 * topic-count badge) + a RIGHT prose pane injecting the selected section's HTML.
 * Section switching is client-side (one fetch). Loading / error / empty states.
 */
export function Wiki({ api = apiClient }: WikiProps) {
  const loader = useCallback(() => api.wiki(), [api]);
  const state = useApi<WikiPayload>(loader, [loader]);

  // The selected section id; null defers to "the first section" so the default
  // tracks the freshly-loaded payload without an effect (no stale selection).
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const head = <h1>Feature Wiki</h1>;

  if (state.phase === "loading") {
    return (
      <section aria-busy="true">
        {head}
        <p role="status">Loading wiki…</p>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section>
        {head}
        <p role="alert" className="error">
          Failed to load wiki: {state.message}
        </p>
      </section>
    );
  }

  const sections = state.data.sections;

  if (sections.length === 0) {
    return (
      <section>
        {head}
        <div className="empty">
          <div className="empty__mark">⌀</div>
          No wiki available — run <code>cdmon wiki</code> to generate the feature
          wikis, then commit them so the console can surface them here.
        </div>
      </section>
    );
  }

  // Resolve the active section: the selected one, or the first as the default.
  const active: WikiSection =
    sections.find((s) => s.id === selectedId) ?? sections[0];

  return (
    <section className="wiki">
      {head}
      <p className="wiki-intro">
        The committed feature wikis — the catalog, the traceability matrix, and
        the test / source references — rendered for the console. Pick a section
        on the left to read it.
      </p>

      <div className="wiki-layout">
        <nav className="wiki-rail" aria-label="wiki sections">
          {sections.map((section) => {
            const isActive = section.id === active.id;
            const count = topicCount(section.html);
            return (
              <button
                key={section.id}
                type="button"
                className={`wiki-rail__item${
                  isActive ? " wiki-rail__item--active" : ""
                }`}
                aria-current={isActive ? "true" : undefined}
                onClick={() => setSelectedId(section.id)}
              >
                <DocIcon className="wiki-rail__icon" aria-hidden />
                <span className="wiki-rail__title">{section.title}</span>
                {count > 0 && (
                  <span className="wiki-rail__count" aria-hidden>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <article className="wiki-pane panel">
          <header className="wiki-pane__head">
            <h2>{active.title}</h2>
          </header>
          {/* The HTML is a SAFE fragment pre-rendered + sanitized by the server's
              own markdown renderer (R-09 contract) — injected verbatim. */}
          <div
            className="wiki-prose"
            dangerouslySetInnerHTML={{ __html: active.html }}
          />
        </article>
      </div>
    </section>
  );
}

export default Wiki;
