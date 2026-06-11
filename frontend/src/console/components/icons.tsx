// Hand-drawn line icons (currentColor, 1.6 stroke) — no icon-font dependency, so
// the bundle stays small and the glyphs inherit the instrument-panel palette.
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function base(props: IconProps) {
  return {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    ...props,
  };
}

/** Stacked layers — the fleet / repos overview. */
export function FleetIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3 3 7.5 12 12l9-4.5L12 3Z" />
      <path d="M3 12l9 4.5L21 12" />
      <path d="M3 16.5 12 21l9-4.5" />
    </svg>
  );
}

/** A signal/heartbeat trace — health & telemetry. */
export function PulseIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 12h4l2-6 4 12 2-6h6" />
    </svg>
  );
}

/** A document with a check — coverage / docs. */
export function DocIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
      <path d="m9 14 2 2 3-4" />
    </svg>
  );
}

/** An external arrow — open the API docs. */
export function ExternalIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 4h6v6" />
      <path d="M20 4 11 13" />
      <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
    </svg>
  );
}

/** The wordmark glyph — two diverging traces meeting a node (code↔doc drift). */
export function BrandMark(props: IconProps) {
  return (
    <svg viewBox="0 0 32 32" fill="none" {...props}>
      <rect
        x="1"
        y="1"
        width="30"
        height="30"
        rx="7"
        stroke="var(--accent)"
        strokeOpacity="0.4"
        strokeWidth="1.4"
      />
      <path
        d="M7 11c5 0 5 4 9 4M7 21c5 0 5-4 9-4"
        stroke="var(--accent)"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <circle cx="22.5" cy="15" r="3.2" fill="var(--sync)" />
      <circle cx="22.5" cy="15" r="6" stroke="var(--sync)" strokeOpacity="0.3" strokeWidth="1.2" />
    </svg>
  );
}
