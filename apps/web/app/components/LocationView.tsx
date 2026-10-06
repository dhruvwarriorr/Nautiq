"use client";
import { useRef, useState, useEffect } from "react";
import Link from "next/link";
import type { Conditions, Place } from "../../lib/product";
import { coords, humanizeText, label, reading, unit, when, sourceName } from "../../lib/humanize";
import ProfilePanels from "./ProfilePanels";
import { Signal } from "./ui/Signal";

const variableName: Record<string, string> = {
  sst_c: "Sea temperature",
  wave_height_m: "Wave height",
  wind_speed_m_s: "Wind speed",
  current_speed_m_s: "Current speed",
};
const statusOf = (s: string | undefined) =>
  s === "available" || s === "supported" ? "available" : s === "stale" ? "stale" : s === "unknown" ? "unknown" : "unavailable";

/** India Standard Time ↔ ISO helpers for the time input. */
const toLocalInput = (iso: string) => {
  const d = new Date(Date.parse(iso) + 330 * 60000);
  return d.toISOString().slice(0, 16);
};
const fromLocalInput = (v: string) => new Date(Date.parse(`${v}:00+05:30`)).toISOString();

export function ConditionSummary({ value }: { value: Conditions }) {
  return (
    <>
      <h3>Forecast timeline at this point</h3>
      <div className="table-scroll" role="region" aria-label="Forecast timeline" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th>Measure</th>
              <th>For</th>
              <th>Reading</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {value.fields.flatMap((f) =>
              f.timeline.length
                ? f.timeline.map((entry, i) => {
                    const sample = "result" in entry ? entry.result : null;
                    const t = sample?.requested_time ?? ("requested_time" in entry ? entry.requested_time : null);
                    const reason = sample?.reason ?? ("reason" in entry ? entry.reason : "");
                    return (
                      <tr key={`${f.variable}-${i}`}>
                        <td>
                          {variableName[f.variable] ?? label(f.variable)}
                          <small>{sourceName(f.product_id)}{f.cycle ? `, issued ${when(f.cycle)}` : ""}</small>
                        </td>
                        <td>{t ? when(t) : "—"}</td>
                        <td>{sample?.value == null ? "—" : `${reading(sample.value, 2)} ${unit(sample.units)}`}</td>
                        <td>
                          <Signal status={statusOf(sample?.status ?? f.state)} size={13} />
                          {reason ? <small>{humanizeText(reason)}</small> : null}
                        </td>
                      </tr>
                    );
                  })
                : [
                    <tr key={f.variable}>
                      <td>{variableName[f.variable] ?? label(f.variable)}</td>
                      <td colSpan={3}>No forecast stored for this point.</td>
                    </tr>,
                  ],
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function LocationView({ place, initial, asOf }: { place: Place; initial: Conditions | null; asOf: string }) {
  const [lat, setLat] = useState(String(place.latitude));
  const [lon, setLon] = useState(String(place.longitude));
  const [time, setTime] = useState(toLocalInput(asOf));
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  function clear() {
    request.current?.abort();
    setError("");
    setBusy(false);
  }
  async function load(e: React.FormEvent) {
    e.preventDefault();
    clear();
    const c = new AbortController();
    request.current = c;
    setBusy(true);
    try {
      const q = new URLSearchParams({ latitude: lat, longitude: lon, time: fromLocalInput(time) });
      const r = await fetch(`/api/explore/conditions?${q}`, { signal: c.signal, cache: "no-store" });
      const data = await r.json();
      if (!r.ok) throw Error(data.code ?? "conditions_unavailable");
      if (!c.signal.aborted) setValue(data);
    } catch (e) {
      if (!c.signal.aborted) setError(e instanceof Error ? e.message : "conditions_unavailable");
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <div>
      <p>
        Every value below is the stored source reading at the exact point and time, with nothing averaged. Change the point
        or time to check something else.
      </p>
      <form className="form-grid" onSubmit={load}>
        <label>
          Latitude (°N)
          <input required type="number" min="-85" max="85" step="any" value={lat} onChange={(e) => setLat(e.target.value)} />
        </label>
        <label>
          Longitude (°E)
          <input required type="number" min="-180" max="180" step="any" value={lon} onChange={(e) => setLon(e.target.value)} />
        </label>
        <label>
          Time (IST)
          <input required type="datetime-local" value={time} onChange={(e) => setTime(e.target.value)} />
        </label>
        <button className="btn" disabled={busy}>
          {busy ? "Checking…" : "Check this point"}
        </button>
      </form>
      <div aria-live="polite">
        {error ? <p className="notice">That check didn’t work: {label(error)}. Try a nearby point or another time.</p> : null}
        {value ? (
          <>
            <p className="footnote">
              Point {coords(value.requested_point.latitude, value.requested_point.longitude, 3)} · for {when(value.requested_time)} · checked {when(value.as_of)}
            </p>
            <ConditionSummary value={value} />
            <h3>Floats within 100 km</h3>
            {!value.nearby_profiles.length ? (
              <p className="muted">No float readings within 100 km for this time.</p>
            ) : (
              <div className="table-scroll" tabIndex={0} role="region" aria-label="Nearby floats">
                <table>
                  <thead>
                    <tr>
                      <th>Float</th>
                      <th>Where</th>
                      <th>When</th>
                      <th>Distance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {value.nearby_profiles.map((p) => (
                      <tr key={p.profile_id}>
                        <td>
                          <Link href={`/profiles/${p.profile_id}`}>Float {p.platform_id}</Link>
                        </td>
                        <td>{coords(p.latitude, p.longitude)}</td>
                        <td>{when(p.observed_at)}</td>
                        <td>{reading(p.distance_km, 0)} km</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {value.nearby_profiles[0] ? (
              <>
                <h3>Nearest float, by depth</h3>
                <ProfilePanels key={value.nearby_profiles[0].profile_id} id={value.nearby_profiles[0].profile_id} />
              </>
            ) : null}
            <details>
              <summary>How this view was put together</summary>
              <ul>
                {value.limitations.map((v) => (
                  <li key={v}>{humanizeText(v)}</li>
                ))}
              </ul>
              <pre className="audit-json">
                {JSON.stringify(
                  {
                    requested_point: value.requested_point,
                    requested_time: value.requested_time,
                    as_of: value.as_of,
                    source_cycles: value.fields.map(({ variable, release_id, manifest_sha256, cycle, state }) => ({ variable, release_id, manifest_sha256, cycle, state })),
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          </>
        ) : busy ? (
          <p role="status">Checking…</p>
        ) : (
          <p className="notice">Choose a point and time to load the evidence. Missing evidence doesn’t mean calm or normal conditions.</p>
        )}
      </div>
      <p className="evidence-links">
        <Link className="text-link" href={`/regions/${place.slug}`}>
          The surrounding region
        </Link>
        <Link className="text-link" href={`/compare?left=${place.slug}`}>
          Compare with another place
        </Link>
      </p>
    </div>
  );
}
