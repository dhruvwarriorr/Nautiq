import Link from "next/link";
import { evidence } from "../../lib/science";
import { apiURL } from "../../lib/profiles";
import type { ProductPolicy } from "../../lib/product";
import type { AnswerResponse } from "../../lib/ask-types";
import { toReading, when, type Reading } from "../../lib/humanize";
import { PageHead, Empty } from "../components/ui/Bits";
import Icon from "../components/ui/Icon";
import { Signal } from "../components/ui/Signal";
export const metadata = { title: "Places · Nautiq" };
export const dynamic = "force-dynamic";

async function answer(slug: string): Promise<AnswerResponse | null> {
  try {
    const r = await fetch(`${apiURL}/api/v1/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frame: { intent: "conditions", place: slug, when: "now" }, time_zone: "Asia/Kolkata" }),
      cache: "no-store",
      signal: AbortSignal.timeout(9000),
    });
    return r.ok ? ((await r.json()) as AnswerResponse) : null;
  } catch {
    return null;
  }
}

function Cell({ r }: { r?: Reading }) {
  if (!r || !r.value)
    return (
      <span title={r?.note}>
        <Signal status="unavailable" size={14} />
      </span>
    );
  return (
    <span className="board-value">
      <b>{r.value}</b>
      <span>{r.descriptor}</span>
    </span>
  );
}

export default async function Locations() {
  const value = await evidence<ProductPolicy>("/product-policy");
  const places = value?.policy.locations ?? [];
  const answers = await Promise.all(places.map((p) => answer(p.slug)));
  return (
    <main>
      <PageHead icon="buoy" title="Conditions" lede="Pick a place to see the sea right now: waves, wind, currents and official warnings." />
      {places.length ? (
        <section className="board" aria-label="Places">
          <div className="board-head" aria-hidden="true">
            <span>Place</span>
            <span>Waves</span>
            <span>Wind</span>
            <span>Warnings</span>
            <span />
          </div>
          <ul>
            {places.map((p, i) => {
              const facts = answers[i]?.answer?.facts ?? [];
              const rs = facts.map((f) => toReading(f));
              const pick = (m: Reading["measure"]) => rs.find((r) => r.measure === m);
              const w = pick("warnings");
              return (
                <li key={p.slug}>
                  <Link href={`/locations/${p.slug}`} className="board-row">
                    <span className="board-place">
                      <Icon name="buoy" size={26} />
                      <span>
                        <b>{p.name}</b>
                        <span>{/Offshore$/.test(p.name) ? "Offshore point" : "Open sea"}</span>
                      </span>
                    </span>
                    <span data-label="Waves"><Cell r={pick("waves")} /></span>
                    <span data-label="Wind"><Cell r={pick("wind")} /></span>
                    <span data-label="Warnings">
                      {w ? <Signal status={w.status}>{w.status === "unknown" ? "Unknown" : undefined}</Signal> : <Signal status="unavailable" />}
                    </span>
                    <Icon name="arrow" size={22} className="icon board-arrow" />
                  </Link>
                </li>
              );
            })}
          </ul>
          <p className="footnote board-foot">
            Forecast readings at each place&apos;s offshore point{answers[0]?.answer ? `, checked ${when(answers[0].answer.as_of)}` : ""}. Warnings shown as
            unknown are never an all-clear.
          </p>
        </section>
      ) : (
        <Empty title="Places are unavailable" icon="buoy">
          <p>The place list couldn’t be loaded. Try again in a moment.</p>
        </Empty>
      )}
    </main>
  );
}
