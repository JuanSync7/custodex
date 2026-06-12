// Pure, framework-free helpers shared by the console views: a README/narrative
// partitioner and a coverage directory-tree flattener. Kept out of the page
// components so they are unit-testable without a DOM (and reused identically by
// Documents, the drift timeline, and Mapping).
import type { CoverageFile } from "../types";

/** True when a repo-relative path's basename is a README (README.md, README,
 * readme.rst, …). Case-insensitive; matches `readme` followed by a `.ext` or the
 * end of the name, so `README_TEMPLATE.md` (not a README) is excluded. */
export function isReadmePath(path: string): boolean {
  const base = (path.split("/").pop() ?? path).toLowerCase();
  return /^readme(\.|$)/.test(base);
}

/** Split a list into its README entries and the rest, preserving order. The
 * caller supplies how to read each item's path (a coverage file's `path`, a
 * document's `path`, a record's `doc_path`). */
export function partitionReadme<T>(
  items: readonly T[],
  pathOf: (item: T) => string,
): { main: T[]; readme: T[] } {
  const main: T[] = [];
  const readme: T[] = [];
  for (const item of items) {
    if (isReadmePath(pathOf(item))) readme.push(item);
    else main.push(item);
  }
  return { main, readme };
}

/** One row of the coverage hierarchy: either a directory node (with a roll-up of
 * its descendant leaves by status) or a file leaf carrying its `CoverageFile`. */
export interface CoverageTreeRow {
  kind: "dir" | "file";
  /** A directory's segment name, or a file's basename. */
  name: string;
  /** Full repo-relative path of this node (used as a stable React key). */
  path: string;
  /** Nesting depth — 0 at the top level — driving the row's indentation. */
  depth: number;
  /** Present only on a "file" row. */
  file?: CoverageFile;
  /** Present only on a "dir" row: its descendant-leaf counts by status. */
  counts?: CoverageCounts;
}

export interface CoverageCounts {
  documented: number;
  undocumented: number;
  waived: number;
}

interface DirNode {
  dirs: Map<string, DirNode>;
  files: CoverageFile[];
}

function newDir(): DirNode {
  return { dirs: new Map(), files: [] };
}

function leafCounts(node: DirNode): CoverageCounts {
  const counts: CoverageCounts = { documented: 0, undocumented: 0, waived: 0 };
  const walk = (n: DirNode): void => {
    for (const f of n.files) counts[f.status] += 1;
    for (const child of n.dirs.values()) walk(child);
  };
  walk(node);
  return counts;
}

/** Turn a FLAT list of coverage files into an ordered, depth-tagged tree: each
 * directory becomes a row (with descendant counts) immediately followed by its
 * children, directories before files, alphabetically within a level. This is the
 * "proper hierarchy" the coverage view renders instead of flat relative paths. */
export function buildCoverageRows(files: readonly CoverageFile[]): CoverageTreeRow[] {
  const root = newDir();
  for (const file of files) {
    const parts = file.path.split("/");
    let node = root;
    for (let i = 0; i < parts.length - 1; i += 1) {
      const seg = parts[i];
      let child = node.dirs.get(seg);
      if (!child) {
        child = newDir();
        node.dirs.set(seg, child);
      }
      node = child;
    }
    node.files.push(file);
  }

  const rows: CoverageTreeRow[] = [];
  const walk = (node: DirNode, depth: number, prefix: string): void => {
    const dirNames = [...node.dirs.keys()].sort((a, b) => a.localeCompare(b));
    for (const name of dirNames) {
      const child = node.dirs.get(name)!;
      const path = prefix ? `${prefix}/${name}` : name;
      rows.push({ kind: "dir", name, path, depth, counts: leafCounts(child) });
      walk(child, depth + 1, path);
    }
    const sortedFiles = [...node.files].sort((a, b) =>
      a.path.localeCompare(b.path),
    );
    for (const file of sortedFiles) {
      const name = file.path.split("/").pop() ?? file.path;
      rows.push({ kind: "file", name, path: file.path, depth, file });
    }
  };
  walk(root, 0, "");
  return rows;
}
