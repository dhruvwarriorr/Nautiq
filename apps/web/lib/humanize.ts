// Presentation layer: turns machine values (ISO instants, source ids, snake_case states,
// digests, SI units) into words people read. Public views render through these helpers;
// raw values stay available behind "technical detail" disclosures.
import type { Fact } from "./ask-types";

/** Nautiq's operating geography is India, so public times read in India Standard Time. */
export const DISPLAY_ZONE = "Asia/Kolkata";
export const ZONE_LABEL = "IST";

const STAMP = /(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?\s*(?:Z|UTC|[+-]00:?00)?(?:\s*UTC)?/g;

/** Parses an ISO instant or the API's "YYYY-MM-DD HH:MM UTC" style. Bare dates read as UTC midnight. */
export function instant(value: string | null | undefined): Date | null {
  if (!value) return null;
  const text = value.trim();
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)\s*(Z|UTC|[+-]\d{2}:?\d{2})?$/.exec(text);
  let ms: number;
  if (m) {
    const zone = !m[3] || m[3] === "UTC" ? "Z" : m[3];
    ms = Date.parse(`${m[1]}T${m[2].slice(0, 12)}${zone}`);
  } else if (/^\d{4}-\d{2}-\d{2}$/.test(text)) ms = Date.parse(`${text}T00:00:00Z`);
  else ms = Date.parse(text);
  return Number.isFinite(ms) ? new Date(ms) : null;
}

function parts(d: Date) {
  const f = new Intl.DateTimeFormat("en-GB", {
    timeZone: DISPLAY_ZONE,
    year: "numeric",
    month: "short",
    day: "numeric",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).formatToParts(d);
  const get = (t: string) => f.find((p) => p.type === t)?.value ?? "";
  return {
    year: get("year"),
    month: get("month"),
    day: get("day"),
    weekday: get("weekday"),
    time: `${get("hour")}:${get("minute")} ${get("dayPeriod").toLowerCase()}`.replace(":00 ", " "),
  };
}
const dayKey = (d: Date) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: DISPLAY_ZONE }).format(d);

function dayWord(d: Date, now: Date): string | null {
  const diff = Math.round(
    (Date.parse(dayKey(d)) - Date.parse(dayKey(now))) / 86400000,
  );
  return diff === 0 ? "today" : diff === -1 ? "yesterday" : diff === 1 ? "tomorrow" : null;
}

/** "10:02 am today", "11:30 pm yesterday", "Sat 3 Oct, 6 am", "3 Oct 2025". */
export function when(value: string | Date | null | undefined, now = new Date()): string {
  const d = value instanceof Date ? value : instant(value ?? null);
  if (!d) return "an unknown time";
  const p = parts(d);
  const word = dayWord(d, now);
  if (word) return `${p.time} ${word}`;
  const sameYear = p.year === parts(now).year;
  return sameYear ? `${p.weekday} ${p.day} ${p.month}, ${p.time}` : `${p.day} ${p.month} ${p.year}`;
}

/** Day only: "today", "Sat 3 Oct", "3 Oct 2025". */
export function day(value: string | Date | null | undefined, now = new Date()): string {
  const d = value instanceof Date ? value : instant(value ?? null);
  if (!d) return "an unknown day";
  const word = dayWord(d, now);
  if (word) return word;
  const p = parts(d);
  return p.year === parts(now).year ? `${p.weekday} ${p.day} ${p.month}` : `${p.day} ${p.month} ${p.year}`;
}

/** "just now", "12 min ago", "3 hours ago", "in 2 days". */
export function ago(value: string | Date | null | undefined, now = new Date()): string {
  const d = value instanceof Date ? value : instant(value ?? null);
  if (!d) return "never";
  const minutes = Math.round((now.getTime() - d.getTime()) / 60000);
  const future = minutes < 0;
  const m = Math.abs(minutes);
  let text: string;
  if (m < 1) return "just now";
  if (m < 60) text = `${m} min`;
  else if (m < 60 * 36) text = `${Math.round(m / 60)} hour${Math.round(m / 60) === 1 ? "" : "s"}`;
  else text = `${Math.round(m / 1440)} days`;
  return future ? `in ${text}` : `${text} ago`;
}

