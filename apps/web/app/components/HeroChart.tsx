import { chartBounds, landPath } from "../../lib/chart-land";
import type { Place } from "../../lib/product";

const { west, east, south, north, width, height } = chartBounds;
const merc = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
export const project = (lon: number, lat: number) => [
  ((lon - west) / (east - west)) * width,
  ((merc(north) - merc(lat)) / (merc(north) - merc(south))) * height,
];

/** A quiet chart of India's seas with each catalog place flown as a signal ball. */
export default function HeroChart({ places }: { places: Place[] }) {
  const lons = [65, 70, 75, 80, 85, 90, 95];
  const lats = [5, 10, 15, 20, 25];
  const hover = places
    .map(
      (p) =>
        `.hero:has([data-place="${p.slug}"]:is(:hover,:focus-visible)) .pin[data-place="${p.slug}"] .pin-ring{animation:ping 1.6s var(--ease) infinite}` +
        `.hero:has([data-place="${p.slug}"]:is(:hover,:focus-visible)) .pin[data-place="${p.slug}"] .pin-ball{fill:#fff}` +
        `.hero:has([data-place="${p.slug}"]:is(:hover,:focus-visible)) .pin[data-place="${p.slug}"] .pin-label{opacity:1}`,
    )
    .join("");
  return (
    <>
      <style>{hover}</style>
      <svg className="hero-chart" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        {lons.map((lon) => {
          const [x] = project(lon, 0);
          return (
            <g key={`lon${lon}`}>
              <line className="graticule" x1={x} x2={x} y1={0} y2={height} />
              <text className="tick" x={x + 6} y={height - 12}>{lon}°E</text>
            </g>
          );
        })}
        {lats.map((lat) => {
          const [, y] = project(west, lat);
          return (
            <g key={`lat${lat}`}>
              <line className="graticule" x1={0} x2={width} y1={y} y2={y} />
              <text className="tick" x={8} y={y - 6}>{lat}°N</text>
            </g>
          );
        })}
        <path className="land" d={landPath} />
        <text className="sea-name" x={project(68.6, 12)[0]} y={project(68.6, 12)[1]}>Arabian Sea</text>
        <text className="sea-name" x={project(84, 14)[0]} y={project(84, 14)[1]}>Bay of Bengal</text>
        <text className="sea-name" x={project(78, 3.5)[0]} y={project(78, 3.5)[1]}>Indian Ocean</text>
        {places.map((p) => {
          const [x, y] = project(p.longitude, p.latitude);
          return (
            <g key={p.slug} className="pin" data-place={p.slug} transform={`translate(${x} ${y})`}>
              <circle className="pin-ring" cx="0" cy="-26" r="9" />
              <line className="pin-staff" x1="0" y1="0" x2="0" y2="-18" />
              <circle className="pin-ball" cx="0" cy="-26" r="7" />
              <text className="pin-label" x="14" y="-21">{p.name}</text>
            </g>
          );
        })}
      </svg>
    </>
  );
}
