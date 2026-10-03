"use client";
import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { publicQuery, type QueryPlan } from "../../lib/product";
import ResearchExplorer from "../components/ResearchExplorer";
export default function Query() {
  const [text, setText] = useState("");
  const [zone, setZone] = useState("UTC");
  const [plan, setPlan] = useState<QueryPlan | null>(null);
  const [execute, setExecute] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const control = useRef<AbortController | null>(null);
  useEffect(() => () => control.current?.abort(), []);
  function clear() {
    control.current?.abort();
    setPlan(null);
    setExecute(false);
    setError("");
    setBusy(false);
  }
  async function parse() {
    clear();
    const c = new AbortController();
    control.current = c;
    setBusy(true);
    try {
      const data = await publicQuery<{ plan: QueryPlan }>(
        "query",
        { text, time_zone: zone },
        c.signal,
      );
      if (!c.signal.aborted) setPlan(data.plan);
    } catch (e) {
      if (!c.signal.aborted)
        setError(e instanceof Error ? e.message : "query_unavailable");
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void parse();
        }}
      >
        <label className="wide-label">
          Describe the evidence you want
          <textarea
            required
            maxLength={512}
            rows={4}
            value={text}
            onChange={(e) => {
              clear();
              setText(e.target.value);
            }}
          />
        </label>
        <div className="field-controls">
          <label>
            Time zone (IANA)
            <input
              required
              value={zone}
              onChange={(e) => {
                clear();
                setZone(e.target.value);
              }}
            />
          </label>
          <button disabled={busy}>
            {busy ? "Preparing typed query…" : "Preview query"}
          </button>
        </div>
      </form>
      <p>
        Supported: named location conditions, retained events, or temperature /
        salinity profiles for a named region and two explicit dates. For
        example: “temperature profiles in Arabian Sea from 2026-09-01 to
        2026-10-01”. Relative times and unnamed places require clarification.
        Questions stay in this tab’s memory.
      </p>
      <p role="status">{error.replaceAll("_", " ")}</p>
      {plan ? (
        <section>
          <h2>
            {plan.intent.replaceAll("_", " ")} · {plan.state}
          </h2>
          <p>{plan.explanation}</p>
          <ul>
            {plan.clarifications.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          {plan.state === "ready" ? (
            plan.research ? (
              <>
                <details>
                  <summary>Typed query preview</summary>
                  <pre className="audit-json">
                    {JSON.stringify(plan.research, null, 2)}
                  </pre>
                </details>
                <button onClick={() => setExecute(true)}>
                  Open validated research query
                </button>
                {execute ? (
                  <ResearchExplorer
                    key={JSON.stringify(plan.research)}
                    initial={plan.research}
                  />
                ) : null}
              </>
            ) : plan.place ? (
              <Link className="button" href={`/locations/${plan.place.slug}`}>
                Inspect {plan.place.name} evidence
              </Link>
            ) : plan.intent === "events" ? (
              <Link className="button" href="/events">
                Inspect retained event runs
              </Link>
            ) : null
          ) : null}
          {plan.intent.includes("trip") ? (
            <Link href="/trips">Enter actual timed waypoints</Link>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
