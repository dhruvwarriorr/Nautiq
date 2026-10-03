import { evidence } from "../../lib/science";
import type { ProductPolicy, Conditions } from "../../lib/product";
import { ConditionSummary } from "../components/LocationView";
export const dynamic = "force-dynamic";
export default async function Compare({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const [params, policy] = await Promise.all([
    searchParams,
    evidence<ProductPolicy>("/product-policy"),
  ]);
  if (!policy)
    return (
      <main>
        <h1>Comparison catalog unavailable.</h1>
      </main>
    );
  const places = policy.policy.locations;
  const left = places.find((p) => p.slug === params.left) ?? places[0],
    right = places.find((p) => p.slug === params.right) ?? places[1];
  const time = params.time ?? policy.as_of;
  const [a, b] = await Promise.all(
    [left, right].map((p) =>
      evidence<Conditions>(
        `/conditions/point?${new URLSearchParams({ latitude: String(p.latitude), longitude: String(p.longitude), time })}`,
      ),
    ),
  );
  return (
    <main className="explorer">
      <p className="eyebrow">COMPARISON / COMMON TIME AND UNITS</p>
      <h1>Compare the source evidence.</h1>
      <form className="filters">
        <label>
          Location A
          <select name="left" defaultValue={left.slug}>
            {places.map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Location B
          <select name="right" defaultValue={right.slug}>
            {places.map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Common UTC time
          <input name="time" required defaultValue={time} />
        </label>
        <button className="button">Compare evidence</button>
      </form>
      <p>
        Both locations request the same UTC time. Compare only matching
        variables, units, source cycles and support. Different instrument dates
        and coverage remain visible; no difference is inferred where either
        value is missing.
      </p>
      <div className="comparison-grid">
        {[a, b].map((value, i) => (
          <section key={i}>
            <h2>{i === 0 ? left.name : right.name}</h2>
            {value ? (
              <ConditionSummary value={value} />
            ) : (
              <p className="notice">
                Evidence unavailable for this location; no numeric comparison
                can be made.
              </p>
            )}
          </section>
        ))}
      </div>
    </main>
  );
}
