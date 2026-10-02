import Link from "next/link";
import { evidence, type Calculation } from "../../../lib/science";
export const dynamic = "force-dynamic";
export default async function CalculationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const value = await evidence<Calculation>(
    `/calculations/${encodeURIComponent(id)}`,
  );
  if (!value)
    return (
      <main>
        <Link href="/data">← Data quality</Link>
        <h1>Evidence unavailable.</h1>
        <p>The calculation is absent or its evidence service is unavailable.</p>
      </main>
    );
  const m = value.manifest;
  return (
    <main className="explorer">
      <nav>
        <Link href="/data">← Data quality</Link>
        <Link href="/profiles">Argo profiles</Link>
      </nav>
      <p className="eyebrow">CALCULATION / DURABLE EVIDENCE</p>
      <h1>Reproduce the result.</h1>
      <dl className="evidence">
        <dt>Calculation ID</dt>
        <dd className="digest">{value.calculation_id}</dd>
        <dt>Method</dt>
        <dd>{m.method_version}</dd>
        <dt>State</dt>
        <dd>{value.state}</dd>
        <dt>Evaluation time (UTC)</dt>
        <dd>{m.evaluation_time}</dd>
        <dt>Calculated (UTC)</dt>
        <dd>{value.created_at}</dd>
        <dt>Manifest SHA-256</dt>
        <dd className="digest">{value.manifest_sha256}</dd>
        <dt>Code SHA-256</dt>
        <dd className="digest">{m.code_sha256}</dd>
      </dl>
      <section>
        <h2>Pinned input revisions</h2>
        <p>
          Raw downloads use the recorded revision. The profile explorer may show
          a newer revision.
        </p>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Profile</th>
                <th>Revision / raw SHA-256</th>
                <th>Raw evidence</th>
              </tr>
            </thead>
            <tbody>
              {m.inputs.map((i) => (
                <tr key={i.profile_id + i.revision_sha256}>
                  <td>
                    <Link href={`/profiles/${i.profile_id}`}>
                      {i.profile_id}
                    </Link>
                  </td>
                  <td className="digest">
                    {i.revision_sha256}
                    <br />
                    {i.raw_sha256}
                  </td>
                  <td>
                    <a
                      href={`/profiles/${i.profile_id}/raw?revision_sha256=${i.revision_sha256}`}
                    >
                      Exact NetCDF
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section>
        <h2>Result</h2>
        <pre className="audit-json">{JSON.stringify(m.output, null, 2)}</pre>
      </section>
      <details>
        <summary>Policy and runtime versions</summary>
        <pre className="audit-json">
          {JSON.stringify(
            { policy: m.policy, environment: m.environment },
            null,
            2,
          )}
        </pre>
      </details>
    </main>
  );
}
