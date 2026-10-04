// Nautiq's own icon set: harbour and signal-flag geometry on a 24-unit grid,
// one 1.75 stroke, round caps. Drawn for this product; no third-party glyphs.
import type { SVGProps } from "react";

export type IconName =
  | "hailer" | "spyglass" | "buoy" | "chart" | "voyage" | "pennant" | "float"
  | "ripple" | "waves" | "windsock" | "current" | "thermo" | "sounding" | "logbook"
  | "arrow" | "back" | "down" | "close" | "plus" | "minus" | "layers" | "locate"
  | "outbound" | "clock" | "check" | "info" | "menu" | "pin" | "compass" | "bell"
  | "anchorline" | "export" | "lock" | "play" | "pause";

const paths: Record<IconName, React.ReactNode> = {
  // Loud-hailer: ask in your own words
  hailer: (
    <>
      <path d="M4 10.2v3.6c0 .5.4.9.9.9H7l8.6 4.1c.6.3 1.4-.2 1.4-.9V6.1c0-.7-.8-1.2-1.4-.9L7 9.3H4.9c-.5 0-.9.4-.9.9Z" />
      <path d="M7 14.7 8.3 19" />
      <path d="M19.6 9.4c.9.7.9 4.5 0 5.2" />
    </>
  ),
  // Spyglass: search
  spyglass: (
    <>
      <path d="m3.6 15.4 9.8-9.8 4 4-9.8 9.8z" />
      <path d="m13.4 5.6 1.9-1.9 4 4-1.9 1.9" />
      <path d="M6.2 12.8 10.2 16.8" />
      <path d="m4.2 20.6 1.6-1.6" />
    </>
  ),
  // Marker buoy: a place on the water
  buoy: (
    <>
      <path d="M12 3v3" />
      <path d="M9.2 6h5.6l1.7 9.2H7.5z" />
      <path d="M8.4 10.6h7.2" />
      <path d="M3 19c1.5 0 1.5-1.2 3-1.2S7.5 19 9 19s1.5-1.2 3-1.2 1.5 1.2 3 1.2 1.5-1.2 3-1.2 1.5 1.2 3 1.2" />
    </>
  ),
  // Folded chart with a rhumb line
  chart: (
    <>
      <path d="M3.5 6.2 9 4l6 2.2L20.5 4v13.8L15 20l-6-2.2L3.5 20z" />
      <path d="M9 4v13.8M15 6.2V20" />
      <path d="m5.6 15.4 2.6-2.4 2.8 1.2 3.2-3.6 2.6.8 1.8-2" strokeDasharray="0.1 2.2" />
    </>
  ),
  // Hull with a dotted route: a trip
  voyage: (
    <>
      <path d="M3 15.5h18l-2.2 3.4c-.2.4-.6.6-1 .6H6.2c-.4 0-.8-.2-1-.6z" />
      <path d="M12 15.5V5l5.5 7.6H12" />
      <path d="M4 11.5c1-2.6 2.6-4.6 5-5.8" strokeDasharray="0.1 2.2" />
    </>
  ),
  // Triangular signal pennant: official warning
  pennant: (
    <>
      <path d="M5 21V3" />
      <path d="M5 4.2 19 9 5 13.8" />
    </>
  ),
  // Argo float: cylinder, antenna, drift line
  float: (
    <>
      <path d="M12 2.8v3" />
      <rect x="9.2" y="5.8" width="5.6" height="11" rx="2.8" />
      <path d="M9.2 10.2h5.6" />
      <path d="M12 16.8v2.4" />
      <path d="M8.5 21.2h7" />
    </>
  ),
  // Concentric ripple: regional event
  ripple: (
    <>
      <circle cx="12" cy="12" r="1.6" />
      <path d="M7.6 9.6a5 5 0 0 1 8.8 0M16.4 14.4a5 5 0 0 1-8.8 0" />
      <path d="M4.4 8a8.6 8.6 0 0 1 15.2 0M19.6 16a8.6 8.6 0 0 1-15.2 0" />
    </>
  ),
  // Two swell lines
  waves: (
    <>
      <path d="M2.5 10c1.6 0 2.4-2.4 4.75-2.4S10.4 10 12 10s2.4-2.4 4.75-2.4S20 10 21.5 10" />
      <path d="M2.5 16c1.6 0 2.4-2.4 4.75-2.4S10.4 16 12 16s2.4-2.4 4.75-2.4S20 16 21.5 16" />
    </>
  ),
  // Windsock on a pole
  windsock: (
    <>
      <path d="M4 21V3.5" />
      <path d="M4 5h3l13 2.2v4.6L7 14H4" />
      <path d="M10 5.5v8M15 6.4v6.2" />
    </>
  ),
  // Flowing lines with a heading arrow: current
  current: (
    <>
      <path d="M3 8.5c3-2 6 2 9 0s4.6-1.6 6-.6" />
      <path d="M3 15.5c3-2 6 2 9 0s4.6-1.6 6-.6" />
      <path d="m16.4 4.8 3.4 2.9-3.6 2.4M16.4 11.8l3.4 2.9-3.6 2.4" />
    </>
  ),
  // Thermometer standing in water
  thermo: (
    <>
      <path d="M10 13.6V4.8a2 2 0 1 1 4 0v8.8a3.6 3.6 0 1 1-4 0Z" />
      <path d="M12 9v6.6" />
      <path d="M3 20.6c1.4 0 1.4-1 2.8-1M18.2 19.6c1.4 0 1.4 1 2.8 1" />
    </>
  ),
  // Sounding lead line with depth marks: behind the data
  sounding: (
    <>
      <path d="M12 2.5v12" />
      <path d="M10.2 6h3.6M10.8 9.5h2.4M10.2 13h3.6" />
      <path d="M9.6 15h4.8l-.8 5.2a1.6 1.6 0 0 1-1.6 1.3 1.6 1.6 0 0 1-1.6-1.3z" />
    </>
  ),
  // Ship's logbook with a ribbon: your workspace
  logbook: (
    <>
      <path d="M5.5 4.6c0-.9.7-1.6 1.6-1.6h11.4v15.6H7.1c-.9 0-1.6.7-1.6 1.6V4.6Z" />
      <path d="M5.5 20.2c0 .9.7 1.6 1.6 1.6h11.4v-3.2" />
      <path d="M14 3v6.4l1.6-1.2 1.6 1.2V3" />
    </>
  ),
  arrow: <path d="M4 12h15.5M13.5 6l6 6-6 6" />,
  back: <path d="M20 12H4.5M10.5 6l-6 6 6 6" />,
  down: <path d="m6 9.5 6 6 6-6" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  layers: (
    <>
      <path d="m12 4 8.5 4.4L12 12.8 3.5 8.4z" />
      <path d="m3.5 12.4 8.5 4.4 8.5-4.4M3.5 16.2l8.5 4.4 8.5-4.4" />
    </>
  ),
  locate: (
    <>
      <circle cx="12" cy="12" r="6.5" />
      <circle cx="12" cy="12" r="1.8" />
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3" />
    </>
  ),
  outbound: <path d="M8 5h11v11M18.5 5.5 5 19" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="8.6" />
      <path d="M12 7v5.2l3.4 2" />
    </>
  ),
  check: <path d="m4.5 12.5 4.6 4.6 10.4-10.4" />,
  info: (
    <>
      <circle cx="12" cy="12" r="8.6" />
      <path d="M12 11v5.6M12 7.6v.2" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h10" />,
  // Pin as a signal ball on a staff
  pin: (
    <>
      <circle cx="12" cy="8" r="4.6" />
      <path d="M12 12.6V21" />
    </>
  ),
  // Compass rose, four points
  compass: (
    <>
      <path d="m12 2.6 2.2 7.2L21.4 12l-7.2 2.2L12 21.4l-2.2-7.2L2.6 12l7.2-2.2z" />
      <circle cx="12" cy="12" r="1.2" />
    </>
  ),
  // Ship's bell: alerts
  bell: (
    <>
      <path d="M12 3v1.6" />
      <path d="M7.2 16.6c0-5 .4-10.4 4.8-10.4s4.8 5.4 4.8 10.4" />
      <path d="M5.4 16.6h13.2" />
      <path d="M12 16.6v2.4" />
      <circle cx="12" cy="20.4" r="1.2" />
    </>
  ),
  // Mooring line: saved place
  anchorline: (
    <>
      <path d="M7 4h10v3.4H7z" />
      <path d="M9 7.4v2.2M15 7.4v2.2" />
      <path d="M12 9.6c0 4 -5 4 -5 8M12 9.6c0 4 5 4 5 8" />
      <path d="M4 20.4h16" />
    </>
  ),
  export: (
    <>
      <path d="M12 3.5v11M7.6 8 12 3.5 16.4 8" />
      <path d="M4.5 14.5v4.2c0 .9.7 1.6 1.6 1.6h11.8c.9 0 1.6-.7 1.6-1.6v-4.2" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10.5" width="14" height="10" rx="1.6" />
      <path d="M8.2 10.5V7.8a3.8 3.8 0 0 1 7.6 0v2.7" />
    </>
  ),
  play: <path d="M8 5.5v13l10.5-6.5z" />,
  pause: <path d="M8.5 5.5v13M15.5 5.5v13" />,
};

export default function Icon({
  name,
  size = 22,
  title,
  ...rest
}: { name: IconName; size?: number; title?: string } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
      className="icon"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {paths[name]}
    </svg>
  );
}

/** Nautiq mark: the November code flag (a blue-and-white chequer) flown on a short hoist. */
export function NautiqMark({ size = 28 }: { size?: number }) {
  const cells = [];
  for (let r = 0; r < 4; r++)
    for (let c = 0; c < 4; c++)
      if ((r + c) % 2 === 0)
        cells.push(<rect key={`${r}${c}`} x={6 + c * 4.5} y={4 + r * 4.5} width="4.5" height="4.5" />);
  return (
    <svg viewBox="0 0 26 26" width={size} height={size} aria-hidden="true" className="mark">
      <rect x="6" y="4" width="18" height="18" fill="var(--mark-light, #fff)" />
      <g fill="var(--mark-dark, #123f6b)">{cells}</g>
      <rect x="6" y="4" width="18" height="18" fill="none" stroke="var(--mark-dark, #123f6b)" strokeWidth="1" />
      <path d="M3 2v22" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  );
}
