import Link from "next/link";
import {
  evidence,
  type Source,
  type Rejection,
  type SnapshotSummary,
} from "../../lib/science";
export const dynamic = "force-dynamic";
export default async function Data() {
  const [sources, rejections, snapshots] = await Promise.all([
    evidence<{ items: Source[] }>("/sources"),
    evidence<{ items: Rejection[] }>("/qc-rejections?limit=50"),
    evidence<{ items: SnapshotSummary[] }>("/training-snapshots?limit=50"),
  ]);
  return (
    <main className="explorer">
      <nav>
        <Link href="/">Nautiuq</Link>
        <Link href="/profiles">Argo profiles</Link>
        <Link href="/climatology">Historical normal</Link>
        <Link href="/models">Expected-state models</Link>
        <Link href="/status">Platform health</Link>
      </nav>
      <p className="eyebrow">DATA / QUALITY & REPRODUCIBILITY</p>
      <h1>Know the evidence.</h1>
      <p className="intro">
        Review source timing, rejected measurements and frozen training inputs.
        Runtime health and scientific release approval are separate.
      </p>
      <section>
        <h2>Source monitoring</h2>
        {sources ? (
          sources.items.map((s) => (
            <article className="evidence" key={s.source_id}>
              <h3>{s.metadata.provider}</h3>
              <dl>
                <dt>Provider freshness</dt>
                <dd>
                  {s.health?.source_freshness ?? "Unknown"} · expected cadence{" "}
                  {s.health?.expected_update_hours ?? "unverified"} hours ·{" "}
                  {s.health?.cadence_verified
                    ? "reviewed cadence"
                    : "cadence not verified"}
                </dd>
                <dt>Local ingestion</dt>
                <dd>
                  {s.health?.ingestion_state ?? "Unknown"} · last successful
                  live fetch {s.health?.last_successful_fetch ?? "Not recorded"}
                </dd>
                <dt>Observation time</dt>
                <dd>{s.health?.newest_observed_at ?? "Not recorded"}</dd>
                <dt>Coverage</dt>
                <dd>{s.health?.coverage_state ?? "Unverified"}</dd>
                <dt>Monitor</dt>
                <dd>
                  {s.monitor_state} · {s.monitor_checked_at ?? "Not checked"}
                </dd>
                <dt>Pending delivery</dt>
                <dd>{s.health?.pending_event_count ?? "Unknown"} events</dd>
                <dt>Attribution</dt>
                <dd>{s.metadata.attribution}</dd>
                <dt>Source terms</dt>
                <dd>
                  <a href={s.metadata.terms_url}>{s.metadata.license_state}</a>
                </dd>
                <dt>Production approval</dt>
                <dd>
                  {s.metadata.production_approved ? "Approved" : "Not approved"}
                </dd>
              </dl>
            </article>
          ))
        ) : (
          <p role="alert">Source monitoring is unavailable.</p>
        )}
      </section>
      <section>
        <h2>Frozen training snapshots</h2>
        <p>
          Original delayed-mode QC 1 labels with pinned inputs, split
          assignments and checksums. A stored snapshot does not approve a
          scientific model.
        </p>
        {snapshots ? (
          snapshots.items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Snapshot</th>
                    <th>Profiles / levels</th>
                    <th>State</th>
                    <th>Created (UTC)</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshots.items.map((s) => (
                    <tr key={s.snapshot_id}>
                      <td>
                        <Link href={`/training-snapshots/${s.snapshot_id}`}>
                          {s.snapshot_id}
                        </Link>
                      </td>
                      <td>
                        {s.profile_count} / {s.row_count}
                      </td>
                      <td>{s.status}</td>
                      <td>{s.created_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="notice">
              No frozen training snapshot has been built.
            </p>
          )
        ) : (
          <p role="alert">Snapshot evidence is unavailable.</p>
        )}
      </section>
      <section>
        <h2>QC rejection audit</h2>
        <p>
          Latest 50 audit groups. Variable groups retain counts and sampled
          native level indices; exact rejected values remain in the raw file.
        </p>
        {rejections ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Source / profile index</th>
                  <th>Variable / count</th>
                  <th>Reason</th>
                  <th>QC policy</th>
                  <th>Recorded (UTC)</th>
                </tr>
              </thead>
              <tbody>
                {rejections.items.map((r) => (
                  <tr key={r.rejection_id}>
                    <td>
                      {r.source_id} / {r.profile_index ?? "unknown"}
                      <details>
                        <summary>Artifact and rule</summary>
                        <p className="digest">
                          {r.artifact_id ?? "No registered artifact"}
                        </p>
                        <p>{r.rule_id}</p>
                        <pre>{JSON.stringify(r.context, null, 2)}</pre>
                      </details>
                    </td>
                    <td>
                      {r.variable ?? "Profile"} / {r.rejected_count}
                    </td>
                    <td>{r.reason_code.replaceAll("_", " ")}</td>
                    <td>{r.qc_version}</td>
                    <td>{r.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p role="alert">QC audit is unavailable.</p>
        )}
      </section>
    </main>
  );
}
