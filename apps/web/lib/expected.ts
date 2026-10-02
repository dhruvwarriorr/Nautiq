export type ModelMetric = {
  rows: number;
  profiles: number;
  mae: number | null;
  rmse: number | null;
  median_absolute_error: number | null;
  bias: number | null;
  profile_weighted_mae: number | null;
  profile_bootstrap_mae_95: [number, number] | null;
};
export type Promotion = {
  eligible: boolean;
  active_method: string;
  reasons: string[];
  subgroup_checks?: {
    group: string;
    profiles: number;
    adequate: boolean;
    regressed: boolean;
  }[];
};
export type ModelSummary = {
  release_id: string;
  reference_id: string;
  snapshot_id: string;
  calculation_id: string;
  status: string;
  selected: boolean;
  model_count: number;
  active_methods: Record<string, string>;
  fitting_period: { start_year: number; end_year: number };
  release_approved: false;
};
export type ModelReport = {
  variables: Record<
    string,
    {
      status: string;
      reason?: string;
      promotion: Promotion;
      profile_counts: Record<string, number>;
      missing_or_unsupported_rows?: number;
      selected?: Record<
        string,
        {
          leaves: number;
          tuning_profile_weighted_mae: number;
          parameters: Record<string, unknown>;
        }
      >;
      evaluation?: Record<string, Record<string, Record<string, ModelMetric>>>;
    }
  >;
  independence_audits: {
    kind: string;
    fold: string;
    complement_profiles: number;
    held_profiles: number;
    reference_fit_hash: string;
    variables: Record<
      string,
      {
        status: string;
        reason?: string;
        held_candidate_rows?: number;
        held_supported_rows?: number;
        held_evaluation?: ModelMetric;
        held_comparison?: Record<string, ModelMetric>;
      }
    >;
  }[];
  feature_schema: {
    version: string;
    names: string[];
    omitted_static_features: string[];
    reason: string;
  };
  bootstrap_limitations: string;
  source_git_commit: string;
  code_sha256: string;
};
export type ModelRelease = ModelSummary & {
  manifest: {
    output: ModelSummary & { bundle_sha256: string; report_sha256: string };
  };
  report: ModelReport;
  tracking: null | {
    run_id: string;
    registered_model: string;
    model_version: string;
  };
};
export type ExpectedPoint = {
  observed: number | null;
  expected_mean: number | null;
  climatology_mean: number | null;
  candidate_mean: number | null;
  candidate_residual: number | null;
  ml_residual: number | null;
  active_method: string;
  reason: string | null;
  candidate_reason: string | null;
  difference: number | null;
  direction: string;
  promotion_reasons: string[];
  feature_contributions: { feature: string; contribution: number }[];
  contribution_bias: number | null;
};
export type ExpectedProfile = {
  profile_id: string;
  revision_sha256: string;
  release_id: string | null;
  reference_id: string | null;
  calculation_id: string | null;
  status: string;
  pending_reason: string | null;
  active_methods: Record<string, string> | null;
  fitting_period: ModelSummary["fitting_period"] | null;
  result: null | {
    status: string;
    supported_pairs: number;
    interval_status: string;
    explanation_interpretation: string;
    rows: {
      depth_m: number;
      temperature_c: ExpectedPoint;
      practical_salinity: ExpectedPoint;
    }[];
  };
};
