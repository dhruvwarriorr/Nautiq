"use client";
import { useRef, useState, useEffect } from "react";
import Link from "next/link";
import type { Conditions, Place } from "../../lib/product";
import { fieldNumber } from "../../lib/fields";
import ProfilePanels from "./ProfilePanels";
export function ConditionSummary({ value }: { value: Conditions }) {
  return (
    <>
      <p>
        Requested {value.requested_point.latitude.toFixed(4)},{" "}
        {value.requested_point.longitude.toFixed(4)} · {value.requested_time}.
        Evidence inspected {value.as_of}.
      </p>
      <h2>Retained forecast timeline</h2>
      <div
        className="table-scroll"
        role="region"
        aria-label="Location forecast evidence"
        tabIndex={0}
      >
        <table>
          <thead>
            <tr>
              <th>Variable / cycle</th>
              <th>Requested UTC time</th>
              <th>Value</th>
              <th>Support / freshness</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {value.fields.flatMap((f) =>
              f.timeline.length
                ? f.timeline.map((entry, i) => {
                    const sample = "result" in entry ? entry.result : null;
                    return (
                      <tr key={`${f.variable}-${i}`}>
                        <td>
                          {f.variable}
                          <small>{f.cycle ?? "No forecast cycle"}</small>
                        </td>
                        <td>
                          {sample?.requested_time ??
                            ("requested_time" in entry
                              ? entry.requested_time
                              : "Unavailable")}
                        </td>
                        <td>
                          {sample?.value == null
                            ? "Unavailable"
                            : `${fieldNumber(sample.value)} ${sample.units}`}
                        </td>
                        <td>
                          {sample?.status ?? "unavailable"} · {f.state}
                          <small>
                            {sample?.reason ??
                              ("reason" in entry ? entry.reason : "")}
                          </small>
                        </td>
                        <td>
                          {f.release_id ? (
                            <Link href={`/fields/${f.release_id}`}>
                              Pinned release
                            </Link>
                          ) : (
                            "Unavailable"
                          )}
                        </td>
                      </tr>
                    );
                  })
                : [
                    <tr key={f.variable}>
                      <td>{f.variable}</td>
                      <td colSpan={4}>
                        No retained field evidence is available.
                      </td>
                    </tr>,
                  ],
            )}
          </tbody>
        </table>
      </div>
      <h2>Official advisory state</h2>
      <p className="notice">
        {value.advisory.status.replaceAll("_", " ")}. Missing coverage and
        unresolved official areas cannot establish an all-clear.
      </p>
      {value.advisory.warnings?.map((w) => (
        <p key={w.revision_id}>
          <Link href={`/advisories/${w.revision_id}`}>
            Official {w.event} · {w.severity} · expires {w.expires ?? "unknown"}
          </Link>
        </p>
      ))}
      <Link href="/advisories">
        Inspect original bulletins, validity and source health →
      </Link>
      <h2>Observed versus expected at this point</h2>
      <p>
        A collocated observed profile and expected interval at the requested
        point are unavailable. Nearby instrument comparisons keep their measured
        positions, times and depths.
      </p>
      <p>
        Confidence: unavailable pending a validated policy. Source coverage and
        freshness above remain factual labels.
      </p>
    </>
  );
}
export default function LocationView({
  place,
  initial,
  asOf,
}: {
  place: Place;
  initial: Conditions | null;
  asOf: string;
}) {
  const [lat, setLat] = useState(String(place.latitude));
  const [lon, setLon] = useState(String(place.longitude));
  const [time, setTime] = useState(asOf);
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  function clear() {
    request.current?.abort();
    setValue(null);
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
      const q = new URLSearchParams({ latitude: lat, longitude: lon, time });
      const r = await fetch(`/api/explore/conditions?${q}`, {
        signal: c.signal,
        cache: "no-store",
      });
      const data = await r.json();
      if (!r.ok) throw Error(data.code ?? "conditions_unavailable");
      if (!c.signal.aborted) setValue(data);
    } catch (e) {
      if (!c.signal.aborted)
        setError(e instanceof Error ? e.message : "conditions_unavailable");
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <div className="field-viewer">
      <form className="field-controls" onSubmit={load}>
        <label>
          Requested latitude
          <input
            required
            type="number"
            min="-85"
            max="85"
            step="any"
            value={lat}
            onInput={(e) => {
              clear();
              setLat(e.currentTarget.value);
            }}
          />
        </label>
        <label>
          Requested longitude
          <input
            required
            type="number"
            min="-180"
            max="180"
            step="any"
            value={lon}
            onInput={(e) => {
              clear();
              setLon(e.currentTarget.value);
            }}
          />
        </label>
        <label>
          Requested UTC time (ISO with offset)
          <input
            required
            value={time}
            onChange={(e) => {
              clear();
              setTime(e.target.value);
            }}
          />
        </label>
        <button disabled={busy}>
          {busy ? "Loading evidence…" : "Inspect location evidence"}
        </button>
      </form>
      <div aria-live="polite">
        {error ? (
          <p className="notice">
            Query unavailable: {error.replaceAll("_", " ")}.
          </p>
        ) : null}
        {value ? (
          <>
            <ConditionSummary value={value} />
            <h2>Nearby instruments and recent observations</h2>
            <p>
              Within 100 km, ordered by observed time. Distance and age describe
              source support; they do not authorize interpolation to this
              location.
            </p>
            {!value.nearby_profiles.length ? (
              <p>
                No matching nearby accepted profiles were retained for the
                selected time.
              </p>
            ) : null}
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Nearby observation evidence"
            >
              <table>
                <thead>
                  <tr>
                    <th>Instrument</th>
                    <th>Actual position</th>
                    <th>Observed UTC</th>
                    <th>Distance</th>
                    <th>QC</th>
                  </tr>
                </thead>
                <tbody>
                  {value.nearby_profiles.map((p) => (
                    <tr key={p.profile_id}>
                      <td>
                        <Link href={`/profiles/${p.profile_id}`}>
                          Argo {p.platform_id}
                        </Link>
                      </td>
                      <td>
                        {p.latitude.toFixed(3)}, {p.longitude.toFixed(3)}
                      </td>
                      <td>{p.observed_at}</td>
                      <td>{p.distance_km.toFixed(1)} km</td>
                      <td>{p.qc_version}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {value.nearby_profiles[0] ? (
              <>
                <h2>Vertical profile and matching references</h2>
                <ProfilePanels
                  key={value.nearby_profiles[0].profile_id}
                  id={value.nearby_profiles[0].profile_id}
                />
              </>
            ) : null}
            <details>
              <summary>How this view was assembled</summary>
              <ul>
                {value.limitations.map((v) => (
                  <li key={v}>{v}</li>
                ))}
              </ul>
              <pre className="audit-json">
                {JSON.stringify(
                  {
                    requested_point: value.requested_point,
                    requested_time: value.requested_time,
                    as_of: value.as_of,
                    source_cycles: value.fields.map(
                      ({
                        variable,
                        release_id,
                        manifest_sha256,
                        cycle,
                        state,
                      }) => ({
                        variable,
                        release_id,
                        manifest_sha256,
                        cycle,
                        state,
                      }),
                    ),
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          </>
        ) : busy ? (
          <p role="status">Loading independent evidence layers…</p>
        ) : (
          <p className="notice">
            Submit the point and UTC time to load evidence. Unavailable evidence
            does not mean calm or normal conditions.
          </p>
        )}
      </div>
      <p>
        <Link href={`/regions/${place.slug}`}>
          Explore the surrounding region →
        </Link>{" "}
        ·{" "}
        <Link href={`/compare?left=${place.slug}`}>
          Compare another location →
        </Link>
      </p>
    </div>
  );
}
