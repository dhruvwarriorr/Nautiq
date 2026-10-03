"use client";
import { useRef, useState, useEffect } from "react";
import Link from "next/link";
import type { ProfileBundle } from "../../lib/product";
import ProfileChart from "./ProfileChart";
import Climatology from "../profiles/[id]/Climatology";
import Expected from "../profiles/[id]/ExpectedState";
import Uncertainty from "../profiles/[id]/Uncertainty";
import Anomaly from "../profiles/[id]/Anomaly";
export default function ProfilePanels({ id }: { id: string }) {
  const [value, setValue] = useState<ProfileBundle | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const control = useRef<AbortController | null>(null);
  useEffect(() => () => control.current?.abort(), []);
  async function load() {
    control.current?.abort();
    const c = new AbortController();
    control.current = c;
    setBusy(true);
    setValue(null);
    setError("");
    try {
      const response = await fetch(
        `/api/explore/profile?id=${encodeURIComponent(id)}`,
        { signal: c.signal, cache: "no-store" },
      );
      if (!response.ok)
        throw Error("The profile evidence could not be loaded.");
      const data = (await response.json()) as ProfileBundle;
      if (!c.signal.aborted) setValue(data);
    } catch (e) {
      if (!c.signal.aborted)
        setError(e instanceof Error ? e.message : "Profile unavailable.");
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  const p = value?.profile;
  return (
    <section className="field-viewer">
      <button disabled={busy} onClick={() => void load()}>
        {busy
          ? "Loading profile evidence…"
          : value
            ? "Reload measured profile and references"
            : "Load measured profile and references"}
      </button>
      {error ? (
        <p role="status" className="notice">
          {error}
        </p>
      ) : null}
      {p ? (
        <>
          <p>
            Argo {p.platform_id} · {p.latitude.toFixed(4)},{" "}
            {p.longitude.toFixed(4)} · observed {p.observed_at}. These values
            belong to this instrument position and recorded depths.
          </p>
          <div className="charts">
            <ProfileChart
              levels={p.levels}
              variable="temperature_c"
              label="Observed temperature"
              unit="°C"
            />
            <ProfileChart
              levels={p.levels}
              variable="practical_salinity"
              label="Observed practical salinity"
              unit="PSS-78"
            />
          </div>
          <Climatology value={value.climatology} revision={p.revision_sha256} />
          <Expected value={value.expected} revision={p.revision_sha256} />
          <Uncertainty value={value.uncertainty} revision={p.revision_sha256} />
          <Anomaly value={value.anomaly} revision={p.revision_sha256} />
          {value.anomaly?.revision_sha256 === p.revision_sha256 &&
          value.anomaly.result ? (
            <>
              <h3>Residual depth heatmap</h3>
              <p>
                Standardized residuals are dimensionless diagnostic values.
                Missing support remains blank; color is accompanied by numeric
                evidence.
              </p>
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="Residual depth evidence"
              >
                <table>
                  <thead>
                    <tr>
                      <th>Variable</th>
                      <th>Depth (m)</th>
                      <th>Observed minus expected</th>
                      <th>Standardized residual</th>
                      <th>Support</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(value.anomaly.result.variables).flatMap(
                      ([variable, entry]) =>
                        entry.points.map((point) => (
                          <tr key={`${variable}-${point.depth_m}`}>
                            <td>{variable}</td>
                            <td>{point.depth_m}</td>
                            <td>
                              {point.residual?.toFixed(3) ?? "Unavailable"}{" "}
                              {variable === "temperature_c" ? "°C" : "PSS-78"}
                            </td>
                            <td
                              style={{
                                background:
                                  point.standardized_residual == null
                                    ? "#eef2ea"
                                    : point.standardized_residual >= 0
                                      ? "#f1d7c2"
                                      : "#d4e6ef",
                              }}
                            >
                              {point.standardized_residual?.toFixed(3) ??
                                "Unavailable"}
                            </td>
                            <td>
                              {point.reason ?? "Matching diagnostic support"}
                            </td>
                          </tr>
                        )),
                    )}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
          <Link href={`/profiles/${p.id}`}>
            Original levels, QC, source and exact calculation evidence →
          </Link>
        </>
      ) : value ? (
        <p className="notice">
          The original profile is unavailable; reference values cannot
          substitute for its observation.
        </p>
      ) : null}
    </section>
  );
}
