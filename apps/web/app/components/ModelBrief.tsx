import Link from "next/link";
import { evidence } from "../../lib/science";
import type { ModelReport, ModelSummary } from "../../lib/expected";
import { statusWords, type MonitoringResponse } from "../../lib/monitoring";
import { Signal } from "./ui/Signal";
import { when, type Status } from "../../lib/humanize";
const reasonText: Record<string, string> = {
  promotion_thresholds_not_reviewed: "the promotion thresholds have not been reviewed",
  test_block_previously_inspected: "the 2022–2024 test years were already looked at, so they cannot approve a release",
  spatial_platform_audits_not_approved: "the spatial and float-independence audits are not approved",
  source_coverage_not_approved: "source coverage is not approved",
  insufficient_material_improvement: "it did not improve enough over the seasonal normal",
};
function reasons(codes: string[]) {
  const named = codes.filter((c) => reasonText[c]).map((c) => reasonText[c]);
  const regress = codes.filter((c) => c.startsWith("subgroup_regression")).length;
  return [...named, ...(regress ? [`it got worse in ${regress} depth or region group${regress > 1 ? "s" : ""}`] : [])];
}
type IntervalSummary = { release_id: string; status: string; release_approved: false };
export default async function ModelBrief({ compact = false }: { compact?: boolean }) {
  const [selected, intervals, anomalies, monitoring] = await Promise.all([
    evidence<ModelSummary>("/expected-state-releases/selected"),
    evidence<IntervalSummary>("/uncertainty-releases/selected"),
    evidence<IntervalSummary>("/anomaly-releases/selected"),
    evidence<MonitoringResponse>("/model-monitoring?history=1"),
  ]);
  const detail = selected ? await evidence<{ report: ModelReport }>(`/expected-state-releases/${selected.release_id}`) : null;
  const methods = selected?.active_methods ?? {};
  const allClimatology = selected ? Object.values(methods).every((m) => m === "climatology") : false;
  const why = new Set<string>();
  for (const v of Object.values(detail?.report?.variables ?? {})) for (const r of reasons(v.promotion?.reasons ?? [])) why.add(r);
  const [, word, tone] = statusWords[monitoring?.latest?.status ?? "reference_unavailable"] ?? ["", "", "unavailable"];
  return (
    <section className="model-brief" aria-labelledby="model-brief-title">
      <h2 id="model-brief-title">What the models are doing today</h2>
      <ul className="brief-list">
        <li>
          <strong>Expected normal.</strong>{" "}
          {selected
            ? allClimatology
              ? "Both temperature and salinity use a seasonal historical normal (2005–2016 Argo data). A learned residual model was tested against it but is not used."
              : "A learned residual model is active for at least one variable."
            : "No expected-normal release is selected, so no comparison with normal is shown."}
          {!compact && why.size ? <> The learned model was not promoted because {[...why].join("; ")}.</> : null}
        </li>
        <li>
          <strong>Expected range.</strong>{" "}
          {intervals ? "A calibrated range around the normal is shown as diagnostic evidence. It describes ordinary variability; its coverage cannot be confirmed until trusted delayed-mode outcomes exist." : "No interval release is selected."}
        </li>
        <li>
          <strong>Unusual profiles.</strong>{" "}
          {anomalies ? "Each complete profile gets descriptive ranks and a category (typical, elevated, unusual, strongly unusual) with its components. These are ranks against history, not event probabilities." : "No profile-ranking release is selected."}
        </li>
        <li>
          <strong>Monitoring.</strong> <Signal status={tone as Status}>{word}</Signal>{" "}
          {monitoring?.latest ? <>checked {when(monitoring.latest.checked_at)}.</> : "has not been run yet."} <Link href="/models/monitoring">Details</Link>
        </li>
      </ul>
      <p className="footnote">
        None of this is scientifically approved for release, and no model ever produces a trip verdict or an observation.{" "}
        <Link href="/models">Model evidence</Link> · <Link href="/methodology">Methods</Link>
      </p>
    </section>
  );
}
