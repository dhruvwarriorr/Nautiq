import Link from "next/link";
import { evidence } from "../../lib/science";
import type { ReferenceSummary } from "../../lib/climatology";
export const dynamic = "force-dynamic";
export default async function References() {
  const [selected, releases] = await Promise.all([
    evidence<ReferenceSummary>("/climatology-releases/selected"),
    evidence<{ items: ReferenceSummary[] }>("/climatology-releases?limit=50"),
  ]);
  return (
    <main className="explorer">
      <nav>
        <Link href="/">Nautiuq</Link>
        <Link href="/profiles">Argo profiles</Link>
        <Link href="/data">Data quality</Link>
        <Link href="/models">Expected-state models</Link>
      </nav>
      <p className="eyebrow">HISTORICAL / SEASONAL REFERENCE</p>
      <h1>Normal, with its evidence.</h1>
      <p className="intro">
        A fixed harmonic reference describes historical seasonal means. Compare
        observations at their own location, time and depth, with supported
        coverage and explicit pooled fallbacks.
      </p>
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