/** A date range in words: "1 Oct – 4 Oct", "last 12 months". */
export function span(start: string, end: string, now = new Date()): string {
  const a = instant(start), b = instant(end);
  if (!a || !b) return "an unknown period";
  const days = Math.round((b.getTime() - a.getTime()) / 86400000);
  const endsNow = Math.abs(now.getTime() - b.getTime()) < 2 * 86400000;
  if (endsNow && days >= 360 && days <= 370) return "the last 12 months";
  if (endsNow && days >= 28 && days <= 31) return "the last 30 days";
  if (endsNow && days === 7) return "the last 7 days";
  return `${day(a, now)} – ${day(b, now)}`;
}

/** Rewrites every machine timestamp inside free text into friendly local time. */
export function humanizeText(text: string, now = new Date()): string {
  return text
    .replace(STAMP, (match) => {
      const d = instant(match.replace(/\s*UTC$/, "Z").replace(" ", "T"));
      return d ? when(d, now) : match;
    })
    .replace(/\bm s-1\b/g, "m/s")
    .replace(/\bdegree_Celsius\b/g, "°C");
}

const labels: Record<string, string> = {
  favorable: "Within your limits",
  caution: "Take care",
  unfavorable: "Too rough",
  unknown: "Unknown",
  available: "Available",
  unavailable: "Unavailable",
  stale: "Out of date",
  stale_or_incomplete: "Out of date or incomplete",
  unconfigured: "Not connected",
  healthy: "Reachable",
  ready: "Ready",
  active: "Active",
  expired: "Expired",
  cancelled: "Cancelled",
  superseded: "Replaced by a newer message",
  historical_diagnostics: "Past diagnostics only",
  profile_groups: "Groups of unusual floats",
  warm_event: "Warm-water event",
  sst_warm_event: "Warm-water event",
  insufficient_data: "Not enough data",
  not_assessed: "Not assessed",
  not_assessable: "Can’t be assessed",
  strongly_unusual: "Strongly unusual",
  typical: "Typical",
  elevated: "Slightly unusual",
  unusual: "Unusual",
  accepted: "Accepted",
  science_ready: "Science-ready",
  succeeded: "Done",
  failed: "Failed",
  queued: "Waiting",
  running: "Working",
  pending: "Waiting",
  buoy_observations: "Buoy observations",
  operational_sst_anomaly: "Live sea-temperature anomaly",
  operational_profile_anomaly: "Live unusual-float alerts",
  validated_confidence: "Validated confidence",
  visibility: "Visibility",
  tides: "Tides",
};
/** Sentence-case words for a machine state or enum. */
export function label(value: string | null | undefined): string {
  if (!value) return "Unknown";
  if (labels[value]) return labels[value];
  const words = value.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase();
}

const sources: Record<string, string> = {
  cmems_wave: "Copernicus Marine wave forecast",
  cmems_currents: "Copernicus Marine current forecast",
  cmems_sst: "Copernicus Marine sea-temperature forecast",
  noaa_oisst: "NOAA daily sea temperature",
  noaa_gfs_wave: "NOAA wave forecast",
  noaa_gfs_weather: "NOAA wind & weather forecast",
  hycom_espc: "HYCOM ocean-current forecast",
  argo_gdac: "Argo float network",
};
export function sourceName(id: string | null | undefined): string {
  return id ? (sources[id] ?? label(id)) : "Unknown source";
}

const senders: Record<string, string> = {
  CWC: "Central Water Commission",
  IMD: "India Meteorological Department",
  INCOIS: "INCOIS",
  NDMA: "National Disaster Management Authority",
};
/** Expands agency short names: "Assam-SDMA" → "Assam disaster authority". */
export function sender(name: string): string {
  if (senders[name]) return senders[name];
  const sdma = /^(.+?)[- ]SDMA$/i.exec(name);
  if (sdma) return `${sdma[1]} disaster authority`;
  const imd = /^IMD[- ]?(.+)$/i.exec(name);
  if (imd) return `IMD ${imd[1]}`;
  return name;
}

