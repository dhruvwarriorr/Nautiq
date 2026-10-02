import Link from "next/link";
import { evidence } from "../../lib/science";
import {
  eventLabel,
  type EventRunSummary,
  type EventDataset,
} from "../../lib/events";
export const dynamic = "force-dynamic";
export default async function Events() {
  const [runs, baselines] = await Promise.all([
    evidence<{ items: EventRunSummary[] }>("/event-runs?limit=50"),
    evidence<{ items: EventDataset[] }>(
      "/event-datasets?kind=baseline&limit=50",
    ),
  ]);
  return (
    <main className="explorer">
      <nav>
        <Link href="/">Nautiq</Link>
        <Link href="/fields">Surface fields</Link>
        <Link href="/anomalies">Profile diagnostics</Link>
      </nav>
      <p className="eyebrow">REGIONAL EVENTS / PERSISTENCE AND SUPPORT</p>
      <h1>Separate a departure from a persistent event.</h1>
      <p className="intro">
        Inspect fixed seasonal SST thresholds, consecutive-day persistence and
        spatial support. Profile anomalies are grouped separately using their
        actual observed positions, dates and platforms.
      </p>
      <p className="notice">
        One unusual profile is not a regional heatwave. These are retained
        diagnostic candidates; scientific event approval and live alerting
        remain unavailable.
      </p>
      <div className="evidence-grid">
        <section>
          <h2>Surface thermal candidates</h2>
          <p>
            A fixed 1982–2011 daily baseline supplies the seasonal 90th
            percentile. Five consecutive exceedance days are required. Missing
            days remain unknown; only observed short gaps can join qualified
            runs.
          </p>
        </section>
        <section>
          <h2>Profile point groups</h2>
          <p>
            Historical percentile exceedances need multiple profiles, platforms
            and observed dates to form a regional candidate. Sparse point
            support never becomes a dense SST polygon.
          </p>
        </section>
      </div>
      <h2>Retained detection runs</h2>
      {!runs ? (
        <p>Event evidence is unavailable.</p>
      ) : !runs.items.length ? (
        <p>
          No event run has been built. A missing detector run does not mean that
          no event occurred.
        </p>
      ) : (
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Detection run evidence"
        >
          <table>
            <thead>
              <tr>
                <th>Method</th>
                <th>Window (UTC)</th>
                <th>Components</th>
                <th>Input state</th>
                <th>Release</th>
              </tr>
            </thead>
            <tbody>
              {runs.items.map((r) => (
                <tr key={r.run_id}>
                  <td>
                    <Link href={`/events/runs/${r.run_id}`}>
                      {eventLabel(r.kind)}
                    </Link>
                  </td>
                  <td>
                    {r.start} to {r.end}
                  </td>
                  <td>{r.event_count}</td>
                  <td>
                    {r.status} · {r.input_state}
                  </td>
                  <td className="digest">{r.run_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h2>Frozen SST baselines</h2>
      {baselines?.items.length ? (
        baselines.items.map((b) => (
          <p key={b.dataset_id}>
            <Link href={`/events/datasets/${b.dataset_id}`}>
              {b.dataset_id}
            </Link>{" "}
            · {b.status} ·{" "}
            <Link href={`/calculations/${b.calculation_id}`}>
              Calculation evidence
            </Link>
          </p>
        ))
      ) : (
        <p>
          No compatible fixed baseline is available. Current SST alone cannot
          establish a heatwave.
        </p>
      )}
    </main>
  );
}
