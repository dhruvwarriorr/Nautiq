export type Geometry = {
  type: "Polygon" | "MultiPolygon" | "MultiPoint";
  coordinates: unknown;
};
export type RegionalEvent = {
  event_id: string;
  kind:
    | "surface_thermal_candidate"
    | "regional_profile_candidate"
    | "isolated_profile_anomalies";
  variable: string;
  start: string;
  end: string;
  duration_days: number;
  persistence_days: number;
  geometry: Geometry;
  maximum_intensity: number;
  mean_intensity: number;
  units: string;
  support_kind: string;
  cell_count?: number;
  cell_days?: number;
  profile_count?: number;
  platform_count?: number;
  maximum_category?: number;
  left_censored?: boolean;
  right_censored?: boolean;
  direction?: string;
  coverage_state?: string;
  release_approved: false;
  daily_support?: {
    day: string;
    cells: number;
    area_km2: number;
    observed_cells: number;
    mean_intensity: number;
    maximum_intensity: number;
    supported_regional_day: boolean;
  }[];
  members: unknown[];
};
export type EventRunSummary = {
  run_id: string;
  kind: string;
  calculation_id: string;
  report_sha256: string;
  baseline_id: string | null;
  history_id: string | null;
  anomaly_id: string | null;
  status: string;
  input_state: string;
  start: string;
  end: string;
  created_at: string;
  event_count: number;
  release_approved: false;
};
export type EventReport = {
  kind: string;
  method_version: string;
  start: string;
  end: string;
  extent: number[];
  events: RegionalEvent[];
  release_approved: false;
  limitations: string[];
  as_of?: string;
  baseline_years?: number[];
  baseline_id?: string;
  history_id?: string;
  anomaly_id?: string;
  regional_groups?: number;
  isolated_groups?: number;
  qualified_cell_days?: number;
  rejected_small_components?: number;
  coverage:
    | {
        day: string;
        observed_cells: number;
        unknown_cells: number;
        above_threshold_cells: number;
        qualified_cells: number;
      }[]
    | {
        queried_profiles: number;
        exceedance_variable_points: number;
        reasons: Record<string, number>;
        state: string;
      };
};
export type EventRun = EventRunSummary & {
  report: EventReport;
  manifest: {
    code_sha256: string;
    policy_sha256: string;
    source_git_commit: string;
    inputs: Record<string, unknown>;
  };
};
export type EventDetail = Omit<EventRun, "report"> & { event: RegionalEvent };
export type EventDataset = {
  dataset_id: string;
  kind: string;
  parent_id: string | null;
  calculation_id: string;
  status: string;
  created_at: string;
  manifest_sha256: string;
  metadata?: Record<string, unknown>;
  manifest?: {
    code_sha256: string;
    arrays_sha256: string;
    arrays_bytes: number;
    metadata: {
      dates?: string[];
      shape: number[];
      supported_seasonal_cells?: number;
      baseline_years?: number[];
      missing_cells?: number;
      source: { attribution: string; documentation: string };
      raw?: { url: string; sha256: string; bytes: number }[];
    };
  };
};
const labels: Record<string, string> = {
  surface_thermal_candidate: "Persistent SST candidate",
  regional_profile_candidate: "Regional profile group",
  isolated_profile_anomalies: "Isolated profile evidence",
  surface_thermal: "SST threshold and persistence",
  profile_groups: "Profile point grouping",
};
export const eventLabel = (kind: string) => labels[kind] ?? kind;
export const eventNumber = (n: number) =>
  n.toLocaleString("en", { maximumFractionDigits: 3 });
