import Link from "next/link";
import { dependencyNames, validateReport } from "../../lib/health.mjs";
export const dynamic = "force-dynamic";
type Report = { status: string; checked_at: string; dependencies: Record<string, {status: string; detail?: string}> };
const labels: Record<string, string> = {postgresql:"PostgreSQL",postgis:"PostGIS",timescaledb:"TimescaleDB",schema:"Database schema",minio:"MinIO object storage",redis:"Redis cache",nats_jetstream:"NATS JetStream",ml_inference:"Python ML runtime",field_service:"Python field runtime",web:"Next.js web"};
export default async function Status() {
  let report: Report | null = null;
  try {
    const response = await fetch(`${process.env.API_INTERNAL_URL ?? "http://localhost:8080"}/api/v1/health`, {cache:"no-store", signal:AbortSignal.timeout(5000)});
    if (response.status === 200 || response.status === 503) report = validateReport(await response.json());
  } catch { /* The status page remains available during a Core API outage. */ }
  return <main><nav><Link href="/">Nautiq</Link><form action="/status" method="get"><button type="submit">Refresh checks ↻</button></form></nav><p className="eyebrow">PHASE 1 / PLATFORM HEALTH</p><h1>{report?.status === "healthy" ? "Local platform ready." : "Platform needs attention."}</h1><p className="intro">{report ? "Live checks of the local services and required storage capabilities." : "The Core API is unavailable or returned an invalid health response. Start the stack and refresh this page."}</p><div className="summary" role="status">Core API: {report ? "reachable" : "unavailable"}{report && <span>Checked {new Date(report.checked_at).toISOString().replace("T", " ").replace("Z", " UTC")}</span>}</div><ul className="checks">{dependencyNames.map((name:string) => <li key={name}><span>{labels[name]}</span><strong className={report?.dependencies[name]?.status === "healthy" ? "healthy" : "unavailable"}>{report ? report.dependencies[name].status : "unknown"}</strong></li>)}</ul><p className="footnote">Runtime health confirms connectivity. Scientific models and data feeds are introduced in later phases.</p></main>;
}
