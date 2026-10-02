import Link from "next/link";
import type { ExpectedProfile } from "../../../lib/expected";
const number = (n: number | null) =>
  n === null ? "Unavailable" : n.toFixed(3);
const featureName: Record<string, string> = {
  latitude: "latitude",
  longitude: "longitude",
  depth_m: "depth",
  season_sin: "annual seasonal phase",
  season_cos: "annual seasonal phase",
  season_sin2: "second seasonal harmonic",
  season_cos2: "second seasonal harmonic",
  basin_id: "broad basin",
};
export default function ExpectedState({
  value,
  revision,
}: {
  value: ExpectedProfile | null;
  revision: string;
}) {
  if (!value || value.revision_sha256 !== revision)
    return (
      <section>
        <h2>Expected state</h2>
        <p>Matching model evidence is unavailable for this profile revision.</p>
        <Link href="/models">Review model references →</Link>
      </section>
    );
  if (!value.result || !value.calculation_id)
    return (
      <section>
        <h2>Expected state</h2>
        <p>
          {value.status === "pending"
            ? "The model comparison is pending; original observations and historical comparisons remain available."
            : value.status === "reference_mismatch"
              ? "The selected model and historical reference differ. Matching model evidence is unavailable."
              : "No supported model release has been selected."}
        </p>
        <Link href="/models">Review model references →</Link>
      </section>
    );
  const fallback = Object.values(value.active_methods ?? {}).every(
    (v) => v === "climatology",
  );
  return (
    <section>
      <h2>Expected state and residual model</h2>
      <p>
        {fallback
          ? "Climatology remains the serving mean. Candidate values are diagnostic because promotion gates have not passed."
          : "The serving mean combines historical climatology with a qualified residual candidate where coverage supports it."}{" "}
        These are conditional means. Review the separate predictive interval
        evidence below. Profile anomaly verdicts remain unavailable.
      </p>
      <div className="evidence-links">
        <Link href={`/models/${value.release_id}`}>
          Model, held-out comparisons and promotion evidence →
        </Link>
        <Link href={`/calculations/${value.calculation_id}`}>
          Pinned inference evidence →
        </Link>
      </div>
      {(["temperature_c", "practical_salinity"] as const).map((variable) => (
        <section key={variable}>
          <h3>
            {variable === "temperature_c"
              ? "Temperature (°C)"
              : "Practical salinity (PSS-78)"}
          </h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Depth (m)</th>
                  <th>Observed</th>
                  <th>Historical mean</th>
                  <th>Candidate residual</th>
                  <th>Candidate mean</th>
                  <th>Serving mean</th>
                  <th>Difference</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {value.result!.rows.map((row) => {
                  const p = row[variable];
                  return (
                    <tr key={row.depth_m}>
                      <td>{row.depth_m}</td>
                      <td>{number(p.observed)}</td>
                      <td>{number(p.climatology_mean)}</td>
                      <td>{number(p.candidate_residual)}</td>
                      <td>{number(p.candidate_mean)}</td>
                      <td>{number(p.expected_mean)}</td>
                      <td>
                        {number(p.difference)}
                        <small>{p.direction}</small>
                      </td>
                      <td>
                        {p.active_method.replaceAll("_", " ")}
                        {p.candidate_reason ? (
                          <small>
                            {p.candidate_reason.replaceAll("_", " ")}
                          </small>
                        ) : null}
                        {p.feature_contributions.length ? (
                          <details>
                            <summary>Residual model explanation</summary>
                            <p>
                              Largest contributions:{" "}
                              {[...p.feature_contributions]
                                .sort(
                                  (a, b) =>
                                    Math.abs(b.contribution) -
                                    Math.abs(a.contribution),
                                )
                                .slice(0, 3)
                                .map(
                                  (c) =>
                                    `${featureName[c.feature] ?? c.feature}: ${c.contribution >= 0 ? "+" : ""}${c.contribution.toFixed(3)}`,
                                )
                                .join("; ")}
                              .
                            </p>
                            <p>
                              Model bias: {number(p.contribution_bias)}. All
                              eight feature contributions plus this bias sum to
                              the candidate residual; the three largest are
                              shown above. They explain the model and do not
                              prove oceanographic causation.
                            </p>
                          </details>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </section>
  );
}
