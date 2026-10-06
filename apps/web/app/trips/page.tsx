import { evidence } from "../../lib/science";
import type { TripPolicy } from "../../lib/trips";
import type { ProductPolicy } from "../../lib/product";
import { TripForm } from "./TripForm";
import { PageHead, Notice } from "../components/ui/Bits";
export const dynamic = "force-dynamic";
export const metadata = { title: "Plan a trip · Nautiq" };
function prefillFrom(q: Record<string, string | string[] | undefined>) {
  const one = (k: string) => (typeof q[k] === "string" ? (q[k] as string) : "");
  const lat = Number(one("lat"));
  const lon = Number(one("lon"));
  if (!one("lat") || !one("lon") || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 85 || Math.abs(lon) > 180) return undefined;
  const depart = one("depart");
  const time = Date.parse(depart);
  return {
    latitude: lat,
    longitude: lon,
    departure: Number.isFinite(time) ? new Date(time).toISOString() : undefined,
    place: /^[a-z-]{1,40}$/.test(one("place")) ? one("place") : "",
  };
}
export default async function Trips({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const prefill = prefillFrom(await searchParams);
  const [policy, fields, catalog] = await Promise.all([
    evidence<TripPolicy>("/trip-policy"),
    evidence<{ items: { release_id: string; product_id: string; cycle: string | null; selected: boolean; status: string; freshness: string }[] }>("/fields?limit=200"),
    evidence<ProductPolicy>("/product-policy"),
  ]);
  return (
    <main>
      <PageHead
        icon="voyage"
        title="Plan a trip"
        lede="Enter your stops and times, out and back. Nautiq checks every leg against the forecast, and lists what it couldn’t check."
      />
      <Notice tone="caution" title="Nautiq won’t call a trip safe">
        <p>It checks the forecast against wave, wind and current limits. The defaults suit small open boats; set your own in Advanced settings. Nautiq doesn’t read official warnings, so check INCOIS and IMD before you go.</p>
      </Notice>
      {prefill ? (
        <Notice title="We started your route for you">
          <p>
            The first stop{prefill.place ? ` (${prefill.place.replaceAll("-", " ")})` : ""} came from where you were. The other stops are placeholders: change them to your real route.
          </p>
        </Notice>
      ) : null}
      {policy ? (
        <TripForm policy={policy} releases={fields?.items ?? []} prefill={prefill} places={catalog?.policy.locations ?? []} />
      ) : (
        <Notice tone="caution" title="Trip checks are unavailable">
          <p>The rule service didn’t respond. Try again shortly.</p>
        </Notice>
      )}
    </main>
  );
}
