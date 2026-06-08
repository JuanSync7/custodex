import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The dashboard reads the EPIC-E FastAPI server. In dev, `/api/*` is proxied to
// the local uvicorn server (the `/api` prefix is stripped so it hits `/repos`,
// `/repos/{id}/status`, ...). In prod the app is served behind a reverse proxy
// that exposes the API under `VITE_API_BASE` (default `/api`).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // bind 0.0.0.0 so the dev dashboard is reachable from other machines
    proxy: {
      "/api": {
        target: "http://127.0.0.1:33333",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
