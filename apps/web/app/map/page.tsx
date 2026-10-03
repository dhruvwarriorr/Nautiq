import { evidence } from "../../lib/science";
import type { MapOverview } from "../../lib/product";
import { observationWindow } from "../../lib/profiles";
import SurfaceMap from "../components/SurfaceMap";
export const dynamic = "force-dynamic";
export default async function OceanMap({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [p, defaults] = await Promise.all([searchParams, observationWindow()]);
  const text = (key: string, fallback: string) =>
    typeof p[key] === "string" ? (p[key] as string) : fallback;
  const bbox = text("bbox", "45,0,100,30"),
    start = text("start", defaults.start),
    end = text("end", defaults.end);
  const query = new URLSearchParams({
    bbox,
    start: `${start}T00:00:00Z`,
    end: `${end}T00:00:00Z`,
  });
  const value = await evidence<MapOverview>(`/map/overview?${query}`);
  return (
    <main className="explorer">
      <p className="eyebrow">OCEAN MAP / SOURCE AND TIME</p>
      <h1>Explore the evidence in place.</h1>
      <p className="intro">
        Native surface fields, instrument positions, retained event support and
        official geometries. Every layer keeps its own coverage, age and
        uncertainty.
      </p>
      <form className="filters" method="get">
        <label>
          Bounding box (west, south, east, north)
          <input name="bbox" required defaultValue={bbox} />
        </label>
        <label>
          Observation start (UTC)
          <input name="start" type="date" required defaultValue={start} />
        </label>
        <label>
          Exclusive end (UTC)
          <input name="end" type="date" required defaultValue={end} />
        </label>
        <button className="button">Load evidence layers</button>
      </form>
      {value ? (
        <SurfaceMap value={value} />
      ) : (
        <p role="status" className="notice">
          Map evidence is unavailable or the bounds/time interval are invalid.
          Use a non-crossing box and at most 366 days; exact profile and field
          explorers remain available.
        </p>
      )}
    </main>
  );
}
