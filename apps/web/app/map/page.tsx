import Link from "next/link";
import { evidence } from "../../lib/science";
import type { MapOverview } from "../../lib/product";
import { observationWindow } from "../../lib/profiles";
import { coords, humanizeText, label, short, span, when } from "../../lib/humanize";
import OceanMap from "./OceanMap";
import { TechDetail, Notice } from "../components/ui/Bits";
export const dynamic = "force-dynamic";
export const metadata = { title: "Ocean map · Nautiq" };

export default async function OceanMapPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const [p, defaults] = await Promise.all([searchParams, observationWindow()]);
  const text = (key: string, fallback: string) => (typeof p[key] === "string" ? (p[key] as string) : fallback);
  const bbox = text("bbox", "45,0,100,30"),
    start = text("start", defaults.start),
    end = text("end", defaults.end);
  const query = new URLSearchParams({ bbox, start: `${start}T00:00:00Z`, end: `${end}T00:00:00Z` });
  const value = await evidence<MapOverview>(`/map/overview?${query}`);
  return (
    <main className="map-main">
      {value ? (
        <OceanMap value={value} />
      ) : (
        <div style={{ paddingTop: 48 }}>
          <Notice tone="caution" title="The map data is unavailable">
            <p>Check the dates below (at most 366 days) or try again shortly. The other pages still work.</p>
          </Notice>
        </div>
      )}
      <div className="map-below">
        <TechDetail summary="Everything on the map, as a list">
          <form className="form-grid" method="get">
            <label>
              From
              <input name="start" type="date" required defaultValue={start} />
            </label>
            <label>
              Until (not included)
              <input name="end" type="date" required defaultValue={end} />
            </label>
            <label>
              Area (west, south, east, north)
              <input name="bbox" required defaultValue={bbox} />
            </label>
            <button className="btn">Update the map</button>
          </form>
          {value ? (
            <>
              <p>
                Showing {span(value.start, value.end)}. Patches are{" "}
                {label(value.event_state).toLowerCase()}.
              </p>
              <h3>Float readings</h3>
              <div className="table-scroll" role="region" aria-label="Float readings" tabIndex={0}>
                <table>
                  <thead>
                    <tr>
                      <th>Float</th>
                      <th>Where</th>
                      <th>When</th>
                      <th>Version</th>
                    </tr>
                  </thead>
                  <tbody>
                    {value.profiles.map((f) => (
                      <tr key={f.id}>
                        <td><Link href={`/profiles/${f.id}`}>Float {f.platform_id}</Link></td>
                        <td>{coords(f.latitude, f.longitude)}</td>
                        <td>{when(f.observed_at)}</td>
                        <td className="digest">{short(f.revision_sha256)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h3>Unusual patches</h3>
              <ul>
                {value.events.map((e) => (
                  <li key={e.event_id}>
                    <Link href={`/events/${e.event_id}`}>{label(e.kind)} · {span(e.start, e.end)}</Link>
                  </li>
                ))}
                {!value.events.length ? <li className="muted">Nothing mapped for this period.</li> : null}
              </ul>
              <h3>Limits of this map</h3>
              <ul>
                {value.unavailable_layers.map((v) => (
                  <li key={v}>{label(v)}: not available yet.</li>
                ))}
                {value.limitations.map((v) => (
                  <li key={v}>{humanizeText(v)}</li>
                ))}
              </ul>
            </>
          ) : null}
        </TechDetail>
      </div>
    </main>
  );
}
