import Link from "next/link";
import { dependencyNames, validateReport } from "../../lib/health.mjs";
export const dynamic = "force-dynamic";
type Report = {
  status: string;
  checked_at: string;
  dependencies: Record<string, { status: string }>;
};
type Operations = {
  status: string;
  as_of: string;
  production_approved: boolean;
  scientific_approved: boolean;
  controls: { revision: number; paused: Record<string, boolean> };
  sources: {
    fields: {
      product_id: string;
      status: string;
      cycle: string | null;
      valid_time_end: string | null;
      fresh: boolean;
    }[];
    advisories: {
      source_id: string;
      transport: string;
      checked_at: string | null;
      integrity: string;
    }[];
  };
  workers: { notifications: boolean; email_configured: boolean };
};
const labels: Record<string, string> = {
  postgresql: "PostgreSQL",
  postgis: "PostGIS",
  timescaledb: "TimescaleDB",
  schema: "Database schema",
  minio: "Object storage",
  redis: "Redis cache",
  nats_jetstream: "NATS JetStream",
  ml_inference: "Python ML runtime",
  field_service: "Python field runtime",
  web: "Next.js web",
};
async function operations(): Promise<Operations | null> {
  try {
    const response = await fetch(
      `${process.env.API_INTERNAL_URL ?? "http://localhost:8080"}/api/v1/operations/status`,
      { cache: "no-store", signal: AbortSignal.timeout(4000) },
    );
    if (!response.ok) return null;
    const value = await response.json();
    const validTime = (time: unknown) =>
      time === null ||
      (typeof time === "string" && Number.isFinite(Date.parse(time)));
    if (
      value.status !== "available" ||
      !Number.isFinite(Date.parse(value.as_of)) ||
      !Array.isArray(value.sources?.fields) ||
      !Array.isArray(value.sources?.advisories) ||
      !Number.isSafeInteger(value.controls?.revision) ||
      value.controls.revision < 1 ||
      !value.controls.paused ||
      typeof value.controls.paused !== "object" ||
      Array.isArray(value.controls.paused) ||
      !Object.values(value.controls.paused).every(
        (paused) => typeof paused === "boolean",
      ) ||
      typeof value.workers?.notifications !== "boolean" ||
      typeof value.workers?.email_configured !== "boolean" ||
      value.production_approved !== false ||
      value.scientific_approved !== false ||
      value.sources.fields.length > 100 ||
      value.sources.advisories.length > 100 ||
      !value.sources.fields.every(
        (field: Operations["sources"]["fields"][number]) =>
          field &&
          typeof field.product_id === "string" &&
          typeof field.status === "string" &&
          typeof field.fresh === "boolean" &&
          validTime(field.cycle) &&
          validTime(field.valid_time_end),
      ) ||
      !value.sources.advisories.every(
        (source: Operations["sources"]["advisories"][number]) =>
          source &&
          typeof source.source_id === "string" &&
          typeof source.transport === "string" &&
          typeof source.integrity === "string" &&
          validTime(source.checked_at),
      )
    )
      return null;
    return value;
  } catch {
    return null;
  }
}
async function health(): Promise<Report | null> {
  try {
    const response = await fetch(
      `${process.env.API_INTERNAL_URL ?? "http://localhost:8080"}/api/v1/health`,
      { cache: "no-store", signal: AbortSignal.timeout(4000) },
    );
    if (response.status === 200 || response.status === 503)
      return validateReport(await response.json());
  } catch {
    /* Status still renders during outages. */
  }
  return null;
}
export default async function Status() {
  const [report, ops] = await Promise.all([health(), operations()]);
  const paused = ops
    ? Object.entries(ops.controls.paused)
        .filter(([, value]) => value)
        .map(([scope]) => scope)
    : [];
  return (
    <main>
      <nav aria-label="Status navigation">
        <Link href="/">Nautiq</Link>
        <Link href="/data-sources">Sources and limitations</Link>
        <form action="/status" method="get">
          <button type="submit">Refresh checks</button>
        </form>
      </nav>
      <p className="eyebrow">SERVICE AND SOURCE STATUS</p>
      <h1>
        {report?.status === "healthy"
          ? "Services are connected."
          : "Services need attention."}
      </h1>
      <p className="intro">
        Connectivity, source freshness and scientific approval are separate
        checks. A responding service does not establish safe marine conditions.
      </p>
      <div className="summary" role="status">
        Core API: {report ? "reachable" : "unavailable"}
        {report && (
          <span>Checked {new Date(report.checked_at).toISOString()}</span>
        )}
      </div>
      <h2>Service connectivity</h2>
      <ul className="checks">
        {dependencyNames.map((name: string) => (
          <li key={name}>
            <span>{labels[name]}</span>
            <strong
              className={
                report?.dependencies[name]?.status === "healthy"
                  ? "healthy"
                  : "unavailable"
              }
            >
              {report ? report.dependencies[name].status : "unknown"}
            </strong>
          </li>
        ))}
      </ul>
      <h2>Incident controls</h2>
      <p>
        {ops
          ? paused.length
            ? `Paused: ${paused.join(", ").replaceAll("_", " ")}. Existing evidence stays historical.`
            : `No scopes paused. Control revision ${ops.controls.revision}.`
          : "Control state unavailable. Scientific serving fails closed when incident controls cannot be read."}
      </p>
      <h2>Source health</h2>
      {ops ? (
        <>
          <p>
            Checked {ops.as_of}. Native cycles are evaluated against their
            source-age budgets. Transport health does not establish complete
            marine-warning coverage.
          </p>
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Native field cycles"
          >
            <table>
              <caption>Retained native field cycles</caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Integrity</th>
                  <th scope="col">Cycle / valid end (UTC)</th>
                  <th scope="col">Source age</th>
                </tr>
              </thead>
              <tbody>
                {ops.sources.fields.map((field) => (
                  <tr key={field.product_id}>
                    <th scope="row">{field.product_id}</th>
                    <td>{field.status}</td>
                    <td>{field.cycle ?? field.valid_time_end ?? "Unknown"}</td>
                    <td>
                      {field.fresh
                        ? "Within source-age budget"
                        : "Stale or unavailable"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Official feed health"
          >
            <table>
              <caption>Official feed transport and retained integrity</caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Transport</th>
                  <th scope="col">Integrity</th>
                  <th scope="col">Last checked (UTC)</th>
                </tr>
              </thead>
              <tbody>
                {ops.sources.advisories.map((source) => (
                  <tr key={source.source_id}>
                    <th scope="row">{source.source_id}</th>
                    <td>{source.transport}</td>
                    <td>{source.integrity}</td>
                    <td>{source.checked_at ?? "Unknown"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Notification worker:{" "}
            {ops.workers.notifications
              ? "responding"
              : "unavailable or delayed"}
            . Email transport:{" "}
            {ops.workers.email_configured ? "configured" : "unconfigured"}.
          </p>
        </>
      ) : (
        <p>
          Source and worker health are unknown while the operational status
          service is unavailable.
        </p>
      )}
      <h2>Release approval</h2>
      <p className="notice">
        Public production and scientific approval remain unavailable.
        Calibration, source cadence, marine advisory completeness, source
        rights, reviewed trip wording and security sign-off require separate
        evidence.
      </p>
      <p>
        <Link href="/methodology">Review the methods</Link> ·{" "}
        <Link href="/app/alerts">Private monitoring status</Link>
      </p>
    </main>
  );
}
