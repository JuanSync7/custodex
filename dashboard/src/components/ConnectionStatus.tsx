// The shell's live link to the central server. Polls the OPEN `/health` route and
// renders a connecting / online / offline signal — so an operator can see at a
// glance whether the console is actually talking to the API. `api` and the poll
// interval are injectable so tests run deterministically with no real network.
import { useEffect, useRef, useState } from "react";
import { apiClient } from "../api/client";

export interface PingApi {
  ping(): Promise<{ status: string }>;
}

type Phase = "connecting" | "online" | "offline";

export interface ConnectionStatusProps {
  /** Injected client; defaults to the shared singleton. */
  api?: PingApi;
  /** The base URL shown to the operator (display only). */
  baseUrl?: string;
  /** Poll cadence in ms (0 disables polling; one probe still runs on mount). */
  intervalMs?: number;
}

function displayBase(): string {
  const fromEnv = import.meta.env?.VITE_API_BASE;
  if (typeof fromEnv === "string") {
    // "" or "/" = same-origin root (single-port deploy): show the live origin.
    if (fromEnv === "" || fromEnv === "/")
      return typeof window !== "undefined" ? window.location.host : "same-origin";
    return fromEnv;
  }
  return "/api";
}

const PHASE_COPY: Record<Phase, string> = {
  connecting: "Linking…",
  online: "Online",
  offline: "Offline",
};
const PHASE_TONE: Record<Phase, string> = {
  connecting: "review",
  online: "sync",
  offline: "drift",
};

export function ConnectionStatus({
  api = apiClient,
  baseUrl,
  intervalMs = 15000,
}: ConnectionStatusProps) {
  const [phase, setPhase] = useState<Phase>("connecting");
  const [latency, setLatency] = useState<number | null>(null);
  const url = baseUrl ?? displayBase();
  // A monotonic-ish clock that still works under fake timers / jsdom.
  const now = () =>
    typeof performance !== "undefined" ? performance.now() : 0;
  const startedRef = useRef(0);

  useEffect(() => {
    let cancelled = false;

    async function probe() {
      startedRef.current = now();
      try {
        const res = await api.ping();
        if (cancelled) return;
        setLatency(Math.max(0, Math.round(now() - startedRef.current)));
        setPhase(res?.status === "ok" || res ? "online" : "offline");
      } catch {
        if (cancelled) return;
        setLatency(null);
        setPhase("offline");
      }
    }

    void probe();
    const id =
      intervalMs > 0 ? setInterval(() => void probe(), intervalMs) : undefined;

    return () => {
      cancelled = true;
      if (id !== undefined) clearInterval(id);
    };
  }, [api, intervalMs]);

  const tone = PHASE_TONE[phase];

  return (
    <div className="conn" role="status" aria-label="central server connection">
      <div className="conn__row">
        <span className={`dot dot--${tone}${phase === "online" ? " dot--live" : ""}`} />
        <span className="conn__state" style={{ color: `var(--${tone})` }}>
          {PHASE_COPY[phase]}
        </span>
        {phase === "online" && latency !== null ? (
          <span className="conn__meta">{latency}ms</span>
        ) : null}
      </div>
      <div className="conn__url" title={url}>
        {url}
      </div>
    </div>
  );
}

export default ConnectionStatus;
