import { evidence } from "../../lib/science";
import type { ProductPolicy } from "../../lib/product";
import Ask from "./Ask";
export const dynamic = "force-dynamic";
export const metadata = {
  title: "Ask · Nautiq",
  description:
    "Ask about sea conditions, official warnings, observed profiles or how a result is calculated. Every answer comes from retained evidence.",
};
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ q?: string | string[] }>;
}) {
  const value = await evidence<ProductPolicy>("/product-policy");
  const q = (await searchParams).q;
  const initial = typeof q === "string" ? q.slice(0, 512) : "";
  return (
    <main className="explorer ask-page">
      <p className="eyebrow">ASK NAUTIQ</p>
      <h1>Ask about the sea.</h1>
      <p className="intro">
        Ask in your own words. Nautiq works out what you mean, shows you how it
        understood the question, and answers only from retained evidence, with
        every limit stated.
      </p>
      <Ask
        places={value?.policy.locations ?? []}
        languageModel={Boolean(
          (value as unknown as { language_model_parsing?: boolean })
            ?.language_model_parsing,
        )}
        initialQuestion={initial}
      />
    </main>
  );
}
