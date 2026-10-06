import Link from "next/link";
import type { Answer, Fact } from "../../lib/ask-types";
import { toReading, type Reading, type Measure } from "../../lib/humanize";
import Icon from "./ui/Icon";
import { Signal } from "./ui/Signal";

export { measureIcon } from "./readingIcons";
import { measureIcon } from "./readingIcons";
const order: Measure[] = ["waves", "wind", "current", "sst"];

function ReadingCell({ r }: { r: Reading }) {
  const [num, ...rest] = r.value.split(" ");
  return (
    <article className="reading" data-status={r.status} aria-label={r.title}>
      <div className="reading-top">
        <span className="reading-title">
          <Icon name={measureIcon[r.measure]} size={20} />
          {r.title}
        </span>
        {r.status === "stale" || r.status === "unknown" ? <Signal status={r.status} size={14} /> : null}
      </div>
      {r.value ? (
        <p className="reading-value">
          {num}
          <small>{rest.join(" ")}</small>
        </p>
      ) : (
        <p className="reading-none">
          <span className="ring" aria-hidden="true" />
          <span>Not available</span>
        </p>
      )}
      {r.descriptor ? <p className="reading-descriptor" style={{ margin: 0 }}>{r.descriptor}</p> : null}
      <div className="reading-meta">
        {r.value ? (
          <>
            {r.time ? (
              <span>
                <Icon name="clock" size={16} /> {r.time}
              </span>
            ) : null}
            {r.outlook ? <span>{r.outlook}</span> : null}
          </>
        ) : (
          <span className="reading-note">{r.note || "No reading for this place and time."}</span>
        )}
      </div>
    </article>
  );
}

/** Four sea-state readings for a place, in the order people check them. */
export function ReadingsBoard({ facts }: { facts: Fact[] }) {
  const readings = facts.map((f) => toReading(f));
  const board = order.map((m) => readings.find((r) => r.measure === m)).filter(Boolean) as Reading[];
  if (!board.length) return null;
  return (
    <section className="readings" aria-label="Sea-state readings">
      {board.map((r) => (
        <ReadingCell key={r.measure} r={r} />
      ))}
    </section>
  );
}

/** Supporting facts (nearest float, comparison with normal), kept quiet. */
export function QuietFacts({ facts }: { facts: Fact[] }) {
  const rest = facts.map((f) => toReading(f)).filter((r) => r.measure === "float" || r.measure === "normal" || r.measure === "other");
  if (!rest.length) return null;
  return (
    <section className="facts-quiet" aria-label="More context">
      {rest.map((r) => (
        <div className="fact-quiet" key={r.raw.label}>
          <Icon name={measureIcon[r.measure]} size={22} />
          <b>{r.title}</b>
          <p style={{ gridColumn: 2 }}>
            {r.descriptor || r.value}
            {r.note ? ` ${r.note}` : ""}
          </p>
          {r.href ? (
            <Link href={r.href} style={{ gridColumn: 2 }}>
              Learn more
            </Link>
          ) : null}
        </div>
      ))}
    </section>
  );
}

export function Limits({ answer, title = "What this can’t tell you" }: { answer: Answer; title?: string }) {
  if (!answer.cannot_tell_you.length) return null;
  return (
    <aside className="limits">
      <h3>{title}</h3>
      <ul>
        {answer.cannot_tell_you.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </aside>
  );
}
