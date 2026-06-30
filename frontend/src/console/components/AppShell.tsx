// The application base: a left side NAV BAR (the "Atlas" rail) wrapping the
// routed views. It is the one frame that holds the live API connection and the
// navigation between every API-driven view. Pages render INTO `children`.
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import ConnectionStatus from "./ConnectionStatus";
import {
  BrandMark,
  DocIcon,
  ExternalIcon,
  FleetIcon,
  GearIcon,
  PulseIcon,
} from "./icons";

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
  if (pathname.endsWith("/dependencies")) return "Dependencies";
  if (pathname.endsWith("/ownership")) return "Ownership";
  if (pathname.endsWith("/worklist")) return "Worklist";
  if (pathname.endsWith("/mapping")) return "Mapping";
  if (pathname === "/config") return "Config Format";
  if (pathname === "/settings") return "Settings";
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
  const onSettings = pathname === "/settings";
  const root = apiBase().replace(/\/$/, "");
  const docsHref = `${root}/docs`;
  const openApiHref = `${root}/openapi.json`;

  return (
    <div className="app">
      <aside className="rail">
        <Link to="/" className="brand" aria-label="Custodex console">
          <BrandMark className="brand__mark" aria-hidden />
          <span className="brand__text">
            <span className="brand__title">Custodex</span>
            <span className="brand__sub">code · doc · custody</span>
          </span>
        </Link>

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
          <Link
            to="/config"
            className={`nav__item${onConfig ? " nav__item--active" : ""}`}
            aria-current={onConfig ? "page" : undefined}
          >
            <DocIcon className="nav__icon" aria-hidden />
            Format
          </Link>
          <Link
            to="/settings"
            className={`nav__item${onSettings ? " nav__item--active" : ""}`}
            aria-current={onSettings ? "page" : undefined}
          >
            <GearIcon className="nav__icon" aria-hidden />
            Settings
          </Link>
        </nav>

        <div className="rail__label">Reference</div>
        <nav className="nav" aria-label="reference">
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

      <main className="canvas" aria-label={pageLabel(pathname)}>
        {children}
      </main>
    </div>
  );
}

export default AppShell;
