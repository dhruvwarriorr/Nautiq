import { apiURL } from "./profiles";
export async function evidence<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${apiURL}/api/v1${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(9000),
    });
    return response.ok ? ((await response.json()) as T) : null;
  } catch {
    return null;
  }
}
export type Source = {
  source_id: string;
  metadata: {
    provider: string;
    attribution: string;
    terms_url: string;
    license_state: string;
    production_approved: boolean;
  };
  monitor_state: string;
  monitor_checked_at: string | null;
  health: null | {
    source_freshness: string;
    ingestion_state: string;
    coverage_state: string;
    expected_update_hours: number | null;
    cadence_verified: boolean;
    newest_observed_at: string | null;
    last_successful_fetch: string | null;
    observation_age_hours: number | null;
    pending_event_count: number;
    qc_rejection_count: number;
  };
};
export type Rejection = {
  rejection_id: string;
  artifact_id: string | null;
  source_id: string;
  profile_index: number | null;
  variable: string | null;
  rule_id: string;
  reason_code: string;
  qc_version: string;
  rejected_count: number;
  context: Record<string, unknown>;
  created_at: string;
};
export type SnapshotSummary = {
  snapshot_id: string;
  snapshot_sha256: string;
  calculation_id: string;
  profile_count: number;
  row_count: number;
  created_at: string;
  parquet_sha256: string;
  status: string;
};
export type Input = {
  profile_id: string;
  revision_sha256: string;
  raw_sha256: string;
};
export type Manifest = {
  calculation_id: string;
  calculation_sha256: string;
  kind: string;
  method_version: string;
  inputs: Input[];
  evaluation_time: string;
  code_sha256: string;
  policy: Record<string, unknown>;
  environment: Record<string, string>;
  output: Record<string, unknown>;
};
export type Calculation = {
  calculation_id: string;
  kind: string;
  state: string;
  created_at: string;
  manifest_sha256: string;
  manifest: Manifest;
};
export type Snapshot = SnapshotSummary & {
  manifest_sha256: string;
  manifest: Manifest;
};
export type Revision = {
  revision_sha256: string;
  data_mode: string;
  source_updated_at: string;
  selection_state: string;
  science_ready: boolean;
  calculation_id: string | null;
  raw_sha256: string;
};
export type Statistics = {
  profile_id: string;
  revision_sha256: string;
  status: string;
  calculation_id: string | null;
  statistics: Record<string, unknown> | null;
};
