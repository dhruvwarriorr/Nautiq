import Link from "next/link";
import Chart from "../../components/ProfileChart";
import Climatology from "./Climatology";
import ExpectedState from "./ExpectedState";
import Uncertainty from "./Uncertainty";
import Anomaly from "./Anomaly";
import type { AnomalyProfile } from "../../../lib/anomaly";
import type { IntervalProfile } from "../../../lib/uncertainty";
import type { ExpectedProfile } from "../../../lib/expected";
import type { ProfileClimatology } from "../../../lib/climatology";
import { notFound } from "next/navigation";
import { evidence, type Revision, type Statistics } from "../../../lib/science";
import { apiURL, type Profile } from "../../../lib/profiles";
export const dynamic = "force-dynamic";
export default async function Detail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const climatologyRequest = evidence<ProfileClimatology>(
    `/profiles/${encodeURIComponent(id)}/climatology`,
  );
  const revisionRequest = evidence<{ items: Revision[] }>(
    `/profiles/${encodeURIComponent(id)}/revisions?limit=50`,
  );
  const statsRequest = evidence<Statistics>(
    `/profiles/${encodeURIComponent(id)}/statistics`,
  );
  const expectedRequest = evidence<ExpectedProfile>(
    `/profiles/${encodeURIComponent(id)}/expected-state`,
  );
  const uncertaintyRequest = evidence<IntervalProfile>(`/profiles/${encodeURIComponent(id)}/uncertainty`);
  const anomalyRequest = evidence<AnomalyProfile>(`/profiles/${encodeURIComponent(id)}/anomaly`);
  let profile: Profile | null = null;
  let absent = false;
  try {
    const response = await fetch(
      `${apiURL}/api/v1/profiles/${encodeURIComponent(id)}`,
      { cache: "no-store", signal: AbortSignal.timeout(9000) },
    );
    if (response.status === 404) absent = true;
    else if (response.ok) profile = await response.json();
  } catch {}
  if (absent) notFound();
  if (!profile)
    return (
      <main>
        <Link href="/profiles">← Profiles</Link>
        <h1>Profile unavailable.</h1>
        <p>The observation service is unavailable. Refresh to retry.</p>
      </main>
    );
  const [history, stats, climatology, expected, uncertainty, anomaly] = await Promise.all([
    revisionRequest,
    statsRequest,
    climatologyRequest,
    expectedRequest,
    uncertaintyRequest,
    anomalyRequest,
  ]);
  const p = profile,
    pr = p.provenance;
  return (
    <main className="explorer">
      <nav>
        <Link href="/profiles">← Argo profiles</Link>
        <Link href="/status">Platform health</Link>
      </nav>
      <p className="eyebrow">
        ARGO {p.platform_id} / CYCLE {pr.cycle_number}
      </p>
      <h1>The observed profile.</h1>
      <p className="intro">
        {p.latitude.toFixed(4)}° latitude · {p.longitude.toFixed(4)}° longitude
        <br />
        Observed {p.observed_at} · {pr.sampling_scheme}
      </p>
      <div className="summary">
        <span>
          Mode {p.data_mode} · {p.levels.length} accepted pressure levels
        </span>
        <span>Original levels · no interpolation</span>
      </div>
      <div className="charts">
        <Chart
          levels={p.levels}
          variable="temperature_c"
          label="Temperature"
          unit="°C"
        />
        <Chart
          levels={p.levels}
          variable="practical_salinity"
          label="Practical salinity"
          unit="PSS-78"
        />
      </div>
      <p className="footnote">
        Points are original accepted measurements. Connecting lines are visual
        guides and break at missing values or depth gaps over 250 m. Depth is
        converted from pressure using TEOS-10.
      </p>
      <section className="evidence">
        <h2>Source, QC and provenance</h2>
        <dl>
          <dt>Calculation evidence</dt>
          <dd>
            {pr.calculation_id ? (
              <Link href={`/calculations/${pr.calculation_id}`}>
                {pr.calculation_id}
              </Link>
            ) : (
              "Pending evidence backfill"
            )}
          </dd>
          <dt>Source</dt>
          <dd>
            {p.source_id} · {pr.attribution}
          </dd>
          <dt>Observed / received</dt>
          <dd>
            {p.observed_at} / {p.received_at}
          </dd>
          <dt>Provider update</dt>
          <dd>{pr.source_updated_at}</dd>
          <dt>QC policy</dt>
          <dd>
            {p.qc_version} · only source QC 1 is displayed; values for each
            variable can remain missing
          </dd>
          <dt>Parameter modes</dt>
          <dd>
            {Object.entries(pr.parameter_modes)
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ")}
          </dd>
          <dt>Methods</dt>
          <dd>
            {pr.normalizer_version} / {pr.depth_conversion_version}
          </dd>
          <dt>Canonical revision SHA-256</dt>
          <dd className="digest">{p.revision_sha256}</dd>
          <dt>Raw file SHA-256</dt>
          <dd className="digest">{pr.raw_sha256}</dd>
          <dt>Parquet SHA-256</dt>
          <dd className="digest">{pr.parquet_sha256}</dd>
          <dt>Immutable lake object</dt>
          <dd className="digest">{pr.parquet_key}</dd>
        </dl>
        <div className="evidence-links">
          <a
            className="button"
            href={`/profiles/${p.id}/raw?revision_sha256=${p.revision_sha256}`}
          >
            Download exact raw NetCDF ↓
          </a>
          <a href={pr.source_url} target="_blank" rel="noreferrer">
            Original GDAC file ↗
          </a>
        </div>
        <p className="footnote">
          The downloaded local artifact is pinned to this revision. The upstream
          file may later change. Neither the profile nor QC acceptance
          establishes current local sea conditions or a trip verdict.
        </p>
      </section>
      <Climatology value={climatology} revision={p.revision_sha256} />
      <ExpectedState value={expected} revision={p.revision_sha256} />
      <Uncertainty value={uncertainty} revision={p.revision_sha256} />
      <Anomaly value={anomaly} revision={p.revision_sha256} />
      <section>
        <h2>Descriptive profile summary</h2>
        {stats?.status === "ready" &&
        stats.revision_sha256 === p.revision_sha256 &&
        stats.calculation_id ? (
          <>
            <Link href={`/calculations/${stats.calculation_id}`}>
              Summary calculation evidence
            </Link>
            <pre className="audit-json">
              {JSON.stringify(stats.statistics, null, 2)}
            </pre>
          </>
        ) : (
          <p>
            {!stats
              ? "Summary evidence is unavailable. Refresh to retry."
              : stats.revision_sha256 !== p.revision_sha256
                ? "The profile changed while loading. Refresh for matching summary evidence."
                : "Summary recomputation is pending."}
          </p>
        )}
      </section>
      {history ? (
        <details>
          <summary>Retained revisions ({history.items.length})</summary>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Mode / state</th>
                  <th>Provider update</th>
                  <th>Evidence</th>
                  <th>Raw file</th>
                </tr>
              </thead>
              <tbody>
                {history.items.map((r) => (
                  <tr key={r.revision_sha256}>
                    <td>
                      {r.data_mode} / {r.selection_state}
                    </td>
                    <td>{r.source_updated_at}</td>
                    <td>
                      {r.calculation_id ? (
                        <Link href={`/calculations/${r.calculation_id}`}>
                          {r.calculation_id}
                        </Link>
                      ) : (
                        "Pending"
                      )}
                    </td>
                    <td>
                      <a
                        href={`/profiles/${p.id}/raw?revision_sha256=${r.revision_sha256}`}
                      >
                        Pinned NetCDF
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
      <details>
        <summary>Original levels and QC flags</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Depth (m)</th>
                <th>Pressure (dbar)</th>
                <th>Temperature (°C)</th>
                <th>Salinity (PSS-78)</th>
                <th>QC / missing reasons</th>
              </tr>
            </thead>
            <tbody>
              {p.levels.map((level, i) => (
                <tr key={i}>
                  <td>{level.depth_m.toFixed(2)}</td>
                  <td>{level.pressure_dbar.toFixed(2)}</td>
                  <td>{level.temperature_c ?? "Missing"}</td>
                  <td>{level.practical_salinity ?? "Missing"}</td>
                  <td>
                    {JSON.stringify(level.qc_flags)}{" "}
                    {JSON.stringify(level.missing_reasons)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </main>
  );
}
