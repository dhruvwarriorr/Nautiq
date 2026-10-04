import {evidence} from "../../../lib/science";
import type {FieldRelease} from "../../../lib/fields";
import FieldViewer from "../FieldViewer";
import { PageHead } from "../../components/ui/Bits";
import { when } from "../../../lib/humanize";
export const dynamic = "force-dynamic";
export default async function FieldPage({params}: {params: Promise<{id: string}>}) {
  const {id} = await params;
  const release = /^[a-f0-9-]{36}$/.test(id) ? await evidence<FieldRelease>(`/fields/${id}`) : null;
  if (!release) return <main><PageHead back={{ href: "/fields", label: "Field catalog" }} title="Field evidence unavailable" lede={"This release is absent or its evidence service is unavailable."} /></main>;
  return <main>
      <PageHead back={{ href: "/fields", label: "Forecast layers" }} title={<>{release.metadata.product}</>} lede={<>{release.metadata.attribution}</>} /><p className="notice">{release.freshness === "stale" ? "This retained source exceeds its freshness budget. Values are historical evidence, with stale status. " : ""}Forecast uncertainty, tides and local hazards remain outside this field view. No trip verdict is produced.</p>
  <dl className="field-metadata"><div><dt>Initialization cycle</dt><dd>{release.cycle ?? "None · daily blended analysis"}</dd></div><div><dt>Valid window (UTC)</dt><dd>{when(release.metadata.valid_time_start)} to {when(release.metadata.valid_time_end)}</dd></div><div><dt>Normalized release created (UTC)</dt><dd>{new Date(release.created_at).toISOString().slice(0,19).replace("T"," ")} UTC</dd></div><div><dt>Source revision / selection</dt><dd>{release.source_version} · {release.selected ? "Selected" : "Retained"} · {release.status} · {release.freshness}</dd></div><div><dt>Release / manifest SHA-256</dt><dd className="digest">{release.release_id}<br />{release.manifest_sha256}</dd></div></dl>
  {release.status === "ready" ? <FieldViewer releaseId={release.release_id} metadata={release.metadata} /> : <p>Verified chunks or the field policy are unavailable. Sampling is withheld until a compatible release is ready.</p>}
  <section><h2>Native coverage and limits</h2><p>Latitude {release.metadata.extent[1]}° to {release.metadata.extent[3]}°; longitude {release.metadata.extent[0]}° to {release.metadata.extent[2]}°. Native grid: {release.metadata.resolution.latitude_degrees.toFixed(3)}° × {release.metadata.resolution.longitude_degrees.toFixed(3)}°.</p><div className="table-scroll" tabIndex={0} role="region" aria-label="Native variable coverage"><table><thead><tr><th>Variable</th><th>Units</th><th>Masked cells across retained times</th></tr></thead><tbody>{release.metadata.variables.map(v => <tr key={v}><td>{release.metadata.variable_metadata[v].label}</td><td>{release.metadata.variable_metadata[v].units}</td><td>{release.metadata.mask_counts[v].toLocaleString("en")}</td></tr>)}</tbody></table></div><ul>{release.metadata.limitations.map(l => <li key={l}>{l}</li>)}</ul></section>
  {release.manifest ? <section><h2>Retained source bytes</h2>{release.manifest.raw.map(raw => <p className="digest" key={raw.sha256}><a href={raw.url}>Provider request ↗</a> · {raw.bytes.toLocaleString("en")} bytes<br />SHA-256 {raw.sha256}</p>)}</section> : null}</main>;
}
