import Link from "next/link";
import { notFound } from "next/navigation";
import { evidence } from "../../../lib/science";
import type { Conditions, ProductPolicy } from "../../../lib/product";
import LocationView from "../../components/LocationView";
import ModelBrief from "../../components/ModelBrief";
import { apiURL } from "../../../lib/profiles";
import type { AnswerResponse } from "../../../lib/ask-types";
import { coords, headline, when } from "../../../lib/humanize";
import { PageHead, TechDetail, Notice } from "../../components/ui/Bits";
import Icon from "../../components/ui/Icon";
import { ReadingsBoard, WarningVerdict, QuietFacts, Limits } from "../../components/Readings";
import { Hoist, type HoistMark } from "../../components/ui/Signal";
import { toReading } from "../../../lib/humanize";
import type { Answer } from "../../../lib/ask-types";

function placeMarks(answer: Answer): HoistMark[] {
  const rs = answer.facts.map((f) => toReading(f));
  const w = rs.find((r) => r.measure === "warnings");
  const sea = rs.filter((r) => ["waves", "wind", "current", "sst"].includes(r.measure));
  const have = sea.filter((r) => r.value).length;
  const f = rs.find((r) => r.measure === "float");
  return [
    { key: "w", label: "Official warnings", status: w?.status ?? "unknown", word: w?.status === "warning" ? "Warning in force" : w?.status === "available" ? "None found" : "Unknown" },
    { key: "s", label: "Sea readings", status: have ? "available" : "unavailable", word: sea.length ? `${have} of ${sea.length} in` : "None" },
    { key: "f", label: "Nearest float", status: f?.status === "available" ? "available" : "unavailable", word: f?.status === "available" ? "Within 100 km" : "None nearby" },
  ];
}

async function summary(slug: string): Promise<AnswerResponse | null> {
  try {
    const response = await fetch(`${apiURL}/api/v1/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frame: { intent: "conditions", place: slug, when: "now" }, time_zone: "Asia/Kolkata" }),
      cache: "no-store",
      signal: AbortSignal.timeout(9000),
    });
    return response.ok ? ((await response.json()) as AnswerResponse) : null;
  } catch {
    return null;
  }
}
export const dynamic = "force-dynamic";
export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const name = slug.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  return { title: `${name} · Nautiq` };
}
export default async function Location({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const catalog = await evidence<ProductPolicy>("/product-policy");
  if (!catalog)
    return (
      <main>
        <PageHead title="Places are unavailable" lede="The place list couldn’t be loaded. Try again in a moment." back={{ href: "/", label: "Home" }} />
      </main>
    );
  const place = catalog.policy.locations.find((p) => p.slug === slug);
  if (!place) notFound();
  const q = new URLSearchParams({ latitude: String(place.latitude), longitude: String(place.longitude), time: catalog.as_of });
  const [value, plain] = await Promise.all([evidence<Conditions>(`/conditions/point?${q}`), summary(slug)]);
  const answer = plain?.answer;
  const tomorrow = `/ask?q=${encodeURIComponent(`How are the conditions near ${place.name} tomorrow morning?`)}`;
  return (
    <main>
      <PageHead
        back={{ href: "/locations", label: "All places" }}
        title={place.name}
        lede={answer ? headline(answer.headline) : "Live readings for this place are unavailable right now."}
      >
        {answer ? <Hoist row marks={placeMarks(answer)} /> : null}
        <div className="head-actions">
          <Link className="btn" href={tomorrow}>
            <Icon name="hailer" size={18} /> Ask about tomorrow
          </Link>
          <Link className="btn-ghost" href={`/trips?lat=${place.latitude}&lon=${place.longitude}&place=${place.slug}`}>
            <Icon name="voyage" size={18} /> Plan a trip from here
          </Link>
          <Link className="btn-ghost" href={`/map`}>
            <Icon name="chart" size={18} /> Open map
          </Link>
        </div>
      </PageHead>

      {answer ? (
        <>
          <WarningVerdict facts={answer.facts} />
          <div style={{ marginTop: 18 }}>
            <ReadingsBoard facts={answer.facts} />
          </div>
          <QuietFacts facts={answer.facts} />
          <Limits answer={answer} />
          <p className="answer-meta">
            Readings at {coords(place.latitude, place.longitude, 1)} · checked {when(answer.as_of)} · times in IST.
          </p>
        </>
      ) : (
        <Notice tone="caution" title="Readings are unavailable">
          <p>The answer service didn’t respond. Unavailable data doesn’t mean calm or normal conditions.</p>
        </Notice>
      )}

      <TechDetail summary="Full evidence for this place">
        <LocationView place={place} initial={value} asOf={catalog.as_of} />
        <ModelBrief compact />
      </TechDetail>
    </main>
  );
}
