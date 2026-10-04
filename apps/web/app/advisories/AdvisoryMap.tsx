import type { Bulletin } from "../../lib/advisories";
import { chartBounds, landPath } from "../../lib/chart-land";
import { project } from "../components/HeroChart";
import { sender, label } from "../../lib/humanize";

/** Mapped bulletin areas drawn on Nautiq's chart of India's seas. Place-name-only areas are never guessed onto it. */
export function AdvisoryMap({ items }: { items: Bulletin[] }) {
  const shapes = items.flatMap((b) => b.message.infos.flatMap((i) => i.areas.flatMap((a) => a.polygons.map((p) => ({ b, p })))));
  const d = (rings: number[][][]) =>
    rings.map((r) => r.map(([lon, lat], i) => `${i ? "L" : "M"}${project(lon, lat).map((v) => v.toFixed(1)).join(" ")}`).join("") + "Z").join("");
  return (
    <figure className="event-map advisory-chart">
      <svg viewBox={`0 0 ${chartBounds.width} ${chartBounds.height}`} role="img" aria-label={`${shapes.length} mapped official warning areas on a chart of India's seas.`}>
        <rect width={chartBounds.width} height={chartBounds.height} fill="#123f6b" />
        <path d={landPath} fill="#eef2f3" stroke="#8fb1cc" strokeWidth="0.8" />
        {shapes.map(({ b, p }, idx) => (
          <path key={`${b.message.revision_id}-${idx}`} d={d(p.coordinates)} fill={b.lifecycle.state === "active" ? "#d23f2a" : "#8a98a6"} fillOpacity=".35" stroke={b.lifecycle.state === "active" ? "#a8301d" : "#6b7a88"} strokeWidth="1">
            <title>{`${sender(b.message.sender)}: ${b.message.infos[0]?.event ?? ""} (${label(b.lifecycle.state)})`}</title>
          </path>
        ))}
      </svg>
      <figcaption>
        {shapes.length ? `${shapes.length} mapped areas.` : "No bulletin in this set has a mapped area."} Bulletins that only name places aren’t drawn, because guessing their outline could mislead.
      </figcaption>
    </figure>
  );
}
