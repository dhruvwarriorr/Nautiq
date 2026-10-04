import Link from "next/link";
import { evidence } from "../../lib/science";
import type { ModelSummary } from "../../lib/expected";
import ModelBrief from "../components/ModelBrief";
export const dynamic = "force-dynamic";
export default async function Models() {
  const [selected, models] = await Promise.all([
    evidence<ModelSummary>("/expected-state-releases/selected"),
    evidence<{ items: ModelSummary[] }>("/expected-state-releases?limit=50"),
  ]);
  return (
    <main className="explorer">
      <nav>
        <Link href="/">Nautiq</Link>
        <Link href="/profiles">Argo profiles</Link>
        <Link href="/climatology">Historical normal</Link>
        <Link href="/anomalies">Profile magnitude and shape</Link> <Link href="/uncertainty">Predictive intervals</Link>
        <Link href="/data">Data quality</Link>
        <Link href="/models/monitoring">Monitoring</Link>
      </nav>
      <p className="eyebrow">EXPECTED STATE / FROZEN MODEL COMPARISONS</p>
      <h1>The reference, and the model to beat it.</h1>
      <p className="intro">
        Residual models learn the structure left after the seasonal historical
        mean. Compare LightGBM with HGBR and climatology using fixed training
        inputs and separate evaluation blocks.
      </p>
      <ModelBrief />
      <p className="notice">
        Local prototype. Candidate performance does not establish scientific
        release approval. Unqualified candidates retain climatology as the
        serving mean; interval coverage remains diagnostic and anomaly verdicts are unavailable.
      </p>
      {selected ? (
        <p>
          Selected model release:{" "}
          <Link href={`/models/${selected.release_id}`}>
            {selected.release_id}
          </Link>
        </p>
      ) : (
        <p>
          No model release has been selected, or its evidence is unavailable.
        </p>
      )}
      <h2>Frozen model releases</h2>
      {models ? (
        models.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Release</th>
                  <th>Fitting years</th>
                  <th>Temperature mean</th>
                  <th>Salinity mean</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {models.items.map((m) => (
                  <tr key={m.release_id}>
                    <td>
                      <Link href={`/models/${m.release_id}`}>
                        {m.release_id}
                      </Link>
                    </td>
                    <td>
                      {m.fitting_period.start_year}–{m.fitting_period.end_year}
                    </td>
                    <td>
                      {m.active_methods.temperature_c.replaceAll("_", " ")}
                    </td>
                    <td>
                      {m.active_methods.practical_salinity.replaceAll("_", " ")}
                    </td>
                    <td>
                      {m.selected ? "Selected" : "Retained"} · {m.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>No model releases have been built.</p>
        )
      ) : (
        <p role="alert">Model evidence is unavailable.</p>
      )}
    </main>
  );
}
