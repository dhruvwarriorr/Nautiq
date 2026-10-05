import Link from "next/link";
import { evidence } from "../../lib/science";
import type { IntervalSummary } from "../../lib/uncertainty";
import { PageHead } from "../components/ui/Bits";
export const metadata = { title: "Uncertainty · Nautiq" };
export const dynamic = "force-dynamic";
export default async function Intervals() {
  const [selected, releases] = await Promise.all([
    evidence<IntervalSummary>("/uncertainty-releases/selected"),
    evidence<{items: IntervalSummary[]}>("/uncertainty-releases?limit=50"),
  ]);
  return <main>
      <PageHead icon="compass" back={{ href: "/behind-the-data", label: "Behind the data" }} title={"Expected ranges"} lede={"How much the sea normally varies around its usual state, and how well that range holds up."} />
    <p className="notice">Local diagnostic intervals. The nominal 80% target concerns a profile within a region and depth group. It does not establish full-profile joint or conditional coverage. Scientific release approval requires reviewed gates and an untouched test.</p>
    <p>{selected ? <>Selected interval release: <Link href={`/uncertainty/${selected.release_id}`}>{selected.release_id}</Link></> : "No interval release selected, or evidence unavailable."}</p>
    <h2>Frozen interval releases</h2>
    {releases ? releases.items.length ? <div className="table-scroll"><table><thead><tr><th>Release</th><th>Temperature family</th><th>Salinity family</th><th>Calibration years</th><th>State</th></tr></thead><tbody>{releases.items.map(r => <tr key={r.release_id}><td><Link href={`/uncertainty/${r.release_id}`}>{r.release_id}</Link></td><td>{r.selected_families.temperature_c ?? "Unavailable"}</td><td>{r.selected_families.practical_salinity ?? "Unavailable"}</td><td>{r.calibration_period.start_year}–{r.calibration_period.end_year}</td><td>{r.selected ? "Selected" : "Retained"} · {r.status}</td></tr>)}</tbody></table></div> : <p>No interval releases built.</p> : <p role="alert">Interval evidence unavailable.</p>}
  </main>;
}
