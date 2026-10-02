import Link from "next/link";
import { evidence } from "../../lib/science";
import type { AdvisorySnapshot, AdvisoryState } from "../../lib/advisories";
import { AdvisoryMap } from "./AdvisoryMap";
export const dynamic = "force-dynamic";
export default async function Advisories({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const keys = ["longitude", "latitude", "start", "end"];
  const supplied = keys.every((k) => typeof params[k] === "string");
  const q = new URLSearchParams();
  if (supplied) keys.forEach((k) => q.set(k, params[k] as string));
  const [snapshot, state] = await Promise.all([
    evidence<AdvisorySnapshot>("/advisories"),
    supplied
      ? evidence<AdvisoryState>(`/advisories/state?${q}`)
      : Promise.resolve(null),
  ]);
  return (
    <main className="explorer">
      <nav>
        <Link href="/">Nautiq</Link>
        <Link href="/fields">Forecast fields</Link>
        <Link href="/events">Scientific events</Link>
      </nav>
      <p className="eyebrow">OFFICIAL ADVISORIES / SOURCE EVIDENCE</p>
      <h1>Keep official warnings visible.</h1>
      <p className="intro">
        Inspect original CAP bulletins, issue and validity times, source
        freshness and explicit revisions. Official agency messages remain
        separate from Nautiq scientific diagnostics.
      </p>
      <p className="notice">
        Marine advisory coverage is unknown. A healthy download or an empty feed
        does not establish that no relevant warning exists. INCOIS machine
        access and marine completeness remain unverified.
      </p>
      <h2>Feed health</h2>
      {snapshot?.sources.length ? (
        <div className="evidence-grid">
          {snapshot.sources.map((s) => (
            <section key={s.source_id}>
              <h3>{s.policy.authority}</h3>
              <p>
                {s.transport} · coverage {s.coverage}
              </p>
              <p>
                Last checked: {s.checked_at ?? "never"}
                <br />
                Age:{" "}
                {s.age_seconds === null
                  ? "unknown"
                  : `${s.age_seconds} seconds`}{" "}
                · evidence {s.integrity}
              </p>
              {s.policy.url && (
                <a href={s.policy.url} target="_blank" rel="noreferrer">
                  Official source
                </a>
              )}
            </section>
          ))}
        </div>
      ) : (
        <p>Advisory evidence is unavailable. State remains unknown.</p>
      )}
      <h2>Inspect a location and time window</h2>
      <form method="get" className="field-controls">
        <label>
          Longitude
          <input
            name="longitude"
            required
            type="number"
            step="any"
            min="-180"
            max="180"
            defaultValue={
              typeof params.longitude === "string" ? params.longitude : "72"
            }
          />
        </label>
        <label>
          Latitude
          <input
            name="latitude"
            required
            type="number"
            step="any"
            min="-90"
            max="90"
            defaultValue={
              typeof params.latitude === "string" ? params.latitude : "12"
            }
          />
        </label>
        <label>
          Start (UTC, ISO 8601)
          <input
            name="start"
            required
            defaultValue={
              typeof params.start === "string"
                ? params.start
                : (snapshot?.as_of ?? "")
            }
          />
        </label>
        <label>
          End (UTC, ISO 8601)
          <input
            name="end"
            required
            defaultValue={
              typeof params.end === "string"
                ? params.end
                : (snapshot ? new Date(Date.parse(snapshot.as_of) + 6 * 3600000).toISOString() : "")
            }
          />
        </label>
        <button type="submit">Inspect official state</button>
      </form>
      {supplied && (
        <section aria-live="polite">
          <h3>
            {state?.status === "official_warning"
              ? "Relevant official warning"
              : state?.status === "known_none_intersecting"
                ? "No intersecting warning in verified coverage"
                : "Advisory state unknown"}
          </h3>
          {state ? (
            <>
              <p>
                {state.warnings.length} intersecting retained warnings.{" "}
                {state.unknown_reasons.length} unresolved coverage or bulletin
                conditions.
              </p>
              {state.warnings.map((w, i) => (
                <p key={`${w.revision_id}-${i}`}>
                  <Link href={`/advisories/${w.revision_id}`}>
                    {w.event} · {w.severity}
                  </Link>{" "}
                  · {w.effective} to {w.expires ?? "unknown expiry"}
                </p>
              ))}
              <details>
                <summary>Unknown conditions</summary>
                <ul>
                  {state.unknown_reasons.map((reason) => (
                    <li className="digest" key={reason}>
                      {reason}
                    </li>
                  ))}
                </ul>
              </details>
            </>
          ) : (
            <p>
              The query or evidence could not be verified. Check coordinates and
              an increasing window of at most 96 hours.
            </p>
          )}
        </section>
      )}
      <h2>Retained agency bulletins</h2>
      {snapshot && <AdvisoryMap items={snapshot.items} />}
      <p>
        Expired, test, cancelled and superseded messages stay in the archive.
        Missing geometry is explicit; an unmapped bulletin can still be
        relevant.
      </p>
      {snapshot?.items.length ? (
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Official bulletin evidence"
        >
          <table>
            <thead>
              <tr>
                <th>Issuer and event</th>
                <th>Issued (UTC)</th>
                <th>Message / lifecycle</th>
                <th>Geometry</th>
              </tr>
            </thead>
            <tbody>
              {[...snapshot.items].reverse().map((b) => (
                <tr key={b.message.revision_id}>
                  <td>
                    <Link href={`/advisories/${b.message.revision_id}`}>
                      {b.message.sender} ·{" "}
                      {b.message.infos[0]?.event ?? b.message.msgType}
                    </Link>
                  </td>
                  <td>{b.message.sent}</td>
                  <td>
                    {b.message.msgType} · {b.lifecycle.state} ·{" "}
                    {b.message.status}
                  </td>
                  <td>
                    {b.message.infos.some((i) =>
                      i.areas.some(
                        (a) => a.polygons.length || a.circles.length,
                      ),
                    )
                      ? "geometry retained"
                      : "unresolved place names"}
                    {b.lifecycle.issues.length ? " · revision ambiguity" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>
          No verified bulletin archive is available. This does not establish an
          absence of warnings.
        </p>
      )}
    </main>
  );
}
