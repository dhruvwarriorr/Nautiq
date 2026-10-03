import { notFound } from "next/navigation";
import { evidence } from "../../../lib/science";
import type { Conditions, ProductPolicy } from "../../../lib/product";
import LocationView from "../../components/LocationView";
export const dynamic = "force-dynamic";
export default async function Location({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const catalog = await evidence<ProductPolicy>("/product-policy");
  if (!catalog)
    return (
      <main>
        <h1>Location catalog unavailable.</h1>
        <p>Retry when the evidence service recovers.</p>
      </main>
    );
  const place = catalog.policy.locations.find((p) => p.slug === slug);
  if (!place) notFound();
  const q = new URLSearchParams({
    latitude: String(place.latitude),
    longitude: String(place.longitude),
    time: catalog.as_of,
  });
  const value = await evidence<Conditions>(`/conditions/point?${q}`);
  return (
    <main className="explorer">
      <p className="eyebrow">LOCATION / ACTUAL SUPPORT AND PROVENANCE</p>
      <h1>{place.name}</h1>
      <p className="intro">
        Forecasts at the chosen point, nearby instrument evidence and official
        advisory state. Expected profile values apply at an instrument’s
        recorded location and depth.
      </p>
      <LocationView place={place} initial={value} asOf={catalog.as_of} />
    </main>
  );
}
