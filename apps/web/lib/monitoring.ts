export type MonStatus = "reference_unavailable" | "insufficient_evidence" | "within_expectation" | "investigate";
export type MonFlag = { code: string; message: string; section: string };
export type Drift = { psi: number | null; status: string; note?: string };
export type Section = { status: MonStatus; reason?: string; flags: { code: string; message: string }[] } & Record<string, unknown>;
export type MonitoringReport = {
  schema_version: 1;
  method_version: string;
  checked_at: string;
  window_start: string;
  window_end: string;
  status: MonStatus;
  pins: Record<string, string>;
  policy: Record<string, unknown> & { window_days: number; threshold_note: string; thresholds_reviewed: boolean };
  sections: {
    inputs: Section & {
      recent_profiles: number;
      baseline_profiles: number;
      feature_availability: { profiles_with_expected_comparison: number; cells_without_expected_mean: number; profile_depth_variable_cells: number; missing_rate: number | null; reasons: Record<string, number>; interpretation: string };
      distribution_drift: Record<string, Drift>;
      spatial_coverage: { cell_degrees: number; recent_cells: number; baseline_cells: number; recent_profiles_in_cells_without_training_profiles: number; novel_cell_share: number | null };
    };
    expected_state_outcomes: Section & {
      trusted_profiles: number;
      recent_profiles_with_comparison: number;
      label_policy: string;
      variables: Record<string, Record<"trusted" | "unverified_realtime", Record<"active_method" | "residual_candidate" | "climatology", { profiles: number; profile_weighted_mae: number | null; profile_weighted_bias: number | null }>>>;
    };
    profile_detector: Section & {
      note: string;
      variables: Record<string, { status: string; scored_profiles: number; regional_fallback_share: number | null; reference_resolution_share: number | null; reason?: string; histogram_deciles?: number[]; tail_shares: Record<string, { percentile_at_least: number; profiles: number; share: number | null; reference_share: number; p_value_excess: number | null; resolvable_with_reference: boolean }> }>;
    };
    calibration: Section & {
      coverage_monitor?: { checked_at: string; nominal_coverage: number; trusted_profiles: number; candidate_profiles: number; pending_profiles: number; variables: Record<string, { status: string | null; profile_group_coverage: number | null }> };
      recent_interval_usage?: Record<string, { interval_cells: number; fallback_group_share: number | null; median_width: number | null }>;
    };
  };
  flags: MonFlag[];
  actions: string;
  release_approved: false;
};
export type MonitoringResponse = {
  latest: null | { report_id: string; checked_at: string; status: MonStatus; calculation_id: string; report: MonitoringReport; report_sha256: string; age_seconds: number; pins_current: boolean };
  history: { report_id: string; checked_at: string; status: MonStatus }[];
  method: string;
  actions: string;
};
export const statusWords: Record<string, [string, string, string]> = {
  within_expectation: ["✓", "Within expectation", "available"],
  insufficient_evidence: ["?", "Not enough evidence", "unknown"],
  investigate: ["⚠", "Investigate", "warning"],
  reference_unavailable: ["–", "No selected release", "unavailable"],
  watch: ["⏱", "Watch", "stale"],
  informative_only: ["i", "Informative only", "unknown"],
};
export const pct = (v: number | null | undefined, digits = 0) => (v == null ? "Unavailable" : `${(v * 100).toFixed(digits)}%`);
export const num = (v: number | null | undefined, digits = 3) => (v == null ? "Unavailable" : v.toFixed(digits));
