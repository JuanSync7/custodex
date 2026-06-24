// @ts-check
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import mdx from "@astrojs/mdx";

// One Astro app for custodex (EPIC ASTRO). Static output so a single
// FastAPI process serves the API and this site on one port (`StaticFiles` over
// `frontend/dist`). React islands hydrate the interactive console (ASTRO-03);
// markdown/MDX renders the EPIC-R wikis natively (ASTRO-02). Asset dir is the
// Astro default `_astro/` — which the server serves verbatim and which never
// collides with the API's real paths (`/health`, `/repos*`, `/config*`, ...).
export default defineConfig({
  // The public showcase (PUBLIC_SHOWCASE build) is served at this custom domain on
  // GitHub Pages (see .github/workflows/deploy-pages.yml + public/CNAME). `site` is
  // the deploy origin Astro uses to build absolute URLs — the Layout reads it for
  // the canonical + OpenGraph/Twitter link-preview tags.
  site: "https://custodex.juansync.dev",
  integrations: [react(), mdx()],
  output: "static",
  build: { assets: "_astro" },
});
