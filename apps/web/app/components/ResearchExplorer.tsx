"use client";
import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import {
  publicQuery,
  type ResearchFilter,
  type ResearchResult,
  type Session,
} from "../../lib/product";
import AccountGate from "./AccountGate";
import PrivateJobs from "./PrivateJobs";
import ProfilePanels from "./ProfilePanels";
import { coords, reading, when } from "../../lib/humanize";
import Icon from "./ui/Icon";
export default function ResearchExplorer({
  initial,
  session = null,
}: {
  initial: ResearchFilter;
  session?: Session | null;
}) {
  const [filter, setFilter] = useState(initial);
  const [bbox, setBBox] = useState(initial.bbox.join(","));
  const [polygon, setPolygon] = useState("");
  const [percentile, setPercentile] = useState("");
  const [event, setEvent] = useState("");
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  function invalidate() {
    controller.current?.abort();
    setResult(null);
    setSelected("");
    setError("");
    setBusy(false);
  }
  function change<K extends keyof ResearchFilter>(
    key: K,
    value: ResearchFilter[K],
  ) {
    invalidate();
    setFilter({ ...filter, [key]: value });
  }
  async function search(cursor?: string) {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    setBusy(true);
    setError("");
    try {
      const query: ResearchFilter = {
        ...filter,
        bbox: bbox.split(",").map(Number),
        ...(polygon.trim() ? { polygon: JSON.parse(polygon) } : {}),
        ...(percentile !== ""
          ? { minimum_anomaly_percentile: Number(percentile) }
          : {}),
        ...(event ? { event_id: event } : {}),
        ...(cursor ? { cursor } : {}),
      };
      if (
        query.bbox.length !== 4 ||
        bbox.split(",").some((v) => !v.trim()) ||
        query.bbox.some((v) => !Number.isFinite(v))
      )
        throw Error("four_bbox_coordinates_required");
      const data = await publicQuery<ResearchResult>(
        "research",
        query,
        c.signal,
      );
      if (c.signal.aborted) return;
      setResult((old) =>
        cursor && old
          ? { ...data, items: [...old.items, ...data.items] }
          : data,
      );
      setSelected(data.items[0]?.id ?? "");
    } catch (e) {
      if (!c.signal.aborted)
        setError(e instanceof Error ? e.message : "research_unavailable");
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  const areas: [string, string][] = [
    ["45,0,100,30", "All of India’s seas"],
    ["45,0,77,25", "Arabian Sea"],
    ["78,0,100,25", "Bay of Bengal"],
    ["72,8,78,16", "Off Kerala and Goa"],
  ];
  const periods: [number, string][] = [
    [7, "Last 7 days"],
    [30, "Last 30 days"],
    [90, "Last 3 months"],
    [365, "Last 12 months"],
  ];
  const depths: [number, number, string][] = [
    [0, 50, "Near the surface (0–50 m)"],
    [0, 200, "Upper ocean (0–200 m)"],
    [0, 1000, "Down to 1,000 m"],
    [0, 2000, "Full depth (0–2,000 m)"],
  ];
  const span = Math.round((Date.parse(filter.end) - Date.parse(filter.start)) / 86400000);
  const period = periods.find(([d]) => Math.abs(d - span) <= 1)?.[0] ?? 0;
  const depthKey = `${filter.min_depth_m}-${filter.max_depth_m}`;
  return (
    <>
      <form
        className="explore-form"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <div className="explore-main">
          <label>
            Area
            <select
              value={areas.some(([v]) => v === bbox) ? bbox : "custom"}
              onChange={(e) => {
                invalidate();
                if (e.target.value !== "custom") setBBox(e.target.value);
              }}
            >
              {areas.map(([v, t]) => (
                <option key={v} value={v}>{t}</option>
              ))}
              <option value="custom">Custom area (below)</option>
            </select>
          </label>
          <label>
            Period
            <select
              value={period || "custom"}
              onChange={(e) => {
                if (e.target.value === "custom") return;
                const end = new Date();
                invalidate();
                setFilter({ ...filter, end: end.toISOString(), start: new Date(end.getTime() - Number(e.target.value) * 86400000).toISOString() });
              }}
            >
              {periods.map(([d, t]) => (
                <option key={d} value={d}>{t}</option>
              ))}
              <option value="custom">Custom dates (below)</option>
            </select>
          </label>
          <label>
            Measure
            <select value={filter.variable} onChange={(e) => change("variable", e.target.value as ResearchFilter["variable"])}>
              <option value="temperature_c">Temperature (°C)</option>
              <option value="practical_salinity">Salinity</option>
            </select>
          </label>
          <label>
            Depth
            <select
              value={depths.some(([a, b]) => `${a}-${b}` === depthKey) ? depthKey : "custom"}
              onChange={(e) => {
                if (e.target.value === "custom") return;
                const [a, b] = e.target.value.split("-").map(Number);
                invalidate();
                setFilter({ ...filter, min_depth_m: a, max_depth_m: b });
              }}
            >
              {depths.map(([a, b, t]) => (
                <option key={t} value={`${a}-${b}`}>{t}</option>
              ))}
              <option value="custom">Custom depths (below)</option>
            </select>
          </label>
          <button className="btn" disabled={busy}>
            <Icon name="spyglass" size={18} /> {busy ? "Searching…" : "Find readings"}
          </button>
        </div>
        <details className="tech">
          <summary>
            <Icon name="sounding" size={18} />
            <span>More filters</span>
            <Icon name="down" size={18} className="icon tech-chevron" />
          </summary>
          <div className="tech-body">
            <div className="form-grid">
              <label>
                Area (west, south, east, north)
                <input required value={bbox} onChange={(e) => { invalidate(); setBBox(e.target.value); }} />
              </label>
              <label>
                From
                <input type="date" required value={filter.start.slice(0, 10)} onChange={(e) => change("start", `${e.target.value}T00:00:00Z`)} />
              </label>
              <label>
                Until (not included)
                <input type="date" required value={filter.end.slice(0, 10)} onChange={(e) => change("end", `${e.target.value}T00:00:00Z`)} />
              </label>
              <label>
                Shallowest (m)
                <input type="number" min={0} max={6000} required value={filter.min_depth_m} onChange={(e) => change("min_depth_m", Number(e.target.value))} />
              </label>
              <label>
                Deepest (m)
                <input type="number" min={0} max={6000} required value={filter.max_depth_m} onChange={(e) => change("max_depth_m", Number(e.target.value))} />
              </label>
              <label>
                Quality
                <select value={filter.qc} onChange={(e) => change("qc", e.target.value as ResearchFilter["qc"])}>
                  <option value="accepted">Passed quality checks</option>
                  <option value="science_ready">Science-ready only</option>
                </select>
              </label>
              <label>
                Processing
                <select value={filter.data_mode ?? ""} onChange={(e) => change("data_mode", e.target.value)}>
                  <option value="">Any</option>
                  <option value="R">Real-time</option>
                  <option value="A">Adjusted</option>
                  <option value="D">Delayed (expert-checked)</option>
                </select>
              </label>
              <label>
                Readings per page
                <input required type="number" min={1} max={100} value={filter.limit} onChange={(e) => change("limit", Number(e.target.value))} />
              </label>
              <label>
                Only unusual (minimum rank %)
                <input type="number" min={0} max={100} value={percentile} placeholder="e.g. 95" onChange={(e) => { invalidate(); setPercentile(e.target.value); }} />
              </label>
              <label>
                Belongs to event (ID)
                <input value={event} onChange={(e) => { invalidate(); setEvent(e.target.value); }} />
              </label>
            </div>
            <label className="wide-label">
              Custom shape (longitude, latitude pairs, closed)
              <textarea rows={2} value={polygon} onChange={(e) => { invalidate(); setPolygon(e.target.value); }} placeholder="[[65,10],[66,10],[66,11],[65,10]]" />
            </label>
            <p className="footnote">Source: Argo floats. Up to 366 days at a time. Readings keep their true depth and position.</p>
          </div>
        </details>
      </form>
      <p role="status" className="ask-status">{error ? `That search didn’t work: ${error.replaceAll("_", " ")}.` : ""}</p>
      {result ? (
        <section>
          <div className="section-head" style={{ marginTop: 36 }}>
            <h2 style={{ margin: 0 }}>{result.items.length} float readings</h2>
            <p>Found {when(result.snapshot_at)}</p>
          </div>
          {result.items.length === 0 ? (
            <p>
              No float readings match. Try a wider area or a longer period.
            </p>
          ) : (
            <>
              <div
                className="table-scroll"
                role="region"
                tabIndex={0}
                aria-label="Research observations"
              >
                <table>
                  <thead>
                    <tr>
                      <th>Float</th>
                      <th>When</th>
                      <th>Range</th>
                      <th>Unusual?</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.items.map((r) => (
                      <tr key={`${r.id}:${r.revision_sha256}`}>
                        <td>
                          <Link href={`/profiles/${r.id}`}>Float {r.platform_id}</Link>
                          <small>{coords(r.latitude, r.longitude)} · {r.level_count} depths</small>
                        </td>
                        <td>{when(r.observed_at)}</td>
                        <td>
                          {r.minimum == null || r.maximum == null ? "—" : `${reading(r.minimum, 1)}–${reading(r.maximum, 1)} ${filter.variable === "temperature_c" ? "°C" : ""}`}
                        </td>
                        <td>
                          {r.anomaly_percentile == null ? <span className="muted">Not ranked</span> : r.anomaly_percentile >= 95 ? <b>Top {Math.max(1, Math.round(100 - r.anomaly_percentile))}%</b> : "Typical"}
                        </td>
                        <td>
                          <button aria-pressed={selected === r.id} onClick={() => setSelected(r.id)}>
                            Show by depth
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <figure className="research-series">
                <svg
                  viewBox="0 0 700 180"
                  role="img"
                  aria-label="Observed profile extrema across UTC observation times"
                >
                  {result.items.map((r) => {
                    const values = result.items
                      .flatMap((v) => [v.minimum, v.maximum])
                      .filter((v): v is number => v !== null);
                    const lo = Math.min(...values),
                      hi = Math.max(...values);
                    const times = result.items.map((v) =>
                      Date.parse(v.observed_at),
                    );
                    const x =
                      30 +
                      ((Date.parse(r.observed_at) - Math.min(...times)) /
                        (Math.max(...times) - Math.min(...times) || 1)) *
                        640;
                    const y = (v: number) =>
                      150 - ((v - lo) / (hi - lo || 1)) * 120;
                    return r.minimum !== null && r.maximum !== null ? (
                      <g key={r.id}>
                        <title>{`${when(r.observed_at)}: ${r.minimum} to ${r.maximum} ${result.units} at ${r.latitude}, ${r.longitude}`}</title>
                        <line
                          x1={x}
                          x2={x}
                          y1={y(r.minimum)}
                          y2={y(r.maximum)}
                          stroke="#123f6b"
                          strokeWidth={3}
                        />
                        <circle cx={x} cy={y(r.minimum)} r={3} fill="#0b2341" />
                      </g>
                    ) : null;
                  })}
                </svg>
                <figcaption>
                  Time runs left to right. Each line spans one float’s lowest to highest reading in the chosen depths. Floats are in different places; nothing is smoothed between them.
                </figcaption>
              </figure>
              {selected ? <ProfilePanels key={selected} id={selected} /> : null}
            </>
          )}
          {result.next_cursor ? (
            <button
              disabled={busy}
              onClick={() => void search(result.next_cursor!)}
            >
              Load more
            </button>
          ) : null}
          <details>
            <summary>Limits of this search</summary>
            <ul>
              {result.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </details>
          <AccountGate initial={session}>
            {(account) => (
              <PrivateJobs
                account={account}
                kind="exports"
                request={{
                  scope: "research",
                  query: { ...result.query, cursor: undefined },
                }}
              />
            )}
          </AccountGate>
          <p className="footnote">
            Downloads hold one page (up to 10,000 depth readings) and carry Argo credit, quality flags and units.
          </p>
        </section>
      ) : null}
    </>
  );
}
