import ConsoleApp from "./ConsoleApp";
import { makeDemoFetch } from "./demo/demoFetch";

// The showcase demo (juansync.dev). Installs the mock `fetch` BEFORE the console's
// shared client makes any call — the client does a lazy `globalThis.fetch` lookup,
// so swapping it here makes the REAL <ConsoleApp/> run against the baked demo
// dataset with no backend. Loaded `client:only` from pages/demo.astro, so this
// global swap only happens on the /demo document and never affects other pages.
if (typeof globalThis !== "undefined" && typeof globalThis.fetch === "function") {
  globalThis.fetch = makeDemoFetch();
}

/** The real console, wired to sample data, with a clear "demo" ribbon. */
export default function DemoConsole() {
  return (
    <>
      <ConsoleApp />
      <aside className="demo-ribbon" role="note">
        <span className="demo-ribbon__dot" aria-hidden="true" />
        <span>
          <strong>Demo</strong> — sample data, no backend. The real Custodex console.
        </span>
        <a href="https://github.com/JuanSync7/custodex">Source ↗</a>
      </aside>
    </>
  );
}
