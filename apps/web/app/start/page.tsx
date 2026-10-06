import Link from "next/link";
import { topicOptions } from "../../lib/ask.mjs";
import { PageHead } from "../components/ui/Bits";
import Icon, { type IconName } from "../components/ui/Icon";
import { Signal } from "../components/ui/Signal";
export const metadata = {
  title: "Two-minute guide · Nautiq",
  description: "How to read Nautiq: what the signals mean and what it will never tell you.",
};
const steps: { title: string; body: string; href: string; link: string; icon: IconName }[] = [
  { title: "Ask, or pick a place", body: "Type a question in your own words, or choose a place. Nautiq shows how it understood you (place, time, kind of question) and lets you change any of it.", href: "/ask", link: "Try asking", icon: "hailer" },
  { title: "Read the signal before the number", body: "Every value carries a shape and a word. Out-of-date values are history, not now. Unknown never means clear.", href: "/", link: "See the signals", icon: "pennant" },
  { title: "See where a number came from", body: "Open “Technical detail” on any page to see the source, the time it was measured or forecast, and how it was worked out. Float readings stay at the float’s own position and depth.", href: "/research", link: "Browse float readings", icon: "sounding" },
  { title: "Plan a trip properly", body: "Add your stops out and back with times. Nautiq checks the forecast against your limits along the whole route, and lists what it couldn’t check. It never says a trip is safe, and it doesn’t read official warnings.", href: "/trips", link: "Plan a trip", icon: "voyage" },
  { title: "Keep your routes and places", body: "A free private workspace saves your routes, places and trip receipts so you can check them again.", href: "/app", link: "Open your workspace", icon: "logbook" },
];
const glossary = [
  ["Historical normal", "What the sea usually reads at a place, depth and time of year, from a fixed 2005–2016 float record. It is not a forecast."],
  ["Expected range", "Where an ordinary reading would fall around the normal. It describes natural variation, not measurement error."],
  ["Unusual float", "A float reading that ranks high against history. It is a rank, not a probability, and not an event."],
  ["Regional event", "A lasting patch of unusual water, such as a warm spell, found by a fixed method. One unusual float is never an event."],
  ["Too rough", "Somewhere on your route the forecast reaches a trip limit. The defaults suit small open boats; you can set stricter ones."],
  ["Not enough data", "At least one thing needed couldn’t be checked. It is never a mild form of “fine”."],
];
export default function Page() {
  return (
    <main>
      <PageHead icon="compass" title="The two-minute guide" lede="Nautiq is built to be honest about what it knows. Five steps and a short glossary cover everything." />
      <ol className="steps">
        {steps.map((s) => (
          <li key={s.title}>
            <span className="step-mark" aria-hidden="true">
              <Icon name={s.icon} size={24} />
            </span>
            <div>
              <h2>{s.title}</h2>
              <p>{s.body}</p>
              <Link className="text-link" href={s.href}>
                {s.link} <Icon name="arrow" size={16} />
              </Link>
            </div>
          </li>
        ))}
      </ol>
      <section className="section">
        <div className="section-head">
          <h2>The five signals</h2>
        </div>
        <ul className="signal-key">
          <li><Signal status="available" /><p>Current, checked and within its allowed age.</p></li>
          <li><Signal status="stale" /><p>Older than it should be. Shown as history.</p></li>
          <li><Signal status="unknown" /><p>Couldn’t be confirmed. Never an all-clear.</p></li>
          <li><Signal status="unavailable" /><p>No data here. Nothing is filled in.</p></li>
          <li><Signal status="warning" /><p>A trip reaches your limits somewhere on the route.</p></li>
        </ul>
      </section>
      <section className="section">
        <div className="section-head">
          <h2>Words you’ll meet</h2>
        </div>
        <dl className="glossary">
          {glossary.map(([term, text]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="section">
        <div className="section-head">
          <h2>Ask Nautiq to explain itself</h2>
        </div>
        <ul className="suggestions">
          {topicOptions.slice(0, 6).map(([topic, text]: string[]) => (
            <li key={topic}>
              <Link className="suggestion" href={`/ask?q=${encodeURIComponent(text.replace("Why a trip shows caution or insufficient data", "Why is Nautiq showing caution?"))}`}>
                {text}
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <div className="section">
        <p className="notice">Nautiq is still awaiting scientific and public release approval. Never use it as your only source for decisions at sea.</p>
      </div>
    </main>
  );
}
