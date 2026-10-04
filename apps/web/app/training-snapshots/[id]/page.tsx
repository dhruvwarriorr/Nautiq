import { evidence, type Snapshot } from "../../../lib/science";
import { PageHead } from "../../components/ui/Bits";
export const dynamic = "force-dynamic";
export default async function SnapshotPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const value = await evidence<Snapshot>(
    `/training-snapshots/${encodeURIComponent(id)}`,
  );
  if (!value)
    return (
      <main><PageHead back={{ href: "/data", label: "Data quality" }} title="Snapshot unavailable" lede={"The snapshot is absent or its evidence service is unavailable."} /></main>
    );
  return (
    <main>
      <PageHead back={{ href: "/data", label: "Datasets and quality" }} title={"Training snapshot"} lede={<>{value.profile_count} delayed-mode profiles · {value.row_count} original
        levels. Upstream revisions create new evidence; this snapshot retains
        its original input versions.</>} />
      <dl className="evidence">
        <dt>Snapshot ID</dt>
        <dd className="digest">{value.snapshot_id}</dd>
        <dt>As of (UTC)</dt>
        <dd>{value.manifest.evaluation_time}</dd>
        <dt>Parquet SHA-256</dt>
        <dd className="digest">{value.parquet_sha256}</dd>
        <dt>Manifest SHA-256</dt>
        <dd className="digest">{value.manifest_sha256}</dd>
        <dt>Scientific release</dt>
        <dd>Not approved · frozen input data only</dd>
      </dl>
      <a
        className="button"
        href={`/training-snapshots/${value.snapshot_id}/parquet`}
      >
        Download verified Parquet ↓
      </a>
      <section>
        <h2>Counts, splits and coverage</h2>
        <pre className="audit-json">
          {JSON.stringify(value.manifest.output, null, 2)}
        </pre>
      </section>
      <details>
        <summary>Training policy</summary>
        <pre className="audit-json">
          {JSON.stringify(value.manifest.policy, null, 2)}
        </pre>
      </details>
    </main>
  );
}
