import { notFound } from "next/navigation";
import { evidence } from "../../../lib/science";
import type { ProductPolicy } from "../../../lib/product";
import { coords } from "../../../lib/humanize";
import { PageHead, DoorLink } from "../../components/ui/Bits";
export const dynamic = "force-dynamic";
export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const name = slug.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  return { title: `${name} · Nautiq` };
}
export default async function Region({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const policy = await evidence<ProductPolicy>("/product-policy");
  if (!policy)
    return (
      <main>
        <PageHead title="Regions are unavailable" lede="Try again in a moment." back={{ href: "/locations", label: "Conditions" }} />
      </main>
    );
  const place = policy.policy.locations.find((p) => p.slug === slug);
  if (!place) notFound();
  const bbox = place.bbox.join(",");
  const [w, s, e, n] = place.bbox;
  return (
    <main>
      <PageHead
        back={{ href: `/locations/${place.slug}`, label: place.name }}
        title={`Around ${place.name}`}
        lede={`The wider area from ${coords(s, w, 0)} to ${coords(n, e, 0)}. Float readings stay at their own positions; nothing is smoothed into a surface.`}
      />
      <div className="door-list">
        <DoorLink href={`/locations/${place.slug}`} icon="buoy" title="Conditions at the point" text="Waves, wind, currents and sea temperature right now." />
        <DoorLink href={`/map?bbox=${encodeURIComponent(bbox)}`} icon="chart" title="This area on the map" text="Forecast layers, floats and official areas." />
        <DoorLink href={`/research?place=${place.slug}`} icon="float" title="Float readings here" text="Temperature and salinity by date and depth." />
        <DoorLink href={`/compare?left=${place.slug}`} icon="compass" title="Compare with another place" text="Side by side, same time." />
      </div>
    </main>
  );
}
