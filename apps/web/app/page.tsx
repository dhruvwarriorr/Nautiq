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
  "What is the wind near Kerala tonight?",
  "Is it a good time to go fishing near Mumbai tomorrow?",
];

function marks(ops: Operations | null, floats: MapOverview | null): HoistMark[] {
  const now = new Date();
  let forecasts: HoistMark = {
    key: "forecasts", label: "Forecasts", status: "unknown", word: "Unknown", note: "Forecast status unavailable.", href: "/map",
  };
  let sst: HoistMark = {
    key: "sst", label: "Sea temperature", status: "unknown", word: "Unknown", note: "Sea temperature status unavailable.", href: "/map",
  };
  if (ops) {
    const layers = ops.sources.fields.filter((f) => f.product_id !== "cmems_sst");
    const fresh = layers.filter((f) => f.fresh).length;
    const latest = layers.map((f) => f.cycle).filter(Boolean).sort().at(-1);
    const status: Status = fresh === layers.length && layers.length ? "available" : fresh ? "stale" : "unavailable";
    forecasts = {
      ...forecasts,
      status,
      word: status === "available" ? "Up to date" : status === "stale" ? "Partly out of date" : "Not available",
      note: `${fresh} of ${layers.length} layers fresh${latest ? ` · issued ${when(latest, now)}` : ""}`,
    };
    const temp = ops.sources.fields.find((f) => f.product_id === "cmems_sst");
    if (temp) {
      const ok = temp.status === "ready" && temp.fresh;
      sst = {
        ...sst,
        status: ok ? "available" : "stale",
        word: ok ? "Up to date" : "Out of date",
        note: `Copernicus forecast${temp.cycle ? ` · updated ${when(temp.cycle, now)}` : ""}`,
      };
    }
  }
  const newest = floats?.profiles.map((p) => p.observed_at).sort().at(-1);
  const obs: HoistMark = newest
    ? { key: "floats", label: "Float readings", status: "available", word: "Reporting", note: `Newest reading ${ago(newest, now)}`, href: "/research" }
    : { key: "floats", label: "Float readings", status: "unavailable", word: "None recent", note: "No float readings in the last 30 days.", href: "/research" };
  return [forecasts, sst, obs];
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
              Plain answers for India&apos;s coast: waves, wind, currents and sea temperature, with the gaps shown
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
                <input id="home-q" name="q" required maxLength={512} autoComplete="off" placeholder="Ask about waves, wind or a trip" />
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
          <DoorLink href="/map" icon="chart" title="Ocean map" text="See waves, wind and currents across the whole coast, with float readings." />
          <DoorLink href="/trips" icon="voyage" title="Plan a trip" text="Enter your route out and back. Nautiq checks every leg and lists what it couldn’t check." />
          <DoorLink href="/compare" icon="buoy" title="Compare places" text="Put two places side by side before you choose where to go." />
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
            <Signal status="warning">Too rough</Signal>
            <p>A trip goes past your limits somewhere on the route.</p>
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
              <span>It won&apos;t call a trip safe. It checks the forecast against your limits; you still decide.</span>
            </li>
            <li>
              <SignalShape status="unknown" size={20} />
              <span>It doesn&apos;t track official warnings. Check INCOIS and IMD before you go.</span>
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
