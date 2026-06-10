import { StrictMode } from "react";
import { HashRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

// The console island entry (EPIC ASTRO). Mirrors the retired dashboard
// `main.tsx`: a HashRouter (client routes stay `#/repos` and never shadow the
// API's real paths under the single-origin deploy) wraps the ported <App/>.
// Mounted `client:only="react"` from `src/pages/index.astro`, so the whole
// data-driven console hydrates on the client — no SSR.
export default function ConsoleApp() {
  return (
    <StrictMode>
      <HashRouter>
        <App />
      </HashRouter>
    </StrictMode>
  );
}
