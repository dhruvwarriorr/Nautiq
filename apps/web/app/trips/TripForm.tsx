"use client";
import { useState } from "react";
import Link from "next/link";
import RouteDiagram from "../components/RouteDiagram";
import type {
  TripPolicy,
  TripPoint,
  TripRequest,
  TripResult,
} from "../../lib/trips";
type Release = {
  release_id: string;
  product_id: string;
  cycle: string | null;
  selected: boolean;
  status: string;
  freshness: string;
};
function missingSummaries(codes: string[]): string[] {
  const labels: Record<string, string> = {
    threshold_release_unapproved_or_invalid:
      "Decision thresholds are awaiting domain review",
    advisory_coverage_unknown: "Marine advisory coverage is unknown",
    unresolved_geometry: "Official bulletin areas are unresolved",
    revision_ambiguity:
      "Official bulletin references or identities are unresolved",
    unknown_validity_or_classification:
      "Official bulletin validity or classification is unresolved",
    "ndma_cap_rss:unverified": "NDMA marine coverage is unverified",
    "ndma_cap_rss:stale_or_incomplete": "NDMA transport is stale or incomplete",
    "incois_advisories:unconfigured": "INCOIS machine access is unconfigured",
  };
  const counts = new Map<string, number>();
  for (const code of codes) {
    let text = labels[code];
    if (!text && code.startsWith("advisory:")) {
      const reason = code.slice(9);
      text =
        labels[reason] ??
        labels[reason.split(":").at(-1) ?? ""] ??
        "Official advisory evidence has an unresolved condition";
    }
    if (!text) {
      text = code
        .replace("wave_height_m:", "Wave forecast: ")
        .replace("wind_speed_m_s:", "Wind forecast: ")
        .replace("current_speed_m_s:", "Surface current forecast: ")
        .replaceAll("_", " ");
    }
    counts.set(text, (counts.get(text) ?? 0) + 1);
  }
  return [...counts].map(
    ([text, count]) => `${text}${count > 1 ? ` (${count} conditions)` : ""}.`,
  );
}

