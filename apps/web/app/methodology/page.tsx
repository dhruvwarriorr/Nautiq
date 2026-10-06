import { PageHead, DoorLink } from "../components/ui/Bits";
export const metadata = { title: "How it works · Nautiq" };
const parts = [
  {
    title: "Float readings stay where they were taken",
    text: "Argo floats measure temperature and salinity down to 2,000 m. Each reading keeps its own position, time, depth and quality check. A nearby float never stands in for a measurement at your spot.",
    href: "/research", link: "Float observations", icon: "float" as const,
  },
  {
    title: "Forecasts are read straight from the source grid",
    text: "Each wave, wind, current and sea-temperature value names the exact forecast it came from and when that forecast was issued. Gaps, old forecasts and times past the forecast’s reach are shown as gaps.",
    href: "/fields", link: "Forecast layers", icon: "layers" as const,
  },
  {
    title: "Models are tested, not trusted",
    text: "The historical normal, expected ranges and unusual-float ranks are diagnostics you can inspect. A rank is not a probability. Scientific approval and confidence levels are still pending.",
    href: "/models", link: "Models", icon: "logbook" as const,
  },
  {
    title: "Trips are checked against limits you can see",
    text: "Every leg, out and back, is sampled against wave, wind and current limits. The defaults suit small open boats and you can tighten them. Nautiq does not read official warnings, so check INCOIS and IMD before you go. Replaying a saved trip never refreshes its data.",
    href: "/trips", link: "Plan a trip", icon: "voyage" as const,
  },
  {
    title: "Your saved things are private",
    text: "Saved routes, places, reports and downloads belong to your account only. Float exports include credit to the Argo programme. Downloads expire after 72 hours.",
    href: "/data-sources", link: "Data sources and terms", icon: "lock" as const,
  },
];
export default function Page() {
  return (
    <main>
      <PageHead icon="sounding" title="How it works" lede="From raw readings to a plain answer, with the evidence kept at every step." />
      <div className="door-list">
        {parts.map((p) => (
          <div key={p.title} className="method">
            <h2>{p.title}</h2>
            <p>{p.text}</p>
            <DoorLink href={p.href} icon={p.icon} title={p.link} text="Open" />
          </div>
        ))}
      </div>
    </main>
  );
}
