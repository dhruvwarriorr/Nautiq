import Link from "next/link";
import { evidence } from "../../lib/science";
import type { ModelSummary } from "../../lib/expected";
import ModelBrief from "../components/ModelBrief";
import { PageHead } from "../components/ui/Bits";
export const dynamic = "force-dynamic";
export default async function Models() {
  const [selected, models] = await Promise.all([
    evidence<ModelSummary>("/expected-state-releases/selected"),
    evidence<{ items: ModelSummary[] }>("/expected-state-releases?limit=50"),
  ]);
  return (
    <main>
      <PageHead icon="logbook" back={{ href: "/behind-the-data", label: "Behind the data" }} title={"Models"} lede={"What Nautiq tested, what it uses today, and why. Today a simple seasonal normal wins."} />
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
