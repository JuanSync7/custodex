/// <reference types="astro/client" />

interface ImportMetaEnv {
  /** Single-origin API base. "" = same-origin root (the prod single-port deploy,
   *  where FastAPI serves both the API and this site). Unset → "/api" (astro dev
   *  proxy). Replaces the dashboard's VITE_API_BASE. */
  readonly PUBLIC_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
