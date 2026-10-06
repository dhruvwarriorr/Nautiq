// Day-signal status vocabulary. Every state is a distinct shape AND a word, never colour alone.
//   available   → ball
//   stale       → ball at half-hoist (lower half filled)
//   unknown     → diamond with a centre point
//   unavailable → empty dashed ring (absence drawn, not hidden)
//   warning     → red cone, point down (too rough for your limits)
import { statusWord, type Status } from "../../../lib/humanize";

export function SignalShape({ status, size = 18 }: { status: Status; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 20 20", "aria-hidden": true as const, className: `signal-shape s-${status}` };
  switch (status) {
    case "available":
      return (
        <svg {...common}>
          <circle cx="10" cy="10" r="7.5" fill="currentColor" />
        </svg>
      );
    case "stale":
      return (
        <svg {...common}>
          <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="1.75" />
          <path d="M3 10a7 7 0 0 0 14 0z" fill="var(--caution)" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" />
        </svg>
      );
    case "unknown":
      return (
        <svg {...common}>
          <path d="M10 2.2 17.8 10 10 17.8 2.2 10z" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" />
          <circle cx="10" cy="10" r="1.9" fill="currentColor" />
        </svg>
      );
    case "unavailable":
      return (
        <svg {...common}>
          <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeDasharray="2.4 2.6" />
        </svg>
      );
    case "warning":
      return (
        <svg {...common}>
          <path d="M2.4 3.4h15.2L10 17.4z" fill="var(--signal)" stroke="var(--signal)" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      );
  }
}

/** Shape + word, the atomic status label used everywhere. */
export function Signal({
  status,
  children,
  size,
}: {
  status: Status;
  children?: React.ReactNode;
  size?: number;
}) {
  return (
    <span className="signal" data-status={status}>
      <SignalShape status={status} size={size} />
      <span>{children ?? statusWord[status]}</span>
    </span>
  );
}

export type HoistMark = { key: string; label: string; status: Status; word: string; note?: string; href?: string };

/** The mast: a vertical halyard carrying a stack of marks. Stale marks rest at half-mast. */
export function Hoist({ marks, caption, onSea = true, row = false }: { marks: HoistMark[]; caption?: React.ReactNode; onSea?: boolean; row?: boolean }) {
  return (
    <figure className="hoist" data-on-sea={onSea} data-row={row || undefined}>
      <div className="hoist-mast" aria-hidden="true">
        <span className="hoist-truck" />
      </div>
      <ul className="hoist-marks">
        {marks.map((m, i) => {
          const body = (
            <>
              <span className="hoist-shape">
                <SignalShape status={m.status} size={30} />
              </span>
              <span className="hoist-text">
                <span className="hoist-label">{m.label}</span>
                <span className="hoist-word">{m.word}</span>
                {m.note ? <span className="hoist-note">{m.note}</span> : null}
              </span>
            </>
          );
          return (
            <li key={m.key} data-status={m.status} style={{ "--i": i } as React.CSSProperties}>
              {m.href ? <a href={m.href}>{body}</a> : <div>{body}</div>}
            </li>
          );
        })}
      </ul>
      {caption ? <figcaption>{caption}</figcaption> : null}
    </figure>
  );
}
