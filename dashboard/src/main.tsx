import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

// A HASH router (#/repos/…) keeps every client route inside the URL fragment, so
// when FastAPI serves this SPA on the SAME origin as the API (single-port deploy
// on :33333), a deep link / hard refresh never collides with a real API route
// like GET /repos/{id}/coverage — the server only ever sees `/`. Tests inject
// their own router (MemoryRouter), so this choice is production-only.

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("root element #root not found");
}

createRoot(rootEl).render(
  <StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </StrictMode>,
);
