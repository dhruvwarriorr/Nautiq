import Link from "next/link";
import { evidence } from "../../../../lib/science";
import type { EventDataset } from "../../../../lib/events";
import { PageHead } from "../../../components/ui/Bits";
export const dynamic = "force-dynamic";
export default async function Dataset({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const data = /^[a-f0-9-]{36}$/.test(id)
    ? await evidence<EventDataset>(`/event-datasets/${id}`)
    : null;
  if (!data?.manifest)
    return (
      <main><PageHead back={{ href: "/events", label: "Event evidence" }} title="Dataset evidence unavailable" /></main>
    );
  const m = data.manifest;
  return (
    <main>
      <PageHead back={{ href: "/events", label: "Regional events" }} title={<>Frozen {data.kind} dataset.</>} lede={<>{m.metadata.source.attribution}</>} />
      <p>
        {data.status} · shape {m.metadata.shape.join(" × ")} ·{" "}
        {m.arrays_bytes.toLocaleString("en")} compressed bytes.
      </p>
      <p>
        {m.metadata.baseline_years
          ? `Fixed years: ${m.metadata.baseline_years.join("–")}; ${m.metadata.supported_seasonal_cells} supported seasonal cells.`
          : `${m.metadata.dates?.length} UTC days: ${m.metadata.dates?.[0]} through ${m.metadata.dates?.at(-1)}. Missing cells: ${m.metadata.missing_cells}.`}
      </p>
      {data.parent_id ? (
        <p>
          <Link href={`/events/datasets/${data.parent_id}`}>
            Retained daily fitting inputs
          </Link>
        </p>
      ) : null}
      <dl className="field-metadata">
        <div>
          <dt>Dataset / manifest hash</dt>
          <dd className="digest">
            {data.dataset_id}
            <br />
            {data.manifest_sha256}
          </dd>
        </div>
        <div>
          <dt>Arrays / code hash</dt>
          <dd className="digest">
            {m.arrays_sha256}
            <br />
            {m.code_sha256}
          </dd>
        </div>
      </dl>
      <a href={m.metadata.source.documentation}>NOAA source documentation ↗</a>
      <h2>Retained provider requests</h2>
      {m.metadata.raw?.map((r) => (
        <p className="digest" key={r.sha256}>
          <a href={r.url}>Provider subset request ↗</a> ·{" "}
          {r.bytes.toLocaleString("en")} bytes
          <br />
          {r.sha256}
        </p>
      )) ?? <p>Fitting inputs are pinned by the parent dataset.</p>}
    </main>
  );
}
