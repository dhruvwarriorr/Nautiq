import { PageHead, DoorLink } from "../components/ui/Bits";
import type { IconName } from "../components/ui/Icon";
export const metadata = { title: "Behind the data · Nautiq", description: "The sources, models and raw evidence behind every Nautiq answer." };
const groups: { title: string; text: string; links: [string, IconName, string, string][] }[] = [
  {
    title: "Understand Nautiq",
    text: "Start here if you want to know how an answer is made.",
    links: [
      ["/start", "compass", "Two-minute guide", "The signals and the words you’ll meet."],
      ["/methodology", "sounding", "How it works", "From raw readings to a plain answer."],
      ["/data-sources", "outbound", "Data sources", "Who provides what, and the terms."],
      ["/status", "clock", "System status", "Is every feed running right now?"],
    ],
  },
  {
    title: "Observations",
    text: "Real readings from floats in the water.",
    links: [
      ["/research", "float", "Float observations", "Temperature and salinity by depth."],
      ["/profiles", "pin", "Float readings list", "Every stored float reading."],
      ["/anomalies", "ripple", "Unusual floats", "Readings that stand out from normal."],
      ["/data", "layers", "Datasets and quality", "Freshness and quality checks."],
    ],
  },
  {
    title: "Forecasts and events",
    text: "The grids and detectors behind the map.",
    links: [
      ["/fields", "waves", "Forecast layers", "Raw forecast and analysis grids."],
      ["/events", "ripple", "Regional events", "Lasting unusual patches in past data."],
      ["/insights", "chart", "Insights", "Change over time, with its support."],
      ["/compare", "compass", "Compare places", "Two places, same time."],
    ],
  },
  {
    title: "Models",
    text: "What was tested, what is used, and how it’s watched.",
    links: [
      ["/models", "logbook", "Models", "Why the seasonal normal is used today."],
      ["/models/monitoring", "bell", "Model monitoring", "Ongoing checks on model behaviour."],
      ["/climatology", "waves", "Historical normal", "The seasonal baseline."],
      ["/uncertainty", "compass", "Expected ranges", "How much the sea normally varies."],
    ],
  },
];
export default function Page() {
  return (
    <main>
      <PageHead icon="sounding" title="Behind the data" lede="Every answer on Nautiq can be traced back to its source. These pages are for when you want to dig." />
      <div className="btd-grid">
        {groups.map((g) => (
          <section key={g.title} className="btd-group section" style={{ marginTop: 0, paddingTop: 8, paddingBottom: 40 }}>
            <h2>{g.title}</h2>
            <p>{g.text}</p>
            <div className="door-list">
              {g.links.map(([href, icon, title, text]) => (
                <DoorLink key={href} href={href} icon={icon} title={title} text={text} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </main>
  );
}
