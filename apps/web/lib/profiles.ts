export type Summary = {
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
};
export type Level = {
  pressure_dbar: number;
  depth_m: number;
  temperature_c: number | null;
  practical_salinity: number | null;
  missing_reasons: Record<string, string>;
  qc_flags: Record<string, string>;
};
export type Profile = Summary & {
  levels: Level[];
  provenance: {
    calculation_id: string | null;
    raw_sha256: string;
    source_url: string;
    depth_conversion_version: string;
    normalizer_version: string;
    parquet_sha256: string;
    parquet_key: string;
    source_updated_at: string;
    attribution: string;
    cycle_number: number;
    direction: string;
    sampling_scheme: string;
    parameter_modes: Record<string, string>;
  };
};
export type Page = {
  items: Summary[];
  next_cursor: string | null;
  snapshot_at: string;
};
export const apiURL = process.env.API_INTERNAL_URL ?? "http://localhost:8080";

export async function observationWindow() {
  const now = Date.now();
  return {
    start: new Date(now - 365 * 86400000).toISOString().slice(0, 10),
    end: new Date(now + 86400000).toISOString().slice(0, 10),
  };
}
