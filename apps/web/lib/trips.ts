export type TripPoint = { latitude: number; longitude: number; time: string };
export type TripRequest = {
  activity: string;
  threshold_version: string;
  waypoints: TripPoint[];
  fields: { variable: string; release_id: string }[];
  spacing_km: number;
  step_minutes: number;
  preferences: Record<string, never>;
};
export type TripPolicy = {
  policy: {
    version: string;
    approved: boolean;
    review_record: string;
    activities: string[];
    inputs: {
      variable: string;
      product_id: string;
      units: string;
      required: boolean;
      caution: number | null;
      critical: number | null;
    }[];
    limitations: string[];
  };
  engine_available: boolean;
  as_of: string;
};
export type TripVerdict = {
  status: string;
  engine_available: boolean;
  rules_fired: {
    rule_id: string;
    verdict: string;
    variable: string;
    origin: string;
    value: number | null;
    limit: number | null;
    units: string;
    point: TripPoint | null;
    evidence: string;
  }[];
  worst_samples: {
    variable: string;
    value: number;
    units: string;
    point: TripPoint;
    sample_status: string;
  }[];
  missing_inputs: string[];
  source_cycles: {
    variable: string;
    release_id: string;
    cycle: string | null;
    manifest_sha256: string;
    evidence_sha256: string;
  }[];
  threshold_version: string;
  method_version: string;
  as_of: string;
  sampling: {
    sample_count: number;
    spacing_km: number;
    step_minutes: number;
    distance_km: number;
  };
  wording: string;
  limitations: string[];
  production_approved: boolean;
};
export type TripResult = {
  calculation_id: string;
  access_token: string;
  manifest_sha256: string;
  verdict: TripVerdict;
};
