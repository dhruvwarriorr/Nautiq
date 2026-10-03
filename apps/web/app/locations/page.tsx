import Link from "next/link";
import { evidence } from "../../lib/science";
import type { ProductPolicy } from "../../lib/product";
export const dynamic = "force-dynamic";
export default async function Locations() {
  const value = await evidence<ProductPolicy>("/product-policy");
  return (
    <main className="explorer">
      <p className="eyebrow">LOCATIONS / OBSERVATIONS AND FORECASTS</p>
      <h1>Choose a place to explore.</h1>
      <p className="intro">
        Inspect forecasts at a requested point and nearby observations at their
        actual instrument positions. Each page separates retained data from
        current availability.
      </p>
      <div className="place-grid">
        {value?.policy.locations.map((p) => (
          <article key={p.slug}>
            <h2>
              <Link href={`/locations/${p.slug}`}>{p.name}</Link>
            </h2>
            <p>
              {p.latitude.toFixed(2)}° latitude · {p.longitude.toFixed(2)}°
              longitude
            </p>
            <Link href={`/regions/${p.slug}`}>
              Explore the surrounding region →
            </Link>
          </article>
        ))}
      </div>
      {!value ? (
        <p className="notice">
          Location catalog unavailable. Retry when the evidence service
          recovers.
        </p>
      ) : null}
    </main>
  );
}
