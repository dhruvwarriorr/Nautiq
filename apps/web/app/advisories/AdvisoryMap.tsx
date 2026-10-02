import type { Bulletin } from "../../lib/advisories";
// A static inspection layer, with identical bulletin access in the keyboard table.
export function AdvisoryMap({ items }: { items: Bulletin[] }) {
  const shapes = items.flatMap((b) =>
    b.message.infos.flatMap((i) =>
      i.areas.flatMap((a) => a.polygons.map((p) => ({ b, p }))),
    ),
  );
  const project = ([lon, lat]: number[]) => [
    20 + (lon + 180) * 2,
    20 + (90 - lat) * 2,
  ];
  return (
    <figure className="event-map">
      <svg
        viewBox="0 0 760 400"
        role="img"
        aria-label="Official CAP polygon inspection layer. Text-only areas have no mapped geometry."
      >
        <rect
          x="20"
          y="20"
          width="720"
          height="360"
          fill="#f3f1ea"
          stroke="#bbb"
        />
        {shapes.map(({ b, p }, idx) => (
          <path
            key={`${b.message.revision_id}-${idx}`}
            d={p.coordinates
              .map(
                (r) =>
                  r
                    .map(
                      (point, i) =>
                        `${i ? "L" : "M"}${project(point).join(",")}`,
                    )
                    .join(" ") + " Z",
              )
              .join(" ")}
            fill={b.lifecycle.state === "active" ? "#b05f37" : "#999"}
            fillOpacity=".35"
            stroke="#865035"
          >
            <title>{`${b.message.sender}: ${b.message.identifier} (${b.lifecycle.state})`}</title>
          </path>
        ))}
      </svg>
      <figcaption>
        Original CAP polygons in WGS84. Circles are retained as exact geodesic
        center/radius evidence on bulletin pages. Place names and geocodes are
        not guessed into map areas.
      </figcaption>
    </figure>
  );
}
