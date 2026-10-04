import Link from "next/link";
import { evidence } from "../../../lib/science";
import { num, pct, statusWords, type MonitoringResponse } from "../../../lib/monitoring";
export const dynamic = "force-dynamic";
export const metadata = { title: "Model monitoring · Nautiq" };
const names: Record<string, string> = { temperature_c: "Temperature", practical_salinity: "Salinity" };
function Chip({ status }: { status: string }) {
  const [icon, word, tone] = statusWords[status] ?? ["", status, "unavailable"];
  return (
    <span className="status-chip" data-status={tone}>
      <span aria-hidden="true">{icon}</span> {word}
    </span>
  );
}
export default async function Page() {
  const data = await evidence<MonitoringResponse>("/model-monitoring");
  const latest = data?.latest ?? null;
  const r = latest?.report;
  const old = latest ? latest.age_seconds > 48 * 3600 : false;
  return (
    <main className="explorer">
      <p className="eyebrow">MODELS / MONITORING</p>
      <h1>Is the model still behaving as expected?</h1>
      <p className="intro">
        Nautiq watches four things: whether new profiles look like the data the models were built on, how far expected values are from real outcomes, whether the profile-ranking system flags more profiles than it should, and whether the intervals still cover what they promise.
      </p>
      <p className="notice">
        A flag here starts an investigation. Nautiq never retrains, recalibrates or promotes a model on its own. Delayed-mode labels arrive one to two years after observation, so “not enough evidence” is expected today and is not a sign of good or bad health.
      </p>
      {!data ? (
        <p className="notice">Monitoring evidence is unavailable right now.</p>
      ) : !latest || !r ? (
        <section>
          <h2>No report yet</h2>
          <p>Monitoring has not been run. An operator runs it with <code>make model-monitor</code>; it reads stored comparisons and changes nothing.</p>
        </section>
      ) : (
        <>
          <section aria-labelledby="overall">
            <h2 id="overall">Overall</h2>
            <p>
              <Chip status={r.status} /> Checked {latest.checked_at.slice(0, 16).replace("T", " ")} UTC, covering profiles from the last {r.policy.window_days} days.
            </p>
            {old ? <p className="notice">This report is more than 48 hours old. Treat it as history.</p> : null}
            {!latest.pins_current ? <p className="notice">The selected releases have changed since this report. Run monitoring again.</p> : null}
            {r.flags.length ? (
              <ul>
                {r.flags.map((f) => (
                  <li key={f.section + f.code}><strong>{f.section.replaceAll("_", " ")}:</strong> {f.message}</li>
                ))}
              </ul>
            ) : (
              <p>No investigation flags were raised.</p>
            )}
          </section>

          <section aria-labelledby="inputs">
            <h2 id="inputs">1. Inputs <Chip status={r.sections.inputs.status} /></h2>
            <p>{r.sections.inputs.recent_profiles} recent profiles compared with {r.sections.inputs.baseline_profiles} baseline profiles from the pinned training grid.</p>
            {r.sections.inputs.reason ? <p className="notice">{String(r.sections.inputs.reason).replaceAll("_", " ")}.</p> : null}
            <div className="table-scroll" role="region" aria-label="Input drift" tabIndex={0}>
              <table>
                <caption>Distribution shift against the training baseline (population stability index)</caption>
                <thead><tr><th>Measure</th><th>PSI</th><th>Reading</th></tr></thead>
                <tbody>
                  {Object.entries(r.sections.inputs.distribution_drift).map(([k, d]) => (
                    <tr key={k}><td>{k.replaceAll("_", " ")}{d.note ? <small>{d.note}</small> : null}</td><td>{num(d.psi, 2)}</td><td><Chip status={d.status} /></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>
              Spatial coverage: {r.sections.inputs.spatial_coverage.recent_profiles_in_cells_without_training_profiles} recent profiles ({pct(r.sections.inputs.spatial_coverage.novel_cell_share)}) lie in {r.sections.inputs.spatial_coverage.cell_degrees}° cells with no training profile.
            </p>
            <p>
              Expected-mean availability: {r.sections.inputs.feature_availability.cells_without_expected_mean} of {r.sections.inputs.feature_availability.profile_depth_variable_cells} profile-depth cells have none ({pct(r.sections.inputs.feature_availability.missing_rate)}). {r.sections.inputs.feature_availability.interpretation}
            </p>
            {Object.keys(r.sections.inputs.feature_availability.reasons).length ? (
              <ul>{Object.entries(r.sections.inputs.feature_availability.reasons).map(([k, v]) => <li key={k}>{k.replaceAll("_", " ")}: {v}</li>)}</ul>
            ) : null}
          </section>

          <section aria-labelledby="outcomes">
            <h2 id="outcomes">2. Expected values against outcomes <Chip status={r.sections.expected_state_outcomes.status} /></h2>
            <p>{r.sections.expected_state_outcomes.reason}</p>
            <p>{r.sections.expected_state_outcomes.label_policy} Trusted profiles: {r.sections.expected_state_outcomes.trusted_profiles}.</p>
            <div className="table-scroll" role="region" aria-label="Outcome errors" tabIndex={0}>
              <table>
                <caption>Profile-weighted absolute error and bias against observed values</caption>
                <thead><tr><th>Variable</th><th>Label status</th><th>Method</th><th>Profiles</th><th>MAE</th><th>Bias</th></tr></thead>
                <tbody>
                  {Object.entries(r.sections.expected_state_outcomes.variables).flatMap(([v, groups]) =>
                    Object.entries(groups).flatMap(([g, methods]) =>
                      Object.entries(methods).map(([m, s]) => (
                        <tr key={v + g + m}><td>{names[v]}</td><td>{g === "trusted" ? "Trusted (delayed-mode)" : "Unverified (real-time)"}</td><td>{m.replaceAll("_", " ")}</td><td>{s.profiles}</td><td>{num(s.profile_weighted_mae)}</td><td>{num(s.profile_weighted_bias)}</td></tr>
                      )),
                    ),
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section aria-labelledby="detector">
            <h2 id="detector">3. Profile ranking <Chip status={r.sections.profile_detector.status} /></h2>
            <p>{r.sections.profile_detector.note}</p>
            {Object.entries(r.sections.profile_detector.variables).map(([v, d]) => (
              <div key={v}>
                <h3>{names[v]} <Chip status={d.status} /></h3>
                <p>{d.scored_profiles} scored profiles{d.regional_fallback_share != null ? `; ${pct(d.regional_fallback_share)} use the global fallback group` : ""}{d.reference_resolution_share != null ? `; the reference can only resolve ranks to about ${(d.reference_resolution_share * 100).toFixed(1)} percentage points` : ""}.{d.reason ? ` ${d.reason.replaceAll("_", " ")}.` : ""}</p>
                <div className="table-scroll" role="region" aria-label={`${names[v]} rank shares`} tabIndex={0}>
                  <table>
                    <thead><tr><th>Rank at or above</th><th>Profiles</th><th>Share</th><th>Share if nothing changed</th><th>Chance of this many or more</th></tr></thead>
                    <tbody>
                      {Object.entries(d.tail_shares).map(([k, t]) => (
                        <tr key={k}><td>{t.percentile_at_least}th percentile</td><td>{t.profiles}</td><td>{pct(t.share, 1)}</td><td>{pct(t.reference_share, 1)}</td><td>{!t.resolvable_with_reference ? "Not testable: the reference is too small to resolve this band" : t.p_value_excess == null ? "Too few profiles" : t.p_value_excess.toPrecision(2)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </section>

          <section aria-labelledby="calibration">
            <h2 id="calibration">4. Interval calibration <Chip status={r.sections.calibration.status} /></h2>
            {r.sections.calibration.reason ? <p>{String(r.sections.calibration.reason)}</p> : null}
            {r.sections.calibration.coverage_monitor ? (
              <p>
                Fixed-reference coverage monitor, {r.sections.calibration.coverage_monitor.checked_at.slice(0, 10)}: {r.sections.calibration.coverage_monitor.trusted_profiles} trusted of {r.sections.calibration.coverage_monitor.candidate_profiles} candidate profiles; nominal coverage {pct(r.sections.calibration.coverage_monitor.nominal_coverage)}.
              </p>
            ) : null}
            {r.sections.calibration.recent_interval_usage ? (
              <div className="table-scroll" role="region" aria-label="Interval usage" tabIndex={0}>
                <table>
                  <thead><tr><th>Variable</th><th>Interval cells</th><th>Using a fallback group</th><th>Median width</th></tr></thead>
                  <tbody>
                    {Object.entries(r.sections.calibration.recent_interval_usage).map(([v, u]) => (
                      <tr key={v}><td>{names[v]}</td><td>{u.interval_cells}</td><td>{pct(u.fallback_group_share)}</td><td>{num(u.median_width, 2)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>

          <details>
            <summary>Thresholds and evidence</summary>
            <p>{r.policy.threshold_note} Thresholds reviewed: {r.policy.thresholds_reviewed ? "yes" : "no"}.</p>
            <p>Calculation <Link href={`/calculations/${latest.calculation_id}`}>{latest.calculation_id}</Link> · report SHA-256 <span className="digest">{latest.report_sha256}</span></p>
            <p>Pinned releases: <Link href={`/models/${r.pins.expected_id}`}>expected</Link> · <Link href={`/uncertainty/${r.pins.uncertainty_id}`}>interval</Link> · <Link href={`/anomalies/${r.pins.anomaly_id}`}>profile ranking</Link></p>
          </details>
          {data.history.length > 1 ? (
            <section>
              <h2>Earlier reports</h2>
              <ul>{data.history.map((h) => <li key={h.report_id}>{h.checked_at.slice(0, 16).replace("T", " ")} UTC · <Chip status={h.status} /></li>)}</ul>
            </section>
          ) : null}
        </>
      )}
      <p><Link href="/models">← Back to models</Link></p>
    </main>
  );
}
