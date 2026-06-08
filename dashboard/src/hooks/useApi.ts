// A tiny loading/error/data hook so pages don't re-implement the fetch dance.
// The `loader` is an async thunk; `deps` re-run it (like useEffect deps). Cancels
// a stale in-flight load so a fast filter change can't overwrite newer results.
import { useEffect, useState } from "react";

export type AsyncState<T> =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; data: T };

/**
 * Run `loader()` whenever `deps` change, exposing loading/error/ready phases.
 * `loader` must be stable for the given `deps` (wrap in useCallback or build it
 * inline from primitive deps) — the eslint deps rule is satisfied by listing
 * `loader` itself in `deps`.
 */
export function useApi<T>(
  loader: () => Promise<T>,
  deps: readonly unknown[],
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });

    loader()
      .then((data) => {
        if (!cancelled) setState({ phase: "ready", data });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err);
        setState({ phase: "error", message });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
