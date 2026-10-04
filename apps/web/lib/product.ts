import type { FieldRelease, FieldEvidence, FieldSample } from "./fields";
import type { AdvisoryState, AdvisorySource } from "./advisories";
import type { Level, Profile } from "./profiles";
import type { ExpectedProfile } from "./expected";
import type { IntervalProfile } from "./uncertainty";
import type { AnomalyProfile } from "./anomaly";
import type { ProfileClimatology } from "./climatology";
export type Place = {
  slug: string;
  name: string;
  latitude: number;
  longitude: number;
  bbox: number[];
};
export type ProductPolicy = {
  as_of: string;
  policy: {
    version: string;
    locations: Place[];
    limitations: string[];
    unavailable_layers: string[];
    export_permissions: Record<string, boolean>;
  };
  accounts_available: boolean;
  notification_delivery_available: boolean;
};
export type Session = {
  account_id: string;
  handle: string;
  notifications_enabled: boolean;
  version: number;
  csrf_token: string;
  expires_at: string;
};
export type SavedObject = {
  id: string;
  kind: string;
  name: string;
  data: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
};
export type Job = {
  id: string;
  kind: "exports" | "reports";
  format: string;
  state: string;
  reason: string | null;
  version: number;
  input: Record<string, unknown>;
  input_sha256: string;
  artifact_sha256: string | null;
  artifact_bytes: number | null;
  created_at: string;
  finished_at: string | null;
  expires_at: string;
};
export type ResearchFilter = {
  bbox: number[];
  start: string;
  end: string;
  min_depth_m: number;
  max_depth_m: number;
  variable: "temperature_c" | "practical_salinity";
  source: "argo_gdac";
  qc: "accepted" | "science_ready";
  data_mode?: string;
  minimum_anomaly_percentile?: number;
  event_id?: string;
  polygon?: number[][];
  limit: number;
  cursor?: string;
};
export type ResearchRow = {
  id: string;
  revision_sha256: string;
  platform_id: string;
  observed_at: string;
  received_at: string;
  latitude: number;
  longitude: number;
  data_mode: string;
  qc_version: string;
  source_id: string;
  calculation_id: string | null;
  raw_sha256: string;
  source_url: string;
  levels: Level[];
  level_count: number;
  minimum: number | null;
  maximum: number | null;
  anomaly_percentile: number | null;
  anomaly_calculation_id: string | null;
  anomaly_state: string | null;
};
export type ResearchResult = {
  items: ResearchRow[];
  query: ResearchFilter;
  snapshot_at: string;
  next_cursor: string | null;
  units: string;
  method_version: string;
  limitations: string[];
};
export type ProfileBundle = {
  profile: Profile | null;
  climatology: ProfileClimatology | null;
  expected: ExpectedProfile | null;
  uncertainty: IntervalProfile | null;
  anomaly: AnomalyProfile | null;
};
export type Nearby = {
  profile_id: string;
  platform_id: string;
  revision_sha256: string;
  observed_at: string;
  received_at: string;
  latitude: number;
  longitude: number;
  distance_km: number;
  calculation_id: string | null;
  qc_version: string;
  data_mode: string;
};
export type Conditions = {
  requested_point: { latitude: number; longitude: number };
  requested_time: string;
  as_of: string;
  nearby_profiles: Nearby[];
  fields: {
    product_id: string;
    variable: string;
    release_id: string;
    manifest_sha256: string;
    cycle: string | null;
    state: string;
    timeline: (
      | FieldEvidence<FieldSample>
      | { status: string; requested_time: string; reason: string }
    )[];
  }[];
  advisory: AdvisoryState;
  limitations: string[];
  confidence: { state: string; reason: string };
  expected_at_point: { state: string; reason: string };
};
export type MapEvent = {
  event_id: string;
  kind: string;
  start: string;
  end: string;
  geometry: { type: string; coordinates: unknown };
  run_id: string;
  report_sha256: string;
  calculation_id: string;
};
export type MapOverview = {
  as_of: string;
  bbox: number[];
  start: string;
  end: string;
  profiles: {
    id: string;
    revision_sha256: string;
    latitude: number;
    longitude: number;
    observed_at: string;
    platform_id: string;
  }[];
  fields: FieldRelease[];
  events: MapEvent[];
  event_state: string;
  advisory_polygons: {
    revision_id: string;
    event: string;
    severity: string;
    effective: string;
    expires: string | null;
    geometry: { type: string; coordinates: unknown };
  }[];
  advisory_sources: AdvisorySource[];
  advisory_circles?: {
    revision_id: string;
    event: string;
    severity: string;
    effective: string;
    expires: string | null;
    circle: { center: number[]; radius_km: number };
  }[];
  advisory_state: string;
  unavailable_layers: string[];
  limitations: string[];
};
export type { AskPlan as QueryPlan } from "./ask-types";
export async function publicQuery<T>(
  action: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api/explore/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.code ?? "evidence_unavailable");
  return data as T;
}
const pendingKeys = new Map<string, string>();
export function clearPrivateRequests(accountId: string) {
  for (const key of pendingKeys.keys())
    if (key.startsWith(accountId + ":")) pendingKeys.delete(key);
}
export async function privateQuery<T>(
  path: string,
  session: Session,
  method = "GET",
  body?: unknown,
  version?: number,
  key?: string,
): Promise<T> {
  const payload = body === undefined ? undefined : JSON.stringify(body);
  const identity = `${session.account_id}:${method}:${path}:${version ?? ""}:${payload ?? ""}`;
  const headers: Record<string, string> = {
    "X-CSRF-Token": session.csrf_token,
    "X-Account-Scope": session.account_id,
  };
  if (method !== "GET") {
    if (!key) {
      key = pendingKeys.get(identity) ?? crypto.randomUUID();
      pendingKeys.set(identity, key);
      if (pendingKeys.size > 128)
        pendingKeys.delete(pendingKeys.keys().next().value!);
    }
    headers["Idempotency-Key"] = key;
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (version !== undefined) headers["If-Match"] = `"${version}"`;
  }
  const response = await fetch(`/api/product/${path}`, {
    method,
    headers,
    body: payload,
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status < 500) pendingKeys.delete(identity);
    throw Error(
      response.status === 401
        ? "session_expired"
        : (data.code ?? "saved_state_unavailable"),
    );
  }
  pendingKeys.delete(identity);
  return data as T;
}
