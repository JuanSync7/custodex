import { describe, it, expect } from "vitest";
import {
  buildCoverageRows,
  dirPaths,
  isReadmePath,
  isRowVisible,
  partitionReadme,
} from "./grouping";
import type { CoverageFile } from "../types";

describe("isReadmePath", () => {
  it("matches a README basename regardless of directory or case", () => {
    expect(isReadmePath("README.md")).toBe(true);
    expect(isReadmePath("docs/guide/README.md")).toBe(true);
    expect(isReadmePath("readme.rst")).toBe(true);
    expect(isReadmePath("README")).toBe(true);
  });

  it("does not match non-README files (incl. README-prefixed names)", () => {
    expect(isReadmePath("src/cli.py")).toBe(false);
    expect(isReadmePath("docs/api/index.md")).toBe(false);
    expect(isReadmePath("README_TEMPLATE.md")).toBe(false);
    expect(isReadmePath("CHANGELOG.md")).toBe(false);
  });
});

describe("partitionReadme", () => {
  it("splits by the supplied path accessor, preserving order", () => {
    const items = [
      { path: "src/a.py" },
      { path: "README.md" },
      { path: "docs/b.md" },
      { path: "pkg/README.md" },
    ];
    const { main, readme } = partitionReadme(items, (i) => i.path);
    expect(main.map((i) => i.path)).toEqual(["src/a.py", "docs/b.md"]);
    expect(readme.map((i) => i.path)).toEqual(["README.md", "pkg/README.md"]);
  });
});

describe("buildCoverageRows", () => {
  const f = (path: string, status: CoverageFile["status"]): CoverageFile => ({
    path,
    language: "python",
    owners: status === "documented" ? ["doc"] : [],
    status,
    waived_reason: status === "waived" ? "generated" : null,
  });

  it("renders a directory hierarchy: dir rows precede their indented files", () => {
    const rows = buildCoverageRows([
      f("pkg/server/app.py", "documented"),
      f("pkg/cli.py", "undocumented"),
      f("setup.py", "documented"),
    ]);
    // Dirs precede files AT EACH LEVEL (a dir's whole subtree is emitted before
    // the level's files): pkg/ (d0) → server/ (d1) → app.py (d2) → cli.py (d1)
    // → setup.py (d0).
    expect(rows.map((r) => [r.kind, r.name, r.depth])).toEqual([
      ["dir", "pkg", 0],
      ["dir", "server", 1],
      ["file", "app.py", 2],
      ["file", "cli.py", 1],
      ["file", "setup.py", 0],
    ]);
  });

  it("rolls up descendant-leaf counts onto each directory node", () => {
    const rows = buildCoverageRows([
      f("pkg/a.py", "documented"),
      f("pkg/b.py", "undocumented"),
      f("pkg/sub/c.py", "waived"),
    ]);
    const pkg = rows.find((r) => r.kind === "dir" && r.name === "pkg")!;
    expect(pkg.counts).toEqual({ documented: 1, undocumented: 1, waived: 1 });
    const sub = rows.find((r) => r.kind === "dir" && r.name === "sub")!;
    expect(sub.counts).toEqual({ documented: 0, undocumented: 0, waived: 1 });
  });

  it("carries the original CoverageFile on each file row and the full path", () => {
    const file = f("pkg/cli.py", "undocumented");
    const rows = buildCoverageRows([file]);
    const leaf = rows.find((r) => r.kind === "file")!;
    expect(leaf.name).toBe("cli.py");
    expect(leaf.path).toBe("pkg/cli.py");
    expect(leaf.file).toBe(file);
  });

  it("returns an empty array for no files", () => {
    expect(buildCoverageRows([])).toEqual([]);
  });
});

describe("dirPaths + isRowVisible (collapse/expand)", () => {
  const file = (path: string): CoverageFile => ({
    path,
    language: "python",
    owners: [],
    status: "undocumented",
    waived_reason: null,
  });
  const rows = buildCoverageRows([
    file("pkg/server/app.py"),
    file("pkg/cli.py"),
    file("setup.py"),
  ]);

  it("dirPaths lists every directory node's path in tree order", () => {
    expect(dirPaths(rows)).toEqual(["pkg", "pkg/server"]);
  });

  it("collapsing a directory hides its whole subtree (but not the dir itself)", () => {
    const collapsed = new Set(["pkg"]);
    const visible = rows
      .filter((r) => isRowVisible(r, collapsed))
      .map((r) => [r.kind, r.name]);
    expect(visible).toEqual([
      ["dir", "pkg"],
      ["file", "setup.py"],
    ]);
  });

  it("collapsing a deeper directory hides only that subtree", () => {
    const collapsed = new Set(["pkg/server"]);
    const names = rows
      .filter((r) => isRowVisible(r, collapsed))
      .map((r) => r.name);
    expect(names).toEqual(["pkg", "server", "cli.py", "setup.py"]); // app.py hidden
  });

  it("an empty collapsed set shows every row (fully expanded default)", () => {
    expect(rows.every((r) => isRowVisible(r, new Set()))).toBe(true);
  });
});
