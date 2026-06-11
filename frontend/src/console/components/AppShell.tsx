// The application base: a fixed instrument rail + sticky topbar wrapping the
// routed views. It is the single frame that holds the live API connection and
// the navigation between every API-driven view. Pages render INTO `children`.
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

/** Derive the topbar page label from the current route. */
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
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <BrandMark className="brand__mark" aria-hidden />
          <span className="brand__text">
            <span className="brand__title">drift console</span>
            <span className="brand__sub">code · doc · monitor</span>
          </span>
        </div>

        <div className="rail__label">Console</div>
        <nav className="nav" aria-label="primary">
          <Link
            to="/"
            className={`nav__item${onFleet ? " nav__item--active" : ""}`}
            aria-current={onFleet ? "page" : undefined}
          >
            <FleetIcon className="nav__icon" aria-hidden />
            Fleet
          </Link>
        </nav>

        <div className="rail__label">Reference</div>
        <nav className="nav" aria-label="reference">
          <Link
            to="/config"
            className={`nav__item${onConfig ? " nav__item--active" : ""}`}
            aria-current={onConfig ? "page" : undefined}
          >
            <DocIcon className="nav__icon" aria-hidden />
            Format
          </Link>
          <a className="nav__item" href="/wiki/features">
            <DocIcon className="nav__icon" aria-hidden />
            Wiki
          </a>
          <a className="nav__item" href={docsHref} target="_blank" rel="noreferrer">
            <DocIcon className="nav__icon" aria-hidden />
            API Docs
            <ExternalIcon
              className="nav__icon"
              style={{ marginLeft: "auto", width: 13, height: 13 }}
              aria-hidden
            />
          </a>
          <a className="nav__item" href={openApiHref} target="_blank" rel="noreferrer">
            <PulseIcon className="nav__icon" aria-hidden />
            OpenAPI
            <ExternalIcon
              className="nav__icon"
              style={{ marginLeft: "auto", width: 13, height: 13 }}
              aria-hidden
            />
          </a>
        </nav>

        <div className="rail__spacer" />

        <div className="rail__label">Central server</div>
        <ConnectionStatus />

        <div className="rail__foot">
          <span>v0.1.0</span>
          <span>FastAPI · E-06</span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="crumb">
            <span className="crumb__root">code-doc-monitor</span>
            <span className="crumb__sep">/</span>
            <span className="crumb__here">{pageLabel(pathname)}</span>
          </div>
          <a
            className="chip"
            href={docsHref}
            target="_blank"
            rel="noreferrer"
            style={{ marginLeft: "auto" }}
          >
            View API
            <ExternalIcon style={{ width: 12, height: 12 }} aria-hidden />
          </a>
        </header>
        <main className="canvas">{children}</main>
      </div>
    </div>
  );
}

export default AppShell;
