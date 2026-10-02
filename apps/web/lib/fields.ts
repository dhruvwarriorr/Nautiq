export type FieldMetadata = {
  product_id: string; provider: string; product: string; kind: "analysis" | "forecast";
  cycle: string | null; times: string[]; valid_time_start: string; valid_time_end: string;
  attribution: string; documentation: string; extent: number[];
  resolution: {longitude_degrees: number; latitude_degrees: number}; shape: number[];
  variables: string[]; derived_variables: string[];
  variable_metadata: Record<string, {label: string; units: string; colors: number[]; direction?: string}>;
  mask_counts: Record<string, number>; limitations: string[];
};
export type FieldRelease = {
  release_id: string; product_id: string; calculation_id: string; metadata: FieldMetadata;
  cycle: string | null; selected: boolean; freshness: string; source_version: string;
  created_at: string; status: string; release_approved: false; manifest_sha256: string;
  manifest?: {raw: {url: string; sha256: string; bytes: number}[]; code_sha256: string; policy_sha256: string};
};
export type FieldSample = {
  latitude: number; longitude: number; requested_time: string; value: number | null;
  units: string; status: string; reason: string | null; source_distance_km: number | null;
  spatial_support: {latitude: number; longitude: number; weight: number}[];
  temporal_support: {valid_time: string; weight: number}[];
};
export type FieldEvidence<T> = {release_id: string; metadata: FieldMetadata; freshness: string; variable: string; result: T};
export type FieldRoute = {status: string; available_fraction: number; sampled_minimum: number | null; sampled_maximum: number | null; samples: FieldSample[]; sampling: {sample_count: number; distance_km: number}; assessment: "not_assessed"};
export const fieldNumber = (n: number | null | undefined) => n == null ? "Unavailable" : n.toLocaleString("en", {maximumFractionDigits: 3});