/** "5.81° N, 71.06° E" */
export function coords(lat: number, lon: number, digits = 2): string {
  const ns = lat >= 0 ? "N" : "S", ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(digits)}° ${ns}, ${Math.abs(lon).toFixed(digits)}° ${ew}`;
}

export function unit(u: string | null | undefined): string {
  if (!u) return "";
  return ({ "m s-1": "m/s", degree_Celsius: "°C", degree: "°", Pa: "Pa" } as Record<string, string>)[u] ?? u;
}

/** Rounds a reading to what a person would say aloud. */
export function reading(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "";
  return value.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export const knots = (ms: number) => ms * 1.943844;

/** Beaufort description of a wind speed (descriptive scale, not a safety judgement). */
export function beaufort(ms: number): string {
  const limits: [number, string][] = [
    [0.5, "Calm"], [1.6, "Light air"], [3.4, "Light breeze"], [5.5, "Gentle breeze"],
    [8, "Moderate breeze"], [10.8, "Fresh breeze"], [13.9, "Strong breeze"], [17.2, "Near gale"],
    [20.8, "Gale"], [24.5, "Strong gale"], [28.5, "Storm"], [32.7, "Violent storm"],
  ];
  return limits.find(([max]) => ms < max)?.[1] ?? "Hurricane force";
}

/** WMO sea-state description of a significant wave height (descriptive, not a safety judgement). */
export function seaState(m: number): string {
  const limits: [number, string][] = [
    [0.05, "Glassy calm"], [0.1, "Rippled"], [0.5, "Smooth"], [1.25, "Slight"],
    [2.5, "Moderate"], [4, "Rough"], [6, "Very rough"], [9, "High"], [14, "Very high"],
  ];
  return limits.find(([max]) => m < max)?.[1] ?? "Phenomenal";
}

/** First characters of a digest, for technical views only. */
export const short = (hash: string | null | undefined, n = 8) => (hash ? hash.slice(0, n) : "—");

/** Fact statuses plus "warning", which marks a trip that is too rough for your limits. */
export type Status = Fact["status"] | "warning";
export const statusWord: Record<Status, string> = {
  available: "Available",
  stale: "Out of date",
  unknown: "Unknown",
  unavailable: "Not available",
  warning: "Too rough",
};

export type Measure = "waves" | "wind" | "current" | "sst" | "float" | "normal" | "other";
export type Reading = {
  measure: Measure;
  title: string;
  status: Status;
  /** Big number with unit, e.g. "0.6 m"; empty when unavailable. */
  value: string;
  /** Plain descriptor, e.g. "Smooth sea" or "Light air". */
  descriptor: string;
  /** "Forecast for 10:02 am today". */
  time: string;
  /** Extra one-liner, e.g. "Up to 0.6 m in the next 12 hours". */
  outlook: string;
  /** Plain-language explanation of the source or the gap. */
  note: string;
  href?: string;
  raw: Fact;
};

function measureOf(labelText: string): Measure {
  const l = labelText.toLowerCase();
  if (l.includes("sea surface temperature") || l.includes("temperature")) return "sst";
  if (l.includes("wave")) return "waves";
  if (l.includes("wind")) return "wind";
  if (l.includes("current")) return "current";
  if (l.includes("observation") || l.includes("profile") || l.includes("float")) return "float";
  if (l.includes("normal")) return "normal";
  return "other";
}
const titles: Record<Measure, string> = {
  waves: "Waves",
  wind: "Wind",
  current: "Current",
  sst: "Sea temperature",
  float: "Nearest float",
  normal: "Compared with normal",
  other: "",
};

function tidyNote(detail: string | undefined, now: Date): string {
  if (!detail) return "";
  let t = detail
    .replace(/Source: no forecast cycle \(analysis\)\./g, "")
    .replace(/Source: forecast cycle (.+? UTC)\./g, (_, c) => `Latest forecast was issued ${c}.`)
    .replace(/forecast cycle (.+? UTC)\./gi, (_, c) => `Forecast issued ${c}.`)
    .replace(/Sampled at the place’s catalog point, not an average of the area\./g, "Read at one point offshore, not averaged over the area.")
    .replace(/A validated way to place a profile’s expected normal at an arbitrary point does not exist yet; expected-normal evidence is shown per Argo profile\./g, "There’s no proven way yet to estimate the normal at any point, so it’s shown for each float instead.")
    .replace(/the newest retained daily analysis does not cover this time \(analyses are published with a delay\)\./g, "Today’s satellite analysis isn’t published yet; it usually arrives a day late.")
    .replace(/the time is outside the retained forecast\./g, "The forecast we hold doesn’t reach this time.")
    .replace(/\bretained\b/g, "stored");
  t = humanizeText(t, now).trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : "";
}

/** Parses an answer fact into a reading a person can scan. Values outside the known patterns pass through humanized. */
export function toReading(fact: Fact, now = new Date()): Reading {
  const measure = measureOf(fact.label);
  const kind = /\((forecast|daily analysis)\)/i.exec(fact.label)?.[1]?.toLowerCase();
  const base: Reading = {
    measure,
    title: titles[measure] || fact.label,
    status: fact.status,
    value: "",
    descriptor: "",
    time: "",
    outlook: "",
    note: tidyNote(fact.detail, now),
    href: fact.href,
    raw: fact,
  };
  const m = /^(-?[\d.]+)\s*(m\/s|m|°C|degree_Celsius|m s-1)\s+at\s+(.+?UTC)(?:\s*\(highest of \d+ samples over (\d+) h: (-?[\d.]+)\s*[^)]*\))?/.exec(fact.value);
  if (m) {
    const v = Number(m[1]);
    const peak = m[5] ? Number(m[5]) : null;
    const at = instant(m[3]);
    const lead = kind === "daily analysis" ? "Analysis for" : "Forecast for";
    base.time = at ? `${lead} ${when(at, now)}` : "";
    const hours = m[4];
    if (measure === "wind" || measure === "current") {
      base.value = `${reading(knots(v), knots(v) < 10 ? 1 : 0)} kn`;
      base.descriptor = measure === "wind" ? beaufort(v) : `${reading(v, 2)} m/s`;
      if (peak != null && hours) base.outlook = `Up to ${reading(knots(peak), 0)} kn in the next ${hours} hours`;
    } else if (measure === "waves") {
      base.value = `${reading(v, 1)} m`;
      base.descriptor = `${seaState(v)} sea`;
      if (peak != null && hours) base.outlook = `Up to ${reading(peak, 1)} m in the next ${hours} hours`;
    } else {
      base.value = `${reading(v, 1)} ${unit(m[2])}`;
      if (peak != null && hours) base.outlook = `Up to ${reading(peak, 1)} ${unit(m[2])} in the next ${hours} hours`;
    }
    return base;
  }
  const latest = /^(-?[\d.]+)\s*(°C|degree_Celsius)\s+on\s+(\d{4}-\d{2}-\d{2})\s+\(latest daily analysis\)/.exec(fact.value);
  if (latest) {
    const at = instant(`${latest[3]} 12:00 UTC`);
    base.value = `${reading(Number(latest[1]), 1)} ${unit(latest[2])}`;
    // A daily analysis has no meaningful time of day, so show only its date.
    base.time = `Latest daily analysis, ${at ? at.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" }) : latest[3]}`;
    return base;
  }
  if (fact.status === "unavailable" && /^unavailable$/i.test(fact.value.trim())) return base;
  base.descriptor = humanizeText(
    fact.value
      .replace(/^Unknown\. This is not an all-clear\.$/, "Unknown — not an all-clear")
      .replace(/^No accepted Argo profile within 100 km in retained data\.$/, "No float within 100 km")
      .replace(/^Not available at this point\.$/, "Not available here"),
    now,
  );
  return base;
}

/** Splits an API "Why: a; b; c." explanation into separate plain reasons. */
export function reasons(note: string): string[] {
  const why = /Why:\s*(.+)$/.exec(note)?.[1];
  if (!why) return [];
  return why
    .replace(/\.$/, "")
    .split(/;\s*/)
    .map((r) => r.charAt(0).toUpperCase() + r.slice(1));
}

/** Headline from the answer service, softened: "2 of 4 sea-state measures are available for X." */
export function headline(text: string): string {
  const m = /^(\d+) of (\d+) sea-state measures are available for (.+)\.$/.exec(text);
  if (m) return m[1] === m[2] ? `All ${m[2]} readings are in for ${m[3]}.` : `${m[1]} of ${m[2]} readings are in for ${m[3]} right now.`;
  const none = /^No usable forecast values for (.+) at the chosen time\.$/.exec(text);
  if (none) return `No forecast readings for ${none[1]} at that time yet.`;
  return humanizeText(text);
}
