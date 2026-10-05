import Link from "next/link";
import { dependencyNames, validateReport } from "../../lib/health.mjs";
import { ago, label, sourceName, when } from "../../lib/humanize";
import { PageHead, TechDetail, Notice } from "../components/ui/Bits";
import Icon from "../components/ui/Icon";
import { Signal } from "../components/ui/Signal";
export const metadata = { title: "System status · Nautiq" };
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
  postgresql: "Database",
  postgis: "Map database",
  timescaledb: "Time-series store",
  schema: "Database structure",
  minio: "File storage",
  redis: "Cache",
  nats_jetstream: "Message queue",
  ml_inference: "Model service",
  field_service: "Forecast service",
  web: "Website",
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
const productNames: Record<string, string> = {
  noaa_oisst: "Sea temperature (NOAA, daily)",
  noaa_gfs_wave: "Wave forecast (NOAA)",
  noaa_gfs_weather: "Wind forecast (NOAA)",
  hycom_espc: "Current forecast (HYCOM)",
};
export default async function Status() {
  const [report, ops] = await Promise.all([health(), operations()]);
  const paused = ops
    ? Object.entries(ops.controls.paused)
        .filter(([, value]) => value)
        .map(([scope]) => scope)
    : [];
  const healthy = report?.status === "healthy";
  return (
    <main>
      <PageHead
        icon="clock"
        back={{ href: "/behind-the-data", label: "Behind the data" }}
        title={healthy ? "All services running" : report ? "Some services need attention" : "Status unavailable"}
        lede={report ? `Checked ${when(report.checked_at)}. A running service doesn’t mean the sea is safe.` : "The status service didn’t answer. Treat every feed as unknown until it returns."}
      >
        <form action="/status" method="get" className="head-actions">
          <button type="submit" className="btn">
            <Icon name="clock" size={18} /> Check again
          </button>
        </form>
      </PageHead>

      <section aria-labelledby="feeds">
        <div className="section-head">
          <h2 id="feeds">Data feeds</h2>
          <p>Is each source recent enough to use?</p>
        </div>
        {ops ? (
          <ul className="rows">
            {ops.sources.fields.map((f) => (
              <li key={f.product_id} className="row">
                <span className="row-icon">
                  <Icon name={f.product_id.includes("wave") ? "waves" : f.product_id.includes("weather") ? "windsock" : f.product_id.includes("hycom") ? "current" : "thermo"} size={22} />
                </span>
                <span>
                  <span className="row-title">{productNames[f.product_id] ?? label(f.product_id)}</span>
                  <span className="row-sub" style={{ display: "block" }}>
                    {f.cycle ? `Issued ${when(f.cycle)}` : f.valid_time_end ? `Covers until ${when(f.valid_time_end)}` : "No issue time"}
                  </span>
                </span>
                <Signal status={f.fresh ? "available" : "stale"}>{f.fresh ? "Up to date" : "Out of date"}</Signal>
              </li>
            ))}
            {ops.sources.advisories.map((a) => (
              <li key={a.source_id} className="row">
                <span className="row-icon">
                  <Icon name="pennant" size={22} />
                </span>
                <span>
                  <span className="row-title">{sourceName(a.source_id)}</span>
                  <span className="row-sub" style={{ display: "block" }}>
                    {a.transport === "unconfigured" ? "Not connected yet" : a.checked_at ? `Last checked ${ago(a.checked_at)}` : "Never checked"}
                  </span>
                </span>
                <Signal status={a.transport === "healthy" ? "available" : a.transport === "stale" ? "stale" : "unavailable"}>
                  {a.transport === "healthy" ? "Up to date" : a.transport === "stale" ? "Not recent" : "Not connected"}
                </Signal>
              </li>
            ))}
            <li className="row">
              <span className="row-icon">
                <Icon name="bell" size={22} />
              </span>
              <span>
                <span className="row-title">Alerts and email</span>
                <span className="row-sub" style={{ display: "block" }}>
                  Alert worker {ops.workers.notifications ? "responding" : "not responding"} · email {ops.workers.email_configured ? "set up" : "not set up"}
                </span>
              </span>
              <Signal status={ops.workers.notifications ? "available" : "unavailable"}>{ops.workers.notifications ? "Running" : "Down"}</Signal>
            </li>
          </ul>
        ) : (
          <Notice tone="caution" title="Feed status unavailable">
            <p>Treat every source as unknown until this returns.</p>
          </Notice>
        )}
        {paused.length ? (
          <Notice tone="caution" title="Some updates are paused">
            <p>Paused: {paused.map((x) => label(x).toLowerCase()).join(", ")}. What’s already stored is shown as history.</p>
          </Notice>
        ) : null}
      </section>

      <section className="section" aria-labelledby="services">
        <div className="section-head">
          <h2 id="services">Services</h2>
          <p>The parts that keep Nautiq running.</p>
        </div>
        <ul className="service-grid">
          {dependencyNames.map((name: string) => {
            const ok = report?.dependencies[name]?.status === "healthy";
            return (
              <li key={name}>
                <span>{labels[name]}</span>
                <Signal status={report ? (ok ? "available" : "unavailable") : "unknown"}>{report ? (ok ? "Running" : label(report.dependencies[name]?.status)) : "Unknown"}</Signal>
              </li>
            );
          })}
        </ul>
      </section>

      <div className="section">
        <Notice tone="caution" title="Not yet approved for public release">
          <p>Scientific calibration, source schedules, warning coverage of the sea, data rights, trip wording and security still need separate sign-off.</p>
        </Notice>
      </div>

      <TechDetail>
        <p>Control revision {ops?.controls.revision ?? "unknown"}. Scientific serving stops if incident controls can’t be read.</p>
        <p>
          <Link href="/methodology">How it works</Link> · <Link href="/app/alerts">Your alert monitoring</Link>
        </p>
      </TechDetail>
    </main>
  );
}
