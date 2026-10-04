import { evidence } from "../../lib/science";
import { apiURL } from "../../lib/profiles";
import type { ProductPolicy, Conditions } from "../../lib/product";
import type { AnswerResponse } from "../../lib/ask-types";
import { ConditionSummary } from "../components/LocationView";
import { headline } from "../../lib/humanize";
import { PageHead, TechDetail, Notice } from "../components/ui/Bits";
import { ReadingsBoard, WarningVerdict } from "../components/Readings";
import Icon from "../components/ui/Icon";
export const dynamic = "force-dynamic";
export const metadata = { title: "Compare places · Nautiq" };
const whens: [string, string][] = [
  ["now", "Right now"],
  ["tomorrow_morning", "Tomorrow morning"],
  ["tomorrow_afternoon", "Tomorrow afternoon"],
  ["tonight", "Tonight"],
];
async function answer(slug: string, when: string): Promise<AnswerResponse | null> {
  try {
    const r = await fetch(`${apiURL}/api/v1/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frame: { intent: "conditions", place: slug, when }, time_zone: "Asia/Kolkata" }),
      cache: "no-store",
      signal: AbortSignal.timeout(9000),
    });
    return r.ok ? ((await r.json()) as AnswerResponse) : null;
  } catch {
    return null;
  }
}
export default async function Compare({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const [params, policy] = await Promise.all([searchParams, evidence<ProductPolicy>("/product-policy")]);
  if (!policy)
    return (
      <main>
        <PageHead title="Compare places" lede="The place list is unavailable right now. Try again shortly." />
      </main>
    );
  const places = policy.policy.locations;
  const left = places.find((p) => p.slug === params.left) ?? places[0],
    right = places.find((p) => p.slug === params.right) ?? places[1];
  const when = whens.some(([k]) => k === params.when) ? params.when! : "now";
  const [a, b, ca, cb] = await Promise.all([
    answer(left.slug, when),
    answer(right.slug, when),
    evidence<Conditions>(`/conditions/point?${new URLSearchParams({ latitude: String(left.latitude), longitude: String(left.longitude), time: policy.as_of })}`),
    evidence<Conditions>(`/conditions/point?${new URLSearchParams({ latitude: String(right.latitude), longitude: String(right.longitude), time: policy.as_of })}`),
  ]);
  return (
    <main>
      <PageHead icon="compass" title="Compare places" lede="Two places side by side, at the same time. Where either reading is missing, no difference is drawn." />
      <form className="check-form compare-form">
        <label>
          First place
          <select name="left" defaultValue={left.slug}>
            {places.map((p) => (
              <option key={p.slug} value={p.slug}>{p.name}</option>
            ))}
          </select>
        </label>
        <label>
          Second place
          <select name="right" defaultValue={right.slug}>
            {places.map((p) => (
              <option key={p.slug} value={p.slug}>{p.name}</option>
            ))}
          </select>
        </label>
        <label>
          When
          <select name="when" defaultValue={when}>
            {whens.map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
        <button className="btn"><Icon name="compass" size={18} /> Compare</button>
      </form>
      <div className="compare-grid">
        {[
          [left, a],
          [right, b],
        ].map(([p, r], i) => {
          const place = p as typeof left;
          const res = r as AnswerResponse | null;
          return (
            <section key={i}>
              <h2>{place.name}</h2>
              {res?.answer ? (
                <>
                  <p className="muted">{headline(res.answer.headline)}</p>
                  <WarningVerdict facts={res.answer.facts} />
                  <div style={{ marginTop: 14 }}>
                    <ReadingsBoard facts={res.answer.facts} />
                  </div>
                </>
              ) : (
                <Notice tone="caution" title="No readings for this place">
                  <p>Nothing can be compared while this side is missing.</p>
                </Notice>
              )}
            </section>
          );
        })}
      </div>
      <TechDetail summary="Point evidence for both places">
        <div className="compare-grid">
          {[ca, cb].map((value, i) => (
            <section key={i}>
              <h3>{i === 0 ? left.name : right.name}</h3>
              {value ? <ConditionSummary value={value} /> : <p className="muted">Evidence unavailable.</p>}
            </section>
          ))}
        </div>
      </TechDetail>
    </main>
  );
}
