import Link from "next/link";
import { statusLabels, topicOptions } from "../../lib/ask.mjs";
export const metadata = {
  title: "Start here · Nautiq",
  description: "A two-minute guide to reading Nautiq: what the labels mean and what it cannot tell you.",
};
const steps = [
  {
    title: "Ask, or pick a place",
    body: "Type a question on the Ask page, or choose a named place under Conditions. Nautiq shows how it understood you (place, time, kind of question) and lets you change any of it before you rely on the answer.",
    href: "/ask",
    link: "Try the Ask page",
  },
  {
    title: "Read the labels before the numbers",
    body: "Each value is Available, Stale, Unknown, Unavailable, or an Official warning. Stale values are history, not now. Unknown never means clear.",
    href: "/",
    link: "See the label guide on the home page",
  },
  {
    title: "Check where a number came from",
    body: "Every result has evidence: the source, the observation or forecast time, the method version and a calculation identifier. Observations are shown at the instrument’s own position and depth, never moved to your location.",
    href: "/research",
    link: "Browse real observations",
  },
  {
    title: "Plan a trip properly",
    body: "A trip needs timed waypoints out and back. Nautiq checks forecasts and official warnings along the whole route. It reports what it could not check and does not say a trip is safe.",
    href: "/trips",
    link: "Open the trip form",
  },
  {
    title: "Keep your places and alerts",
    body: "Create a free private account to save routes, watchlists and personal alert limits. Personal limits are your preferences, not safety thresholds, and never override an official warning.",
    href: "/app",
    link: "Open your workspace",
  },
];
const glossary = [
  ["Expected normal", "What an Argo profile would typically read at that place, depth and time of year, from a fixed 2005–2016 historical baseline. It is not a forecast."],
  ["Expected interval", "The range where an ordinary profile would fall around the expected normal. It describes natural variability, not measurement error."],
  ["Unusual profile", "A profile whose differences from normal rank high against retained history. A descriptive rank, not a probability and not an event."],
  ["Regional event", "A persistent, spatially coherent departure (for example a sea-surface warm spell) found by a fixed detector. One unusual profile is never an event."],
  ["Official warning", "A bulletin from an agency such as NDMA. Nautiq shows it as issued, with its validity and revisions, and always gives it priority."],
  ["Insufficient data", "At least one needed input could not be checked. It is not a mild form of “fine”."],
];
export default function Page() {
  return (
    <main className="explorer start-page">
      <p className="eyebrow">START HERE</p>
      <h1>Two minutes to read Nautiq well.</h1>
      <p className="intro">
        Nautiq is built to be honest about what it knows. These five steps and a short glossary cover everything you need.
      </p>
      <ol className="steps">
        {steps.map((s, i) => (
          <li key={s.title}>
            <span className="step-number" aria-hidden="true">{i + 1}</span>
            <div>
              <h2>{s.title}</h2>
              <p>{s.body}</p>
              <Link href={s.href}>{s.link} →</Link>
            </div>
          </li>
        ))}
      </ol>
      <section>
        <h2>The five labels</h2>
        <ul className="legend">
          {Object.entries(statusLabels).map(([key, [icon, word]]) => (
            <li key={key}>
              <span className="status-chip" data-status={key}>
                <span aria-hidden="true">{icon}</span> {word}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2>Words you will meet</h2>
        <dl className="glossary">
          {glossary.map(([term, text]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section>
        <h2>You can ask Nautiq to explain itself</h2>
        <ul>
          {topicOptions.slice(0, 6).map(([topic, label]: string[]) => (
            <li key={topic}>
              <Link href={`/ask?q=${encodeURIComponent(label.replace("Why a trip shows caution or insufficient data", "Why is Nautiq showing caution?"))}`}>
                {label}
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <p className="notice">
        Nautiq is a private diagnostic product. Scientific and public release approvals are still pending, and it must not be used as your only source for decisions at sea.
      </p>
    </main>
  );
}
