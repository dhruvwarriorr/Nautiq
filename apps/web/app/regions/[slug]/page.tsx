import Link from "next/link";
import { notFound } from "next/navigation";
import { evidence } from "../../../lib/science";
import type { ProductPolicy } from "../../../lib/product";
export const dynamic = "force-dynamic";
export default async function Region({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const policy = await evidence<ProductPolicy>("/product-policy");
  if (!policy)
    return (
      <main>
        <h1>Region catalog unavailable.</h1>
      </main>
    );
  const place = policy.policy.locations.find((p) => p.slug === slug);
  if (!place) notFound();
  const bbox = place.bbox.join(",");
  return (
    <main className="explorer">
      <p className="eyebrow">REGION / COVERAGE AND COMPARISON</p>
      <h1>{place.name}</h1>
      <p className="intro">
        Explore this region’s recorded observations and retained fields. A
        center-point sample is separate from a regional spatial average.
      </p>
      <div className="place-grid">
        <article>
          <h2>Observed water column</h2>
          <Link href={`/research?place=${place.slug}`}>
            Query profiles by date, depth, QC and variable →
          </Link>
        </article>
        <article>
          <h2>Spatial evidence</h2>
          <Link href={`/map?bbox=${encodeURIComponent(bbox)}`}>
            Open native fields and evidence layers →
          </Link>
        </article>
        <article>
          <h2>Requested center point</h2>
          <Link href={`/locations/${place.slug}`}>
            View point forecasts and nearby instruments →
          </Link>
        </article>
        <article>
          <h2>Compare places</h2>
          <Link href={`/compare?left=${place.slug}`}>
            Align time, units and source cycles →
          </Link>
        </article>
      </div>
      <p>
        Bounding box: {bbox}. Query results retain instrument positions and
        source times; sparse observations are not interpolated into a regional
        surface.
      </p>
    </main>
  );
}
