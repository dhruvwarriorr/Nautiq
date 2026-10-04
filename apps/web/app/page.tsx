import Link from "next/link";
import { evidence } from "../lib/science";
import type { MapOverview, Place, ProductPolicy } from "../lib/product";
import { ago, when, type Status } from "../lib/humanize";
import Icon from "./components/ui/Icon";
import { Hoist, Signal, SignalShape, type HoistMark } from "./components/ui/Signal";
import { DoorLink } from "./components/ui/Bits";
import HeroChart from "./components/HeroChart";
export const dynamic = "force-dynamic";

type Operations = {
  as_of: string;
  sources: {
    fields: { product_id: string; fresh: boolean; cycle: string | null; valid_time_end: string | null; status: string }[];
    advisories: { source_id: string; transport: string; checked_at: string | null }[];
  };
};

const fallbackPlaces: Place[] = [
  { slug: "mumbai-offshore", name: "Mumbai Offshore", latitude: 19, longitude: 72.3, bbox: [] },
  { slug: "goa-offshore", name: "Goa Offshore", latitude: 15.4, longitude: 73.3, bbox: [] },
  { slug: "kerala-offshore", name: "Kerala Offshore", latitude: 10, longitude: 75.5, bbox: [] },
  { slug: "arabian-sea", name: "Arabian Sea", latitude: 15, longitude: 65, bbox: [] },
  { slug: "bay-of-bengal", name: "Bay of Bengal", latitude: 15, longitude: 87, bbox: [] },
];

const suggestions = [
  "How are the waves near Goa tomorrow morning?",
  "Is there an official warning near Kerala?",
  "Is it a good time to go fishing near Mumbai tomorrow?",
];

function marks(ops: Operations | null, floats: MapOverview | null): HoistMark[] {
  const now = new Date();
  let warnings: HoistMark = {
    key: "warnings", label: "Official warnings", status: "unknown", word: "Unknown",
    note: "Feed status unavailable. Never read this as an all-clear.", href: "/advisories",
  };
  let forecasts: HoistMark = {
    key: "forecasts", label: "Forecasts", status: "unknown", word: "Unknown", note: "Forecast status unavailable.", href: "/map",
  };
  if (ops) {
    const off = ops.sources.advisories.filter((a) => a.transport !== "healthy");
    warnings = {
      ...warnings,
      note: off.length
        ? `${off.length === ops.sources.advisories.length ? "No alert feed" : "One alert feed"} is fully connected. Check your place; this is not an all-clear.`
        : "Feeds are connected, but marine coverage isn’t verified. Check your place.",
    };
    const fresh = ops.sources.fields.filter((f) => f.fresh).length;
    const total = ops.sources.fields.length;
    const latest = ops.sources.fields.map((f) => f.cycle).filter(Boolean).sort().at(-1);
    const status: Status = fresh === total && total ? "available" : fresh ? "stale" : "unavailable";
    forecasts = {
      ...forecasts,
      status,
      word: status === "available" ? "Up to date" : status === "stale" ? "Partly out of date" : "Not available",
      note: `${fresh} of ${total} layers fresh${latest ? ` · issued ${when(latest, now)}` : ""}`,
    };
  }
  const newest = floats?.profiles.map((p) => p.observed_at).sort().at(-1);
  const obs: HoistMark = newest
    ? { key: "floats", label: "Float readings", status: "available", word: "Reporting", note: `Newest reading ${ago(newest, now)}`, href: "/research" }
    : { key: "floats", label: "Float readings", status: "unavailable", word: "None recent", note: "No float readings in the last 30 days.", href: "/research" };
  return [warnings, forecasts, obs];
}

