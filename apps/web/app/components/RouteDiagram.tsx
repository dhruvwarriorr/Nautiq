"use client";
import type { TripPoint, TripVerdict } from "../../lib/trips";
import { when, label } from "../../lib/humanize";
import { landPath } from "../../lib/chart-land";
import { project } from "./HeroChart";

/** Your stops drawn on Nautiq's chart of the coast, cropped to the route with room to see the shore. */
export default function RouteDiagram({ points, verdict }: { points: TripPoint[]; verdict?: TripVerdict | null }) {
  if (points.length < 2 || points.some((p) => !Number.isFinite(p.latitude) || !Number.isFinite(p.longitude))) return null;
  const xy = points.map((p) => project(p.longitude, p.latitude));
  const xs = xy.map((p) => p[0]), ys = xy.map((p) => p[1]);
  // At least ~5° of context so the coastline is readable, kept at the frame's 7:3 aspect.
  const minSpan = 150;
  let w = Math.max(Math.max(...xs) - Math.min(...xs), minSpan) * 1.5;
  let h = Math.max(Math.max(...ys) - Math.min(...ys), minSpan * 0.43) * 1.5;
  if (w / h > 7 / 3) h = (w * 3) / 7;
  else w = (h * 7) / 3;
  const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2;
  const box = [cx - w / 2, cy - h / 2, w, h];
  const u = w / 700; // one screen pixel in chart units
  const path = xy.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join(" ");
  return (
    <figure className="route-diagram">
      <svg viewBox={box.map((v) => v.toFixed(2)).join(" ")} role="img" aria-label={`Your ${points.length} stops on a chart of the coast`}>
        <rect x={box[0]} y={box[1]} width={w} height={h} fill="#123f6b" />
        <path d={landPath} fill="#eef2f3" stroke="#8fb1cc" strokeWidth={u * 1.2} />
        <path d={path} fill="none" stroke="#eef4f8" strokeWidth={u * 2.5} strokeDasharray={`${u} ${u * 7}`} strokeLinecap="round" />
        {xy.map(([x, y], i) => (
          <g key={i} transform={`translate(${x} ${y}) scale(${u})`}>
            <title>{`Stop ${i + 1}: ${when(points[i].time)}`}</title>
            <line y1="0" y2="-20" stroke="#eef4f8" strokeWidth="1.5" />
            <circle cy="-26" r="9" fill={i === 0 ? "#0b2341" : "#eef4f8"} stroke="#eef4f8" strokeWidth="1.5" />
            <text y="-22.5" textAnchor="middle" fontSize="11" fontWeight="800" fill={i === 0 ? "#eef4f8" : "#0b2341"}>{i + 1}</text>
          </g>
        ))}
        {verdict?.worst_samples.map((s) => {
          const [x, y] = project(s.point.longitude, s.point.latitude);
          return (
            <g key={s.variable} transform={`translate(${x} ${y}) scale(${u})`}>
              <title>{`Toughest ${label(s.variable)}: ${s.value} ${s.units} at ${when(s.point.time)}`}</title>
              <path d="M0 -8 8 0 0 8 -8 0Z" fill="#ffffff" stroke="#0b2341" strokeWidth="1.5" />
            </g>
          );
        })}
      </svg>
      <figcaption>Your stops in order on a simplified coastline. White diamonds mark where conditions were toughest.</figcaption>
    </figure>
  );
}
