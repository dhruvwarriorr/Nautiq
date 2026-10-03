import type { Level } from "../../lib/profiles";
export default function Chart({
  levels,
  variable,
  label,
  unit,
}: {
  levels: Level[];
  variable: "temperature_c" | "practical_salinity";
  label: string;
  unit: string;
}) {
  const valid = levels.filter((p) => p[variable] !== null);
  if (!valid.length)
    return (
      <section>
        <h2>{label}</h2>
        <p>No QC accepted values for this variable.</p>
      </section>
    );
  const values = valid.map((p) => p[variable] as number),
    min = Math.min(...values),
    max = Math.max(...values),
    span = max - min || 1;
  const depth = Math.max(...levels.map((p) => p.depth_m)) || 1;
  const x = (v: number) => 75 + ((v - min) / span) * 310,
    y = (z: number) => 35 + (z / depth) * 330;
  // Break lines across missing levels and large unsampled vertical gaps.
  const paths: string[] = [];
  let path = "",
    lastDepth: number | null = null;
  for (const level of levels) {
    const value = level[variable];
    if (
      value === null ||
      (lastDepth !== null && level.depth_m - lastDepth > 250)
    ) {
      if (path) paths.push(path);
      path = "";
    }
    if (value !== null) {
      path += `${path ? " L" : "M"} ${x(value)} ${y(level.depth_m)}`;
    }
    lastDepth = level.depth_m;
  }
  if (path) paths.push(path);
  return (
    <section className="chart">
      <h2>{label}</h2>
      <svg
        viewBox="0 0 450 420"
        role="img"
        aria-label={`${label} in ${unit} plotted against depth in metres, increasing downwards`}
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <path d={`M 75 ${35 + i * 82.5} H 385`} stroke="#ccd8d4" />
            <text x="63" y={39 + i * 82.5} textAnchor="end" fontSize="12">
              {((depth * i) / 4).toFixed(0)}
            </text>
            <text x={75 + i * 77.5} y="395" textAnchor="middle" fontSize="12">
              {(min + (span * i) / 4).toFixed(1)}
            </text>
          </g>
        ))}
        <text x="230" y="418" textAnchor="middle" fontSize="12">
          {unit}
        </text>
        <text
          x="18"
          y="200"
          transform="rotate(-90 18 200)"
          textAnchor="middle"
          fontSize="12"
        >
          Depth (m)
        </text>
        {paths.map((d, i) => (
          <path key={i} d={d} fill="none" stroke="#236443" strokeWidth="2" />
        ))}
        {valid.map((p, i) => (
          <circle
            key={i}
            cx={x(p[variable] as number)}
            cy={y(p.depth_m)}
            r="2"
            fill="#163c40"
          >
            <title>
              {p.depth_m.toFixed(2)} m: {p[variable]} {unit}
            </title>
          </circle>
        ))}
      </svg>
    </section>
  );
}
