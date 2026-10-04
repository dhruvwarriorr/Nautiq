"use client";
import { Fragment, useState } from "react";
import Link from "next/link";
import RouteDiagram from "../components/RouteDiagram";
import RoutePicker from "./RoutePicker";
import Icon from "../components/ui/Icon";
import { SignalShape } from "../components/ui/Signal";
import { beaufort, coords, knots, label, reading, seaState, short, when } from "../../lib/humanize";
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
      "Trip limits are still being reviewed by marine experts",
    advisory_coverage_unknown: "We can’t confirm official warnings cover this stretch of sea",
    unresolved_geometry: "Some official bulletins name places we can’t map",
    revision_ambiguity:
      "Some official bulletins have unclear revisions",
    unknown_validity_or_classification:
      "Some official bulletins have unclear start or end times",
    "ndma_cap_rss:unverified": "NDMA alerts aren’t verified to cover the sea",
    "ndma_cap_rss:stale_or_incomplete": "NDMA alerts haven’t been checked recently",
    "incois_advisories:unconfigured": "INCOIS ocean advisories aren’t connected yet",
  };
  const counts = new Map<string, number>();
  for (const code of codes) {
    let text = labels[code];
    if (!text && code.startsWith("advisory:")) {
      const reason = code.slice(9);
      text =
        labels[reason] ??
        labels[reason.split(":").at(-1) ?? ""] ??
        "Some official warning evidence is unresolved";
    }
    if (!text) {
      text = code
        .replace("wave_height_m:", "Waves: ")
        .replace("wind_speed_m_s:", "Wind: ")
        .replace("current_speed_m_s:", "Current: ")
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
  prefill,
  onSaveRoute,
  onSaveTrip,
  places = [],
}: {
  places?: { slug: string; name: string; latitude: number; longitude: number }[];
  policy: TripPolicy;
  releases: Release[];
  initialRequest?: TripRequest;
  prefill?: { latitude: number; longitude: number; departure?: string };
  onSaveRoute?: (request: TripRequest) => Promise<void>;
  onSaveTrip?: (result: TripResult) => Promise<void>;
}) {
  const initial =
    initialRequest?.waypoints.map((p) => ({
      latitude: String(p.latitude),
      longitude: String(p.longitude),
      time: p.time,
    })) ??
    [0, 1, 2].map((i) => {
      const base = prefill ?? { latitude: 12, longitude: 72 };
      const out = i === 1 ? 0.05 : 0;
      const t0 = prefill?.departure
        ? Date.parse(prefill.departure)
        : Date.parse(policy.as_of) + 3600000;
      return {
        latitude: String(Number((base.latitude + out).toFixed(4))),
        longitude: String(Number((base.longitude + out).toFixed(4))),
        time: new Date(t0 + i * 3600000).toISOString(),
      };
    });
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
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [evidence, setEvidence] = useState<unknown>(null);
  const [replayed, setReplayed] = useState(false);
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
  const toIST = (iso: string) => {
    const t = Date.parse(iso);
    return Number.isFinite(t) ? new Date(t + 330 * 60000).toISOString().slice(0, 16) : "";
  };
  const fromIST = (v: string) => (v ? new Date(Date.parse(`${v}:00+05:30`)).toISOString() : "");
  const status = result?.verdict.status ?? "";
  const tone = status === "official_warning" || status === "critical" ? "warning" : status === "caution" ? "stale" : status === "insufficient_data" ? "unknown" : "available";
  return (
    <div className="trip">
      <form onSubmit={submit} className="trip-form">
        <section className="trip-step" aria-labelledby="t-activity">
          <h2 id="t-activity"><span className="step-dot">1</span> What are you doing?</h2>
          <div className="choice-row" role="radiogroup" aria-label="Activity">
            {policy.policy.activities.map((a) => (
              <button
                type="button"
                key={a}
                role="radio"
                aria-checked={activity === a}
                className="choice"
                disabled={busy}
                onClick={() => {
                  clear();
                  setActivity(a);
                }}
              >
                <Icon name={a === "fishing" ? "buoy" : "voyage"} size={22} />
                {a.charAt(0).toUpperCase() + a.slice(1)}
              </button>
            ))}
          </div>
        </section>

        <section className="trip-step" aria-labelledby="t-route">
          <h2 id="t-route"><span className="step-dot">2</span> Your route, out and back</h2>
          <p className="muted">Add each stop with the time you expect to be there (India time). A stop where you wait uses the same spot twice. Up to 24 hours.</p>
          {places.length ? (
            <div className="start-from">
              <span>Start from</span>
              {places.map((pl) => (
                <button
                  type="button"
                  key={pl.slug}
                  className="suggestion"
                  disabled={busy}
                  onClick={() => {
                    clear();
                    const base = Date.parse(points[0].time);
                    const t0 = Number.isFinite(base) ? base : Date.now() + 3600000;
                    setPoints([
                      { latitude: String(pl.latitude), longitude: String(pl.longitude), time: new Date(t0).toISOString() },
                      { latitude: String(Number((pl.latitude + 0.08).toFixed(4))), longitude: String(Number((pl.longitude - 0.08).toFixed(4))), time: new Date(t0 + 2 * 3600000).toISOString() },
                      { latitude: String(pl.latitude), longitude: String(pl.longitude), time: new Date(t0 + 4 * 3600000).toISOString() },
                    ]);
                  }}
                >
                  <Icon name="buoy" size={16} /> {pl.name}
                </button>
              ))}
            </div>
          ) : null}
          <div className="trip-route">
            <ol className="stops">
              {points.map((p, i) => (
                <li key={i} className="stop" data-active={active === i || undefined}>
                  <span className="stop-mark" aria-hidden="true">{i + 1}</span>
                  <div className="stop-fields">
                    <div className="stop-head">
                      <p className="stop-name">{i === 0 ? "Leave from" : i === points.length - 1 ? "Arrive back" : `Stop ${i}`}</p>
                      <button type="button" className="stop-place" aria-pressed={active === i} onClick={() => setActive(i)} disabled={busy}>
                        <Icon name="pin" size={16} /> {active === i ? "Tap the chart" : "Place on chart"}
                      </button>
                    </div>
                    <p className="stop-where">
                      {Number.isFinite(Number(p.latitude)) && Number.isFinite(Number(p.longitude)) && p.latitude !== "" && p.longitude !== ""
                        ? coords(Number(p.latitude), Number(p.longitude))
                        : "Not placed yet"}
                    </p>
                    <label className="stop-time">
                      Time (IST)
                      <input aria-label={`Stop ${i + 1} time`} type="datetime-local" required value={toIST(p.time)} disabled={busy} onChange={(e) => update(i, "time", fromIST(e.target.value))} />
                    </label>
                    <details className="stop-coords">
                      <summary>Type coordinates instead</summary>
                      <div className="stop-coords-grid">
                        <label>
                          Latitude
                          <input aria-label={`Stop ${i + 1} latitude`} type="number" min="-85" max="85" step="any" required value={p.latitude} disabled={busy} onChange={(e) => update(i, "latitude", e.target.value)} />
                        </label>
                        <label>
                          Longitude
                          <input aria-label={`Stop ${i + 1} longitude`} type="number" min="-180" max="180" step="any" required value={p.longitude} disabled={busy} onChange={(e) => update(i, "longitude", e.target.value)} />
                        </label>
                      </div>
                    </details>
                  </div>
                  <button
                    type="button"
                    className="stop-remove"
                    aria-label={`Remove stop ${i + 1}`}
                    disabled={busy || points.length <= 2}
                    onClick={() => {
                      clear();
                      setPoints(points.filter((_, j) => j !== i));
                      setActive((a) => Math.max(0, Math.min(a, points.length - 2)));
                    }}
                  >
                    <Icon name="close" size={18} />
                  </button>
                </li>
              ))}
            </ol>
            <div className="trip-preview">
              <RoutePicker
                stops={points.map((p) => ({ latitude: p.latitude === "" ? NaN : Number(p.latitude), longitude: p.longitude === "" ? NaN : Number(p.longitude) }))}
                active={Math.min(active, points.length - 1)}
                onPick={(lat, lon) => {
                  clear();
                  setPoints((ps) => ps.map((p, j) => (j === Math.min(active, ps.length - 1) ? { ...p, latitude: String(lat), longitude: String(lon) } : p)));
                  setActive((a) => Math.min(a + 1, points.length - 1));
                }}
              />
            </div>
          </div>
          <div className="trip-actions">
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
                setPoints([...points, { ...last, time: new Date(Date.parse(last.time) + 3600000).toISOString() }]);
                setActive(points.length);
              }}
            >
              <Icon name="plus" size={18} /> Add a stop
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                clear();
                const first = Date.parse(points[0].time);
                if (!Number.isFinite(first) || points.some((p) => !Number.isFinite(Date.parse(p.time)))) {
                  setError("invalid_waypoint_time");
                  return;
                }
                const shift = Date.now() + 3600000 - first;
                setPoints(points.map((p) => ({ ...p, time: new Date(Date.parse(p.time) + shift).toISOString() })));
              }}
            >
              <Icon name="clock" size={18} /> Leave in one hour
            </button>
          </div>
        </section>

        <details className="tech">
          <summary>
            <Icon name="sounding" size={18} />
            <span>Advanced settings</span>
            <Icon name="down" size={18} className="icon tech-chevron" />
          </summary>
          <div className="tech-body">
            <div className="form-grid">
              <label>
                Check every (km)
                <input type="number" min="0.5" max="5" step="0.5" value={spacing} disabled={busy} onChange={(e) => { clear(); setSpacing(e.target.value); }} />
              </label>
              <label>
                Check every (minutes)
                <input type="number" min="1" max="30" value={step} disabled={busy} onChange={(e) => { clear(); setStep(e.target.value); }} />
              </label>
              {policy.policy.inputs.map((s) => (
                <label key={s.variable}>
                  {s.variable.startsWith("wave") ? "Wave forecast" : s.variable.startsWith("wind") ? "Wind forecast" : "Current forecast"} {s.required ? "" : "(optional)"}
                  <select
                    disabled={busy}
                    value={bindings[s.variable] ?? ""}
                    onChange={(e) => {
                      clear();
                      setBindings({ ...bindings, [s.variable]: e.target.value });
                    }}
                  >
                    <option value="">Don’t use</option>
                    {releases
                      .filter((r) => r.product_id === s.product_id && r.status === "ready")
                      .map((r) => (
                        <option key={r.release_id} value={r.release_id}>
                          {r.cycle ? `Issued ${when(r.cycle)}` : "Daily analysis"} · {label(r.freshness)}
                        </option>
                      ))}
                  </select>
                </label>
              ))}
            </div>
            <p className="footnote">
              Rule set <span className="digest">{policy.policy.version}</span> · {policy.engine_available ? "reviewed" : "awaiting expert review"}. No numeric limits are approved yet.
            </p>
          </div>
        </details>

        <div className="trip-submit">
          <button type="submit" className="btn" disabled={busy}>
            {busy ? "Checking every leg…" : "Check my trip"} <Icon name="arrow" size={18} />
          </button>
          {onSaveRoute ? (
            <button type="button" className="btn-ghost" disabled={busy} onClick={() => void save(false)}>
              <Icon name="anchorline" size={18} /> Save this route
            </button>
          ) : null}
        </div>
      </form>

      <div aria-live="polite">
        {error && <p className="notice">That didn’t work: {label(error)}. Check every stop has a position and a later time than the one before.</p>}
        {result && (
          <section className="trip-result" aria-label="Trip result">
            <div className="verdict" data-status={tone}>
              <span className="verdict-shape">
                <SignalShape status={tone as "available"} size={30} />
              </span>
              <div>
                <p className="verdict-title">{label(result.verdict.status)}</p>
                <p className="verdict-text">{result.verdict.wording}</p>
              </div>
              {onSaveTrip ? (
                <button className="btn-ghost" disabled={busy} onClick={() => void save(true)}>
                  <Icon name="logbook" size={18} /> Save receipt
                </button>
              ) : null}
            </div>
            <ul className="stat-line">
              <li><b>{result.verdict.sampling.sample_count}</b><span>checks along the route</span></li>
              <li><b>{reading(result.verdict.sampling.distance_km, 1)} km</b><span>total distance</span></li>
              <li><b>{points.length}</b><span>stops</span></li>
            </ul>
            <div className="split">
              <div>
                <h3>Toughest conditions on the way</h3>
                {result.verdict.worst_samples.length ? (
                  <ul className="rows">
                    {result.verdict.worst_samples.map((w) => (
                      <li key={w.variable} className="row">
                        <span className="row-icon"><Icon name={w.variable.startsWith("wave") ? "waves" : w.variable.startsWith("wind") ? "windsock" : "current"} size={22} /></span>
                        <span>
                          <span className="row-title">
                            {w.variable.startsWith("wave")
                              ? `${reading(w.value, 1)} m waves · ${seaState(w.value)}`
                              : w.variable.startsWith("wind")
                                ? `${reading(knots(w.value), 0)} kn wind · ${beaufort(w.value)}`
                                : `${reading(knots(w.value), 1)} kn current`}
                          </span>
                          <span className="row-sub" style={{ display: "block" }}>At {when(w.point.time)} · {coords(w.point.latitude, w.point.longitude)}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">No forecast readings could be taken along this route.</p>
                )}
                <h3 style={{ marginTop: 28 }}>What couldn’t be checked</h3>
                <ul className="plain-list">
                  {missingSummaries(result.verdict.missing_inputs).map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </div>
              <RouteDiagram points={points.map((p) => ({ latitude: Number(p.latitude), longitude: Number(p.longitude), time: p.time }))} verdict={result.verdict} />
            </div>
            <details className="tech">
              <summary>
                <Icon name="sounding" size={18} />
                <span>Receipt and technical detail</span>
                <Icon name="down" size={18} className="icon tech-chevron" />
              </summary>
              <div className="tech-body">
                <p>
                  Checked {when(result.verdict.as_of)}. This calculation is frozen: replaying it gives the same answer and never refreshes the data.
                </p>
                <div className="evidence-links">
                  <button type="button" disabled={busy} onClick={() => inspect(false)}>Open private receipt</button>
                  <button type="button" disabled={busy} onClick={() => inspect(true)}>Replay calculation</button>
                </div>
                {replayed && <p>Replay matched the stored result. The data was not refreshed.</p>}
                <dl>
                  <dt>Calculation</dt>
                  <dd className="digest">{result.calculation_id}</dd>
                  <dt>Fingerprint</dt>
                  <dd className="digest">{short(result.manifest_sha256, 16)}…</dd>
                  {result.verdict.source_cycles.map((c) => (
                    <Fragment key={c.variable}>
                      <dt>{label(c.variable)}</dt>
                      <dd>
                        {c.cycle ? `Issued ${when(c.cycle)}` : "No forecast cycle"} · <Link href={`/fields/${c.release_id}`}>layer</Link>
                      </dd>
                    </Fragment>
                  ))}
                </dl>
                {result.verdict.rules_fired.length > 0 && (
                  <>
                    <h3>Rules that applied</h3>
                    <ul>
                      {result.verdict.rules_fired.map((r, i) => (
                        <li key={i}>
                          {label(r.verdict)} · {r.rule_id} · {r.value !== null ? `${r.value} ${r.units}` : r.evidence}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                <h3>Limits</h3>
                <ul>
                  {result.verdict.limitations.map((l) => (
                    <li key={l}>{l}</li>
                  ))}
                </ul>
                {evidence !== null && <pre className="audit-json">{JSON.stringify(evidence, null, 2)}</pre>}
              </div>
            </details>
          </section>
        )}
      </div>
    </div>
  );
}
