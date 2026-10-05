import Link from "next/link";
import { evidence } from "../../../../lib/science";
import { eventLabel, type EventRun } from "../../../../lib/events";
import EventMap from "../../EventMap";
import { PageHead } from "../../../components/ui/Bits";
import { when } from "../../../../lib/humanize";
export const metadata = { title: "Event detection run · Nautiq" };
export const dynamic = "force-dynamic";
export default async function RunPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const run = /^[a-f0-9-]{36}$/.test(id)
    ? await evidence<EventRun>(`/event-runs/${id}`)
    : null;
  if (!run)
    return (
      <main><PageHead back={{ href: "/events", label: "Event evidence" }} title="Event run unavailable" lede={"The retained report is absent or its integrity could not be verified."} /></main>
    );
  const report = run.report;
  return (
    <main>
      <PageHead back={{ href: "/events", label: "Regional events" }} title={<>{report.start} to {report.end}</>} lede={<>{report.events.length} retained components · {run.input_state}. The
        detector describes this exact source window; it does not certify current
        conditions.</>} />
      <p className="notice">
        Scientific release approval is false. Isolated profile evidence remains
        separate from regional candidates. Missing coverage cannot establish
        absence of events.
      </p>
      <dl className="field-metadata">
        <div>
          <dt>Method</dt>
          <dd>{report.method_version}</dd>
        </div>
        <div>
          <dt>Input state</dt>
          <dd>
            {run.input_state}
            {report.as_of ? ` · ${when(report.as_of)}` : ""}
          </dd>
        </div>
        <div>
          <dt>Run / report SHA-256</dt>
          <dd className="digest">
            {run.run_id}
            <br />
            {run.report_sha256}
          </dd>
        </div>
        <div>
          <dt>Code / policy SHA-256</dt>
          <dd className="digest">
            {run.manifest.code_sha256}
            <br />
            {run.manifest.policy_sha256}
          </dd>
        </div>
      </dl>
      {report.baseline_id ? (
        <p>
          <Link href={`/events/datasets/${report.baseline_id}`}>
            Fixed baseline ({report.baseline_years?.join("–")})
          </Link>{" "}
          ·{" "}
          <Link href={`/events/datasets/${report.history_id}`}>
            Daily source window
          </Link>
        </p>
      ) : (
        <p>
          <Link href={`/anomalies/${report.anomaly_id}`}>
            Exact profile anomaly parent
          </Link>
          . {report.regional_groups} regional groups; {report.isolated_groups}{" "}
          isolated groups.
        </p>
      )}
      <EventMap events={report.events} extent={report.extent} />
      <h2>Components and support</h2>
      {!report.events.length ? (
        <p>
          No regional candidate satisfies the declared persistence and support
          rules in this covered window. Unknown cells and unsupported profiles
          remain explicit below.
        </p>
      ) : (
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Regional and isolated components"
        >
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Variable</th>
                <th>Window</th>
                <th>Persistence</th>
                <th>Actual support</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {report.events.map((e) => (
                <tr key={e.event_id}>
                  <td>{eventLabel(e.kind)}</td>
                  <td>{e.variable}</td>
                  <td>
                    {e.start} to {e.end}
                  </td>
                  <td>{e.persistence_days} observed days</td>
                  <td>
                    {e.cell_count
                      ? `${e.cell_count} native cells`
                      : `${e.profile_count} profiles / ${e.platform_count} platforms`}
                  </td>
                  <td>
                    <Link href={`/events/${e.event_id}`}>
                      Inspect component →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h2>Source coverage</h2>
      {Array.isArray(report.coverage) ? (
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Daily SST coverage"
        >
          <table>
            <thead>
              <tr>
                <th>UTC day</th>
                <th>Observed cells</th>
                <th>Unknown cells</th>
                <th>Above threshold</th>
                <th>Qualified cell days</th>
              </tr>
            </thead>
            <tbody>
              {report.coverage.map((d) => (
                <tr key={d.day}>
                  <td>{d.day}</td>
                  <td>{d.observed_cells}</td>
                  <td>{d.unknown_cells}</td>
                  <td>{d.above_threshold_cells}</td>
                  <td>{d.qualified_cells}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <p>
            {report.coverage.queried_profiles} queried profiles;{" "}
            {report.coverage.exceedance_variable_points} exceedance variable
            points. Coverage between observations is unknown.
          </p>
          <ul>
            {Object.entries(report.coverage.reasons).map(([reason, n]) => (
              <li key={reason}>
                {reason.replaceAll("_", " ")}: {n}
              </li>
            ))}
          </ul>
        </>
      )}
      <ul>
        {report.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </main>
  );
}
