import Link from "next/link";
import { evidence } from "../lib/science";
import { exampleQuestions } from "../lib/ask.mjs";
import Welcome from "./components/Welcome";
export const dynamic = "force-dynamic";
type Operations = {
  sources: {
    fields: { product_id: string; fresh: boolean; cycle: string | null; status: string }[];
    advisories: { source_id: string; transport: string; checked_at: string | null }[];
  };
  scientific_approved: boolean;
};
const productNames: Record<string, string> = {
  noaa_oisst: "Sea surface temperature (NOAA OISST)",
  noaa_gfs_wave: "Wave forecast (NOAA GFS-Wave)",
  noaa_gfs_weather: "Wind and weather (NOAA GFS)",
  hycom_espc: "Surface currents (HYCOM)",
};
const paths = [
  {
    href: "/locations",
    title: "Check the sea near a place",
    text: "Waves, wind, currents and surface temperature at a named place, with official-warning state and the nearest real observation.",
  },
  {
    href: "/trips",
    title: "Plan a trip",
    text: "Enter a timed route out and back. Nautiq checks every leg against forecasts and official warnings and shows what it could not check.",
  },
  {
    href: "/advisories",
    title: "See official warnings",
    text: "Original agency bulletins with validity and feed health. An unknown state is shown as unknown, never as clear.",
  },
  {
    href: "/research",
    title: "Explore observations",
    text: "Real Argo float profiles of temperature and salinity at their true positions and depths, with quality flags and the source file.",
  },
];
const states = [
  ["✓", "Available", "Current, checked, and within its allowed age."],
  ["⏱", "Stale", "Older than its allowed age. Shown as history, never as now."],
  ["?", "Unknown", "Could not be confirmed. This is never an all-clear."],
  ["–", "Unavailable", "No data for this place or time. Nothing is filled in."],
  ["⚠", "Official warning", "An agency bulletin applies. It always takes priority."],
];
export default async function Home() {
  const ops = await evidence<Operations>("/operations/status");
  return (
    <main className="home">
      <Welcome />
      <section className="hero">
        <p className="eyebrow">NAUTIQ / OCEAN EVIDENCE FOR INDIA’S COASTAL WATERS</p>
        <h1>
          What is the sea doing,
          <br />
          and how sure are we?
        </h1>
        <p className="intro">
          Nautiq brings together real ocean observations, forecasts and
          official warnings, shows how unusual conditions are against a fixed
          historical normal, and tells you plainly what it does not know.
        </p>
        <form className="hero-ask" action="/ask" method="get">
          <label htmlFor="home-q">Ask in your own words</label>
          <div className="ask-row">
            <input
              id="home-q"
              name="q"
              required
              maxLength={512}
              placeholder="How are the waves near Goa tomorrow morning?"
              autoComplete="off"
            />
            <button className="ask-submit">Ask</button>
          </div>
        </form>
        <div className="chips" role="group" aria-label="Example questions">
          {exampleQuestions.slice(0, 4).map((q: string) => (
            <Link key={q} className="chip" href={`/ask?q=${encodeURIComponent(q)}`}>
              {q}
            </Link>
          ))}
        </div>
      </section>

      <section aria-labelledby="start-heading" className="section">
        <h2 id="start-heading">Or start with what you need</h2>
        <div className="path-grid">
          {paths.map((p) => (
            <Link key={p.href} href={p.href} className="path-card">
              <h3>{p.title}</h3>
              <p>{p.text}</p>
              <span aria-hidden="true">Open →</span>
            </Link>
          ))}
        </div>
        <p>
          <Link href="/map">Open the ocean map</Link> ·{" "}
          <Link href="/start">First time? Read the two-minute guide</Link>
        </p>
      </section>

      <section aria-labelledby="read-heading" className="section">
        <h2 id="read-heading">How to read what you see</h2>
        <p className="lead">
          Every value in Nautiq carries one of these labels. They use words and
          symbols, not just colour.
        </p>
        <ul className="legend">
          {states.map(([icon, word, text]) => (
            <li key={word}>
              <span className="status-chip" data-status={word.toLowerCase().split(" ")[0]}>
                <span aria-hidden="true">{icon}</span> {word}
              </span>
              <span>{text}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="live-heading" className="section">
        <h2 id="live-heading">The data right now</h2>
        {ops ? (
          <ul className="legend">
            {ops.sources.fields.map((f) => (
              <li key={f.product_id}>
                <span className="status-chip" data-status={f.fresh ? "available" : "stale"}>
                  <span aria-hidden="true">{f.fresh ? "✓" : "⏱"}</span> {f.fresh ? "Fresh" : "Stale"}
                </span>
                <span>
                  {productNames[f.product_id] ?? f.product_id}
                  {f.cycle ? `, cycle ${f.cycle.slice(0, 16).replace("T", " ")} UTC` : ""}
                </span>
              </li>
            ))}
            {ops.sources.advisories.map((a) => (
              <li key={a.source_id}>
                <span className="status-chip" data-status={a.transport === "healthy" ? "available" : "unknown"}>
                  <span aria-hidden="true">{a.transport === "healthy" ? "✓" : "?"}</span>{" "}
                  {a.transport === "healthy" ? "Reachable" : a.transport === "unconfigured" ? "Not connected" : "Not recent"}
                </span>
                <span>
                  Official bulletins: {a.source_id === "ndma_cap_rss" ? "NDMA CAP feed" : "INCOIS advisories"}
                  {a.checked_at ? `, last checked ${a.checked_at.slice(0, 16).replace("T", " ")} UTC` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="notice">
            Live source status is unavailable right now. Nothing below should be treated as current until it returns.
          </p>
        )}
        <p>
          <Link href="/status">Full system status</Link>
        </p>
      </section>

      <section aria-labelledby="not-heading" className="section honest">
        <h2 id="not-heading">What Nautiq will not do</h2>
        <ul>
          <li>It will not tell you a trip is safe. Numeric trip limits are not yet approved by marine and legal reviewers, so real trips return “insufficient data” unless an official warning applies.</li>
          <li>It will not treat a missing warning as no warning. Official coverage of marine areas is not yet verified.</li>
          <li>It will not invent a number. Where evidence is missing, you see “unavailable”, not a guess.</li>
          <li>
            Its machine-learning models are tested, not trusted: today a
            historical seasonal normal is used because neither learned model
            beat it convincingly. <Link href="/models">See the evidence</Link>.
          </li>
        </ul>
      </section>
    </main>
  );
}
