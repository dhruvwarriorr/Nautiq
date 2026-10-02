export type Metric = {
  evaluated_rows: number;
  profiles: number;
  candidate_rows: number;
  mae: number | null;
  rmse: number | null;
  bias: number | null;
  profile_weighted_mae: number | null;
  profile_bootstrap_mae_95: [number, number] | null;
  coverage_counts: Record<string, number>;
};
export type Evaluation = {
  variables: Record<
    string,
    Record<
      string,
      {
        overall: Metric;
        regions: Record<string, Metric>;
        depths: Record<string, Metric>;
      }
    >
  >;
  bootstrap_limitations: string;
};
export type ReferenceSummary = {
  release_id: string;
  snapshot_id: string;
  calculation_id: string;
  status: string;
  selected: boolean;
  model_count: number;
  fitting_period: { start_year: number; end_year: number };
  release_approved: false;
};
export type Reference = ReferenceSummary & {
  manifest: {
    output: {
      fitting_period: ReferenceSummary["fitting_period"];
      dataset_baseline: ReferenceSummary["fitting_period"];
      model_count: number;
      profile_count: number;
      standard_grid_rows: number;
      limitations: string[];
      fit_hash: string;
      support_models: Record<string, unknown>[];
    };
    policy: {
      climatology_policy: {
        standard_depths_m: number[];
        max_interpolation_gap_m: number;
        min_profiles: number;
        min_months: number;
        min_platforms: number;
      };
    };
  };
  evaluation: Evaluation;
};
export type ComparedVariable = {
  observed: number | null;
  observed_reason: string | null;
  observed_method: string | null;
  expected_mean: number | null;
  difference: number | null;
  direction: string;
  spread?: number;
  spread_estimator?: string;
  reason: string | null;
  fallback?: boolean;
  method_group?: string;
  fallback_reasons?: string[];
  training_profiles?: number;
  training_platforms?: number;
};
export type ProfileClimatology = {
  profile_id: string;
  revision_sha256: string;
  status: string;
  release_id: string | null;
  calculation_id: string | null;
  fitting_period: ReferenceSummary["fitting_period"] | null;
  dataset_baseline: ReferenceSummary["fitting_period"] | null;
  result: null | {
    status: string;
    supported_pairs: number;
    spread_interpretation: string;
    rows: {
      depth_m: number;
      temperature_c: ComparedVariable;
      practical_salinity: ComparedVariable;
    }[];
  };
};
