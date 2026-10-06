import { evidence } from "../../lib/science";
import type { ProductPolicy } from "../../lib/product";
import Ask from "./Ask";
import { PageHead } from "../components/ui/Bits";
export const dynamic = "force-dynamic";
export const metadata = {
  title: "Ask · Nautiq",
  description: "Ask about sea conditions, trips or floats in your own words. Every answer comes from stored evidence.",
};
export default async function Page({ searchParams }: { searchParams: Promise<{ q?: string | string[] }> }) {
  const value = await evidence<ProductPolicy>("/product-policy");
  const q = (await searchParams).q;
  const initial = typeof q === "string" ? q.slice(0, 512) : "";
  return (
    <main className="page-ask">
      <PageHead icon="hailer" title="Ask about the sea" lede="Ask in your own words. Nautiq shows how it understood you, and answers only from real evidence." compact />
      <Ask
        places={value?.policy.locations ?? []}
        languageModel={Boolean((value as unknown as { language_model_parsing?: boolean })?.language_model_parsing)}
        initialQuestion={initial}
      />
    </main>
  );
}
