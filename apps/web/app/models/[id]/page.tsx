import Link from "next/link";
import { evidence } from "../../../lib/science";
import type { ModelRelease, ModelMetric } from "../../../lib/expected";
import { PageHead } from "../../components/ui/Bits";
export const metadata = { title: "Model · Nautiq" };
export const dynamic = "force-dynamic";
const number = (n: number | null) =>
  n === null ? "Unavailable" : n.toFixed(3);
function Metrics({ value }: { value: ModelMetric }) {
  return (
    <>
      <td>
        {value.profiles} / {value.rows}
      </td>
      <td>{number(value.profile_weighted_mae)}</td>
      <td>{number(value.mae)}</td>
      <td>{number(value.rmse)}</td>
      <td>{number(value.bias)}</td>
    </>
  );
}
const title = (v: string) =>
  v === "temperature_c" ? "Temperature (°C)" : "Practical salinity (PSS-78)";
export default async function Model({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const model = await evidence<ModelRelease>(
    `/expected-state-releases/${encodeURIComponent(id)}`,
  );
  if (!model)
    return (
      <main><PageHead back={{ href: "/models", label: "Models" }} title="Model evidence unavailable" lede={"This release is absent or its evidence service is unavailable."} /></main>
    );
  const out = model.manifest.output;
  return (
    <main>
      <PageHead back={{ href: "/models", label: "Models" }} title={"Model release"} lede={"How this learned model compared with the seasonal normal, step by step."} />
      <p className="notice">
        Scientific production approval is unavailable. The inspected historical
        test block remains diagnostic; promotion requires reviewed thresholds, a
        new untouched test and approved independence and source coverage audits.
      </p>
      <dl className="evidence">
        <dt>Model release</dt>
        <dd className="digest">{model.release_id}</dd>
        <dt>State</dt>
        <dd>
          {model.selected ? "Selected" : "Retained"} · {model.status}
        </dd>
        <dt>Fitting years</dt>
        <dd>
          {out.fitting_period.start_year}–{out.fitting_period.end_year}
        </dd>
        <dt>Snapshot</dt>
        <dd>
          <Link href={`/training-snapshots/${model.snapshot_id}`}>
            {model.snapshot_id}
          </Link>
        </dd>
        <dt>Fit calculation</dt>
        <dd>
          <Link href={`/calculations/${model.calculation_id}`}>
            {model.calculation_id}
          </Link>
        </dd>
        <dt>Bundle checksum</dt>
        <dd className="digest">{out.bundle_sha256}</dd>
        <dt>Code fingerprint</dt>
        <dd className="digest">{model.report.code_sha256}</dd>
        <dt>Feature version</dt>
        <dd>{model.report.feature_schema.version}</dd>
        <dt>Reference features</dt>
        <dd>{model.report.feature_schema.names.join(", ")}</dd>
        <dt>Static coastal features</dt>
        <dd>
          Bathymetry and coast distance omitted until their sources are
          validated
        </dd>
        <dt>MLflow registry</dt>
        <dd>
          {model.tracking
            ? `${model.tracking.registered_model}, version ${model.tracking.model_version}; run ${model.tracking.run_id}`
            : "Experiment logging pending"}
        </dd>
      </dl>
      <p>
        All depths of a stable profile share one temporal partition. Candidate
        settings and early stopping use tuning profiles; calibration and test
        labels do not alter the fitted trees. Outputs estimate a conditional
        mean, with no median or calibrated interval claim.
      </p>
      {Object.entries(model.report.variables).map(([variable, result]) => (
        <section key={variable}>
          <h2>{title(variable)}</h2>
          <p>
            Serving method:{" "}
            {result.promotion.active_method.replaceAll("_", " ")}.{" "}
            {result.promotion.eligible
              ? "Candidate passed its configured gates."
              : "Candidate remains diagnostic; climatology stays active."}
          </p>
          {!result.evaluation ? (
            <p>
              {result.reason?.replaceAll("_", " ") ??
                "Insufficient training support."}
            </p>
          ) : (
            <>
              <h3>Training and held-out comparison</h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Partition / method</th>
                      <th>Profiles / rows</th>
                      <th>Profile MAE</th>
                      <th>Row MAE</th>
                      <th>RMSE</th>
                      <th>Bias</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(result.evaluation).flatMap(
                      ([partition, methods]) =>
                        Object.entries(methods).map(([method, groups]) => (
                          <tr key={`${partition}-${method}`}>
                            <td>
                              {partition} / {method}
                            </td>
                            <Metrics value={groups.overall} />
                          </tr>
                        )),
                    )}
                  </tbody>
                </table>
              </div>
              <h3>Test groups, on matching supported rows</h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Group / method</th>
                      <th>Profiles / rows</th>
                      <th>Profile MAE</th>
                      <th>Row MAE</th>
                      <th>RMSE</th>
                      <th>Bias</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(result.evaluation.test).flatMap(
                      ([method, groups]) =>
                        Object.entries(groups)
                          .filter(([name]) => name !== "overall")
                          .map(([name, metric]) => (
                            <tr key={`${method}-${name}`}>
                              <td>
                                {name.replaceAll("_", " ")} / {method}
                              </td>
                              <Metrics value={metric} />
                            </tr>
                          )),
                    )}
                  </tbody>
                </table>
              </div>
              <p>
                Unsupported or missing variable/depth rows:{" "}
                {result.missing_or_unsupported_rows}. Coastal-distance grouping
                is unavailable. Sparse subgroups keep their counts and null
                metrics.
              </p>
            </>
          )}
          <details>
            <summary>Tuning choices and promotion checks</summary>
            <pre className="audit-json">
              {JSON.stringify(
                {
                  selected: result.selected,
                  promotion: result.promotion,
                  profile_counts: result.profile_counts,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </section>
      ))}
      <h2>Spatial and platform independence audits</h2>
      <p>
        Each fold rebuilds the entire climatology and residual candidates on the
        held-group complement. Spatial folds exclude a geographic buffer. These
        bounded diagnostics require review and may lack fitting or held-out
        support.
      </p>
      {model.report.independence_audits.map((fold) => (
        <section key={fold.fold}>
          <h3>{fold.fold}</h3>
          <p>
            {fold.complement_profiles} complement profiles; {fold.held_profiles}{" "}
            held profiles.
          </p>
          <ul>
            {Object.entries(fold.variables).map(([v, r]) => (
              <li key={v}>
                {title(v)}: {r.status};{" "}
                {r.held_evaluation
                  ? `${r.held_supported_rows} supported held rows, profile MAE ${number(r.held_evaluation.profile_weighted_mae)}`
                  : r.reason?.replaceAll("_", " ")}
                {r.held_comparison ? (
                  <span>
                    {" · "}
                    {Object.entries(r.held_comparison)
                      .map(
                        ([method, metric]) =>
                          `${method}: ${number(metric.profile_weighted_mae)}`,
                      )
                      .join("; ")}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ))}
      <p>{model.report.bootstrap_limitations}</p>
    </main>
  );
}
