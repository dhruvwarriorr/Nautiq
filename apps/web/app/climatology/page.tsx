import Link from "next/link";
import { evidence } from "../../lib/science";
import type { ReferenceSummary } from "../../lib/climatology";
import { PageHead } from "../components/ui/Bits";
export const dynamic = "force-dynamic";
export default async function References() {
  const [selected, releases] = await Promise.all([
    evidence<ReferenceSummary>("/climatology-releases/selected"),
    evidence<{ items: ReferenceSummary[] }>("/climatology-releases?limit=50"),
  ]);
  return (
    <main>
      <PageHead icon="waves" back={{ href: "/behind-the-data", label: "Behind the data" }} title={"Historical normal"} lede={"What the sea is usually like at each place, depth and season, from 2005–2016 float data."} />
      <p className="notice">
        Local scientific prototype. Spatial and platform independence, coastal
        coverage and production approval remain unverified. Spread is training
        residual variability, with uncalibrated coverage.
      </p>
      {selected ? (
        <p>
          Selected reference:{" "}
          <Link href={`/climatology/${selected.release_id}`}>
            {selected.release_id}
          </Link>{" "}
          · fitted {selected.fitting_period.start_year}–
          {selected.fitting_period.end_year}
        </p>
      ) : (
        <p>
          No historical reference is currently selected, or the evidence service
          is unavailable.
        </p>
      )}
      <h2>Frozen references</h2>
      {releases ? (
        releases.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Reference</th>
                  <th>Fitting years</th>
                  <th>Supported pools</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {releases.items.map((r) => (
                  <tr key={r.release_id}>
                    <td>
                      <Link href={`/climatology/${r.release_id}`}>
                        {r.release_id}
                      </Link>
                    </td>
                    <td>
                      {r.fitting_period.start_year}–{r.fitting_period.end_year}
                    </td>
                    <td>{r.model_count}</td>
                    <td>
                      {r.selected ? "Selected" : "Retained"} · {r.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>No frozen reference has been built.</p>
        )
      ) : (
        <p role="alert">Reference inventory is unavailable.</p>
      )}
    </main>
  );
}
