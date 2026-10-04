import { notFound } from "next/navigation";
import { evidence } from "../../../lib/science";
import type { Conditions, ProductPolicy } from "../../../lib/product";
import LocationView from "../../components/LocationView";
import ModelBrief from "../../components/ModelBrief";
import { FactList } from "../../ask/Ask";
import { apiURL } from "../../../lib/profiles";
import type { AnswerResponse } from "../../../lib/ask-types";
async function summary(slug: string): Promise<AnswerResponse | null> {
  try {
    const response = await fetch(`${apiURL}/api/v1/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frame: { intent: "conditions", place: slug, when: "now" }, time_zone: "UTC" }),
      cache: "no-store",
      signal: AbortSignal.timeout(9000),
    });
    return response.ok ? ((await response.json()) as AnswerResponse) : null;
  } catch {
    return null;
  }
}
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
  const [value, plain] = await Promise.all([evidence<Conditions>(`/conditions/point?${q}`), summary(slug)]);
  return (
    <main className="explorer">
      <p className="eyebrow">LOCATION / ACTUAL SUPPORT AND PROVENANCE</p>
      <h1>{place.name}</h1>
      <p className="intro">
        Forecasts at the chosen point, nearby instrument evidence and official
        advisory state. Expected profile values apply at an instrument’s
        recorded location and depth.
      </p>
      {plain?.answer ? (
        <section className="plain-summary" aria-labelledby="plain-title">
          <h2 id="plain-title">{plain.answer.headline}</h2>
          <FactList answer={plain.answer} />
          <aside className="cannot">
            <h3>What this does not tell you</h3>
            <ul>{plain.answer.cannot_tell_you.map((c) => <li key={c}>{c}</li>)}</ul>
          </aside>
          <p className="answer-meta">Assembled from retained evidence with fixed templates. Want a different time? <a href={`/ask?q=${encodeURIComponent("How are the conditions near " + place.name + " tomorrow morning?")}`}>Ask about tomorrow morning</a>.</p>
        </section>
      ) : null}
      <h2>Full evidence</h2>
      <LocationView place={place} initial={value} asOf={catalog.as_of} />
      <ModelBrief compact />
    </main>
  );
}
