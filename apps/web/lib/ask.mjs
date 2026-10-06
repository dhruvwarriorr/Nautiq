// Pure helpers for the Ask experience. Kept framework-free so node --test can exercise them.
export const intentLabels = {
  conditions: "Sea conditions",
  events: "Regional events",
  research: "Observed profiles",
  trip: "Trip planning",
  explain: "Explanation",
  unsupported: "Not supported",
};
export const whenOptions = [
  ["now", "Now (next 24 hours)"],
  ["today", "Today"],
  ["tonight", "Tonight"],
  ["tomorrow", "Tomorrow"],
  ["tomorrow_morning", "Tomorrow morning"],
  ["tomorrow_afternoon", "Tomorrow afternoon"],
  ["tomorrow_evening", "Tomorrow evening"],
  ["this_week", "This week"],
  ["last_week", "Last week"],
  ["last_7_days", "Last 7 days"],
  ["last_30_days", "Last 30 days"],
  ["this_month", "This month"],
  ["last_month", "Last month"],
];
export const topicOptions = [
  ["caution", "Why a trip shows caution or insufficient data"],
  ["insufficient", "What “insufficient data” means"],
  ["unusual", "What an unusual profile means"],
  ["expected", "What “expected normal” means"],
  ["interval", "What an expected interval means"],
  ["freshness", "What stale data means"],
  ["model", "How the model is used, and its limits"],
  ["evidence", "What the evidence shows"],
  ["personal_limits", "How your own trip limits work"],
];
export const statusLabels = {
  available: ["✓", "Available"],
  stale: ["⏱", "Stale"],
  unknown: ["?", "Unknown"],
  unavailable: ["–", "Unavailable"],
};
export const exampleQuestions = [
  "How are the waves near Goa tomorrow morning?",
  "What is the wind near Kerala tonight?",
  "Show unusual temperature profiles in the Arabian Sea this week",
  "Compare salinity near Kerala in October",
  "Why is Nautiq showing caution?",
  "Is it a good time to go fishing near Mumbai tomorrow?",
];

const pad = (n) => String(n).padStart(2, "0");
function local(iso, zone) {
  const d = new Date(iso);
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: zone,
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(d);
  } catch {
    return iso;
  }
}
// "Tue 6 Oct, 06:00 → 12:00 (Asia/Kolkata) = 00:30–06:30 UTC"
export function describeWindow(window) {
  if (!window) return "";
  const a = new Date(window.start);
  const b = new Date(window.end);
  const utc = (d) => `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  const day = (d) => d.toISOString().slice(0, 10);
  const sameUtcDay = day(a) === day(b);
  const utcText = sameUtcDay
    ? `${day(a)} ${utc(a)}–${utc(b)} UTC`
    : `${day(a)} ${utc(a)} → ${day(b)} ${utc(b)} UTC`;
  return `${local(window.start, window.time_zone)} → ${local(window.end, window.time_zone)} (${window.time_zone}) = ${utcText}`;
}
// Replace the time part of a frame without keeping stale resolved instants.
export function withWhen(frame, when) {
  const { start, end, ...rest } = frame;
  void start;
  void end;
  return { ...rest, when };
}
export function withDates(frame, start, end) {
  const { when, ...rest } = frame;
  void when;
  return { ...rest, start, end };
}
export function withPlace(frame, place) {
  return { ...frame, place };
}
export function ageText(iso, now = Date.now()) {
  const minutes = Math.max(0, Math.round((now - Date.parse(iso)) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}
export function browserZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
