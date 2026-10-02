import Link from "next/link";
import { apiURL, observationWindow, type Page } from "../../lib/profiles";
export const dynamic = "force-dynamic";
type Search = { [key: string]: string | string[] | undefined };
function date(value: string | undefined, fallback: string) {
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : fallback;
}
export default async function Profiles({
  searchParams,
}: {
  searchParams: Promise<Search>;
}) {
  const params = await searchParams;
  const input = (key: string) =>
    typeof params[key] === "string" ? (params[key] as string) : undefined;
  const defaults = await observationWindow();
  const end = date(input("end"), defaults.end);
  const start = date(input("start"), defaults.start);
  const bbox = input("bbox") ?? "45,0,100,30";
  const query = new URLSearchParams({
    bbox,
    start: start + "T00:00:00Z",
    end: end + "T00:00:00Z",
    limit: "50",
  });
  const cursor = input("cursor");
  if (cursor) query.set("cursor", cursor);
  let page: Page | null = null;
  let error = "";
  try {
    const response = await fetch(`${apiURL}/api/v1/profiles?${query}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(9000),
    });
    if (response.ok) page = await response.json();
    else {
      const problem = await response.json();
      error = problem.code ?? "observations_unavailable";
    }
  } catch {
    error = "observations_unavailable";
  }
  const next = new URLSearchParams({ bbox, start, end });
  if (page?.next_cursor) next.set("cursor", page.next_cursor);
  const box = bbox.split(",").map(Number);
  const validBox =
    box.length === 4 &&
    box.every(Number.isFinite) &&
    box[0] < box[2] &&
    box[1] < box[3];
  return (
    <main className="explorer">
      <nav>
        <Link href="/">Nautiuq</Link>
        <Link href="/climatology">Historical normal</Link>
        <Link href="/data">Data quality</Link>
        <Link href="/status">Platform health</Link>
      </nav>
      <p className="eyebrow">ARGO / OBSERVATION EXPLORER</p>
      <h1>A view into the water column.</h1>
      <p className="intro">
        Measured profiles from the International Argo Program. Each point is an
        instrument observation at its recorded position and time.
      </p>
      <form className="filters" action="/profiles" method="get">
        <label>
          Bounding box (west, south, east, north)
          <input name="bbox" defaultValue={bbox} required />
        </label>
        <label>
          Start date (UTC)
          <input type="date" name="start" defaultValue={start} required />
        </label>
        <label>
          End date (UTC, exclusive)
          <input type="date" name="end" defaultValue={end} required />
        </label>
        <button className="button" type="submit">
          Find profiles
        </button>
      </form>
      {error ? (
        <p role="alert" className="notice">
          Query unavailable: {error.replaceAll("_", " ")}. Use a valid box and a
          date range of at most 366 days.
        </p>
      ) : null}
      {page ? (
        <>
          <div className="summary">
            <span>
              {page.items.length} profiles on this page · All times UTC
            </span>
            <span>Snapshot: {page.snapshot_at}</span>
          </div>
          {validBox ? (
            <section aria-label="Profile location map" className="profile-map">
              <svg
                viewBox="0 0 900 380"
                role="img"
                aria-label="Longitude and latitude map of the current profile results"
              >
                <rect width="900" height="380" fill="#e1eeeb" />
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <g key={i}>
                    <path
                      d={`M ${60 + i * 156} 25 V 335 M 60 ${25 + i * 62} H 840`}
                      stroke="#bdcfca"
                      strokeWidth="1"
                    />
                    <text
                      x={60 + i * 156}
                      y="365"
                      textAnchor="middle"
                      fontSize="12"
                      fill="#4c6263"
                    >
                      {(box[0] + (i * (box[2] - box[0])) / 5).toFixed(1)}°E
                    </text>
                    <text
                      x="48"
                      y={29 + i * 62}
                      textAnchor="end"
                      fontSize="12"
                      fill="#4c6263"
                    >
                      {(box[3] - (i * (box[3] - box[1])) / 5).toFixed(1)}°N
                    </text>
                  </g>
                ))}
                {page.items.map((p) => (
                  <a
                    key={p.id}
                    href={`/profiles/${p.id}`}
                    aria-label={`Open Argo ${p.platform_id}, ${p.latitude.toFixed(2)} latitude, ${p.longitude.toFixed(2)} longitude`}
                  >
                    <circle
                      cx={
                        60 + ((p.longitude - box[0]) / (box[2] - box[0])) * 780
                      }
                      cy={
                        25 + ((box[3] - p.latitude) / (box[3] - box[1])) * 310
                      }
                      r="7"
                      fill="#163c40"
                      stroke="white"
                      strokeWidth="2"
                    >
                      <title>
                        {p.platform_id} · {p.observed_at}
                      </title>
                    </circle>
                  </a>
                ))}
              </svg>
              <p className="footnote">
                Coordinate map · markers show these results only. Use the table
                below for keyboard access and exact coordinates.
              </p>
            </section>
          ) : null}
          {page.items.length === 0 ? (
            <p className="notice">
              No accepted profiles in this query. Ingestion may still be
              processing; try a wider date range or refresh.
            </p>
          ) : (
            <div className="table-scroll">
              <table>
                <caption>QC accepted Argo profiles</caption>
                <thead>
                  <tr>
                    <th>Platform</th>
                    <th>Observed (UTC)</th>
                    <th>Coordinates</th>
                    <th>Data mode</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <Link href={`/profiles/${p.id}`}>
                          {p.platform_id} →
                        </Link>
                      </td>
                      <td>{p.observed_at.replace("T", " ")}</td>
                      <td>
                        {p.latitude.toFixed(3)}°, {p.longitude.toFixed(3)}°
                      </td>
                      <td>
                        {p.data_mode === "D"
                          ? "Delayed / adjusted"
                          : p.data_mode === "A"
                            ? "Real-time / adjusted"
                            : "Real-time / raw"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {page.next_cursor ? (
            <Link className="button" href={`/profiles?${next}`}>
              Next 50 profiles →
            </Link>
          ) : null}
        </>
      ) : null}
      <p className="footnote">
        Source: International Argo Program and contributing national programs ·{" "}
        <a href="https://doi.org/10.17882/42182">Argo dataset</a>. QC acceptance
        follows the local display policy; operational source approval and
        scientific model validation remain separate.
      </p>
    </main>
  );
}
