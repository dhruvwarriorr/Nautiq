import type { RegionalEvent } from "../../lib/events";
export default function EventMap({
  events,
  extent,
}: {
  events: RegionalEvent[];
  extent: number[];
}) {
  const width = 800,
    height = 400,
    pad = 24;
  const [west, south, east, north] = extent;
  const xy = (p: number[]) => [
    pad + ((p[0] - west) / (east - west || 1)) * (width - 2 * pad),
    height - pad - ((p[1] - south) / (north - south || 1)) * (height - 2 * pad),
  ];
  const ring = (points: number[][]) =>
    points
      .map(
        (p, i) =>
          `${i ? "L" : "M"}${xy(p)
            .map((v) => v.toFixed(2))
            .join(" ")}`,
      )
      .join(" ") + " Z";
  return (
    <figure className="event-map">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Retained event support: native SST cell footprints and observed profile points. No surface area is inferred from profile points."
      >
        <rect width={width} height={height} fill="#edf0eb" />
        {events.map((e) =>
          e.geometry.type === "MultiPoint" ? (
            (e.geometry.coordinates as number[][]).map((p, i) => (
              <circle
                key={`${e.event_id}-${i}`}
                cx={xy(p)[0]}
                cy={xy(p)[1]}
                r="5"
                fill={
                  e.kind === "isolated_profile_anomalies"
                    ? "#163c40"
                    : "#99401e"
                }
              >
                <title>{`${e.kind} · observed point ${p[1]}°, ${p[0]}°`}</title>
              </circle>
            ))
          ) : (
            <path
              key={e.event_id}
              d={(e.geometry.type === "Polygon"
                ? [e.geometry.coordinates as number[][][]]
                : (e.geometry.coordinates as number[][][][])
              )
                .flatMap((p) => p.map(ring))
                .join(" ")}
              fill="#b7672e"
              fillOpacity=".65"
              stroke="#774326"
              strokeWidth="1"
              fillRule="evenodd"
            >
              <title>{`${e.start} to ${e.end} · ${e.cell_count} native cells`}</title>
            </path>
          ),
        )}
        <text
          x="24"
          y="24"
          fill="#163c40"
          fontSize="13"
        >{`${west}° to ${east}° longitude · ${south}° to ${north}° latitude`}</text>
      </svg>
      <figcaption>
        Geographic support in the retained calculation. SST geometry contains
        native cells; profile groups contain observed points. Unobserved space
        has no inferred event coverage.
      </figcaption>
    </figure>
  );
}
