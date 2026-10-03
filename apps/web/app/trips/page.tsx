import Link from "next/link";
import { evidence } from "../../lib/science";
import type { TripPolicy } from "../../lib/trips";
import { TripForm } from "./TripForm";
export const dynamic = "force-dynamic";
export default async function Trips() {
  const [policy, fields] = await Promise.all([
    evidence<TripPolicy>("/trip-policy"),
    evidence<{
      items: {
        release_id: string;
        product_id: string;
        cycle: string | null;
        selected: boolean;
        status: string;
        freshness: string;
      }[];
    }>("/fields?limit=200"),
  ]);
  return (
    <main className="explorer">
      <nav>
        <Link href="/">Nautiq</Link>
        <Link href="/fields">Forecast fields</Link>
        <Link href="/advisories">Official advisories</Link>
      </nav>
      <p className="eyebrow">TRIP EVIDENCE / TIMED ROUTE AND DECISION RULES</p>
      <h1>Inspect the evidence for the whole trip.</h1>
      <p className="intro">
        Supply timed outward and return legs, including stops. Review official
        warning state, retained forecast samples and every missing input in one
        reproducible calculation.
      </p>
      <p className="notice">
        Decision thresholds are awaiting domain review. Marine advisory
        completeness and forecast operational approval remain unverified.
        Current trips cannot receive a favorable assessment.
      </p>
      {policy ? (
        <TripForm policy={policy} releases={fields?.items ?? []} />
      ) : (
        <p>The decision policy is unavailable. The trip cannot be assessed.</p>
      )}
      <h2>What a calculation preserves</h2>
      <p>
        Source cycles and immutable release hashes, the exact route and sample
        positions, official advisory state, rule version, missing inputs and
        worst retained samples. A new request creates a new calculation; replay
        uses the original as-of time.
      </p>
      <p>
        Private evidence uses an access token held in this browser page&apos;s
        memory. Reloading clears that access. Authenticated saved trips and
        alerts are separate future capabilities.
      </p>
    </main>
  );
}