export default async function Home() {
  const end = new Date();
  const start = new Date(end.getTime() - 30 * 86400000);
  const q = new URLSearchParams({ bbox: "45,0,100,30", start: start.toISOString().slice(0, 10) + "T00:00:00Z", end: new Date(end.getTime() + 86400000).toISOString().slice(0, 10) + "T00:00:00Z" });
  const [ops, policy, floats] = await Promise.all([
    evidence<Operations>("/operations/status"),
    evidence<ProductPolicy>("/product-policy"),
    evidence<MapOverview>(`/map/overview?${q}`),
  ]);
  const places = policy?.policy.locations.length ? policy.policy.locations : fallbackPlaces;
  return (
    <main className="home">
      <section className="hero" aria-labelledby="hero-title">
        <HeroChart places={places} />
        <div className="hero-inner">
          <Hoist
            marks={marks(ops, floats)}
            caption={ops ? <>Today on India&apos;s seas · checked {when(ops.as_of)}</> : "Live status unavailable right now"}
          />
          <div className="hero-main">
            <h1 id="hero-title">
              What is <span>the sea doing?</span>
            </h1>
            <p className="hero-sub">
              Plain answers for India&apos;s coast: waves, wind, currents and official warnings, with the gaps shown
              honestly.
            </p>
            <form action="/ask" method="get" role="search" aria-label="Ask Nautiq">
              <label htmlFor="home-q" className="visually-hidden">
                Ask in your own words
              </label>
              <div className="ask-field">
                <span className="ask-icon">
                  <Icon name="hailer" size={24} />
                </span>
                <input id="home-q" name="q" required maxLength={512} autoComplete="off" placeholder="Ask about waves, wind or warnings" />
                <button className="ask-go">
                  Ask <Icon name="arrow" size={18} />
                </button>
              </div>
            </form>
            <p className="hero-or">or pick a place</p>
            <ul className="place-board" aria-label="Places">
              {places.map((p) => (
                <li key={p.slug}>
                  <Link href={`/locations/${p.slug}`} data-place={p.slug}>
                    <Icon name="buoy" size={24} className="icon pb-icon" />
                    <span className="pb-name">{p.name.replace(/ Offshore$/, "")}</span>
                    <span className="pb-kind">{/Offshore$/.test(p.name) ? "Offshore" : "Open sea"}</span>
                  </Link>
                </li>
              ))}
            </ul>
            <p className="hero-try">
              Try asking:{" "}
              {suggestions.slice(0, 2).map((q, i) => (
                <span key={q}>
                  {i ? " · " : ""}
                  <Link href={`/ask?q=${encodeURIComponent(q)}`}>{q}</Link>
                </span>
              ))}
            </p>
          </div>
        </div>
      </section>

      <section className="section" aria-labelledby="ways">
        <div className="section-head">
          <h2 id="ways">Three more ways in</h2>
        </div>
        <div className="doors">
          <DoorLink href="/map" icon="chart" title="Ocean map" text="See waves, wind and currents across the whole coast, with floats and official areas." />
          <DoorLink href="/trips" icon="voyage" title="Plan a trip" text="Enter your route out and back. Nautiq checks every leg and lists what it couldn’t check." />
          <DoorLink href="/advisories" icon="pennant" title="Official warnings" text="Bulletins from Indian agencies, in their own words, with when they start and end." />
        </div>
      </section>

      <section className="section" aria-labelledby="signals">
        <div className="section-head">
          <h2 id="signals">Read the signals</h2>
          <p>Every answer carries one of these marks: a shape and a word, never colour alone.</p>
        </div>
        <ul className="signal-key">
          <li>
            <Signal status="available">Available</Signal>
            <p>Current, checked and within its allowed age.</p>
          </li>
          <li>
            <Signal status="stale">Out of date</Signal>
            <p>Older than it should be. Shown as history, never as now.</p>
          </li>
          <li>
            <Signal status="unknown">Unknown</Signal>
            <p>Couldn’t be confirmed. Never an all-clear.</p>
          </li>
          <li>
            <Signal status="unavailable">Not available</Signal>
            <p>No data for this place or time. Nothing is filled in.</p>
          </li>
          <li>
            <Signal status="warning">Official warning</Signal>
            <p>An agency bulletin applies. It always comes first.</p>
          </li>
        </ul>
      </section>

      <section className="promise" aria-labelledby="promise">
        <div className="promise-inner">
          <div>
            <h2 id="promise">What Nautiq won&apos;t do</h2>
            <p className="lead">Honesty is the feature. These limits are on purpose.</p>
            <Link className="text-link" href="/start">
              Read the two-minute guide <Icon name="arrow" size={18} />
            </Link>
          </div>
          <ol>
            <li>
              <SignalShape status="warning" size={20} />
              <span>It won&apos;t call a trip safe. Trip limits are still being reviewed by marine and legal experts.</span>
            </li>
            <li>
              <SignalShape status="unknown" size={20} />
              <span>It won&apos;t treat a missing warning as no warning. Official marine coverage isn&apos;t verified yet.</span>
            </li>
            <li>
              <SignalShape status="unavailable" size={20} />
              <span>It won&apos;t invent a number. Where data is missing, you see that it&apos;s missing.</span>
            </li>
            <li>
              <SignalShape status="available" size={20} />
              <span>
                It won&apos;t oversell its models. A simple seasonal normal is used because the learned models didn&apos;t
                beat it. <Link href="/models">See why</Link>.
              </span>
            </li>
          </ol>
        </div>
      </section>
    </main>
  );
}
