import Link from "next/link";
import {evidence} from "../../lib/science";
import {title, type AnomalySummary} from "../../lib/anomaly";
import { PageHead } from "../components/ui/Bits";
import { when } from "../../lib/humanize";
export const dynamic = "force-dynamic";
export default async function Anomalies() {
  const data = await evidence<{items: AnomalySummary[]}>("/anomaly-releases?limit=50");
  return <main>
      <PageHead icon="pin" back={{ href: "/behind-the-data", label: "Behind the data" }} title={"Unusual floats"} lede={"How float readings are ranked against history to spot the ones that stand out."} /><p className="notice">These models are diagnostic prototypes. Historical percentiles are descriptive; expert events, quiet-period false-alert rates and independent scientific release approval remain unavailable.</p>
  {!data?<p>The profile model evidence service is unavailable.</p>:!data.items.length?<p>No profile model release has been built.</p>:<div className="table-scroll"><table><thead><tr><th>Release</th><th>State</th><th>Supported variables</th><th>Created</th><th>Coverage</th></tr></thead><tbody>{data.items.map(r=><tr key={r.release_id}><td className="digest"><Link href={`/anomalies/${r.release_id}`}>{r.release_id}</Link></td><td>{r.selected?"Selected":"Retained"} · {r.status}</td><td>{(r.supported_variables ?? []).map(title).join(", ") || "Unavailable"}</td><td>{when(r.created_at)}</td><td>Complete 10–500 m</td></tr>)}</tbody></table></div>}</main>;
}
