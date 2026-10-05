import Link from "next/link";
import { evidence } from "../../../lib/science";
import { eventLabel, eventNumber, type EventDetail } from "../../../lib/events";
import EventMap from "../EventMap";
import { PageHead } from "../../components/ui/Bits";
export const metadata = { title: "Regional event · Nautiq" };
export const dynamic = "force-dynamic";
export default async function EventPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const result = /^[a-f0-9-]{36}$/.test(id)
    ? await evidence<EventDetail>(`/events/${id}`)
    : null;
  if (!result)
    return (
      <main><PageHead back={{ href: "/events", label: "Event evidence" }} title="Component evidence unavailable" lede={"Its retained source/report integrity could not be verified."} /></main>
    );
  const e = result.event;
  const positions =
    e.geometry.type === "MultiPoint"
      ? (e.geometry.coordinates as number[][])
      : [];
  const thermal = e.kind === "surface_thermal_candidate";
  const box = positions.length
    ? [
        Math.min(...positions.map((p) => p[0])) - 0.5,
        Math.min(...positions.map((p) => p[1])) - 0.5,
        Math.max(...positions.map((p) => p[0])) + 0.5,
        Math.max(...positions.map((p) => p[1])) + 0.5,
      ]
    : null;
  return (
    <main>
      <PageHead back={{ href: "/events", label: "Regional events" }} title={<>{eventLabel(e.kind)}</>} lede={<>{e.variable} · {e.start} to {e.end}. {e.persistence_days} supported
        days; {e.duration_days} calendar days. {result.input_state}.</>} />
      <p className="notice">
        Diagnostic evidence only.{" "}
        {thermal
          ? "This is a persistent regional SST candidate with a fixed historical threshold."
          : "Point groups retain sparse observed support. They are not a marine heatwave or a dense event polygon."}
      </p>
      <dl className="field-metadata">
        <div>
          <dt>Mean / maximum intensity</dt>
          <dd>
            {eventNumber(e.mean_intensity)} / {eventNumber(e.maximum_intensity)}{" "}
            {e.units}
          </dd>
        </div>
        <div>
          <dt>Support</dt>
          <dd>
            {thermal
              ? `${e.cell_count} unique cells; ${e.cell_days} cell days`
              : `${e.profile_count} profiles; ${e.platform_count} platforms`}
          </dd>
        </div>
        <div>
          <dt>Boundary / category</dt>
          <dd>
            {thermal
              ? `Left censored: ${e.left_censored}; right censored: ${e.right_censored}; maximum category ${e.maximum_category} (prototype)`
              : e.coverage_state}
          </dd>
        </div>
        <div>
          <dt>Event / report hash</dt>
          <dd className="digest">
            {e.event_id}
            <br />
            {result.report_sha256}
          </dd>
        </div>
      </dl>
      {box ? (
        <EventMap events={[e]} extent={box} />
      ) : (
        <p>
          Exact native-cell geometry is shown on the{" "}
          <Link href={`/events/runs/${result.run_id}`}>source-window map</Link>;
          its footprint excludes masked cells.
        </p>
      )}
      {e.daily_support ? (
        <>
          <h2>Daily regional support and anomaly</h2>
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Daily component evidence"
          >
            <table>
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Cells</th>
                  <th>Area km²</th>
                  <th>Mean / max anomaly °C</th>
                  <th>Regional support</th>
                </tr>
              </thead>
              <tbody>
                {e.daily_support.map((d) => (
                  <tr key={d.day}>
                    <td>{d.day}</td>
                    <td>{d.cells}</td>
                    <td>{eventNumber(d.area_km2)}</td>
                    <td>
                      {eventNumber(d.mean_intensity)} /{" "}
                      {eventNumber(d.maximum_intensity)}
                    </td>
                    <td>
                      {d.supported_regional_day
                        ? "Supported"
                        : "Below regional minimum"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <>
          <h2>Supporting profile observations</h2>
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Profile point support"
          >
            <table>
              <thead>
                <tr>
                  <th>Profile</th>
                  <th>Platform</th>
                  <th>Day</th>
                  <th>Position</th>
                  <th>Historical rank</th>
                </tr>
              </thead>
              <tbody>
                {(
                  e.members as {
                    profile_id: string;
                    platform_id: string;
                    day: string;
                    latitude: number;
                    longitude: number;
                    percentile: number;
                  }[]
                ).map((p) => (
                  <tr key={p.profile_id}>
                    <td>
                      <Link href={`/profiles/${p.profile_id}`}>
                        {p.profile_id}
                      </Link>
                    </td>
                    <td>{p.platform_id}</td>
                    <td>{p.day}</td>
                    <td>
                      {eventNumber(p.latitude)}°, {eventNumber(p.longitude)}°
                    </td>
                    <td>{eventNumber(p.percentile)}th percentile</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  );
}
