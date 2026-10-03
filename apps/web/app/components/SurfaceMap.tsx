"use client";
import { useState } from "react";
import Link from "next/link";
import FieldViewer, { type MapOverlay } from "../fields/FieldViewer";
import type { MapOverview } from "../../lib/product";
function geometry(value: { type: string; coordinates: unknown } | null): {
  paths: number[][][];
  points: number[][];
} {
  if (!value || !Array.isArray(value.coordinates))
    return { paths: [], points: [] };
  let paths: number[][][] = [],
    points: number[][] = [];
  if (value.type === "Polygon") paths = value.coordinates as number[][][];
  if (value.type === "MultiPolygon")
    paths = (value.coordinates as number[][][][]).flat();
  if (value.type === "MultiPoint") points = value.coordinates as number[][];
  const valid = (p: number[]) =>
    Array.isArray(p) &&
    p.length === 2 &&
    p.every(Number.isFinite) &&
    Math.abs(p[0]) <= 180 &&
    Math.abs(p[1]) <= 85;
  if (!paths.every(Array.isArray) || !Array.isArray(points))
    return { paths: [], points: [] };
  const count = points.length + paths.reduce((n, p) => n + p.length, 0);
  if (
    count > 8192 ||
    !points.every(valid) ||
    !paths.every(
      (p) =>
        p.every(valid) &&
        p.every((v, i) => i === 0 || Math.abs(v[0] - p[i - 1][0]) <= 180),
    )
  )
    return { paths: [], points: [] };
  return { paths, points };
}
export default function SurfaceMap({ value }: { value: MapOverview }) {
  const [release, setRelease] = useState(value.fields[0]?.release_id ?? "");
  const [showProfiles, setProfiles] = useState(true);
  const [showEvents, setEvents] = useState(true);
  const [showAdvisories, setAdvisories] = useState(true);
  const selected = value.fields.find((v) => v.release_id === release);
  const overlays: MapOverlay[] = [];
  if (showProfiles)
    for (const p of value.profiles)
      overlays.push({
        id: p.id,
        kind: "profile",
        label: `Argo ${p.platform_id} · ${p.observed_at}`,
        href: `/profiles/${p.id}`,
        points: [[p.longitude, p.latitude]],
        paths: [],
      });
  if (showEvents)
    for (const e of value.events)
      overlays.push({
        id: e.event_id,
        kind: "event",
        label: `${e.kind.replaceAll("_", " ")} · ${e.start} to ${e.end}`,
        href: `/events/${e.event_id}`,
        ...geometry(e.geometry),
      });
  if (showAdvisories)
    for (const [i, p] of value.advisory_polygons.entries())
      overlays.push({
        id: `${p.revision_id}-${i}`,
        kind: "advisory",
        label: `Official ${p.event} · ${p.severity} · ${p.effective} to ${p.expires ?? "unknown expiry"}`,
        href: `/advisories/${p.revision_id}`,
        ...geometry(p.geometry),
      });
  if (showAdvisories)
    for (const [i, c] of (value.advisory_circles ?? []).entries()) {
      if (
        c.circle.center.length !== 2 ||
        !c.circle.center.every(Number.isFinite) ||
        !Number.isFinite(c.circle.radius_km)
      )
        continue;
      const [lon, lat] = c.circle.center.map((v) => (v * Math.PI) / 180);
      const d = c.circle.radius_km / 6371;
      const ring = Array.from({ length: 49 }, (_, i) => {
        const b = (i / 48) * 2 * Math.PI;
        const y = Math.asin(
          Math.sin(lat) * Math.cos(d) +
            Math.cos(lat) * Math.sin(d) * Math.cos(b),
        );
        const x =
          lon +
          Math.atan2(
            Math.sin(b) * Math.sin(d) * Math.cos(lat),
            Math.cos(d) - Math.sin(lat) * Math.sin(y),
          );
        return [(((x * 180) / Math.PI + 540) % 360) - 180, (y * 180) / Math.PI];
      });
      overlays.push({
        id: `circle-${c.revision_id}-${i}`,
        kind: "advisory",
        label: `Official ${c.event} circle · ${c.circle.radius_km} km radius (48-segment display)`,
        href: `/advisories/${c.revision_id}`,
        ...geometry({ type: "Polygon", coordinates: [ring] }),
      });
    }
  return (
    <>
      <div className="field-controls">
        <label>
          Native field layer
          <select value={release} onChange={(e) => setRelease(e.target.value)}>
            {value.fields.map((f) => (
              <option key={f.release_id} value={f.release_id}>
                {f.metadata.product} · {f.freshness}
              </option>
            ))}
          </select>
        </label>
      </div>
      <fieldset className="layer-controls">
        <legend>Evidence overlays</legend>
        <label>
          <input
            type="checkbox"
            checked={showProfiles}
            onChange={(e) => setProfiles(e.target.checked)}
          />{" "}
          Accepted profiles ({value.profiles.length})
        </label>
        <label>
          <input
            type="checkbox"
            checked={showEvents}
            onChange={(e) => setEvents(e.target.checked)}
          />{" "}
          Historical event candidates ({value.events.length})
        </label>
        <label>
          <input
            type="checkbox"
            checked={showAdvisories}
            onChange={(e) => setAdvisories(e.target.checked)}
          />{" "}
          Official geometries (
          {value.advisory_polygons.length +
            (value.advisory_circles?.length ?? 0)}
          )
        </label>
      </fieldset>
      <p>
        Vector window {value.start} to {value.end}. Field valid times are
        selected separately below. Advisory coverage remains{" "}
        <strong>{value.advisory_state}</strong>; event support is{" "}
        {value.event_state.replaceAll("_", " ")}.
      </p>
      {selected ? (
        <>
          <p>
            Retained release{" "}
            <Link href={`/fields/${selected.release_id}`}>
              {selected.release_id}
            </Link>{" "}
            · {selected.freshness} · no operational approval.
          </p>
          <FieldViewer
            key={selected.release_id}
            releaseId={selected.release_id}
            metadata={selected.metadata}
            overlays={overlays}
          />
        </>
      ) : (
        <p className="notice">
          No native field release is available. The observation table and
          original evidence links remain usable.
        </p>
      )}
      <details>
        <summary>Layer coverage and limitations</summary>
        <ul>
          {value.unavailable_layers.map((v) => (
            <li key={v}>{v.replaceAll("_", " ")}: unavailable.</li>
          ))}
          {value.limitations.map((v) => (
            <li key={v}>{v}</li>
          ))}
        </ul>
        {value.advisory_sources?.map((s) => (
          <p key={s.source_id}>
            {s.source_id}: transport {s.transport}; marine coverage {s.coverage}
            .
          </p>
        ))}
      </details>
      <h2>Mapped observations</h2>
      <p>
        Instrument positions and observed times. An empty filtered view does not
        establish an absence of unusual conditions.
      </p>
      <div
        className="table-scroll"
        role="region"
        aria-label="Mapped observation evidence"
        tabIndex={0}
      >
        <table>
          <thead>
            <tr>
              <th>Profile</th>
              <th>Position</th>
              <th>Observed (UTC)</th>
              <th>Revision</th>
            </tr>
          </thead>
          <tbody>
            {value.profiles.map((p) => (
              <tr key={p.id}>
                <td>
                  <Link href={`/profiles/${p.id}`}>Argo {p.platform_id}</Link>
                </td>
                <td>
                  {p.latitude.toFixed(3)}, {p.longitude.toFixed(3)}
                </td>
                <td>{p.observed_at}</td>
                <td className="digest">{p.revision_sha256.slice(0, 12)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>Event and advisory geometry</h2>
      <ul>
        {value.events.map((e) => (
          <li key={e.event_id}>
            <Link href={`/events/${e.event_id}`}>
              {e.kind.replaceAll("_", " ")} · {e.start} to {e.end}
            </Link>
          </li>
        ))}
        {value.advisory_polygons.map((p, i) => (
          <li key={`${p.revision_id}-${i}`}>
            <Link href={`/advisories/${p.revision_id}`}>
              Official {p.event} · {p.severity} · expires{" "}
              {p.expires ?? "unknown"}
            </Link>
          </li>
        ))}
      </ul>
      <Link href="/advisories">
        Review circle originals, text-only and unresolved official areas →
      </Link>
    </>
  );
}