export function TripForm({
  policy,
  releases,
  initialRequest,
  onSaveRoute,
  onSaveTrip,
}: {
  policy: TripPolicy;
  releases: Release[];
  initialRequest?: TripRequest;
  onSaveRoute?: (request: TripRequest) => Promise<void>;
  onSaveTrip?: (result: TripResult) => Promise<void>;
}) {
  const initial =
    initialRequest?.waypoints.map((p) => ({
      latitude: String(p.latitude),
      longitude: String(p.longitude),
      time: p.time,
    })) ??
    [0, 1, 2].map((i) => ({
      latitude: i === 1 ? "12.05" : "12",
      longitude: i === 1 ? "72.05" : "72",
      time: new Date(
        Date.parse(policy.as_of) + (i + 1) * 3600000,
      ).toISOString(),
    }));
  const [points, setPoints] =
    useState<{ latitude: string; longitude: string; time: string }[]>(initial);
  const [activity, setActivity] = useState(
    initialRequest?.activity ?? policy.policy.activities[0],
  );
  const [spacing, setSpacing] = useState(
    String(initialRequest?.spacing_km ?? 5),
  );
  const [step, setStep] = useState(String(initialRequest?.step_minutes ?? 30));
  const [bindings, setBindings] = useState<Record<string, string>>(() =>
    initialRequest
      ? Object.fromEntries(
          initialRequest.fields.map((f) => [f.variable, f.release_id]),
        )
      : Object.fromEntries(
          policy.policy.inputs.map((s) => [
            s.variable,
            releases.find(
              (r) =>
                r.product_id === s.product_id &&
                r.selected &&
                r.status === "ready",
            )?.release_id ?? "",
          ]),
        ),
  );
  const [result, setResult] = useState<TripResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [evidence, setEvidence] = useState<unknown>(null);
  const [replayed, setReplayed] = useState(false);
  const previewPoints = points.every(
    (p) => p.latitude.trim() && p.longitude.trim(),
  )
    ? points.map((p) => ({
        latitude: Number(p.latitude),
        longitude: Number(p.longitude),
        time: p.time,
      }))
    : [];
  function clear() {
    setResult(null);
    setEvidence(null);
    setReplayed(false);
    setError("");
  }
  function update(index: number, key: keyof TripPoint, value: string) {
    clear();
    setPoints(points.map((p, i) => (i === index ? { ...p, [key]: value } : p)));
  }
  function request(): TripRequest {
    if (
      points.some(
        (p) =>
          !p.latitude.trim() ||
          !p.longitude.trim() ||
          !Number.isFinite(Number(p.latitude)) ||
          !Number.isFinite(Number(p.longitude)),
      )
    )
      throw Error("coordinates_required");
    return {
      activity,
      threshold_version: policy.policy.version,
      waypoints: points.map((p) => ({
        latitude: Number(p.latitude),
        longitude: Number(p.longitude),
        time: p.time,
      })),
      fields: Object.entries(bindings)
        .filter(([, id]) => id)
        .map(([variable, release_id]) => ({ variable, release_id })),
      spacing_km: Number(spacing),
      step_minutes: Number(step),
      preferences: {},
    };
  }
  async function save(trip: boolean) {
    setBusy(true);
    setError("");
    try {
      if (trip && result) await onSaveTrip?.(result);
      else await onSaveRoute?.(request());
    } catch (e) {
      setError(e instanceof Error ? e.message : "save_unavailable");
    } finally {
      setBusy(false);
    }
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    clear();
    setBusy(true);
    try {
      const body = request();
      const response = await fetch("/api/trips", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) throw Error(data.code ?? "trip_unavailable");
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "trip_unavailable");
    } finally {
      setBusy(false);
    }
  }
  async function inspect(replay: boolean) {
    if (!result) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(
        `/api/trips/${result.calculation_id}${replay ? "/replay" : ""}`,
        {
          method: replay ? "POST" : "GET",
          headers: { Authorization: `Bearer ${result.access_token}` },
        },
      );
      const data = await response.json();
      if (!response.ok) throw Error(data.code ?? "evidence_unavailable");
      if (replay) setReplayed(data.replayed === true);
      else setEvidence(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "evidence_unavailable");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="field-viewer">
      <form onSubmit={submit}>
        <div className="field-controls">
          <label>
            Activity
            <select
              value={activity}
              disabled={busy}
              onChange={(e) => {
                clear();
                setActivity(e.target.value);
              }}
            >
              {policy.policy.activities.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </label>
          <label>
            Sample spacing (km)
            <input
              type="number"
              min="0.5"
              max="5"
              step="0.5"
              value={spacing}
              disabled={busy}
              onInput={(e) => {
                clear();
                setSpacing(e.currentTarget.value);
              }}
            />
          </label>
          <label>
            Time step (minutes)
            <input
              type="number"
              min="1"
              max="30"
              value={step}
              disabled={busy}
              onInput={(e) => {
                clear();
                setStep(e.currentTarget.value);
              }}
            />
          </label>
        </div>
        <p>
          Threshold release:{" "}
          <span className="digest">{policy.policy.version}</span> ·{" "}
          {policy.engine_available ? "reviewed" : "unavailable pending review"}.
          No numeric limits are approved.
        </p>
        <h2>Timed waypoints</h2>
        <RouteDiagram points={previewPoints} />
        <p>
          Include outward and return legs. A stop uses the same position at two
          increasing times. All times require a UTC offset; duration is at most
          24 hours.
        </p>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Timed trip waypoints"
        >
          <table>
            <thead>
              <tr>
                <th>Order</th>
                <th>Latitude</th>
                <th>Longitude</th>
                <th>Arrival / departure (UTC ISO)</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p, i) => (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td>
                    <input
                      aria-label={`Latitude ${i + 1}`}
                      type="number"
                      min="-85"
                      max="85"
                      step="any"
                      required
                      value={p.latitude}
                      disabled={busy}
                      onInput={(e) =>
                        update(i, "latitude", e.currentTarget.value)
                      }
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Longitude ${i + 1}`}
                      type="number"
                      min="-180"
                      max="180"
                      step="any"
                      required
                      value={p.longitude}
                      disabled={busy}
                      onInput={(e) =>
                        update(i, "longitude", e.currentTarget.value)
                      }
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Time ${i + 1}`}
                      required
                      value={p.time}
                      disabled={busy}
                      onChange={(e) => update(i, "time", e.target.value)}
                    />
                  </td>
                  <td>
                    <button
                      type="button"
                      disabled={busy || points.length <= 2}
                      onClick={() => {
                        clear();
                        setPoints(points.filter((_, j) => j !== i));
                      }}
                    >
                      Remove {i + 1}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          type="button"
          disabled={busy || points.length >= 32}
          onClick={() => {
            clear();
            const last = points[points.length - 1];
            if (!Number.isFinite(Date.parse(last.time))) {
              setError("invalid_waypoint_time");
              return;
            }
            setPoints([
              ...points,
              {
                ...last,
                time: new Date(Date.parse(last.time) + 3600000).toISOString(),
              },
            ]);
          }}
        >
          Add timed stop / waypoint
        </button>{" "}
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            clear();
            const first = Date.parse(points[0].time);
            if (
              !Number.isFinite(first) ||
              points.some((p) => !Number.isFinite(Date.parse(p.time)))
            ) {
              setError("invalid_waypoint_time");
              return;
            }
            const shift = Date.now() + 3600000 - first;
            setPoints(
              points.map((p) => ({
                ...p,
                time: new Date(Date.parse(p.time) + shift).toISOString(),
              })),
            );
          }}
        >
          Move departure to one hour from now
        </button>
        <h2>Pinned forecast releases</h2>
        <div className="field-controls">
          {policy.policy.inputs.map((s) => (
            <label key={s.variable}>
              {s.variable} (
              {s.required ? "required evidence" : "optional evidence"})
              <select
                disabled={busy}
                value={bindings[s.variable] ?? ""}
                onChange={(e) => {
                  clear();
                  setBindings({ ...bindings, [s.variable]: e.target.value });
                }}
              >
                <option value="">Missing / not supplied</option>
                {releases
                  .filter(
                    (r) =>
                      r.product_id === s.product_id && r.status === "ready",
                  )
                  .map((r) => (
                    <option key={r.release_id} value={r.release_id}>
                      {r.cycle ?? "no cycle"} · {r.freshness} ·{" "}
                      {r.release_id.slice(0, 8)}
                    </option>
                  ))}
              </select>
            </label>
          ))}
        </div>
        <button type="submit" disabled={busy}>
          {busy ? "Retaining trip evidence…" : "Inspect trip evidence"}
        </button>
        {onSaveRoute ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void save(false)}
          >
            Save timed route
          </button>
        ) : null}
      </form>
      <div aria-live="polite">
        {error && (
          <p className="notice">
            The request could not be completed: {error.replaceAll("_", " ")}.
          </p>
        )}
        {result && (
          <section>
            <p className="eyebrow">
              {result.verdict.status.replaceAll("_", " ")}
            </p>
            <h2>{result.verdict.wording}</h2>
            <RouteDiagram
              points={points.map((p) => ({
                latitude: Number(p.latitude),
                longitude: Number(p.longitude),
                time: p.time,
              }))}
              verdict={result.verdict}
            />
            {onSaveTrip ? (
              <button disabled={busy} onClick={() => void save(true)}>
                Save private trip receipt to account
              </button>
            ) : null}
            <p>
              As of {result.verdict.as_of} ·{" "}
              {result.verdict.sampling.sample_count} timed samples ·{" "}
              {result.verdict.sampling.distance_km.toFixed(2)} km
            </p>
            <p className="digest">
              Calculation {result.calculation_id}
              <br />
              Manifest SHA-256 {result.manifest_sha256}
            </p>
            <h3>Missing or unverified inputs</h3>
            <ul>
              {missingSummaries(result.verdict.missing_inputs).map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
            <h3>Worst retained samples</h3>
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Worst trip samples"
            >
              <table>
                <thead>
                  <tr>
                    <th>Variable</th>
                    <th>Value / unit</th>
                    <th>UTC time</th>
                    <th>Position</th>
                    <th>Support</th>
                  </tr>
                </thead>
                <tbody>
                  {result.verdict.worst_samples.map((w) => (
                    <tr key={w.variable}>
                      <td>{w.variable}</td>
                      <td>
                        {w.value.toFixed(3)} {w.units}
                      </td>
                      <td>{w.point.time}</td>
                      <td>
                        {w.point.latitude.toFixed(4)},{" "}
                        {w.point.longitude.toFixed(4)}
                      </td>
                      <td>{w.sample_status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {result.verdict.rules_fired.length > 0 && (
              <>
                <h3>All fired rules</h3>
                {result.verdict.rules_fired.map((r, i) => (
                  <p key={i}>
                    {r.verdict} · {r.rule_id} · {r.origin} ·{" "}
                    {r.value !== null ? `${r.value} ${r.units}` : r.evidence}
                  </p>
                ))}
              </>
            )}
            <h3>Source cycles</h3>
            {result.verdict.source_cycles.map((c) => (
              <p className="digest" key={c.variable}>
                {c.variable}: {c.cycle ?? "missing cycle"}
                <br />
                <Link href={`/fields/${c.release_id}`}>{c.release_id}</Link>
                <br />
                Manifest {c.manifest_sha256}
              </p>
            ))}
            <button
              type="button"
              disabled={busy}
              onClick={() => inspect(false)}
            >
              Inspect private calculation receipt
            </button>{" "}
            <button type="button" disabled={busy} onClick={() => inspect(true)}>
              Replay frozen calculation
            </button>
            {replayed && (
              <p>
                Replay matched the stored verdict. Freshness was not renewed.
              </p>
            )}
            {evidence !== null && (
              <details open>
                <summary>Private retained inputs and output</summary>
                <pre className="audit-json">
                  {JSON.stringify(evidence, null, 2)}
                </pre>
              </details>
            )}
            <h3>Limitations</h3>
            <ul>
              {result.verdict.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
