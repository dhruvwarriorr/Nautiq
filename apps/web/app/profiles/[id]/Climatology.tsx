import Link from "next/link";
import type { ProfileClimatology } from "../../../lib/climatology";

function format(value: number | null | undefined) {
  return value == null ? "Unavailable" : value.toFixed(3);
}
function Overlay({
  value,
  variable,
  title,
  unit,
}: {
  value: NonNullable<ProfileClimatology["result"]>;
  variable: "temperature_c" | "practical_salinity";
  title: string;
  unit: string;
}) {
  const numbers = value.rows.flatMap((row) => {
    const p = row[variable];
    return [
      p.observed,
      p.expected_mean,
      p.expected_mean == null ? null : p.expected_mean - (p.spread ?? 0),
      p.expected_mean == null ? null : p.expected_mean + (p.spread ?? 0),
    ].filter((n): n is number => n !== null);
  });
  if (!numbers.length)
    return <p>{title}: no supported reference or observed grid values.</p>;
  const minimum = Math.min(...numbers),
    span = Math.max(...numbers) - minimum || 1;
  const depth = Math.max(...value.rows.map((r) => r.depth_m));
  const x = (n: number) => 75 + ((n - minimum) / span) * 310;
  const y = (z: number) => 35 + (z / depth) * 330;
  const series = (field: "observed" | "expected_mean") => {
    const paths: string[] = [];
    let path = "",
      previous: number | null = null;
    for (const row of value.rows) {
      const n = row[variable][field];
      if (n === null || (previous !== null && row.depth_m - previous > 250)) {
        if (path) paths.push(path);
        path = "";
      }
      if (n !== null)
        path += `${path ? " L" : "M"} ${x(n).toFixed(2)} ${y(row.depth_m).toFixed(2)}`;
      previous = row.depth_m;
    }
    if (path) paths.push(path);
    return paths;
  };
  return (
    <section className="chart">
      <h3>{title}</h3>
      <svg
        viewBox="0 0 450 420"
        role="img"
        aria-label={`${title}: solid observed standard-depth values and dashed historical conditional mean; depth increases downwards`}
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <path d={`M75 ${35 + i * 82.5} H385`} stroke="#ccd8d4" />
            <text x="63" y={39 + i * 82.5} textAnchor="end" fontSize="12">
              {((depth * i) / 4).toFixed(0)}
            </text>
            <text x={75 + i * 77.5} y="395" textAnchor="middle" fontSize="12">
              {(minimum + (span * i) / 4).toFixed(1)}
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
        {value.rows.map((row) => {
          const p = row[variable];
          return p.expected_mean == null || p.spread == null ? null : (
            <path
              key={row.depth_m}
              d={`M${x(p.expected_mean - p.spread)} ${y(row.depth_m)} H${x(p.expected_mean + p.spread)}`}
              stroke="#a2a9b9"
              strokeWidth="2"
            >
              <title>{`Training residual spread ±${p.spread.toFixed(3)} ${unit}; uncalibrated`}</title>
            </path>
          );
        })}
        {series("expected_mean").map((d, i) => (
          <path
            key={`expected-${i}`}
            d={d}
            stroke="#525b91"
            strokeDasharray="6 4"
            strokeWidth="2"
            fill="none"
          />
        ))}
        {series("observed").map((d, i) => (
          <path
            key={`observed-${i}`}
            d={d}
            stroke="#236443"
            strokeWidth="2"
            fill="none"
          />
        ))}
        {value.rows.map((row) =>
          row[variable].observed == null ? null : (
            <circle
              key={row.depth_m}
              cx={x(row[variable].observed)}
              cy={y(row.depth_m)}
              r="3"
              fill="#236443"
            >
              <title>{`${row.depth_m} m observed: ${row[variable].observed} ${unit}`}</title>
            </circle>
          ),
        )}
      </svg>
      <p className="footnote">
        Solid: observed grid values. Dashed: expected mean. Bars: ±1 training
        residual RMS, with uncalibrated coverage.
      </p>
    </section>
  );
}
export default function Climatology({
  value,
  revision,
}: {
  value: ProfileClimatology | null;
  revision: string;
}) {
  if (!value || value.revision_sha256 !== revision)
    return (
      <section>
        <h2>Observed, expected, difference</h2>
        <p>
          Matching climatology evidence is unavailable. Refresh to check this
          profile revision.
        </p>
      </section>
    );
  if (!value.result || !value.calculation_id)
    return (
      <section>
        <h2>Observed, expected, difference</h2>
        <p>
          {value.status === "pending"
            ? "Reference comparison is being calculated."
            : "A supported historical reference has not been selected."}
        </p>
        <Link href="/climatology">Review historical references →</Link>
      </section>
    );
  return (
    <section>
      <h2>Observed, expected, difference</h2>
      <p>
        Compare this profile&apos;s position, observation time and standard
        depths with a fixed seasonal conditional mean. Reference fit:{" "}
        {value.fitting_period?.start_year}–{value.fitting_period?.end_year}.
        This local prototype does not establish a regional event or current
        coastal conditions.
      </p>
      <div className="evidence-links">
        <Link href={`/climatology/${value.release_id}`}>
          Reference and held-out evaluation →
        </Link>
        <Link href={`/calculations/${value.calculation_id}`}>
          Pinned comparison evidence →
        </Link>
      </div>
      <div className="charts">
        <Overlay
          value={value.result}
          variable="temperature_c"
          title="Temperature and historical normal"
          unit="°C"
        />
        <Overlay
          value={value.result}
          variable="practical_salinity"
          title="Salinity and historical normal"
          unit="PSS-78"
        />
      </div>
      <p className="footnote">
        Observed grid values use exact levels or linear interpolation through
        consecutive accepted native levels with gaps ≤250 m. Missing brackets
        and unsampled surface/bottom depths stay unavailable. Original
        observations remain in the charts above.
      </p>
      <p>{value.result.spread_interpretation}</p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Depth (m)</th>
              <th>Variable</th>
              <th>Observed</th>
              <th>Expected mean</th>
              <th>Difference</th>
              <th>Direction</th>
              <th>Spread / support</th>
            </tr>
          </thead>
          <tbody>
            {value.result.rows.flatMap((row) =>
              (["temperature_c", "practical_salinity"] as const).map(
                (variable) => {
                  const p = row[variable];
                  return (
                    <tr key={`${row.depth_m}-${variable}`}>
                      <td>{row.depth_m}</td>
                      <td>
                        {variable === "temperature_c"
                          ? "Temperature (°C)"
                          : "Salinity (PSS-78)"}
                      </td>
                      <td>
                        {format(p.observed)}
                        <small>{p.observed_reason?.replaceAll("_", " ")}</small>
                      </td>
                      <td>
                        {format(p.expected_mean)}
                        <small>{p.reason?.replaceAll("_", " ")}</small>
                      </td>
                      <td>{format(p.difference)}</td>
                      <td>{p.direction}</td>
                      <td>
                        {format(p.spread)}
                        <small>
                          {p.method_group?.replaceAll("_", " ")} ·{" "}
                          {p.training_profiles ?? 0} training profiles
                        </small>
                        {p.fallback ? (
                          <details>
                            <summary>Pooled fallback</summary>
                            {p.fallback_reasons
                              ?.join(", ")
                              .replaceAll("_", " ")}
                          </details>
                        ) : null}
                      </td>
                    </tr>
                  );
                },
              ),
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
