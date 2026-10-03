"use client";
import { useState } from "react";
import type { TripPoint, TripVerdict } from "../../lib/trips";
export default function RouteDiagram({
  points,
  verdict,
}: {
  points: TripPoint[];
  verdict?: TripVerdict | null;
}) {
  const [segment, setSegment] = useState(0);
  if (
    points.length < 2 ||
    points.some(
      (p) => !Number.isFinite(p.latitude) || !Number.isFinite(p.longitude),
    )
  )
    return null;
  const minX = Math.min(...points.map((p) => p.longitude)),
    maxX = Math.max(...points.map((p) => p.longitude)),
    minY = Math.min(...points.map((p) => p.latitude)),
    maxY = Math.max(...points.map((p) => p.latitude));
  const x = (v: number) => 45 + ((v - minX) / (maxX - minX || 0.1)) * 610;
  const y = (v: number) => 265 - ((v - minY) / (maxY - minY || 0.1)) * 220;
  return (
    <figure className="route-diagram">
      <svg
        viewBox="0 0 700 310"
        role="img"
        aria-label="Timed route schematic, with original waypoint coordinates"
      >
        <rect width={700} height={310} fill="#eef2ea" />
        {points.slice(1).map((p, i) => (
          <g key={i}>
            <title>
              Leg {i + 1}: {points[i].time} to {p.time}; status{" "}
              {verdict?.status ?? "not assessed"}
            </title>
            <line
              x1={x(points[i].longitude)}
              y1={y(points[i].latitude)}
              x2={x(p.longitude)}
              y2={y(p.latitude)}
              stroke={segment === i ? "#1c8491" : "#687976"}
              strokeWidth={segment === i ? 5 : 2}
            />
          </g>
        ))}
        {points.map((p, i) => (
          <g key={i}>
            <circle
              cx={x(p.longitude)}
              cy={y(p.latitude)}
              r={8}
              fill="#163c40"
            />
            <text x={x(p.longitude) + 12} y={y(p.latitude) + 5} fontSize={14}>
              {i + 1}
            </text>
            <title>
              {p.latitude}, {p.longitude} at {p.time}
            </title>
          </g>
        ))}
        {verdict?.worst_samples.map((w) => (
          <circle
            key={w.variable}
            cx={x(w.point.longitude)}
            cy={y(w.point.latitude)}
            r={5}
            fill="#c26e37"
          >
            <title>
              {w.variable}: {w.value} {w.units}, {w.point.time}
            </title>
          </circle>
        ))}
      </svg>
      <figcaption>
        Timed route schematic. Lines join entered waypoints; sampling follows
        the server’s great-circle method. Gray legs have no separate segment
        verdict. Orange markers show retained worst samples. This view does not
        infer safe segments.
      </figcaption>
      <label>
        Inspect leg{" "}
        <select
          value={Math.min(segment, points.length - 2)}
          onChange={(e) => setSegment(Number(e.target.value))}
        >
          {points.slice(1).map((_, i) => (
            <option key={i} value={i}>
              Leg {i + 1}
            </option>
          ))}
        </select>
      </label>
      <p>
        {points[Math.min(segment, points.length - 2)].time} →{" "}
        {points[Math.min(segment + 1, points.length - 1)].time}.{" "}
        {verdict
          ? `Overall retained status: ${verdict.status.replaceAll("_", " ")}.`
          : "Not assessed. Enter future UTC times and inspect trip evidence."}
      </p>
    </figure>
  );
}
