import Link from "next/link";
export default function Page() {
  return (
    <main className="explorer">
      <p className="eyebrow">RETAINED DIAGNOSTIC INSIGHTS</p>
      <h1>Inspect change with its support.</h1>
      <p className="intro">
        Historical diagnostics keep their event run, source window, methodology
        and confidence limitations. An empty catalog does not establish live
        event absence.
      </p>
      <div className="place-grid">
        <article>
          <h2>
            <Link href="/events">Regional events</Link>
          </h2>
          <p>Retained coherent supports and original member evidence.</p>
        </article>
        <article>
          <h2>
            <Link href="/anomalies">Profile anomaly diagnostics</Link>
          </h2>
          <p>Instrument depth residuals and diagnostic ranks.</p>
        </article>
        <article>
          <h2>
            <Link href="/research">Observation series</Link>
          </h2>
          <p>Exact observed positions, times, depths and source revisions.</p>
        </article>
      </div>
      <Link href="/methodology">Methods and approval boundaries</Link>
    </main>
  );
}
