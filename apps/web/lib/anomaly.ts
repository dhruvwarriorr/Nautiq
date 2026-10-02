export const labels: Record<string, string> = {
  weighted_squared_residual: "Depth-weighted squared residual",
  mahalanobis_squared: "Shrinkage Mahalanobis distance²",
  fpca_distance_squared: "PCA score-space distance²",
  fpca_reconstruction_error: "PCA reconstruction error",
  climatology_z_squared: "Climatology Z-score baseline",
  isolation_forest: "Isolation Forest baseline",
};
export const title = (v: string) => v === "temperature_c" ? "Temperature" : "Practical salinity";
export const n = (value: number | null | undefined) => value == null ? "Unavailable" : value.toLocaleString("en", {maximumFractionDigits: 4});
export type Depth = {depth_m: number; observed: number | null; expected_mean: number | null; residual: number | null; scale: number | null; scale_floored: boolean; standardized_residual: number | null; covered: boolean; reason: string | null; training_center?: number; centered_standardized_residual?: number; weighted_contribution?: number; mahalanobis_contribution?: number; reconstructed_standardized_residual?: number; reconstruction_error?: number};
export type VariableEvidence = {status: string; reason: string | null; complete: boolean; qualified: false; points: Depth[]; max_signed_standardized_residual?: number; maximum_departure_depth_m?: number; largest_contribution_depth_m?: number; depth_bands?: {start_m: number; end_m: number; weighted_contribution: number; signed_mean_residual: number}[];
  score_evidence: {scores: Record<string, number>; component_scores: number[]; component_distance_contributions: number[]; dominant_component: number} | null;
  percentiles: {requested_group: string; group: string | null; fallback: boolean; profiles: number; resolution_percent: number | null; reason: string | null; values: Record<string, number | null>} | null};
export type AnomalyProfile = {profile_id: string; revision_sha256: string; release_id: string | null; uncertainty_id: string | null; expected_id: string | null; reference_id: string | null; calculation_id: string | null; reference_calculation_id: string | null; status: string; pending_reason: string | null; release_approved: false; result: {status: string; depths_m: number[]; scale_estimator: string; variables: Record<string, VariableEvidence>} | null};
export type VariableReport = {status: string; reason: string | null; qualified: false; qualification_reasons: string[]; complete_profiles: Record<string, number>; excluded_profiles: Record<string, number>; covariance_condition?: number; covariance_shrinkage?: number; explained_variance_ratio?: number[]; basis_loadings?: number[][]; comparison_groups?: Record<string, {profiles: number; resolution_percent: number}>;
 evaluation?: Record<string, {profiles: number; percentile_supported_profiles: number; median_scores: Record<string, number | null>; median_percentiles: Record<string, number | null>}>;
 synthetic_layer_sensitivity?: {perturbation: string; profiles: number; median_score_change: Record<string, number | null>};
 resampling_stability?: {seed: number; status: string; reason?: string; tune_profiles?: number; rank_correlations?: Record<string, number | null>}[]};
export type AnomalyRelease = {release_id: string; uncertainty_id: string; expected_id: string; reference_id: string; snapshot_id: string; calculation_id: string; status: string; selected: boolean; release_approved: false; created_at: string;
 manifest: {output: {bundle_sha256: string; supported_variables: string[]}};
 report: {method_version: string; code_sha256: string; source_git_commit: string; depths_m: number[]; weights: number[]; coverage_policy: string; scale_estimator: string; limitations: string[]; variables: Record<string, VariableReport>; policy: {min_train_profiles: number; min_calibration_profiles: number; components: number; hierarchy: string[]; scale_floor: Record<string, number>; max_predict_p95_ms: number}};
 tracking: {run_id: string; registered_model: string; model_version: string; performance: Record<string, {p95_score_ms: number; scope: string}>} | null};

export type AnomalySummary = Pick<AnomalyRelease, "release_id" | "uncertainty_id" | "expected_id" | "reference_id" | "snapshot_id" | "calculation_id" | "status" | "selected" | "release_approved" | "created_at"> & {supported_variables: string[]; depths_m: number[]; coverage_policy: string; scale_estimator: string};
