import Link from "next/link";
import {evidence} from "../../lib/science";
import type {FieldRelease} from "../../lib/fields";
import { PageHead } from "../components/ui/Bits";
import { when } from "../../lib/humanize";
export const dynamic = "force-dynamic";
const productNames: Record<string,string> = {noaa_oisst: "SST analysis", noaa_gfs_wave: "Wave forecasts", noaa_gfs_weather: "Wind and weather", hycom_espc: "Surface currents"};
export default async function Fields() {
  const data = await evidence<{items: FieldRelease[]; products: {product_id: string; selected_release_id: string | null; latest_run: {status: string; completed_at: string | null; reason_code: string | null} | null}[]}>("/fields?limit=50");
  return <main>
      <PageHead icon="layers" back={{ href: "/behind-the-data", label: "Behind the data" }} title={"Forecast layers"} lede={"The raw forecast and satellite grids behind every reading, with when each was issued."} /><p className="notice">Regional products retain coastal masks and missing times. These samples support inspection; local hazards, advisory completeness and trip assessments remain unavailable.</p>
  {!data ? <p>The field catalog is unavailable.</p> : <>
  <div className="evidence-grid">{data.products.map(p => <section key={p.product_id}><h2>{productNames[p.product_id] ?? p.product_id}</h2><p>{p.selected_release_id ? <Link href={`/fields/${p.selected_release_id}`}>Open selected field →</Link> : "No verified field has been ingested."}</p><p className="footnote">Latest acquisition: {p.latest_run?.status ?? "Not run"}{p.latest_run?.reason_code ? ` · ${p.latest_run.reason_code}` : ""}{p.latest_run?.completed_at ? ` · ${p.latest_run.completed_at}` : ""}</p></section>)}</div>
  <h2>Retained releases</h2>{!data.items.length ? <p>No field releases are available. The catalog keeps acquisition failures explicit.</p> : <div className="table-scroll"><table><thead><tr><th>Product</th><th>Cycle / analysis day</th><th>Valid window</th><th>State</th><th>Grid</th></tr></thead><tbody>{data.items.map(r => <tr key={r.release_id}><td><Link href={`/fields/${r.release_id}`}>{r.metadata.product}</Link><p className="digest">{r.release_id}</p></td><td>{r.cycle ?? `Daily analysis · ${r.metadata.valid_time_start.slice(0, 10)}`}<p>{r.source_version}</p></td><td>{when(r.metadata.valid_time_start)}<br />{when(r.metadata.valid_time_end)}</td><td>{r.selected ? "Selected" : "Retained"} · {r.status} · {r.freshness}</td><td>{r.metadata.shape.join(" × ")}<p>{r.metadata.resolution.latitude_degrees.toFixed(3)}° × {r.metadata.resolution.longitude_degrees.toFixed(3)}°</p></td></tr>)}</tbody></table></div>}</>}
  </main>;
}
