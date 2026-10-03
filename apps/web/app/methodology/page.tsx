import Link from "next/link";
export default function Page() {
  return (
    <main className="explorer">
      <p className="eyebrow">METHODS AND LIMITATIONS</p>
      <h1>Every result keeps its evidence.</h1>
      <p className="intro">
        Nautiq distinguishes original instrument observations, native forecast
        grids, diagnostic model results and official authority bulletins.
      </p>
      <section>
        <h2>Original depth observations</h2>
        <p>
          Argo profiles keep their instrument coordinates, observation time,
          depth, QC and immutable source revision. Nearby instruments do not
          establish measurements at your chosen point. Expected-state and
          residual views apply at the original profile position and depth.
        </p>
        <Link href="/research">Inspect original observations</Link>
      </section>
      <section>
        <h2>Native surface fields</h2>
        <p>
          Each sample names the exact field release, source cycle, variable,
          units and support. Missing coverage, stale cycles and times outside
          the forecast horizon remain explicit. There is no interpolated Argo
          surface anomaly layer.
        </p>
        <Link href="/fields">Inspect field releases and methods</Link>
      </section>
      <section>
        <h2>Diagnostics and scientific approval</h2>
        <p>
          Expected profiles, anomaly ranks, intervals and event runs are
          inspectable diagnostics. Percentiles are ranks, not probabilities.
          Production scientific validation, calibrated confidence and trip
          decision thresholds remain unapproved.
        </p>
        <Link href="/models">Review model releases</Link> ·{" "}
        <Link href="/uncertainty">Review interval calibration</Link> ·{" "}
        <Link href="/events">Review historical event support</Link>
      </section>
      <section>
        <h2>Official warnings and timed trips</h2>
        <p>
          Authority content and validity remain attached to exact bulletin
          revisions. Unknown marine coverage cannot establish “no advisory”.
          Known applicable warnings take precedence. Timed routes sample outward
          and return legs; insufficient or unverified evidence remains
          insufficient. Replaying a frozen receipt does not renew its source
          freshness.
        </p>
        <Link href="/advisories">Inspect official sources</Link> ·{" "}
        <Link href="/trips">Inspect timed trip evidence</Link>
      </section>
      <section>
        <h2>Private saved state and files</h2>
        <p>
          Saved routes, watchlists, rules, reports and downloads require the
          owning session. Argo exports contain bounded original accepted levels,
          source attribution and QC. Forecast and advisory exports await
          redistribution review. Private files expire after 72 hours.
        </p>
        <Link href="/data-sources">Review source terms</Link>
      </section>
    </main>
  );
}
