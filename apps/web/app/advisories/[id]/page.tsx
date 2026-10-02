import Link from "next/link";
import { evidence } from "../../../lib/science";
import type { Bulletin, AdvisorySource } from "../../../lib/advisories";
import { AdvisoryMap } from "../AdvisoryMap";
export const dynamic = "force-dynamic";
export default async function Advisory({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const result = await evidence<{
    bulletin: Bulletin;
    sources: AdvisorySource[];
  }>(`/advisories/${id}`);
  if (!result)
    return (
      <main className="explorer">
        <Link href="/advisories">Official advisories</Link>
        <h1>Bulletin evidence unavailable</h1>
        <p>
          A missing or unverifiable bulletin does not establish that an official
          warning was cancelled.
        </p>
      </main>
    );
  const b = result.bulletin;
  return (
    <main className="explorer">
      <nav>
        <Link href="/">Nautiq</Link>
        <Link href="/advisories">Official advisories</Link>
      </nav>
      <p className="eyebrow">RETAINED CAP / EXACT REVISION</p>
      <h1>
        {b.message.sender}: {b.message.infos[0]?.event ?? b.message.msgType}
      </h1>
      <p className="notice">
        {b.message.msgType} · {b.lifecycle.state} · {b.message.status} /{" "}
        {b.message.scope}. Source transport and complete marine coverage are
        separate. This archived message is not an all-clear for a trip.
      </p>
      <p>
        Issued {b.message.sent}. Identifier{" "}
        <span className="digest">{b.message.identifier}</span>.
      </p>
      <a href={b.source_url} target="_blank" rel="noreferrer">
        Original agency CAP document
      </a>
      <AdvisoryMap items={[b]} />
      {b.message.infos.map((info, i) => (
        <section key={i}>
          <h2>
            {info.headline || info.event} ({info.language})
          </h2>
          <p>
            {info.severity} · {info.urgency} · {info.certainty}
          </p>
          <p>
            Effective {info.effective}
            <br />
            Expected onset {info.onset ?? "not supplied"}
            <br />
            Expires {info.expires ?? "unknown; no expiry invented"}
          </p>
          <p style={{ whiteSpace: "pre-wrap" }}>{info.description}</p>
          {info.instruction && (
            <p style={{ whiteSpace: "pre-wrap" }}>{info.instruction}</p>
          )}
          {info.issues.length > 0 && (
            <p>Unresolved: {info.issues.join(", ")}</p>
          )}
          <h3>Original warning areas</h3>
          {info.areas.map((a, j) => (
            <section key={j}>
              <p>{a.description}</p>
              <p>
                {a.polygons.length} polygons · {a.circles.length} circles ·{" "}
                {a.unresolved.join(", ") || "geometry supplied"}
              </p>
              {a.circles.map((c, k) => (
                <p key={k}>
                  Geodesic circle: longitude {c.center[0]}, latitude{" "}
                  {c.center[1]}, radius {c.radius_km} km.
                </p>
              ))}
              {a.geocodes.map((g, k) => (
                <p key={k}>
                  {g.name}: {g.value} (no reviewed place mapping)
                </p>
              ))}
            </section>
          ))}
        </section>
      ))}
      <h2>Revision lineage</h2>
      <p>
        {b.lifecycle.issues.join(", ") || "No unresolved revision references"}
      </p>
      {b.message.references.map((r, i) => (
        <p className="digest" key={i}>
          {r.sender}, {r.identifier}, {r.sent}
        </p>
      ))}
      {b.lifecycle.replaced_by.map((r) => (
        <p key={r}>
          <Link href={`/advisories/${r}`}>Replacement / cancellation {r}</Link>
        </p>
      ))}
      <h2>Retained bytes</h2>
      <p className="digest">
        Revision {b.message.revision_id}
        <br />
        Raw SHA-256 {b.raw_sha256}
        <br />
        First retained feed run {b.first_run_id}
      </p>
    </main>
  );
}
