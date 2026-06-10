import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The console islands are pure React components, so they test under a standalone
// Vitest config (jsdom + Testing Library) — independent of the Astro build, just
// like the old dashboard. `setupFiles` registers jest-dom + per-test cleanup.
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/console/test/setup.ts"],
    css: false,
    include: ["src/console/**/*.test.{ts,tsx}"],
  },
});
