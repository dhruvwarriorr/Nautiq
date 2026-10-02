import Link from "next/link";
import { evidence } from "../../../lib/science";
import type { Reference, Metric } from "../../../lib/climatology";
export const dynamic = "force-dynamic";
const number = (value: number | null) =>
  value == null ? "Unavailable" : value.toFixed(3);
function MetricCells({ m }: { m: Metric }) {
  return (
    <>
      <td>
        {m.profiles} / {m.evaluated_rows}
      </td>
      <td>{number(m.profile_weighted_mae)}</td>
      <td>{number(m.mae)}</td>
      <td>{number(m.rmse)}</td>
      <td>{number(m.bias)}</td>
    </>
  );
}
export default async function ReferencePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const release = await evidence<Reference>(
    `/climatology-releases/${encodeURIComponent(id)}`,
  );
  if (!release)
    return (
      <main>
        <Link href="/climatology">← References</Link>
        <h1>Reference unavailable.</h1>
        <p>The reference is absent or its evidence service is unavailable.</p>
      </main>
    );
  const out = release.manifest.output,
    policy = release.manifest.policy.climatology_policy;
  return (
    <main className="explorer">
      <nav>
        <Link href="/climatology">← Historical references</Link>
        <Link href="/profiles">Argo profiles</Link>
        <Link href="/data">Data quality</Link>
      </nav>
      <p className="eyebrow">CLIMATOLOGY / FROZEN REFERENCE</p>
      <h1>A seasonal mean, with limits.</h1>
      <dl className="evidence">
        <dt>Reference</dt>
        <dd className="digest">{release.release_id}</dd>
        <dt>Fitting years</dt>
        <dd>
          {out.fitting_period.start_year}–{out.fitting_period.end_year} ·
          training partition only
        </dd>
        <dt>Dataset years</dt>
        <dd>
          {out.dataset_baseline.start_year}–{out.dataset_baseline.end_year} ·
          later blocks reserved for evaluation
        </dd>
        <dt>Dataset</dt>
        <dd>
          <Link href={`/training-snapshots/${release.snapshot_id}`}>
            {release.snapshot_id}
          </Link>
        </dd>
        <dt>Calculation</dt>
        <dd>
          <Link href={`/calculations/${release.calculation_id}`}>
            {release.calculation_id}
          </Link>
        </dd>
        <dt>Profiles / grid rows</dt>
        <dd>
          {out.profile_count} / {out.standard_grid_rows}
        </dd>
        <dt>Reference support</dt>
        <dd>
          {out.model_count} fitted pools ·{" "}
          {release.selected ? "selected" : "retained"} · {release.status}
        </dd>
        <dt>Standard depths (m)</dt>
        <dd>{policy.standard_depths_m.join(", ")}</dd>
        <dt>Interpolation</dt>
        <dd>
          Consecutive accepted native levels, maximum{" "}
          {policy.max_interpolation_gap_m} m gap; no extrapolation
        </dd>
        <dt>Minimum fitting support</dt>
        <dd>
          {policy.min_profiles} profiles, {policy.min_platforms} platforms,{" "}
          {policy.min_months} months and two years per pool
        </dd>
        <dt>Scientific release approval</dt>
        <dd>Not approved · local prototype</dd>
        <dt>Training data fingerprint</dt>
        <dd className="digest">{out.fit_hash}</dd>
      </dl>
      <p>
        Fallback order: 5° cell at the requested depth, broad basin at that
        depth, then a basin depth band with linear and quadratic depth terms.
        Each estimate stays within its training position and depth envelope.
        Unsupported estimates remain unavailable.
      </p>
      {out.limitations.map((text) => (
        <p className="notice" key={text}>
          {text}
        </p>
      ))}
      <h2>Held-out performance</h2>
      <p>
        Errors are observed minus expected, in °C or PSS-78. Profile weighting
        gives each observed profile equal weight across its supported depths.
        Counts and unavailable coverage remain part of the evaluation.
      </p>
      {Object.entries(release.evaluation.variables).map(
        ([variable, partitions]) => (
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
                    <th>Partition</th>
                    <th>Profiles / rows</th>
                    <th>Profile MAE</th>
                    <th>Row MAE</th>
                    <th>RMSE</th>
                    <th>Bias</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(partitions).map(([name, p]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <MetricCells m={p.overall} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h4>Test by region and depth</h4>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Group</th>
                    <th>Profiles / rows</th>
                    <th>Profile MAE</th>
                    <th>Row MAE</th>
                    <th>RMSE</th>
                    <th>Bias</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries({
                    ...partitions.test.regions,
                    ...Object.fromEntries(
                      Object.entries(partitions.test.depths).map(([z, m]) => [
                        `${z} m`,
                        m,
                      ]),
                    ),
                  }).map(([name, m]) => (
                    <tr key={name}>
                      <td>{name.replaceAll("_", " ")}</td>
                      <MetricCells m={m} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>
              Exploratory 95% profile-bootstrap interval for test profile MAE:{" "}
              {partitions.test.overall.profile_bootstrap_mae_95
                ?.map(number)
                .join("–") ?? "Unavailable"}
              .
            </p>
            <details>
              <summary>Coverage, errors and pooled fallback counts</summary>
              <pre className="audit-json">
                {JSON.stringify(partitions, null, 2)}
              </pre>
            </details>
          </section>
        ),
      )}
      <p>{release.evaluation.bootstrap_limitations}</p>
      <details>
        <summary>Frozen training support and policy</summary>
        <pre className="audit-json">
          {JSON.stringify({ support: out.support_models, policy }, null, 2)}
        </pre>
      </details>
    </main>
  );
}
