export type IntervalMetric = {
  rows: number; profiles: number; pinball_loss: number | null;
  crossing_rate: number | null; raw_row_coverage: number | null;
  row_coverage: number | null; profile_group_count: number;
  profile_group_coverage: number | null; profile_group_coverage_95: [number, number] | null;
  full_profile_coverage: number | null; profile_weighted_width: number | null;
  fallback_rows: number; unavailable_rows: number;
};
export type IntervalSummary = {
  release_id: string; expected_id: string; reference_id: string; snapshot_id: string;
  calculation_id: string; status: string; selected: boolean; release_approved: false;
  selected_families: Record<string, string | null>; qualified: Record<string, boolean>;
  nominal_coverage: number; coverage_unit: string;
  fitting_period: {start_year: number; end_year: number};
  calibration_period: {start_year: number; end_year: number};
};
export type CalibrationGroup = {profiles: number; rank: number; correction: number | null; reason: string | null};
export type IntervalVariable = {
  status: string; reason?: string; selected_family?: string; selection_rule?: string;
  profile_counts: Record<string, number>;
  coverage_gate: {qualified: boolean; reasons: string[]};
  selected?: Record<string, {parameters: Record<string, unknown>[]; tuning_profile_pinball: number; tuning_raw_coverage: number; tuning_crossing_rate: number}>;
  families?: Record<string, {
    calibration: {groups: Record<string, CalibrationGroup>};
    evaluation: Record<string, Record<string, IntervalMetric>>;
    native_model_count: number; outside_quantile_training_envelope_rows: number;
  }>;
};
export type IntervalRelease = IntervalSummary & {
  manifest: {output: IntervalSummary & {bundle_sha256: string; report_sha256: string}};
  report: {
    variables: Record<string, IntervalVariable>; code_sha256: string; source_git_commit: string;
    feature_schema: {version: string; names: string[]}; interval_interpretation: string;
    policy: {hierarchy: string[]; min_calibration_profiles: number; max_predict_p95_ms: number};
    independence_audits: {kind: string; fold: string; complement_profiles: number; held_profiles: number; reference_fit_hash: string; variables: Record<string, {status: string; families: Record<string, IntervalMetric>}>}[];
  };
  tracking: null | {registered_model: string; model_version: string; run_id: string; performance: Record<string, unknown>};
};
export type IntervalPoint = {
  expected_mean: number | null; observed: number | null; q10: number | null; q50: number | null; q90: number | null;
  lower: number | null; upper: number | null; width: number | null; correction: number | null; covered: boolean | null;
  status: string; reason: string | null; family: string; calibration_group: string | null; requested_group: string | null;
  calibration_profiles: number; calibration_rank: number | null; fallback: boolean; fallback_reasons: string[];
  quantile_crossing: boolean; coverage_qualified: boolean;
};
export type IntervalProfile = {
  profile_id: string; revision_sha256: string; release_id: string | null; expected_id: string | null; reference_id: string | null;
  calculation_id: string | null; status: string; pending_reason: string | null; nominal_coverage: number | null;
  result: null | {supported_intervals: number; rows: {depth_m: number; temperature_c: IntervalPoint; practical_salinity: IntervalPoint}[]};
};
export type Coverage = {
  release_id: string; status: string; calculation_id: string | null; checked_at: string | null;
  report: null | {window_start: string; window_end: string; trusted_profiles: number; pending_profiles: number; skipped_untrusted_profiles: number; variables: Record<string, IntervalMetric & {status: string; suspect_profiles_for_adaptation: number}>};
};
