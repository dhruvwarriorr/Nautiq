export type AdvisoryArea = {
  description: string;
  polygons: { type: string; coordinates: number[][][] }[];
  circles: { center: number[]; radius_km: number }[];
  unresolved: string[];
  geocodes: { name: string; value: string }[];
};
export type AdvisoryInfo = {
  language: string;
  event: string;
  severity: string;
  urgency: string;
  certainty: string;
  effective: string;
  onset: string | null;
  expires: string | null;
  headline: string;
  description: string;
  instruction: string;
  web: string;
  issues: string[];
  areas: AdvisoryArea[];
};
export type Bulletin = {
  message: {
    revision_id: string;
    identifier: string;
    sender: string;
    sent: string;
    source_id: string;
    msgType: string;
    status: string;
    scope: string;
    operational: boolean;
    issues: string[];
    infos: AdvisoryInfo[];
    references: { sender: string; identifier: string; sent: string }[];
  };
  lifecycle: { state: string; issues: string[]; replaced_by: string[] };
  raw_sha256: string;
  source_url: string;
  first_run_id: string;
};
export type AdvisorySource = {
  source_id: string;
  policy: { authority: string; url: string | null; required: boolean };
  transport: string;
  checked_at: string | null;
  age_seconds: number | null;
  coverage: string;
  integrity: string;
  run_id: string | null;
};
export type AdvisorySnapshot = {
  as_of: string;
  sources: AdvisorySource[];
  items: Bulletin[];
  issues: string[];
  production_approved: false;
};
export type AdvisoryState = {
  status: "unknown" | "official_warning" | "known_none_intersecting";
  warnings: {
    revision_id: string;
    event: string;
    severity: string;
    effective: string;
    expires: string | null;
  }[];
  unknown_reasons: string[];
  as_of: string;
};
