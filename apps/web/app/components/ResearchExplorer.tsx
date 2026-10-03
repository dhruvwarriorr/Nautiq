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
  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <div className="field-controls">
          <label>
            Bounding box: west,south,east,north
            <input
              required
              value={bbox}
              onChange={(e) => {
                invalidate();
                setBBox(e.target.value);
              }}
            />
          </label>
          <label>
            Start (UTC ISO)
            <input
              required
              value={filter.start}
              onChange={(e) => change("start", e.target.value)}
            />
          </label>
          <label>
            End, exclusive (UTC ISO)
            <input
              required
              value={filter.end}
              onChange={(e) => change("end", e.target.value)}
            />
          </label>
          <label>
            Variable
            <select
              value={filter.variable}
              onChange={(e) =>
                change("variable", e.target.value as ResearchFilter["variable"])
              }
            >
              <option value="temperature_c">Temperature · °C</option>
              <option value="practical_salinity">
                Practical salinity · PSS-78
              </option>
            </select>
          </label>
          <label>
            Minimum depth (m)
            <input
              type="number"
              min={0}
              max={6000}
              required
              value={filter.min_depth_m}
              onInput={(e) =>
                change("min_depth_m", Number(e.currentTarget.value))
              }
            />
          </label>
          <label>
            Maximum depth (m)
            <input
              type="number"
              min={0}
              max={6000}
              required
              value={filter.max_depth_m}
              onInput={(e) =>
                change("max_depth_m", Number(e.currentTarget.value))
              }
            />
          </label>
          <label>
            Quality
            <select
              value={filter.qc}
              onChange={(e) =>
                change("qc", e.target.value as ResearchFilter["qc"])
              }
            >
              <option value="accepted">QC accepted</option>
              <option value="science_ready">Science ready</option>
            </select>
          </label>
          <label>
            Argo data mode
            <select
              value={filter.data_mode ?? ""}
              onChange={(e) => change("data_mode", e.target.value)}
            >
              <option value="">Any</option>
              {["R", "A", "D"].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>
            Page / export profile limit
            <input
              required
              type="number"
              min={1}
              max={100}
              value={filter.limit}
              onInput={(e) => change("limit", Number(e.currentTarget.value))}
            />
          </label>
          <label>
            Minimum diagnostic percentile (optional)
            <input
              type="number"
              min={0}
              max={100}
              value={percentile}
              onInput={(e) => {
                invalidate();
                setPercentile(e.currentTarget.value);
              }}
            />
          </label>
          <label>
            Exact event membership ID (optional)
            <input
              value={event}
              onChange={(e) => {
                invalidate();
                setEvent(e.target.value);
              }}
            />
          </label>
        </div>
        <label className="wide-label">
          Optional closed polygon as longitude, latitude pairs
          <textarea
            rows={3}
            value={polygon}
            onChange={(e) => {
              invalidate();
              setPolygon(e.target.value);
            }}
            placeholder="[[65,10],[66,10],[66,11],[65,10]]"
          />
        </label>
        <p>
          Source: Argo GDAC. Bounds span at most 366 days. Original instrument
          depths and positions are retained; percentile filtering applies only
          to current diagnostic calculations.
        </p>
        <button disabled={busy}>
          {busy ? "Loading original observations…" : "Search observations"}
        </button>
      </form>
      <p role="status">{error.replaceAll("_", " ")}</p>
      {result ? (
        <section>
          <h2>{result.items.length} matching profiles</h2>
          <p>
            Selection snapshot {result.snapshot_at}. {result.units}. Each row’s
            extrema use all matched original levels; charts preview up to 200
            levels per instrument.
          </p>
          {result.items.length === 0 ? (
            <p>
              No accepted observations match these bounds. Widen the area or
              dates to explore retained data.
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
                      <th>Instrument / original position</th>
                      <th>Observation time</th>
                      <th>Depth records</th>
                      <th>Minimum / maximum</th>
                      <th>Diagnostic percentile</th>
                      <th>Inspect</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.items.map((r) => (
                      <tr key={`${r.id}:${r.revision_sha256}`}>
                        <td>
                          {r.platform_id}
                          <small>
                            {r.latitude.toFixed(4)}, {r.longitude.toFixed(4)} ·{" "}
                            {r.data_mode}
                          </small>
                        </td>
                        <td>{r.observed_at}</td>
                        <td>{r.level_count}</td>
                        <td>
                          {r.minimum ?? "unknown"} / {r.maximum ?? "unknown"}
                        </td>
                        <td>
                          {r.anomaly_percentile ?? "unavailable"}
                          <small>{r.anomaly_state ?? "no diagnostic"}</small>
                        </td>
                        <td>
                          <button onClick={() => setSelected(r.id)}>
                            View depth and residuals
                          </button>
                          <small>
                            <Link href={`/profiles/${r.id}`}>
                              Original profile and QC
                            </Link>
                          </small>
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
                        <title>
                          {r.observed_at}: {r.minimum} to {r.maximum}{" "}
                          {result.units} at {r.latitude}, {r.longitude}
                        </title>
                        <line
                          x1={x}
                          x2={x}
                          y1={y(r.minimum)}
                          y2={y(r.maximum)}
                          stroke="#1c8491"
                          strokeWidth={3}
                        />
                        <circle cx={x} cy={y(r.minimum)} r={3} fill="#163c40" />
                      </g>
                    ) : null;
                  })}
                </svg>
                <figcaption>
                  UTC time runs left to right. Vertical spans show each
                  instrument’s minimum and maximum within the selected depths.
                  Instruments are at different positions; this is an observation
                  series, with no spatial interpolation. Exact values appear in
                  the table.
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
              Load next snapshot page
            </button>
          ) : null}
          <ul>
            {result.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
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
          <p>
            Export requires a query fitting one page and at most 10,000 original
            levels. Refine bounds if the server asks. Argo attribution, source
            revisions, QC and units travel with each file.
          </p>
        </section>
      ) : null}
    </>
  );
}
