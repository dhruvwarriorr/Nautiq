export const dependencyNames = ["postgresql", "postgis", "timescaledb", "schema", "minio", "redis", "nats_jetstream", "ml_inference", "field_service", "web"];

export function validateReport(value) {
  if (!value || !["healthy", "degraded"].includes(value.status) || typeof value.checked_at !== "string" || !Number.isFinite(Date.parse(value.checked_at))) throw new Error("Invalid health report");
  for (const name of dependencyNames) {
    if (!["healthy", "unavailable"].includes(value.dependencies?.[name]?.status)) throw new Error("Incomplete health report");
  }
  if (value.status === "healthy" && dependencyNames.some((name) => value.dependencies[name].status !== "healthy")) throw new Error("Inconsistent health report");
  return value;
}
