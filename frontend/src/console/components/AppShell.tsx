// The application base: a single horizontal COMMAND BAR across the top wrapping
// the routed views (the "Atlas" shell — no left rail). It is the one frame that
// holds the live API connection and the navigation between every API-driven
// view. Pages render INTO `children`.
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import ConnectionStatus from "./ConnectionStatus";
import { BrandMark, DocIcon, ExternalIcon, FleetIcon, PulseIcon } from "./icons";

/** The API base, used to deep-link the server's own Swagger docs. Default "" =
 *  same-origin (single-port deploy), so the Swagger link resolves to `/docs`. */
function apiBase(): string {
  const fromEnv = import.meta.env?.PUBLIC_API_BASE;
  return typeof fromEnv === "string" && fromEnv.length > 0 ? fromEnv : "";
}

/** Derive the current page label from the route (names the main landmark). */
function pageLabel(pathname: string): string {
  if (pathname === "/" || pathname === "") return "Fleet Overview";
  if (pathname.endsWith("/coverage")) return "Coverage Basket";
  if (pathname.endsWith("/health")) return "Health & Telemetry";
  if (pathname.endsWith("/documents")) return "Documents";
  if (pathname.endsWith("/mapping")) return "Mapping";
  if (pathname === "/config") return "Config Format";
  if (pathname.startsWith("/repos")) return "Drift Timeline";
  return "Console";
}

export interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { pathname } = useLocation();
  const onFleet = pathname === "/" || pathname.startsWith("/repos");
  const onConfig = pathname === "/config";
  const root = apiBase().replace(/\/$/, "");
  const docsHref = `${root}/docs`;
  const openApiHref = `${root}/openapi.json`;

  return (
    <div className="app">
      <header className="topnav" role="banner">
        <Link to="/" className="topnav__brand" aria-label="code-doc-monitor console">
          <BrandMark className="topnav__brandmark" aria-hidden />
          <span className="topnav__word">
            <span className="topnav__title">drift console</span>
            <span className="topnav__sub">code · doc · monitor</span>
          </span>
        </Link>

        <nav className="topnav__nav" aria-label="primary">
          <Link
            to="/"
            className={`topnav__link${onFleet ? " topnav__link--active" : ""}`}
            aria-current={onFleet ? "page" : undefined}
          >
            <FleetIcon className="nav__icon" aria-hidden />
            Fleet
          </Link>
          <Link
            to="/config"
            className={`topnav__link${onConfig ? " topnav__link--active" : ""}`}
            aria-current={onConfig ? "page" : undefined}
          >
            <DocIcon className="nav__icon" aria-hidden />
            Format
          </Link>
          <a className="topnav__link" href="/wiki/features">
            <DocIcon className="nav__icon" aria-hidden />
            Wiki
          </a>
        </nav>

        <div className="topnav__spacer" />

        <nav className="topnav__nav topnav__nav--ref" aria-label="reference">
          <a className="topnav__link" href={docsHref} target="_blank" rel="noreferrer">
            API Docs
            <ExternalIcon className="nav__icon" aria-hidden />
          </a>
          <a className="topnav__link" href={openApiHref} target="_blank" rel="noreferrer">
            <PulseIcon className="nav__icon" aria-hidden />
            OpenAPI
          </a>
        </nav>

        <span className="topnav__div" aria-hidden />
        <ConnectionStatus />
      </header>

      <main className="canvas" aria-label={pageLabel(pathname)}>
        {children}
      </main>
    </div>
  );
}

export default AppShell;
